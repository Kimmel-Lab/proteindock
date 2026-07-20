#!/usr/bin/env python3
"""
ncaa_reranker.py — Train an ncAA-aware GP/regressor to predict DockQ
improvement from interface mutations, and use it as a re-ranker over
Rosetta decoys.

This is the HEADLINE NOVELTY for paper 2: nobody else combines ncAA
design with DockQ benchmarking + re-ranking. AlphaRED uses Rosetta total
score for ranking; we replace that signal with a learned function over
(interface chemistry, position structural features, mutation set).

Pipeline:
  1. TRAIN — given DockQ-labeled docking decoys + interface analysis,
     train a regressor f(decoy_features) → predicted_DockQ.
     Features per decoy:
       - Rosetta interface energy (I_sc, fa_atr_iface, fa_elec_iface, hbond_sc)
       - Interface SASA + buried surface
       - Number of interface residues, contacts, hbonds, salt bridges
       - ncAA descriptors of any non-canonical residues at the interface (13-dim)
       - ProteinMPNN sequence recovery (if redesigned and re-docked)
     Use scikit-optimize GP or scikit-learn GBR — same dependency surface
     as the existing ncAA optimizer.

  2. RERANK — given a set of docking decoys + interface analyses, predict
     DockQ for each, output sorted list. The predicted "top-1" replaces
     Rosetta's score-based pick.

  3. EVALUATE — compare top-1 by predicted DockQ vs top-1 by Rosetta score
     on a held-out test set. Improvement here is the paper claim.

Training data sources we can use today:
  - Bound benchmark (10 PDBs) — decoys + native + DockQ labels
  - Unbound benchmark (10 PDBs) — same
  - Each PDB has 10-50 decoys; full training set ~200-500 decoys
  - Augment by including ncAA mutations from the case-study runs

Status: SCAFFOLD. Run `train_reranker.py --help` once ground-truth data
is collected from the benchmark runs.

Usage (later):
  # Train on existing benchmark outputs
  python ncaa_reranker.py train \\
      --runs ~/protein_web_jobs/bench_runs/iter0_baseline \\
             ~/protein_web_jobs/bench_runs/iter1_prerelax \\
      --model ~/protein_web_jobs/ncaa_reranker_v1.joblib

  # Apply to a new docking run
  python ncaa_reranker.py rerank \\
      --bench-dir ~/protein_web_jobs/bench_runs/iter6_boltz_refined \\
      --model ~/protein_web_jobs/ncaa_reranker_v1.joblib \\
      --out  ~/protein_web_jobs/bench_runs/iter7_reranked
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def parse_fasc(fasc_path: Path) -> list[dict]:
    """Parse Rosetta fasc into list of per-decoy dicts."""
    decoys = []
    headers = None
    for line in fasc_path.read_text().splitlines():
        if not line.startswith("SCORE:"):
            continue
        parts = line.split()
        if headers is None:
            headers = parts[1:]
            continue
        row = {}
        for k, v in zip(headers, parts[1:]):
            try:
                row[k] = float(v)
            except ValueError:
                row[k] = v
        decoys.append(row)
    return decoys


def featurize_decoy(decoy_pdb: Path, fasc_row: dict, native_pdb: Path | None) -> dict:
    """
    Extract feature vector for a single decoy.

    Features (and where they come from):
      - rosetta_total_score, I_sc, fa_atr, fa_elec, hbond_sc (from fasc)
      - n_interface_residues, mean_delta_sasa, n_hbonds, n_salt_bridges
        (from running analyze_interface on the decoy)
      - rms / Irms / Fnat (from fasc — interface RMSDs)
      - presence/identity of ncAAs at interface (from .params overlay)
    """
    from backend.interface_analysis import analyze_multi_interface
    features = {
        "rosetta_total_score": fasc_row.get("total_score"),
        "I_sc": fasc_row.get("I_sc"),
        "fa_atr": fasc_row.get("fa_atr"),
        "fa_elec": fasc_row.get("fa_elec"),
        "fa_rep": fasc_row.get("fa_rep"),
        "hbond_sc": fasc_row.get("hbond_sc"),
        "fasc_rms": fasc_row.get("rms"),
        "fasc_Fnat": fasc_row.get("Fnat"),
    }
    try:
        analysis = analyze_multi_interface(
            decoy_pdb, receptor_chains=["A"], binder_chains=["B"],
        )
        features.update({
            "n_iface_residues": len(analysis.residues_a) + len(analysis.residues_b),
            "n_hbonds": len(getattr(analysis, "hbonds", []) or []),
            "n_salt_bridges": len(getattr(analysis, "salt_bridges", []) or []),
            "total_delta_sasa": sum(r.delta_sasa for r in analysis.residues_a)
                              + sum(r.delta_sasa for r in analysis.residues_b),
        })
    except Exception as e:
        features.update({"interface_error": str(e)})
    return features


def collect_training_data(run_dirs: list[Path]) -> list[dict]:
    """
    Walk benchmark run dirs, build (features, dockq) training rows.

    Each row:
      {
        "pdb_code": str,
        "decoy_name": str,
        "features": dict[str, float],
        "dockq": float,
      }
    """
    from backend.dockq_scorer import score_dockq
    rows = []
    for run_dir in run_dirs:
        results = json.loads((run_dir / "results.json").read_text())
        bench_dir = run_dir  # convention: each entry has its own subdir
        for r in results:
            if r["status"] != "success":
                continue
            pdb = r["pdb_code"]
            pdb_dir = bench_dir / pdb
            fasc = pdb_dir / "docking.fasc"
            native = pdb_dir / "native.pdb"
            if not fasc.exists() or not native.exists():
                continue
            decoys = parse_fasc(fasc)
            rec_chains = r.get("native_receptor_chains", ["A"])
            bind_chains = r.get("native_binder_chains", ["B"])
            for d in decoys:
                desc = d.get("description", "")
                decoy_pdb = pdb_dir / f"{desc}.pdb"
                if not decoy_pdb.exists():
                    continue
                try:
                    dockq_result = score_dockq(
                        model_pdb=decoy_pdb, native_pdb=native,
                        receptor_native_chains=rec_chains,
                        binder_native_chains=bind_chains,
                    )
                    feats = featurize_decoy(decoy_pdb, d, native)
                    rows.append({
                        "pdb_code": pdb,
                        "decoy_name": desc,
                        "features": feats,
                        "dockq": dockq_result["DockQ"],
                    })
                except Exception as e:
                    print(f"  Skip {pdb}/{desc}: {e}", file=sys.stderr)
    return rows


def train_model(training_rows: list[dict], model_out: Path) -> None:
    """Train a GBR on (features → dockq) and save to disk."""
    import numpy as np
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.model_selection import cross_val_score
    import joblib

    feature_keys = sorted({k for r in training_rows for k in r["features"]
                           if isinstance(r["features"].get(k), (int, float))})
    X = np.array([[r["features"].get(k, 0.0) or 0.0 for k in feature_keys]
                  for r in training_rows])
    y = np.array([r["dockq"] for r in training_rows])

    model = GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.05)
    cv = cross_val_score(model, X, y, cv=5, scoring="r2")
    print(f"5-fold CV R²: {cv.mean():.3f} ± {cv.std():.3f}")
    model.fit(X, y)

    joblib.dump({"model": model, "feature_keys": feature_keys}, model_out)
    print(f"Saved {model_out}")
    print(f"Feature importances:")
    for k, imp in sorted(zip(feature_keys, model.feature_importances_), key=lambda kv: -kv[1])[:10]:
        print(f"  {k:30s}  {imp:.3f}")


def rerank(bench_dir: Path, model_path: Path, out_dir: Path) -> None:
    """Apply the trained model to a bench run, pick new top-1 per PDB."""
    import joblib
    import numpy as np
    obj = joblib.load(model_path)
    model = obj["model"]
    feature_keys = obj["feature_keys"]

    out_dir.mkdir(parents=True, exist_ok=True)
    results = json.loads((bench_dir / "results.json").read_text())
    new_results = []
    for r in results:
        if r["status"] != "success":
            new_results.append(r)
            continue
        pdb = r["pdb_code"]
        pdb_dir = bench_dir / pdb
        fasc = pdb_dir / "docking.fasc"
        if not fasc.exists():
            new_results.append(r); continue
        decoys = parse_fasc(fasc)
        scored = []
        for d in decoys:
            desc = d.get("description", "")
            decoy_pdb = pdb_dir / f"{desc}.pdb"
            if not decoy_pdb.exists():
                continue
            feats = featurize_decoy(decoy_pdb, d, pdb_dir / "native.pdb")
            x = np.array([[feats.get(k, 0.0) or 0.0 for k in feature_keys]])
            pred = float(model.predict(x)[0])
            scored.append({"name": desc, "predicted_dockq": pred, "rosetta_score": d.get("total_score")})
        scored.sort(key=lambda s: -s["predicted_dockq"])
        new_top = scored[0]["name"] if scored else r.get("best_model")

        # Re-score the new top-1 with DockQ to get actual improvement
        from backend.dockq_scorer import score_dockq
        new_top_pdb = pdb_dir / f"{new_top}.pdb"
        dockq = score_dockq(
            model_pdb=new_top_pdb,
            native_pdb=pdb_dir / "native.pdb",
            receptor_native_chains=r.get("native_receptor_chains", ["A"]),
            binder_native_chains=r.get("native_binder_chains", ["B"]),
        )
        new_row = dict(r)
        new_row.update({
            "best_model": f"{new_top}.pdb",
            **dockq,
            "rerank_source": "ncaa_reranker",
            "rerank_top10": [s["name"] for s in scored[:10]],
        })
        new_results.append(new_row)
    (out_dir / "results.json").write_text(json.dumps(new_results, indent=2))
    print(f"Reranked → {out_dir / 'results.json'}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    train = sub.add_parser("train")
    train.add_argument("--runs", nargs="+", required=True, type=Path)
    train.add_argument("--model", required=True, type=Path)

    rerank_p = sub.add_parser("rerank")
    rerank_p.add_argument("--bench-dir", required=True, type=Path)
    rerank_p.add_argument("--model", required=True, type=Path)
    rerank_p.add_argument("--out", required=True, type=Path)

    args = p.parse_args()

    if args.cmd == "train":
        print("Collecting training data from", args.runs)
        rows = collect_training_data(args.runs)
        print(f"  → {len(rows)} (features, DockQ) training rows")
        if len(rows) < 30:
            print("WARNING: very small training set. R² will be noisy.")
        train_model(rows, args.model)

    elif args.cmd == "rerank":
        rerank(args.bench_dir, args.model, args.out)


if __name__ == "__main__":
    main()
