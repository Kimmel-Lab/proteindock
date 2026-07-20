#!/usr/bin/env python3
"""
compare_runs.py — Diff DockQ benchmark runs side-by-side.

Reads results.json + summary.json from one or more bench_runs/ subdirs and
prints a per-PDB comparison table plus aggregate stats. Highlights deltas
between runs so you can see at a glance whether iteration N improved over
iteration N-1.

Usage:
  compare_runs.py iter0_baseline iter1_prerelax [iter2_topN ...]
  compare_runs.py --root /path/to/bench_runs iter0 iter1
  compare_runs.py --markdown iter0 iter1   # markdown table for paste

Each bench_runs/<run_label>/ should contain:
  - results.json  (list of per-PDB dicts with DockQ, Fnat, iRMS, LRMS, status)
  - summary.json  (mean/median/etc.)
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

DEFAULT_ROOT = Path.home() / "protein_web_jobs" / "bench_runs"


def load_run(run_dir: Path) -> tuple[list[dict], dict]:
    """Returns (per_pdb_results, summary_dict). Tolerates missing summary."""
    results_path = run_dir / "results.json"
    summary_path = run_dir / "summary.json"
    if not results_path.exists():
        raise FileNotFoundError(f"Missing {results_path}")
    results = json.loads(results_path.read_text())
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    return results, summary


def index_by_pdb(results: list[dict]) -> dict[str, dict]:
    return {r["pdb_code"]: r for r in results}


def fmt(val, n=3) -> str:
    if val is None:
        return "—"
    if isinstance(val, str):
        return val
    return f"{val:.{n}f}"


def color_delta(delta: float | None) -> str:
    if delta is None:
        return ""
    if abs(delta) < 0.005:
        return f"     "
    sign = "+" if delta > 0 else ""
    return f"({sign}{delta:.2f})"


def render_table(runs: list[tuple[str, dict[str, dict]]], markdown: bool = False) -> str:
    """runs = list of (label, pdb→result dict) tuples."""
    all_pdbs = sorted(set().union(*(r.keys() for _, r in runs)))
    headers = ["PDB"] + [label for label, _ in runs]
    rows = []
    for pdb in all_pdbs:
        row = [pdb]
        baseline = None
        for label, idx in runs:
            r = idx.get(pdb)
            if r is None or r.get("status") != "success":
                row.append("—")
                continue
            dq = r.get("DockQ")
            cls = r.get("classification", "")
            cell = f"{fmt(dq)} {cls[:1] if cls else ''}"
            if baseline is None:
                baseline = dq
            else:
                delta = dq - baseline if (dq is not None and baseline is not None) else None
                cell = f"{fmt(dq)} {cls[:1] if cls else ''} {color_delta(delta)}"
            row.append(cell)
        rows.append(row)

    if markdown:
        lines = ["| " + " | ".join(headers) + " |"]
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for row in rows:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)
    else:
        widths = [max(len(str(row[i])) for row in [headers] + rows) for i in range(len(headers))]
        sep = " │ "
        lines = [sep.join(h.ljust(w) for h, w in zip(headers, widths))]
        lines.append("─" * (sum(widths) + len(widths) * 3))
        for row in rows:
            lines.append(sep.join(c.ljust(w) for c, w in zip(row, widths)))
        return "\n".join(lines)


def aggregate(results: list[dict]) -> dict:
    success = [r for r in results if r["status"] == "success" and r.get("DockQ") is not None]
    scores = sorted(r["DockQ"] for r in success)
    if not scores:
        return {"n_success": 0, "mean": None, "median": None, "high": 0, "medium": 0, "acceptable": 0, "incorrect": 0}
    high = sum(1 for s in scores if s >= 0.80)
    medium = sum(1 for s in scores if 0.49 <= s < 0.80)
    accept = sum(1 for s in scores if 0.23 <= s < 0.49)
    incorrect = sum(1 for s in scores if s < 0.23)
    return {
        "n_success": len(scores),
        "mean": sum(scores) / len(scores),
        "median": scores[len(scores) // 2],
        "high": high,
        "medium": medium,
        "acceptable": accept,
        "incorrect": incorrect,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="+", help="Run labels (subdirs of --root)")
    p.add_argument("--root", default=str(DEFAULT_ROOT), help="bench_runs root dir")
    p.add_argument("--markdown", action="store_true", help="Emit markdown")
    args = p.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: {root} does not exist", file=sys.stderr)
        sys.exit(1)

    loaded = []
    for label in args.runs:
        run_dir = root / label
        try:
            results, summary = load_run(run_dir)
        except FileNotFoundError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
        loaded.append((label, results, summary))

    indexed = [(label, index_by_pdb(results)) for label, results, _ in loaded]
    print(render_table(indexed, markdown=args.markdown))

    print()
    sep_w = max(20, max(len(label) for label, _, _ in loaded) + 5)
    if args.markdown:
        print()
        print("| Stat | " + " | ".join(label for label, _, _ in loaded) + " |")
        print("|" + "|".join(["---"] * (len(loaded) + 1)) + "|")
        for stat in ("n_success", "mean", "median", "high", "medium", "acceptable", "incorrect"):
            row = [stat]
            for _, results, _ in loaded:
                a = aggregate(results)
                v = a[stat]
                row.append(fmt(v) if isinstance(v, float) else str(v))
            print("| " + " | ".join(row) + " |")
    else:
        for label, results, _ in loaded:
            a = aggregate(results)
            print(f"--- {label} ---")
            print(f"  Successes:        {a['n_success']}")
            print(f"  Mean DockQ:       {fmt(a['mean'])}")
            print(f"  Median DockQ:     {fmt(a['median'])}")
            print(f"  Class breakdown:  H={a['high']}  M={a['medium']}  A={a['acceptable']}  I={a['incorrect']}")
            print()

    # Mean delta vs first run (baseline)
    if len(loaded) > 1:
        baseline = aggregate(loaded[0][1])
        print(f"=== vs {loaded[0][0]} ===")
        for label, results, _ in loaded[1:]:
            a = aggregate(results)
            if baseline["mean"] is not None and a["mean"] is not None:
                delta = a["mean"] - baseline["mean"]
                sign = "+" if delta >= 0 else ""
                print(f"  {label}: mean DockQ {sign}{delta:.3f}")


if __name__ == "__main__":
    main()
