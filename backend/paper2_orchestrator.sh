#!/usr/bin/env bash
# paper2_orchestrator.sh — One-command pipeline that runs the full
# paper-2 iteration ladder: iter0 (baseline) → iter1 (pre-relax) → iter2
# (top-N redock) → iter3 (combined) → boltz_alone → boltz_refined →
# train ncAA reranker → final reranked numbers.
#
# Each iteration submits as a SLURM job and waits for previous to finish
# (via --dependency=afterany or polling). The script prints status + the
# final comparison table at the end.
#
# Usage:
#   bash paper2_orchestrator.sh <dataset> [--from <iter>]
#
# Datasets:
#   db55_unbound  — DB5.5 unbound 10-PDB subset (default)
#   pinder_s      — PINDER-S small curated
#   pinder_af2    — PINDER-AF2 leakage-controlled
#   sabdab        — SAbDab antibody-antigen curated 20
#
# --from <iter>  Resume from iteration N (e.g., --from iter3_combined)
#
# Run on a login node. Designed to take overnight + a day to fully execute.

set -euo pipefail

DATASET="${1:-db55_unbound}"
RESUME_FROM=""
shift || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) RESUME_FROM="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Paths ────────────────────────────────────────────────────
SHARED=/fs/scratch/PAS2959/proteindock
BACKEND=$SHARED/protein_web/backend
BENCH_RUNS=$HOME/protein_web_jobs/bench_runs

case "$(hostname)" in
    pitzer*|p[0-9]*)  VENV=$SHARED/protein_web/venv-pitzer/bin/python3 ;;
    cardinal*|c[0-9]*) VENV=$SHARED/protein_web/venv-cardinal/bin/python3 ;;
    *) VENV=$SHARED/protein_web/venv-pitzer/bin/python3 ;;
esac

# ── Per-dataset index path ───────────────────────────────────
mkdir -p "$BENCH_RUNS"
case "$DATASET" in
    db55_unbound)
        INDEX=$BENCH_RUNS/db55_unbound_index.json
        if [[ ! -f "$INDEX" ]]; then
            $VENV $BACKEND/build_benchmark_index.py \
                --source db55 \
                --dir $HOME/protein_web_jobs/db55_structures \
                --codes "1AY7,1CGI,1ACB,1PPE,2SIC,2SNI,1DFJ,1AVX,1BVN,1EWY" \
                --out "$INDEX" \
                --stage "$BENCH_RUNS/db55_native_stage"
        fi
        ;;
    db55_full)
        # Full DB5.5 (~254 targets with both bound + unbound).
        # This is the benchmark AlphaRED was scored on — use this for SOTA claims.
        INDEX=$BENCH_RUNS/db55_full_index.json
        if [[ ! -f "$INDEX" ]]; then
            $VENV $BACKEND/build_benchmark_index.py \
                --source db55 \
                --dir $HOME/protein_web_jobs/db55_structures \
                --all \
                --out "$INDEX" \
                --stage "$BENCH_RUNS/db55_full_native_stage"
        fi
        ;;
    pinder_s)
        INDEX=$BENCH_RUNS/pinder_s_index.json
        [[ ! -f "$INDEX" ]] && $VENV $BACKEND/fetch_pinder.py \
            --subset PINDER-S --out $HOME/protein_web_jobs/pinder_data \
            --index "$INDEX" --limit 20
        ;;
    pinder_af2)
        INDEX=$BENCH_RUNS/pinder_af2_holo_index.json
        [[ ! -f "$INDEX" ]] && $VENV $BACKEND/fetch_pinder.py \
            --subset PINDER-AF2 --type holo \
            --out $HOME/protein_web_jobs/pinder_data --index "$INDEX"
        ;;
    sabdab)
        INDEX=$BENCH_RUNS/sabdab_index.json
        [[ ! -f "$INDEX" ]] && $VENV $BACKEND/fetch_sabdab.py \
            --out $HOME/protein_web_jobs/sabdab_data --index "$INDEX"
        ;;
    *) echo "Unknown dataset: $DATASET"; exit 1 ;;
esac

echo "=== Paper-2 orchestrator ==="
echo "Dataset:    $DATASET"
echo "Index:      $INDEX"
echo "Resume:     ${RESUME_FROM:-(none, full pipeline)}"
echo

# ── Define iteration ladder ──────────────────────────────────
# Each tuple: label | extra args to benchmark_runner_custom.py
declare -A LADDER
LADDER[iter0_baseline]=""
LADDER[iter1_prerelax]="--pre-relax"
LADDER[iter2_topN]="--refine-top-n 5"
LADDER[iter3_combined]="--pre-relax --refine-top-n 5"
LADDER[iter4_blind]="--docking-mode global"
LADDER[boltz_alone]="--starting-structure boltz1 --boltz-seeds 25 --nstruct 1"  # no refinement
LADDER[boltz_refined]="--starting-structure boltz1 --boltz-seeds 25 --pre-relax --refine-top-n 5"

ORDER=(iter0_baseline iter1_prerelax iter2_topN iter3_combined iter4_blind boltz_alone boltz_refined)

# Filter for resume
SKIP=true
RUN_LIST=()
for label in "${ORDER[@]}"; do
    if [[ -z "$RESUME_FROM" || "$label" == "$RESUME_FROM" ]]; then
        SKIP=false
    fi
    [[ "$SKIP" == "false" ]] && RUN_LIST+=("$label")
done

echo "Will run: ${RUN_LIST[*]}"
echo

# ── Submit each iteration as a SLURM job, chained via --dependency ──
PREV_JOB=""
for label in "${RUN_LIST[@]}"; do
    RUN_DIR=$BENCH_RUNS/${DATASET}_${label}
    mkdir -p "$RUN_DIR"
    SCRIPT=$RUN_DIR/job.sh

    cat > "$SCRIPT" <<EOF
#!/bin/bash
#SBATCH --job-name=p2_${label}
#SBATCH --account=PAS2959
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=24:00:00
#SBATCH --output=$RUN_DIR/slurm-%j.out
#SBATCH --error=$RUN_DIR/slurm-%j.err

cd $RUN_DIR
$VENV $BACKEND/benchmark_runner_custom.py \\
    --index $INDEX \\
    --output $RUN_DIR \\
    --nstruct 50 \\
    ${LADDER[$label]}
EOF
    chmod +x "$SCRIPT"

    SBATCH_ARGS=()
    if [[ -n "$PREV_JOB" ]]; then
        SBATCH_ARGS+=(--dependency=afterany:$PREV_JOB)
    fi
    JOB_ID=$(sbatch "${SBATCH_ARGS[@]}" "$SCRIPT" | awk '{print $4}')
    echo "  → submitted $label as job $JOB_ID${PREV_JOB:+ (depends on $PREV_JOB)}"
    PREV_JOB=$JOB_ID
done

# ── Final comparison job ─────────────────────────────────────
FINAL_SCRIPT=$BENCH_RUNS/final_compare_${DATASET}.sh
RUN_LABELS=()
for label in "${RUN_LIST[@]}"; do
    RUN_LABELS+=("${DATASET}_${label}")
done

cat > "$FINAL_SCRIPT" <<EOF
#!/bin/bash
#SBATCH --job-name=p2_final_compare
#SBATCH --account=PAS2959
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --time=00:30:00
#SBATCH --output=$BENCH_RUNS/final_compare_${DATASET}.log

$VENV $BACKEND/compare_runs.py ${RUN_LABELS[*]} --markdown > $BENCH_RUNS/final_table_${DATASET}.md
echo "Comparison table:"
cat $BENCH_RUNS/final_table_${DATASET}.md
EOF
chmod +x "$FINAL_SCRIPT"

FINAL_JOB=$(sbatch --dependency=afterany:$PREV_JOB "$FINAL_SCRIPT" | awk '{print $4}')
echo "  → final compare as job $FINAL_JOB"

echo
echo "=== Pipeline submitted ==="
echo "Watch with: squeue -u $(whoami) -M all"
echo "Final table → $BENCH_RUNS/final_table_${DATASET}.md"
echo
echo "Estimated wall-clock: ~24-48 hrs total (depending on cluster queue)"
