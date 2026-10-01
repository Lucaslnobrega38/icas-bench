#!/bin/bash
# Hardware checks and isolation

run_preflight() {
    log "=== FASE 0: PREFLIGHT ==="

    [[ $EUID -eq 0 ]] || die "Execute como root (sudo)"

    log "Topologia detectada: P-cores=[${PCORES}] E-cores=[${ECORES}]"

    require stress-ng taskset python3

    # MSR necessário para leituras HFI/ITD
    if [[ ! -c /dev/cpu/0/msr ]]; then
        modprobe msr 2>/dev/null || warn "MSR não disponível — leituras HFI/ITD podem falhar"
    fi

    local cpu_model
    cpu_model=$(grep "model name" /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)
    log "CPU: ${cpu_model}"
    echo "$cpu_model" >> "${OUTDIR}/raw/hw_info.txt"

    local _pcore_arr _ecore_arr
    IFS=',' read -ra _pcore_arr <<< "$PCORES"
    IFS=',' read -ra _ecore_arr <<< "$ECORES"
    for cpu in "${_pcore_arr[@]:0:4}"; do
        local prio
        prio=$(cat /sys/devices/system/cpu/cpu${cpu}/acpi_cppc/highest_perf 2>/dev/null || echo "N/A")
        echo "  CPU${cpu} (P): acpi_highest_perf=${prio}" | tee -a "${OUTDIR}/raw/hw_info.txt"
    done
    for cpu in "${_ecore_arr[@]:0:4}"; do
        local prio
        prio=$(cat /sys/devices/system/cpu/cpu${cpu}/acpi_cppc/highest_perf 2>/dev/null || echo "N/A")
        echo "  CPU${cpu} (E): acpi_highest_perf=${prio}" | tee -a "${OUTDIR}/raw/hw_info.txt"
    done

    log "Prioridades ITMT:"
    local _itmt_sample=("${_pcore_arr[0]}" "${_pcore_arr[1]:-${_pcore_arr[0]}}" "${_ecore_arr[0]}" "${_ecore_arr[1]:-${_ecore_arr[0]}}")
    for cpu in "${_itmt_sample[@]}"; do
        local prio
        prio=$(cat /sys/devices/system/cpu/cpu${cpu}/acpi_cppc/highest_perf 2>/dev/null || echo "N/A")
        echo "  CPU${cpu}: itmt_prio=${prio}" | tee -a "${OUTDIR}/raw/hw_info.txt"
    done
    dmesg 2>/dev/null | grep -i "ITMT support" | tail -1 | tee -a "${OUTDIR}/raw/hw_info.txt" || true

    {
        echo "=== uname ==="
        uname -a
        echo "=== cpuinfo ==="
        cat /proc/cpuinfo
        echo "=== lstopo ==="
        lstopo --of txt 2>/dev/null || true
        echo "=== scheduler features ==="
        cat /sys/kernel/debug/sched/features 2>/dev/null || cat /sys/kernel/debug/sched_features 2>/dev/null || true
        echo "=== HFI/ITD status ==="
        rdmsr -a 0x17d1 2>/dev/null || true   # IA32_HW_FEEDBACK_CONFIG
        rdmsr -a 0x17d4 2>/dev/null || true   # HW_FEEDBACK_THREAD_CONFIG
    } >> "${OUTDIR}/raw/hw_info.txt"

    log "Fixando CPU governor em 'performance'..."
    ORIGINAL_GOVERNOR=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo "unknown")
    echo "$ORIGINAL_GOVERNOR" > "${OUTDIR}/raw/original_governor.txt"

    for cpu_path in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        echo performance > "$cpu_path" 2>/dev/null || true
    done
    log "Governor: ${ORIGINAL_GOVERNOR} → performance"

    # turbo desativado para reduzir variância de frequência
    if [[ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
        cat /sys/devices/system/cpu/intel_pstate/no_turbo > "${OUTDIR}/raw/original_turbo.txt"
        echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo
        log "Intel turbo: desativado"
    fi

    trap _restore_system EXIT

    log "Aquecimento (${WARMUP_SEC}s)..."
    stress-ng --cpu "$(nproc)" --timeout "${WARMUP_SEC}s" --quiet

    log "Preflight concluído."
}

_restore_system() {
    local orig_gov
    orig_gov=$(cat "${OUTDIR}/raw/original_governor.txt" 2>/dev/null || echo "powersave")
    log "Restaurando governor → ${orig_gov}"
    for cpu_path in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        echo "$orig_gov" > "$cpu_path" 2>/dev/null || true
    done

    if [[ -f "${OUTDIR}/raw/original_turbo.txt" ]]; then
        local orig_turbo
        orig_turbo=$(cat "${OUTDIR}/raw/original_turbo.txt")
        echo "$orig_turbo" > /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || true
        log "Intel turbo restaurado."
    fi
}
