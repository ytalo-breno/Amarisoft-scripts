"""Gera visoes gerais, trechos por usuario e histograma dos CSVs de validacao."""
import argparse
import csv
import math
import os
from collections import defaultdict


def read_groups(path):
    groups = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as stream:
        for fallback_row, row in enumerate(csv.DictReader(stream), start=2):
            try:
                point = (int(row.get("row_number", fallback_row)),
                         float(row["mcs_error"]), float(row["observed_ul_mcs"]),
                         float(row["proposed_mcs"]))
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(value) for value in point):
                continue
            groups[(row.get("cell_id") or "?", row.get("rnti") or "?")].append(point)
    for points in groups.values():
        points.sort(key=lambda point: point[0])
    return groups


def read_errors(path):
    return sorted((point for points in read_groups(path).values() for point in points),
                  key=lambda point: point[0])


def limits(values):
    low, high = min(values), max(values)
    padding = max((high - low) * 0.08, 0.5)
    return low - padding, high + padding


def plot_file(path, output_dir, samples_per_plot=150):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    if samples_per_plot < 1:
        raise ValueError("samples_per_plot deve ser positivo")
    groups = read_groups(path)
    if not groups:
        return None
    os.makedirs(output_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(path))[0]
    points = [point for group in groups.values() for point in group]
    error_limits = limits([0] + [point[1] for point in points])
    mcs_limits = limits([value for point in points for value in point[2:]])
    generated = []

    def save(figure, filename):
        target = os.path.join(output_dir, filename)
        figure.savefig(target, dpi=200, bbox_inches="tight")
        plt.close(figure)
        generated.append(target)

    def draw(axis, group, comparison, overview=False):
        rows, errors, observed, proposed = zip(*group)
        style = dict(marker=".", markersize=2, linewidth=0.7, alpha=0.65)
        # A visao geral usa pontos para evitar uma linha densa sobreposta.
        if overview:
            style["linestyle"] = "None"
        if comparison:
            axis.plot(rows, observed, label="MCS observado", color="#2f6690", **style)
            axis.plot(rows, proposed, label="MCS proposto", color="#c44e30", **style)
            axis.set_ylabel("MCS")
            axis.set_ylim(mcs_limits)
            axis.legend(loc="upper right", fontsize=9)
        else:
            axis.plot(rows, errors, color="#2f6690", **style)
            axis.axhline(0, color="black", linewidth=0.8)
            axis.set_ylabel("MCS proposto − observado")
            axis.set_ylim(error_limits)
        axis.set_xlabel("Linha original da tabela")
        axis.xaxis.set_major_locator(MaxNLocator(nbins=10, integer=True))
        axis.grid(True, alpha=0.25)

    # Escalas verticais comuns permitem comparar todos os usuarios e trechos.
    for comparison, suffix in ((False, "mcs_difference"),
                               (True, "mcs_observed_proposed")):
        figure, axes = plt.subplots(len(groups), 1, figsize=(16, 3.5 * len(groups)),
                                    squeeze=False, layout="constrained")
        figure.suptitle(f"{name} — visao geral por usuario")
        for axis, ((cell, rnti), group) in zip(axes[:, 0], groups.items()):
            draw(axis, group, comparison, overview=True)
            axis.set_title(f"Celula {cell} · RNTI {rnti} · {len(group)} amostras")
        save(figure, f"{name}_{suffix}.png")

    for group_index, ((cell, rnti), group) in enumerate(groups.items(), start=1):
        for start in range(0, len(group), samples_per_plot):
            chunk = group[start:start + samples_per_plot]
            figure, axes = plt.subplots(2, 1, figsize=(16, 8), sharex=True,
                                       layout="constrained")
            figure.suptitle(f"{name} · Celula {cell} · RNTI {rnti}\n"
                            f"Amostras {start + 1}–{start + len(chunk)} de {len(group)}")
            draw(axes[0], chunk, True)
            draw(axes[1], chunk, False)
            save(figure, f"{name}_user_{group_index:02d}_"
                         f"part_{start // samples_per_plot + 1:03d}.png")

    figure, axis = plt.subplots(figsize=(12, 6), layout="constrained")
    axis.hist([point[1] for point in points], bins="auto", color="#2f6690",
              edgecolor="white")
    axis.axvline(0, color="black", linewidth=1, linestyle="--")
    axis.set(title=f"{name} — distribuicao do erro ({len(points)} amostras)",
             xlabel="MCS proposto − MCS observado", ylabel="Numero de amostras")
    axis.yaxis.set_major_locator(MaxNLocator(integer=True))
    axis.grid(axis="y", alpha=0.25)
    save(figure, f"{name}_mcs_error_histogram.png")
    return tuple(generated)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="+", help="CSV(s) de validacao")
    parser.add_argument("--output-dir", default="mcs_difference_graphs")
    parser.add_argument("--samples-per-plot", type=int, default=150,
                        help="Maximo de amostras por trecho e usuario (padrao: 150)")
    args = parser.parse_args(argv)
    if args.samples_per_plot < 1:
        parser.error("--samples-per-plot deve ser maior que zero")
    generated = False
    for path in args.input:
        paths = plot_file(path, args.output_dir, args.samples_per_plot)
        for target in paths or ():
            print(target)
            generated = True
    return 0 if generated else 1


if __name__ == "__main__":
    raise SystemExit(main())
