#!/usr/bin/env python3
"""
analysis/compare.py — Comparação de N kernels scheduler
Lê os arquivos reais de resultado e produz:
  - results/comparison/report.txt   : tabela texto com t-test
  - results/comparison/plots/       : gráficos PNG/PDF

Métricas:
  - Placement : cls2→P-cores / cls1→E-cores (cenários: relaxed, mixed)
  - Latência  : schbench baseline (p50/p90/p99/p99.9)
  - Throughput+Energia : c2_alone, c2_bg10 (ops/s, ops/J, W, J)

Uso:
    python3 analysis/compare.py --kernels vanilla,asym_packing,ipcc
    python3 analysis/compare.py --a vanilla --b ipcc
"""

import argparse
import csv
import math
import os
import re
import sys
from pathlib import Path

try:
    import numpy as np
    import scipy.stats as sci
    HAS_STATS = True
except ImportError:
    HAS_STATS = False
    print("[WARN] scipy não encontrado — p-values indisponíveis")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_PLOT = True
except ImportError:
    HAS_PLOT = False
    print("[WARN] matplotlib não encontrado — sem gráficos")

_PALETTE = ["#4878CF", "#D65F5F", "#6ACC65", "#E78AC3", "#FDB863"]

def kernel_color(i):
    return _PALETTE[i % len(_PALETTE)]


# ─── estatísticas ─────────────────────────────────────────────────────────────

def mean(v):
    return sum(v) / len(v) if v else None

def std(v):
    if len(v) < 2:
        return 0.0
    m = mean(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))

def welch(a, b):
    if not HAS_STATS or len(a) < 3 or len(b) < 3:
        return None, None
    _, p = sci.ttest_ind(a, b, equal_var=False)
    return p, p < 0.05

def load_numeric(path):
    vals = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and line != "NA":
                    try:
                        vals.append(float(line))
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    return vals


# ─── loaders ──────────────────────────────────────────────────────────────────

def load_schbench(base):
    """Latência: apenas schbench (baseline)."""
    result = {}
    lat = Path(base) / "latency"
    if not lat.exists():
        return result
    for d in sorted(lat.glob("schbench_*")):
        tag = d.name.replace("schbench_", "")
        pfile = d / "percentiles.csv"
        if not pfile.exists():
            continue
        cols = {}
        with open(pfile) as f:
            reader = csv.DictReader(f)
            for row in reader:
                for col in ["p50", "p90", "p99", "p99.9"]:
                    try:
                        cols.setdefault(col, []).append(float(row[col]))
                    except (KeyError, ValueError):
                        pass
        if cols:
            result[tag] = cols
    return result


def load_throughput(base):
    """Throughput + energia (integrados no mesmo diretório).

    Retorna: {label: {'ops': [...], 'pkg_j': [...], 'pkg_w': [...], 'ops_per_j': [...]}}
    """
    result = {}
    thr = Path(base) / "throughput"
    if not thr.exists():
        return result
    for d in sorted(thr.iterdir()):
        if not d.is_dir():
            continue
        entry = {
            "ops":       load_numeric(d / "compute_ops.txt"),
            "pkg_j":     load_numeric(d / "pkg_joules.txt"),
            "pkg_w":     load_numeric(d / "pkg_watt_avg.txt"),
            "ops_per_j": load_numeric(d / "ops_per_joule.txt"),
        }
        if any(entry.values()):
            result[d.name] = entry
    return result


def load_placement(base):
    """Placement: cenários relaxed, mixed (cls2→P%, cls1→E%)."""
    result = {}
    pl_dir = Path(base) / "placement"
    if not pl_dir.exists():
        return result

    for scenario_dir in sorted(pl_dir.iterdir()):
        if not scenario_dir.is_dir():
            continue
        label = scenario_dir.name

        cls2_p = load_numeric(scenario_dir / "cls2_p_residency.txt")
        cls1_e = load_numeric(scenario_dir / "cls1_e_residency.txt")
        if not cls2_p and not cls1_e:
            continue

        entry = {
            "cls2_p": cls2_p,
            "cls1_e": cls1_e,
            "cls2_p_residency": mean(cls2_p) if cls2_p else None,
            "cls1_e_residency": mean(cls1_e) if cls1_e else None,
        }
        result[label] = entry
    return result


# ─── formatação N-kernels ──────────────────────────────────────────────────────

def fmt(v, decimals=2):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"

def delta_str(base_val, cmp_val, lower_is_better=True):
    if base_val is None or cmp_val is None or base_val == 0:
        return "—"
    d = 100 * (cmp_val - base_val) / base_val
    arrow = "▼" if (d < 0) == lower_is_better else "▲"
    return f"{arrow}{abs(d):.1f}%"

def sig_str(p):
    if p is None:
        return "n/a"
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "** "
    if p < 0.05:
        return "*  "
    return "ns "

_W_NAME   = 26
_W_VAL    = 12
_W_DELTA  =  8
_W_SIG    =  4

def _header(lines, names):
    vals  = "".join(f" {n[:_W_VAL]:>{_W_VAL}}" for n in names)
    deltas = "".join(f"  {'Δ%→'+n[:6]:>{_W_DELTA}}  {'sig':>{_W_SIG}}" for n in names[1:])
    lines.append(f"  {'Benchmark':<{_W_NAME}}{vals}{deltas}")
    sep_w = _W_NAME + len(names) * (_W_VAL + 1) + (len(names) - 1) * (_W_DELTA + _W_SIG + 4)
    lines.append("  " + "─" * sep_w)

def _row(lines, name, data_list, decimals=2, lower_is_better=True, unit=""):
    base = data_list[0]
    mb = mean(base)
    suffix = f" {unit}" if unit else ""
    vals = f" {fmt(mb, decimals):>{_W_VAL}}{suffix}"
    for vals_k in data_list[1:]:
        mk = mean(vals_k)
        vals += f" {fmt(mk, decimals):>{_W_VAL}}{suffix}"
    deltas = ""
    for vals_k in data_list[1:]:
        mk = mean(vals_k)
        ds = delta_str(mb, mk, lower_is_better)
        p, _ = welch(base, vals_k)
        ss = sig_str(p)
        deltas += f"  {ds:>{_W_DELTA}}  {ss:>{_W_SIG}}"
    lines.append(f"  {name:<{_W_NAME}}{vals}{deltas}")


# ─── relatório ────────────────────────────────────────────────────────────────

def section(lines, title):
    lines.append("")
    lines.append("═" * 80)
    lines.append(f"  {title}")
    lines.append("═" * 80)


def build_report(kernels):
    names = [k[0] for k in kernels]
    dirs  = [k[1] for k in kernels]

    lines = []
    lines.append("╔" + "═" * 78 + "╗")
    title = "COMPARAÇÃO: " + " vs ".join(n.upper() for n in names)
    lines.append(f"║  {title:<76}║")
    lines.append("╚" + "═" * 78 + "╝")
    for i, (n, d) in enumerate(kernels):
        lines.append(f"  {'baseline' if i==0 else f'kernel {i}'} = {n} ({d})")
    lines.append(f"  Δ% = (X−baseline)/baseline×100  |  sig: *** p<0.001  ** p<0.01  * p<0.05  ns")

    # ── 1. Placement ────────────────────────────────────────────────────────
    pls = [load_placement(d) for d in dirs]
    all_pl_labels = sorted(set(l for pl in pls for l in pl))

    section(lines, "1. PLACEMENT — residência nos P/E-cores por tipo de tarefa (%, maior é melhor)")

    col_w = 9
    hdr = f"  {'Cenário':<20}"
    for name in names:
        hdr += f" {'cls2→P%':>{col_w}} {'cls1→E%':>{col_w}}"
    hdr += f"  {'ΔP%':>7}  {'sig':>4}  {'ΔE%':>7}  {'sig':>4}" * (len(names) - 1)
    lines.append(hdr)
    sep = 20 + len(names) * (col_w * 2 + 3) + (len(names) - 1) * 28
    lines.append("  " + "─" * sep)

    for label in all_pl_labels:
        line = f"  {label:<20}"
        cp_arrays, ce_arrays = [], []
        cp_means,  ce_means  = [], []
        for pl in pls:
            r  = pl.get(label, {})
            cp = r.get("cls2_p_residency")
            ce = r.get("cls1_e_residency")
            cp_arrays.append(r.get("cls2_p", []))
            ce_arrays.append(r.get("cls1_e", []))
            cp_means.append(cp)
            ce_means.append(ce)
            line += f" {fmt(cp, 1):>{col_w}} {fmt(ce, 1):>{col_w}}"

        base_cp, base_ce = cp_means[0], ce_means[0]
        base_cp_arr, base_ce_arr = cp_arrays[0], ce_arrays[0]
        for cp_v, ce_v, cp_arr, ce_arr in zip(
                cp_means[1:], ce_means[1:], cp_arrays[1:], ce_arrays[1:]):
            dcp = f"{100*(cp_v-base_cp)/base_cp:+.1f}%" if base_cp and cp_v else "—"
            dce = f"{100*(ce_v-base_ce)/base_ce:+.1f}%" if base_ce and ce_v else "—"
            pp, _ = welch(base_cp_arr, cp_arr)
            pe, _ = welch(base_ce_arr, ce_arr)
            line += f"  {dcp:>7}  {sig_str(pp):>4}  {dce:>7}  {sig_str(pe):>4}"
        lines.append(line)

    # Distribuição por cenário (com std, melhor, pior)
    for pl_label in all_pl_labels:
        max_n = max(
            max(len(pl.get(pl_label, {}).get("cls2_p", [])),
                len(pl.get(pl_label, {}).get("cls1_e", [])))
            for pl in pls
        ) if pls else 0
        if max_n == 0:
            continue

        lines.append("")
        lines.append(f"  Distribuição {pl_label} ({max_n} runs) — cls2→P-cores e cls1→E-cores:")
        hdr2 = f"  {'kernel':<20}  {'cls2→P mean':>12}  {'±std':>6}  {'melhor':>8}  {'pior':>8}"
        hdr2 += f"  {'cls1→E mean':>12}  {'±std':>6}  {'melhor':>8}  {'pior':>8}  {'n':>4}"
        lines.append(hdr2)
        lines.append("  " + "─" * (len(hdr2) - 2))
        for name, pl in zip(names, pls):
            r  = pl.get(pl_label, {})
            cp = r.get("cls2_p", [])
            ce = r.get("cls1_e", [])
            if not cp and not ce:
                lines.append(f"  {name:<20}  sem dados")
                continue
            def _s(v): return f"{mean(v):5.1f}%" if v else "—"
            def _sd(v): return f"{std(v):.1f}"   if len(v) > 1 else "—"
            def _mx(v): return f"{max(v):5.1f}%" if v else "—"
            def _mn(v): return f"{min(v):5.1f}%" if v else "—"
            n = max(len(cp), len(ce))
            lines.append(
                f"  {name:<20}  {_s(cp):>12}  {_sd(cp):>6}  {_mx(cp):>8}  {_mn(cp):>8}"
                f"  {_s(ce):>12}  {_sd(ce):>6}  {_mx(ce):>8}  {_mn(ce):>8}  {n:>4}"
            )

    # ── 2. Latência schbench ─────────────────────────────────────────────────
    section(lines, "2. LATÊNCIA DE WAKEUP — schbench (μs, menor é melhor)")
    _header(lines, names)
    schbs = [load_schbench(d) for d in dirs]
    all_tags = sorted(set(t for s in schbs for t in s))
    for tag in all_tags:
        for pname in ["p50", "p90", "p99", "p99.9"]:
            data_list = [s.get(tag, {}).get(pname, []) for s in schbs]
            if any(data_list):
                _row(lines, f"  {tag}/{pname}", data_list, decimals=0,
                     lower_is_better=True, unit="μs")

    # ── 3. Throughput ─────────────────────────────────────────────────────────
    thrs = [load_throughput(d) for d in dirs]
    all_thr_labels = sorted(set(l for t in thrs for l in t))

    section(lines, "3. THROUGHPUT (bogo-ops/s, maior é melhor)")
    _header(lines, names)
    for label in all_thr_labels:
        data_list = [t.get(label, {}).get("ops", []) for t in thrs]
        if any(data_list):
            _row(lines, f"  {label}", data_list, decimals=0,
                 lower_is_better=False, unit="ops/s")

    # ── 4. Eficiência energética ─────────────────────────────────────────────
    section(lines, "4. EFICIÊNCIA — ops/Joule (maior é melhor)")
    _header(lines, names)
    for label in all_thr_labels:
        data_list = [t.get(label, {}).get("ops_per_j", []) for t in thrs]
        if any(data_list):
            _row(lines, f"  {label}", data_list, decimals=1,
                 lower_is_better=False, unit="ops/J")

    section(lines, "4b. POTÊNCIA MÉDIA — Watt (menor é melhor)")
    _header(lines, names)
    for label in all_thr_labels:
        data_list = [t.get(label, {}).get("pkg_w", []) for t in thrs]
        if any(data_list):
            _row(lines, f"  {label}", data_list, decimals=2,
                 lower_is_better=True, unit="W")

    section(lines, "4c. ENERGIA TOTAL — Joules por run (menor é melhor)")
    _header(lines, names)
    for label in all_thr_labels:
        data_list = [t.get(label, {}).get("pkg_j", []) for t in thrs]
        if any(data_list):
            _row(lines, f"  {label}", data_list, decimals=2,
                 lower_is_better=True, unit="J")

    lines.append("")
    lines.append("═" * 80)
    lines.append("  LEGENDA")
    lines.append("  Δ%: (X−baseline)/baseline×100  ▼=menor  ▲=maior")
    lines.append("  sig: *** p<0.001  ** p<0.01  * p<0.05  ns=não significativo")
    lines.append("═" * 80)

    return lines


# ─── gráficos ─────────────────────────────────────────────────────────────────

def _bar_n(ax, tags, data_per_kernel, names, ylabel, title, lower_is_better=True):
    n = len(names)
    w = 0.8 / n
    x = range(len(tags))
    for i, (vals_per_tag, name) in enumerate(zip(data_per_kernel, names)):
        means = [mean(v) if v else 0 for v in vals_per_tag]
        stds  = [std(v)  if v else 0 for v in vals_per_tag]
        offset = (i - n/2 + 0.5) * w
        ax.bar([xi + offset for xi in x], means, w, yerr=stds,
               capsize=3, label=name, alpha=0.85, color=kernel_color(i))
    ax.set_xticks(list(x))
    ax.set_xticklabels(tags, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.legend(fontsize=8)
    ax.grid(True, axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def generate_plots(kernels, out_dir):
    if not HAS_PLOT:
        print("[plots] matplotlib não disponível, pulando gráficos")
        return

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    names = [k[0] for k in kernels]
    dirs  = [k[1] for k in kernels]

    # ── Fig 1: placement residency ──────────────────────────────────────────
    pls = [load_placement(d) for d in dirs]
    pl_labels = sorted(set(l for pl in pls for l in pl))
    if pl_labels:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        for ax, key, ylabel, title in [
            (axes[0], "cls2_p_residency", "% tempo nos P-cores", "cls2 (vector) → P-cores"),
            (axes[1], "cls1_e_residency", "% tempo nos E-cores", "cls1 (integer) → E-cores"),
        ]:
            n = len(names)
            w = 0.8 / n
            x = range(len(pl_labels))
            for i, (pl, name) in enumerate(zip(pls, names)):
                vals = [pl.get(l, {}).get(key) or 0 for l in pl_labels]
                offset = (i - n/2 + 0.5) * w
                ax.bar([xi + offset for xi in x], vals, w,
                       label=name, alpha=0.85, color=kernel_color(i))
            ax.axhline(50, color="gray", linestyle="--", linewidth=1, alpha=0.5)
            ax.set_xticks(list(x))
            ax.set_xticklabels(pl_labels)
            ax.set_ylabel(ylabel, fontsize=9)
            ax.set_title(title, fontsize=10, fontweight="bold")
            ax.set_ylim(0, 105)
            ax.legend(fontsize=8)
            ax.grid(True, axis="y", alpha=0.3)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
        plt.tight_layout()
        plt.savefig(f"{out_dir}/placement_residency.pdf", dpi=150)
        plt.savefig(f"{out_dir}/placement_residency.png", dpi=150)
        plt.close()
        print(f"[plots] placement_residency → {out_dir}/")

    # ── Fig 2: schbench percentis ───────────────────────────────────────────
    schbs = [load_schbench(d) for d in dirs]
    all_tags = sorted(set(t for s in schbs for t in s))
    if all_tags:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        for ax, pct, title in [
            (axes[0], "p99",   "schbench — p99 Wakeup Latency"),
            (axes[1], "p99.9", "schbench — p99.9 Wakeup Latency"),
        ]:
            data_per_kernel = [
                [s.get(t, {}).get(pct, []) for t in all_tags]
                for s in schbs
            ]
            _bar_n(ax, all_tags, data_per_kernel, names,
                   f"{pct} latency (μs)", title, lower_is_better=True)
        plt.tight_layout()
        plt.savefig(f"{out_dir}/schbench.pdf", dpi=150)
        plt.savefig(f"{out_dir}/schbench.png", dpi=150)
        plt.close()
        print(f"[plots] schbench → {out_dir}/")

    # ── Fig 3: throughput + energia ─────────────────────────────────────────
    thrs = [load_throughput(d) for d in dirs]
    thr_labels = sorted(set(l for t in thrs for l in t))
    if thr_labels:
        fig, axes = plt.subplots(2, 2, figsize=(13, 9))

        # ops/s
        _bar_n(axes[0][0], thr_labels,
               [[t.get(l, {}).get("ops", []) for l in thr_labels] for t in thrs],
               names, "ops/s", "Throughput (bogo-ops/s)", lower_is_better=False)

        # ops/J
        _bar_n(axes[0][1], thr_labels,
               [[t.get(l, {}).get("ops_per_j", []) for l in thr_labels] for t in thrs],
               names, "ops/J", "Eficiência (ops/Joule)", lower_is_better=False)

        # Watt médio
        _bar_n(axes[1][0], thr_labels,
               [[t.get(l, {}).get("pkg_w", []) for l in thr_labels] for t in thrs],
               names, "W", "Potência Média (pkg)", lower_is_better=True)

        # Joules totais
        _bar_n(axes[1][1], thr_labels,
               [[t.get(l, {}).get("pkg_j", []) for l in thr_labels] for t in thrs],
               names, "J", "Energia Total por run (pkg)", lower_is_better=True)

        plt.tight_layout()
        plt.savefig(f"{out_dir}/throughput_energia.pdf", dpi=150)
        plt.savefig(f"{out_dir}/throughput_energia.png", dpi=150)
        plt.close()
        print(f"[plots] throughput_energia → {out_dir}/")


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Compara N kernels scheduler")
    parser.add_argument("--base",    default="./results",
                        help="Diretório base de resultados")
    parser.add_argument("--kernels", default=None,
                        help="Lista de kernels separada por vírgula (ex: vanilla,asym_packing,ipcc)")
    parser.add_argument("--a",       default="vanilla",
                        help="Kernel baseline (compatibilidade 2-kernels)")
    parser.add_argument("--b",       default="ipcc",
                        help="Kernel comparado (compatibilidade 2-kernels)")
    parser.add_argument("--out",     default=None,
                        help="Diretório de saída (padrão: base/comparison)")
    args = parser.parse_args()

    base = Path(args.base)

    if args.kernels:
        kernel_names = [k.strip() for k in args.kernels.split(",")]
    else:
        kernel_names = [args.a, args.b]

    kernels = []
    for name in kernel_names:
        d = base /name
        if not d.exists():
            print(f"[ERRO] diretório não encontrado: {d}", file=sys.stderr)
            sys.exit(1)
        kernels.append((name, d))

    out_dir = Path(args.out) if args.out else base / "comparison"
    plots_dir = out_dir / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[compare] kernels: {' vs '.join(k[0] for k in kernels)}")
    print(f"[compare] saída em: {out_dir}")

    lines = build_report(kernels)
    report_path = out_dir / "report.txt"
    with open(report_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n[compare] relatório: {report_path}")
    print("\n".join(lines))

    generate_plots(kernels, str(plots_dir))


if __name__ == "__main__":
    main()
