#!/usr/bin/env python3
"""Interactive setup for ProteinDock config.json.

Prompts for the paths that are always cluster-specific (Rosetta binary,
Rosetta database, PyRosetta database, SLURM account, etc.) and writes them
into config.json. If a value is left blank, the current one is kept.

Run once after ./install.sh — you can re-run any time to change a path.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = ROOT / "config.json"
EXAMPLE = ROOT / "config.example.json"


def load() -> dict:
    if CFG.exists():
        return json.loads(CFG.read_text())
    if EXAMPLE.exists():
        return json.loads(EXAMPLE.read_text())
    raise FileNotFoundError("Neither config.json nor config.example.json exists.")


def ask(label: str, current: str | None, *, is_path: bool = False) -> str:
    shown = current if current else "(not set)"
    resp = input(f"  {label}\n    [{shown}]\n    > ").strip()
    if not resp:
        return current or ""
    if is_path:
        p = Path(resp).expanduser()
        if not p.exists():
            print(f"    ! Warning: {p} does not exist. Saving anyway.")
        return str(p)
    return resp


def main() -> None:
    cfg = load()
    print("ProteinDock configuration — press Enter to keep the current value.\n")

    print("Rosetta:")
    r = cfg.setdefault("rosetta", {})
    r["clean_pdb"]        = ask("clean_pdb path",        r.get("clean_pdb"),        is_path=True)
    r["rosetta_scripts"]  = ask("rosetta_scripts binary",r.get("rosetta_scripts"),  is_path=True)
    r["database"]         = ask("Rosetta database dir",  r.get("database"),         is_path=True)

    print("\nTemplates (Rosetta XMLs / options — see backend/templates/):")
    t = cfg.setdefault("templates", {})
    for k in ("docking_xml", "docking_options",
              "ala_scan_wt_xml", "ala_scan_mut_xml", "ala_scan_options"):
        t[k] = ask(k, t.get(k), is_path=True)

    print("\nSLURM:")
    s = cfg.setdefault("slurm", {})
    s["account"]      = ask("account",                s.get("account"))
    s["default_time"] = ask("default_time (HH:MM:SS)",s.get("default_time"))
    s["default_cpus"] = int(ask("default_cpus",       str(s.get("default_cpus", 4))) or 4)

    print("\nColabFold (optional; leave blank if not installed):")
    c = cfg.setdefault("colabfold", {})
    c["conda_base"] = ask("conda_base",  c.get("conda_base"), is_path=True)
    c["env_name"]   = ask("env_name",    c.get("env_name") or "colabfold")

    print("\nPyMOL (optional):")
    p = cfg.setdefault("pymol", {})
    p["command"]        = ask("pymol command",  p.get("command") or "pymol")
    p["headless_flags"] = ask("headless flags", p.get("headless_flags") or "-cq")

    print("\nWorkdir (where jobs run):")
    wd = ask("workdir", cfg.get("workdir"), is_path=True)
    cfg["workdir"] = wd or None

    # Backup existing config, then write
    if CFG.exists():
        shutil.copy2(CFG, CFG.with_suffix(".json.bak"))
    CFG.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"\nWrote {CFG} (backup at {CFG}.bak if it existed).")
    print("Next: ./run.sh")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
