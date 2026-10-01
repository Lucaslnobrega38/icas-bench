#!/bin/bash
# Throughput under contention
# Cenário c2_contention: nproc --all/2 cls2 (rand48) + nproc --all/2 cls1 (div16), média por worker cls2.
# --oracle-pin: taskset por tarefa, cls2 nas threads de P-core primeiro.

THROUGHPUT_DIR="${OUTDIR}/throughput"

CLS2_METHOD="rand48"
CLS1_METHOD="div16"
THROUGHPUT_DURATION="${THROUGHPUT_DURATION:-10}"   # 10s é suficiente para estabilizar a vazão
THROUGHPUT_LAUNCH="${THROUGHPUT_LAUNCH:-together}"      # together | bg_first

_bench_throughput() {
    local label="$1" n_cls2="$2" n_cls1="$3"
    local out="${THROUGHPUT_DIR}/${label}"
    mkdir -p "$out"

    local existing=0
    [[ -f "${out}/compute_ops.txt" ]] && existing=$(wc -l < "${out}/compute_ops.txt")
    if [[ "$existing" -ge "$RUNS" ]]; then
        log "  [throughput] ${label} — já completo, pulando"
        return
    fi

    local start_from=$(( existing + 1 ))
    [[ "$existing" -gt 0 ]] && log "  [throughput] ${label} — resumindo do run ${start_from}"
    log "  [throughput] ${label}: ${n_cls2} cls2 + ${n_cls1} cls1 (média por worker cls2), ${THROUGHPUT_DURATION}s, lançamento=${THROUGHPUT_LAUNCH}"

    # Ordem das CPUs para o oráculo: threads dos P-cores, depois E-cores.
    local -a cpu_order=()
    if [[ "${ORACLE_PIN:-0}" == 1 ]]; then
        local -a _p _e
        IFS=',' read -ra _p <<< "$PCORES"
        IFS=',' read -ra _e <<< "$ECORES"
        cpu_order=("${_p[@]}" "${_e[@]}")
    fi

    local i
    for i in $(seq "$start_from" "$RUNS"); do
        local tmp; tmp=$(mktemp -d)
        local pids=() k=0 j=0
        local pin=()

        _launch_cls2() {   # $1 = índice
            pin=()
            [[ "${ORACLE_PIN:-0}" == 1 ]] && pin=(taskset -c "${cpu_order[$(( $1 % ${#cpu_order[@]} ))]}")
            "${pin[@]}" stress-ng --cpu 1 --cpu-method "${CLS2_METHOD}" \
                --timeout "${THROUGHPUT_DURATION}s" --metrics-brief > "${tmp}/c2_$1.txt" 2>&1 &
            pids+=($!)
        }
        _launch_cls1() {   # $1 = índice
            pin=()
            [[ "${ORACLE_PIN:-0}" == 1 ]] && pin=(taskset -c "${cpu_order[$(( (n_cls2 + $1) % ${#cpu_order[@]} ))]}")
            "${pin[@]}" stress-ng --cpu 1 --cpu-method "${CLS1_METHOD}" \
                --timeout "${THROUGHPUT_DURATION}s" --quiet > /dev/null 2>&1 &
            pids+=($!)
        }

        if [[ "$THROUGHPUT_LAUNCH" == bg_first ]]; then
            for (( j = 0; j < n_cls1; j++ )); do _launch_cls1 "$j"; done
            sleep 0.3
            for (( k = 0; k < n_cls2; k++ )); do _launch_cls2 "$k"; done
        else
            k=0; j=0
            while (( k < n_cls2 || j < n_cls1 )); do
                (( k < n_cls2 )) && { _launch_cls2 "$k"; k=$(( k + 1 )); }
                (( j < n_cls1 )) && { _launch_cls1 "$j"; j=$(( j + 1 )); }
            done
        fi

        wait "${pids[@]}" 2>/dev/null || true

        # média (bogo-ops/s, tempo real) dos workers cls2
        local ops
        ops=$(cat "${tmp}"/c2_*.txt 2>/dev/null | awk '/cpu /{s += $9; n++} END{ if (n > 0) printf "%.2f", s / n }')
        rm -rf "$tmp"

        echo "${ops:-NA}" >> "${out}/compute_ops.txt"
        printf "    run %02d/%02d: %s ops/s (média por worker cls2)\n" "$i" "$RUNS" "${ops:-NA}"
    done

    log "  [throughput] ${label} → ${out}/"
}

run_throughput_tests() {
    log "=== FASE 3: THROUGHPUT ==="
    log "  cls2: ${CLS2_METHOD}  |  cls1: ${CLS1_METHOD}"

    local n=$(( TOTAL_CPUS / 2 ))
    log "  Total CPUs (nproc --all): ${TOTAL_CPUS}  →  ${n} cls2 + ${n} cls1"

    # 2× --runs, como o placement.
    local saved_runs="$RUNS"
    RUNS=$(( RUNS * 2 ))
    log "  throughput runs = ${RUNS} (2× --runs), ${THROUGHPUT_DURATION}s cada"

    _bench_throughput "c2_contention" "$n" "$n"

    RUNS="$saved_runs"
    log "Fase 3 concluída → ${THROUGHPUT_DIR}/"
}
