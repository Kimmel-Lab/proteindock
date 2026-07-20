#!/usr/bin/env python3
"""
rescore_benchmark.py — Re-score benchmark entries with the fixed DockQ scorer.

Walks ~/protein_web_jobs/benchmark/<PDB>/, picks best Rosetta model from
docking.fasc, computes DockQ against native.pdb, writes fresh
results.json + summary.json.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.dockq_scorer import score_dockq, PRESET_BENCHMARK, EXTENDED_BENCHMARK
from backend.pipeline import parse_fasc_and_find_best


def rescore(benchmark_dir: Path, entries: list[dict]) -> list[dict]:
    results = []
    for entry in entries:
        pdb_code = entry["pdb_code"]
        d = benchmark_dir / pdb_code
        result = {
            "pdb_code": pdb_code,
            "category": entry.get("category", "unknown"),
            "description": entry.get("description", ""),
        }
        if not d.exists():
            result.update({"status": "missing", "error": "directory not found"})
            results.append(result)
            continue

        fasc = d / "docking.fasc"
        native = d / "native.pdb"
        if not fasc.exists() or not native.exists():
            result.update({"status": "missing", "error": "no fasc or native"})
            results.append(result)
            continue

        try:
            best = parse_fasc_and_find_best(
                fasc_path=fasc, pdb_glob=str(d / "complex_input_full_*.pdb")
            )
            if best is None:
                result.update({"status": "failed", "error": "no models in fasc"})
                results.append(result)
                continue
            best_pdb = Path(best["pdb_path"])
            dockq = score_dockq(
                model_pdb=best_pdb,
                native_pdb=native,
                receptor_native_chains=entry["receptor_chains"],
                binder_native_chains=entry["binder_chains"],
            )
            result.update({
                "status": "success",
                "rosetta_score": round(float(best["total_score"]), 3),
                "best_model": best_pdb.name,
                **dockq,
            })
            print(f"  {pdb_code}: DockQ={dockq['DockQ']:.3f} ({dockq['classification']})  "
                  f"Fnat={dockq['Fnat']:.3f}  iRMS={dockq['iRMS']:.2f}  LRMS={dockq['LRMS']:.2f}")
        except Exception as e:
            result.update({"status": "failed", "error": str(e)})
            print(f"  {pdb_code}: FAILED — {e}")
        results.append(result)
    return results


def summarize(results: list[dict]) -> dict:
    success = [r for r in results if r["status"] == "success"]
    scores = [r["DockQ"] for r in success]
    mean = sum(scores) / len(scores) if scores else 0.0
    median = sorted(scores)[len(scores) // 2] if scores else 0.0
    by_class = {"High": 0, "Medium": 0, "Acceptable": 0, "Incorrect": 0}
    for r in success:
        by_class[r["classification"]] = by_class.get(r["classification"], 0) + 1
    acc_or_better = sum(1 for r in success if r["DockQ"] >= 0.23)
    return {
        "total": len(results),
        "success": len(success),
        "failed": len(results) - len(success),
        "mean_DockQ": round(mean, 4),
        "median_DockQ": round(median, 4),
        "acceptable_or_better": acc_or_better,
        "acceptable_or_better_rate": round(acc_or_better / len(success), 4) if success else 0.0,
        "by_classification": by_class,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=str(Path.home() / "protein_web_jobs" / "benchmark"))
    parser.add_argument("--preset", choices=["standard", "extended"], default="standard")
    args = parser.parse_args()

    bench_dir = Path(args.dir)
    entries = EXTENDED_BENCHMARK if args.preset == "extended" else PRESET_BENCHMARK

    print(f"Rescoring {len(entries)} entries in {bench_dir}")
    results = rescore(bench_dir, entries)
    summary = summarize(results)

    (bench_dir / "results.json").write_text(json.dumps(results, indent=2))
    (bench_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print()
    print(f"Summary: {summary['success']}/{summary['total']} succeeded")
    print(f"  Mean DockQ: {summary['mean_DockQ']:.4f}")
    print(f"  Median DockQ: {summary['median_DockQ']:.4f}")
    print(f"  Acceptable or better: {summary['acceptable_or_better']}/{summary['success']} "
          f"({summary['acceptable_or_better_rate']*100:.1f}%)")
    print(f"  Classification: {summary['by_classification']}")


if __name__ == "__main__":
    main()
