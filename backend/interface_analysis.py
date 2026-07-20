#!/usr/bin/env python3
"""
interface_analysis.py

Analyze protein-protein docking interfaces from PDB files.
Extracts interface residues, classifies contacts (H-bonds, salt bridges,
hydrophobic), and computes per-residue delta-SASA.

Dependencies:
  - BioPython >= 1.80 (BSD-3-Clause, https://github.com/biopython/biopython)
"""

from pathlib import Path
from dataclasses import dataclass, field, asdict

import numpy as np
from Bio.PDB import PDBParser, Selection
from Bio.PDB.SASA import ShrakeRupley
from Bio.PDB.NeighborSearch import NeighborSearch


# ── Residue classification ────────────────────────────────────

CHARGED_POS = {"ARG", "LYS", "HIS"}
CHARGED_NEG = {"ASP", "GLU"}
POLAR = {"SER", "THR", "ASN", "GLN", "TYR", "CYS"}
HYDROPHOBIC = {"ALA", "VAL", "LEU", "ILE", "PHE", "TRP", "MET", "PRO"}

# Donor/acceptor atoms for H-bond detection
HBOND_DONORS = {"N", "NE", "NE1", "NE2", "NH1", "NH2", "ND1", "ND2",
                "NZ", "OG", "OG1", "OH", "SG"}
HBOND_ACCEPTORS = {"O", "OD1", "OD2", "OE1", "OE2", "OG", "OG1",
                   "OH", "ND1", "NE2", "SD", "SG"}

# Salt bridge atom pairs
SALT_BRIDGE_POS_ATOMS = {"NZ", "NH1", "NH2", "NE", "ND1", "NE2"}  # Lys, Arg, His
SALT_BRIDGE_NEG_ATOMS = {"OD1", "OD2", "OE1", "OE2"}  # Asp, Glu


# ── Data structures ───────────────────────────────────────────

@dataclass
class ContactResidue:
    chain: str
    resname: str
    resid: int
    delta_sasa: float = 0.0
    n_contacts: int = 0
    classification: str = ""  # "charged+", "charged-", "polar", "hydrophobic"

    def to_dict(self):
        return asdict(self)


@dataclass
class Contact:
    type: str  # "hbond", "salt_bridge", "hydrophobic"
    chain_a: str
    resname_a: str
    resid_a: int
    atom_a: str
    chain_b: str
    resname_b: str
    resid_b: int
    atom_b: str
    distance: float

    def to_dict(self):
        return asdict(self)


@dataclass
class InterfaceAnalysis:
    residues_a: list[ContactResidue] = field(default_factory=list)
    residues_b: list[ContactResidue] = field(default_factory=list)
    hbonds: list[Contact] = field(default_factory=list)
    salt_bridges: list[Contact] = field(default_factory=list)
    hydrophobic_contacts: list[Contact] = field(default_factory=list)
    total_buried_sasa: float = 0.0
    chain_a_id: str = "A"
    chain_b_id: str = "B"

    def to_dict(self):
        return {
            "residues_a": [r.to_dict() for r in self.residues_a],
            "residues_b": [r.to_dict() for r in self.residues_b],
            "hbonds": [c.to_dict() for c in self.hbonds],
            "salt_bridges": [c.to_dict() for c in self.salt_bridges],
            "hydrophobic_contacts": [c.to_dict() for c in self.hydrophobic_contacts],
            "total_buried_sasa": self.total_buried_sasa,
            "chain_a_id": self.chain_a_id,
            "chain_b_id": self.chain_b_id,
            "summary": self.summary(),
        }

    def summary(self) -> dict:
        """Quick stats for display."""
        return {
            "n_interface_residues_a": len(self.residues_a),
            "n_interface_residues_b": len(self.residues_b),
            "n_hbonds": len(self.hbonds),
            "n_salt_bridges": len(self.salt_bridges),
            "n_hydrophobic_contacts": len(self.hydrophobic_contacts),
            "total_buried_sasa": round(float(self.total_buried_sasa), 1),
            "dominant_interaction": self._dominant_interaction(),
        }

    def _dominant_interaction(self) -> str:
        counts = {
            "hydrogen bonding": len(self.hbonds),
            "electrostatic (salt bridges)": len(self.salt_bridges),
            "hydrophobic packing": len(self.hydrophobic_contacts),
        }
        if not any(counts.values()):
            return "unknown"
        return max(counts, key=counts.get)


# ── Helpers ───────────────────────────────────────────────────

def _classify_residue(resname: str) -> str:
    resname = resname.strip().upper()
    if resname in CHARGED_POS:
        return "charged+"
    if resname in CHARGED_NEG:
        return "charged-"
    if resname in POLAR:
        return "polar"
    if resname in HYDROPHOBIC:
        return "hydrophobic"
    return "other"


def _get_chain_atoms(structure, chain_id: str):
    """Get all atoms for a given chain from model 0."""
    model = structure[0]
    atoms = []
    for chain in model:
        if chain.id == chain_id:
            for residue in chain:
                if residue.id[0] == " ":  # skip heteroatoms/water
                    atoms.extend(residue.get_atoms())
    return atoms


def _compute_sasa_per_residue(structure) -> dict:
    """Compute SASA for each residue. Returns {(chain, resid): sasa} as native floats."""
    sr = ShrakeRupley()
    sr.compute(structure[0], level="R")
    result = {}
    for chain in structure[0]:
        for residue in chain:
            if residue.id[0] == " ":
                result[(chain.id, residue.id[1])] = float(residue.sasa)
    return result


def _build_single_chain_structure(structure, chain_id: str):
    """Create a new structure containing only one chain (for isolated SASA)."""
    from Bio.PDB import StructureBuilder
    sb = StructureBuilder.StructureBuilder()
    sb.init_structure("isolated")
    sb.init_model(0)
    sb.init_seg(" ")

    model = structure[0]
    for chain in model:
        if chain.id == chain_id:
            sb.init_chain(chain.id)
            for residue in chain:
                if residue.id[0] == " ":
                    sb.init_residue(residue.resname, *residue.id)
                    for atom in residue:
                        sb.init_atom(
                            atom.name, atom.coord.tolist(), atom.bfactor,
                            atom.occupancy, atom.altloc, atom.fullname,
                            atom.serial_number, atom.element
                        )
    return sb.get_structure()


# ── Main analysis function ────────────────────────────────────

def analyze_interface(
    pdb_path: Path,
    chain_a: str = "A",
    chain_b: str = "B",
    contact_dist: float = 5.0,
    hbond_dist: float = 3.5,
    salt_bridge_dist: float = 4.0,
    hydrophobic_dist: float = 4.5,
) -> InterfaceAnalysis:
    """
    Analyze the interface between two chains in a docked PDB.

    Args:
        pdb_path: Path to the docked complex PDB file
        chain_a: Chain ID for the receptor
        chain_b: Chain ID for the binder
        contact_dist: Distance cutoff for interface residues (Angstroms)
        hbond_dist: Distance cutoff for hydrogen bonds
        salt_bridge_dist: Distance cutoff for salt bridges
        hydrophobic_dist: Distance cutoff for hydrophobic contacts

    Returns:
        InterfaceAnalysis with all interface data
    """
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("complex", str(pdb_path))

    result = InterfaceAnalysis(chain_a_id=chain_a, chain_b_id=chain_b)

    # ── Get atoms per chain ───────────────────────────────────
    atoms_a = _get_chain_atoms(structure, chain_a)
    atoms_b = _get_chain_atoms(structure, chain_b)

    if not atoms_a or not atoms_b:
        return result  # empty — chains not found

    # ── Find interface residues (within contact_dist across chains) ──
    ns_b = NeighborSearch(atoms_b)
    interface_residues_a = set()
    interface_residues_b = set()

    for atom_a in atoms_a:
        nearby = ns_b.search(atom_a.coord, contact_dist, level="A")
        for atom_b in nearby:
            res_a = atom_a.get_parent()
            res_b = atom_b.get_parent()
            if res_a.id[0] != " " or res_b.id[0] != " ":
                continue
            interface_residues_a.add((chain_a, res_a.resname, res_a.id[1]))
            interface_residues_b.add((chain_b, res_b.resname, res_b.id[1]))

    # ── Compute delta-SASA ────────────────────────────────────
    # SASA of whole complex
    complex_sasa = _compute_sasa_per_residue(structure)

    # SASA of isolated chains
    struct_a = _build_single_chain_structure(structure, chain_a)
    struct_b = _build_single_chain_structure(structure, chain_b)
    isolated_sasa_a = _compute_sasa_per_residue(struct_a)
    isolated_sasa_b = _compute_sasa_per_residue(struct_b)

    total_buried = 0.0

    # Build ContactResidue objects for chain A
    for ch, resname, resid in sorted(interface_residues_a, key=lambda x: x[2]):
        iso = isolated_sasa_a.get((ch, resid), 0.0)
        cpx = complex_sasa.get((ch, resid), 0.0)
        delta = iso - cpx
        total_buried += max(0.0, delta)
        result.residues_a.append(ContactResidue(
            chain=ch, resname=resname, resid=resid,
            delta_sasa=round(float(delta), 1),
            classification=_classify_residue(resname),
        ))

    # Build ContactResidue objects for chain B
    for ch, resname, resid in sorted(interface_residues_b, key=lambda x: x[2]):
        iso = isolated_sasa_b.get((ch, resid), 0.0)
        cpx = complex_sasa.get((ch, resid), 0.0)
        delta = float(iso - cpx)
        total_buried += max(0.0, delta)
        result.residues_b.append(ContactResidue(
            chain=ch, resname=resname, resid=resid,
            delta_sasa=round(float(delta), 1),
            classification=_classify_residue(resname),
        ))

    result.total_buried_sasa = round(float(total_buried), 1)

    # ── Classify contacts ─────────────────────────────────────
    # Count contacts per residue
    contact_counts = {}  # (chain, resid) -> count

    for atom_a in atoms_a:
        res_a = atom_a.get_parent()
        if res_a.id[0] != " ":
            continue
        nearby = ns_b.search(atom_a.coord, max(hbond_dist, salt_bridge_dist, hydrophobic_dist), level="A")

        for atom_b in nearby:
            res_b = atom_b.get_parent()
            if res_b.id[0] != " ":
                continue

            dist = float(atom_a - atom_b)  # BioPython distance → native float
            resname_a = res_a.resname.strip()
            resname_b = res_b.resname.strip()
            aname_a = atom_a.name.strip()
            aname_b = atom_b.name.strip()

            key_a = (chain_a, res_a.id[1])
            key_b = (chain_b, res_b.id[1])
            contact_counts[key_a] = contact_counts.get(key_a, 0) + 1
            contact_counts[key_b] = contact_counts.get(key_b, 0) + 1

            contact_base = dict(
                chain_a=chain_a, resname_a=resname_a, resid_a=res_a.id[1], atom_a=aname_a,
                chain_b=chain_b, resname_b=resname_b, resid_b=res_b.id[1], atom_b=aname_b,
                distance=round(float(dist), 2),
            )

            # Hydrogen bond: donor-acceptor within hbond_dist, involving N/O
            if dist <= hbond_dist:
                is_donor_a = aname_a in HBOND_DONORS and atom_a.element in ("N", "O", "S")
                is_acceptor_b = aname_b in HBOND_ACCEPTORS and atom_b.element in ("N", "O", "S")
                is_donor_b = aname_b in HBOND_DONORS and atom_b.element in ("N", "O", "S")
                is_acceptor_a = aname_a in HBOND_ACCEPTORS and atom_a.element in ("N", "O", "S")

                if (is_donor_a and is_acceptor_b) or (is_donor_b and is_acceptor_a):
                    result.hbonds.append(Contact(type="hbond", **contact_base))
                    continue

            # Salt bridge: charged+ within salt_bridge_dist of charged-
            if dist <= salt_bridge_dist:
                pos_neg = (
                    (resname_a in CHARGED_POS and aname_a in SALT_BRIDGE_POS_ATOMS and
                     resname_b in CHARGED_NEG and aname_b in SALT_BRIDGE_NEG_ATOMS)
                )
                neg_pos = (
                    (resname_a in CHARGED_NEG and aname_a in SALT_BRIDGE_NEG_ATOMS and
                     resname_b in CHARGED_POS and aname_b in SALT_BRIDGE_POS_ATOMS)
                )
                if pos_neg or neg_pos:
                    result.salt_bridges.append(Contact(type="salt_bridge", **contact_base))
                    continue

            # Hydrophobic: C-C contact between hydrophobic residues
            if dist <= hydrophobic_dist:
                if (atom_a.element == "C" and atom_b.element == "C" and
                        resname_a in HYDROPHOBIC and resname_b in HYDROPHOBIC):
                    result.hydrophobic_contacts.append(Contact(type="hydrophobic", **contact_base))

    # Update contact counts on residues
    for cr in result.residues_a:
        cr.n_contacts = contact_counts.get((cr.chain, cr.resid), 0)
    for cr in result.residues_b:
        cr.n_contacts = contact_counts.get((cr.chain, cr.resid), 0)

    # Deduplicate contacts (same residue pair may appear multiple times)
    result.hbonds = _dedup_contacts(result.hbonds)
    result.salt_bridges = _dedup_contacts(result.salt_bridges)
    result.hydrophobic_contacts = _dedup_contacts(result.hydrophobic_contacts)

    return result


def _dedup_contacts(contacts: list[Contact]) -> list[Contact]:
    """Keep only the closest contact per residue pair."""
    best = {}
    for c in contacts:
        key = (c.resid_a, c.resid_b, c.type)
        if key not in best or c.distance < best[key].distance:
            best[key] = c
    return sorted(best.values(), key=lambda c: c.distance)


# ── Multi-component helpers ──────────────────────────────────

def parse_partners(partners_str: str) -> tuple[list[str], list[str]]:
    """
    Parse a Rosetta partners string into receptor and binder chain lists.

    Examples:
        "A_B"   -> (["A"], ["B"])
        "A_BCD" -> (["A"], ["B", "C", "D"])
        "AB_C"  -> (["A", "B"], ["C"])
        "AB_CD" -> (["A", "B"], ["C", "D"])
    """
    groups = partners_str.strip().split("_")
    if len(groups) != 2 or not groups[0] or not groups[1]:
        return ["A"], ["B"]
    return list(groups[0]), list(groups[1])


def analyze_multi_interface(
    pdb_path: Path,
    receptor_chains: list[str],
    binder_chains: list[str],
    contact_dist: float = 5.0,
    hbond_dist: float = 3.5,
    salt_bridge_dist: float = 4.0,
    hydrophobic_dist: float = 4.5,
) -> InterfaceAnalysis:
    """
    Analyze the interface between receptor chain group and binder chain group.

    For each (receptor, binder) chain pair, runs analyze_interface() and merges
    results.  Residues appearing in multiple pair analyses are deduplicated by
    (chain, resid), keeping the max delta_sasa and max n_contacts.

    For the simple 2-chain case this delegates directly to analyze_interface().
    """
    # Fast path: simple 2-chain case — no overhead
    if len(receptor_chains) == 1 and len(binder_chains) == 1:
        return analyze_interface(
            pdb_path, receptor_chains[0], binder_chains[0],
            contact_dist, hbond_dist, salt_bridge_dist, hydrophobic_dist,
        )

    # Run pairwise analyses
    pair_results: list[InterfaceAnalysis] = []
    for rc in receptor_chains:
        for bc in binder_chains:
            pair = analyze_interface(
                pdb_path, rc, bc,
                contact_dist, hbond_dist, salt_bridge_dist, hydrophobic_dist,
            )
            pair_results.append(pair)

    # Merge receptor-side residues: dedup by (chain, resid), keep max delta_sasa
    rec_best: dict[tuple[str, int], ContactResidue] = {}
    for pair in pair_results:
        for r in pair.residues_a:
            key = (r.chain, r.resid)
            if key not in rec_best or abs(r.delta_sasa) > abs(rec_best[key].delta_sasa):
                rec_best[key] = ContactResidue(
                    chain=r.chain, resname=r.resname, resid=r.resid,
                    delta_sasa=r.delta_sasa,
                    n_contacts=max(r.n_contacts, rec_best.get(key, r).n_contacts),
                    classification=r.classification,
                )
            else:
                existing = rec_best[key]
                existing.n_contacts = max(existing.n_contacts, r.n_contacts)

    # Binder-side residues: same dedup logic
    bind_best: dict[tuple[str, int], ContactResidue] = {}
    for pair in pair_results:
        for r in pair.residues_b:
            key = (r.chain, r.resid)
            if key not in bind_best or abs(r.delta_sasa) > abs(bind_best[key].delta_sasa):
                bind_best[key] = ContactResidue(
                    chain=r.chain, resname=r.resname, resid=r.resid,
                    delta_sasa=r.delta_sasa,
                    n_contacts=max(r.n_contacts, bind_best.get(key, r).n_contacts),
                    classification=r.classification,
                )
            else:
                existing = bind_best[key]
                existing.n_contacts = max(existing.n_contacts, r.n_contacts)

    # Merge and deduplicate contacts across all pairs
    all_hbonds = []
    all_salt = []
    all_hydro = []
    for pair in pair_results:
        all_hbonds.extend(pair.hbonds)
        all_salt.extend(pair.salt_bridges)
        all_hydro.extend(pair.hydrophobic_contacts)

    all_hbonds = _dedup_contacts(all_hbonds)
    all_salt = _dedup_contacts(all_salt)
    all_hydro = _dedup_contacts(all_hydro)

    # Total buried SASA from deduplicated residues
    total_buried = sum(max(0.0, r.delta_sasa) for r in rec_best.values())
    total_buried += sum(max(0.0, r.delta_sasa) for r in bind_best.values())

    return InterfaceAnalysis(
        residues_a=sorted(rec_best.values(), key=lambda r: (r.chain, r.resid)),
        residues_b=sorted(bind_best.values(), key=lambda r: (r.chain, r.resid)),
        hbonds=all_hbonds,
        salt_bridges=all_salt,
        hydrophobic_contacts=all_hydro,
        total_buried_sasa=round(float(total_buried), 1),
        chain_a_id="".join(receptor_chains),
        chain_b_id="".join(binder_chains),
    )
