#!/bin/bash
# cps_test.sh: confirmed classifications per second (trace_printk in
# debounce_and_update_class(), filtered by pid) for one method pinned on a P-core,
# with SMT off, SMT with idle sibling, and SMT with busy sibling.
# Usage: sudo ./cps_test.sh [método] [duração_s] [pcore] [sibling_cpu]
#   Padrão: div16, 8s, cpu2 (P-core), cpu3 (irmão SMT de cpu2 no i5-1334U).
set -uo pipefail
[[ $EUID -eq 0 ]] || { echo "rode com sudo"; exit 1; }

METHOD="${1:-div16}"
DUR="${2:-8}"
PCPU="${3:-2}"
SIBCPU="${4:-3}"

TRACE=/sys/kernel/tracing/trace
TRACE_ON=/sys/kernel/tracing/tracing_on
[[ -r "$TRACE" ]] || { TRACE=/sys/kernel/debug/tracing/trace; TRACE_ON=/sys/kernel/debug/tracing/tracing_on; }
[[ -r "$TRACE" ]] || { echo "sem acesso a $TRACE — tracefs não montado ou faltou sudo"; exit 1; }

_count() {
    local label="$1" sibling_busy="$2"
    : > "$TRACE"; echo 1 > "$TRACE_ON"
    taskset -c "$PCPU" stress-ng --cpu 1 --cpu-method "$METHOD" --timeout "${DUR}s" --quiet &
    local launcher=$!
    local sib_launcher=""
    if [[ "$sibling_busy" == "1" ]]; then
        taskset -c "$SIBCPU" stress-ng --cpu 1 --cpu-method "$METHOD" --timeout "${DUR}s" --quiet &
        sib_launcher=$!
    fi
    sleep 0.3
    local worker
    worker=$(pgrep -P "$launcher" | head -1) || true
    [[ -n "$worker" ]] || worker="$launcher"
    wait "$launcher" 2>/dev/null || true
    [[ -n "$sib_launcher" ]] && wait "$sib_launcher" 2>/dev/null
    echo 0 > "$TRACE_ON"
    local n rate
    n=$(grep -cE "IPCC UPDATE: pid=${worker}\b" "$TRACE" 2>/dev/null || echo 0)
    rate=$(awk -v n="$n" -v d="$DUR" 'BEGIN{printf "%.1f", n/d}')
    printf "%-32s pid=%-7s n=%-5d  %s classificações/s\n" "$label" "$worker" "$n" "$rate"
}

echo "=== ${METHOD}, ${DUR}s, P-core=cpu${PCPU}, irmão=cpu${SIBCPU} ==="
echo "SMT original: $(cat /sys/devices/system/cpu/smt/control)"

echo off | sudo -n tee /sys/devices/system/cpu/smt/control >/dev/null
sleep 0.5
echo "--- nosmt (cpu${PCPU} sozinho, cpu${SIBCPU} offline) ---"
_count "nosmt" 0

echo on | sudo -n tee /sys/devices/system/cpu/smt/control >/dev/null
sleep 0.5
echo "--- smt ligado, irmão (cpu${SIBCPU}) ocioso ---"
_count "smt, irmão ocioso" 0
echo "--- smt ligado, irmão (cpu${SIBCPU}) ocupado ---"
_count "smt, irmão ocupado" 1

echo on | sudo -n tee /sys/devices/system/cpu/smt/control >/dev/null
echo "=== SMT final: $(cat /sys/devices/system/cpu/smt/control) ==="
