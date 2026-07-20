#!/usr/bin/env python3
"""
analyze_ncaa_results.py — Build paper-ready summary from ncAA optimizer outputs.

Reads results_history.csv (every evaluation) and writes:
  - paper_summary.json   — headline stats + ranked hits
  - pareto_data.csv      — non-dominated subset for ddG_bind vs ddG_fold
  - top10_table.md       — markdown table ready for the paper

Usage:
  python analyze_ncaa_results.py --dir <ncaa_opt_dir>
"""

import argparse
import csv
import json
from pathlib import Path


def load_history(csv_path: Path) -> list[dict]:
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    parsed = []
    for r in rows:
        if r.get("status") != "ok":
            continue
        parsed.append({
            "iter": int(r["iteration"]),
            "ncaa": r["ncaa"],
            "pos": int(r["position"]),
            "chain": r["chain"],
            "resid": int(r["resid"]),
            "wt_aa": r["wt_aa"],
            "wt_aa3": r["wt_aa3"],
            "sasa": float(r["sasa"]),
            "ddg_bind": float(r["ddg_bind"]),
            "ddg_fold": float(r["ddg_fold"]),
            "score": float(r["objective_score"]),
        })
    return parsed


def pareto_front(points: list[dict]) -> list[dict]:
    """Return Pareto-optimal points minimizing both ddg_bind and ddg_fold."""
    front = []
    for p in points:
        dominated = False
        for q in points:
            if q is p:
                continue
            if (q["ddg_bind"] <= p["ddg_bind"] and q["ddg_fold"] <= p["ddg_fold"]
                    and (q["ddg_bind"] < p["ddg_bind"] or q["ddg_fold"] < p["ddg_fold"])):
                dominated = True
                break
        if not dominated:
            front.append(p)
    return sorted(front, key=lambda x: x["ddg_bind"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="ncaa_opt directory")
    ap.add_argument("--max-abs-ddg-bind", type=float, default=20.0,
                    help="Drop evaluations with |ddg_bind| > this (REU). "
                         "Rosetta minimization with long aliphatic ncAAs can "
                         "produce -1000+ REU artifacts; cap at 20 by default.")
    args = ap.parse_args()

    d = Path(args.dir)
    hist_csv = d / "results_history.csv"
    summary_json = d / "results_summary.json"
    if not hist_csv.exists():
        raise SystemExit(f"Missing: {hist_csv}")
    history_raw = load_history(hist_csv)
    n_before = len(history_raw)
    history = [h for h in history_raw if abs(h["ddg_bind"]) <= args.max_abs_ddg_bind]
    n_dropped = n_before - len(history)
    if n_dropped:
        print(f"Filtered {n_dropped}/{n_before} outliers (|ddg_bind| > {args.max_abs_ddg_bind} REU)")
    summary = json.loads(summary_json.read_text()) if summary_json.exists() else {}

    # Filter to "good" hits — must improve binding AND not destabilize too much
    good = [h for h in history if h["ddg_bind"] < 0]
    stable = [h for h in history if h["ddg_bind"] < 0 and h["ddg_fold"] < 2.0]
    free_lunch = [h for h in history if h["ddg_bind"] < 0 and h["ddg_fold"] < 0]

    by_score = sorted(history, key=lambda x: x["score"])
    by_bind = sorted(history, key=lambda x: x["ddg_bind"])

    front = pareto_front(history)

    paper = {
        "n_evaluations": len(history),
        "n_improving_binding": len(good),
        "n_stable_improvements": len(stable),
        "n_free_lunch": len(free_lunch),
        "best_score": by_score[0]["score"] if by_score else None,
        "best_score_hit": by_score[0] if by_score else None,
        "best_binder": by_bind[0] if by_bind else None,
        "free_lunch_hits": free_lunch,
        "pareto_front": front,
        "ncaa_counts": {},
    }
    for h in history:
        paper["ncaa_counts"][h["ncaa"]] = paper["ncaa_counts"].get(h["ncaa"], 0) + 1

    (d / "paper_summary.json").write_text(json.dumps(paper, indent=2))

    # CSV of Pareto front
    pf_csv = d / "pareto_data.csv"
    with open(pf_csv, "w") as f:
        w = csv.DictWriter(f, fieldnames=["ncaa", "chain", "resid", "wt_aa", "sasa", "ddg_bind", "ddg_fold", "score"])
        w.writeheader()
        for h in front:
            w.writerow({k: h[k] for k in w.fieldnames})

    # Markdown table
    lines = [
        "| Rank | ncAA | Position | WT | ΔΔG_bind | ΔΔG_fold | Score |",
        "|------|------|----------|----|----------|----------|-------|",
    ]
    for i, h in enumerate(by_score[:10], 1):
        lines.append(
            f"| {i} | {h['ncaa']} | {h['chain']}{h['resid']} | {h['wt_aa']} | "
            f"{h['ddg_bind']:+.2f} | {h['ddg_fold']:+.2f} | {h['score']:+.2f} |"
        )
    (d / "top10_table.md").write_text("\n".join(lines) + "\n")

    print(f"Wrote: {d}/paper_summary.json")
    print(f"       {d}/pareto_data.csv  ({len(front)} non-dominated points)")
    print(f"       {d}/top10_table.md")
    print()
    print(f"Evaluations:           {len(history)}")
    print(f"Improving binding:     {len(good)}/{len(history)} ({100*len(good)/max(1,len(history)):.0f}%)")
    print(f"Stable improvements:   {len(stable)}")
    print(f"Free-lunch hits:       {len(free_lunch)}  (both bind better AND fold better)")
    print()
    print("=== Top 5 by combined score ===")
    for h in by_score[:5]:
        print(f"  {h['ncaa']} @ {h['chain']}{h['resid']}({h['wt_aa']})  "
              f"ddg_bind={h['ddg_bind']:+7.2f}  ddg_fold={h['ddg_fold']:+7.2f}  score={h['score']:+7.2f}")
    if free_lunch:
        print()
        print("=== Free-lunch hits (negative on both axes) ===")
        for h in free_lunch:
            print(f"  {h['ncaa']} @ {h['chain']}{h['resid']}({h['wt_aa']})  "
                  f"ddg_bind={h['ddg_bind']:+7.2f}  ddg_fold={h['ddg_fold']:+7.2f}")


if __name__ == "__main__":
    main()
