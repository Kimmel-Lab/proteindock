#!/usr/bin/env python3
"""
share_export.py

Generate self-contained HTML files for sharing docking results.
Embeds PDB data, 3Dmol.js viewer, scores, interface analysis, and
experiment plan in a single downloadable HTML file.

Dependencies:
  - 3Dmol.js loaded from CDN (BSD-3-Clause, https://github.com/3dmol/3Dmol.js)
"""

from pathlib import Path
from typing import Optional
import html
import json

from backend.experiment_designer import AA_MAP


def generate_share_html(
    pdb_path: Path,
    scores: dict,
    interface_data: dict,
    ai_result: Optional[dict] = None,
    experiment_plan: Optional[dict] = None,
    project_name: str = "",
) -> str:
    """
    Generate a self-contained HTML file with embedded viewer and analysis.

    Args:
        pdb_path: Path to the docked PDB file
        scores: Rosetta score dict for the model
        interface_data: Output from InterfaceAnalysis.to_dict()
        ai_result: Output from generate_interpretation() (optional)
        experiment_plan: Output from ExperimentPlan.to_dict() (optional)
        project_name: Name of the project

    Returns:
        HTML string
    """
    pdb_text = pdb_path.read_text()
    pdb_escaped = html.escape(pdb_text)
    model_name = pdb_path.stem

    summary = interface_data.get("summary", {})
    total_score = scores.get("total_score", scores.get("score", "N/A"))
    i_sc = scores.get("I_sc", "N/A")
    fnat = scores.get("Fnat", "N/A")

    # Format scores
    def fmt(v):
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v) if v is not None else "N/A"

    # Build interface residue rows
    res_rows = ""
    all_res = sorted(
        interface_data.get("residues_a", []) + interface_data.get("residues_b", []),
        key=lambda r: r.get("delta_sasa", 0),
        reverse=True,
    )
    for r in all_res[:12]:
        one = AA_MAP.get(r['resname'], '?')
        res_rows += (
            f"<tr><td>{r['chain']}</td><td>{r['resname']}{r['resid']} ({one}{r['resid']})</td>"
            f"<td>{r['delta_sasa']}</td><td>{r['n_contacts']}</td>"
            f"<td>{r['classification']}</td></tr>\n"
        )

    # Build contact rows
    contact_rows = ""
    for c in interface_data.get("hbonds", [])[:6]:
        one_a = AA_MAP.get(c['resname_a'], '?')
        one_b = AA_MAP.get(c['resname_b'], '?')
        contact_rows += (
            f"<tr><td>H-bond</td>"
            f"<td>{c['resname_a']}{c['resid_a']} ({one_a}{c['resid_a']}) [{c['chain_a']}]</td>"
            f"<td>{c['resname_b']}{c['resid_b']} ({one_b}{c['resid_b']}) [{c['chain_b']}]</td>"
            f"<td>{c['distance']}A</td></tr>\n"
        )
    for c in interface_data.get("salt_bridges", [])[:4]:
        one_a = AA_MAP.get(c['resname_a'], '?')
        one_b = AA_MAP.get(c['resname_b'], '?')
        contact_rows += (
            f"<tr><td>Salt bridge</td>"
            f"<td>{c['resname_a']}{c['resid_a']} ({one_a}{c['resid_a']}) [{c['chain_a']}]</td>"
            f"<td>{c['resname_b']}{c['resid_b']} ({one_b}{c['resid_b']}) [{c['chain_b']}]</td>"
            f"<td>{c['distance']}A</td></tr>\n"
        )

    # AI interpretation section
    ai_section = ""
    if ai_result:
        rules = ai_result.get("rule_based", [])
        llm_text = ai_result.get("llm_interpretation", "")
        rules_html = "".join(f"<li>{html.escape(r)}</li>" for r in rules)
        ai_section = f"""
        <div class="section">
            <h2>AI Analysis</h2>
            <div class="card">
                <h3>Score Interpretation</h3>
                <ul>{rules_html}</ul>
            </div>
            {f'<div class="card"><h3>LLM Interpretation</h3><p>{html.escape(llm_text)}</p></div>' if llm_text else ''}
        </div>
        """

    # Experiment plan section
    exp_section = ""
    if experiment_plan:
        hotspot_rows = ""
        for h in experiment_plan.get("hotspots", [])[:6]:
            one = AA_MAP.get(h['resname'], '?')
            hotspot_rows += (
                f"<tr><td><b>{h['mutation']}</b></td>"
                f"<td>{h['chain']}:{h['resname']}{h['resid']} ({one}{h['resid']})</td>"
                f"<td>{h['delta_sasa']}</td>"
                f"<td>{h['hotspot_score']}</td>"
                f"<td>{h['reason']}</td></tr>\n"
            )
        exp_cards = ""
        for e in experiment_plan.get("experiments", []):
            exp_cards += (
                f'<div class="card">'
                f'<h3>{html.escape(e["name"])} <span class="badge">{e["priority"]}</span></h3>'
                f'<p>{html.escape(e["description"])}</p></div>\n'
            )
        exp_section = f"""
        <div class="section">
            <h2>Validation Plan</h2>
            <p>{html.escape(experiment_plan.get('summary', ''))}</p>
            <table>
                <thead><tr><th>Mutation</th><th>Residue</th><th>delta-SASA</th><th>Score</th><th>Reason</th></tr></thead>
                <tbody>{hotspot_rows}</tbody>
            </table>
            {exp_cards}
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Docking Result: {html.escape(model_name)} — ProteinDock</title>
    <!-- 3Dmol.js (BSD-3-Clause) — https://github.com/3dmol/3Dmol.js -->
    <script src="https://3dmol.org/build/3Dmol-min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #0f0f1a; color: #e2e8f0; line-height: 1.6; padding: 2rem; }}
        .header {{ text-align: center; margin-bottom: 2rem; }}
        .header h1 {{ font-size: 1.5rem; color: #60a5fa; }}
        .header p {{ color: #94a3b8; font-size: 0.875rem; }}
        .viewer-container {{ width: 100%; max-width: 900px; margin: 0 auto 2rem;
                            border-radius: 12px; overflow: hidden; border: 1px solid #334155; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                  gap: 1rem; max-width: 900px; margin: 0 auto 2rem; }}
        .stat {{ background: #1e293b; border-radius: 8px; padding: 1rem; text-align: center;
                border: 1px solid #334155; }}
        .stat .value {{ font-size: 1.5rem; font-weight: 700; font-family: 'Courier New', monospace; }}
        .stat .label {{ font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
        .section {{ max-width: 900px; margin: 0 auto 2rem; }}
        .section h2 {{ font-size: 1.25rem; margin-bottom: 1rem; color: #60a5fa; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; }}
        th, td {{ padding: 0.5rem 0.75rem; text-align: left; font-size: 0.8rem; border-bottom: 1px solid #334155; }}
        th {{ background: #334155; color: #e2e8f0; font-weight: 600; text-transform: uppercase; font-size: 0.7rem; }}
        .card {{ background: #1e293b; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; border: 1px solid #334155; }}
        .card h3 {{ font-size: 0.95rem; margin-bottom: 0.5rem; color: #60a5fa; }}
        .card p, .card li {{ font-size: 0.85rem; color: #cbd5e1; }}
        .card ul {{ padding-left: 1.5rem; }}
        .badge {{ font-size: 0.65rem; padding: 2px 8px; border-radius: 9999px;
                  background: #334155; color: #94a3b8; vertical-align: middle; }}
        .footer {{ text-align: center; color: #475569; font-size: 0.75rem; margin-top: 3rem; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Docking Result: {html.escape(model_name)}</h1>
        <p>Project: {html.escape(project_name)} | Generated by ProteinDock</p>
    </div>

    <div class="viewer-container">
        <div id="viewer" style="width:100%;height:500px;position:relative;"></div>
    </div>

    <div class="stats">
        <div class="stat"><div class="value" style="color:#34d399">{fmt(total_score)}</div><div class="label">Total Score (REU)</div></div>
        <div class="stat"><div class="value">{fmt(i_sc)}</div><div class="label">Interface Score</div></div>
        <div class="stat"><div class="value">{fmt(fnat)}</div><div class="label">Fnat</div></div>
        <div class="stat"><div class="value">{summary.get('total_buried_sasa', 'N/A')}</div><div class="label">Buried SA (Å²)</div></div>
        <div class="stat"><div class="value">{summary.get('n_hbonds', 0)}</div><div class="label">H-Bonds</div></div>
        <div class="stat"><div class="value">{summary.get('n_salt_bridges', 0)}</div><div class="label">Salt Bridges</div></div>
    </div>

    <div class="section">
        <h2>Interface Residues</h2>
        <table>
            <thead><tr><th>Chain</th><th>Residue</th><th>δ-SASA (Å²)</th><th>Contacts</th><th>Type</th></tr></thead>
            <tbody>{res_rows}</tbody>
        </table>
    </div>

    {f'''<div class="section">
        <h2>Interface Contacts</h2>
        <table>
            <thead><tr><th>Type</th><th>Residue A</th><th>Residue B</th><th>Distance</th></tr></thead>
            <tbody>{contact_rows}</tbody>
        </table>
    </div>''' if contact_rows else ''}

    {ai_section}
    {exp_section}

    <div class="footer">
        <p>Generated by ProteinDock | 3D viewer: 3Dmol.js (BSD-3-Clause)</p>
        <p>Rosetta scoring: Alford et al., JCTC 2017 | BioPython: Cock et al., Bioinformatics 2009</p>
    </div>

    <script>
    var pdbData = {json.dumps(pdb_text)};
    var viewer = $3Dmol.createViewer("viewer", {{backgroundColor: "0x0f0f1a", antialias: true}});
    viewer.addModel(pdbData, "pdb");
    viewer.setStyle({{chain: "A"}}, {{cartoon: {{color: "0x2dd4bf"}}}});
    viewer.setStyle({{chain: "B"}}, {{cartoon: {{color: "0xfb923c"}}}});
    viewer.setStyle(
        {{chain: "A", within: {{distance: 5, sel: {{chain: "B"}}}}}},
        {{cartoon: {{color: "0x2dd4bf"}}, stick: {{colorscheme: "default", radius: 0.15}}}}
    );
    viewer.setStyle(
        {{chain: "B", within: {{distance: 5, sel: {{chain: "A"}}}}}},
        {{cartoon: {{color: "0xfb923c"}}, stick: {{colorscheme: "default", radius: 0.15}}}}
    );
    viewer.zoomTo();
    viewer.render();
    </script>
</body>
</html>"""
