# ProteinDock

A physics-informed layer for improving protein–protein docking reliability, built on Rosetta.

**Web app**: https://proteindock.com
**Repo**: this one — hosts the backend source, the frontend source, and install scripts.

## How it's deployed

The frontend runs at [proteindock.com](https://proteindock.com). Backends are **user-hosted**: you install this repo on a machine that has PyRosetta + Rosetta available (typically an HPC login node), start the FastAPI server, and paste the URL into the frontend's Settings dialog. Your data never leaves your compute environment.

## Required third-party software

ProteinDock is a thin wrapper. It does **not** bundle or redistribute the tools below — you install them yourself under their own licenses. Full details, download links, and citations are in [`THIRD_PARTY.md`](./THIRD_PARTY.md).

> ⚠ **Non-commercial by default.** Rosetta, PyRosetta, and AlphaFold 3 (if used) are licensed for **non-commercial academic use only**. Commercial use requires separate licenses from **UW CoMotion** (`license@uw.edu`, for Rosetta / PyRosetta) and **Google DeepMind** (`alphafold@google.com`, for AlphaFold 3). ProteinDock itself is MIT — the non-commercial restriction comes from the tools it calls.

| Tool | Purpose | License | Where to get |
|---|---|---|---|
| **Rosetta** | Docking engine (`rosetta_scripts`) | RosettaCommons | <https://rosettacommons.org/software/download> |
| **PyRosetta** | Python bindings for FastRelax + InterfaceAnalyzer | RosettaCommons | <https://www.pyrosetta.org/downloads> |
| **DockQ v2** | Complex quality scoring | MIT | `pip install DockQ` |
| AlphaFold 3 *(optional)* | Mode 2 input poses | DeepMind terms | Local install, **or** just use the free [AlphaFold Server](https://alphafoldserver.com/) and upload the resulting PDB |
| Boltz-2 *(optional)* | Mode 2 secondary predictor | MIT | `pip install boltz` (GPU) |
| HADDOCK3 *(optional)* | Baseline comparison only | Academic-free | <https://github.com/haddocking/haddock3> |
| PyMOL *(optional)* | Headless model rendering | Academic-free | conda-forge |

For most users, the two required items are Rosetta + PyRosetta. Mode 2 can run without any local AF3 install — just feed it PDBs downloaded from the AlphaFold Server.

## Install (backend)

Requires: Python 3.10+ and the two required tools above.

```bash
git clone https://github.com/Kimmel-Lab/proteindock.git
cd proteindock
./install.sh          # creates venv, installs Python deps (NOT Rosetta / PyRosetta)
python configure.py   # interactive: fill Rosetta paths, SLURM account, etc.
./run.sh              # starts backend on http://0.0.0.0:8000
```

`install.sh` will warn if PyRosetta isn't importable and print instructions to install the wheel into the venv.

Then open <https://proteindock.com>, click the ⚙ Settings icon, and paste your backend URL.

## What it does

**Mode 1 — Docking layer.** Refines physics-based docking with pre-relax and a reweighted `fa_elec × 1.5` score function.

**Mode 2 — Scoring layer.** Reranks foundation-model predictions (AlphaFold3, Boltz-2) by Rosetta interface energy.

## Repo layout

```
backend/          FastAPI app + pipeline (Python)
frontend/         React/Vite app (deployed to proteindock.com)
docs/             Hosted landing page source
config.example.json   Template config
install.sh · configure.py · run.sh   One-command backend setup
```

## Citation

> Rajagopal, G., Spina, S. C., Bailey Jr., J. S., & Kimmel, B. R. (2026).
> *ProteinDock: A physics-informed layer to improve protein–protein docking reliability.*
> Manuscript in preparation.

## Contact

Blaise R. Kimmel, PhD ([kimmel.85@osu.edu](mailto:kimmel.85@osu.edu))
