#!/usr/bin/env python3
"""
af3_predictor.py — AlphaFold 3 wrapper for PPI starting structures.

Mirrors boltz_predictor.py but uses DeepMind's AlphaFold 3.

Setup expectations:
  - AF3 installed at /fs/scratch/PAS2959/proteindock/conda-af3-cardinal/envs/af3
  - Weights at /fs/scratch/PAS2959/proteindock/af3/af3.bin
  - alphafold3 repo at /fs/scratch/PAS2959/proteindock/af3/alphafold3
  - Run via `run_alphafold.py` from the repo

Inputs: receptor sequence + binder sequence + name
Outputs: best top-ranked CIF/PDB by AF3 confidence

Usage as library:
  from backend.af3_predictor import predict_complex
  result = predict_complex(rec_seq, bind_seq, n_seeds=5, output_dir=Path('...'))
  # result["best_pdb"] = path to highest-confidence model (converted to PDB)

Usage as CLI:
  python af3_predictor.py --rec REC.fasta --bind BIND.fasta --out outdir/
"""

from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

AF3_DIR = Path("/fs/scratch/PAS2959/proteindock/af3")
AF3_REPO = AF3_DIR / "alphafold3"
AF3_WEIGHTS = AF3_DIR / "af3.bin"
AF3_VENV = Path("/fs/scratch/PAS2959/proteindock/conda-af3-cardinal/envs/af3")
AF3_DATABASES = AF3_DIR / "databases"  # populated by fetch_databases.sh


def _build_af3_input_json(rec_seq: str, bind_seq: str, name: str,
                          rec_chain: str = "A", bind_chain: str = "B") -> dict:
    """Construct AF3 JSON input for a 2-chain protein-protein complex."""
    return {
        "name": name,
        "sequences": [
            {"protein": {"id": rec_chain, "sequence": rec_seq}},
            {"protein": {"id": bind_chain, "sequence": bind_seq}},
        ],
        "modelSeeds": [1, 2, 3, 4, 5],  # default: 5 seeds
        "dialect": "alphafold3",
        "version": 1,
    }


def _cif_to_pdb(cif_path: Path, pdb_path: Path) -> Path:
    """Convert mmCIF to PDB via BioPython."""
    try:
        from Bio.PDB import MMCIFParser, PDBIO
        parser = MMCIFParser(QUIET=True)
        structure = parser.get_structure("model", str(cif_path))
        io = PDBIO()
        io.set_structure(structure)
        io.save(str(pdb_path))
        return pdb_path
    except Exception as e:
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
    n_seeds: int = 5,
    name: str = "complex",
    rec_chain: str = "A",
    bind_chain: str = "B",
    af3_venv: Path | None = None,
    af3_repo: Path | None = None,
    weights_dir: Path | None = None,
    databases_dir: Path | None = None,
) -> dict:
    """
    Run AlphaFold 3 with `n_seeds` seeds, rank by confidence.

    Returns dict:
      {
        "best_pdb": Path,
        "best_confidence": float,
        "all": [{seed, cif, pdb, confidence, iptm, ptm, plddt}, ...],
        "n_predictions": int,
      }
    """
    if af3_venv is None:
        af3_venv = AF3_VENV
    if af3_repo is None:
        af3_repo = AF3_REPO
    if weights_dir is None:
        weights_dir = AF3_DIR
    if databases_dir is None:
        databases_dir = AF3_DATABASES

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build input JSON with N seeds
    input_json = _build_af3_input_json(rec_seq, bind_seq, name, rec_chain, bind_chain)
    input_json["modelSeeds"] = list(range(n_seeds))
    json_path = output_dir / f"{name}_input.json"
    json_path.write_text(json.dumps(input_json, indent=2))

    # Build run_alphafold command
    run_script = af3_repo / "run_alphafold.py"
    if not run_script.exists():
        raise FileNotFoundError(f"AF3 run script not found at {run_script}")

    af3_out = output_dir / "af3_output"
    af3_out.mkdir(exist_ok=True)

    py = af3_venv / "bin" / "python"
    cmd = [
        str(py), str(run_script),
        "--json_path", str(json_path),
        "--output_dir", str(af3_out),
        "--model_dir", str(weights_dir),
        "--db_dir", str(databases_dir),
        "--run_inference=true",
        "--run_data_pipeline=true",
    ]

    log_path = output_dir / "af3.log"
    with open(log_path, "w") as log:
        result = subprocess.run(cmd, stdout=log, stderr=log)

    if result.returncode != 0:
        raise RuntimeError(f"AF3 failed (exit {result.returncode}); see {log_path}")

    # Parse outputs: AF3 writes <output_dir>/<name>/<name>_summary_confidences.json
    # and CIF files per seed.
    pred_dir = af3_out / name
    if not pred_dir.exists():
        # AF3 sometimes lowercases the name
        candidates = list(af3_out.glob("*"))
        if not candidates:
            raise RuntimeError(f"AF3 produced no output dirs in {af3_out}")
        pred_dir = candidates[0]

    summary_json = pred_dir / f"{name}_summary_confidences.json"
    if not summary_json.exists():
        # Try alternative names
        candidates = list(pred_dir.glob("*summary*.json"))
        if candidates:
            summary_json = candidates[0]

    confidences = {}
    if summary_json.exists():
        confidences = json.loads(summary_json.read_text())

    # Walk each seed's CIF + per-seed confidence
    all_predictions = []
    for cif_path in sorted(pred_dir.glob("*model_*.cif")):
        m = re.search(r"model_(\d+)\.cif$", cif_path.name)
        if not m:
            continue
        seed_idx = int(m.group(1))
        pdb_path = cif_path.with_suffix(".pdb")
        try:
            _cif_to_pdb(cif_path, pdb_path)
        except Exception as e:
            pdb_path = None

        # Per-seed confidence JSON (AF3 writes one per seed)
        seed_conf_json = pred_dir / f"{name}_confidences_{seed_idx}.json"
        seed_conf = {}
        if seed_conf_json.exists():
            try:
                seed_conf = json.loads(seed_conf_json.read_text())
            except Exception:
                pass

        all_predictions.append({
            "seed": seed_idx,
            "cif_path": str(cif_path),
            "pdb_path": str(pdb_path) if pdb_path else None,
            "iptm": seed_conf.get("iptm"),
            "ptm": seed_conf.get("ptm"),
            "plddt": seed_conf.get("complex_plddt") or seed_conf.get("plddt"),
            "confidence": seed_conf.get("confidence_score") or seed_conf.get("ranking_confidence"),
        })

    # Rank by confidence descending (handle None)
    all_predictions.sort(key=lambda x: -(x.get("confidence") or x.get("iptm") or -1))

    if not all_predictions:
        raise RuntimeError(f"AF3 produced no parseable predictions in {pred_dir}")

    best = all_predictions[0]
    return {
        "best_pdb": best.get("pdb_path"),
        "best_confidence": best.get("confidence"),
        "best_iptm": best.get("iptm"),
        "best_ptm": best.get("ptm"),
        "best_plddt": best.get("plddt"),
        "n_predictions": len(all_predictions),
        "all": all_predictions,
        "input_json": str(json_path),
    }


def _read_fasta(fasta: Path) -> tuple[str, str]:
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
    p.add_argument("--rec", required=True, help="Receptor FASTA")
    p.add_argument("--bind", required=True, help="Binder FASTA")
    p.add_argument("--out", required=True, help="Output dir")
    p.add_argument("--n-seeds", type=int, default=5)
    p.add_argument("--name", default="complex")
    p.add_argument("--rec-chain", default="A")
    p.add_argument("--bind-chain", default="B")
    args = p.parse_args()

    _, rec_seq = _read_fasta(Path(args.rec))
    _, bind_seq = _read_fasta(Path(args.bind))

    print(f"Receptor ({len(rec_seq)}aa): {rec_seq[:50]}...")
    print(f"Binder   ({len(bind_seq)}aa): {bind_seq[:50]}...")
    print(f"Running AF3 with {args.n_seeds} seeds → {args.out}")

    result = predict_complex(
        rec_seq, bind_seq, Path(args.out),
        n_seeds=args.n_seeds, name=args.name,
        rec_chain=args.rec_chain, bind_chain=args.bind_chain,
    )

    summary = Path(args.out) / "af3_summary.json"
    summary.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nBest model: {result['best_pdb']}")
    print(f"  confidence={result['best_confidence']}  ipTM={result['best_iptm']}  pTM={result['best_ptm']}")
    print(f"  Total predictions: {result['n_predictions']}")


if __name__ == "__main__":
    main()
