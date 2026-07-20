#!/usr/bin/env python3
"""
merge_array_results.py — Merge per-PDB results.json from a SLURM array
benchmark run into one combined results.json + summary.json.

After submit_array_iteration.sh finishes, each task wrote its own
results.json (containing 1 entry). This walks the output dir, collects
all per-task results, and produces the unified outputs that
compare_runs.py expects.
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path


def merge(out_dir: Path) -> dict:
    all_results = []
    # Each task wrote results.json containing typically 1 entry (the PDB it ran)
    # But because all tasks share the same output dir, the LAST task to
    # finish overwrites results.json. So we walk per-PDB subdirs instead.
    for pdb_dir in sorted(out_dir.iterdir()):
        if not pdb_dir.is_dir():
            continue
        if pdb_dir.name in ("boltz_ensemble", "db55_native_stage"):
            continue
        # Look for a marker that this PDB was processed
        if not (pdb_dir / "complex_input.pdb").exists():
            continue
        # Reconstruct a result entry by reading the latest results.json
        # OR by scoring the best decoy directly (slower but reliable)
        # Easiest: parse the SLURM out logs to find the final result line
        slurm_outs = list(out_dir.glob(f"slurm-*_*.out"))
        # Better: each task wrote `results.json` at completion — but only the
        # last writer wins. Let's use a different convention: read per-PDB
        # results from the in-progress files if available.
        # Since results are in the parent results.json (overwritten), we
        # rebuild by re-scoring the best model per PDB dir.
        from backend.dockq_scorer import score_dockq
        from backend.pipeline import parse_fasc_and_find_best
        fasc = pdb_dir / "docking.fasc"
        native = pdb_dir / "native.pdb"
        if not fasc.exists() or not native.exists():
            continue
        try:
            best = parse_fasc_and_find_best(
                fasc_path=fasc, pdb_glob=str(pdb_dir / "complex_input_full_*.pdb")
            )
            if best is None:
                continue
            # Native chain detection
            rec_chains = _detect_chains(pdb_dir / "receptor_clean.pdb") or ["A"]
            bind_chains = _detect_chains(pdb_dir / "binder_clean.pdb") or ["B"]
            # If native uses different chain IDs, we need them from the original index
            # but in the array setup we standardized to A/B
            dockq = score_dockq(
                model_pdb=Path(best["pdb_path"]), native_pdb=native,
                receptor_native_chains=["A"],
                binder_native_chains=["B"],
            )
            # Try to fall back to original native chains if A/B doesn't work
            if "error" in dockq:
                # Re-detect from native
                native_chains = _detect_chains(native)
                if len(native_chains) >= 2:
                    dockq = score_dockq(
                        model_pdb=Path(best["pdb_path"]), native_pdb=native,
                        receptor_native_chains=[native_chains[0]],
                        binder_native_chains=[native_chains[1]],
                    )
            all_results.append({
                "pdb_code": pdb_dir.name,
                "status": "success",
                "rosetta_score": round(float(best["total_score"]), 3),
                "best_model": Path(best["pdb_path"]).name,
                **dockq,
            })
        except Exception as e:
            all_results.append({
                "pdb_code": pdb_dir.name,
                "status": "failed",
                "error": str(e),
            })

    # Compute summary
    success = [r for r in all_results if r["status"] == "success"]
    scores = [r["DockQ"] for r in success if r.get("DockQ") is not None]
    summary = {
        "total": len(all_results),
        "success": len(success),
        "failed": len(all_results) - len(success),
        "mean_DockQ": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "median_DockQ": round(sorted(scores)[len(scores) // 2], 4) if scores else 0.0,
    }
    return {"results": all_results, "summary": summary}


def _detect_chains(pdb_path: Path) -> list[str]:
    if not pdb_path.exists():
        return []
    chains = []
    for line in pdb_path.read_text().splitlines():
        if line.startswith("ATOM") and len(line) > 21 and line[21] not in chains:
            chains.append(line[21])
    return chains


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", required=True, type=Path)
    args = p.parse_args()

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    merged = merge(args.out_dir)
    (args.out_dir / "results.json").write_text(json.dumps(merged["results"], indent=2))
    (args.out_dir / "summary.json").write_text(json.dumps(merged["summary"], indent=2))
    print(f"Merged → {args.out_dir}/results.json + summary.json")
    print(f"  {merged['summary']}")


if __name__ == "__main__":
    main()
