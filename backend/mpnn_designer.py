#!/usr/bin/env python3
"""
mpnn_designer.py — ProteinMPNN interface redesign wrapper.

Given a docked complex (chain A = receptor, chain B = binder), redesigns
interface residues on the binder using ProteinMPNN, returning ranked sequences.

Exposes:
  run_mpnn_design(complex_pdb, output_dir, binder_chain, receptor_chains,
                  interface_residues, n_seqs, temperature) -> list[dict]
"""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

# Path to the venv Python that has proteinmpnn installed
_VENV_PYTHON = Path(__file__).resolve().parent.parent / "venv" / "bin" / "python3"
_WEIGHTS_DIR = None  # auto-detected from package


def _find_weights_dir() -> str:
    """Locate bundled ProteinMPNN vanilla weights directory."""
    import pkg_resources
    data_dir = Path(pkg_resources.resource_filename("proteinmpnn", "data"))
    vanilla = data_dir / "vanilla_model_weights"
    return str(vanilla)


def run_mpnn_design(
    complex_pdb: Path,
    output_dir: Path,
    binder_chain: str = "B",
    receptor_chains: list[str] | None = None,
    interface_residue_ids: list[int] | None = None,
    n_seqs: int = 10,
    temperature: float = 0.1,
    model_name: str = "v_48_020",
) -> list[dict]:
    """
    Run ProteinMPNN to redesign binder interface residues.

    Args:
        complex_pdb: Path to docked complex PDB (receptor=A, binder=binder_chain)
        output_dir: Where to write ProteinMPNN output
        binder_chain: Chain ID of the binder to redesign (default "B")
        receptor_chains: Receptor chain IDs to hold fixed (default ["A"])
        interface_residue_ids: Residue sequence numbers on binder to redesign.
                               If None, redesigns all binder residues.
        n_seqs: Number of sequences to generate
        temperature: Sampling temperature (0.1=conservative, 0.3=diverse)
        model_name: ProteinMPNN model variant

    Returns:
        List of dicts sorted by score (best first):
          { sequence, score, recovery, rank, chain }
    """
    if receptor_chains is None:
        receptor_chains = ["A"]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    python = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else "python3"

    # Build fixed-positions JSON: fix all receptor residues + non-interface binder residues
    fixed_jsonl = None
    if interface_residue_ids is not None:
        # Read all residue IDs on binder from PDB
        all_binder_resids = _get_residue_ids(complex_pdb, binder_chain)
        fixed_binder = sorted(set(all_binder_resids) - set(interface_residue_ids))

        if fixed_binder:
            pdb_stem = complex_pdb.stem
            fixed_dict = {pdb_stem: {binder_chain: fixed_binder}}
            fixed_jsonl = output_dir / "fixed_positions.jsonl"
            with open(fixed_jsonl, "w") as f:
                json.dump(fixed_dict, f)
                f.write("\n")

    # NOTE: don't pass --path-to-model-weights — the proteinmpnn pip package
    # has a bug where setting this flag leaves checkpoint_path unbound. The
    # default path (pkg_resources lookup) finds the bundled vanilla weights.
    cmd = [
        python, "-m", "proteinmpnn.protein_mpnn_run",
        "--pdb-path", str(complex_pdb),
        "--out-folder", str(output_dir),
        "--num-seq-per-target", str(n_seqs),
        "--sampling-temp", str(temperature),
        "--pdb-path-chains", binder_chain,
        "--model-name", model_name,
        "--suppress-print", "1",
    ]
    if fixed_jsonl:
        cmd += ["--fixed-positions-jsonl", str(fixed_jsonl)]

    # Cap thread counts — on 100+ core nodes torch oversubscribes and a 0.4s
    # forward pass turns into 25+ minutes of thread contention. 8 threads is
    # the sweet spot for this small model.
    env = os.environ.copy()
    env.update({
        "OMP_NUM_THREADS": "8",
        "MKL_NUM_THREADS": "8",
        "OPENBLAS_NUM_THREADS": "8",
    })
    subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)

    return _parse_mpnn_output(output_dir, complex_pdb.stem, binder_chain)


def _get_residue_ids(pdb_path: Path, chain: str) -> list[int]:
    """Extract all residue sequence numbers for a given chain from a PDB."""
    seen = []
    with open(pdb_path) as f:
        for line in f:
            if line.startswith(("ATOM", "HETATM")) and line[21] == chain:
                try:
                    resid = int(line[22:26].strip())
                    if resid not in seen:
                        seen.append(resid)
                except ValueError:
                    pass
    return seen


def _parse_mpnn_output(output_dir: Path, pdb_stem: str, binder_chain: str) -> list[dict]:
    """
    Parse ProteinMPNN FASTA output.

    Output file: output_dir/seqs/{pdb_stem}.fa
    Header format: >T=0.1, SAMPLE=1, score=-1.2345, seq_recovery=0.82
    """
    seqs_dir = output_dir / "seqs"
    fa_file = seqs_dir / f"{pdb_stem}.fa"

    if not fa_file.exists():
        # Try glob in case name differs
        candidates = list(seqs_dir.glob("*.fa"))
        if not candidates:
            return []
        fa_file = candidates[0]

    results = []
    current_header = None
    current_seq = ""

    with open(fa_file) as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if current_header and current_seq:
                    results.append(_parse_header(current_header, current_seq, binder_chain))
                current_header = line[1:]
                current_seq = ""
            else:
                current_seq += line

    if current_header and current_seq:
        results.append(_parse_header(current_header, current_seq, binder_chain))

    # Skip the wild-type (first) entry, keep designed sequences
    designed = [r for r in results if r.get("sample", 0) > 0]
    designed.sort(key=lambda x: x["score"])  # lower score = better (negative log prob)

    for i, r in enumerate(designed):
        r["rank"] = i + 1

    return designed


def _parse_header(header: str, sequence: str, chain: str) -> dict:
    """Parse ProteinMPNN FASTA header into structured dict."""
    result = {"raw_header": header, "sequence": sequence, "chain": chain}

    m = re.search(r"score=([0-9.\-]+)", header)
    if m:
        result["score"] = round(float(m.group(1)), 4)

    m = re.search(r"seq_recovery=([0-9.]+)", header)
    if m:
        result["recovery"] = round(float(m.group(1)), 4)

    m = re.search(r"sample=(\d+)", header, re.IGNORECASE)
    if m:
        result["sample"] = int(m.group(1))

    m = re.search(r"T=([0-9.]+)", header)
    if m:
        result["temperature"] = float(m.group(1))

    return result
