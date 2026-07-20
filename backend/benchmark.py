#!/usr/bin/env python3
"""
benchmark.py — SLURM job management for DockQ benchmarking.

Exposes:
  run_benchmark_slurm(entries, output_dir, nstruct, time_limit, cpus) -> dict
  check_benchmark_job(job_id, output_dir, num_entries) -> dict
  PRESET_BENCHMARK (re-exported from dockq_scorer)
"""

import json
import subprocess
from pathlib import Path

from backend.config import SLURM_ACCOUNT
from backend.dockq_scorer import PRESET_BENCHMARK

# Path to the standalone runner script (same directory as this file)
_RUNNER = Path(__file__).resolve().parent / "benchmark_runner.py"

# Path to the protein_web venv Python
_VENV_PYTHON = Path(__file__).resolve().parent.parent / "venv" / "bin" / "python"


def run_benchmark_slurm(
    entries: list[dict],
    output_dir: Path,
    nstruct: int = 10,
    time_limit: str = "04:00:00",
    cpus: int = 4,
) -> dict:
    """
    Submit a SLURM job that runs the full benchmark pipeline.

    Generates:
      output_dir/benchmark_config.json  — entries + settings
      output_dir/benchmark_job.sh       — SLURM batch script
      output_dir/results.json           — written progressively by runner
      output_dir/summary.json           — written at completion
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write config for the runner
    config = {"entries": entries, "nstruct": nstruct}
    config_path = output_dir / "benchmark_config.json"
    config_path.write_text(json.dumps(config, indent=2))

    python = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else "python3"

    script = f"""#!/bin/bash
#SBATCH --job-name=proteindock_benchmark
#SBATCH --account={SLURM_ACCOUNT}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={cpus}
#SBATCH --time={time_limit}
#SBATCH --output={output_dir}/slurm-%j.out
#SBATCH --error={output_dir}/slurm-%j.err

{python} {_RUNNER} --config {config_path} --output {output_dir}
"""
    job_script = output_dir / "benchmark_job.sh"
    job_script.write_text(script)

    result = subprocess.run(
        ["sbatch", str(job_script)],
        capture_output=True, text=True, check=True,
    )
    job_id = result.stdout.strip().split()[-1]

    job_info = {
        "job_id": job_id,
        "output_dir": str(output_dir),
        "num_entries": len(entries),
        "nstruct": nstruct,
    }
    (output_dir / "benchmark_job_info.json").write_text(json.dumps(job_info, indent=2))
    return job_info


def check_benchmark_job(job_id: str, output_dir: Path, num_entries: int) -> dict:
    """
    Poll SLURM for benchmark job status.

    Returns dict with:
      status: PENDING | RUNNING | COMPLETED | FAILED
      done: number of PDBs processed so far
      total: total PDBs
      results: list of per-PDB results (from results.json if available)
      summary: aggregate stats (from summary.json if completed)
    """
    output_dir = Path(output_dir)

    sacct = subprocess.run(
        ["sacct", "--job", job_id, "--format", "State", "--noheader", "--parsable2"],
        capture_output=True, text=True,
    )
    raw_states = [s.strip() for s in sacct.stdout.strip().splitlines() if s.strip()]
    state = raw_states[0] if raw_states else "UNKNOWN"

    # Normalize compound states like "CANCELLED by 1234"
    if state.startswith("CANCELLED"):
        state = "CANCELLED"

    # Read progressive results if available
    results_file = output_dir / "results.json"
    results = []
    if results_file.exists():
        try:
            results = json.loads(results_file.read_text())
        except Exception:
            pass

    progress_file = output_dir / "progress.json"
    done = 0
    if progress_file.exists():
        try:
            done = json.loads(progress_file.read_text()).get("done", 0)
        except Exception:
            pass

    response = {
        "status": state,
        "done": done,
        "total": num_entries,
        "results": results,
    }

    if state == "COMPLETED":
        summary_file = output_dir / "summary.json"
        if summary_file.exists():
            try:
                response["summary"] = json.loads(summary_file.read_text())
            except Exception:
                pass
        response["summary"] = _compute_summary(results)

    return response


def _compute_summary(results: list[dict]) -> dict:
    """Compute aggregate statistics from completed benchmark results."""
    successful = [r for r in results if r.get("status") == "success"]
    scores = [r["DockQ"] for r in successful if r.get("DockQ") is not None]

    if not scores:
        return {"mean_DockQ": None, "success_rate": 0.0, "by_classification": {}}

    by_class: dict[str, int] = {"High": 0, "Medium": 0, "Acceptable": 0, "Incorrect": 0}
    for r in successful:
        c = r.get("classification", "Incorrect")
        by_class[c] = by_class.get(c, 0) + 1

    return {
        "mean_DockQ": round(sum(scores) / len(scores), 4),
        "median_DockQ": round(sorted(scores)[len(scores) // 2], 4),
        "success_rate": round(len(successful) / len(results), 3) if results else 0.0,
        "acceptable_or_better": round(
            (by_class["Acceptable"] + by_class["Medium"] + by_class["High"]) / len(results), 3
        ) if results else 0.0,
        "by_classification": by_class,
        "n_total": len(results),
        "n_success": len(successful),
    }
