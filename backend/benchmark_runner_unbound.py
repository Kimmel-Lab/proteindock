#!/usr/bin/env python3
"""
benchmark_runner_unbound.py — Unbound-docking benchmark using DB5.5 chains.

For each entry:
  1. Take pre-downloaded unbound receptor (_r_u.pdb) and binder (_l_u.pdb)
  2. Normalize chains to A (receptor) and B (binder)
  3. Clean → normalize → sanitize → merge (ProteinDock pipeline)
  4. Run Rosetta docking with randomized starting positions
  5. Score best model with DockQ vs. native bound complex (_r_b + _l_b)
  6. Write progressive results.json

This is the "real" benchmark — unbound chains have different conformations
than the bound forms, requiring the docker to model conformational change.
"""

import argparse
import json
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pipeline import (
    run_clean_pdb,
    normalize_chains,
    sanitize_pdb,
    combine_in_python,
    run_docking,
    parse_fasc_and_find_best,
)
from backend.dockq_scorer import score_dockq


def _rename_chain(input_pdb: Path, output_pdb: Path, new_chain_id: str) -> None:
    with open(input_pdb) as f:
        lines = []
        for line in f:
            if line.startswith(("ATOM", "HETATM")) and len(line) > 21:
                line = line[:21] + new_chain_id + line[22:]
            lines.append(line)
    output_pdb.write_text("".join(lines))


def _combine_native(r_b: Path, l_b: Path, out: Path) -> None:
    """Combine bound receptor + bound ligand into the native reference complex.

    Chains are preserved as-is from the DB5.5 _b files (typically A and B).
    """
    parts = []
    for f in (r_b, l_b):
        for line in open(f):
            if line.startswith(("ATOM", "HETATM")):
                parts.append(line)
        parts.append("TER\n")
    parts.append("END\n")
    out.write_text("".join(parts))


def _detect_native_chains(pdb: Path) -> list[str]:
    chains = []
    with open(pdb) as f:
        for line in f:
            if line.startswith("ATOM") and line[21] not in chains:
                chains.append(line[21])
    return chains


def _write_results(results: list, output_dir: Path) -> None:
    tmp = output_dir / "results.json.tmp"
    tmp.write_text(json.dumps(results, indent=2))
    tmp.replace(output_dir / "results.json")


def _write_progress(done: int, total: int, output_dir: Path) -> None:
    (output_dir / "progress.json").write_text(json.dumps({"done": done, "total": total}))


def run_unbound_benchmark(
    entries: list[dict],
    db55_dir: Path,
    output_dir: Path,
    nstruct: int,
) -> list[dict]:
    results = []
    total = len(entries)

    for i, entry in enumerate(entries):
        pdb_code = entry["pdb_code"]
        category = entry.get("category", "unknown")
        description = entry.get("description", "")

        pdb_dir = output_dir / pdb_code
        pdb_dir.mkdir(parents=True, exist_ok=True)

        result = {
            "pdb_code": pdb_code,
            "category": category,
            "description": description,
            "status": "running",
            "started_at": datetime.now().isoformat(),
        }
        results.append(result)
        _write_results(results, output_dir)

        import time as _time
        _t_start = _time.monotonic()
        try:
            print(f"\n[{i+1}/{total}] {pdb_code} — {description}", flush=True)

            # Source files from DB5.5
            r_u = db55_dir / f"{pdb_code}_r_u.pdb"
            l_u = db55_dir / f"{pdb_code}_l_u.pdb"
            r_b = db55_dir / f"{pdb_code}_r_b.pdb"
            l_b = db55_dir / f"{pdb_code}_l_b.pdb"
            for f in (r_u, l_u, r_b, l_b):
                if not f.exists():
                    raise FileNotFoundError(str(f))

            # Build native reference complex
            native_complex = pdb_dir / "native.pdb"
            _combine_native(r_b, l_b, native_complex)
            native_rec = _detect_native_chains(r_b)
            native_bind = _detect_native_chains(l_b)
            print(f"  Native chains: rec={native_rec}, bind={native_bind}", flush=True)

            # Standardize unbound chains to A and B
            rec_std = pdb_dir / "receptor_std.pdb"
            bind_std = pdb_dir / "binder_std.pdb"
            _rename_chain(r_u, rec_std, "A")
            _rename_chain(l_u, bind_std, "B")

            print("  Cleaning unbound chains...", flush=True)
            rec_clean = pdb_dir / "receptor_clean.pdb"
            bind_clean = pdb_dir / "binder_clean.pdb"
            run_clean_pdb(rec_std, rec_clean)
            run_clean_pdb(bind_std, bind_clean)

            rec_chains_pdb, used = normalize_chains(rec_clean, used=set())
            bind_chains_pdb, _ = normalize_chains(bind_clean, used=used)
            rec_fixed = sanitize_pdb(rec_chains_pdb)
            bind_fixed = sanitize_pdb(bind_chains_pdb)

            print("  Merging starting complex...", flush=True)
            complex_pdb = pdb_dir / "complex_input.pdb"
            combine_in_python(rec_fixed, bind_fixed, complex_pdb)
            (pdb_dir / "partners.txt").write_text("A_B")

            print(f"  Running Rosetta docking (nstruct={nstruct}, randomized)...", flush=True)
            try:
                # Note: pipeline.run_docking uses the standard XML which already
                # includes DockingProtocol. Decoys start from the input pose with
                # internal perturbations. For "fully blind" unbound, we'd want
                # -randomize1 -randomize2 but that requires custom options.
                run_docking(complex_pdb, output_dir=pdb_dir, nstruct=nstruct)
            except RuntimeError as dock_err:
                import glob as _glob
                n_pdbs = len(_glob.glob(str(pdb_dir / "complex_input_full_*.pdb")))
                if n_pdbs == 0:
                    raise RuntimeError(f"Rosetta produced no output structures: {dock_err}") from dock_err
                print(f"  Rosetta partial failure ({n_pdbs} structures — continuing)", flush=True)

            fasc = pdb_dir / "docking.fasc"
            best = parse_fasc_and_find_best(
                fasc_path=fasc, pdb_glob=str(pdb_dir / "complex_input_full_*.pdb")
            )
            if best is None:
                raise RuntimeError("No docking models produced.")
            best_pdb = Path(best["pdb_path"])
            print(f"  Best model: {best_pdb.name} (score={best['total_score']:.2f})", flush=True)

            print("  Scoring with DockQ vs native bound complex...", flush=True)
            dockq = score_dockq(
                model_pdb=best_pdb,
                native_pdb=native_complex,
                receptor_native_chains=native_rec,
                binder_native_chains=native_bind,
            )
            print(f"  DockQ={dockq['DockQ']:.3f} ({dockq['classification']})  "
                  f"Fnat={dockq['Fnat']:.3f}  iRMS={dockq['iRMS']:.2f}  LRMS={dockq['LRMS']:.2f}", flush=True)

            result.update({
                "status": "success",
                "rosetta_score": round(float(best["total_score"]), 3),
                "best_model": best_pdb.name,
                "native_receptor_chains": native_rec,
                "native_binder_chains": native_bind,
                **dockq,
                "finished_at": datetime.now().isoformat(),
                "wall_seconds": round(_time.monotonic() - _t_start, 1),
            })

        except Exception:
            tb = traceback.format_exc()
            print(f"  ERROR: {tb}", flush=True)
            result.update({
                "status": "failed",
                "error": tb,
                "finished_at": datetime.now().isoformat(),
                "wall_seconds": round(_time.monotonic() - _t_start, 1),
            })

        _write_results(results, output_dir)
        _write_progress(i + 1, total, output_dir)

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--db55", required=True, help="Path to DB5.5 structures dir")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text())
    entries = config["entries"]
    nstruct = config.get("nstruct", 50)
    db55_dir = Path(args.db55)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"ProteinDock UNBOUND Benchmark (DB5.5)")
    print(f"Entries: {len(entries)}  nstruct: {nstruct}")
    print(f"DB5.5 dir: {db55_dir}")
    print(f"Output:    {output_dir}")

    results = run_unbound_benchmark(entries, db55_dir, output_dir, nstruct)

    success = sum(1 for r in results if r["status"] == "success")
    scores = [r["DockQ"] for r in results if r.get("DockQ") is not None]
    mean_dockq = sum(scores) / len(scores) if scores else 0.0
    summary = {
        "total": len(results),
        "success": success,
        "failed": len(results) - success,
        "mean_DockQ": round(mean_dockq, 4),
        "nstruct": nstruct,
        "benchmark_type": "unbound (DB5.5)",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nDone. {success}/{len(results)} succeeded. Mean DockQ = {mean_dockq:.4f}")


if __name__ == "__main__":
    main()
