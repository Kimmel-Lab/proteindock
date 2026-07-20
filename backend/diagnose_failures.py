#!/usr/bin/env python3
"""
diagnose_failures.py — For failed/Acceptable benchmark entries, find out
*why* they failed: scoring problem (right answer in decoy set, mis-ranked)
or sampling problem (no decoy near native).

Walks each PDB dir, scores ALL decoys (not just the lowest Rosetta score)
against the native, then reports:

  PDB    | Top-1 by Rosetta | Best by DockQ      | Verdict
  1AY7   | 0.219 (Incorrect)| 0.611 (Medium) #34 | SCORING — re-rank wins
  1ACB   | 0.228 (Incorrect)| 0.241 (Acceptable) | SAMPLING — no good decoy

Verdict criteria:
  - SCORING: best-DockQ decoy beats top-1 by >0.10 → re-ranker would help
  - SAMPLING: best-DockQ decoy < 0.50 → not enough sampling, even oracle picker can't save it
  - OK: top-1 already at Medium+ → nothing wrong
"""

from __future__ import annotations
import argparse
import json
import sys
from glob import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.dockq_scorer import score_dockq, classify_dockq
from backend.pipeline import parse_fasc_and_find_best


def parse_fasc_all(fasc_path: Path) -> list[dict]:
    """Parse all decoys from a Rosetta fasc file."""
    decoys = []
    if not fasc_path.exists():
        return decoys
    headers = None
    with open(fasc_path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith("SCORE:"):
                continue
            parts = line.split()
            if headers is None:
                headers = parts[1:]
                continue
            row = {}
            for k, v in zip(headers, parts[1:]):
                try:
                    row[k] = float(v)
                except ValueError:
                    row[k] = v
            decoys.append(row)
    return decoys


def diagnose_one(pdb_dir: Path, native_pdb: Path, rec_chains: list[str], bind_chains: list[str], top_n: int = 50, verbose: bool = False) -> dict:
    """Score every decoy in pdb_dir, return diagnosis dict."""
    fasc = pdb_dir / "docking.fasc"
    decoys = parse_fasc_all(fasc)
    if not decoys:
        return {"pdb_code": pdb_dir.name, "verdict": "NO_DATA", "n_decoys": 0}

    # Sort by total_score (lower = better)
    decoys_sorted = sorted(decoys, key=lambda d: d.get("total_score", 1e9))[:top_n]

    decoy_scores = []
    for d in decoys_sorted:
        desc = d.get("description", "")
        if not desc:
            continue
        pdb_path = pdb_dir / f"{desc}.pdb"
        if not pdb_path.exists():
            continue
        try:
            result = score_dockq(
                model_pdb=pdb_path,
                native_pdb=native_pdb,
                receptor_native_chains=rec_chains,
                binder_native_chains=bind_chains,
            )
            decoy_scores.append({
                "name": desc,
                "total_score": d.get("total_score"),
                "rms": d.get("rms"),
                "I_sc": d.get("I_sc"),
                "DockQ": result["DockQ"],
                "classification": result["classification"],
            })
        except Exception as e:
            if verbose:
                print(f"  Skipped {desc}: {e}", file=sys.stderr)

    if not decoy_scores:
        return {"pdb_code": pdb_dir.name, "verdict": "NO_VALID_DECOYS", "n_decoys": len(decoys)}

    top1 = decoy_scores[0]
    best_dockq = max(decoy_scores, key=lambda d: d["DockQ"])
    best_dockq_rank = decoy_scores.index(best_dockq) + 1

    # Verdict
    if top1["DockQ"] >= 0.49:
        verdict = "OK"
    elif best_dockq["DockQ"] >= top1["DockQ"] + 0.10:
        verdict = "SCORING"
    elif best_dockq["DockQ"] < 0.50:
        verdict = "SAMPLING"
    else:
        verdict = "MARGINAL"

    return {
        "pdb_code": pdb_dir.name,
        "n_decoys_scanned": len(decoy_scores),
        "n_decoys_in_fasc": len(decoys),
        "top1_by_rosetta": {
            "name": top1["name"],
            "DockQ": round(top1["DockQ"], 4),
            "classification": top1["classification"],
            "rosetta_score": top1["total_score"],
        },
        "best_by_dockq": {
            "name": best_dockq["name"],
            "rank_in_rosetta_score": best_dockq_rank,
            "DockQ": round(best_dockq["DockQ"], 4),
            "classification": best_dockq["classification"],
            "rosetta_score": best_dockq["total_score"],
        },
        "verdict": verdict,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results", required=True, help="results.json from benchmark run")
    p.add_argument("--bench-dir", required=True, help="benchmark output dir (contains <PDB>/ subdirs)")
    p.add_argument("--top-n", type=int, default=50, help="Rescore the top N by Rosetta score")
    p.add_argument("--only-failures", action="store_true", help="Only diagnose Acceptable/Incorrect entries")
    p.add_argument("--out", default=None, help="Write diagnosis JSON to this path (default stdout)")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    results = json.loads(Path(args.results).read_text())
    bench_dir = Path(args.bench_dir)

    diagnoses = []
    for r in results:
        if r["status"] != "success":
            continue
        if args.only_failures and r.get("DockQ", 0) >= 0.49:
            continue
        pdb = r["pdb_code"]
        pdb_dir = bench_dir / pdb
        native = pdb_dir / "native.pdb"
        rec_chains = r.get("native_receptor_chains") or [pdb_dir.name[0]] or ["A"]
        bind_chains = r.get("native_binder_chains") or ["B"]

        # For bound benchmark, native chains stored differently
        if not (pdb_dir / "native.pdb").exists():
            print(f"Skip {pdb}: no native.pdb in {pdb_dir}", file=sys.stderr)
            continue

        print(f"Diagnosing {pdb} (top {args.top_n} by Rosetta score)...", file=sys.stderr)
        diag = diagnose_one(pdb_dir, native, rec_chains, bind_chains, args.top_n, args.verbose)
        diag["initial_top1_DockQ"] = r.get("DockQ")
        diag["initial_classification"] = r.get("classification")
        diagnoses.append(diag)

    # Print compact table
    print()
    print(f"{'PDB':6s} {'Top-1 Rosetta':>14s} {'Best DockQ':>14s} {'Rank':>5s} {'Verdict':10s}")
    print("─" * 60)
    for d in diagnoses:
        if d.get("verdict") in ("NO_DATA", "NO_VALID_DECOYS"):
            print(f"{d['pdb_code']:6s} {d['verdict']:30s}")
            continue
        t1 = d["top1_by_rosetta"]
        bb = d["best_by_dockq"]
        print(f"{d['pdb_code']:6s} {t1['DockQ']:>7.3f} ({t1['classification'][:1]:1s})   "
              f"{bb['DockQ']:>7.3f} ({bb['classification'][:1]:1s})   "
              f"{bb['rank_in_rosetta_score']:>3d}  {d['verdict']}")

    print()
    print("Verdict legend:")
    print("  OK        — top-1 already Medium+, nothing to fix")
    print("  SCORING   — re-ranker would find a better decoy in the existing set")
    print("  SAMPLING  — even oracle picker can't recover; need more nstruct or pre-relax")
    print("  MARGINAL  — close to threshold, could go either way")

    if args.out:
        Path(args.out).write_text(json.dumps(diagnoses, indent=2))
        print(f"\nWrote diagnosis JSON: {args.out}")


if __name__ == "__main__":
    main()
