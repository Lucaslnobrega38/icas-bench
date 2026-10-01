#!/usr/bin/env python3
"""
analysis/pw_delta_by_class.py — razão P/E de ops/joule por método, separado
por classe final (cls1 x cls2). Mesmo estilo de pe_delta_by_class.py, mas
para eficiência energética em vez de vazão bruta.

Uso:
    python3 analysis/pw_delta_by_class.py \
        --power-csv results/<tag>/class_sweep_power/summary.csv \
        --class-csv results/<tag>/class_sweep/summary.csv \
        --out pw_delta.pdf
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

COLOR = {"1": "#0072B2", "2": "#E69F00"}
LABEL = {"1": "class 1", "2": "class 2"}


def load_classes(path):
    cls = {}
    with open(path) as f:
        for line in f:
            parts = line.rstrip("\n").split(",")
            if len(parts) != 6:
                continue
            method, core, ops, classes, final, ntrans = parts
            if core == "p" and final in ("1", "2"):
                cls[method] = final
    return cls


def load_power(path):
    power = {}
    with open(path) as f:
        next(f)
        for line in f:
            parts = line.rstrip("\n").split(",")
            if len(parts) != 5:
                continue
            method, core, ops, ej, opj = parts
            power[(method, core)] = opj   # última ocorrência vence (dedup natural)
    return power


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--power-csv", required=True)
    ap.add_argument("--class-csv", required=True)
    ap.add_argument("--out", default=str(Path.home() / "Downloads" / "pw_delta.pdf"))
    ap.add_argument("--width", type=float, default=3.45)
    ap.add_argument("--height", type=float, default=2.6)
    ap.add_argument("--fontsize", type=float, default=8.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--filter-outliers", action="store_true")
    args = ap.parse_args()

    cls = load_classes(args.class_csv)
    power = load_power(args.power_csv)
    methods = sorted(set(m for m, _ in power))

    pe = {"1": [], "2": []}
    for m in methods:
        c = cls.get(m)
        if c not in ("1", "2"):
            continue
        p_opj, e_opj = power.get((m, "p")), power.get((m, "e"))
        if p_opj in (None, "NA", "") or e_opj in (None, "NA", ""):
            continue
        p_opj, e_opj = float(p_opj), float(e_opj)
        if e_opj <= 0:
            continue
        pe[c].append((m, p_opj / e_opj))

    dropped = {"1": [], "2": []}
    if args.filter_outliers:
        for c in ("1", "2"):
            vals = [v for _, v in pe[c]]
            s = sorted(vals)
            n = len(s)
            def pct(p):
                k = (n - 1) * p; f = int(k); cc = min(f + 1, n - 1)
                return s[f] + (s[cc] - s[f]) * (k - f)
            q1, q3 = pct(0.25), pct(0.75)
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            dropped[c] = [(m, v) for m, v in pe[c] if not (lo <= v <= hi)]
            pe[c] = [(m, v) for m, v in pe[c] if lo <= v <= hi]

    rng = np.random.default_rng(args.seed)
    plt.rcParams.update({"font.size": args.fontsize, "axes.labelsize": args.fontsize,
                         "xtick.labelsize": args.fontsize, "ytick.labelsize": args.fontsize - 0.5})
    fig, ax = plt.subplots(figsize=(args.width, args.height))

    for x, c in enumerate(("1", "2")):
        vals = [r for _, r in pe[c]]
        if not vals:
            continue
        jitter = rng.uniform(-0.28, 0.28, len(vals))
        ax.scatter([x] * len(vals) + jitter, vals, s=14, c=COLOR[c], alpha=0.75,
                   edgecolors="white", linewidths=0.4, zorder=3)
        mean = sum(vals) / len(vals)
        ax.hlines(mean, x - 0.36, x + 0.36, colors="black", lw=1.3, zorder=4)
        ax.text(x, -0.09, f"n={len(vals)}  mean={mean:.2f}×", transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize=args.fontsize - 1)

    ax.axhline(1.0, color="#999999", lw=0.8, ls="--", zorder=1)
    ax.set_xlim(-0.6, 1.6)
    ax.set_xticks([0, 1])
    ax.set_xticklabels([LABEL["1"], LABEL["2"]])
    ax.set_ylabel("P-core / E-core ops per joule")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if args.filter_outliers:
        ax.set_title("outliers removidos (1.5×IQR por classe)", fontsize=args.fontsize - 1, pad=4)
    fig.subplots_adjust(left=0.16, right=0.97, top=(0.88 if args.filter_outliers else 0.96), bottom=0.20)
    fig.savefig(args.out, dpi=300)
    print(f"[pw_delta_by_class] gravado {args.out}")
    for c in ("1", "2"):
        vals = sorted(pe[c], key=lambda x: x[1])
        print(f"  classe {c}: n={len(vals)}  min={vals[0] if vals else None}  max={vals[-1] if vals else None}")
        if dropped[c]:
            print(f"    outliers removidos: {sorted(dropped[c], key=lambda x: x[1])}")


if __name__ == "__main__":
    main()
