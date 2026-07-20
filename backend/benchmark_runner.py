#!/usr/bin/env python3
"""
benchmark_runner.py — Standalone script executed inside a SLURM job.

For each PDB entry:
  1. Download native complex from RCSB
  2. Extract receptor/binder chains
  3. Clean → normalize → sanitize → merge (ProteinDock pipeline)
  4. Run Rosetta docking (blocking)
  5. Score best model with DockQ vs. native
  6. Write result to results.json (updated after each PDB so progress is visible)

Usage:
  python benchmark_runner.py --config <config.json> --output <output_dir>
"""

import argparse
import json
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Add protein_web root to sys.path so backend.* imports work.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import DEFAULT_WORKDIR
from backend.pipeline import (
    fetch_pdb,
    run_clean_pdb,
    normalize_chains,
    sanitize_pdb,
    combine_in_python,
    run_docking,
    parse_fasc_and_find_best,
)
from backend.dockq_scorer import extract_chains, score_dockq


def _rename_chain(input_pdb: Path, output_pdb: Path, new_chain_id: str) -> None:
    """Rewrite all ATOM/HETATM records with a single chain ID."""
    lines = []
    with open(input_pdb) as f:
        for line in f:
            if line.startswith(("ATOM", "HETATM")) and len(line) > 21:
                line = line[:21] + new_chain_id + line[22:]
            lines.append(line)
    with open(output_pdb, "w") as f:
        f.writelines(lines)


def _write_results(results: list, output_dir: Path) -> None:
    tmp = output_dir / "results.json.tmp"
    tmp.write_text(json.dumps(results, indent=2))
    tmp.replace(output_dir / "results.json")


def _write_progress(done: int, total: int, output_dir: Path) -> None:
    (output_dir / "progress.json").write_text(
        json.dumps({"done": done, "total": total})
    )


def run_benchmark(entries: list[dict], output_dir: Path, nstruct: int) -> list[dict]:
    results = []
    total = len(entries)

    for i, entry in enumerate(entries):
        pdb_code = entry["pdb_code"]
        rec_chains = entry["receptor_chains"]
        bind_chains = entry["binder_chains"]
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
            print(f"\n[{i+1}/{total}] {pdb_code} — {description}")

            # 1. Download native complex
            print(f"  Fetching {pdb_code} from RCSB...")
            native_pdb = fetch_pdb(pdb_code, pdb_dir)

            # Save a copy of the native complex for DockQ scoring
            native_copy = pdb_dir / "native.pdb"
            shutil.copy(native_pdb, native_copy)

            # 2. Extract receptor and binder chains from native
            print(f"  Extracting chains: receptor={rec_chains}, binder={bind_chains}")
            rec_raw = pdb_dir / "receptor_raw.pdb"
            bind_raw = pdb_dir / "binder_raw.pdb"
            extract_chains(native_pdb, rec_chains, rec_raw)
            extract_chains(native_pdb, bind_chains, bind_raw)

            # Normalize to standard chain IDs (A/B) before cleaning so
            # run_clean_pdb always finds the expected output filename.
            rec_std = pdb_dir / "receptor_std.pdb"
            bind_std = pdb_dir / "binder_std.pdb"
            _rename_chain(rec_raw, rec_std, "A")
            _rename_chain(bind_raw, bind_std, "B")

            # 3. Clean
            print("  Cleaning...")
            rec_clean = pdb_dir / "receptor_clean.pdb"
            bind_clean = pdb_dir / "binder_clean.pdb"
            run_clean_pdb(rec_std, rec_clean)
            run_clean_pdb(bind_std, bind_clean)

            # 4. Normalize (assign chain A to receptor, B to binder)
            rec_chains_pdb, used = normalize_chains(rec_clean, used=set())
            bind_chains_pdb, _ = normalize_chains(bind_clean, used=used)

            # 5. Sanitize
            rec_fixed = sanitize_pdb(rec_chains_pdb)
            bind_fixed = sanitize_pdb(bind_chains_pdb)

            # 6. Merge
            print("  Merging into complex...")
            complex_pdb = pdb_dir / "complex_input.pdb"
            combine_in_python(rec_fixed, bind_fixed, complex_pdb)
            (pdb_dir / "partners.txt").write_text("A_B")

            # 7. Dock — allow partial Rosetta failures (some decoys may fail
            # internal contact/VdW filters while others succeed; we only need 1).
            print(f"  Running Rosetta docking (nstruct={nstruct})...")
            try:
                run_docking(complex_pdb, output_dir=pdb_dir, nstruct=nstruct)
            except RuntimeError as dock_err:
                fasc_check = pdb_dir / "docking.fasc"
                import glob as _glob
                n_pdbs = len(_glob.glob(str(pdb_dir / "complex_input_full_*.pdb")))
                if n_pdbs == 0:
                    raise RuntimeError(f"Rosetta produced no output structures: {dock_err}") from dock_err
                print(f"  Rosetta partial failure ({n_pdbs} structures produced — continuing)")

            # 8. Parse best model
            fasc = pdb_dir / "docking.fasc"
            pdb_glob = str(pdb_dir / "complex_input_full_*.pdb")
            best = parse_fasc_and_find_best(fasc_path=fasc, pdb_glob=pdb_glob)
            if best is None:
                raise RuntimeError("No docking models produced.")

            best_pdb = Path(best["pdb_path"])
            print(f"  Best model: {best_pdb.name} (score={best['total_score']:.2f})")

            # 9. Score with DockQ
            print("  Scoring with DockQ...")
            dockq = score_dockq(
                model_pdb=best_pdb,
                native_pdb=native_copy,
                receptor_native_chains=rec_chains,
                binder_native_chains=bind_chains,
            )
            print(f"  DockQ={dockq['DockQ']:.3f} ({dockq['classification']})  "
                  f"Fnat={dockq['Fnat']:.3f}  iRMS={dockq['iRMS']:.2f}  LRMS={dockq['LRMS']:.2f}")

            result.update({
                "status": "success",
                "rosetta_score": round(float(best["total_score"]), 3),
                "best_model": best_pdb.name,
                **dockq,
                "finished_at": datetime.now().isoformat(),
                "wall_seconds": round(_time.monotonic() - _t_start, 1),
            })

        except Exception:
            tb = traceback.format_exc()
            print(f"  ERROR: {tb}")
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
    parser.add_argument("--config", required=True, help="Path to benchmark config JSON")
    parser.add_argument("--output", required=True, help="Output directory for results")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text())
    entries = config["entries"]
    nstruct = config.get("nstruct", 10)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"ProteinDock Benchmark Runner")
    print(f"Entries: {len(entries)}  nstruct: {nstruct}")
    print(f"Output:  {output_dir}")

    results = run_benchmark(entries, output_dir, nstruct)

    success = sum(1 for r in results if r["status"] == "success")
    scores = [r["DockQ"] for r in results if r.get("DockQ") is not None]
    mean_dockq = sum(scores) / len(scores) if scores else 0.0

    summary = {
        "total": len(results),
        "success": success,
        "failed": len(results) - success,
        "mean_DockQ": round(mean_dockq, 4),
        "nstruct": nstruct,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nDone. {success}/{len(results)} succeeded. Mean DockQ = {mean_dockq:.4f}")


if __name__ == "__main__":
    main()
