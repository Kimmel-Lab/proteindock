#!/usr/bin/env python3
"""
pipeline.py

Pure backend API for the Rosetta docking pipeline.

This module exposes functions that your FastAPI backend can call:
- fetch_pdb
- copy_uploaded_pdb
- write_fasta
- run_colabfold
- run_clean_pdb
- normalize_chains
- sanitize_pdb
- combine_in_python
- parse_fasc_and_find_best
- visualize_best_model
- open_best_model_in_pymol
"""

import shutil
import subprocess
import tempfile
from pathlib import Path
import re
import glob

import requests
import numpy as np
from Bio.PDB import PDBParser, PDBIO

# ============================================================
# CONFIG (loaded from config.json — see backend/config.py)
# ============================================================

from backend.config import (
    ROSETTA_CLEAN_PDB,
    ROSETTA_SCRIPTS,
    ROSETTA_DATABASE,
    DOCKING_XML_SRC,
    DOCKING_OPTIONS_SRC,
    ALA_SCAN_WT_XML,
    ALA_SCAN_MUT_XML,
    ALA_SCAN_OPTIONS_SRC,
    SLURM_ACCOUNT,
    CONDA_BASE,
    CONDA_ENV,
    PYMOL_COMMAND,
    PYMOL_HEADLESS_FLAGS,
    DEFAULT_WORKDIR,
    SURFACE_GAP,
    NCAA_OPTIMIZER_SCRIPT,
    NCAA_PYROSETTA_ENV,
    NCAA_CONDA_BASE,
    SLURM_NCAA_OPT_TIME,
    SLURM_NCAA_OPT_CPUS,
    NCAA_PYROSETTA_DB,
)

# Default locations for docking outputs (used by parse_fasc_and_find_best / visualize_best_model)
FASC_PATH = DEFAULT_WORKDIR / "docking.fasc"
PDB_GLOB = str(DEFAULT_WORKDIR / "complex_input_full_*.pdb")


# ============================================================
# BEST MODEL PARSER (FASC + PDB MATCHING)
# ============================================================

def extract_index(desc: str) -> int | None:
    """
    Extract numeric suffix like 0003 from 'complex_input_full_0003'.
    """
    m = re.search(r"_(\d+)$", desc)
    return int(m.group(1)) if m else None


def parse_fasc_all_models(
    fasc_path: Path | None = None, pdb_glob: str | None = None
) -> list[dict]:
    """
    Parse a Rosetta .fasc file and return ALL models with detailed scores.

    Returns a list of dicts, each containing all score components plus:
        {
          "score": float (total_score),
          "desc": str,
          "index": int,
          "pdb_path": str | None
        }
    """
    fasc_path = fasc_path or FASC_PATH
    pdb_glob = pdb_glob or PDB_GLOB

    if not fasc_path.exists():
        raise FileNotFoundError(f"Missing docking.fasc at {fasc_path}")

    lines = fasc_path.read_text().splitlines()
    
    # Parse header to get column order (line with "SCORE:" and "total_score")
    header_line = None
    header_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("SCORE:") and "total_score" in line:
            header_line = line
            header_idx = i
            break
    
    if not header_line:
        raise RuntimeError("Could not find SCORE header line in docking.fasc")
    
    # Parse header columns (skip "SCORE:" prefix)
    # Split on whitespace but preserve structure
    header_parts = header_line.split()
    # Find where "description" is in header
    desc_idx = -1
    for i, part in enumerate(header_parts):
        if part == "description":
            desc_idx = i
            break
    
    # Get all column names except "SCORE:" and "description"
    column_names = header_parts[1:desc_idx] if desc_idx > 0 else header_parts[1:]
    
    models: list[dict] = []
    
    # Find all PDB files upfront for matching
    candidates = sorted(glob.glob(pdb_glob))
    pdb_map: dict[int, Path] = {}
    for c in candidates:
        idx = extract_index(Path(c).stem)
        if idx is not None:
            pdb_map[idx] = Path(c)

    # Parse data lines (skip header and SEQUENCE lines)
    for line in lines[header_idx + 1:]:
        if not line.startswith("SCORE:") or "total_score" in line:
            continue  # Skip non-data lines

        parts = line.split()
        if len(parts) < 3:  # Need at least SCORE:, value, description
            continue

        # Build model dict from columns
        model: dict = {}
        
        # Parse all score columns (skip "SCORE:" at index 0)
        # The number of data values should match column_names
        # Description is always the last field
        num_data_values = len(parts) - 2  # -2 for "SCORE:" and description
        
        for i, col_name in enumerate(column_names):
            if i < num_data_values:
                try:
                    model[col_name] = float(parts[i + 1])  # +1 to skip "SCORE:"
                except (ValueError, IndexError):
                    model[col_name] = None
            else:
                model[col_name] = None
        
        # Description is last
        desc = parts[-1]
        model["desc"] = desc
        model["index"] = extract_index(desc)
        
        # Use total_score as "score" for compatibility
        model["score"] = model.get("total_score", 0.0)
        
        # Find matching PDB
        idx = model["index"]
        if idx is not None and idx in pdb_map:
            model["pdb_path"] = str(pdb_map[idx])
        else:
            model["pdb_path"] = None

        models.append(model)

    if not models:
        raise RuntimeError("No SCORE lines parsed in docking.fasc.")

    return models


def parse_fasc_and_find_best(
    fasc_path: Path | None = None, pdb_glob: str | None = None
) -> dict:
    """
    Parse a Rosetta .fasc file and return the best-scoring model.

    Returns a dict:
        {
          "score": float,
          "desc": str,
          "index": int,
          "pdb_path": Path
        }
    """
    all_models = parse_fasc_all_models(fasc_path, pdb_glob)
    
    # Find best (lowest score)
    best = min(all_models, key=lambda x: x["score"])
    
    # Ensure pdb_path is Path object for backward compatibility
    if best.get("pdb_path"):
        best["pdb_path"] = Path(best["pdb_path"])
    
    return best


# ============================================================
# VISUALIZATION HELPERS
# ============================================================

_VIS_CHAIN_COLORS = [
    "0x2dd4bf", "0xfb923c", "0xa78bfa", "0x34d399", "0xf472b6",
    "0x60a5fa", "0xfbbf24", "0xf87171", "0x4ade80", "0xc084fc",
]
_VIS_IFACE_COLORS = ["0xec4899", "0xf97316", "0x8b5cf6", "0x10b981", "0xef4444"]


def _detect_chains(pdb_path: Path) -> list[str]:
    """Detect unique chain IDs in order from a PDB file."""
    chains: list[str] = []
    seen: set[str] = set()
    with open(pdb_path) as fh:
        for line in fh:
            if line.startswith(("ATOM", "HETATM")):
                ch = line[21].strip()
                if ch and ch not in seen:
                    seen.add(ch)
                    chains.append(ch)
    return chains or ["A", "B"]


def _build_pymol_script(pdb_path: Path, img_path: Path, chains: list[str]) -> str:
    """Build a PyMOL script for N chains with dynamic coloring."""
    color_lines = []
    surface_lines = []
    for i, ch in enumerate(chains):
        c = _VIS_CHAIN_COLORS[i % len(_VIS_CHAIN_COLORS)]
        color_lines.append(f"color {c}, chain {ch}")
        surface_lines.append(f"set surface_color, {c}, chain {ch}")

    show_sel = " or ".join(f"chain {ch}" for ch in chains)

    # Interface: first chain vs rest
    iface = ""
    if len(chains) >= 2:
        rest_sel = " or ".join(f"chain {ch}" for ch in chains[1:])
        iface_colors = ""
        iface_colors += f"color {_VIS_IFACE_COLORS[0]}, interface and chain {chains[0]}\n"
        for i, ch in enumerate(chains[1:]):
            ic = _VIS_IFACE_COLORS[(i + 1) % len(_VIS_IFACE_COLORS)]
            iface_colors += f"color {ic}, interface and chain {ch}\n"
        iface = f"""
select interface_first, (chain {chains[0]} within 5 of ({rest_sel}))
select interface_rest, (({rest_sel}) within 5 of chain {chains[0]})
select interface, interface_first or interface_rest
show sticks, interface
set stick_radius, 0.15
{iface_colors}
distance hbonds, interface_first, interface_rest, 3.5, mode=2
hide labels, hbonds
set dash_color, 0xfbbf24, hbonds
set dash_gap, 0.3
set dash_width, 2.0
"""

    return f"""# ProteinDock — Docking Visualization
load {pdb_path}
bg_color white
set ray_shadow, 1
set ray_trace_mode, 1
set antialias, 2
set orthoscopic, off
set depth_cue, 1
set fog_start, 0.45
hide everything

# ── Chain coloring ({len(chains)} chains) ────────
{chr(10).join(color_lines)}
show cartoon, {show_sel}
set cartoon_fancy_helices, 1
set cartoon_smooth_loops, 1
set cartoon_flat_sheets, 1
{iface}
# ── Surface ──────────────────────────────────────
show surface, {show_sel}
{chr(10).join(surface_lines)}
set transparency, 0.75

zoom interface, 5
deselect

ray 2000,1500
png {img_path}, dpi=300
quit
"""


def visualize_best_model(
    fasc_path: Path | None = None,
    pdb_glob: str | None = None,
) -> dict:
    """
    Generate a PyMOL script + PNG for the best docking model.
    Runs PyMOL in command-line mode (headless) so it works on HPC/SSH.

    Returns:
        dict with keys: pdb_path, img_path, pml_path, desc, score
    """
    best = parse_fasc_and_find_best(fasc_path=fasc_path, pdb_glob=pdb_glob)
    best_pdb: Path = best["pdb_path"]

    pml_path = best_pdb.with_suffix(".pml")
    img_path = best_pdb.with_suffix(".png")

    # Detect chains from PDB
    chains = _detect_chains(best_pdb)
    pml_path.write_text(_build_pymol_script(best_pdb, img_path, chains))

    print("\n=====================================")
    print(" BEST DOCKING MODEL")
    print("=====================================")
    print(f"Descriptor:  {best['desc']}")
    print(f"Score:       {best['score']}")
    print(f"PDB File:    {best_pdb}")
    print(f"PNG Image:   {img_path}")
    print("=====================================")
    print("Running PyMOL in headless mode…")

    # Run PyMOL in headless mode via OSC module
    try:
        result = subprocess.run(
            ["bash", "-c", f"{PYMOL_COMMAND} {PYMOL_HEADLESS_FLAGS} " + str(pml_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            print(f"⚠️  PyMOL error (exit {result.returncode}): {result.stderr[:500]}")
        elif img_path.exists():
            print(f"✅ Image rendered → {img_path}")
        else:
            print(f"⚠️  PyMOL ran but image not found at {img_path}")
    except FileNotFoundError:
        print("⚠️  PyMOL not available — skipping image render. PML script saved for manual use.")

    return {
        "pdb_path": str(best_pdb),
        "img_path": str(img_path),
        "pml_path": str(pml_path),
        "desc": best["desc"],
        "score": best["score"],
    }


# ============================================================
# INPUT / STRUCTURE HELPERS
# ============================================================

def fetch_pdb(pdb_code: str, output_dir: Path) -> Path:
    """
    Download a PDB file from RCSB and save to output_dir.
    """
    pdb_code = pdb_code.lower().strip()
    url = f"https://files.rcsb.org/download/{pdb_code}.pdb"  # fixed spaces
    r = requests.get(url)
    r.raise_for_status()

    output_dir.mkdir(exist_ok=True, parents=True)
    out = output_dir / f"{pdb_code}.pdb"
    out.write_bytes(r.content)

    print(f"📥 Fetched {pdb_code} → {out}")
    return out


def write_fasta(sequence: str, output_dir: Path, name: str) -> Path:
    """
    Write a FASTA file for a given amino-acid sequence.
    """
    output_dir.mkdir(exist_ok=True, parents=True)
    fasta = output_dir / f"{name}.fasta"
    fasta.write_text(f">{name}\n{sequence.strip()}\n")
    return fasta


def run_colabfold(fasta_path: Path, output_dir: Path) -> Path:
    """
    Run ColabFold and return the first produced PDB path.
    Activates the 'colabfold' conda environment before running.
    Logs are saved to output_dir/colabfold.log
    """
    output_dir.mkdir(exist_ok=True, parents=True)

    # Log file path
    log_path = output_dir / "colabfold.log"

    # Build command that activates conda env and runs colabfold
    # Using bash -c to properly source conda and activate environment
    activate_cmd = f"""
source {CONDA_BASE}/etc/profile.d/conda.sh
conda activate {CONDA_ENV}
colabfold_batch "{fasta_path}" "{output_dir}" --use-gpu-relax
"""
    
    print(f"🧬 Running ColabFold prediction...")
    print(f"   Input: {fasta_path}")
    print(f"   Output: {output_dir}")
    print(f"   Log: {log_path}")
    
    # Run with output to both console and log file
    with open(log_path, "w") as log_file:
        log_file.write(f"=== ColabFold Prediction ===\n")
        log_file.write(f"Input FASTA: {fasta_path}\n")
        log_file.write(f"Output Dir: {output_dir}\n")
        log_file.write(f"Conda Env: {CONDA_ENV}\n")
        log_file.write(f"=" * 40 + "\n\n")
        
        process = subprocess.Popen(
            ["bash", "-c", activate_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Stream output to both console and log file
        for line in iter(process.stdout.readline, ''):
            if not line:
                break
            print(line, end='')  # Print to console
            log_file.write(line)  # Write to log file
            log_file.flush()
        
        process.wait()
        
        if process.returncode != 0:
            error_msg = f"ColabFold failed with exit code {process.returncode}"
            log_file.write(f"\n\nERROR: {error_msg}\n")
            raise RuntimeError(error_msg)
        
        log_file.write(f"\n\n=== ColabFold Completed Successfully ===\n")

    pdbs = list(output_dir.glob("*.pdb"))
    if not pdbs:
        raise FileNotFoundError("ColabFold produced no PDB. Check if GPU is available and CUDA is configured.")
    
    # Return the best ranked model
    ranked_pdbs = sorted([p for p in pdbs if "rank" in p.name.lower()])
    if ranked_pdbs:
        print(f"✅ Best model: {ranked_pdbs[0]}")
        return ranked_pdbs[0]
    print(f"✅ Model: {pdbs[0]}")
    return pdbs[0]


def copy_uploaded_pdb(path: str, output_dir: Path) -> Path:
    """
    Copy a user-uploaded PDB into the working directory.
    """
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(src)
    output_dir.mkdir(exist_ok=True, parents=True)
    dest = output_dir / src.name
    shutil.copy(src, dest)
    print(f"📂 Copied → {dest}")
    return dest


# ============================================================
# ROSETTA CLEAN
# ============================================================

def detect_first_chain(pdb_path: Path) -> str:
    """
    Detect the first chain ID in a PDB file.
    """
    with open(pdb_path) as fh:
        for line in fh:
            if line.startswith(("ATOM", "HETATM")):
                return line[21].strip() or "A"
    return "A"


def run_clean_pdb(input_path: Path, output_path: Path) -> None:
    """
    Run Rosetta's clean_pdb.py on a PDB and move the result to output_path.
    """
    chain = detect_first_chain(input_path)
    print(f"🧼 Cleaning {input_path.name} (chain {chain})")

    # Run clean_pdb.py from the input file's directory so output lands there
    subprocess.run(
        ["python3", ROSETTA_CLEAN_PDB, str(input_path), chain],
        check=True,
        cwd=input_path.parent  # Run from input directory so output goes there
    )

    expected = input_path.stem + f"_{chain}.pdb"
    expected_path = input_path.parent / expected
    
    # Also check current working directory as fallback
    if not expected_path.exists():
        cwd_path = Path.cwd() / expected
        if cwd_path.exists():
            expected_path = cwd_path
        else:
            raise FileNotFoundError(
                f"Rosetta output missing: checked {expected_path} and {cwd_path}"
            )

    shutil.move(str(expected_path), output_path)
    print(f"✅ Cleaned → {output_path}")


# ============================================================
# CHAIN NORMALIZER
# ============================================================

def normalize_chains(pdb_path: Path, used: set | None = None) -> tuple[Path, set]:
    """
    Ensure unique chain IDs for all models.

    Returns:
        (fixed_pdb_path, updated_used_set)
    """
    if used is None:
        used = set()

    fixed = pdb_path.with_name(pdb_path.stem + "_chains.pdb")
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    new_lines: list[str] = []
    chain_map: dict[str, str] = {}
    next_idx = len(used)

    with open(pdb_path) as fh:
        for line in fh:
            if line.startswith(("ATOM", "HETATM")):
                old = line[21]
                if old.strip() == "":
                    old = "_"

                if old not in chain_map:
                    while letters[next_idx] in used:
                        next_idx += 1
                    new_chain = letters[next_idx]
                    chain_map[old] = new_chain
                    used.add(new_chain)
                    next_idx += 1

                new_lines.append(line[:21] + chain_map[old] + line[22:])
            else:
                new_lines.append(line)

    fixed.write_text("".join(new_lines))
    return fixed, used


# ============================================================
# RESIDUE SANITIZER
# ============================================================

def sanitize_pdb(pdb_path: Path) -> Path:
    """
    Renumber residues sequentially, ignoring insertion codes.
    """
    fixed = pdb_path.with_name(pdb_path.stem + "_fixed.pdb")
    new_lines: list[str] = []
    last_key = None
    new_resseq = 1
    new_num = "   1"

    with open(pdb_path) as fh:
        for line in fh:
            if line.startswith(("ATOM", "HETATM")):
                chain = line[21]
                resseq = line[22:26].strip()
                icode = line[26].strip()
                key = (chain, resseq, icode)

                if key != last_key:
                    new_num = f"{new_resseq:4d}"
                    new_resseq += 1
                    last_key = key

                new_lines.append(line[:22] + new_num + " " + line[27:])
            else:
                new_lines.append(line)

    fixed.write_text("".join(new_lines))
    return fixed


# ============================================================
# ALIGN + MERGE
# ============================================================

def load_coords(pdb_path: Path):
    parser = PDBParser(QUIET=True)
    struct = parser.get_structure("s", pdb_path)
    coords = np.array([a.coord for a in struct.get_atoms()])
    return coords, struct


def translate_structure(struct, vec):
    for atom in struct.get_atoms():
        atom.coord = atom.coord + vec


def save_pdb(struct, path: Path):
    io = PDBIO()
    io.set_structure(struct)
    io.save(str(path))


def combine_in_python(rec: Path, bin: Path, out: Path, gap: float = SURFACE_GAP) -> None:
    """
    Align binder to receptor such that the closest atoms are at a given gap distance,
    then write out a merged complex PDB.
    """
    parser = PDBParser(QUIET=True)

    rec_struct = parser.get_structure("rec", rec)
    bin_struct = parser.get_structure("bin", bin)

    # Force chain IDs
    for atom in rec_struct.get_atoms():
        atom.get_parent().get_parent().id = "A"
    for atom in bin_struct.get_atoms():
        atom.get_parent().get_parent().id = "B"

    # Coordinates BEFORE merge
    rec_coords = np.array([a.coord for a in rec_struct.get_atoms()])
    bin_coords = np.array([a.coord for a in bin_struct.get_atoms()])

    # Find closest pair
    dists = np.linalg.norm(rec_coords[:, None, :] - bin_coords[None, :, :], axis=2)
    min_i, min_j = np.unravel_index(np.argmin(dists), dists.shape)
    # min_dist = dists[min_i, min_j]  # unused but kept for clarity

    # Vector binder → receptor
    vec = rec_coords[min_i] - bin_coords[min_j]
    norm = np.linalg.norm(vec)
    if norm < 1e-6:
        vec = np.array([1.0, 0.0, 0.0])
        norm = 1.0

    unit = vec / norm

    # Required movement to reach final distance = gap
    needed = norm - gap

    # Test BOTH possible directions
    shift_forward = unit * (-needed)  # expected direction (toward)
    shift_backward = unit * needed    # opposite direction

    # Compute resulting closest distances
    test1 = np.min(
        np.linalg.norm((bin_coords + shift_forward)[:, None, :] - rec_coords[None, :, :], axis=2)
    )
    test2 = np.min(
        np.linalg.norm((bin_coords + shift_backward)[:, None, :] - rec_coords[None, :, :], axis=2)
    )

    # Choose the shift that gives distance closest to desired gap
    final_shift = shift_forward if abs(test1 - gap) < abs(test2 - gap) else shift_backward

    # Apply translation
    for atom in bin_struct.get_atoms():
        atom.coord += final_shift

    # Merge
    rec_model = rec_struct[0]
    for chain in bin_struct[0]:
        rec_model.add(chain)

    # Save
    io = PDBIO()
    io.set_structure(rec_struct)
    io.save(str(out))

    print(f"🤝 Complex saved → {out}")


# ============================================================
# MULTI-COMPONENT MERGE
# ============================================================

CHAIN_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def combine_multi(
    components: list[Path],
    out: Path,
    gap: float = SURFACE_GAP,
    partners: str | None = None,
) -> dict:
    """
    Merge N structures into a single complex PDB.

    Args:
        components: List of PDB file paths (minimum 2)
        out: Output path for the merged complex
        gap: Surface gap in Angstroms between adjacent components
        partners: Docking partners string (e.g., "A_BCD"). Auto-generated if None.

    Returns:
        dict with keys: output, partners, chains
    """
    if len(components) < 2:
        raise ValueError("Need at least 2 components to merge")

    parser = PDBParser(QUIET=True)

    # Load all structures and assign chain IDs
    structures = []
    for i, comp_path in enumerate(components):
        struct = parser.get_structure(f"comp_{i}", comp_path)
        chain_id = CHAIN_LETTERS[i]
        # Force all chains in this structure to the assigned ID
        for chain in struct[0]:
            chain.id = chain_id
        structures.append(struct)

    # Position first component at origin, accumulate merged coordinates
    base_struct = structures[0]
    merged_coords = np.array([a.coord for a in base_struct.get_atoms()])

    for i in range(1, len(structures)):
        curr_struct = structures[i]
        curr_coords = np.array([a.coord for a in curr_struct.get_atoms()])

        # Find closest atom pair between merged complex so far and new component
        dists = np.linalg.norm(
            merged_coords[:, None, :] - curr_coords[None, :, :], axis=2
        )
        min_i, min_j = np.unravel_index(np.argmin(dists), dists.shape)

        vec = merged_coords[min_i] - curr_coords[min_j]
        norm = np.linalg.norm(vec)
        if norm < 1e-6:
            vec = np.array([1.0, 0.0, 0.0])
            norm = 1.0

        unit = vec / norm
        needed = norm - gap

        # Test both directions
        shift_forward = unit * (-needed)
        shift_backward = unit * needed

        test1 = np.min(np.linalg.norm(
            (curr_coords + shift_forward)[:, None, :] - merged_coords[None, :, :],
            axis=2,
        ))
        test2 = np.min(np.linalg.norm(
            (curr_coords + shift_backward)[:, None, :] - merged_coords[None, :, :],
            axis=2,
        ))

        final_shift = (
            shift_forward if abs(test1 - gap) < abs(test2 - gap) else shift_backward
        )

        # Apply translation
        for atom in curr_struct.get_atoms():
            atom.coord += final_shift

        # Add this component's chains to the base model
        for chain in curr_struct[0]:
            base_struct[0].add(chain)

        # Update combined coordinates for next iteration
        merged_coords = np.array([a.coord for a in base_struct.get_atoms()])

    # Save merged complex
    io = PDBIO()
    io.set_structure(base_struct)
    io.save(str(out))

    # Auto-generate partners string if not provided
    chains = [CHAIN_LETTERS[i] for i in range(len(components))]
    if not partners:
        partners = f"{chains[0]}_{''.join(chains[1:])}"

    print(f"🤝 Complex saved → {out} (chains: {','.join(chains)}, partners: {partners})")

    return {
        "output": str(out),
        "partners": partners,
        "chains": chains,
    }


# ============================================================
# DYNAMIC XML GENERATION
# ============================================================

def generate_docking_xml(partners: str, output_path: Path) -> Path:
    """
    Generate a docking XML protocol adapted for the given partners string.

    For 2-chain docking (A_B): copies the stock XML unchanged.
    For multi-chain groups (e.g., AB_C, A_BCD): removes 'rtiv' from
    FastRelax task_operations so it minimizes all residues (correct for
    multi-chain interfaces). The Docking movers with jumps="1" remain
    correct because -partners defines the fold tree jump across the
    underscore boundary.
    """
    total_chains = sum(len(g) for g in partners.split("_"))

    if total_chains <= 2:
        shutil.copy(DOCKING_XML_SRC, output_path)
    else:
        xml_text = DOCKING_XML_SRC.read_text()
        # Remove rtiv from FastRelax task_operations
        xml_text = xml_text.replace(
            'task_operations="ifcl,rtr,rtiv,prfrp"',
            'task_operations="ifcl,rtr,prfrp"',
        )
        output_path.write_text(xml_text)

    return output_path


# ============================================================
# ROSETTA DOCKING
# ============================================================

def run_relax(
    input_pdb: Path,
    output_pdb: Path,
    chain_only: str | None = None,
) -> Path:
    """
    FastRelax a PDB to clear crystal-form clashes before docking.

    Args:
        input_pdb: PDB to relax
        output_pdb: Where to write relaxed PDB
        chain_only: If set, restrict relaxation to this chain (residue selector).

    Returns:
        Path to the relaxed PDB.
    """
    work_dir = output_pdb.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    # Minimal FastRelax XML (mover-only, no chain selector for now).
    relax_xml = work_dir / f"relax_{input_pdb.stem}.xml"
    relax_xml.write_text("""<ROSETTASCRIPTS>
  <SCOREFXNS><ScoreFunction name="ref15" weights="ref2015"/></SCOREFXNS>
  <MOVERS>
    <FastRelax name="frelax" scorefxn="ref15" repeats="1"/>
  </MOVERS>
  <PROTOCOLS>
    <Add mover="frelax"/>
  </PROTOCOLS>
</ROSETTASCRIPTS>
""")

    log_path = work_dir / f"relax_{input_pdb.stem}.log"
    cmd = [
        ROSETTA_SCRIPTS,
        "-s", str(input_pdb),
        "-parser:protocol", str(relax_xml),
        "-database", ROSETTA_DATABASE,
        "-nstruct", "1",
        "-out:prefix", "relaxed_",
        "-out:path:pdb", str(work_dir),
        "-overwrite",
    ]
    with open(log_path, "w") as log:
        result = subprocess.run(cmd, cwd=work_dir, stdout=log, stderr=log)
    if result.returncode != 0:
        raise RuntimeError(f"FastRelax failed: see {log_path}")

    relaxed = work_dir / f"relaxed_{input_pdb.stem}_0001.pdb"
    if not relaxed.exists():
        candidates = list(work_dir.glob(f"relaxed_{input_pdb.stem}*.pdb"))
        if not candidates:
            raise RuntimeError(f"Relax produced no output (expected {relaxed})")
        relaxed = candidates[0]
    shutil.move(str(relaxed), str(output_pdb))
    return output_pdb


def run_docking(
    complex_pdb: Path,
    output_dir: Path | None = None,
    nstruct: int = 10,
    xml_content: str | None = None,
    options_extra: str = "",
    pre_relax: bool = False,
    docking_mode: str = "local",
    weight_overrides: dict | None = None,
) -> dict:
    """
    Run Rosetta docking protocol on a complex PDB.

    Args:
        complex_pdb: Path to the merged complex PDB file
        output_dir: Directory for output files (defaults to complex_pdb's directory)
        nstruct: Number of structures to generate
        xml_content: Custom XML protocol (uses default if None)
        options_extra: Additional command-line options
        pre_relax: If True, FastRelax the complex before docking. Helps when
                   input chains come from unbound crystal forms (clashes).
        docking_mode: "local" (default, ±3°/8Å perturbation around input pose)
                      or "global" (randomize1+randomize2: blind docking from
                      random orientation; standard for DB5 unbound benchmarks).

    Returns:
        dict with keys: fasc_path, output_dir, nstruct
    """
    if output_dir is None:
        output_dir = complex_pdb.parent

    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy complex to output dir if not already there
    complex_dest = output_dir / "complex_input.pdb"
    if complex_pdb != complex_dest:
        shutil.copy(complex_pdb, complex_dest)

    # Optional pre-relax. Helpful when chains come from unbound crystal forms
    # — clears clashes that confuse the docker.
    if pre_relax:
        print(f"→ Pre-relaxing {complex_dest}...")
        relaxed = output_dir / "complex_relaxed.pdb"
        run_relax(complex_dest, relaxed)
        shutil.copy(relaxed, complex_dest)
        print(f"✓ Pre-relaxed: {complex_dest}")

    # Read partners string from project dir if available
    partners_file = output_dir / "partners.txt"
    partners = partners_file.read_text().strip() if partners_file.exists() else "A_B"

    # Generate partners-aware XML protocol
    xml_path = output_dir / "docking_full.xml"
    generate_docking_xml(partners, xml_path)
    print(f"→ Generated docking_full.xml → {xml_path} (partners: {partners})")

    # Copy and update options file
    options_path = output_dir / "docking.options.txt"
    shutil.copy(DOCKING_OPTIONS_SRC, options_path)

    # Update options lines to use absolute project paths and dynamic partners.
    # For global/refine modes, also REPLACE any existing -dock_pert line so
    # Rosetta doesn't see "3 8 8 30" (4 values, illegal) from concatenation.
    fasc_path = output_dir / "docking.fasc"
    opt_text = options_path.read_text().splitlines()
    new_lines = []
    skip_dock_pert = docking_mode in ("global", "refine")
    for line in opt_text:
        stripped = line.strip()
        if stripped.startswith("-s "):
            new_lines.append(f"-s {complex_dest}")
        elif stripped.startswith("-out:file:scorefile"):
            new_lines.append(f"-out:file:scorefile {fasc_path}")
        elif "-partners" in stripped:
            new_lines.append(f"\t-partners {partners}")
        elif skip_dock_pert and stripped.startswith("-dock_pert"):
            # Drop the template's dock_pert; mode-specific value added below
            continue
        else:
            new_lines.append(line)

    # docking_mode=global → randomize1+randomize2+spin for blind docking.
    # docking_mode=local → uses default -dock_pert from template.
    # docking_mode=refine → tight perturbation (±1°/3Å) around input pose,
    #   for second-stage refinement of an already-good docking result.
    if docking_mode == "global":
        new_lines += [
            "-randomize1",
            "-randomize2",
            "-spin",
            "-dock_pert 8 30",  # widened for global search
        ]
        print("→ Docking mode: GLOBAL (randomize1/randomize2/spin)")
    elif docking_mode == "local":
        print("→ Docking mode: LOCAL (perturbation around input pose)")
    elif docking_mode == "refine":
        new_lines += ["-dock_pert 1 3"]  # tight refinement
        print("→ Docking mode: REFINE (tight ±1°/3Å around input)")
    else:
        raise ValueError(f"Unknown docking_mode={docking_mode!r}; use 'local', 'global', or 'refine'")

    # Optional score-function weight overrides (e.g. boost fa_elec for
    # charge-driven interfaces). dict like {"fa_elec": 1.5, "hbond_sc": 1.2}.
    if weight_overrides:
        # Rosetta accepts -score:set_weights "term1 val1 term2 val2 ..."
        ws = " ".join(f"{k} {v}" for k, v in weight_overrides.items())
        new_lines += [f'-score:set_weights {ws}']
        print(f"→ Score weight overrides: {ws}")

    options_path.write_text("\n".join(new_lines))
    print(f"→ Updated docking.options.txt (partners: {partners})")

    print(f"🚀 Starting Rosetta docking...")
    print(f"   Complex: {complex_dest}")
    print(f"   Output:  {output_dir}")
    print(f"   nstruct: {nstruct}")
    
    # Build command exactly like the working script
    docking_cmd = [
        ROSETTA_SCRIPTS,
        f"@{options_path}",
        "-parser:protocol", str(xml_path),
        "-out:suffix", "_full",
        "-nstruct", str(nstruct),
        "-overwrite"
    ]
    
    print(f"   Command: {' '.join(docking_cmd)}")
    print("=" * 50)
    
    # Run with log file
    log_path = output_dir / "docking_full.log"
    with open(log_path, "w") as log:
        result = subprocess.run(
            docking_cmd,
            cwd=output_dir,
            stdout=log,
            stderr=log
        )
    
    if result.returncode != 0:
        print(f"❌ Rosetta failed with code {result.returncode}")
        print(f"   See log: {log_path}")
        raise RuntimeError(f"Rosetta docking failed. Check {log_path}")
    
    print(f"✅ Docking complete!")
    print(f"   Results: {fasc_path}")

    return {
        "fasc_path": str(fasc_path),
        "output_dir": str(output_dir),
        "nstruct": nstruct,
        "log_path": str(log_path),
    }


# ============================================================
# SLURM DOCKING
# ============================================================

def run_docking_slurm(
    complex_pdb: Path,
    output_dir: Path | None = None,
    nstruct: int = 10,
    time_limit: str = "01:00:00",
    cpus: int = 4,
) -> dict:
    """
    Submit Rosetta docking as a SLURM job via sbatch.

    Args:
        complex_pdb: Path to the merged complex PDB file
        output_dir: Directory for output files
        nstruct: Number of structures to generate
        time_limit: SLURM time limit (HH:MM:SS)
        cpus: Number of CPUs to request

    Returns:
        dict with keys: job_id, slurm_script, output_dir, log_path, slurm_out, slurm_err
    """
    if output_dir is None:
        output_dir = complex_pdb.parent

    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy complex to output dir if not already there
    complex_dest = output_dir / "complex_input.pdb"
    if complex_pdb != complex_dest:
        shutil.copy(complex_pdb, complex_dest)

    # Read partners string from project dir if available
    partners_file = output_dir / "partners.txt"
    partners = partners_file.read_text().strip() if partners_file.exists() else "A_B"

    # Generate partners-aware XML protocol
    xml_path = output_dir / "docking_full.xml"
    generate_docking_xml(partners, xml_path)

    # Copy and update options file
    options_path = output_dir / "docking.options.txt"
    shutil.copy(DOCKING_OPTIONS_SRC, options_path)

    fasc_path = output_dir / "docking.fasc"
    opt_text = options_path.read_text().splitlines()
    new_lines = []
    for line in opt_text:
        if line.strip().startswith("-s "):
            new_lines.append(f"-s {complex_dest}")
        elif line.strip().startswith("-out:file:scorefile"):
            new_lines.append(f"-out:file:scorefile {fasc_path}")
        elif "-partners" in line:
            new_lines.append(f"\t-partners {partners}")
        else:
            new_lines.append(line)
    options_path.write_text("\n".join(new_lines))

    log_path = output_dir / "docking_full.log"
    slurm_out = output_dir / "slurm-%j.out"
    slurm_err = output_dir / "slurm-%j.err"

    # Build the SLURM batch script
    slurm_script_path = output_dir / "docking_job.sh"
    slurm_script_path.write_text(f"""#!/bin/bash
#SBATCH --job-name=rosetta_dock
#SBATCH --account={SLURM_ACCOUNT}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={cpus}
#SBATCH --time={time_limit}
#SBATCH --output={output_dir}/slurm-%j.out
#SBATCH --error={output_dir}/slurm-%j.err

echo "=== ROSETTA DOCKING JOB ==="
echo "Hostname: $(hostname)"
echo "Date: $(date)"
echo "Working dir: {output_dir}"
echo "Complex: {complex_dest}"
echo "nstruct: {nstruct}"
echo "=========================="

cd {output_dir}

{ROSETTA_SCRIPTS} \\
    @{options_path} \\
    -parser:protocol {xml_path} \\
    -database {ROSETTA_DATABASE} \\
    -out:suffix _full \\
    -nstruct {nstruct} \\
    -overwrite \\
    > {log_path} 2>&1

EXIT_CODE=$?

echo "=== DOCKING FINISHED ==="
echo "Exit code: $EXIT_CODE"
echo "Date: $(date)"

if [ $EXIT_CODE -eq 0 ]; then
    echo "STATUS: COMPLETED"
else
    echo "STATUS: FAILED"
fi
""")

    # Submit via sbatch
    result = subprocess.run(
        ["sbatch", str(slurm_script_path)],
        capture_output=True,
        text=True,
        cwd=str(output_dir),
    )

    if result.returncode != 0:
        raise RuntimeError(f"sbatch failed: {result.stderr}")

    # Parse job ID from "Submitted batch job 12345"
    job_id = result.stdout.strip().split()[-1]

    # Save job info for later status checks
    job_info = {
        "job_id": job_id,
        "slurm_script": str(slurm_script_path),
        "output_dir": str(output_dir),
        "log_path": str(log_path),
        "nstruct": nstruct,
        "fasc_path": str(output_dir / "docking.fasc"),
    }

    # Write job info to file for persistence
    import json
    job_info_path = output_dir / "slurm_job_info.json"
    job_info_path.write_text(json.dumps(job_info, indent=2))

    print(f"Submitted SLURM job {job_id}")
    print(f"  Script: {slurm_script_path}")
    print(f"  Output: {output_dir}")

    return job_info


def check_slurm_job(job_id: str) -> dict:
    """
    Check the status of a SLURM job.

    Returns:
        dict with keys: job_id, status, reason
        status is one of: PENDING, RUNNING, COMPLETED, FAILED, CANCELLED, UNKNOWN
    """
    result = subprocess.run(
        ["sacct", "-j", job_id, "--format=JobID,State,ExitCode,Elapsed", "--noheader", "-P"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Fallback to squeue
        sq = subprocess.run(
            ["squeue", "-j", job_id, "--noheader", "-o", "%T"],
            capture_output=True,
            text=True,
        )
        if sq.stdout.strip():
            return {"job_id": job_id, "status": sq.stdout.strip().split("\n")[0]}
        return {"job_id": job_id, "status": "UNKNOWN"}

    lines = result.stdout.strip().split("\n")
    if not lines:
        return {"job_id": job_id, "status": "UNKNOWN"}

    # First line is the main job (not .batch or .extern steps)
    for line in lines:
        parts = line.split("|")
        if len(parts) >= 2 and parts[0] == job_id:
            return {
                "job_id": job_id,
                "status": parts[1].strip(),
                "exit_code": parts[2].strip() if len(parts) > 2 else "",
                "elapsed": parts[3].strip() if len(parts) > 3 else "",
            }

    # Fallback: use first line
    parts = lines[0].split("|")
    return {
        "job_id": job_id,
        "status": parts[1].strip() if len(parts) > 1 else "UNKNOWN",
    }


# ============================================================
# SEQUENTIAL ASSEMBLY DOCKING
# ============================================================

def _rechain_pdb(pdb_path: Path, num_original_components: int) -> None:
    """
    Re-assign chain IDs A, B, C, ... to segments separated by TER records
    in the final assembly PDB. This restores proper chain identity after
    sequential merging (which collapses multi-chain inputs to single chains).
    """
    parser = PDBParser(QUIET=True)
    struct = parser.get_structure("assembly", str(pdb_path))
    chains = list(struct[0].get_chains())
    # Assign chain IDs sequentially
    for i, chain in enumerate(chains):
        if i < len(CHAIN_LETTERS):
            chain.id = CHAIN_LETTERS[i]
    io = PDBIO()
    io.set_structure(struct)
    io.save(str(pdb_path))


def generate_sequential_driver(
    project_dir: Path,
    components: list[Path],
    nstruct: int,
) -> Path:
    """
    Generate a Python driver script for sequential assembly docking.

    The driver merges and docks components pairwise in order:
      Step 1: components[0] + components[1] → dock → best model
      Step 2: best_step1 + components[2] → dock → best model
      ...
    Each step is standard 2-body Rosetta docking (partners A_B).

    Returns: Path to the generated driver script.
    """
    driver_path = project_dir / "sequential_driver.py"
    backend_parent = Path(__file__).resolve().parent.parent  # protein_web/

    components_repr = repr([str(c) for c in components])

    driver_code = f'''#!/usr/bin/env python3
"""Auto-generated sequential assembly docking driver."""
import sys, json, shutil, subprocess, glob
from pathlib import Path

sys.path.insert(0, {repr(str(backend_parent))})

from backend.pipeline import (
    combine_multi,
    generate_docking_xml,
    parse_fasc_and_find_best,
    _rechain_pdb,
    ROSETTA_SCRIPTS,
    DOCKING_OPTIONS_SRC,
    CHAIN_LETTERS,
    SURFACE_GAP,
)

PROJECT_DIR = Path({repr(str(project_dir))})
COMPONENTS = {components_repr}
NSTRUCT = {nstruct}
NUM_STEPS = len(COMPONENTS) - 1


def write_status(step, total, phase, detail=""):
    status = {{
        "mode": "sequential",
        "current_step": step,
        "total_steps": total,
        "phase": phase,
        "detail": detail,
    }}
    (PROJECT_DIR / "sequential_status.json").write_text(json.dumps(status, indent=2))


def rewrite_options(options_src, options_dst, complex_pdb, fasc_path, partners):
    """Copy and patch docking options for a step."""
    shutil.copy(str(options_src), str(options_dst))
    lines = options_dst.read_text().splitlines()
    new_lines = []
    for line in lines:
        if line.strip().startswith("-s "):
            new_lines.append(f"-s {{complex_pdb}}")
        elif line.strip().startswith("-out:file:scorefile"):
            new_lines.append(f"-out:file:scorefile {{fasc_path}}")
        elif "-partners" in line:
            new_lines.append(f"\\t-partners {{partners}}")
        else:
            new_lines.append(line)
    options_dst.write_text("\\n".join(new_lines))


def run_step(step_num, pdb_a, pdb_b):
    """Merge two PDBs, dock, return best model path."""
    step_dir = PROJECT_DIR / f"step_{{step_num}}"
    step_dir.mkdir(parents=True, exist_ok=True)

    write_status(step_num, NUM_STEPS, "merging", f"Merging inputs for step {{step_num}}")

    complex_pdb = step_dir / "complex_input.pdb"
    partners = "A_B"
    combine_multi([Path(pdb_a), Path(pdb_b)], complex_pdb, gap=SURFACE_GAP, partners=partners)
    (step_dir / "partners.txt").write_text(partners)

    # Generate XML and options
    xml_path = step_dir / "docking_full.xml"
    generate_docking_xml(partners, xml_path)
    options_path = step_dir / "docking.options.txt"
    fasc_path = step_dir / "docking.fasc"
    rewrite_options(DOCKING_OPTIONS_SRC, options_path, complex_pdb, fasc_path, partners)

    write_status(step_num, NUM_STEPS, "docking", f"Running Rosetta ({{NSTRUCT}} structures)")

    log_path = step_dir / "docking_full.log"
    cmd = [
        str(ROSETTA_SCRIPTS),
        f"@{{options_path}}",
        "-parser:protocol", str(xml_path),
        "-out:suffix", "_full",
        "-nstruct", str(NSTRUCT),
        "-overwrite",
    ]
    with open(log_path, "w") as log:
        result = subprocess.run(cmd, cwd=str(step_dir), stdout=log, stderr=log)

    if result.returncode != 0:
        write_status(step_num, NUM_STEPS, "failed", f"Rosetta failed at step {{step_num}}")
        step_result = {{"step": step_num, "status": "failed", "log": str(log_path)}}
        (step_dir / "result.json").write_text(json.dumps(step_result, indent=2))
        sys.exit(1)

    write_status(step_num, NUM_STEPS, "parsing", f"Parsing results for step {{step_num}}")

    best = parse_fasc_and_find_best(
        fasc_path=fasc_path,
        pdb_glob=str(step_dir / "complex_input_full_*.pdb"),
    )
    step_result = {{
        "step": step_num,
        "status": "completed",
        "best_score": best["score"],
        "best_model": best["desc"],
        "best_pdb": str(best["pdb_path"]),
    }}
    (step_dir / "result.json").write_text(json.dumps(step_result, indent=2))
    return Path(best["pdb_path"])


def main():
    components = [Path(c) for c in COMPONENTS]

    # Step 1: first two components
    current_assembly = run_step(1, components[0], components[1])

    # Steps 2..N-1: add remaining components one at a time
    for i in range(2, len(components)):
        current_assembly = run_step(i, current_assembly, components[i])

    # Copy final model and re-chain to A, B, C, ...
    final_dest = PROJECT_DIR / "final_assembly.pdb"
    shutil.copy(str(current_assembly), str(final_dest))
    _rechain_pdb(final_dest, len(components))

    # Compat copy for existing results viewer
    shutil.copy(str(final_dest), str(PROJECT_DIR / "complex_input_full_0001.pdb"))

    write_status(NUM_STEPS, NUM_STEPS, "done", "Sequential assembly complete")

    # Write summary
    steps = []
    for s in range(1, NUM_STEPS + 1):
        sr = PROJECT_DIR / f"step_{{s}}" / "result.json"
        if sr.exists():
            steps.append(json.loads(sr.read_text()))
    summary = {{
        "mode": "sequential",
        "num_steps": NUM_STEPS,
        "num_components": len(components),
        "steps": steps,
        "final_pdb": str(final_dest),
        "final_score": steps[-1]["best_score"] if steps else None,
    }}
    (PROJECT_DIR / "sequential_summary.json").write_text(json.dumps(summary, indent=2))
    print("Sequential assembly complete!")


if __name__ == "__main__":
    main()
'''

    driver_path.write_text(driver_code)
    driver_path.chmod(0o755)
    return driver_path


def run_sequential_docking_slurm(
    project_dir: Path,
    components: list[Path],
    nstruct: int = 10,
    time_limit: str = "01:00:00",
    cpus: int = 4,
) -> dict:
    """
    Submit sequential assembly docking as a single SLURM job.

    Generates a Python driver script and wraps it in a SLURM bash script.
    The driver handles step-by-step merging and docking inside the job.
    """
    project_dir.mkdir(parents=True, exist_ok=True)

    driver_path = generate_sequential_driver(project_dir, components, nstruct)
    venv_bin = Path(__file__).resolve().parent.parent / "venv" / "bin"

    slurm_script_path = project_dir / "sequential_docking_job.sh"
    slurm_script_path.write_text(f"""#!/bin/bash
#SBATCH --job-name=seq_dock
#SBATCH --account={SLURM_ACCOUNT}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={cpus}
#SBATCH --time={time_limit}
#SBATCH --output={project_dir}/slurm-%j.out
#SBATCH --error={project_dir}/slurm-%j.err

echo "=== SEQUENTIAL ASSEMBLY DOCKING ==="
echo "Hostname: $(hostname)"
echo "Date: $(date)"
echo "Components: {len(components)}"
echo "Steps: {len(components) - 1}"
echo "nstruct per step: {nstruct}"
echo "===================================="

module load python/3.10
source {venv_bin}/activate

cd {project_dir}
{venv_bin}/python {driver_path}
""")
    slurm_script_path.chmod(0o755)

    result = subprocess.run(
        ["sbatch", str(slurm_script_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"sbatch failed: {result.stderr}")

    job_id = result.stdout.strip().split()[-1]
    num_steps = len(components) - 1

    job_info = {
        "job_id": job_id,
        "mode": "sequential",
        "num_steps": num_steps,
        "num_components": len(components),
        "components": [str(c) for c in components],
        "nstruct": nstruct,
        "slurm_script": str(slurm_script_path),
        "driver_script": str(driver_path),
    }
    (project_dir / "slurm_job_info.json").write_text(
        __import__("json").dumps(job_info, indent=2)
    )

    return job_info


def check_sequential_status(project_dir: Path, job_id: str) -> dict:
    """
    Check status of a sequential assembly SLURM job.

    Reads sequential_status.json (written by the driver in real-time)
    and per-step result.json files to build a progress report.
    """
    import json as _json

    slurm_status = check_slurm_job(job_id)
    response = {
        "job_id": job_id,
        "status": slurm_status["status"],
        "mode": "sequential",
    }

    # Read driver status file
    status_file = project_dir / "sequential_status.json"
    if status_file.exists():
        driver_status = _json.loads(status_file.read_text())
        response["current_step"] = driver_status.get("current_step", 1)
        response["total_steps"] = driver_status.get("total_steps", 1)
        response["step_phase"] = driver_status.get("phase", "pending")
        response["detail"] = driver_status.get("detail", "")
    else:
        job_info_path = project_dir / "slurm_job_info.json"
        if job_info_path.exists():
            ji = _json.loads(job_info_path.read_text())
            response["total_steps"] = ji.get("num_steps", 1)
        response["current_step"] = 0
        response["step_phase"] = "pending"

    # Collect per-step results
    steps = []
    total_steps = response.get("total_steps", 1)
    for s in range(1, total_steps + 1):
        result_file = project_dir / f"step_{s}" / "result.json"
        if result_file.exists():
            steps.append(_json.loads(result_file.read_text()))
    response["steps"] = steps

    # If job completed, read summary
    if slurm_status["status"] == "COMPLETED":
        summary_file = project_dir / "sequential_summary.json"
        if summary_file.exists():
            summary = _json.loads(summary_file.read_text())
            response["final_pdb"] = summary.get("final_pdb")
            response["final_score"] = summary.get("final_score")

    # Progress: count structures done in current step's fasc
    current_step = response.get("current_step", 0)
    if current_step > 0:
        fasc = project_dir / f"step_{current_step}" / "docking.fasc"
        if fasc.exists():
            lines = fasc.read_text().splitlines()
            response["structures_done"] = sum(
                1 for l in lines if l.startswith("SCORE:") and "total_score" not in l
            )
        else:
            response["structures_done"] = 0

    return response


# ============================================================
# OPTIONAL: BEST MODEL FROM LOG (ALTERNATIVE PATH)
# ============================================================

def find_best_model_in_folder(folder: Path) -> Path:
    """
    Finds lowest-score model name from docking/docking_full.log,
    then resolves actual .pdb path (either working folder or cwd).
    """
    log_path = folder / "docking" / "docking_full.log"
    if not log_path.exists():
        raise FileNotFoundError("docking_full.log not found inside /docking/")

    best_score = float("inf")
    best_model: str | None = None

    with open(log_path) as f:
        for line in f:
            if line.startswith("SCORE:"):
                parts = line.split()
                try:
                    score = float(parts[1])
                    model = parts[-1]  # example: complex_input_full_0003
                    if score < best_score:
                        best_score = score
                        best_model = model
                except Exception:
                    continue

    if not best_model:
        raise RuntimeError("No valid SCORE lines found.")

    candidate = folder / f"{best_model}.pdb"
    if candidate.exists():
        return candidate

    # fallback: Rosetta often dumps results in script's run directory
    alt = Path(f"{best_model}.pdb")
    if alt.exists():
        return alt

    raise FileNotFoundError(
        f"Best model '{best_model}.pdb' not found in working folder nor current directory."
    )


def open_best_model_in_pymol(folder: Path) -> None:
    """
    Build a PyMOL visualization script for the best model found
    via docking_full.log and launch PyMOL.
    """
    best_pdb = find_best_model_in_folder(folder)
    pml_path = best_pdb.with_suffix(".pml")

    pml_path.write_text(
        f"""
# Load structure
load {best_pdb}

# Hide everything first
hide everything

# Color and show protein backbones as ribbons
color teal, chain A
color orange, chain B
show cartoon, chain A or chain B

# Ribbon transparency
set cartoon_transparency, 0.3

# Interface selections (within 5 Å)
select interface_A, (chain A within 5 of chain B)
select interface_B, (chain B within 5 of chain A)
select interface, interface_A or interface_B

# Show sticks for interface residues
show sticks, interface
set stick_radius, 0.2
set stick_quality, 16
color hotpink, interface

# Optional: show a mesh around the interface
show mesh, interface
set mesh_width, 0.4
set mesh_color, gray70
set mesh_quality, 2

# Nicely center the view
zoom interface
zoom animate=-1
"""
    )

    print(f"🎨 Opening best-scoring model in PyMOL → {best_pdb}")
    
    # Detect OS and use appropriate PyMOL command
    import platform
    system = platform.system()
    
    if system == "Darwin":  # macOS
        # Try multiple Mac PyMOL locations
        pymol_commands = [
            ["pymol", "-c", str(pml_path)],  # Homebrew/system install
            ["/Applications/PyMOL.app/Contents/MacOS/PyMOL", "-c", str(pml_path)],  # App bundle
            ["/Applications/PyMOLX11Hybrid.app/Contents/MacOS/PyMOL", "-c", str(pml_path)],  # Alternative bundle
        ]
        
        # Try each command until one works
        for cmd in pymol_commands:
            try:
                result = subprocess.run(cmd, check=False, timeout=5, capture_output=True)
                if result.returncode == 0 or result.returncode == None:
                    print(f"✅ PyMOL launched successfully")
                    return
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        
        print(f"⚠️  Warning: PyMOL not found. Please install PyMOL or update the path.")
    else:  # Linux or other
        subprocess.run(["pymol", str(pml_path)], check=False)


# ============================================================
# ALANINE SCANNING (ΔΔG)
# ============================================================

def _compute_pose_numbers(pdb_path: Path) -> dict[tuple[str, int], int]:
    """
    Map (chain_id, PDB_resid) → Rosetta pose number.

    Rosetta assigns sequential 1-based pose numbers by iterating chains
    in file order, skipping HETATM and water. This must exactly match
    Rosetta's internal numbering so MutateResidue targets the right residue.
    """
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("complex", str(pdb_path))
    model = structure[0]

    pose_map: dict[tuple[str, int], int] = {}
    pose_num = 0

    for chain in model:
        for residue in chain:
            # Skip HETATM and water (hetflag != " ")
            if residue.id[0] != " ":
                continue
            pose_num += 1
            pose_map[(chain.id, residue.id[1])] = pose_num

    return pose_map


def _setup_single_pose_scan(
    scan_dir: Path,
    complex_pdb: Path,
    mutations: list[dict],
    nstruct: int = 3,
    cpus: int = 4,
    time_limit: str = "00:30:00",
) -> str:
    """
    Set up and submit a single-pose alanine scan SLURM array job.

    Creates mutations.txt, options, SLURM script, copies XMLs+PDB,
    submits via sbatch, and returns the job_id.

    Args:
        scan_dir: Directory to write all scan files into
        complex_pdb: Path to the complex PDB for this pose
        mutations: List of mutation dicts (must include pose_num)
        nstruct: Number of replicates per mutation
        cpus: CPUs per SLURM task
        time_limit: SLURM time limit string
    Returns:
        job_id string from sbatch
    """
    scan_dir.mkdir(parents=True, exist_ok=True)

    # Copy input PDB
    complex_dest = scan_dir / "complex_input.pdb"
    shutil.copy(complex_pdb, complex_dest)

    # Copy XML protocols and patch interface partners
    partners_file = complex_pdb.parent / "partners.txt"
    partners = partners_file.read_text().strip() if partners_file.exists() else "A_B"

    for src, dest_name in [
        (ALA_SCAN_WT_XML, "ala_scan_wt.xml"),
        (ALA_SCAN_MUT_XML, "ala_scan_mut.xml"),
    ]:
        xml_text = src.read_text()
        xml_text = xml_text.replace('interface="A_B"', f'interface="{partners}"')
        (scan_dir / dest_name).write_text(xml_text)

    # Copy and update options file with absolute paths
    options_path = scan_dir / "ala_scan.options.txt"
    opt_text = ALA_SCAN_OPTIONS_SRC.read_text()
    opt_text += f"\n-s {complex_dest}\n"
    options_path.write_text(opt_text)

    # Write mutations task file
    # Line 0: WT
    # Lines 1-N: pose_num chain resname resid
    task_lines = ["WT"]
    for m in mutations:
        task_lines.append(f"{m['pose_num']} {m['chain']} {m['resname']} {m['resid']}")
    (scan_dir / "mutations.txt").write_text("\n".join(task_lines) + "\n")

    num_mutations = len(mutations)
    wt_xml = scan_dir / "ala_scan_wt.xml"
    mut_xml = scan_dir / "ala_scan_mut.xml"

    # Build SLURM array script
    slurm_script_path = scan_dir / "ala_scan_job.sh"
    slurm_script_path.write_text(f"""#!/bin/bash
#SBATCH --job-name=ala_scan
#SBATCH --account={SLURM_ACCOUNT}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={cpus}
#SBATCH --time={time_limit}
#SBATCH --array=0-{num_mutations}
#SBATCH --output={scan_dir}/slurm-%A_%a.out
#SBATCH --error={scan_dir}/slurm-%A_%a.err

echo "=== ALANINE SCANNING JOB ==="
echo "Array Task ID: $SLURM_ARRAY_TASK_ID"
echo "Hostname: $(hostname)"
echo "Date: $(date)"

cd {scan_dir}

IDX=$SLURM_ARRAY_TASK_ID

if [ $IDX -eq 0 ]; then
    echo "Running WILDTYPE (repack + minimize + analyze)"

    {ROSETTA_SCRIPTS} \\
        @{options_path} \\
        -parser:protocol {wt_xml} \\
        -database {ROSETTA_DATABASE} \\
        -out:file:scorefile {scan_dir}/score_wt.fasc \\
        -out:suffix _wt \\
        -nstruct {nstruct} \\
        -overwrite \\
        > {scan_dir}/log_wt.txt 2>&1
else
    # Read mutation spec from task file (1-indexed line = IDX+1)
    LINE=$(sed -n "$((IDX+1))p" {scan_dir}/mutations.txt)
    POSE_NUM=$(echo $LINE | awk '{{print $1}}')
    CHAIN=$(echo $LINE | awk '{{print $2}}')
    RESNAME=$(echo $LINE | awk '{{print $3}}')
    RESID=$(echo $LINE | awk '{{print $4}}')

    echo "Running MUTANT: ${{CHAIN}}:${{RESNAME}}${{RESID}} -> ALA (pose ${{POSE_NUM}})"

    {ROSETTA_SCRIPTS} \\
        @{options_path} \\
        -parser:protocol {mut_xml} \\
        -parser:script_vars resid=${{POSE_NUM}} \\
        -database {ROSETTA_DATABASE} \\
        -out:file:scorefile {scan_dir}/score_mut_${{IDX}}.fasc \\
        -out:suffix _mut_${{IDX}} \\
        -nstruct {nstruct} \\
        -overwrite \\
        > {scan_dir}/log_mut_${{IDX}}.txt 2>&1
fi

EXIT_CODE=$?
echo "Exit code: $EXIT_CODE"
echo "Date: $(date)"

if [ $EXIT_CODE -eq 0 ]; then
    echo "STATUS: COMPLETED"
else
    echo "STATUS: FAILED"
fi
""")

    # Submit via sbatch
    result = subprocess.run(
        ["sbatch", str(slurm_script_path)],
        capture_output=True,
        text=True,
        cwd=str(scan_dir),
    )

    if result.returncode != 0:
        raise RuntimeError(f"sbatch failed: {result.stderr}")

    # Parse job ID from "Submitted batch job 12345"
    job_id = result.stdout.strip().split()[-1]
    return job_id


def run_alanine_scan_slurm(
    complex_pdb: Path,
    interface_data: dict,
    output_dir: Path,
    nstruct: int = 3,
    max_mutations: int = 8,
    time_limit: str = "00:30:00",
    cpus: int = 4,
) -> dict:
    """
    Submit Rosetta computational alanine scanning as a SLURM array job.

    Index 0 = wildtype (repack + min + InterfaceAnalyzer)
    Indices 1-N = one mutant each (MutateResidue + repack + min + InterfaceAnalyzer)

    Returns dict with job_id, mutations list, and metadata.
    """
    import json
    from backend.experiment_designer import rank_hotspots

    # Get top hotspot candidates
    hotspots = rank_hotspots(interface_data, max_hotspots=max_mutations)
    if not hotspots:
        raise RuntimeError("No hotspot candidates found (all residues have ΔSASA < 20 Å²)")

    # Compute pose number mapping
    pose_map = _compute_pose_numbers(complex_pdb)

    # Build mutations list with pose numbers
    mutations = []
    for h in hotspots:
        key = (h.chain, h.resid)
        if key not in pose_map:
            continue
        mutations.append({
            "chain": h.chain,
            "resname": h.resname,
            "resid": h.resid,
            "one_letter": h.one_letter,
            "pose_num": pose_map[key],
            "mutation": h.mutation,
            "side": h.side,
        })

    if not mutations:
        raise RuntimeError("Could not map any hotspot residues to pose numbers")

    # Create scan directory and submit via helper
    scan_dir = output_dir / "ala_scan"
    job_id = _setup_single_pose_scan(
        scan_dir=scan_dir,
        complex_pdb=complex_pdb,
        mutations=mutations,
        nstruct=nstruct,
        cpus=cpus,
        time_limit=time_limit,
    )

    # Save job info
    job_info = {
        "job_id": job_id,
        "scan_dir": str(scan_dir),
        "mutations": mutations,
        "nstruct": nstruct,
        "num_tasks": len(mutations) + 1,  # WT + N mutants
    }

    (scan_dir / "ala_scan_job_info.json").write_text(json.dumps(job_info, indent=2))

    print(f"Submitted alanine scan SLURM array job {job_id} ({len(mutations)} mutations + WT)")

    return job_info


def _check_single_slurm_array(job_id: str, num_tasks: int) -> dict:
    """Check status of a single SLURM array job.

    Returns {status, tasks_done, tasks_total, tasks_failed}.
    """
    result = subprocess.run(
        ["sacct", "-j", job_id, "--format=JobID,State", "--noheader", "-P"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Fallback to squeue
        sq = subprocess.run(
            ["squeue", "-j", job_id, "--noheader", "-o", "%T"],
            capture_output=True,
            text=True,
        )
        if sq.stdout.strip():
            return {
                "status": "RUNNING",
                "tasks_done": 0,
                "tasks_total": num_tasks,
                "tasks_failed": 0,
            }
        return {
            "status": "UNKNOWN",
            "tasks_done": 0,
            "tasks_total": num_tasks,
            "tasks_failed": 0,
        }

    lines = result.stdout.strip().split("\n")

    completed = 0
    failed = 0
    running = 0
    pending = 0

    for line in lines:
        parts = line.split("|")
        if len(parts) < 2:
            continue
        job_part = parts[0].strip()
        state = parts[1].strip()

        # Array tasks show as JOBID_INDEX (e.g., 12345_0, 12345_1)
        # Skip the main job entry and .batch/.extern entries
        if "_" not in job_part:
            continue
        if ".batch" in job_part or ".extern" in job_part:
            continue

        if state == "COMPLETED":
            completed += 1
        elif state in ("FAILED", "TIMEOUT", "CANCELLED"):
            failed += 1
        elif state == "RUNNING":
            running += 1
        elif state == "PENDING":
            pending += 1

    # Determine overall status
    if completed + failed >= num_tasks:
        overall = "COMPLETED" if failed == 0 else "FAILED"
    elif running > 0:
        overall = "RUNNING"
    elif pending > 0:
        overall = "PENDING"
    elif completed > 0:
        overall = "RUNNING"  # some done, waiting on others
    else:
        overall = "PENDING"

    return {
        "status": overall,
        "tasks_done": completed,
        "tasks_total": num_tasks,
        "tasks_failed": failed,
    }


def check_alanine_scan_job(job_id, num_tasks: int, *, job_info: dict | None = None) -> dict:
    """
    Check status of alanine scanning SLURM job(s).

    Supports both single-pose (job_id is str) and multi-pose
    (job_info has mode=="multi_pose" with multiple job_ids).

    Returns:
        {status, tasks_done, tasks_total, tasks_failed, per_pose_status?}
    """
    # Multi-pose mode: check each pose's job independently
    if job_info and job_info.get("mode") == "multi_pose":
        poses = job_info["poses"]
        tasks_per_pose = job_info.get("num_tasks_per_pose", num_tasks)

        total_done = 0
        total_failed = 0
        total_tasks = tasks_per_pose * len(poses)
        per_pose_status = []
        any_running = False
        any_pending = False
        all_terminal = True

        for pose in poses:
            ps = _check_single_slurm_array(pose["job_id"], tasks_per_pose)
            per_pose_status.append({
                "job_id": pose["job_id"],
                "pose_dir": pose["pose_dir"],
                "status": ps["status"],
                "done": ps["tasks_done"],
                "total": ps["tasks_total"],
            })
            total_done += ps["tasks_done"]
            total_failed += ps["tasks_failed"]

            if ps["status"] in ("RUNNING",):
                any_running = True
                all_terminal = False
            elif ps["status"] in ("PENDING", "UNKNOWN"):
                any_pending = True
                all_terminal = False

        if all_terminal:
            overall = "COMPLETED" if total_failed == 0 else "FAILED"
        elif any_running:
            overall = "RUNNING"
        elif any_pending:
            overall = "PENDING"
        else:
            overall = "RUNNING"

        return {
            "status": overall,
            "tasks_done": total_done,
            "tasks_total": total_tasks,
            "tasks_failed": total_failed,
            "per_pose_status": per_pose_status,
        }

    # Single-pose mode (backward compatible)
    return _check_single_slurm_array(str(job_id), num_tasks)


def _classify_ddG(ddG: float, ci_lower: float, ci_upper: float) -> str:
    """CI-aware classification of ΔΔG values.

    Uses the confidence interval lower bound to decide if the signal
    is statistically distinguishable from noise.
    """
    if ddG >= 4.0 and ci_lower > 2.0:
        return "critical"
    if ddG >= 2.0 and ci_lower > 1.0:
        return "strong"
    if ddG >= 1.0 and ci_lower > 0.5:
        return "moderate"
    if ddG < 0 and ci_upper < 0:
        return "stabilizing"
    if ddG >= 1.0:
        return "uncertain"   # mean says hotspot, CI says maybe not
    return "weak"


# Energy terms to decompose per-mutation ΔΔG
DECOMP_TERMS = [
    "fa_atr", "fa_rep", "fa_elec", "fa_sol",
    "hbond_sc", "hbond_bb_sc", "lk_ball_wtd",
]


def _compute_energy_decomp(
    wt_models: list[dict], mut_models: list[dict],
) -> dict:
    """Compute per-term ΔΔG decomposition between mutant and WT model sets."""
    wt_terms: dict[str, float] = {}
    for term in DECOMP_TERMS:
        vals = [m.get(term, 0.0) for m in wt_models if m.get(term) is not None]
        wt_terms[term] = sum(vals) / len(vals) if vals else 0.0

    mut_terms: dict[str, float] = {}
    for term in DECOMP_TERMS:
        vals = [m.get(term, 0.0) for m in mut_models if m.get(term) is not None]
        mut_terms[term] = sum(vals) / len(vals) if vals else 0.0

    decomp = {term: round(mut_terms[term] - wt_terms[term], 2) for term in DECOMP_TERMS}
    # Dominant contributor
    dominant = max(DECOMP_TERMS, key=lambda t: abs(decomp[t]))
    decomp["dominant"] = dominant
    return decomp


def parse_alanine_scan_results(scan_dir: Path, job_info: dict) -> dict:
    """
    Parse score files from alanine scanning and compute ΔΔG values.

    Returns:
        {
            wt_dG: float,
            wt_std: float,
            wt_n_replicates: int,
            wt_noise_floor: float,
            mutations: [
                {mutation, chain, resname, resid, wt_dG, mut_dG, mut_std,
                 ddG, ci_lower, ci_upper, snr, classification, energy_decomp}
            ]
        }
    """
    import math
    # t-distribution critical values for 95% CI (two-tailed)
    # Precomputed to avoid scipy dependency: t_{df, 0.975}
    _T_CRIT = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
               6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
               15: 2.131, 20: 2.086, 30: 2.042, 50: 2.009, 100: 1.984}

    def _t_crit_val(df: int) -> float:
        if df in _T_CRIT:
            return _T_CRIT[df]
        # For large df, converge toward z=1.96
        if df > 100:
            return 1.96
        # Linear interpolate between known values
        keys = sorted(_T_CRIT.keys())
        for i in range(len(keys) - 1):
            if keys[i] < df < keys[i + 1]:
                lo, hi = keys[i], keys[i + 1]
                frac = (df - lo) / (hi - lo)
                return _T_CRIT[lo] + frac * (_T_CRIT[hi] - _T_CRIT[lo])
        return 1.96

    scan_dir = Path(scan_dir)
    mutations_info = job_info["mutations"]

    # Parse WT scores → average dG_separated
    wt_fasc = scan_dir / "score_wt.fasc"
    if not wt_fasc.exists():
        raise FileNotFoundError("Wildtype score file not found")

    wt_models = parse_fasc_all_models(
        fasc_path=wt_fasc,
        pdb_glob=str(scan_dir / "complex_input_wt_*.pdb"),
    )
    wt_dG_values = [m.get("dG_separated", m.get("score", 0.0)) for m in wt_models]
    wt_dG = sum(wt_dG_values) / len(wt_dG_values)

    # WT replicate stability check
    wt_std = 0.0
    wt_warning = None
    if len(wt_dG_values) > 1:
        variance = sum((v - wt_dG) ** 2 for v in wt_dG_values) / (len(wt_dG_values) - 1)
        wt_std = variance ** 0.5
        if wt_std > 1.0:
            wt_warning = (
                f"WT replicates show high variance (std={wt_std:.2f} REU). "
                f"ΔΔG values may be unreliable. Consider increasing nstruct."
            )

    # Noise floor = WT variance (baseline fluctuation from repacking alone)
    noise_floor = wt_std

    n_replicates = len(wt_dG_values)

    # Parse each mutant
    results = []
    for i, mut in enumerate(mutations_info, start=1):
        mut_fasc = scan_dir / f"score_mut_{i}.fasc"
        if not mut_fasc.exists():
            results.append({
                "mutation": mut["mutation"],
                "chain": mut["chain"],
                "resname": mut["resname"],
                "resid": mut["resid"],
                "side": mut.get("side", ""),
                "wt_dG": round(wt_dG, 2),
                "mut_dG": None,
                "ddG": None,
                "classification": "error",
                "error": "Score file not found",
            })
            continue

        try:
            mut_models = parse_fasc_all_models(
                fasc_path=mut_fasc,
                pdb_glob=str(scan_dir / f"complex_input_mut_{i}_*.pdb"),
            )
            mut_dG_values = [m.get("dG_separated", m.get("score", 0.0)) for m in mut_models]
            mut_dG = sum(mut_dG_values) / len(mut_dG_values)
            ddG = mut_dG - wt_dG

            # Per-mutant replicate std
            mut_std = 0.0
            if len(mut_dG_values) > 1:
                var = sum((v - mut_dG) ** 2 for v in mut_dG_values) / (len(mut_dG_values) - 1)
                mut_std = var ** 0.5

            # Within-pose confidence interval (t-distribution for small n)
            n = len(mut_dG_values)
            se = mut_std / math.sqrt(n) if n > 0 else 0.0
            t_crit = _t_crit_val(max(n - 1, 1)) if n > 1 else 1.96
            ci_lower = ddG - t_crit * se
            ci_upper = ddG + t_crit * se

            # Propagated sigma: sqrt(wt_std^2 + mut_std^2) for SNR
            sigma_ddG = math.sqrt(noise_floor**2 + mut_std**2) if (noise_floor > 0 or mut_std > 0) else 0.0
            snr = abs(ddG) / sigma_ddG if sigma_ddG > 0 else float('inf')

            # CI-aware classification
            classification = _classify_ddG(ddG, ci_lower, ci_upper)
            # Downgrade if signal is below noise floor
            if snr < 1.5 and classification not in ("weak", "stabilizing", "error"):
                classification = "uncertain"

            # Energy decomposition
            energy_decomp = _compute_energy_decomp(wt_models, mut_models)

            results.append({
                "mutation": mut["mutation"],
                "chain": mut["chain"],
                "resname": mut["resname"],
                "resid": mut["resid"],
                "side": mut.get("side", ""),
                "wt_dG": round(wt_dG, 2),
                "mut_dG": round(mut_dG, 2),
                "mut_std": round(mut_std, 2),
                "ddG": round(ddG, 2),
                "ci_lower": round(ci_lower, 2),
                "ci_upper": round(ci_upper, 2),
                "snr": round(snr, 2),
                "classification": classification,
                "energy_decomp": energy_decomp,
            })
        except Exception as e:
            results.append({
                "mutation": mut["mutation"],
                "chain": mut["chain"],
                "resname": mut["resname"],
                "resid": mut["resid"],
                "side": mut.get("side", ""),
                "wt_dG": round(wt_dG, 2),
                "mut_dG": None,
                "ddG": None,
                "classification": "error",
                "error": str(e),
            })

    # Sort by ΔΔG descending (strongest hotspots first)
    results.sort(key=lambda r: r.get("ddG") or 0.0, reverse=True)

    result = {
        "wt_dG": round(wt_dG, 2),
        "wt_std": round(wt_std, 2),
        "wt_n_replicates": n_replicates,
        "wt_noise_floor": round(noise_floor, 2),
        "mutations": results,
    }
    if wt_warning:
        result["wt_warning"] = wt_warning
    return result


def run_multi_pose_ala_scan_slurm(
    project_dir: Path,
    interface_data: dict,
    top_pdbs: list[dict],
    nstruct: int = 3,
    max_mutations: int = 8,
    time_limit: str = "00:30:00",
    cpus: int = 4,
) -> dict:
    """
    Submit multi-decoy alanine scanning: one SLURM array job per docking pose.

    Args:
        project_dir: Project working directory
        interface_data: From analyze_interface()
        top_pdbs: [{pdb_path, score, desc}, ...] from docking results
        nstruct: Replicates per mutation per pose
        max_mutations: Max hotspot mutations to scan
        time_limit: SLURM time per task
        cpus: CPUs per task

    Returns:
        job_info dict saved to ala_scan/ala_scan_job_info.json
    """
    import json
    from backend.experiment_designer import rank_hotspots

    # Rank hotspots once (same mutations for all poses)
    hotspots = rank_hotspots(interface_data, max_hotspots=max_mutations)
    if not hotspots:
        raise RuntimeError("No hotspot candidates found (all residues have ΔSASA < 20 Å²)")

    scan_dir = project_dir / "ala_scan"
    scan_dir.mkdir(parents=True, exist_ok=True)

    poses = []
    all_mutations = None  # mutations without pose_num (canonical list)

    for i, pdb_info in enumerate(top_pdbs):
        pdb_path = Path(pdb_info["pdb_path"])
        pose_dir = scan_dir / f"pose_{i}"

        # Compute pose numbers for this specific PDB
        pose_map = _compute_pose_numbers(pdb_path)

        mutations = []
        for h in hotspots:
            key = (h.chain, h.resid)
            if key not in pose_map:
                continue
            mutations.append({
                "chain": h.chain,
                "resname": h.resname,
                "resid": h.resid,
                "one_letter": h.one_letter,
                "pose_num": pose_map[key],
                "mutation": h.mutation,
                "side": h.side,
            })

        if not mutations:
            continue

        # Store canonical mutation list (without pose_num) on first pose
        if all_mutations is None:
            all_mutations = [
                {k: v for k, v in m.items() if k != "pose_num"}
                for m in mutations
            ]

        # Submit this pose
        job_id = _setup_single_pose_scan(
            scan_dir=pose_dir,
            complex_pdb=pdb_path,
            mutations=mutations,
            nstruct=nstruct,
            cpus=cpus,
            time_limit=time_limit,
        )

        poses.append({
            "job_id": job_id,
            "pose_dir": f"pose_{i}",
            "pdb_path": str(pdb_path),
            "score": pdb_info.get("score"),
            "desc": pdb_info.get("desc", ""),
        })

        print(f"  Pose {i}: job {job_id} ({len(mutations)} mutations + WT)")

    if not poses:
        raise RuntimeError("Could not map hotspots to pose numbers in any PDB")

    num_tasks_per_pose = (len(all_mutations) + 1) if all_mutations else 1

    job_info = {
        "mode": "multi_pose",
        "poses": poses,
        "mutations": all_mutations or [],
        "nstruct": nstruct,
        "num_tasks_per_pose": num_tasks_per_pose,
        "n_poses": len(poses),
    }

    (scan_dir / "ala_scan_job_info.json").write_text(json.dumps(job_info, indent=2))
    print(f"Submitted multi-pose alanine scan: {len(poses)} poses, {len(all_mutations or [])} mutations each")

    return job_info


def parse_multi_pose_results(scan_dir: Path, job_info: dict) -> dict:
    """
    Aggregate alanine scan results across multiple docking poses.

    For each mutation, collects ΔΔG from each pose that succeeded,
    computes cross-pose mean, std, and CI-aware classification.

    Returns a dict with consensus + per_pose_results.
    """
    import math
    # t-distribution critical values for 95% CI (two-tailed)
    # Precomputed to avoid scipy dependency: t_{df, 0.975}
    _T_CRIT = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
               6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
               15: 2.131, 20: 2.086, 30: 2.042, 50: 2.009, 100: 1.984}

    def _t_crit_val(df: int) -> float:
        if df in _T_CRIT:
            return _T_CRIT[df]
        # For large df, converge toward z=1.96
        if df > 100:
            return 1.96
        # Linear interpolate between known values
        keys = sorted(_T_CRIT.keys())
        for i in range(len(keys) - 1):
            if keys[i] < df < keys[i + 1]:
                lo, hi = keys[i], keys[i + 1]
                frac = (df - lo) / (hi - lo)
                return _T_CRIT[lo] + frac * (_T_CRIT[hi] - _T_CRIT[lo])
        return 1.96

    scan_dir = Path(scan_dir)
    poses_info = job_info["poses"]
    mutations_info = job_info["mutations"]
    nstruct = job_info.get("nstruct", 3)

    per_pose_results = {}
    pose_wt_stds = []

    # Parse each pose independently using existing single-pose parser
    for pose in poses_info:
        pose_dir = scan_dir / pose["pose_dir"]
        # Build a single-pose job_info for the parser
        # Read the pose-specific mutations.txt to get pose_nums
        pose_mutations_path = pose_dir / "mutations.txt"
        if not pose_mutations_path.exists():
            continue

        # The mutations for each pose have pose-specific pose_nums,
        # but parse_alanine_scan_results only needs the mutation identity fields.
        # We need to reconstruct per-pose mutations with correct indices.
        pose_job_info = {
            "mutations": mutations_info,
            "nstruct": nstruct,
            "num_tasks": len(mutations_info) + 1,
        }

        try:
            pose_result = parse_alanine_scan_results(pose_dir, pose_job_info)
            per_pose_results[pose["pose_dir"]] = pose_result
            if pose_result.get("wt_std") is not None:
                pose_wt_stds.append(pose_result["wt_std"])
        except Exception as e:
            print(f"Warning: failed to parse {pose['pose_dir']}: {e}")
            continue

    if not per_pose_results:
        raise RuntimeError("No poses produced parseable results")

    # Noise floor = max WT std across all poses (conservative)
    noise_floor = max(pose_wt_stds) if pose_wt_stds else 0.0

    # Aggregate consensus per mutation
    consensus_mutations = []
    for mut in mutations_info:
        pose_ddGs = []
        pose_details = []
        # Collect per-term energy decomps across poses for averaging
        pose_decomps: dict[str, list[float]] = {t: [] for t in DECOMP_TERMS}

        for pose_name, pose_result in per_pose_results.items():
            match = None
            for pm in pose_result["mutations"]:
                if pm["chain"] == mut["chain"] and pm["resid"] == mut["resid"]:
                    match = pm
                    break

            if match and match.get("ddG") is not None:
                pose_ddGs.append(match["ddG"])
                pose_details.append({
                    "pose": pose_name,
                    "ddG": match["ddG"],
                    "mut_std": match.get("mut_std", 0.0),
                    "wt_dG": match.get("wt_dG", 0.0),
                })
                # Collect energy decomp terms
                decomp = match.get("energy_decomp", {})
                for t in DECOMP_TERMS:
                    if t in decomp and decomp[t] is not None:
                        pose_decomps[t].append(decomp[t])

        n_poses_ok = len(pose_ddGs)

        if n_poses_ok == 0:
            consensus_mutations.append({
                "mutation": mut["mutation"],
                "chain": mut["chain"],
                "resname": mut["resname"],
                "resid": mut["resid"],
                "side": mut.get("side", ""),
                "mean_ddG": None,
                "ddG": None,
                "cross_pose_std": None,
                "n_poses_ok": 0,
                "ci_lower": None,
                "ci_upper": None,
                "snr": None,
                "classification": "error",
                "error": "No poses succeeded for this mutation",
                "per_pose": pose_details,
            })
            continue

        mean_ddG = sum(pose_ddGs) / n_poses_ok

        cross_pose_std = 0.0
        if n_poses_ok > 1:
            var = sum((v - mean_ddG) ** 2 for v in pose_ddGs) / (n_poses_ok - 1)
            cross_pose_std = var ** 0.5

        # Cross-pose confidence interval (t-distribution for small n)
        cross_se = cross_pose_std / math.sqrt(n_poses_ok) if n_poses_ok > 1 else 0.0
        t_crit = _t_crit_val(max(n_poses_ok - 1, 1)) if n_poses_ok > 1 else 1.96
        ci_lower = mean_ddG - t_crit * cross_se
        ci_upper = mean_ddG + t_crit * cross_se

        # SNR vs noise floor (propagated sigma)
        snr = abs(mean_ddG) / noise_floor if noise_floor > 0 else float('inf')

        classification = _classify_ddG(mean_ddG, ci_lower, ci_upper)
        if snr < 1.5 and classification not in ("weak", "stabilizing", "error"):
            classification = "uncertain"

        # Average energy decomposition across poses
        avg_decomp = {}
        for t in DECOMP_TERMS:
            vals = pose_decomps[t]
            avg_decomp[t] = round(sum(vals) / len(vals), 2) if vals else 0.0
        dominant = max(DECOMP_TERMS, key=lambda t: abs(avg_decomp[t]))
        avg_decomp["dominant"] = dominant

        consensus_mutations.append({
            "mutation": mut["mutation"],
            "chain": mut["chain"],
            "resname": mut["resname"],
            "resid": mut["resid"],
            "side": mut.get("side", ""),
            "mean_ddG": round(mean_ddG, 2),
            "ddG": round(mean_ddG, 2),  # alias for frontend compat
            "cross_pose_std": round(cross_pose_std, 2),
            "n_poses_ok": n_poses_ok,
            "ci_lower": round(ci_lower, 2),
            "ci_upper": round(ci_upper, 2),
            "snr": round(snr, 2),
            "classification": classification,
            "per_pose": pose_details,
            "energy_decomp": avg_decomp,
        })

    # Sort by ΔΔG descending
    consensus_mutations.sort(key=lambda r: r.get("ddG") or 0.0, reverse=True)

    # Use first pose's WT dG as representative
    first_pose = next(iter(per_pose_results.values()))

    return {
        "mode": "multi_pose",
        "n_poses": len(per_pose_results),
        "wt_dG": first_pose["wt_dG"],
        "wt_std": first_pose.get("wt_std", 0.0),
        "wt_n_replicates": first_pose.get("wt_n_replicates"),
        "wt_noise_floor": round(noise_floor, 2),
        "mutations": consensus_mutations,
        "per_pose_results": per_pose_results,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ncAA Bayesian Optimization — SLURM integration
# ═══════════════════════════════════════════════════════════════════════════

def handle_ncaa_params_upload(project_dir: Path, files) -> Path:
    """Save uploaded .params files to project_dir/ncaa_params/.

    Returns the params directory path.
    """
    params_dir = project_dir / "ncaa_params"
    params_dir.mkdir(parents=True, exist_ok=True)

    ncaa_names = []
    for f in files:
        fname = getattr(f, "filename", None) or "unknown.params"
        dest = params_dir / fname
        content = f.file.read()
        dest.write_bytes(content)
        # Extract NAME from params file
        for line in content.decode("utf-8", errors="replace").splitlines():
            if line.startswith("NAME"):
                parts = line.split()
                if len(parts) >= 2:
                    ncaa_names.append(parts[1].strip())
                break

    return params_dir, ncaa_names


def run_ncaa_optimize_slurm(
    complex_pdb: Path,
    output_dir: Path,
    partners: str,
    ncaa_list: list,
    params_dir: Path = None,
    positions: str = "auto",
    mode: str = "single",
    n_calls: int = 20,
    trials: int = 1,
    seed_csv: str = "",
    time_limit: str = None,
    cpus: int = None,
) -> dict:
    """Submit ncAA Bayesian optimization as a SLURM job.

    Mirrors run_alanine_scan_slurm() pattern.
    """
    time_limit = time_limit or str(SLURM_NCAA_OPT_TIME)
    cpus = cpus or int(SLURM_NCAA_OPT_CPUS)

    opt_dir = output_dir / "ncaa_opt"
    opt_dir.mkdir(parents=True, exist_ok=True)

    # Clean old results from previous runs
    for old_file in opt_dir.glob("results_*"):
        old_file.unlink()
    for old_file in opt_dir.glob("slurm-*"):
        old_file.unlink()

    # Copy complex PDB
    local_pdb = opt_dir / "complex_input.pdb"
    shutil.copy2(str(complex_pdb), str(local_pdb))

    # Symlink or copy params directory (only if custom params were uploaded)
    local_params = None
    if params_dir and params_dir.exists():
        local_params = opt_dir / "ncaa_params"
        if not local_params.exists():
            shutil.copytree(str(params_dir), str(local_params))

    output_prefix = str(opt_dir / "results")
    ncaa_csv = ",".join(ncaa_list)

    # Build optimizer command
    opt_cmd = (
        f"python {NCAA_OPTIMIZER_SCRIPT} "
        f"--pdb_filename {local_pdb} "
        f"--partners {partners} "
        f"--ncaa_list {ncaa_csv} "
        f"--positions {positions} "
        f"--mode {mode} "
        f"--n_calls {n_calls} "
        f"--trials {trials} "
        f"--export_surrogate "
        f"--output_prefix {output_prefix} "
        f"--pyrosetta_db {NCAA_PYROSETTA_DB}"
    )
    if local_params:
        opt_cmd += f" --extra_res_path {local_params}"
    if seed_csv:
        opt_cmd += f" --seed_csv {seed_csv}"

    # Write SLURM script
    script = (
        "#!/bin/bash\n"
        f"#SBATCH --job-name=ncaa_opt\n"
        f"#SBATCH --account={SLURM_ACCOUNT}\n"
        f"#SBATCH --nodes=1\n"
        f"#SBATCH --ntasks=1\n"
        f"#SBATCH --cpus-per-task={cpus}\n"
        f"#SBATCH --time={time_limit}\n"
        f"#SBATCH --output={opt_dir}/slurm-%j.out\n"
        f"#SBATCH --error={opt_dir}/slurm-%j.err\n"
        f"\n"
        f"source {NCAA_CONDA_BASE}/etc/profile.d/conda.sh\n"
        f"conda activate {NCAA_PYROSETTA_ENV}\n"
        f"\n"
        f"cd {opt_dir}\n"
        f"{opt_cmd}\n"
    )

    script_path = opt_dir / "ncaa_opt_job.sh"
    script_path.write_text(script)

    # Submit
    result = subprocess.run(
        ["sbatch", str(script_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"sbatch failed: {result.stderr}")

    job_id = result.stdout.strip().split()[-1]

    job_info = {
        "job_id": job_id,
        "mode": mode,
        "ncaa_list": ncaa_list,
        "n_calls": n_calls,
        "trials": trials,
        "positions": positions,
        "output_prefix": output_prefix,
        "params_dir": str(local_params) if local_params else None,
        "opt_dir": str(opt_dir),
        "script_path": str(script_path),
    }

    info_path = opt_dir / "ncaa_opt_job_info.json"
    import json
    info_path.write_text(json.dumps(job_info, indent=2))

    return job_info


def check_ncaa_optimize_job(job_id: str, opt_dir: Path, n_calls: int) -> dict:
    """Check SLURM job status and read progress from history CSV."""
    import json

    # Check SLURM status via sacct
    try:
        result = subprocess.run(
            ["sacct", "-j", job_id, "--format=JobID,State,ExitCode,Elapsed",
             "--noheader", "--parsable2"],
            capture_output=True, text=True, timeout=10,
        )
        lines = [l for l in result.stdout.strip().split("\n") if l and ".batch" not in l and ".extern" not in l]
        if lines:
            parts = lines[0].split("|")
            state = parts[1].strip() if len(parts) > 1 else "UNKNOWN"
        else:
            state = "UNKNOWN"
    except Exception:
        state = "UNKNOWN"

    # Normalize state
    if state.startswith("RUNNING"):
        status = "RUNNING"
    elif state.startswith("PENDING"):
        status = "PENDING"
    elif state.startswith("COMPLETED"):
        status = "COMPLETED"
    elif state.startswith("FAILED") or state.startswith("TIMEOUT"):
        status = "FAILED"
    elif state.startswith("CANCEL"):
        status = "CANCELLED"
    else:
        status = state

    # Read progress from history CSV (use csv.reader to handle multiline fields)
    evaluations_done = 0
    history_csv = opt_dir / "results_history.csv"
    if history_csv.exists():
        import csv
        try:
            with open(history_csv) as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                evaluations_done = sum(1 for _ in reader)
        except Exception:
            evaluations_done = 0

    return {
        "job_id": job_id,
        "status": status,
        "evaluations_done": evaluations_done,
        "evaluations_total": n_calls,
    }


def parse_ncaa_optimize_results(opt_dir: Path, job_info: dict) -> dict:
    """Parse optimization results from output files."""
    import json
    import csv

    output_prefix = job_info.get("output_prefix", str(opt_dir / "results"))
    summary_path = Path(f"{output_prefix}_summary.json")
    history_path = Path(f"{output_prefix}_history.csv")
    pareto_path = Path(f"{output_prefix}_pareto.csv")

    results = {
        "mode": job_info.get("mode", "single"),
        "n_calls": job_info.get("n_calls", 0),
    }

    # Read summary
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        top5 = summary.get("top5", [])
        results["best"] = top5[0] if top5 else None
        results["top5"] = summary.get("top5", [])
        results["best_score"] = summary.get("best_score")
        results["best_params"] = summary.get("best_params")

    # Read history
    if history_path.exists():
        with open(history_path) as f:
            reader = csv.DictReader(f)
            history = []
            for row in reader:
                # Convert numeric fields
                for key in ["ddg_bind", "ddg_fold", "objective_score", "position",
                            "wt_bind", "mut_bind", "wt_total", "mut_total",
                            "sasa", "resid"]:
                    if key in row and row[key]:
                        try:
                            row[key] = float(row[key])
                        except (ValueError, TypeError):
                            pass
                history.append(row)
            results["history"] = history

    # Read Pareto front
    if pareto_path.exists():
        with open(pareto_path) as f:
            reader = csv.DictReader(f)
            pareto = []
            for row in reader:
                for key in ["ddg_bind", "abs_ddg_fold"]:
                    if key in row:
                        try:
                            row[key] = float(row[key])
                        except (ValueError, TypeError):
                            pass
                pareto.append(row)
            results["pareto"] = pareto

    return results
