#!/usr/bin/env python3
"""
analysis/smt_compare.py — placement (smt x nosmt) e vazão (só smt, com
oráculo onde existir), vanilla/icas sobrepostos por cor na MESMA posição X
(não em colunas separadas). Uma linha por plataforma.

Uso:
    python3 analysis/smt_compare.py \
        --platform "i5-1334U=i5/vanilla_smt,i5/orig_smt,i5/vanilla_nosmt,i5/orig_nosmt,i5/oracle_pin" \
        --platform "i9-14900HX=i9/vanilla,i9/orig_smt,i9/vanilla_nosmt,i9/orig_nosmt," \
        --out smt_compare.pdf

Cada --platform leva 5 diretórios: vanilla_smt,icas_smt,vanilla_nosmt,icas_nosmt,oracle_smt
(o último pode ficar vazio, ex. "...,orig_nosmt," — sem oráculo nessa plataforma).
"""
import argparse
from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    raise SystemExit("matplotlib é necessário: pip install matplotlib numpy")

# Palette: blue/orange/green
COLOR = {"asym": "#2a78d6", "icas": "#eb6834", "pinned": "#1baf7a"}

PLACEMENT_METRICS = [
    ("placement/relaxed/cls2_p_residency.txt", "cls2→P", "Relaxed"),
    ("placement/relaxed/cls1_e_residency.txt", "cls1→E", "Relaxed"),
    ("placement/contention/cls2_p_residency.txt", "cls2→P", "Contention"),
    ("placement/contention/cls1_e_residency.txt", "cls1→E", "Contention"),
]
THROUGHPUT_METRIC = ("throughput/c2_contention/compute_ops.txt", "contention", "Throughput (ops/s)")


def load(path):
    vals = []
    if not Path(path).exists():
        return np.array(vals)
    for line in Path(path).read_text().split("\n"):
        try:
            vals.append(float(line.strip()))
        except ValueError:
            pass
    return np.array(vals)


def overlay(ax, x, groups, width, rng, s=2.0):
    """Desenha os grupos (lista de (vals, key)) sobrepostos na posição x:
    pontos no MESMO range de jitter, uma barra de média por grupo, deslocadas
    o suficiente pra não se confundirem quando os valores são próximos."""
    n = len(groups)
    bar_offsets = np.linspace(-width * 0.32, width * 0.32, n) if n > 1 else [0]
    for (vals, key), off in zip(groups, bar_offsets):
        if len(vals) == 0:
            continue
        jitter = rng.uniform(-width * 0.42, width * 0.42, len(vals))
        ax.scatter(x + jitter, vals, s=s, c=COLOR[key], alpha=0.35, linewidths=0, rasterized=True, zorder=2)
        ax.hlines(vals.mean(), x + off - width * 0.16, x + off + width * 0.16,
                  colors=COLOR[key], lw=1.6, zorder=3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", action="append", required=True,
                    help='"nome=vanilla_smt,icas_smt,vanilla_nosmt,icas_nosmt,oracle_smt" (oracle pode ficar vazio)')
    ap.add_argument("--base", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--out", default="smt_compare.pdf")
    ap.add_argument("--width", type=float, default=7.16)
    ap.add_argument("--panel-height", type=float, default=0.95)
    ap.add_argument("--fontsize", type=float, default=6.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--match-n", action="store_true",
                    help="quando vanilla e icas (nosmt) têm n diferente, sorteia ALEATORIAMENTE (seed fixa) "
                         "o maior até o n do menor, mesmas corridas em todas as métricas. Não escolhe por valor.")
    ap.add_argument("--subsample-seed", type=int, default=12345)
    args = ap.parse_args()

    plats = []
    for spec in args.platform:
        name, _, dirs = spec.partition("=")
        parts = [d.strip() for d in dirs.split(",")]
        while len(parts) < 5:
            parts.append("")
        plats.append((name, parts))

    n_rows = len(plats)
    n_cols = len(PLACEMENT_METRICS) + 1
    rng = np.random.default_rng(args.seed)

    plt.rcParams.update({"font.size": args.fontsize, "axes.labelsize": args.fontsize,
                         "xtick.labelsize": args.fontsize, "ytick.labelsize": args.fontsize - 0.5})
    top, bottom, gap = 0.36, 0.42, 0.30
    fig_h = n_rows * args.panel_height + top + bottom + gap * (n_rows - 1)
    fig, axes = plt.subplots(n_rows, n_cols, squeeze=False, figsize=(args.width, fig_h),
                             gridspec_kw={"hspace": gap / args.panel_height, "wspace": 0.6})
    fig.subplots_adjust(left=0.05, right=0.995, top=1 - top / fig_h, bottom=bottom / fig_h)

    for r, (name, (v_smt, i_smt, v_nosmt, i_nosmt, orac)) in enumerate(plats):
        base = Path(args.base)
        keep = {}   # (cenário) -> índices das corridas mantidas no maior grupo nosmt
        if args.match_n and v_nosmt:
            sub_rng = np.random.default_rng(args.subsample_seed)
            for scen in ("relaxed", "contention"):
                na = len(load(base / v_nosmt / f"placement/{scen}/cls2_p_residency.txt"))
                nb = len(load(base / i_nosmt / f"placement/{scen}/cls2_p_residency.txt"))
                if na != nb:
                    big = max(na, nb)
                    keep[scen] = (("v" if na > nb else "i"), np.sort(sub_rng.choice(big, min(na, nb), replace=False)))
        for c, (rel, title, group) in enumerate(PLACEMENT_METRICS):
            ax = axes[r, c]
            a_smt, b_smt = load(base / v_smt / rel), load(base / i_smt / rel)
            a_no, b_no = (load(base / v_nosmt / rel), load(base / i_nosmt / rel)) if v_nosmt else (np.array([]), np.array([]))
            scen = "relaxed" if "relaxed" in rel else "contention"
            if scen in keep:
                which, idx = keep[scen]
                if which == "v":
                    a_no = a_no[idx]
                else:
                    b_no = b_no[idx]
            if args.match_n and v_nosmt and len(a_no) and len(b_no):
                print(f"[match-n] {name} nosmt {scen} {title}: asym={a_no.mean():.1f} (n={len(a_no)})  icas={b_no.mean():.1f} (n={len(b_no)})")
            overlay(ax, 0, [(a_smt, "asym"), (b_smt, "icas")], 0.8, rng)
            overlay(ax, 1, [(a_no, "asym"), (b_no, "icas")], 0.8, rng)
            ax.set_xlim(-0.6, 1.6)
            ax.set_xticks([0, 1]); ax.set_xticklabels(["smt", "nosmt"])
            ax.set_ylim(-4, 104); ax.set_yticks([0, 50, 100])
            ax.tick_params(length=1.5, pad=1)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            if r == 0:
                ax.set_title(title, pad=2.5, fontsize=args.fontsize)
            if c == 0:
                ax.set_ylabel(name, labelpad=3, fontweight="bold")

        c = n_cols - 1
        ax = axes[r, c]
        rel = THROUGHPUT_METRIC[0]
        a, b = load(base / v_smt / rel), load(base / i_smt / rel)
        groups = [(a, "asym"), (b, "icas")]
        if orac:
            groups.append((load(base / orac / rel), "pinned"))
        if len(a) and len(b):
            overlay(ax, 0, groups, 0.9, rng, s=3.0)
            allvals = np.concatenate([v for v, _ in groups if len(v)])
            lo, hi = allvals.min(), allvals.max()
            pad = (hi - lo) * 0.12 or 1
            ax.set_ylim(lo - pad, hi + pad)
            ax.yaxis.set_major_locator(plt.MaxNLocator(3))
            ax.ticklabel_format(axis="y", style="plain", useOffset=False)
        else:
            ax.text(0.5, 0.5, "data\npending", transform=ax.transAxes, ha="center", va="center",
                    fontsize=args.fontsize, color="#777777")
        ax.set_xlim(-0.6, 0.6)
        ax.set_xticks([0]); ax.set_xticklabels(["smt"])
        ax.tick_params(length=1.5, pad=1)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        if r == 0:
            ax.set_title(THROUGHPUT_METRIC[1], pad=2.5, fontsize=args.fontsize)
        ax.set_ylabel("", labelpad=1.5)

    from matplotlib.patches import Patch
    handles = [Patch(facecolor=COLOR[k], label=lbl) for k, lbl in
              (("asym", "asym_packing"), ("icas", "icas"), ("pinned", "pinned oracle"))]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False,
              fontsize=args.fontsize, bbox_to_anchor=(0.5, 0.06 / fig_h))

    for group, key in (("Placement, relaxed (% time)", "relaxed"),
                       ("Placement, contention (% time)", "contention"),
                       ("Class-2 ops/s", "Throughput")):
        cols = [c for c, m in enumerate(PLACEMENT_METRICS) if key.lower() in m[2].lower()] if key != "Throughput" else [n_cols - 1]
        if not cols:
            continue
        x0 = axes[0, cols[0]].get_position().x0
        x1 = axes[0, cols[-1]].get_position().x1
        fig.text((x0 + x1) / 2, 1 - 0.03 / fig_h, group, ha="center", va="top",
                 fontsize=args.fontsize + 0.5, fontweight="bold")

    fig.savefig(args.out, dpi=300)
    print(f"[smt_compare] gravado {args.out}")


if __name__ == "__main__":
    main()
