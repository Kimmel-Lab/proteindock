#!/usr/bin/env python3
"""
boltz_predictor.py — Multi-seed Boltz-1 wrapper for PPI prediction.

Given a receptor sequence + binder sequence (and optional chains), runs
Boltz-1 N times with different seeds, ranks by ipTM (interface pTM), and
returns the best predicted complex.

Use cases:
  - Generate a starting structure for Rosetta refinement (paper 2 main loop)
  - Generate a baseline "Boltz-alone" prediction for comparison
  - Generate an ensemble of starting points (top-K by ipTM) for diversity

Usage as library:
  from backend.boltz_predictor import predict_complex
  result = predict_complex(rec_seq, bind_seq, n_seeds=25, output_dir=Path("..."))
  # result["best_pdb"] = path to highest-ipTM model
  # result["all"] = list of (seed, pdb_path, iptm, ptm, plddt) sorted by ipTM

Usage as CLI:
  python boltz_predictor.py --rec REC.fasta --bind BIND.fasta \
                             --n-seeds 25 --out outdir/

Notes:
  - Boltz-1 weights download to ~/.boltz/ on first run (~2 GB).
  - GPU strongly recommended; runs on CPU but very slow.
  - Each seed takes 1-5 min on H100, longer on V100.
"""

from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _find_boltz_venv() -> Path:
    """Locate the cluster-appropriate Boltz venv."""
    import socket
    host = socket.gethostname().lower()
    base = Path("/fs/scratch/PAS2959/proteindock/protein_web")
    if host.startswith(("pitzer", "p")):
        return base / "venv-boltz-pitzer"
    if host.startswith(("cardinal", "c")):
        return base / "venv-boltz-cardinal"
    # Fallback: try whichever exists
    for cand in ("venv-boltz-pitzer", "venv-boltz-cardinal"):
        if (base / cand).exists():
            return base / cand
    raise RuntimeError("No Boltz venv found at /fs/scratch/PAS2959/proteindock/")


def _build_yaml(rec_seq: str, bind_seq: str, name: str, out_yaml: Path,
                rec_chain: str = "A", bind_chain: str = "B") -> None:
    """Write a Boltz YAML input describing a 2-chain complex."""
    content = f"""version: 1
sequences:
  - protein:
      id: {rec_chain}
      sequence: {rec_seq}
  - protein:
      id: {bind_chain}
      sequence: {bind_seq}
"""
    out_yaml.write_text(content)


def _parse_ranking(boltz_out_dir: Path) -> list[dict]:
    """
    Parse Boltz output directory for ipTM/pTM scores.

    Boltz writes: <out_dir>/predictions/<input_name>/
                    <input_name>_model_<rank>.cif
                    confidence_<input_name>_model_<rank>.json   (has iptm, ptm, plddt)
    """
    pred_dir = next(boltz_out_dir.glob("predictions/*"), None)
    if pred_dir is None:
        return []
    results = []
    for cif_path in sorted(pred_dir.glob("*_model_*.cif")):
        m = re.search(r"_model_(\d+)\.cif$", cif_path.name)
        if not m:
            continue
        rank = int(m.group(1))
        conf_path = pred_dir / f"confidence_{cif_path.stem}.json"
        conf = {}
        if conf_path.exists():
            try:
                conf = json.loads(conf_path.read_text())
            except Exception:
                pass
        results.append({
            "rank": rank,
            "cif_path": str(cif_path),
            "iptm": conf.get("iptm"),
            "ptm": conf.get("ptm"),
            "plddt": conf.get("complex_plddt") or conf.get("plddt"),
            "confidence": conf.get("confidence_score"),
        })
    return results


def _cif_to_pdb(cif_path: Path, pdb_path: Path) -> Path:
    """Convert mmCIF to PDB via BioPython (fall back to gemmi if available)."""
    try:
        from Bio.PDB import MMCIFParser, PDBIO
        parser = MMCIFParser(QUIET=True)
        structure = parser.get_structure("model", str(cif_path))
        io = PDBIO()
        io.set_structure(structure)
        io.save(str(pdb_path))
        return pdb_path
    except Exception as e:
        # Try gemmi if installed
        try:
            import gemmi
            st = gemmi.read_structure(str(cif_path))
            st.write_pdb(str(pdb_path))
            return pdb_path
        except Exception:
            raise RuntimeError(f"Failed to convert {cif_path} to PDB: {e}")


def predict_complex(
    rec_seq: str,
    bind_seq: str,
    output_dir: Path,
    n_seeds: int = 25,
    name: str = "complex",
    rec_chain: str = "A",
    bind_chain: str = "B",
    boltz_venv: Path | None = None,
    diffusion_samples: int = 1,
) -> dict:
    """
    Run Boltz-1 with `n_seeds` random seeds, rank by ipTM.

    Returns dict:
      {
        "best_pdb": Path,           # path to top-ipTM model (PDB format)
        "best_iptm": float,
        "all": [{seed, cif, pdb, iptm, ptm, plddt}, ...] sorted by ipTM desc,
        "n_predictions": int,
      }
    """
    if boltz_venv is None:
        boltz_venv = _find_boltz_venv()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    boltz_bin = boltz_venv / "bin" / "boltz"
    if not boltz_bin.exists():
        raise FileNotFoundError(f"Boltz binary not found at {boltz_bin}. Run install_boltz1.sh first.")

    # Build YAML input
    yaml_path = output_dir / f"{name}.yaml"
    _build_yaml(rec_seq, bind_seq, name, yaml_path, rec_chain, bind_chain)

    all_predictions = []
    for seed in range(n_seeds):
        seed_dir = output_dir / f"seed_{seed:03d}"
        seed_dir.mkdir(exist_ok=True)
        cmd = [
            str(boltz_bin), "predict", str(yaml_path),
            "--out_dir", str(seed_dir),
            "--seed", str(seed),
            "--diffusion_samples", str(diffusion_samples),
            "--use_msa_server",  # Boltz uses ColabFold MSA server (no local databases needed)
            "--output_format", "mmcif",
        ]
        log_path = seed_dir / "boltz.log"
        with open(log_path, "w") as log:
            result = subprocess.run(cmd, stdout=log, stderr=log)
        if result.returncode != 0:
            print(f"  Seed {seed}: failed (see {log_path})", file=sys.stderr)
            continue

        ranked = _parse_ranking(seed_dir)
        for r in ranked:
            r["seed"] = seed
            # Convert top model to PDB for downstream Rosetta use
            cif = Path(r["cif_path"])
            pdb = cif.with_suffix(".pdb")
            try:
                _cif_to_pdb(cif, pdb)
                r["pdb_path"] = str(pdb)
            except Exception as e:
                r["pdb_path"] = None
                r["convert_error"] = str(e)
            all_predictions.append(r)

    # Sort by ipTM descending (handle None as -inf)
    all_predictions.sort(key=lambda x: -(x.get("iptm") or -1))

    if not all_predictions:
        raise RuntimeError("Boltz produced no successful predictions")

    best = all_predictions[0]
    return {
        "best_pdb": best.get("pdb_path"),
        "best_iptm": best.get("iptm"),
        "best_ptm": best.get("ptm"),
        "best_plddt": best.get("plddt"),
        "n_predictions": len(all_predictions),
        "all": all_predictions,
        "yaml_path": str(yaml_path),
    }


def _read_fasta(fasta: Path) -> tuple[str, str]:
    """Return (header, sequence). Reads first record only."""
    header, seq = "", ""
    for line in fasta.read_text().splitlines():
        if line.startswith(">"):
            if seq:
                break
            header = line[1:].strip()
        else:
            seq += line.strip()
    return header, seq


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rec", required=True, help="Receptor FASTA (1 record)")
    p.add_argument("--bind", required=True, help="Binder FASTA (1 record)")
    p.add_argument("--out", required=True, help="Output dir")
    p.add_argument("--n-seeds", type=int, default=25)
    p.add_argument("--name", default="complex")
    p.add_argument("--rec-chain", default="A")
    p.add_argument("--bind-chain", default="B")
    p.add_argument("--diffusion-samples", type=int, default=1)
    args = p.parse_args()

    _, rec_seq = _read_fasta(Path(args.rec))
    _, bind_seq = _read_fasta(Path(args.bind))

    print(f"Receptor ({len(rec_seq)} aa): {rec_seq[:50]}...")
    print(f"Binder   ({len(bind_seq)} aa): {bind_seq[:50]}...")
    print(f"Running Boltz-1 with {args.n_seeds} seeds → {args.out}")

    result = predict_complex(
        rec_seq, bind_seq, Path(args.out),
        n_seeds=args.n_seeds, name=args.name,
        rec_chain=args.rec_chain, bind_chain=args.bind_chain,
        diffusion_samples=args.diffusion_samples,
    )

    summary = Path(args.out) / "boltz_summary.json"
    summary.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nBest model: {result['best_pdb']}")
    print(f"  ipTM={result['best_iptm']}  pTM={result['best_ptm']}  pLDDT={result['best_plddt']}")
    print(f"  Total successful predictions: {result['n_predictions']}")
    print(f"  Summary: {summary}")


if __name__ == "__main__":
    main()
