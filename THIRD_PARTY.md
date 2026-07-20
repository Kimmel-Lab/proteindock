# Required and optional third-party software

ProteinDock is a **thin wrapper**. It does not bundle, redistribute, or fork the
scientific tools listed below — you obtain each of them yourself under their
own license. This is by design: several are non-redistributable under their
respective agreements.

> ⚠ **Non-commercial by default.** Rosetta, PyRosetta, and AlphaFold 3 (weights + outputs)
> are all licensed for non-commercial academic use only. Any commercial use of ProteinDock
> requires you to independently obtain commercial licenses:
> - **Rosetta / PyRosetta**: UW CoMotion (`license@uw.edu`)
> - **AlphaFold 3**: Google DeepMind (`alphafold@google.com`)
>
> If you are commissioning or using ProteinDock in a commercial context, verify
> that your organization holds an appropriate commercial license for every tool
> under **"Required"** below (and for AlphaFold 3 if you use Mode 2).

---

## Required

### Rosetta
- **What we call**: `rosetta_scripts` (all-atom docking, FastRelax, InterfaceAnalyzer)
- **License**: RosettaCommons Software Access Agreement — free for academic, paid for commercial
- **Where to get**: <https://rosettacommons.org/software/download>
- **Cite**: Leaver-Fay et al., *Methods in Enzymology* 2011; Alford et al., *JCTC* 2017

### PyRosetta
- **What we call**: `pyrosetta` (Python bindings to Rosetta used across `backend/pipeline.py`)
- **License**: Separate agreement from RosettaCommons; requires an academic or commercial license
- **Where to get**: <https://www.pyrosetta.org/downloads>
- **Cite**: Chaudhury et al., *Bioinformatics* 2010

### DockQ v2
- **What we call**: `DockQ` Python package (all scoring in `backend/dockq_scorer.py`)
- **License**: MIT
- **Where to get**: <https://github.com/bjornwallner/DockQ>
- **Cite**: Mirabello & Wallner, *Bioinformatics* 2024

---

## Optional (only if you use the corresponding feature)

### AlphaFold 3
- **Used by**: Mode 2 scoring (source of candidate poses), and the AF3-Boltz-PDT arbitration
- **License**: Model weights are covered by DeepMind's AF3 non-commercial terms and require approval; the source code is under a non-standard license
- **Two ways to feed AF3 predictions into ProteinDock — pick whichever fits:**
  1. **AlphaFold Server (recommended for most users)** — free, browser-based, no install: <https://alphafoldserver.com/>. Submit your receptor+binder sequences, download the top-ranked model(s), then use ProteinDock's Docking page to upload the resulting PDB as the starting complex. **No GPU or DeepMind approval required.**
  2. **Local AlphaFold 3 install** — required only if you want ProteinDock's backend to auto-generate AF3 predictions (via `backend/af3_predictor.py`). Needs: DeepMind weight-access approval, NVIDIA A100/H100-class GPU, ~200 GB reference databases, the [AF3 repository](https://github.com/google-deepmind/alphafold3), and paths set in `config.json` under an `alphafold3` section.
- **What Mode 2 actually needs from you**: one PDB per candidate pose. It rescores those poses with Rosetta's interface energy under `fa_elec × 1.5` — no AF3 code or weights ever run inside ProteinDock.
- **AF3 Output Terms propagate.** PDBs downloaded from AlphaFold Server or produced by a local AF3 install are covered by DeepMind's [AlphaFold 3 Output Terms of Use](https://github.com/google-deepmind/alphafold3/blob/main/OUTPUT_TERMS_OF_USE.md). Those terms follow the pose into every downstream step (including ProteinDock rescoring, publication, and sharing). In practice this means anything you publish or distribute that derives from an AF3 pose stays non-commercial. ProteinDock does not enforce this — you do, by not pushing AF3-derived outputs into a commercial pipeline.
- **Cite**: Abramson et al., *Nature* 2024

### Boltz-2
- **Used by**: Mode 2 scoring (secondary predictor for AF3-Boltz-PDT arbitration)
- **License**: MIT
- **Where to get**: <https://github.com/jwohlwend/boltz>. Boltz-2 is far cheaper to run locally than AF3 — the standard `pip install boltz` on a machine with any modern NVIDIA GPU is enough. No approval process.
- **Alternative**: same idea as AF3 — you can also just submit sequences to a hosted service, download the top-1 PDB, and upload it to ProteinDock's Docking page.
- **Cite**: Passaro et al., 2025 (Boltz-2 preprint)

### HADDOCK3
- **Used by**: baseline comparison only (`backend/benchmark.py` — HADDOCK-local, HADDOCK-AIR)
- **License**: Free for academic non-commercial; commercial requires Utrecht University license
- **Where to get**: <https://github.com/haddocking/haddock3>
- **Cite**: Giulini et al., *JCIM* 2025

### ColabFold (MMseqs2 MSA server)
- **Used by**: Boltz-2's MSA construction (only when `use_msa_server: true` in a manifest)
- **License**: MIT (ColabFold), GPLv3 (MMseqs2)
- **Where to get**: <https://github.com/sokrypton/ColabFold>
- **Cite**: Mirdita et al., *Nature Methods* 2022

### PyMOL
- **Used by**: optional headless rendering of best-model images (`backend/pipeline.py` visualisation helpers)
- **License**: Academic-free (Schrödinger open-source distribution) or paid Schrödinger license
- **Where to get**: <https://pymol.org/> or `conda install -c conda-forge pymol-open-source`

---

## Python dependencies (permissively licensed, installed by `install.sh`)

Installed automatically via pip; each is BSD/MIT/Apache-style:

- `fastapi`, `uvicorn` (MIT)
- `pydantic`, `python-multipart` (MIT)
- `biopython` (BSD-3)
- `numpy`, `scipy` (BSD-3)
- `requests`, `aiofiles` (Apache-2.0 / Apache-2.0)

## Frontend dependencies

The React frontend uses standard permissively licensed packages (React, Vite,
shadcn/ui, TanStack Query, Tailwind CSS). Full list in `frontend/package.json`.
`3Dmol.js` (BSD-3) ships as a bundled asset with its license notice preserved
in the source.

---

*This file is a good-faith summary and is not legal advice. If your use case
raises questions, consult your institution's tech-transfer office and the
official license documents linked above.*
