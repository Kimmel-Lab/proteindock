"""
config.py -- Load site-specific configuration for ProteinDock.

Reads protein_web/config.json (adjacent to the backend/ directory).
Falls back to hardcoded OSC defaults if the file is missing.
"""

import json
import os
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def _load_config() -> dict:
    """Load config.json, returning empty dict if missing."""
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    return {}


_cfg = _load_config()

# ── Rosetta paths ────────────────────────────────────────────
_rosetta = _cfg.get("rosetta", {})

ROSETTA_CLEAN_PDB = _rosetta.get(
    "clean_pdb",
    "/fs/scratch/PAS2959/Protein_Design/ROSETTA/"
    "rosetta.binary.linux.release-387/main/tools/"
    "protein_tools/scripts/clean_pdb.py",
)

ROSETTA_SCRIPTS = _rosetta.get(
    "rosetta_scripts",
    "/fs/scratch/PAS2959/Protein_Design/ROSETTA/"
    "rosetta.binary.linux.release-387/main/source/bin/"
    "rosetta_scripts.static.linuxgccrelease",
)

ROSETTA_DATABASE = _rosetta.get(
    "database",
    "/fs/scratch/PAS2959/Protein_Design/ROSETTA/"
    "rosetta.binary.linux.release-387/main/database",
)

# ── Template paths ───────────────────────────────────────────
_templates = _cfg.get("templates", {})

DOCKING_XML_SRC = Path(_templates.get(
    "docking_xml",
    "/users/PAS2959/graja/docking_stuff/docking_full.xml",
))

DOCKING_OPTIONS_SRC = Path(_templates.get(
    "docking_options",
    "/users/PAS2959/graja/docking_stuff/docking.options.txt",
))

ALA_SCAN_WT_XML = Path(_templates.get(
    "ala_scan_wt_xml",
    "/users/PAS2959/graja/docking_stuff/ala_scan_wt.xml",
))

ALA_SCAN_MUT_XML = Path(_templates.get(
    "ala_scan_mut_xml",
    "/users/PAS2959/graja/docking_stuff/ala_scan_mut.xml",
))

ALA_SCAN_OPTIONS_SRC = Path(_templates.get(
    "ala_scan_options",
    "/users/PAS2959/graja/docking_stuff/ala_scan.options.txt",
))

# ── SLURM ────────────────────────────────────────────────────
_slurm = _cfg.get("slurm", {})

SLURM_ACCOUNT = _slurm.get("account", "PAS2959")
SLURM_DEFAULT_TIME = _slurm.get("default_time", "00:10:00")
SLURM_DEFAULT_CPUS = _slurm.get("default_cpus", 4)
SLURM_ALA_SCAN_TIME = _slurm.get("ala_scan_time", "00:30:00")
SLURM_ALA_SCAN_CPUS = _slurm.get("ala_scan_cpus", 4)
SLURM_NCAA_OPT_TIME = _slurm.get("ncaa_opt_time", "02:00:00")
SLURM_NCAA_OPT_CPUS = _slurm.get("ncaa_opt_cpus", 4)

# ── ColabFold ────────────────────────────────────────────────
_colabfold = _cfg.get("colabfold", {})

CONDA_BASE = _colabfold.get(
    "conda_base",
    "/apps/spack/0.21/pitzer/linux-rhel9-skylake/miniconda3/gcc/11.4.1/24.1.2-py310-ghbxrie",
)

CONDA_ENV = _colabfold.get("env_name", "colabfold")

# ── PyMOL ────────────────────────────────────────────────────
_pymol = _cfg.get("pymol", {})

PYMOL_COMMAND = _pymol.get("command", "module load pymol/2.4.0 && pymol")
PYMOL_HEADLESS_FLAGS = _pymol.get("headless_flags", "-cq")

# ── ncAA Optimization ───────────────────────────────────────
_ncaa = _cfg.get("ncaa", {})

NCAA_OPTIMIZER_SCRIPT = Path(_ncaa.get(
    "optimizer_script",
    "/users/PAS2959/graja/ncAA/ncAA/ncaa_optimizer.py",
))

NCAA_SCAN_SCRIPT = Path(_ncaa.get(
    "scan_script",
    "/users/PAS2959/graja/ncAA/ncAA/n_cAAscan.py",
))

NCAA_FAKE_ROTLIB = Path(_ncaa.get(
    "fake_rotlib_script",
    "/users/PAS2959/graja/ncAA/ncAA/fake_rotlib.py",
))

NCAA_MOLFILE_TO_PARAMS = Path(_ncaa.get(
    "molfile_to_params",
    "/fs/scratch/PAS2959/Protein_Design/ROSETTA/rosetta.binary.linux.release-387/"
    "main/source/scripts/python/public/molfile_to_params_polymer.py",
))

NCAA_PYROSETTA_ENV = _ncaa.get("pyrosetta_env", "pyrosetta")
NCAA_CONDA_BASE = _ncaa.get("conda_base", CONDA_BASE)

NCAA_PYROSETTA_DB = Path(_ncaa.get(
    "pyrosetta_database",
    "/fs/scratch/PAS2959/Protein_Design/PyRosetta/"
    "PyRosetta4.Release.python312.linux.release-387/setup/pyrosetta/database",
))

# ── Work directory ───────────────────────────────────────────
_workdir_cfg = _cfg.get("workdir", None)

if _workdir_cfg:
    DEFAULT_WORKDIR = Path(_workdir_cfg)
else:
    DEFAULT_WORKDIR = Path(os.environ.get(
        "PROTEINWEB_WORKDIR", str(Path.home() / "protein_web_jobs"),
    ))

# Surface gap for merging (Angstroms)
SURFACE_GAP = 2.0
