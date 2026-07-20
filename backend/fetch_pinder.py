#!/usr/bin/env python3
"""
fetch_pinder.py — Download a PINDER subset and convert to our unified
benchmark index format.

PINDER (Kovtun et al., bioRxiv 2024.07.17.603980) provides three test sets:
  - PINDER-S    : small curated subset (~50 systems)
  - PINDER-XL   : extra-large (~1955 systems)
  - PINDER-AF2  : leakage-controlled vs AF-Multimer training (180 holo + 30 apo)

For paper 2, PINDER-AF2 is the right benchmark — it's what the field is
moving to and what AF3-class evals are now being run on.

Usage:
  # Quick test on PINDER-S (small)
  python fetch_pinder.py --subset PINDER-S --out ~/protein_web_jobs/pinder_data \
                         --index ~/protein_web_jobs/bench_runs/pinder_s_index.json --limit 10

  # Full PINDER-AF2 holo
  python fetch_pinder.py --subset PINDER-AF2 --type holo --out ~/protein_web_jobs/pinder_data \
                         --index ~/protein_web_jobs/bench_runs/pinder_af2_holo_index.json

Requires the `pinder` Python package: `pip install pinder`
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def fetch_subset(subset: str, type_filter: str | None, out_dir: Path,
                 limit: int | None = None) -> list[dict]:
    """
    Pull a PINDER subset using the pinder API.

    Returns list of unified-index dicts:
      { pdb_code, receptor_pdb, binder_pdb, native_pdb,
        native_receptor_chains, native_binder_chains, source, category }
    """
    try:
        from pinder.core import PinderSystem, get_index
    except ImportError:
        sys.exit(
            "ERROR: pinder package not installed.\n"
            "  pip install pinder\n"
            "  (or run via the boltz/ml venv if it has pinder)"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    pindex = get_index()

    # Filter to test set
    test_col = f"{subset.lower().replace('-', '_')}"
    if test_col in pindex.columns:
        df = pindex[pindex[test_col] == True]
    else:
        # Fall back to subset_name column if present
        df = pindex[pindex.get("subset_name", pindex.get("split", "")) == subset]

    if type_filter:
        # PINDER-AF2 has holo / apo / predicted columns
        if type_filter in df.columns:
            df = df[df[type_filter] == True]

    print(f"Found {len(df)} systems in {subset}" + (f" / {type_filter}" if type_filter else ""))

    if limit:
        df = df.head(limit)
        print(f"Limited to {len(df)} systems")

    entries = []
    for _, row in df.iterrows():
        sys_id = row["id"] if "id" in row else row.name
        try:
            sys_obj = PinderSystem(entry=sys_id)
            sys_dir = out_dir / sys_id.replace("/", "_")
            sys_dir.mkdir(exist_ok=True)

            # PinderSystem provides receptor_pdb_filepath, ligand_pdb_filepath,
            # native_pdb_filepath. Flat filenames preferred.
            rec_dst = sys_dir / "receptor.pdb"
            bind_dst = sys_dir / "ligand.pdb"
            native_dst = sys_dir / "native.pdb"

            import shutil
            shutil.copy(sys_obj.receptor_pdb_filepath, rec_dst)
            shutil.copy(sys_obj.ligand_pdb_filepath, bind_dst)
            shutil.copy(sys_obj.native_pdb_filepath, native_dst)

            # Detect chains in native
            from backend.dockq_scorer import _ChainSelector  # for detection helper
            rec_chains = _detect_chains(rec_dst)
            bind_chains = _detect_chains(bind_dst)

            entries.append({
                "pdb_code": sys_id,
                "receptor_pdb": str(rec_dst),
                "binder_pdb": str(bind_dst),
                "native_pdb": str(native_dst),
                "native_receptor_chains": rec_chains,
                "native_binder_chains": bind_chains,
                "category": row.get("difficulty", "Unknown"),
                "description": f"PINDER {subset}",
                "source": f"PINDER-{subset}",
            })
        except Exception as e:
            print(f"  Skip {sys_id}: {e}", file=sys.stderr)

    return entries


def _detect_chains(pdb_path: Path) -> list[str]:
    chains = []
    for line in pdb_path.read_text().splitlines():
        if line.startswith("ATOM") and line[21] not in chains:
            chains.append(line[21])
    return chains


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--subset", required=True, choices=["PINDER-S", "PINDER-XL", "PINDER-AF2"],
                   help="Which PINDER test set to pull")
    p.add_argument("--type", choices=["holo", "apo", "predicted"], default=None,
                   help="(PINDER-AF2 only) holo/apo/predicted subset")
    p.add_argument("--out", required=True, help="Where to stage downloaded structures")
    p.add_argument("--index", required=True, help="Path to write index.json")
    p.add_argument("--limit", type=int, default=None, help="Cap number of systems (for testing)")
    args = p.parse_args()

    entries = fetch_subset(args.subset, args.type, Path(args.out), args.limit)
    Path(args.index).write_text(json.dumps(entries, indent=2))
    print(f"\nWrote {len(entries)} entries → {args.index}")
    print(f"Use with: benchmark_runner_custom.py --index {args.index} --output <out>")


if __name__ == "__main__":
    main()
