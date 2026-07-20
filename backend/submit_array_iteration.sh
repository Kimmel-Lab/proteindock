#!/usr/bin/env bash
# submit_array_iteration.sh — Submit a single iteration as a SLURM array
# job (one task per PDB) for ~10× wall-clock speedup vs sequential.
#
# Companion to paper2_orchestrator.sh's per-iteration logic but parallelizes
# across PDBs.
#
# Usage:
#   bash submit_array_iteration.sh <label> <index_path> <output_dir> [extra args...]
#
# Example:
#   bash submit_array_iteration.sh iter1_prerelax \
#        ~/protein_web_jobs/bench_runs/db55_unbound_index.json \
#        ~/protein_web_jobs/bench_runs/db55_unbound_iter1_prerelax \
#        --pre-relax --nstruct 50

set -euo pipefail

LABEL="${1:?usage: submit_array_iteration.sh LABEL INDEX OUT [extra...]}"
INDEX="${2:?need index path}"
OUT="${3:?need output dir}"
shift 3
EXTRA_ARGS="$@"

mkdir -p "$OUT"

# Detect cluster + venv + count entries
case "$(hostname)" in
    pitzer*|p[0-9]*) VENV=/fs/scratch/PAS2959/proteindock/protein_web/venv-pitzer/bin/python3 ;;
    cardinal*|c[0-9]*) VENV=/fs/scratch/PAS2959/proteindock/protein_web/venv-cardinal/bin/python3 ;;
    *) VENV=/fs/scratch/PAS2959/proteindock/protein_web/venv-cardinal/bin/python3 ;;
esac

N_ENTRIES=$($VENV -c "import json; print(len(json.load(open('$INDEX'))))")
LAST=$((N_ENTRIES - 1))

RUNNER=/fs/scratch/PAS2959/proteindock/protein_web/backend/benchmark_runner_custom.py
SCRIPT=$OUT/array_job.sh

cat > "$SCRIPT" <<EOF
#!/bin/bash
#SBATCH --job-name=p2_${LABEL}
#SBATCH --account=PAS2959
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=08:00:00
#SBATCH --array=0-${LAST}
#SBATCH --output=$OUT/slurm-%A_%a.out
#SBATCH --error=$OUT/slurm-%A_%a.err

# On Cardinal compute, libimf.so isn't on LD_LIBRARY_PATH by default on all
# node generations. DockQ's Cython extension needs it. Add path explicitly.
case "\$(hostname)" in
    c[0-9]*|cardinal*)
        export LD_LIBRARY_PATH=/apps/spack/0.21/cardinal/linux-rhel9-sapphirerapids/intel-oneapi-compilers/gcc/11.3.1/2024.1.0-utk57mo/compiler/2024.1/lib:\${LD_LIBRARY_PATH:-}
        ;;
esac

cd $OUT
$VENV $RUNNER \\
    --index $INDEX \\
    --output $OUT \\
    --array-task-id \$SLURM_ARRAY_TASK_ID \\
    $EXTRA_ARGS
EOF
chmod +x "$SCRIPT"

JOB=$(sbatch "$SCRIPT" | awk '{print $4}')
echo "Submitted array job $JOB → $OUT (tasks 0-$LAST)"
echo "$JOB"
