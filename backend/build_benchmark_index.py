#!/usr/bin/env python3
"""
build_benchmark_index.py — Convert a benchmark dataset to the unified index format.

Supported sources:
  --source db55   <db55_structures_dir>
  --source pinder <pinder_subset_dir>  (expects pinder layout: <id>/{receptor,ligand,native}.pdb)
  --source custom <user_dir>           (user must follow custom layout)

Output: index.json suitable for benchmark_runner_custom.py.
"""

import argparse
import json
from pathlib import Path


def _detect_chains(pdb_path: Path) -> list[str]:
    chains = []
    with open(pdb_path) as f:
        for line in f:
            if line.startswith("ATOM") and line[21] not in chains:
                chains.append(line[21])
    return chains


def _combine_chains(rec_b: Path, lig_b: Path, out_native: Path) -> None:
    parts = []
    for f in (rec_b, lig_b):
        for line in open(f):
            if line.startswith(("ATOM", "HETATM")):
                parts.append(line)
        parts.append("TER\n")
    parts.append("END\n")
    out_native.write_text("".join(parts))


def from_db55(structures_dir: Path, pdb_codes: list[str], stage_dir: Path) -> list[dict]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for code in pdb_codes:
        r_u = structures_dir / f"{code}_r_u.pdb"
        l_u = structures_dir / f"{code}_l_u.pdb"
        r_b = structures_dir / f"{code}_r_b.pdb"
        l_b = structures_dir / f"{code}_l_b.pdb"
        if not all(f.exists() for f in (r_u, l_u, r_b, l_b)):
            print(f"SKIP {code}: missing files")
            continue
        native = stage_dir / f"{code}_native.pdb"
        _combine_chains(r_b, l_b, native)
        entries.append({
            "pdb_code": code,
            "receptor_pdb": str(r_u),
            "binder_pdb":   str(l_u),
            "native_pdb":   str(native),
            "native_receptor_chains": _detect_chains(r_b),
            "native_binder_chains":   _detect_chains(l_b),
            "source": "DB5.5",
        })
    return entries


def from_pinder(pinder_dir: Path) -> list[dict]:
    """
    Expects pinder subset layout:
      <pinder_dir>/<id>/receptor.pdb
                       /ligand.pdb
                       /native.pdb        (bound complex)
                       /meta.json          {"rec_chains": [...], "bind_chains": [...]}

    Use the pinder Python package separately to download and pre-process, then
    point this script at the resulting directory.
    """
    entries = []
    for sub in sorted(pinder_dir.iterdir()):
        if not sub.is_dir():
            continue
        rec, lig, native = sub/"receptor.pdb", sub/"ligand.pdb", sub/"native.pdb"
        meta_path = sub/"meta.json"
        if not all(f.exists() for f in (rec, lig, native, meta_path)):
            continue
        meta = json.loads(meta_path.read_text())
        entries.append({
            "pdb_code": sub.name,
            "receptor_pdb": str(rec),
            "binder_pdb":   str(lig),
            "native_pdb":   str(native),
            "native_receptor_chains": meta["rec_chains"],
            "native_binder_chains":   meta["bind_chains"],
            "source": "PINDER",
        })
    return entries


def _list_all_db55_codes(structures_dir: Path) -> list[str]:
    """Find every PDB code in DB5.5 that has all 4 files (_r_u, _l_u, _r_b, _l_b)."""
    codes = set()
    for f in structures_dir.glob("*_r_u.pdb"):
        code = f.name[:4]
        if all((structures_dir / f"{code}{s}.pdb").exists()
               for s in ("_r_u", "_l_u", "_r_b", "_l_b")):
            codes.add(code)
    return sorted(codes)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", choices=["db55", "pinder"], required=True)
    p.add_argument("--dir", required=True, help="Source data directory")
    p.add_argument("--codes", help="DB5.5: comma-separated PDB codes (subset)")
    p.add_argument("--all", action="store_true",
                   help="DB5.5: auto-detect every PDB code with all 4 files (for full 254-target benchmark)")
    p.add_argument("--out", required=True, help="Output index.json path")
    p.add_argument("--stage", default="benchmark_stage", help="Where to write derived natives")
    args = p.parse_args()

    if args.source == "db55":
        if args.all:
            codes = _list_all_db55_codes(Path(args.dir))
            print(f"Found {len(codes)} DB5.5 entries with all 4 files")
        elif args.codes:
            codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        else:
            raise SystemExit("--codes or --all required for db55 source")
        entries = from_db55(Path(args.dir), codes, Path(args.stage))
    else:
        entries = from_pinder(Path(args.dir))

    Path(args.out).write_text(json.dumps(entries, indent=2))
    print(f"Wrote {len(entries)} entries to {args.out}")


if __name__ == "__main__":
    main()
