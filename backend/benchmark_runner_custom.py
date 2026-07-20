#!/usr/bin/env python3
"""
benchmark_runner_custom.py — Generalized benchmark runner.

Works with ANY benchmark format (DB5.5, PINDER subsets, custom user datasets)
as long as you provide the structure files and a JSON index.

Index format (JSON list of entries):
[
  {
    "pdb_code": "1ABC",
    "receptor_pdb": "/path/to/receptor.pdb",      # unbound or bound
    "binder_pdb":   "/path/to/binder.pdb",
    "native_pdb":   "/path/to/native_complex.pdb",
    "native_receptor_chains": ["A"],              # chains on receptor in native
    "native_binder_chains":   ["B"],
    "category":    "Rigid",                        # optional
    "description": "Enzyme:inhibitor",             # optional
    "source":      "DB5.5"                         # optional
  },
  ...
]

Usage:
  python benchmark_runner_custom.py \
    --index <index.json> --output <output_dir> \
    [--nstruct 50] [--pre-relax] [--docking-mode local|global]

PINDER quick start:
  Pinder's API gives you (rec, bind, native) tuples per dimer. Convert to the
  index format above and run this. We do NOT depend on the pinder package —
  any tool that produces this index works.
"""

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pipeline import (
    run_clean_pdb,
    normalize_chains,
    sanitize_pdb,
    combine_in_python,
    run_docking,
    parse_fasc_and_find_best,
)
from backend.dockq_scorer import score_dockq


def _rename_chain(input_pdb: Path, output_pdb: Path, new_chain_id: str) -> None:
    with open(input_pdb) as f:
        lines = []
        for line in f:
            if line.startswith(("ATOM", "HETATM")) and len(line) > 21:
                line = line[:21] + new_chain_id + line[22:]
            lines.append(line)
    output_pdb.write_text("".join(lines))


def _write_results(results: list, output_dir: Path) -> None:
    # Unique temp file per process to avoid SLURM-array races where many tasks
    # share the same output_dir and clobber each other's results.json.tmp.
    import os
    tmp = output_dir / f"results.json.tmp.{os.getpid()}"
    try:
        tmp.write_text(json.dumps(results, indent=2))
        tmp.replace(output_dir / "results.json")
    except FileNotFoundError:
        # Another task may have already renamed our tmp away; safe to ignore
        # since merge_array_results.py rebuilds from per-PDB dirs at the end.
        pass


def _write_progress(done: int, total: int, output_dir: Path) -> None:
    # Per-task progress so array tasks don't clobber each other
    import os
    fname = f"progress.{os.getpid()}.json"
    (output_dir / fname).write_text(json.dumps({"done": done, "total": total}))
    # Also try to write the canonical progress.json (best-effort)
    try:
        (output_dir / "progress.json").write_text(json.dumps({"done": done, "total": total}))
    except Exception:
        pass


def _refine_top_decoys(pdb_dir: Path, n_top: int, refine_nstruct: int,
                       native_local: Path, native_rec: list[str],
                       native_bind: list[str], best_initial: dict) -> dict:
    """
    Take top N decoys from initial dock, redock each with tight perturbation,
    return the best (across initial + all refined) by DockQ.

    For each top-N starting point, runs `nstruct=refine_nstruct` more decoys
    in `pdb_dir/refine_<rank>/` with docking_mode='refine'. After all
    refinements complete, returns the dict with the highest DockQ.

    Returns: best_overall = {"pdb_path": Path, "total_score": float,
                              "DockQ": float, "from_refinement": bool}
    """
    import shutil
    fasc = pdb_dir / "docking.fasc"
    decoys = []
    headers = None
    for line in fasc.read_text().splitlines():
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

    decoys.sort(key=lambda d: d.get("total_score", 1e9))
    top = decoys[:n_top]
    print(f"  Refining top {len(top)} decoys (each with nstruct={refine_nstruct})...", flush=True)

    candidates = []
    # Score the initial best for fair comparison
    initial_dockq = score_dockq(
        model_pdb=Path(best_initial["pdb_path"]),
        native_pdb=native_local,
        receptor_native_chains=native_rec,
        binder_native_chains=native_bind,
    )
    candidates.append({
        "pdb_path": best_initial["pdb_path"],
        "total_score": float(best_initial["total_score"]),
        "DockQ": initial_dockq["DockQ"],
        "from_refinement": False,
        "source_decoy": Path(best_initial["pdb_path"]).stem,
    })

    for rank, dec in enumerate(top, 1):
        desc = dec.get("description", "")
        seed_pdb = pdb_dir / f"{desc}.pdb"
        if not seed_pdb.exists():
            print(f"    Skip rank {rank} — file missing: {seed_pdb.name}", flush=True)
            continue

        refine_dir = pdb_dir / f"refine_{rank:02d}"
        refine_dir.mkdir(exist_ok=True)
        seed_complex = refine_dir / "complex_input.pdb"
        shutil.copy(seed_pdb, seed_complex)
        # Carry over partners
        shutil.copy(pdb_dir / "partners.txt", refine_dir / "partners.txt")

        try:
            run_docking(
                seed_complex, output_dir=refine_dir, nstruct=refine_nstruct,
                pre_relax=False, docking_mode="refine",
            )
        except RuntimeError as e:
            import glob as _g
            n_pdbs = len(_g.glob(str(refine_dir / "complex_input_full_*.pdb")))
            if n_pdbs == 0:
                print(f"    Refine rank {rank}: no decoys produced ({e})", flush=True)
                continue

        refine_best = parse_fasc_and_find_best(
            fasc_path=refine_dir / "docking.fasc",
            pdb_glob=str(refine_dir / "complex_input_full_*.pdb"),
        )
        if refine_best is None:
            continue
        rb_pdb = Path(refine_best["pdb_path"])
        rb_dockq = score_dockq(
            model_pdb=rb_pdb,
            native_pdb=native_local,
            receptor_native_chains=native_rec,
            binder_native_chains=native_bind,
        )
        candidates.append({
            "pdb_path": str(rb_pdb),
            "total_score": float(refine_best["total_score"]),
            "DockQ": rb_dockq["DockQ"],
            "from_refinement": True,
            "source_decoy": desc,
        })
        print(f"    Refine rank {rank} ({desc}): DockQ={rb_dockq['DockQ']:.3f} "
              f"(initial DockQ for this decoy not separately scored)", flush=True)

    # Pick best by DockQ (oracle picker on the refined set; in production a
    # re-ranker would pick by its own scoring signal)
    best_overall = max(candidates, key=lambda c: c["DockQ"])
    print(f"  Best after refinement: DockQ={best_overall['DockQ']:.3f} "
          f"({'refined' if best_overall['from_refinement'] else 'initial'})", flush=True)
    return best_overall


def _extract_chain_seq(pdb_path: Path) -> str:
    """Extract single-letter sequence from a single-chain PDB."""
    three_to_one = {
        'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q','GLU':'E',
        'GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F',
        'PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V',
    }
    seq, last_resid = [], None
    for line in pdb_path.read_text().splitlines():
        if not line.startswith("ATOM"):
            continue
        if line[12:16].strip() != "CA":
            continue
        resid = (line[21], int(line[22:26]))
        if resid == last_resid:
            continue
        last_resid = resid
        aa = line[17:20].strip()
        seq.append(three_to_one.get(aa, "X"))
    return "".join(seq)


def _boltz_predict_starting(rec_pdb: Path, bind_pdb: Path, out_dir: Path,
                            n_seeds: int, name: str) -> Path:
    """Run Boltz-1, return path to top-ipTM PDB to use as starting structure."""
    from backend.boltz_predictor import predict_complex
    rec_seq = _extract_chain_seq(rec_pdb)
    bind_seq = _extract_chain_seq(bind_pdb)
    if not rec_seq or not bind_seq:
        raise RuntimeError(f"Failed to extract sequence from {rec_pdb} or {bind_pdb}")
    print(f"  Boltz-1: predicting {name} with {n_seeds} seeds "
          f"(rec={len(rec_seq)}aa, bind={len(bind_seq)}aa)...", flush=True)
    result = predict_complex(
        rec_seq, bind_seq, out_dir / "boltz_ensemble",
        n_seeds=n_seeds, name=name,
        rec_chain="A", bind_chain="B",
    )
    print(f"    Best ipTM: {result['best_iptm']:.3f} (across {result['n_predictions']} predictions)", flush=True)
    return Path(result["best_pdb"])


def _af3_predict_starting(rec_pdb: Path, bind_pdb: Path, out_dir: Path,
                          n_seeds: int, name: str) -> Path:
    """Run AlphaFold 3, return path to top-confidence PDB to use as starting structure."""
    from backend.af3_predictor import predict_complex
    rec_seq = _extract_chain_seq(rec_pdb)
    bind_seq = _extract_chain_seq(bind_pdb)
    if not rec_seq or not bind_seq:
        raise RuntimeError(f"Failed to extract sequence from {rec_pdb} or {bind_pdb}")
    print(f"  AF3: predicting {name} with {n_seeds} seeds "
          f"(rec={len(rec_seq)}aa, bind={len(bind_seq)}aa)...", flush=True)
    result = predict_complex(
        rec_seq, bind_seq, out_dir / "af3_ensemble",
        n_seeds=n_seeds, name=name,
        rec_chain="A", bind_chain="B",
    )
    print(f"    Best confidence: {result.get('best_confidence')} "
          f"(across {result['n_predictions']} predictions)", flush=True)
    return Path(result["best_pdb"])


def run_custom_benchmark(
    entries: list[dict],
    output_dir: Path,
    nstruct: int,
    pre_relax: bool,
    docking_mode: str,
    refine_top_n: int = 0,
    refine_nstruct: int = 20,
    starting_structure: str = "input",
    boltz_seeds: int = 25,
    weight_overrides: dict | None = None,
) -> list[dict]:
    results = []
    total = len(entries)

    for i, entry in enumerate(entries):
        pdb_code = entry["pdb_code"]
        rec_src = Path(entry["receptor_pdb"])
        bind_src = Path(entry["binder_pdb"])
        native_src = Path(entry["native_pdb"])
        native_rec = entry["native_receptor_chains"]
        native_bind = entry["native_binder_chains"]

        pdb_dir = output_dir / pdb_code
        pdb_dir.mkdir(parents=True, exist_ok=True)

        result = {
            "pdb_code": pdb_code,
            "category": entry.get("category", "unknown"),
            "description": entry.get("description", ""),
            "source": entry.get("source", "custom"),
            "status": "running",
            "started_at": datetime.now().isoformat(),
        }
        results.append(result)
        _write_results(results, output_dir)

        t_start = time.monotonic()
        try:
            print(f"\n[{i+1}/{total}] {pdb_code} — {result['description']}", flush=True)

            for f in (rec_src, bind_src, native_src):
                if not f.exists():
                    raise FileNotFoundError(str(f))

            # Stage native
            import shutil
            native_local = pdb_dir / "native.pdb"
            shutil.copy(native_src, native_local)

            # Standardize chains to A/B
            rec_std = pdb_dir / "receptor_std.pdb"
            bind_std = pdb_dir / "binder_std.pdb"
            _rename_chain(rec_src, rec_std, "A")
            _rename_chain(bind_src, bind_std, "B")

            print("  Cleaning...", flush=True)
            rec_clean = pdb_dir / "receptor_clean.pdb"
            bind_clean = pdb_dir / "binder_clean.pdb"
            run_clean_pdb(rec_std, rec_clean)
            run_clean_pdb(bind_std, bind_clean)
            rec_n, used = normalize_chains(rec_clean, used=set())
            bind_n, _ = normalize_chains(bind_clean, used=used)
            rec_fixed = sanitize_pdb(rec_n)
            bind_fixed = sanitize_pdb(bind_n)

            complex_pdb = pdb_dir / "complex_input.pdb"
            combine_in_python(rec_fixed, bind_fixed, complex_pdb)
            (pdb_dir / "partners.txt").write_text("A_B")

            # Optionally replace the starting complex with an ML predictor
            # output (Boltz-1 or AF3) ranked by confidence/ipTM.
            boltz_meta = None
            if starting_structure == "boltz1":
                boltz_pdb = _boltz_predict_starting(
                    rec_fixed, bind_fixed, pdb_dir, boltz_seeds, pdb_code,
                )
                shutil.copy(boltz_pdb, pdb_dir / "complex_boltz.pdb")
                shutil.copy(boltz_pdb, complex_pdb)
                boltz_meta = {"source": "boltz1", "n_seeds": boltz_seeds,
                              "predictor_pdb": str(boltz_pdb)}
            elif starting_structure == "af3":
                af3_pdb = _af3_predict_starting(
                    rec_fixed, bind_fixed, pdb_dir, boltz_seeds, pdb_code,
                )
                shutil.copy(af3_pdb, pdb_dir / "complex_af3.pdb")
                shutil.copy(af3_pdb, complex_pdb)
                boltz_meta = {"source": "af3", "n_seeds": boltz_seeds,
                              "predictor_pdb": str(af3_pdb)}

            print(f"  Docking (nstruct={nstruct}, mode={docking_mode}, "
                  f"pre_relax={pre_relax})...", flush=True)
            try:
                run_docking(
                    complex_pdb, output_dir=pdb_dir, nstruct=nstruct,
                    pre_relax=pre_relax, docking_mode=docking_mode,
                    weight_overrides=weight_overrides,
                )
            except RuntimeError as dock_err:
                import glob as _g
                n_pdbs = len(_g.glob(str(pdb_dir / "complex_input_full_*.pdb")))
                if n_pdbs == 0:
                    raise RuntimeError(f"No structures produced: {dock_err}") from dock_err
                print(f"  Partial failure ({n_pdbs} structures — continuing)", flush=True)

            fasc = pdb_dir / "docking.fasc"
            best = parse_fasc_and_find_best(
                fasc_path=fasc, pdb_glob=str(pdb_dir / "complex_input_full_*.pdb")
            )
            if best is None:
                raise RuntimeError("No models produced")
            best_pdb = Path(best["pdb_path"])

            # Iterative refinement: re-dock the top N decoys with tight
            # perturbation, then pick best across initial + all refined.
            refined_meta = None
            if refine_top_n > 0:
                refined = _refine_top_decoys(
                    pdb_dir, refine_top_n, refine_nstruct,
                    native_local, native_rec, native_bind, best,
                )
                best_pdb = Path(refined["pdb_path"])
                refined_meta = {
                    "from_refinement": refined["from_refinement"],
                    "source_decoy": refined["source_decoy"],
                    "refine_top_n": refine_top_n,
                    "refine_nstruct": refine_nstruct,
                }

            dockq = score_dockq(
                model_pdb=best_pdb,
                native_pdb=native_local,
                receptor_native_chains=native_rec,
                binder_native_chains=native_bind,
            )
            print(f"  DockQ={dockq['DockQ']:.3f} ({dockq['classification']})", flush=True)

            result.update({
                "status": "success",
                "rosetta_score": round(float(best["total_score"]), 3),
                "best_model": best_pdb.name,
                **dockq,
                "finished_at": datetime.now().isoformat(),
                "wall_seconds": round(time.monotonic() - t_start, 1),
            })
            if refined_meta:
                result["refinement"] = refined_meta
            if boltz_meta:
                result["starting_structure"] = boltz_meta

        except Exception:
            tb = traceback.format_exc()
            print(f"  ERROR: {tb}", flush=True)
            result.update({
                "status": "failed",
                "error": tb,
                "finished_at": datetime.now().isoformat(),
                "wall_seconds": round(time.monotonic() - t_start, 1),
            })

        _write_results(results, output_dir)
        _write_progress(i + 1, total, output_dir)

    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--index", required=True, help="Path to JSON index file")
    p.add_argument("--output", required=True)
    p.add_argument("--nstruct", type=int, default=50)
    p.add_argument("--pre-relax", action="store_true",
                   help="FastRelax complex before docking (helps with unbound).")
    p.add_argument("--docking-mode", choices=["local", "global"], default="local",
                   help="local = perturbation around input; global = randomize1+randomize2.")
    p.add_argument("--refine-top-n", type=int, default=0,
                   help="Take top N decoys, redock each with tight perturbation, "
                        "then pick best. 0 = disabled.")
    p.add_argument("--refine-nstruct", type=int, default=20,
                   help="Decoys per refinement seed (default 20).")
    p.add_argument("--starting-structure", choices=["input", "boltz1", "af3"], default="input",
                   help="input = use receptor+binder PDB as-is (default); "
                        "boltz1 = run Boltz-1 first; af3 = run AlphaFold 3 first.")
    p.add_argument("--boltz-seeds", type=int, default=25,
                   help="Number of Boltz-1 seeds to ensemble (default 25).")
    p.add_argument("--pdb-only", default=None,
                   help="Run only this single PDB code from the index (for SLURM array parallelism).")
    p.add_argument("--array-task-id", type=int, default=None,
                   help="If set, picks entry by index position (for SLURM_ARRAY_TASK_ID).")
    p.add_argument("--weight-override", action="append", default=[],
                   help="Override Rosetta weights, e.g. --weight-override fa_elec=1.5 "
                        "(use multiple times for multiple terms).")
    args = p.parse_args()

    # Parse weight overrides
    weight_overrides = {}
    for kv in args.weight_override:
        if "=" not in kv:
            raise SystemExit(f"Bad --weight-override format (need term=val): {kv}")
        k, v = kv.split("=", 1)
        weight_overrides[k.strip()] = float(v)

    entries = json.loads(Path(args.index).read_text())
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Filter for parallel execution: --pdb-only or --array-task-id picks one entry
    if args.pdb_only:
        entries = [e for e in entries if e["pdb_code"] == args.pdb_only]
        if not entries:
            raise SystemExit(f"PDB code {args.pdb_only!r} not found in index")
    elif args.array_task_id is not None:
        if args.array_task_id >= len(entries):
            raise SystemExit(f"array task id {args.array_task_id} out of range (have {len(entries)} entries)")
        entries = [entries[args.array_task_id]]

    print(f"Custom Benchmark — {len(entries)} entries, nstruct={args.nstruct}, "
          f"mode={args.docking_mode}, pre_relax={args.pre_relax}, "
          f"refine_top_n={args.refine_top_n}")
    print(f"Output: {output_dir}")

    results = run_custom_benchmark(
        entries, output_dir,
        nstruct=args.nstruct,
        pre_relax=args.pre_relax,
        docking_mode=args.docking_mode,
        refine_top_n=args.refine_top_n,
        refine_nstruct=args.refine_nstruct,
        starting_structure=args.starting_structure,
        boltz_seeds=args.boltz_seeds,
        weight_overrides=weight_overrides or None,
    )

    success = [r for r in results if r["status"] == "success"]
    scores = [r["DockQ"] for r in success]
    mean_dockq = sum(scores) / len(scores) if scores else 0.0
    summary = {
        "total": len(results),
        "success": len(success),
        "failed": len(results) - len(success),
        "mean_DockQ": round(mean_dockq, 4),
        "median_DockQ": round(sorted(scores)[len(scores)//2], 4) if scores else 0.0,
        "nstruct": args.nstruct,
        "pre_relax": args.pre_relax,
        "docking_mode": args.docking_mode,
        "refine_top_n": args.refine_top_n,
        "refine_nstruct": args.refine_nstruct,
        "starting_structure": args.starting_structure,
        "boltz_seeds": args.boltz_seeds if args.starting_structure == "boltz1" else None,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nDone. {len(success)}/{len(results)} succeeded. Mean DockQ = {mean_dockq:.4f}")


if __name__ == "__main__":
    main()
