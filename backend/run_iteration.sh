#!/usr/bin/env bash
# run_iteration.sh — Fire one iteration of the unbound DB5.5 benchmark.
#
# Each iteration writes to ~/protein_web_jobs/bench_runs/<label>/ so
# compare_runs.py can diff them later.
#
# Usage:
#   bash run_iteration.sh <label> [--pre-relax] [--docking-mode local|global] [--nstruct 50]
#
# Examples:
#   bash run_iteration.sh iter0_baseline --nstruct 50
#   bash run_iteration.sh iter1_prerelax --pre-relax --nstruct 50
#   bash run_iteration.sh iter4_blind --docking-mode global --nstruct 50
#   bash run_iteration.sh iter5_combined --pre-relax --docking-mode global --nstruct 100

set -euo pipefail

LABEL="${1:-}"
if [[ -z "$LABEL" ]]; then
    echo "Usage: bash $0 <label> [--pre-relax] [--docking-mode local|global] [--nstruct N]"
    exit 1
fi
shift

BENCH_RUNS=~/protein_web_jobs/bench_runs
RUN_DIR=$BENCH_RUNS/$LABEL
DB55=~/protein_web_jobs/db55_structures
INDEX=$BENCH_RUNS/db55_unbound_index.json

mkdir -p $RUN_DIR

# Cluster-aware venv selection (works on Pitzer login + Cardinal login)
HOST=$(hostname)
case "$HOST" in
    pitzer*|p[0-9]*)  VENV=/fs/scratch/PAS2959/proteindock/protein_web/venv-pitzer/bin/python3 ;;
    cardinal*|c[0-9]*) VENV=/fs/scratch/PAS2959/proteindock/protein_web/venv-cardinal/bin/python3 ;;
    *) VENV=/fs/scratch/PAS2959/proteindock/protein_web/venv-pitzer/bin/python3 ;;
esac

RUNNER=/fs/scratch/PAS2959/proteindock/protein_web/backend/benchmark_runner_custom.py
BUILDER=/fs/scratch/PAS2959/proteindock/protein_web/backend/build_benchmark_index.py

# Build index if it doesn't exist
if [[ ! -f "$INDEX" ]]; then
    echo "→ Building DB5.5 unbound benchmark index..."
    $VENV $BUILDER \
        --source db55 \
        --dir "$DB55" \
        --codes "1AY7,1CGI,1ACB,1PPE,2SIC,2SNI,1DFJ,1AVX,1BVN,1EWY" \
        --out "$INDEX" \
        --stage "$BENCH_RUNS/db55_native_stage"
    echo "  ✓ wrote $INDEX"
fi

# Build SLURM script
SCRIPT=$RUN_DIR/job.sh
cat > "$SCRIPT" <<EOF
#!/bin/bash
#SBATCH --job-name=bench_$LABEL
#SBATCH --account=PAS2959
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=12:00:00
#SBATCH --output=$RUN_DIR/slurm-%j.out
#SBATCH --error=$RUN_DIR/slurm-%j.err

cd $RUN_DIR
$VENV $RUNNER \\
    --index $INDEX \\
    --output $RUN_DIR \\
    $@
EOF

chmod +x "$SCRIPT"

echo "→ Submitting iteration: $LABEL"
echo "  Args: $@"
JOB_ID=$(sbatch "$SCRIPT" | awk '{print $4}')
echo "  ✓ submitted job $JOB_ID"
echo "  Output: $RUN_DIR/results.json (when done)"
echo "  Logs:   $RUN_DIR/slurm-${JOB_ID}.{out,err}"
echo
echo "Watch progress:"
echo "  sacct -j $JOB_ID --format=JobID,State,Elapsed"
echo "  cat $RUN_DIR/progress.json"
echo
echo "When done, compare:"
echo "  compare_runs.py iter0_baseline $LABEL"
