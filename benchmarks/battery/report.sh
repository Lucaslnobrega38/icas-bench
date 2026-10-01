#!/bin/bash
# Report generation

generate_report() {
    log "=== RELATÓRIO ==="

    local report="${OUTDIR}/report.txt"
    {
        echo "======================================================"
        echo "  RELATÓRIO — ${KERNEL_TAG}"
        echo "  $(date)"
        echo "======================================================"
        echo ""
        echo "Hardware: $(grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)"
        echo "Kernel:   $(uname -r)"
        echo "Runs:     ${RUNS}"
        echo "P-cores:  ${PCORES}  (${N_PHYSICAL_PCORES} físicos)"
        echo "E-cores:  ${ECORES}"
        echo "Total CPUs: ${TOTAL_CPUS}"
        echo ""

        echo "--- PLACEMENT ---"
        for dir in "${OUTDIR}"/placement/*/; do
            [[ -d "$dir" ]] || continue
            local tag
            tag=$(basename "$dir")
            local cp ce
            cp=$(_mean_std "${dir}/cls2_p_residency.txt")
            ce=$(_mean_std "${dir}/cls1_e_residency.txt")
            echo "  ${tag}: cls2→P=${cp}%  cls1→E=${ce}%"
        done

        echo ""
        echo "======================================================"
    } > "$report"

    cat "$report"
    log "Relatório: ${report}"
}

_mean_std() {
    local file="$1"
    [[ -f "$file" ]] || { echo "NA"; return; }
    awk '
        /^[0-9]/ { sum+=$1; sq+=$1*$1; n++ }
        END {
            if (n>0) {
                m = sum/n
                s = (n>1) ? sqrt((sq - sum*sum/n)/(n-1)) : 0
                printf "%.1f ± %.1f (n=%d)", m, s, n
            } else { print "NA" }
        }
    ' "$file"
}
