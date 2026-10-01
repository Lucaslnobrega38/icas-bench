#!/bin/bash
# class_sweep_power.sh: ops/joule per method, P-core vs E-core, via RAPL.
# RAPL measures the whole package (cores + uncore), not only the pinned CPU
# (see docs/methodology.txt).
# Usage: sudo ./class_sweep_power.sh <tag> [método ...]
#   PCPU/ECPU (env, default 0/8): sudo env PCPU=2 ECPU=11 ./class_sweep_power.sh <tag>
#   RAPL_DOMAIN (env, default intel-rapl:0 = pacote inteiro)
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "rode com sudo"; exit 1; }

TAG="${1:?uso: sudo ./class_sweep_power.sh <tag> [metodo ...]}"
shift || true
DUR=5
PCPU="${PCPU:-0}"
ECPU="${ECPU:-8}"
RAPL_DOMAIN="${RAPL_DOMAIN:-intel-rapl:0}"
ENERGY="/sys/class/powercap/${RAPL_DOMAIN}/energy_uj"
MAXRANGE="/sys/class/powercap/${RAPL_DOMAIN}/max_energy_range_uj"

[[ -r "$ENERGY" ]] || { echo "sem acesso a $ENERGY — RAPL indisponível ou faltou sudo"; exit 1; }
MAX_UJ=$(cat "$MAXRANGE" 2>/dev/null || echo 0)

# move threads off PCPU/ECPU (same as class_sweep.sh)
declare -A _orig_affinity
_clear_cpu() {
    local cpu="$1" pid mask
    for pid in $(ps -eLo psr,lwp --no-headers | awk -v c="$cpu" '$1==c{print $2}' | sort -u); do
        [[ -d "/proc/$pid" ]] || continue
        mask=$(taskset -p "$pid" 2>/dev/null | awk -F': ' '{print $2}') || continue
        [[ -n "$mask" ]] || continue
        _orig_affinity[$pid]="$mask"
        taskset -p "$((0xffffffff & ~(1<<cpu)))" "$pid" &>/dev/null || true
    done
}
_restore_affinity() {
    local pid
    for pid in "${!_orig_affinity[@]}"; do
        [[ -d "/proc/$pid" ]] && taskset -p "${_orig_affinity[$pid]}" "$pid" &>/dev/null || true
    done
}
echo "Esvaziando cpu${PCPU} e cpu${ECPU}..."
_clear_cpu "$PCPU"
_clear_cpu "$ECPU"

if [[ $# -gt 0 ]]; then
    METHODS=("$@")
else
    mapfile -t METHODS < <(stress-ng --cpu-method list 2>&1 \
        | sed 's/.*choices are: //' | tr ' ' '\n' | sed '/^$/d' | grep -v '^all$')
fi

OUT="$(cd "$(dirname "$0")" && pwd)/results/${TAG}/class_sweep_power"
mkdir -p "$OUT"
SUMMARY="${OUT}/summary.csv"
[[ -f "$SUMMARY" ]] || echo "method,core,ops_s,energy_j,ops_per_joule" > "$SUMMARY"

declare -A old_gov
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    v=$(cat "$g" 2>/dev/null) || continue
    old_gov[$g]="$v"
    echo performance > "$g" 2>/dev/null || true
done
NT=/sys/devices/system/cpu/intel_pstate/no_turbo
old_nt=$(cat "$NT" 2>/dev/null || echo "")
[[ -n "$old_nt" ]] && echo 1 > "$NT"
restore() {
    for g in "${!old_gov[@]}"; do echo "${old_gov[$g]}" > "$g" 2>/dev/null || true; done
    [[ -n "$old_nt" ]] && echo "$old_nt" > "$NT"
    _restore_affinity
}
trap restore EXIT

_energy_delta_j() {   # $1=antes(uJ) $2=depois(uJ) -> joules, corrigindo wraparound
    local a="$1" b="$2"
    if (( b < a )) && [[ "$MAX_UJ" -gt 0 ]]; then
        echo "scale=6; (${b} + ${MAX_UJ} - ${a}) / 1000000" | bc
    else
        echo "scale=6; (${b} - ${a}) / 1000000" | bc
    fi
}

_run_one() {
    local method="$1" name="$2" cpu="$3"
    local ops tmp e0 e1 ej opj
    tmp=$(mktemp)
    e0=$(cat "$ENERGY")
    taskset -c "$cpu" stress-ng --cpu 1 --cpu-method "$method" \
        --timeout "${DUR}s" --metrics-brief > "$tmp" 2>&1 || true
    e1=$(cat "$ENERGY")
    ops=$(awk '/cpu /{print $9}' "$tmp")
    rm -f "$tmp"
    ej=$(_energy_delta_j "$e0" "$e1")
    if [[ -n "${ops:-}" ]] && awk "BEGIN{exit !($ej > 0)}"; then
        opj=$(echo "scale=3; ${ops} * ${DUR} / ${ej}" | bc)
    else
        opj="NA"
    fi
    echo "${method},${name},${ops:-NA},${ej},${opj}" >> "$SUMMARY"
    printf "  %-16s %s: %8s ops/s  %6s J  %10s ops/J\n" "$method" "$name" "${ops:-NA}" "$ej" "$opj"
}

echo "=== class_sweep_power: ${#METHODS[@]} métodos, ${DUR}s cada, P=cpu${PCPU} E=cpu${ECPU}, domínio=${RAPL_DOMAIN} ==="
for m in "${METHODS[@]}"; do
    _run_one "$m" p "$PCPU"
    _run_one "$m" e "$ECPU"
done

echo "=== concluído → ${SUMMARY} ==="
