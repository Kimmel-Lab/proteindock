# ProteinDock

A physics-informed layer for improving protein–protein docking reliability, built on Rosetta.

**Web app**: https://proteindock.com
**Repo**: this one — hosts the backend source, the frontend source, and install scripts.

## How it's deployed

The frontend runs at [proteindock.com](https://proteindock.com). Backends are **user-hosted**: you install this repo on a machine that has PyRosetta + Rosetta available (typically an HPC login node), start the FastAPI server, and paste the URL into the frontend's Settings dialog. Your data never leaves your compute environment.

## Install (backend)

Requires: Python 3.10+, [PyRosetta](https://www.pyrosetta.org/downloads) (licensed separately from RosettaCommons), and a Rosetta build for `rosetta_scripts`.

```bash
git clone https://github.com/Kimmel-Lab/proteindock.git
cd proteindock
./install.sh          # creates venv, installs Python deps
python configure.py   # interactive: fill Rosetta paths, SLURM account, etc.
./run.sh              # starts backend on http://0.0.0.0:8000
```

Then open https://proteindock.com, click the ⚙ Settings icon, and paste your backend URL.

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
