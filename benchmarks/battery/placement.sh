#!/bin/bash
# Placement scenarios (relaxed, contention)

PLACEMENT_DIR="${OUTDIR}/placement"
PLACEMENT_DURATION=30

CLS2_METHOD="rand48"
CLS1_METHOD="div16"

_placement_one_run() {
    local n_cls2="$1" n_cls1="$2" duration="$3"
    local out_cls2_p="$4" out_cls1_e="$5"

    local cls2_pids=() cls1_pids=()

    # Oráculo pinado: cada cls2 numa thread lógica própria de P-core; cls1 no resto.
    local pin2=() pin1=() k=0
    for _ in $(seq 1 "$n_cls2"); do
        pin2=()
        [[ "${ORACLE_PIN:-0}" == 1 ]] && \
            pin2=(taskset -c "${P_FIRST_THREADS[$(( k % ${#P_FIRST_THREADS[@]} ))]}")
        "${pin2[@]}" stress-ng --cpu 1 --cpu-method "${CLS2_METHOD}" --timeout "${duration}s" --quiet &
        cls2_pids+=($!)
        k=$(( k + 1 ))
    done
    [[ "${ORACLE_PIN:-0}" == 1 ]] && pin1=(taskset -c "${CLS1_CPUS}")
    for _ in $(seq 1 "$n_cls1"); do
        "${pin1[@]}" stress-ng --cpu 1 --cpu-method "${CLS1_METHOD}" --timeout "${duration}s" --quiet &
        cls1_pids+=($!)
    done

    sleep 1

    local cls2_worker_pids=() cls1_worker_pids=()
    for ppid in "${cls2_pids[@]}"; do
        local children
        children=$(pgrep -P "$ppid" 2>/dev/null) || true
        if [[ -n "$children" ]]; then
            while IFS= read -r c; do cls2_worker_pids+=("$c"); done <<< "$children"
        else
            cls2_worker_pids+=("$ppid")
        fi
    done
    for ppid in "${cls1_pids[@]}"; do
        local children
        children=$(pgrep -P "$ppid" 2>/dev/null) || true
        if [[ -n "$children" ]]; then
            while IFS= read -r c; do cls1_worker_pids+=("$c"); done <<< "$children"
        else
            cls1_worker_pids+=("$ppid")
        fi
    done

    local tmp_samples
    tmp_samples=$(mktemp)
    local deadline=$(( $(date +%s) + duration - 1 ))
    (
        while [[ $(date +%s) -lt $deadline ]]; do
            for pid in "${cls2_worker_pids[@]}"; do
                local cpu
                cpu=$(ps -p "$pid" -o psr= 2>/dev/null | tr -d ' ') || continue
                [[ "$cpu" =~ ^[0-9]+$ ]] && echo "cls2 $cpu"
            done
            for pid in "${cls1_worker_pids[@]}"; do
                local cpu
                cpu=$(ps -p "$pid" -o psr= 2>/dev/null | tr -d ' ') || continue
                [[ "$cpu" =~ ^[0-9]+$ ]] && echo "cls1 $cpu"
            done
            sleep 0.1
        done
    ) > "$tmp_samples" &
    local poll_pid=$!

    wait "${cls2_pids[@]}" "${cls1_pids[@]}" 2>/dev/null || true
    kill "$poll_pid" 2>/dev/null || true
    wait "$poll_pid" 2>/dev/null || true

    awk -v pcores="${PCORES}" -v out2="${out_cls2_p}" -v out1="${out_cls1_e}" '
    BEGIN {
        n = split(pcores, pa, ",")
        for (k = 1; k <= n; k++) p[pa[k]] = 1
    }
    $1 == "cls2" { total2++; if ($2 in p) p2++ }
    $1 == "cls1" { total1++; if (!($2 in p)) e1++ }
    END {
        if (total2 > 0) printf "%.2f\n", 100*p2/total2  > out2
        else            print "NA"                        > out2
        if (total1 > 0) printf "%.2f\n", 100*e1/total1  > out1
        else            print "NA"                        > out1
    }
    ' "$tmp_samples"

    rm -f "$tmp_samples"
}

_run_placement_scenario() {
    local label="$1" n_cls2="$2" n_cls1="$3"
    local out="${PLACEMENT_DIR}/${label}"
    mkdir -p "$out"

    local existing=0
    [[ -f "${out}/cls2_p_residency.txt" ]] && existing=$(wc -l < "${out}/cls2_p_residency.txt")
    if [[ "$existing" -ge "$RUNS" ]]; then
        log "  [placement] ${label} — já completo (${existing} runs), pulando"
        return
    fi

    local start_from=$(( existing + 1 ))
    [[ "$existing" -gt 0 ]] && log "  [placement] ${label} — resumindo do run ${start_from}"
    log "  [placement] ${label}: ${n_cls2} cls2(${CLS2_METHOD}) + ${n_cls1} cls1(${CLS1_METHOD}) × ${RUNS} runs"

    local tmp_cls2p tmp_cls1e
    tmp_cls2p=$(mktemp)
    tmp_cls1e=$(mktemp)

    for i in $(seq "$start_from" "$RUNS"); do
        _placement_one_run "$n_cls2" "$n_cls1" "$PLACEMENT_DURATION" \
            "$tmp_cls2p" "$tmp_cls1e"

        cat "$tmp_cls2p" >> "${out}/cls2_p_residency.txt"
        cat "$tmp_cls1e" >> "${out}/cls1_e_residency.txt"

        local cp ce
        cp=$(cat "$tmp_cls2p"); ce=$(cat "$tmp_cls1e")
        printf "    run %02d/%02d: cls2→P=%s%%  cls1→E=%s%%\n" "$i" "$RUNS" "$cp" "$ce"
    done

    rm -f "$tmp_cls2p" "$tmp_cls1e"
    log "  [placement] ${label}: ${RUNS} runs → ${out}/"
}

run_placement_tests() {
    log "=== FASE 1: PLACEMENT ==="
    log "  cls2: ${CLS2_METHOD}  |  cls1: ${CLS1_METHOD}"
    log "  P-cores físicos: ${N_PHYSICAL_PCORES}  |  Total CPUs: ${TOTAL_CPUS}"

    local n_bg=$(( TOTAL_CPUS - N_PHYSICAL_PCORES ))

    # Placement usa 2× --runs para capturar maior variabilidade de scheduling
    local saved_runs="$RUNS"
    RUNS=$(( RUNS * 2 ))
    log "  placement runs = ${RUNS} (2× --runs)"

    _run_placement_scenario "relaxed"    "${N_PHYSICAL_PCORES}" "${N_PHYSICAL_PCORES}"
    _run_placement_scenario "contention" "${N_PHYSICAL_PCORES}" "${n_bg}"

    RUNS="$saved_runs"

    python3 "${SCRIPT_DIR}/analysis/placement_accuracy.py" \
        --input "${PLACEMENT_DIR}" \
        --pcores "${PCORES}" \
        --output "${PLACEMENT_DIR}/placement_summary.csv" \
        || warn "Script de análise de placement falhou"

    log "Fase 1 concluída → ${PLACEMENT_DIR}/"
}
