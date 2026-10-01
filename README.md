# icas-bench

Benchmark and analysis scripts for the paper "Challenges of IPC Class-Aware
Scheduling on Raptor Lake Processors in the Linux Kernel".

- `run_battery.sh`: placement and throughput battery (`--oracle-pin` for the pinned oracle)
- `class_sweep.sh`, `class_sweep_power.sh`: per-method P/E throughput, IPC class and ops/joule
- `cps_test.sh`: confirmed classifications per second under SMT
- `analysis/`: statistics and figures
- `docs/methodology.txt`: methodology notes

