#!/usr/bin/env python3
"""
analysis/pe_delta_by_class.py — P/E delta por método, separado por classe final
(cls1 x cls2), lado a lado. Cada ponto é UM método do class_sweep.sh.

Uso:
    python3 analysis/pe_delta_by_class.py \
        --csv results/<tag>/class_sweep/summary.csv --out pe_delta.pdf
"""
import argparse
import csv
import subprocess
from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    raise SystemExit("matplotlib é necessário: pip install matplotlib numpy")

# violet/yellow: blue/orange/green are reserved for the kernels
COLOR = {"1": "#4a3aa7", "2": "#eda100"}
LABEL = {"1": "class 1", "2": "class 2"}


def real_methods():
    r = subprocess.run(["stress-ng", "--cpu-method", "list"], capture_output=True, text=True)
    methods = set((r.stdout + r.stderr).split("choices are: ")[-1].split())
    methods.discard("all")
    return methods


def load(csv_path):
    real = real_methods()
    rows = {}
    with open(csv_path) as f:
        for row in csv.reader(f):
            if len(row) != 6 or row[0] not in real:
                continue
            method, core, ops, classes, final, ntrans = row
            rows.setdefault(method, {})[core] = (ops, final)

    pe = {"1": [], "2": []}
    for method, d in rows.items():
        if "p" not in d or "e" not in d:
            continue
        (p_ops, p_final), (e_ops, _) = d["p"], d["e"]
        if p_final not in ("1", "2") or p_ops in ("NA", "") or e_ops in ("NA", ""):
            continue
        p_ops, e_ops = float(p_ops), float(e_ops)
        if e_ops <= 0:
            continue
        pe[p_final].append((method, p_ops / e_ops))
    return pe


def iqr_bounds(vals):
    s = sorted(vals)
    n = len(s)

    def pct(p):
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        return s[f] + (s[c] - s[f]) * (k - f)

    q1, q3 = pct(0.25), pct(0.75)
    iqr = q3 - q1
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", default=str(Path.home() / "Downloads" / "pe_delta.pdf"))
    ap.add_argument("--width", type=float, default=3.45, help="polegadas (3.45 = 1 coluna IEEE)")
    ap.add_argument("--height", type=float, default=2.6)
    ap.add_argument("--fontsize", type=float, default=8.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--label", action="store_true", help="anota o nome do método em cada ponto")
    ap.add_argument("--filter-outliers", action="store_true",
                    help="remove outliers por classe (1.5x IQR) antes de plotar/calcular a média")
    args = ap.parse_args()

    pe = load(args.csv)
    dropped = {"1": [], "2": []}
    if args.filter_outliers:
        for cls in ("1", "2"):
            vals = [v for _, v in pe[cls]]
            lo, hi = iqr_bounds(vals)
            dropped[cls] = [(m, v) for m, v in pe[cls] if not (lo <= v <= hi)]
            pe[cls] = [(m, v) for m, v in pe[cls] if lo <= v <= hi]
    rng = np.random.default_rng(args.seed)

    plt.rcParams.update({"font.size": args.fontsize, "axes.labelsize": args.fontsize,
                         "xtick.labelsize": args.fontsize, "ytick.labelsize": args.fontsize - 0.5})
    fig, ax = plt.subplots(figsize=(args.width, args.height))

    for x, cls in enumerate(("1", "2")):
        vals = [r for _, r in pe[cls]]
        if not vals:
            continue
        jitter = rng.uniform(-0.28, 0.28, len(vals))
        ax.scatter([x] * len(vals) + jitter, vals, s=14, c=COLOR[cls], alpha=0.75,
                   edgecolors="white", linewidths=0.4, zorder=3)
        mean = sum(vals) / len(vals)
        ax.hlines(mean, x - 0.36, x + 0.36, colors="black", lw=1.3, zorder=4)
        ax.text(x, -0.09, f"n={len(vals)}  mean={mean:.2f}×", transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize=args.fontsize - 1)
        if args.label:
            for (m, r), xi in zip(pe[cls], jitter):
                ax.annotate(m, (x + xi, r), fontsize=4, alpha=0.6,
                            xytext=(2, 0), textcoords="offset points")

    ax.axhline(1.0, color="#999999", lw=0.8, ls="--", zorder=1)
    ax.set_xlim(-0.6, 1.6)
    ax.set_xticks([0, 1])
    ax.set_xticklabels([LABEL["1"], LABEL["2"]])
    ax.set_ylabel("P-core / E-core throughput")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.subplots_adjust(left=0.16, right=0.97, top=(0.88 if args.filter_outliers else 0.96), bottom=0.20)
    if args.filter_outliers:
        ax.set_title("outliers removidos (1.5×IQR por classe)", fontsize=args.fontsize - 1, pad=4)
    fig.savefig(args.out, dpi=300)
    print(f"[pe_delta_by_class] gravado {args.out}")
    for cls in ("1", "2"):
        vals = sorted(pe[cls], key=lambda x: x[1])
        print(f"  classe {cls}: n={len(vals)}  min={vals[0] if vals else None}  max={vals[-1] if vals else None}")
        if dropped[cls]:
            print(f"    outliers removidos: {sorted(dropped[cls], key=lambda x: x[1])}")


if __name__ == "__main__":
    main()
