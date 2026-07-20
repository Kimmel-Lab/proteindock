#!/usr/bin/env python3
"""
ai_analyst.py

AI-powered docking result interpreter using a local LLM.
Takes interface analysis + Rosetta scores and generates a biological interpretation.

Dependencies:
  - llama-cpp-python (MIT, https://github.com/abetlen/llama-cpp-python)
  - Model: TinyLlama-1.1B-Chat (Apache 2.0, https://github.com/jzhang38/TinyLlama)
    GGUF quantization by TheBloke (https://huggingface.co/TheBloke)
"""

from pathlib import Path
from typing import Optional

# Lazy-load the model to avoid startup cost
_llm = None
_MODEL_PATH = Path(__file__).resolve().parent.parent.parent / ".models" / "tinyllama-1.1b-chat.Q4_K_M.gguf"


def _get_llm():
    global _llm
    if _llm is None:
        from llama_cpp import Llama
        _llm = Llama(
            model_path=str(_MODEL_PATH),
            n_ctx=2048,
            n_threads=4,
            verbose=False,
        )
    return _llm


# ── Score interpretation rules (deterministic, no LLM needed) ─

SCORE_RULES = {
    "fa_elec": {
        "threshold": -5.0,
        "neg_meaning": "strong electrostatic complementarity at the interface",
        "pos_meaning": "electrostatic repulsion — charge clashes at the interface",
    },
    "hbond_sc": {
        "threshold": -2.0,
        "neg_meaning": "significant sidechain hydrogen bonding network",
        "pos_meaning": "minimal sidechain hydrogen bonding",
    },
    "hbond_bb_sc": {
        "threshold": -1.0,
        "neg_meaning": "backbone-sidechain hydrogen bonds contribute to binding",
        "pos_meaning": "limited backbone-sidechain H-bonds",
    },
    "fa_atr": {
        "threshold": -30.0,
        "neg_meaning": "extensive van der Waals packing — tightly fitted interface",
        "pos_meaning": "loose packing at the interface",
    },
    "fa_rep": {
        "threshold": 5.0,
        "neg_meaning": "minimal steric clashes",
        "pos_meaning": "notable steric strain at the interface",
    },
    "I_sc": {
        "threshold": -5.0,
        "neg_meaning": "favorable interface energy — strong predicted binding",
        "pos_meaning": "weak or unfavorable interface energy",
    },
}


def interpret_scores_rule_based(scores: dict) -> list[str]:
    """
    Deterministic score interpretation. Returns a list of observations.
    """
    observations = []
    for term, rules in SCORE_RULES.items():
        val = scores.get(term)
        if val is None:
            continue
        if val <= rules["threshold"]:
            observations.append(f"{term} = {val:.1f}: {rules['neg_meaning']}")
        elif val > 0 and "pos_meaning" in rules:
            observations.append(f"{term} = {val:.1f}: {rules['pos_meaning']}")
    return observations


def build_analysis_prompt(
    scores: dict,
    interface_summary: dict,
    interface_residues_a: list[dict],
    interface_residues_b: list[dict],
    hbonds: list[dict],
    salt_bridges: list[dict],
) -> str:
    """Build the LLM prompt from analysis data."""

    # Format top interface residues
    all_res = sorted(
        interface_residues_a + interface_residues_b,
        key=lambda r: r.get("delta_sasa", 0),
        reverse=True,
    )
    top_residues = all_res[:8]
    res_lines = "\n".join(
        f"  {r['chain']}:{r['resname']}{r['resid']} "
        f"(delta-SASA={r['delta_sasa']}Å², {r['classification']}, {r['n_contacts']} contacts)"
        for r in top_residues
    )

    # Format contacts
    hbond_lines = "\n".join(
        f"  {h['resname_a']}{h['resid_a']}({h['chain_a']}) -- {h['resname_b']}{h['resid_b']}({h['chain_b']}) "
        f"[{h['atom_a']}-{h['atom_b']}, {h['distance']}A]"
        for h in hbonds[:6]
    )
    salt_lines = "\n".join(
        f"  {s['resname_a']}{s['resid_a']}({s['chain_a']}) -- {s['resname_b']}{s['resid_b']}({s['chain_b']}) "
        f"[{s['distance']}A]"
        for s in salt_bridges[:4]
    )

    # Key scores
    key_scores = {k: v for k, v in scores.items()
                  if k in ("total_score", "I_sc", "fa_elec", "fa_atr", "fa_rep",
                           "hbond_sc", "hbond_bb_sc", "Fnat", "Irms", "CAPRI_rank")}
    score_text = ", ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}"
                           for k, v in key_scores.items())

    prompt = f"""You are a structural biologist interpreting a Rosetta protein-protein docking result.

DOCKING SCORES: {score_text}

INTERFACE SUMMARY:
  Buried surface area: {interface_summary['total_buried_sasa']} Å²
  Interface residues: {interface_summary['n_interface_residues_a']} (chain A) + {interface_summary['n_interface_residues_b']} (chain B)
  Hydrogen bonds: {interface_summary['n_hbonds']}
  Salt bridges: {interface_summary['n_salt_bridges']}
  Hydrophobic contacts: {interface_summary['n_hydrophobic_contacts']}
  Dominant interaction type: {interface_summary['dominant_interaction']}

KEY INTERFACE RESIDUES (by buried surface area):
{res_lines}

HYDROGEN BONDS:
{hbond_lines or '  None detected'}

SALT BRIDGES:
{salt_lines or '  None detected'}

Write a 3-4 sentence biological interpretation of this docking result. Describe what drives the interaction, which residues are most important, and how confident the prediction is. Be specific about residue names and interaction types. Write for a methods section of a paper."""

    return prompt


def generate_interpretation(
    scores: dict,
    interface_data: dict,
) -> dict:
    """
    Generate both rule-based and LLM interpretations.

    Args:
        scores: Rosetta score dict for the model
        interface_data: Output from InterfaceAnalysis.to_dict()

    Returns:
        dict with 'rule_based' observations and 'llm_interpretation'
    """
    # Always generate rule-based (fast, deterministic)
    rule_based = interpret_scores_rule_based(scores)

    summary = interface_data.get("summary", {})

    # Try LLM interpretation
    llm_text = None
    try:
        if _MODEL_PATH.exists():
            prompt = build_analysis_prompt(
                scores=scores,
                interface_summary=summary,
                interface_residues_a=interface_data.get("residues_a", []),
                interface_residues_b=interface_data.get("residues_b", []),
                hbonds=interface_data.get("hbonds", []),
                salt_bridges=interface_data.get("salt_bridges", []),
            )

            llm = _get_llm()
            resp = llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": "You are a structural biologist. Write concise, precise scientific text."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.3,
            )
            llm_text = resp["choices"][0]["message"]["content"].strip()
    except Exception as e:
        llm_text = f"LLM interpretation unavailable: {e}"

    return {
        "rule_based": rule_based,
        "llm_interpretation": llm_text,
        "interface_summary": summary,
    }
