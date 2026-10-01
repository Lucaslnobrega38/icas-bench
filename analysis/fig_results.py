#!/usr/bin/env python3
"""
analysis/fig_results.py — figura compacta de resultados (substitui a tabela de placement/vazão).

Cada ponto é UMA corrida; a barra é a média; o rótulo dá Δ% de `icas` sobre `asym_packing`.
Linhas = plataformas; colunas = métricas (placement relaxed/contention, vazão alone/contention).

Uso:
    python3 analysis/fig_results.py \
        --platform "i5-1334U=i5/vanilla_smt,i5/orig_smt" \
        --platform "i9-14900HX=i9/vanilla,i9/orig_smt" --out results-strip.pdf
"""

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    sys.exit("matplotlib é necessário: pip install matplotlib numpy")

# (arquivo relativo, título curto, é porcentagem?)
METRICS = [
    ("placement/relaxed/cls2_p_residency.txt",       "cls2→P", True,  "Relaxed"),
    ("placement/relaxed/cls1_e_residency.txt",       "cls1→E", True,  "Relaxed"),
    ("placement/contention/cls2_p_residency.txt",    "cls2→P", True,  "Contention"),
    ("placement/contention/cls1_e_residency.txt",    "cls1→E", True,  "Contention"),
    ("throughput/c2_contention/compute_ops.txt",     "contention", False, "Throughput (ops/s)"),
]
# same palette as smt_compare.py
COLOR = {"asym": "#2a78d6", "icas": "#eb6834", "pinned": "#1baf7a"}


def load(path):
    vals = []
    if not Path(path).exists():
        return np.array(vals)
    for line in Path(path).read_text().split("\n"):
        try:
            vals.append(float(line.strip()))
        except ValueError:
            pass                                   # NA / linha vazia
    return np.array(vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", action="append", required=True,
                    help='"nome=dir_asym,dir_icas[,dir_pinned]" relativo a --base (o 3º, opcional, é o oráculo pinado)')
    ap.add_argument("--base", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--out", default="results-strip.pdf")
    ap.add_argument("--width", type=float, default=7.16, help="polegadas (7.16 = 2 colunas IEEE)")
    ap.add_argument("--panel-height", type=float, default=0.74)
    ap.add_argument("--fontsize", type=float, default=6.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--only-throughput", action="store_true",
                    help="só a coluna de vazão (para o oráculo: placement dele é 100%% por construção, sem graça de plotar)")
    args = ap.parse_args()

    global METRICS
    if args.only_throughput:
        METRICS = [m for m in METRICS if "throughput" in m[0]]

    plt.rcParams.update({"font.size": args.fontsize, "axes.labelsize": args.fontsize,
                         "xtick.labelsize": args.fontsize, "ytick.labelsize": args.fontsize - 0.5})
    rng = np.random.default_rng(args.seed)
    n_rows, n_cols = len(args.platform), len(METRICS)
    top, bottom, gap = 0.34, 0.30, 0.30
    fig_h = n_rows * args.panel_height + top + bottom + gap * (n_rows - 1)
    fig, axes = plt.subplots(n_rows, n_cols, squeeze=False, figsize=(args.width, fig_h),
                             gridspec_kw={"hspace": gap / args.panel_height, "wspace": 0.6})
    fig.subplots_adjust(left=0.05, right=0.995, top=1 - top / fig_h, bottom=bottom / fig_h)

    for r, spec in enumerate(args.platform):
        name, _, dirs = spec.partition("=")
        dl = [Path(args.base) / x for x in dirs.split(",")]
        d_asym, d_icas = dl[0], dl[1]
        d_pin = dl[2] if len(dl) > 2 else None
        for c, (rel, title, is_pct, group) in enumerate(METRICS):
            ax = axes[r, c]
            a, b = load(d_asym / rel), load(d_icas / rel)
            if len(a) == 0 or len(b) == 0:          # dados ainda não coletados (ex.: vazão refeita)
                ax.set_xticks([]); ax.set_yticks([])
                ax.text(0.5, 0.5, "data\npending", transform=ax.transAxes, ha="center", va="center",
                        fontsize=args.fontsize, color="#777777")
                for s in ("top", "right"):
                    ax.spines[s].set_visible(False)
                if r == 0:
                    ax.set_title(title, pad=2.5, fontsize=args.fontsize)
                if c == 0:
                    ax.set_ylabel(name, labelpad=1.5, fontweight="bold")
                continue
            groups = [(a, "asym"), (b, "icas")]
            # oráculo só na vazão: placement dele é 100% por construção
            if d_pin is not None and not is_pct:
                groups.append((load(d_pin / rel), "pinned"))
            for x, (vals, key) in enumerate(groups):
                jitter = rng.uniform(-0.28, 0.28, len(vals))
                ax.scatter(x + jitter, vals, s=1.6, c=COLOR[key], alpha=0.45, linewidths=0, rasterized=True)
                ax.hlines(vals.mean(), x - 0.36, x + 0.36, colors="black", lw=1.1, zorder=3)
            delta = (b.mean() - a.mean()) / a.mean() * 100
            ax.set_xlim(-0.6, len(groups) - 0.4)
            ax.set_xticks(range(len(groups)))
            ax.set_xticklabels([k for _, k in groups])
            ax.tick_params(length=1.5, pad=1)
            if is_pct:
                ax.set_ylim(-4, 104)
                ax.set_yticks([0, 50, 100])
            else:
                allv = np.concatenate([v for v, _ in groups if len(v)])
                lo, hi = allv.min(), allv.max()
                pad = (hi - lo) * 0.12 or 1
                ax.set_ylim(lo - pad, hi + pad * 1.6)
                ax.yaxis.set_major_locator(plt.MaxNLocator(3))
                ax.ticklabel_format(axis="y", style="plain", useOffset=False)
            ax.set_xlabel(f"{delta:+.1f}%", labelpad=0.5, fontsize=args.fontsize, fontweight="bold")
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            if r == 0:
                ax.set_title(title, pad=2.5, fontsize=args.fontsize)
            if c == 0:
                ax.set_ylabel(name, labelpad=1.5, fontweight="bold")

    # cabeçalhos de grupo (Relaxed | Contention | Throughput), por posição real das colunas presentes
    all_specs = [("Placement, relaxed (% time)", "placement/relaxed"),
                 ("Placement, contention (% time)", "placement/contention"),
                 ("Class-2 ops/s", "throughput")]
    for group, key in all_specs:
        cols = [c for c, m in enumerate(METRICS) if key in m[0]]
        if not cols:
            continue
        x0 = axes[0, cols[0]].get_position().x0
        x1 = axes[0, cols[-1]].get_position().x1
        fig.text((x0 + x1) / 2, 1 - 0.035 / fig_h, group, ha="center", va="top",
                 fontsize=args.fontsize + 0.5, fontweight="bold")
    fig.savefig(args.out, dpi=300)
    print(f"[fig_results] gravado {args.out}")


if __name__ == "__main__":
    main()
