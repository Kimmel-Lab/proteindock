#!/usr/bin/env python3
"""
experiment_designer.py

Suggest wet-lab validation experiments from docking interface analysis.
Ranks hot spot residues by delta-SASA and contact count, suggests
alanine mutations, and outputs a validation plan.

Dependencies:
  - BioPython (BSD-3-Clause, https://github.com/biopython/biopython)
  - interface_analysis.py (this project)
"""

from dataclasses import dataclass, asdict

# Residues known to be disproportionately hot spots at interfaces
# (Bogan & Thorn, J Mol Biol 1998; Moreira et al., Proteins 2007)
HOTSPOT_BIAS = {"TRP": 3.0, "TYR": 2.0, "ARG": 2.0, "ASP": 1.5, "GLU": 1.5,
                "PHE": 1.5, "HIS": 1.5, "LYS": 1.2}

# 3-letter to 1-letter amino acid codes
AA_MAP = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


@dataclass
class HotSpot:
    chain: str
    resname: str
    resid: int
    one_letter: str
    delta_sasa: float
    n_contacts: int
    classification: str
    hotspot_score: float
    reason: str
    mutation: str  # e.g. "R142A"
    side: str = ""  # "receptor" or "binder"

    def to_dict(self):
        return asdict(self)


@dataclass
class ExperimentPlan:
    hotspots: list[HotSpot]
    mutations: list[str]
    experiments: list[dict]  # {name, description, priority}
    summary: str

    def to_dict(self):
        return {
            "hotspots": [h.to_dict() for h in self.hotspots],
            "mutations": self.mutations,
            "experiments": self.experiments,
            "summary": self.summary,
        }


def rank_hotspots(interface_data: dict, max_hotspots: int = 8) -> list[HotSpot]:
    """
    Rank interface residues by hotspot potential.

    Scoring formula:
      hotspot_score = delta_sasa * residue_bias * (1 + log(n_contacts))

    Residues with delta-SASA < 20 Å² are excluded (not truly buried).
    """
    import math

    # Tag residues with side information (receptor = residues_a, binder = residues_b)
    all_residues = []
    for r in interface_data.get("residues_a", []):
        r_copy = dict(r)
        r_copy["_side"] = "receptor"
        all_residues.append(r_copy)
    for r in interface_data.get("residues_b", []):
        r_copy = dict(r)
        r_copy["_side"] = "binder"
        all_residues.append(r_copy)

    hotspots = []
    for r in all_residues:
        dsasa = r.get("delta_sasa", 0)
        if dsasa < 20.0:
            continue

        # Skip residues that are already alanine or glycine (can't mutate to Ala usefully)
        resname = r["resname"].strip().upper()
        if resname in ("ALA", "GLY"):
            continue

        bias = HOTSPOT_BIAS.get(resname, 1.0)
        n_contacts = max(r.get("n_contacts", 1), 1)
        score = dsasa * bias * (1 + math.log(n_contacts))

        # Build reason string
        reasons = []
        if dsasa > 60:
            reasons.append(f"highly buried ({dsasa:.0f} Å²)")
        elif dsasa > 30:
            reasons.append(f"buried ({dsasa:.0f} Å²)")

        if resname in HOTSPOT_BIAS and HOTSPOT_BIAS[resname] >= 2.0:
            reasons.append(f"{resname} is a known hotspot-enriched residue")

        if n_contacts > 50:
            reasons.append(f"extensive contacts ({n_contacts})")

        # Check if involved in H-bonds or salt bridges
        hbonds = interface_data.get("hbonds", [])
        salt_bridges = interface_data.get("salt_bridges", [])
        for h in hbonds:
            if (h["resid_a"] == r["resid"] and h["chain_a"] == r["chain"]) or \
               (h["resid_b"] == r["resid"] and h["chain_b"] == r["chain"]):
                reasons.append("forms inter-chain hydrogen bond")
                score *= 1.3
                break
        for s in salt_bridges:
            if (s["resid_a"] == r["resid"] and s["chain_a"] == r["chain"]) or \
               (s["resid_b"] == r["resid"] and s["chain_b"] == r["chain"]):
                reasons.append("forms inter-chain salt bridge")
                score *= 1.5
                break

        one_letter = AA_MAP.get(resname, "X")
        mutation = f"{one_letter}{r['resid']}A"

        hotspots.append(HotSpot(
            chain=r["chain"],
            resname=resname,
            resid=r["resid"],
            one_letter=one_letter,
            delta_sasa=dsasa,
            n_contacts=n_contacts,
            classification=r.get("classification", ""),
            hotspot_score=round(score, 1),
            reason="; ".join(reasons) if reasons else "interface residue",
            mutation=mutation,
            side=r.get("_side", ""),
        ))

    hotspots.sort(key=lambda h: h.hotspot_score, reverse=True)
    return hotspots[:max_hotspots]


def design_experiments(interface_data: dict, scores: dict = None) -> ExperimentPlan:
    """
    Design a validation experiment plan from interface analysis.

    Args:
        interface_data: Output from InterfaceAnalysis.to_dict()
        scores: Optional Rosetta score dict for additional context

    Returns:
        ExperimentPlan with hotspots, mutations, and experiment suggestions
    """
    hotspots = rank_hotspots(interface_data)
    summary_data = interface_data.get("summary", {})

    # Build mutation list
    mutations = []
    for h in hotspots[:5]:  # Top 5 mutations
        mutations.append(f"{h.chain}:{h.resname}{h.resid} -> ALA ({h.mutation})")

    # Suggest experiments based on interface characteristics
    experiments = []

    # Always suggest alanine scanning mutagenesis
    if hotspots:
        top_muts = ", ".join(h.mutation for h in hotspots[:3])
        experiments.append({
            "name": "Alanine scanning mutagenesis",
            "description": (
                f"Mutate top hotspot residues ({top_muts}) to alanine via site-directed mutagenesis. "
                f"Assess binding disruption by co-immunoprecipitation or pull-down assay. "
                f"Loss of binding confirms the residue's role at the interface."
            ),
            "priority": "high",
        })

    # Binding affinity measurement
    experiments.append({
        "name": "Surface Plasmon Resonance (SPR) or Bio-Layer Interferometry (BLI)",
        "description": (
            "Measure binding kinetics (kon, koff) and affinity (Kd) for wild-type and each "
            "alanine mutant. Quantifies the energetic contribution of each hotspot residue. "
            "Expected: hotspot mutations increase Kd by >10-fold."
        ),
        "priority": "high",
    })

    # Crosslinking mass spec if there are specific contacts
    n_hbonds = summary_data.get("n_hbonds", 0)
    n_salt = summary_data.get("n_salt_bridges", 0)
    if n_hbonds + n_salt > 0:
        experiments.append({
            "name": "Crosslinking mass spectrometry (XL-MS)",
            "description": (
                f"Use chemical crosslinkers (BS3/DSS for lysine-lysine, EDC for acidic-basic) "
                f"to capture the interface contacts. {n_hbonds} hydrogen bonds and {n_salt} "
                f"salt bridges predicted — crosslinks at these positions validate the docking pose."
            ),
            "priority": "medium",
        })

    # Structure determination
    bsa = summary_data.get("total_buried_sasa", 0)
    if bsa > 800:
        experiments.append({
            "name": "Co-crystal structure or cryo-EM",
            "description": (
                f"The predicted interface buries {bsa:.0f} Å² of surface area, suggesting a "
                f"stable complex suitable for structure determination. A co-crystal or cryo-EM "
                f"structure would definitively validate the docking model."
            ),
            "priority": "low (resource-intensive)",
        })

    # Build summary
    if hotspots:
        top3 = ", ".join(f"{h.resname}{h.resid}({h.chain})" for h in hotspots[:3])
        dominant = summary_data.get("dominant_interaction", "mixed")
        summary = (
            f"The docking interface buries {bsa:.0f} Å² and is primarily driven by {dominant}. "
            f"Top predicted hotspot residues are {top3}. "
            f"Alanine scanning of these residues followed by binding assays (SPR/BLI) "
            f"is the recommended validation strategy."
        )
    else:
        summary = "No significant hotspot residues detected at the interface."

    return ExperimentPlan(
        hotspots=hotspots,
        mutations=mutations,
        experiments=experiments,
        summary=summary,
    )
