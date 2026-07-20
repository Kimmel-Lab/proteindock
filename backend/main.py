#!/usr/bin/env python3
"""
main.py — FastAPI backend for ProteinDock.

Endpoints are grouped by domain:
  1. Projects        — listing / metadata
  2. Input           — fetch, upload, predict
  3. Preprocessing   — clean, normalize, sanitize, merge
  4. Docking         — blocking, streaming (SSE), SLURM, cancel
  5. Results         — scores, PDB content, download
  6. Analysis        — interface, AI interpret, experiment plan
  7. Export          — shareable HTML report
"""

# ── stdlib ────────────────────────────────────────────────────
import asyncio
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

# ── third-party ───────────────────────────────────────────────
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── config ────────────────────────────────────────────────────
from backend.config import (
    ROSETTA_SCRIPTS,
    DOCKING_XML_SRC,
    DOCKING_OPTIONS_SRC,
    PYMOL_COMMAND,
    DEFAULT_WORKDIR,
    SURFACE_GAP,
    NCAA_PYROSETTA_DB,
)

# ── project modules ───────────────────────────────────────────
from backend.pipeline import (
    check_alanine_scan_job,
    check_sequential_status,
    check_slurm_job,
    combine_in_python,
    combine_multi,
    fetch_pdb,
    generate_docking_xml,
    normalize_chains,
    parse_alanine_scan_results,
    parse_fasc_all_models,
    parse_fasc_and_find_best,
    parse_multi_pose_results,
    run_alanine_scan_slurm,
    run_clean_pdb,
    run_colabfold,
    run_docking,
    run_docking_slurm,
    run_multi_pose_ala_scan_slurm,
    run_sequential_docking_slurm,
    sanitize_pdb,
    visualize_best_model,
    write_fasta,
    handle_ncaa_params_upload,
    run_ncaa_optimize_slurm,
    check_ncaa_optimize_job,
    parse_ncaa_optimize_results,
)
from backend.interface_analysis import analyze_interface, analyze_multi_interface, parse_partners
from backend.ai_analyst import generate_interpretation
from backend.experiment_designer import design_experiments
from backend.share_export import generate_share_html
from backend.dockq_scorer import score_dockq, PRESET_BENCHMARK
from backend.benchmark import run_benchmark_slurm, check_benchmark_job
from backend.mpnn_designer import run_mpnn_design


# ══════════════════════════════════════════════════════════════
#  APP SETUP
# ══════════════════════════════════════════════════════════════

app = FastAPI(title="ProteinDock", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def strip_ood_prefix(request, call_next):
    """Strip /node/<host>/<port> prefix added by OOD reverse proxy."""
    path = request.scope["path"]
    m = re.match(r"^/r?node/[^/]+/\d+(/.*)$", path)
    if m:
        request.scope["path"] = m.group(1) or "/"
    return await call_next(request)

WORKDIR = DEFAULT_WORKDIR

# Active streaming docking processes (for cancellation)
_active_docking_jobs: dict[str, subprocess.Popen] = {}


# ── helpers ───────────────────────────────────────────────────

def _safe_name(name: str) -> str:
    """Sanitize a user-supplied name to prevent path traversal."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


def _get_project_dir(project: str) -> Path:
    """Return (and create) the project directory."""
    d = WORKDIR / _safe_name(project)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_best_model(project_dir: Path):
    """Parse .fasc and return (pdb_path, scores_dict) for the best model."""
    fasc = project_dir / "docking.fasc"
    if not fasc.exists():
        raise HTTPException(status_code=404, detail="No docking results found.")
    best = parse_fasc_and_find_best(
        fasc_path=fasc,
        pdb_glob=str(project_dir / "complex_input_full_*.pdb"),
    )
    return best


def _validate_pdb(pdb_path: str) -> Path:
    """Ensure a PDB path exists and return it as a Path."""
    p = Path(pdb_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"PDB not found: {pdb_path}")
    return p


def _validate_workdir_access(p: Path):
    """Ensure the path lives under WORKDIR (prevent path traversal)."""
    try:
        p.resolve().relative_to(WORKDIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")


def _get_partners(project_dir: Path) -> tuple[str, list[str], list[str]]:
    """Read partners.txt and return (partners_str, receptor_chains, binder_chains)."""
    partners_file = project_dir / "partners.txt"
    partners_str = partners_file.read_text().strip() if partners_file.exists() else "A_B"
    receptor_chains, binder_chains = parse_partners(partners_str)
    return partners_str, receptor_chains, binder_chains


# ══════════════════════════════════════════════════════════════
#  1. PROJECTS
# ══════════════════════════════════════════════════════════════

@app.get("/projects")
async def api_list_projects():
    """List all projects with basic metadata."""
    if not WORKDIR.exists():
        return {"projects": []}
    projects = []
    for d in sorted(WORKDIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        fasc = d / "docking.fasc"
        projects.append({
            "name": d.name,
            "path": str(d),
            "has_results": fasc.exists(),
            "fasc_size": fasc.stat().st_size if fasc.exists() else 0,
            "has_complex": (d / "complex_input.pdb").exists(),
            "created": d.stat().st_mtime,
        })
    return {"projects": projects}


@app.get("/config-info")
async def api_config_info():
    """Return non-sensitive config info for debugging."""
    from backend.config import (
        ROSETTA_SCRIPTS as _rs,
        ROSETTA_DATABASE as _db,
        SLURM_ACCOUNT as _sa,
        DOCKING_XML_SRC as _dx,
    )
    return {
        "rosetta_scripts_exists": Path(_rs).exists(),
        "database_exists": Path(_db).exists(),
        "slurm_account": _sa,
        "docking_xml_exists": _dx.exists(),
        "workdir": str(WORKDIR),
    }


# ══════════════════════════════════════════════════════════════
#  2. INPUT STRUCTURES
# ══════════════════════════════════════════════════════════════

@app.post("/fetch")
async def api_fetch(
    project: str = Form(...), role: str = Form(...), pdbCode: str = Form(...),
):
    project_dir = _get_project_dir(project)
    outdir = project_dir / role
    outdir.mkdir(parents=True, exist_ok=True)
    path = fetch_pdb(pdbCode, outdir)
    return {"path": str(path), "filePath": str(path), "project": project}


@app.post("/upload")
async def api_upload(
    project: str = Form(...), role: str = Form(...), file: UploadFile = File(...),
):
    project_dir = _get_project_dir(project)
    outdir = project_dir / _safe_name(role)
    outdir.mkdir(parents=True, exist_ok=True)
    safe_filename = _safe_name(file.filename or "upload.pdb")
    out = outdir / safe_filename
    with out.open("wb") as f:
        f.write(await file.read())
    return {"path": str(out), "filePath": str(out), "project": project}


@app.post("/predict")
async def api_predict(
    project: str = Form(...), role: str = Form(...), sequence: str = Form(...),
):
    project_dir = _get_project_dir(project)
    outdir = project_dir / f"{role}_colabfold"
    with tempfile.TemporaryDirectory() as tmp:
        fasta = write_fasta(sequence.strip(), Path(tmp), role)
        pdb = run_colabfold(fasta, outdir)
    return {"path": str(pdb), "filePath": str(pdb), "project": project}


# ══════════════════════════════════════════════════════════════
#  3. PREPROCESSING
# ══════════════════════════════════════════════════════════════

@app.post("/clean")
async def api_clean(
    project: str = Form(...), rec: str = Form(...), bin: str = Form(...),
):
    project_dir = _get_project_dir(project)
    rec_out = project_dir / "receptor_clean.pdb"
    bin_out = project_dir / "binder_clean.pdb"
    await asyncio.to_thread(run_clean_pdb, Path(rec), rec_out)
    await asyncio.to_thread(run_clean_pdb, Path(bin), bin_out)
    return {"rec": str(rec_out), "bin": str(bin_out), "project": project}


@app.post("/normalize")
async def api_normalize(
    project: str = Form(...), rec: str = Form(...), bin: str = Form(...),
):
    used = set()
    rec2, used = await asyncio.to_thread(normalize_chains, Path(rec), used)
    bin2, used = await asyncio.to_thread(normalize_chains, Path(bin), used)
    return {"rec": str(rec2), "bin": str(bin2), "project": project}


@app.post("/sanitize")
async def api_sanitize(
    project: str = Form(...), rec: str = Form(...), bin: str = Form(...),
):
    rec2 = await asyncio.to_thread(sanitize_pdb, Path(rec))
    bin2 = await asyncio.to_thread(sanitize_pdb, Path(bin))
    return {"rec": str(rec2), "bin": str(bin2), "project": project}


@app.post("/merge")
async def api_merge(
    project: str = Form(...), rec: str = Form(...), bin: str = Form(...),
):
    project_dir = _get_project_dir(project)
    out = project_dir / "complex_input.pdb"
    await asyncio.to_thread(combine_in_python, Path(rec), Path(bin), out)
    # Write default partners for 2-component docking
    (project_dir / "partners.txt").write_text("A_B")
    return {"out": str(out), "path": str(out), "output": str(out), "project": project}


# ── Multi-component preprocessing ────────────────────────────

from pydantic import BaseModel
from typing import Optional


class MultiComponentRequest(BaseModel):
    project: str
    components: list[str]


class MergeMultiRequest(BaseModel):
    project: str
    components: list[str]
    partners: Optional[str] = None


@app.post("/clean-multi")
async def api_clean_multi(req: MultiComponentRequest):
    """Clean N components through Rosetta clean_pdb.py."""
    project_dir = _get_project_dir(req.project)
    cleaned = []
    for i, comp_path in enumerate(req.components):
        out = project_dir / f"component_{i}_clean.pdb"
        await asyncio.to_thread(run_clean_pdb, Path(comp_path), out)
        cleaned.append(str(out))
    return {"cleaned": cleaned, "project": req.project}


@app.post("/normalize-multi")
async def api_normalize_multi(req: MultiComponentRequest):
    """Normalize chain IDs across N components (A, B, C, ...)."""
    used: set = set()
    normalized = []
    for comp_path in req.components:
        result, used = await asyncio.to_thread(normalize_chains, Path(comp_path), used)
        normalized.append(str(result))
    return {"normalized": normalized, "project": req.project}


@app.post("/sanitize-multi")
async def api_sanitize_multi(req: MultiComponentRequest):
    """Sanitize residue numbering for N components."""
    sanitized = []
    for comp_path in req.components:
        result = await asyncio.to_thread(sanitize_pdb, Path(comp_path))
        sanitized.append(str(result))
    return {"sanitized": sanitized, "project": req.project}


@app.post("/merge-multi")
async def api_merge_multi(req: MergeMultiRequest):
    """Merge N components into a single complex PDB."""
    project_dir = _get_project_dir(req.project)
    out = project_dir / "complex_input.pdb"
    result = await asyncio.to_thread(
        combine_multi,
        [Path(p) for p in req.components],
        out,
        SURFACE_GAP,
        req.partners,
    )
    # Save the partners string for use by docking and analysis
    (project_dir / "partners.txt").write_text(result["partners"])

    return {
        "output": str(out),
        "path": str(out),
        "partners": result["partners"],
        "chains": result["chains"],
        "project": req.project,
    }


# ══════════════════════════════════════════════════════════════
#  4. DOCKING
# ══════════════════════════════════════════════════════════════

@app.post("/dock")
async def api_dock(project: str = Form(...), nstruct: int = Form(10)):
    """Run Rosetta docking (blocking) and return the best result."""
    project_dir = _get_project_dir(project)
    complex_pdb = project_dir / "complex_input.pdb"
    if not complex_pdb.exists():
        raise HTTPException(status_code=400, detail="Complex PDB not found. Run merge first.")

    docking_result = run_docking(
        complex_pdb=complex_pdb, output_dir=project_dir, nstruct=nstruct,
    )
    best = parse_fasc_and_find_best(
        fasc_path=Path(docking_result["fasc_path"]),
        pdb_glob=str(project_dir / "complex_input_full_*.pdb"),
    )
    return {
        "score": best["score"],
        "bestScore": best["score"],
        "desc": best["desc"],
        "bestModel": best["desc"],
        "index": best["index"],
        "pdb_path": str(best["pdb_path"]),
        "bestPdbPath": str(best["pdb_path"]),
        "log_path": docking_result["log_path"],
        "project": project,
    }


# ── Streaming SSE docking ────────────────────────────────────

@app.post("/dock-stream")
async def api_dock_stream(project: str = Form(...), nstruct: int = Form(10)):
    """Run Rosetta docking with real-time progress streaming via SSE."""
    project_dir = _get_project_dir(project)
    complex_pdb = project_dir / "complex_input.pdb"
    if not complex_pdb.exists():
        raise HTTPException(status_code=400, detail="Complex PDB not found. Run merge first.")

    async def _stream():
        xml_path = project_dir / "docking_full.xml"
        options_path = project_dir / "docking.options.txt"
        log_path = project_dir / "docking_full.log"

        # Read partners string if available
        partners_file = project_dir / "partners.txt"
        partners = partners_file.read_text().strip() if partners_file.exists() else "A_B"

        # Generate partners-aware XML protocol
        generate_docking_xml(partners, xml_path)

        # Rewrite options with project-specific paths
        new_lines = []
        for line in DOCKING_OPTIONS_SRC.read_text().splitlines():
            if line.strip().startswith("-s "):
                new_lines.append(f"-s {complex_pdb}")
            elif line.strip().startswith("-out:file:scorefile"):
                new_lines.append(f"-out:file:scorefile {project_dir / 'docking.fasc'}")
            elif "-partners" in line:
                new_lines.append(f"\t-partners {partners}")
            else:
                new_lines.append(line)
        new_lines.append(f"-nstruct {nstruct}")
        options_path.write_text("\n".join(new_lines))

        cmd = [
            ROSETTA_SCRIPTS,
            f"@{options_path}",
            "-parser:protocol", str(xml_path),
            "-out:suffix", "_full",
            "-overwrite",
        ]

        yield f"data: {json.dumps({'type': 'start', 'total': nstruct, 'message': 'Starting Rosetta docking...'})}\n\n"

        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=str(project_dir),
        )
        _active_docking_jobs[project] = process
        structures_done = 0

        try:
            with open(log_path, "w") as log_file:
                for line in iter(process.stdout.readline, ""):
                    if not line:
                        break
                    log_file.write(line)
                    log_file.flush()

                    # Progress from JobDistributor
                    if "protocols.jd2.JobDistributor" in line:
                        m = re.search(r"starting\s+(\d+)", line, re.IGNORECASE)
                        if m:
                            current = int(m.group(1))
                            yield f"data: {json.dumps({'type': 'progress', 'current': current, 'total': nstruct, 'percent': int(current / nstruct * 100)})}\n\n"

                    if "job" in line.lower() and "completed" in line.lower():
                        structures_done += 1
                        yield f"data: {json.dumps({'type': 'progress', 'current': structures_done, 'total': nstruct, 'percent': int(structures_done / nstruct * 100)})}\n\n"

                    # Live score lines
                    if line.startswith("SCORE:") and "total_score" not in line and "description" not in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            try:
                                score = float(parts[1])
                                desc = parts[-1] if len(parts) > 2 else "unknown"
                                yield f"data: {json.dumps({'type': 'score', 'score': score, 'desc': desc, 'line': line.strip()})}\n\n"
                            except ValueError:
                                pass

                    await asyncio.sleep(0)

            process.wait()
            _active_docking_jobs.pop(project, None)

            # Final results
            fasc_path = project_dir / "docking.fasc"
            if fasc_path.exists():
                try:
                    best = parse_fasc_and_find_best(fasc_path=fasc_path, pdb_glob=str(project_dir / "complex_input_full_*.pdb"))
                    all_models = parse_fasc_all_models(fasc_path=fasc_path, pdb_glob=str(project_dir / "complex_input_full_*.pdb"))
                    for model in all_models:
                        if model.get("pdb_path"):
                            model["pdb_path"] = str(model["pdb_path"])
                    yield f"data: {json.dumps({'type': 'complete', 'bestScore': best['score'], 'bestModel': best['desc'], 'pdbPath': str(best['pdb_path']), 'index': best['index'], 'allModels': all_models})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'error', 'message': f'Failed to parse results: {e}'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Docking failed — no results file generated'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            _active_docking_jobs.pop(project, None)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ── Cancel ────────────────────────────────────────────────────

@app.post("/dock-cancel")
async def api_dock_cancel(project: str = Form(...)):
    """Cancel a running docking job (streaming or SLURM)."""
    if project in _active_docking_jobs:
        _active_docking_jobs.pop(project).terminate()
        return {"status": "cancelled", "project": project}

    project_dir = _get_project_dir(project)
    job_info_path = project_dir / "slurm_job_info.json"
    if job_info_path.exists():
        job_info = json.loads(job_info_path.read_text())
        subprocess.run(["scancel", job_info["job_id"]], capture_output=True)
        return {"status": "cancelled", "project": project, "job_id": job_info["job_id"]}

    return {"status": "not_found", "project": project}


# ── SLURM docking ─────────────────────────────────────────────

@app.post("/dock-slurm")
async def api_dock_slurm(
    project: str = Form(...),
    nstruct: int = Form(10),
    time_limit: str = Form("01:00:00"),
    cpus: int = Form(4),
):
    """Submit Rosetta docking as a SLURM job."""
    project_dir = _get_project_dir(project)
    complex_pdb = project_dir / "complex_input.pdb"
    if not complex_pdb.exists():
        raise HTTPException(status_code=400, detail="Complex PDB not found. Run merge first.")

    job_info = run_docking_slurm(
        complex_pdb=complex_pdb, output_dir=project_dir,
        nstruct=nstruct, time_limit=time_limit, cpus=cpus,
    )
    return {
        "job_id": job_info["job_id"],
        "status": "SUBMITTED",
        "project": project,
        "output_dir": str(project_dir),
    }


# ── Sequential assembly docking ───────────────────────────────

@app.post("/dock-slurm-sequential")
async def api_dock_slurm_sequential(
    project: str = Form(...),
    nstruct: int = Form(10),
    time_limit: str = Form("01:00:00"),
    cpus: int = Form(4),
    components: str = Form(...),  # JSON array of file paths
):
    """Submit sequential assembly docking as a single SLURM job."""
    project_dir = _get_project_dir(project)
    comp_paths = json.loads(components)
    if len(comp_paths) < 3:
        raise HTTPException(status_code=400, detail="Sequential mode requires 3+ components.")
    for p in comp_paths:
        if not Path(p).exists():
            raise HTTPException(status_code=400, detail=f"Component PDB not found: {p}")

    job_info = run_sequential_docking_slurm(
        project_dir=project_dir,
        components=[Path(p) for p in comp_paths],
        nstruct=nstruct, time_limit=time_limit, cpus=cpus,
    )
    return {
        "job_id": job_info["job_id"],
        "status": "SUBMITTED",
        "project": project,
        "mode": "sequential",
        "num_steps": job_info["num_steps"],
    }


@app.get("/dock-slurm-status")
async def api_dock_slurm_status(project: str):
    """Check status of a SLURM docking job. Returns results when complete."""
    project_dir = _get_project_dir(project)
    job_info_path = project_dir / "slurm_job_info.json"
    if not job_info_path.exists():
        raise HTTPException(status_code=404, detail="No SLURM job found for this project.")

    job_info = json.loads(job_info_path.read_text())
    mode = job_info.get("mode", "group")

    # ── Sequential assembly mode ──
    if mode == "sequential":
        seq = check_sequential_status(project_dir, job_info["job_id"])
        response = {
            "job_id": seq["job_id"],
            "status": seq["status"],
            "project": project,
            "mode": "sequential",
            "nstruct": job_info.get("nstruct", 10),
            "current_step": seq.get("current_step", 0),
            "total_steps": seq.get("total_steps", 1),
            "step_phase": seq.get("step_phase", "pending"),
            "steps": seq.get("steps", []),
            "structures_done": seq.get("structures_done", 0),
        }
        # Map final results to standard format for frontend compat
        if seq["status"] == "COMPLETED" and seq.get("final_pdb"):
            final_pdb = Path(seq["final_pdb"])
            if final_pdb.exists():
                response["results"] = {
                    "bestScore": seq.get("final_score"),
                    "bestModel": "final_assembly",
                    "pdbPath": str(final_pdb),
                    "index": 1,
                    "allModels": [{
                        "score": seq.get("final_score"),
                        "total_score": seq.get("final_score"),
                        "desc": "final_assembly",
                        "index": 1,
                        "pdb_path": str(final_pdb),
                    }],
                }
        return response

    # ── Standard group mode ──
    job_status = check_slurm_job(job_info["job_id"])

    response = {
        "job_id": job_info["job_id"],
        "status": job_status["status"],
        "project": project,
        "mode": "group",
        "nstruct": job_info["nstruct"],
    }

    # Completed → include results
    if job_status["status"] == "COMPLETED":
        fasc_path = Path(job_info["fasc_path"])
        if fasc_path.exists():
            try:
                all_models = parse_fasc_all_models(fasc_path=fasc_path, pdb_glob=str(project_dir / "complex_input_full_*.pdb"))
                for m in all_models:
                    if m.get("pdb_path"):
                        m["pdb_path"] = str(m["pdb_path"])
                best = parse_fasc_and_find_best(fasc_path=fasc_path, pdb_glob=str(project_dir / "complex_input_full_*.pdb"))
                response["results"] = {
                    "allModels": all_models,
                    "bestScore": best["score"],
                    "bestModel": best["desc"],
                    "pdbPath": str(best["pdb_path"]),
                    "index": best["index"],
                }
            except Exception as e:
                response["error"] = f"Job completed but failed to parse results: {e}"
        else:
            response["error"] = "Job completed but no results file found. Check logs."

    # Progress count from .fasc
    fasc_path = Path(job_info["fasc_path"])
    if fasc_path.exists():
        lines = fasc_path.read_text().splitlines()
        response["structures_done"] = sum(1 for l in lines if l.startswith("SCORE:") and "total_score" not in l)
    else:
        response["structures_done"] = 0

    # Log tail
    log_path = Path(job_info["log_path"])
    if log_path.exists():
        response["log_tail"] = "\n".join(log_path.read_text().splitlines()[-10:])

    return response


# ── Alanine scanning (ΔΔG) ───────────────────────────────────

@app.post("/ala-scan")
async def api_ala_scan(
    project: str = Form(...),
    pdb_path: str = Form(None),
    nstruct: int = Form(3),
    max_mutations: int = Form(8),
    n_poses: int = Form(1),
    time_limit: str = Form("00:30:00"),
    cpus: int = Form(4),
):
    """Submit Rosetta computational alanine scanning as a SLURM array job.

    n_poses > 1 triggers multi-decoy mode: scans top N docking poses
    independently, then aggregates cross-pose consensus ΔΔG.
    """
    project_dir = _get_project_dir(project)
    n_poses = max(1, min(n_poses, 5))  # clamp 1-5

    fasc = project_dir / "docking.fasc"

    if n_poses > 1:
        # Multi-pose mode: get top N models from docking results
        if not fasc.exists():
            raise HTTPException(
                status_code=400,
                detail="Docking results required for multi-pose scan. Run docking first.",
            )

        all_models = parse_fasc_all_models(
            fasc_path=fasc,
            pdb_glob=str(project_dir / "complex_input_full_*.pdb"),
        )
        # Sort by score (lower = better) and take top N with valid PDB paths
        ranked = sorted(
            [m for m in all_models if m.get("pdb_path")],
            key=lambda m: m["score"],
        )
        top_pdbs = [
            {"pdb_path": m["pdb_path"], "score": m["score"], "desc": m["desc"]}
            for m in ranked[:n_poses]
        ]

        if len(top_pdbs) < 2:
            raise HTTPException(
                status_code=400,
                detail=f"Need at least 2 docking models for multi-pose scan, found {len(top_pdbs)}.",
            )

        # Run interface analysis on best model for hotspot ranking
        _, rec_chains, bind_chains = _get_partners(project_dir)
        iface = analyze_multi_interface(
            Path(top_pdbs[0]["pdb_path"]),
            receptor_chains=rec_chains,
            binder_chains=bind_chains,
        )
        interface_data = iface.to_dict()

        job_info = run_multi_pose_ala_scan_slurm(
            project_dir=project_dir,
            interface_data=interface_data,
            top_pdbs=top_pdbs,
            nstruct=nstruct,
            max_mutations=max_mutations,
            time_limit=time_limit,
            cpus=cpus,
        )

        return {
            "job_id": job_info["poses"][0]["job_id"],  # first pose job_id for compat
            "status": "SUBMITTED",
            "project": project,
            "mutations": [m["mutation"] for m in job_info["mutations"]],
            "num_mutations": len(job_info["mutations"]),
            "n_poses": job_info["n_poses"],
            "mode": "multi_pose",
        }

    # Single-pose mode (backward compatible)
    if pdb_path:
        complex_pdb = Path(pdb_path)
    else:
        if fasc.exists():
            best = parse_fasc_and_find_best(
                fasc_path=fasc,
                pdb_glob=str(project_dir / "complex_input_full_*.pdb"),
            )
            complex_pdb = Path(best["pdb_path"])
        else:
            complex_pdb = project_dir / "complex_input.pdb"

    if not complex_pdb.exists():
        raise HTTPException(status_code=400, detail="Complex PDB not found.")

    _, rec_chains, bind_chains = _get_partners(project_dir)
    iface = analyze_multi_interface(
        complex_pdb,
        receptor_chains=rec_chains,
        binder_chains=bind_chains,
    )
    interface_data = iface.to_dict()

    job_info = run_alanine_scan_slurm(
        complex_pdb=complex_pdb,
        interface_data=interface_data,
        output_dir=project_dir,
        nstruct=nstruct,
        max_mutations=max_mutations,
        time_limit=time_limit,
        cpus=cpus,
    )

    return {
        "job_id": job_info["job_id"],
        "status": "SUBMITTED",
        "project": project,
        "mutations": [m["mutation"] for m in job_info["mutations"]],
        "num_mutations": len(job_info["mutations"]),
    }


@app.get("/ala-scan-status")
async def api_ala_scan_status(project: str):
    """Check status of an alanine scanning SLURM array job."""
    project_dir = _get_project_dir(project)
    job_info_path = project_dir / "ala_scan" / "ala_scan_job_info.json"

    if not job_info_path.exists():
        raise HTTPException(status_code=404, detail="No alanine scan job found.")

    job_info = json.loads(job_info_path.read_text())
    is_multi = job_info.get("mode") == "multi_pose"

    if is_multi:
        # Multi-pose mode
        num_tasks = job_info["num_tasks_per_pose"] * job_info["n_poses"]
        first_job_id = job_info["poses"][0]["job_id"]
        status = check_alanine_scan_job(
            first_job_id, num_tasks, job_info=job_info,
        )
        response = {
            "job_id": first_job_id,
            "status": status["status"],
            "project": project,
            "tasks_done": status["tasks_done"],
            "tasks_total": status["tasks_total"],
            "tasks_failed": status["tasks_failed"],
            "mutations": [m["mutation"] for m in job_info["mutations"]],
            "mode": "multi_pose",
            "n_poses": job_info["n_poses"],
        }
        if status.get("per_pose_status"):
            response["per_pose_status"] = status["per_pose_status"]

        if status["status"] == "COMPLETED":
            try:
                scan_dir = project_dir / "ala_scan"
                results = parse_multi_pose_results(scan_dir, job_info)
                response["results"] = results
            except Exception as e:
                response["error"] = f"Scan completed but failed to parse results: {e}"

    else:
        # Single-pose mode (backward compatible)
        status = check_alanine_scan_job(job_info["job_id"], job_info["num_tasks"])
        response = {
            "job_id": job_info["job_id"],
            "status": status["status"],
            "project": project,
            "tasks_done": status["tasks_done"],
            "tasks_total": status["tasks_total"],
            "tasks_failed": status["tasks_failed"],
            "mutations": [m["mutation"] for m in job_info["mutations"]],
        }

        if status["status"] == "COMPLETED":
            try:
                results = parse_alanine_scan_results(
                    scan_dir=Path(job_info["scan_dir"]),
                    job_info=job_info,
                )
                response["results"] = results
            except Exception as e:
                response["error"] = f"Scan completed but failed to parse results: {e}"

    return response


@app.post("/ala-scan-cancel")
async def api_ala_scan_cancel(project: str = Form(...)):
    """Cancel a running alanine scanning SLURM array job."""
    project_dir = _get_project_dir(project)
    job_info_path = project_dir / "ala_scan" / "ala_scan_job_info.json"

    if not job_info_path.exists():
        return {"status": "not_found", "project": project}

    job_info = json.loads(job_info_path.read_text())

    if job_info.get("mode") == "multi_pose":
        # Cancel all pose jobs
        for pose in job_info["poses"]:
            subprocess.run(["scancel", pose["job_id"]], capture_output=True)
        return {
            "status": "cancelled",
            "project": project,
            "job_ids": [p["job_id"] for p in job_info["poses"]],
        }

    subprocess.run(["scancel", job_info["job_id"]], capture_output=True)
    return {"status": "cancelled", "project": project, "job_id": job_info["job_id"]}


# ══════════════════════════════════════════════════════════════
#  4b. ncAA BAYESIAN OPTIMIZATION
# ══════════════════════════════════════════════════════════════

@app.get("/ncaa-builtin-library")
async def api_ncaa_builtin_library():
    """Return built-in ncAA residue types from the PyRosetta database."""
    ncaa_dir = NCAA_PYROSETTA_DB / "chemical" / "residue_type_sets" / "fa_standard" / "residue_types" / "l-ncaa"
    if not ncaa_dir.is_dir():
        raise HTTPException(404, f"PyRosetta ncAA directory not found: {ncaa_dir}")
    entries = []
    for params_file in sorted(ncaa_dir.glob("*.params")):
        name = None
        for line in params_file.open():
            if line.startswith("NAME "):
                name = line.split()[1]
                break
        if name:
            # Derive a human-readable label from the filename
            label = params_file.stem.replace("_", " ").replace("-", "-")
            entries.append({"code": name, "label": label})
    return {"count": len(entries), "entries": entries}


@app.post("/ncaa-upload-params")
async def api_ncaa_upload_params(
    project: str = Form(...),
    files: list[UploadFile] = File(...),
):
    """Upload .params files for non-canonical amino acids."""
    project_dir = _get_project_dir(project)
    params_dir, ncaa_names = handle_ncaa_params_upload(project_dir, files)
    return {
        "count": len(ncaa_names),
        "ncaa_names": ncaa_names,
        "params_dir": str(params_dir),
    }


@app.post("/ncaa-optimize")
async def api_ncaa_optimize(
    project: str = Form(...),
    pdb_path: str = Form(None),
    ncaa_list: str = Form(...),
    positions: str = Form("auto"),
    mode: str = Form("single"),
    n_calls: int = Form(20),
    trials: int = Form(1),
    use_ala_scan_seed: bool = Form(False),
    time_limit: str = Form("02:00:00"),
    cpus: int = Form(4),
):
    """Submit ncAA Bayesian optimization as a SLURM job."""
    project_dir = _get_project_dir(project)

    # Resolve PDB
    if pdb_path:
        complex_pdb = Path(pdb_path)
    else:
        fasc = project_dir / "docking.fasc"
        if fasc.exists():
            best = parse_fasc_and_find_best(
                fasc_path=fasc,
                pdb_glob=str(project_dir / "complex_input_full_*.pdb"),
            )
            complex_pdb = Path(best["pdb_path"])
        else:
            complex_pdb = project_dir / "complex_input.pdb"

    if not complex_pdb.exists():
        raise HTTPException(status_code=400, detail="Complex PDB not found.")

    # Resolve partners
    partners_file = project_dir / "partners.txt"
    partners = partners_file.read_text().strip() if partners_file.exists() else "A_B"

    # Resolve params directory (optional — built-in ncAAs don't need it)
    params_dir = project_dir / "ncaa_params"
    if not params_dir.exists():
        params_dir = None  # no custom params; built-in ncAAs still work

    # Parse ncaa_list
    ncaa_names = [n.strip() for n in ncaa_list.split(",") if n.strip()]
    if not ncaa_names:
        raise HTTPException(status_code=400, detail="No ncAA names provided.")

    # Validate mode
    if mode not in ("single", "pareto", "combinatorial"):
        mode = "single"
    n_calls = max(2, min(n_calls, 100))

    # Warm-start from ala scan?
    seed_csv = ""
    if use_ala_scan_seed:
        scan_dir = project_dir / "ala_scan"
        # Look for ala scan CSV results
        for candidate in scan_dir.glob("*.csv"):
            seed_csv = str(candidate)
            break

    job_info = run_ncaa_optimize_slurm(
        complex_pdb=complex_pdb,
        output_dir=project_dir,
        partners=partners,
        ncaa_list=ncaa_names,
        params_dir=params_dir,
        positions=positions,
        mode=mode,
        n_calls=n_calls,
        trials=trials,
        seed_csv=seed_csv,
        time_limit=time_limit,
        cpus=cpus,
    )

    return {
        "job_id": job_info["job_id"],
        "status": "SUBMITTED",
        "project": project,
        "ncaa_list": ncaa_names,
        "mode": mode,
        "n_calls": n_calls,
    }


@app.get("/ncaa-optimize-status")
async def api_ncaa_optimize_status(project: str):
    """Check status of ncAA optimization SLURM job."""
    project_dir = _get_project_dir(project)
    info_path = project_dir / "ncaa_opt" / "ncaa_opt_job_info.json"

    if not info_path.exists():
        raise HTTPException(status_code=404, detail="No ncAA optimization job found.")

    job_info = json.loads(info_path.read_text())
    opt_dir = Path(job_info["opt_dir"])

    status = check_ncaa_optimize_job(
        job_info["job_id"], opt_dir, job_info["n_calls"],
    )

    response = {
        "job_id": job_info["job_id"],
        "status": status["status"],
        "project": project,
        "evaluations_done": status["evaluations_done"],
        "evaluations_total": status["evaluations_total"],
        "mode": job_info.get("mode", "single"),
        "ncaa_list": job_info.get("ncaa_list", []),
    }

    if status["status"] == "COMPLETED":
        try:
            results = parse_ncaa_optimize_results(opt_dir, job_info)
            response["results"] = results
        except Exception as e:
            response["error"] = f"Optimization completed but failed to parse results: {e}"

    return response


@app.post("/ncaa-optimize-cancel")
async def api_ncaa_optimize_cancel(project: str = Form(...)):
    """Cancel a running ncAA optimization SLURM job."""
    project_dir = _get_project_dir(project)
    info_path = project_dir / "ncaa_opt" / "ncaa_opt_job_info.json"

    if not info_path.exists():
        return {"status": "not_found", "project": project}

    job_info = json.loads(info_path.read_text())
    subprocess.run(["scancel", job_info["job_id"]], capture_output=True)
    return {"status": "cancelled", "project": project, "job_id": job_info["job_id"]}


# ══════════════════════════════════════════════════════════════
#  5. RESULTS & FILES
# ══════════════════════════════════════════════════════════════

@app.get("/dock-results")
async def api_dock_results(project: str):
    """Get all docking results for a project."""
    project_dir = _get_project_dir(project)
    fasc_path = project_dir / "docking.fasc"
    if not fasc_path.exists():
        raise HTTPException(status_code=404, detail="No docking results. Run docking first.")

    try:
        all_models = parse_fasc_all_models(fasc_path=fasc_path, pdb_glob=str(project_dir / "complex_input_full_*.pdb"))
        for m in all_models:
            if m.get("pdb_path"):
                m["pdb_path"] = str(m["pdb_path"])
        best = parse_fasc_and_find_best(fasc_path=fasc_path, pdb_glob=str(project_dir / "complex_input_full_*.pdb"))
        return {
            "allModels": all_models,
            "best": {"score": best["score"], "desc": best["desc"], "index": best["index"], "pdb_path": str(best["pdb_path"])},
            "project": project,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse results: {e}")


_VALID_PDB_RECORDS = re.compile(
    r"^(HEADER|OBSLTE|TITLE|COMPND|SOURCE|KEYWDS|EXPDTA|NUMMDL|AUTHOR|"
    r"REVDAT|JRNL|REMARK|DBREF|SEQRES|MODRES|HET |HETNAM|HETSYN|FORMUL|"
    r"HELIX|SHEET|SSBOND|LINK|SITE|ATOM|ANISOU|TER|HETATM|CONECT|"
    r"MODEL|ENDMDL|MASTER|END)"
)


def _clean_pdb_for_viewer(text: str) -> str:
    """Keep only valid PDB records — strips Rosetta scores/energy tables."""
    lines = [l for l in text.splitlines() if _VALID_PDB_RECORDS.match(l)]
    if not any(l.startswith("END") for l in lines):
        lines.append("END")
    return "\n".join(lines)


@app.get("/pdb-content")
async def api_pdb_content(path: str):
    """Return cleaned PDB text for 3Dmol.js rendering."""
    p = _validate_pdb(path)
    _validate_workdir_access(p)
    return _clean_pdb_for_viewer(p.read_text())


@app.get("/pdb-image")
async def api_pdb_image(path: str):
    """Return the PyMOL-rendered PNG for a docked model (if it exists)."""
    pdb_p = Path(path)
    img_p = pdb_p.with_suffix(".png")
    if not img_p.exists():
        raise HTTPException(status_code=404, detail="No rendered image. Click 'Render PyMOL Image' first.")
    _validate_workdir_access(img_p)
    return FileResponse(str(img_p), media_type="image/png")


# Chain color palette for up to 26 chains
_CHAIN_COLORS = [
    "0x2dd4bf",  # A - teal
    "0xfb923c",  # B - orange
    "0xa78bfa",  # C - purple
    "0x34d399",  # D - emerald
    "0xf472b6",  # E - pink
    "0x60a5fa",  # F - blue
    "0xfbbf24",  # G - amber
    "0xf87171",  # H - red
    "0x4ade80",  # I - green
    "0xc084fc",  # J - violet
]

_INTERFACE_COLORS = [
    "0xec4899",  # pink
    "0xf97316",  # orange
    "0x8b5cf6",  # violet
    "0x10b981",  # emerald
    "0xef4444",  # red
]


def _detect_chains_from_pdb(pdb_path: Path) -> list[str]:
    """Detect unique chain IDs from a PDB file."""
    chains: list[str] = []
    seen: set[str] = set()
    try:
        with open(pdb_path) as fh:
            for line in fh:
                if line.startswith(("ATOM", "HETATM")):
                    ch = line[21].strip()
                    if ch and ch not in seen:
                        seen.add(ch)
                        chains.append(ch)
    except Exception:
        pass
    return chains or ["A", "B"]


def _generate_pymol_script(pdb_path: Path, *, headless: bool = False) -> str:
    """Build the PyMOL visualization script for a docked model (N-chain aware)."""
    img_path = pdb_path.with_suffix(".png")
    load_path = str(pdb_path) if headless else pdb_path.name
    chains = _detect_chains_from_pdb(pdb_path)

    # Build chain coloring lines
    color_lines = []
    for i, ch in enumerate(chains):
        color = _CHAIN_COLORS[i % len(_CHAIN_COLORS)]
        color_lines.append(f"color {color}, chain {ch}")

    show_chains = " or ".join(f"chain {ch}" for ch in chains)

    # Build surface color lines
    surface_lines = []
    for i, ch in enumerate(chains):
        color = _CHAIN_COLORS[i % len(_CHAIN_COLORS)]
        surface_lines.append(f"set surface_color, {color}, chain {ch}")

    # Interface: first chain vs all others
    if len(chains) >= 2:
        rest_sel = " or ".join(f"chain {ch}" for ch in chains[1:])
        interface_block = f"""
# ── Interface residues ───────────────────────────
select interface_first, (chain {chains[0]} within 5 of ({rest_sel}))
select interface_rest, (({rest_sel}) within 5 of chain {chains[0]})
select interface, interface_first or interface_rest

show sticks, interface
set stick_radius, 0.15
color {_INTERFACE_COLORS[0]}, interface and chain {chains[0]}
"""
        for i, ch in enumerate(chains[1:]):
            icolor = _INTERFACE_COLORS[(i + 1) % len(_INTERFACE_COLORS)]
            interface_block += f"color {icolor}, interface and chain {ch}\n"

        interface_block += f"""
# ── Polar contacts across the interface ──────────
distance hbonds, interface_first, interface_rest, 3.5, mode=2
hide labels, hbonds
set dash_color, 0xfbbf24, hbonds
set dash_gap, 0.3
set dash_width, 2.0
"""
    else:
        interface_block = ""

    script = f"""# ProteinDock — Docking Visualization
load {load_path}

# ── Scene setup ──────────────────────────────────
bg_color white
set ray_shadow, 1
set ray_trace_mode, 1
set antialias, 2
set orthoscopic, off
set depth_cue, 1
set fog_start, 0.45

hide everything

# ── Chain coloring ({len(chains)} chains) ────────────────────
{chr(10).join(color_lines)}
show cartoon, {show_chains}
set cartoon_fancy_helices, 1
set cartoon_smooth_loops, 1
set cartoon_flat_sheets, 1
{interface_block}
# ── Surface overlay (transparent) ────────────────
show surface, {show_chains}
{chr(10).join(surface_lines)}
set transparency, 0.75

zoom interface, 5
deselect
"""
    if headless:
        script += f"""
# ── Render to PNG ────────────────────────────────
ray 2000,1500
png {img_path}, dpi=300
quit
"""
    return script


@app.get("/pymol-script")
async def api_pymol_script(path: str):
    """Generate a portable PyMOL .pml script for local use."""
    p = _validate_pdb(path)
    _validate_workdir_access(p)
    script = _generate_pymol_script(p, headless=False)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        content=script,
        headers={"Content-Disposition": f'attachment; filename="{p.stem}_view.pml"'},
    )


@app.post("/open-pymol")
async def api_open_pymol(path: str = Form(...)):
    """Launch PyMOL interactively on the server (requires X11 forwarding)."""
    p = _validate_pdb(path)
    _validate_workdir_access(p)

    pml_path = p.with_suffix(".interactive.pml")
    pml_path.write_text(_generate_pymol_script(p, headless=False))

    try:
        subprocess.Popen(
            ["bash", "-c", f"{PYMOL_COMMAND} {pml_path}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"status": "launched", "pml_path": str(pml_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch PyMOL: {e}")


@app.get("/download")
async def api_download(path: str):
    """Download any file within the work directory."""
    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    _validate_workdir_access(p)
    return FileResponse(path)


@app.post("/visualize")
async def api_visualize(project: str = Form(...), pdb: str = Form(None)):
    """Render a PyMOL image of the best docking model."""
    project_dir = _get_project_dir(project)
    try:
        result = visualize_best_model(
            fasc_path=project_dir / "docking.fasc",
            pdb_glob=str(project_dir / "complex_input_full_*.pdb"),
        )
        return {"ok": True, "project": project, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        return {"ok": False, "project": project, "error": str(e)}


# ══════════════════════════════════════════════════════════════
#  6. ANALYSIS
# ══════════════════════════════════════════════════════════════

@app.get("/analyze-interface")
async def api_analyze_interface(project: str, pdb_path: str = None):
    """Analyze the binding interface of a docked model."""
    project_dir = _get_project_dir(project)

    if not pdb_path:
        best = _resolve_best_model(project_dir)
        pdb_path = str(best["pdb_path"])

    p = _validate_pdb(pdb_path)

    partners_str, rec_chains, bind_chains = _get_partners(project_dir)
    analysis = await asyncio.to_thread(
        analyze_multi_interface, p,
        receptor_chains=rec_chains,
        binder_chains=bind_chains,
    )
    result = analysis.to_dict()
    result["partners"] = partners_str
    result["receptor_chains"] = rec_chains
    result["binder_chains"] = bind_chains
    return {"project": project, "pdb_path": pdb_path, **result}


@app.get("/ai-interpret")
async def api_ai_interpret(project: str, pdb_path: str = None):
    """AI-powered biological interpretation of a docking result."""
    project_dir = _get_project_dir(project)
    fasc = project_dir / "docking.fasc"
    if not fasc.exists():
        raise HTTPException(status_code=404, detail="No docking results found.")

    all_models = parse_fasc_all_models(
        fasc_path=fasc, pdb_glob=str(project_dir / "complex_input_full_*.pdb"),
    )

    if not pdb_path:
        best = _resolve_best_model(project_dir)
        pdb_path = str(best["pdb_path"])
        scores = best
    else:
        scores = next((m for m in all_models if m.get("pdb_path") == pdb_path), {})

    p = _validate_pdb(pdb_path)
    _, rec_chains, bind_chains = _get_partners(project_dir)
    analysis = await asyncio.to_thread(
        analyze_multi_interface, p,
        receptor_chains=rec_chains,
        binder_chains=bind_chains,
    )
    interface_data = analysis.to_dict()
    result = await asyncio.to_thread(generate_interpretation, scores, interface_data)
    return {"project": project, "pdb_path": pdb_path, **result}


@app.get("/experiment-plan")
async def api_experiment_plan(project: str, pdb_path: str = None):
    """Generate a wet-lab validation plan from docking results."""
    project_dir = _get_project_dir(project)

    if not pdb_path:
        best = _resolve_best_model(project_dir)
        pdb_path = str(best["pdb_path"])

    p = _validate_pdb(pdb_path)
    _, rec_chains, bind_chains = _get_partners(project_dir)
    analysis = await asyncio.to_thread(
        analyze_multi_interface, p,
        receptor_chains=rec_chains,
        binder_chains=bind_chains,
    )
    plan = design_experiments(analysis.to_dict())
    return {"project": project, "pdb_path": pdb_path, **plan.to_dict()}


# ══════════════════════════════════════════════════════════════
#  7. EXPORT
# ══════════════════════════════════════════════════════════════

@app.get("/share")
async def api_share(project: str, pdb_path: str = None):
    """Generate a self-contained HTML report with embedded 3D viewer."""
    project_dir = _get_project_dir(project)
    fasc = project_dir / "docking.fasc"
    if not fasc.exists():
        raise HTTPException(status_code=404, detail="No docking results found.")

    all_models = parse_fasc_all_models(
        fasc_path=fasc, pdb_glob=str(project_dir / "complex_input_full_*.pdb"),
    )

    if not pdb_path:
        best = _resolve_best_model(project_dir)
        pdb_path = str(best["pdb_path"])
        scores = best
    else:
        scores = next((m for m in all_models if m.get("pdb_path") == pdb_path), {})

    p = _validate_pdb(pdb_path)

    # Interface analysis (required)
    _, rec_chains, bind_chains = _get_partners(project_dir)
    analysis = await asyncio.to_thread(
        analyze_multi_interface, p,
        receptor_chains=rec_chains,
        binder_chains=bind_chains,
    )
    interface_data = analysis.to_dict()

    # AI interpretation (best-effort)
    ai_result = None
    try:
        ai_result = await asyncio.to_thread(generate_interpretation, scores, interface_data)
    except Exception:
        pass

    # Experiment plan (best-effort)
    experiment_plan = None
    try:
        experiment_plan = design_experiments(interface_data).to_dict()
    except Exception:
        pass

    html_content = generate_share_html(
        pdb_path=p,
        scores=scores,
        interface_data=interface_data,
        ai_result=ai_result,
        experiment_plan=experiment_plan,
        project_name=project,
    )

    return HTMLResponse(
        content=html_content,
        headers={"Content-Disposition": f'attachment; filename="{p.stem}_report.html"'},
    )


# ══════════════════════════════════════════════════════════════
#  8. PROTEINMPNN INTERFACE REDESIGN
# ══════════════════════════════════════════════════════════════

@app.post("/design-mpnn")
async def api_design_mpnn(
    project: str = Form(...),
    pdb_path: str = Form(None),
    binder_chain: str = Form("B"),
    n_seqs: int = Form(10),
    temperature: float = Form(0.1),
    redesign_interface_only: bool = Form(True),
):
    """
    Run ProteinMPNN to redesign binder interface residues.
    Returns ranked sequences with ProteinMPNN scores.
    """
    project_dir = _get_project_dir(project)

    if not pdb_path:
        best = _resolve_best_model(project_dir)
        pdb_path = str(best["pdb_path"])

    complex_pdb = _validate_pdb(pdb_path)
    output_dir = project_dir / "mpnn_design"

    interface_residue_ids = None
    if redesign_interface_only:
        _, rec_chains, bind_chains = _get_partners(project_dir)
        analysis = await asyncio.to_thread(
            analyze_multi_interface, complex_pdb,
            receptor_chains=rec_chains,
            binder_chains=bind_chains,
        )
        interface_residue_ids = [
            r.resid for r in analysis.residues_b
        ]

    sequences = await asyncio.to_thread(
        run_mpnn_design,
        complex_pdb, output_dir,
        binder_chain=binder_chain,
        interface_residue_ids=interface_residue_ids,
        n_seqs=n_seqs,
        temperature=temperature,
    )

    return {
        "project": project,
        "pdb_path": pdb_path,
        "binder_chain": binder_chain,
        "n_interface_residues": len(interface_residue_ids) if interface_residue_ids else None,
        "sequences": sequences,
    }


# ══════════════════════════════════════════════════════════════
#  9. BENCHMARKING (DockQ)
# ══════════════════════════════════════════════════════════════

@app.get("/benchmark-presets")
async def api_benchmark_presets():
    """Return the curated preset benchmark set."""
    return {"presets": PRESET_BENCHMARK}


@app.post("/score-dockq")
async def api_score_dockq(
    project: str = Form(...),
    model_pdb: str = Form(...),
    native_pdb: str = Form(...),
    receptor_chains: str = Form("A"),
    binder_chains: str = Form("B"),
):
    """Score a single docked model against a native structure using DockQ."""
    model_path = _validate_pdb(model_pdb)
    native_path = Path(native_pdb)
    if not native_path.exists():
        raise HTTPException(status_code=404, detail=f"Native PDB not found: {native_pdb}")

    rec = [c.strip() for c in receptor_chains.split(",") if c.strip()]
    bind = [c.strip() for c in binder_chains.split(",") if c.strip()]

    result = await asyncio.to_thread(
        score_dockq, model_path, native_path, rec, bind
    )
    return {"project": project, "model_pdb": model_pdb, **result}


@app.post("/benchmark")
async def api_benchmark(
    entries: str = Form(...),       # JSON array of benchmark entries
    nstruct: int = Form(10),
    time_limit: str = Form("04:00:00"),
    cpus: int = Form(4),
):
    """Submit a SLURM benchmark job. entries is a JSON array of PDB entry dicts."""
    try:
        entry_list = json.loads(entries)
    except Exception:
        raise HTTPException(status_code=422, detail="entries must be valid JSON array.")

    output_dir = WORKDIR / "benchmark"
    job_info = await asyncio.to_thread(
        run_benchmark_slurm, entry_list, output_dir, nstruct, time_limit, cpus
    )
    return job_info


@app.get("/benchmark-status")
async def api_benchmark_status(job_id: str, num_entries: int):
    """Poll SLURM benchmark job status and return per-PDB results."""
    output_dir = WORKDIR / "benchmark"
    result = await asyncio.to_thread(
        check_benchmark_job, job_id, output_dir, num_entries
    )
    return result


# ══════════════════════════════════════════════════════════════
#  STATIC FRONTEND (built dist/ served on the same port)
# ══════════════════════════════════════════════════════════════

DIST_DIR = Path(__file__).resolve().parent.parent / "protein-weaver" / "dist"
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="frontend")
