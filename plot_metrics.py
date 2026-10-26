"""Gera graficos a partir do CSV produzido por metrics_collector.py."""
import argparse
import csv
import os
from collections import defaultdict


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def read_files(paths):
    rows = []
    for path in paths:
        rows.extend(read_rows(path))
    return rows


def numeric(row, field):
    try:
        return float(row[field])
    except (KeyError, TypeError, ValueError):
        return None


def plot(rows, output_dir, metrics):
    import matplotlib.pyplot as plt

    os.makedirs(output_dir, exist_ok=True)
    groups = defaultdict(list)
    for row in rows:
        key = (row.get("run_label", ""), row.get("cell_id", ""), row.get("rnti", ""))
        groups[key].append(row)

    for metric in metrics:
        figure, axis = plt.subplots(figsize=(10, 5))
        for key, group in groups.items():
            points = [(numeric(item, metric), numeric(item, "dl_mcs"))
                      for item in group]
            points = [(x, y) for x, y in points if x is not None and y is not None]
            if points:
                axis.scatter([x for x, _ in points], [y for _, y in points],
                             s=14, alpha=0.65,
                             label="/".join(value or "?" for value in key))
        axis.set_xlabel(metric)
        axis.set_ylabel("DL MCS")
        axis.set_title(f"DL MCS x {metric}")
        axis.grid(True, alpha=0.25)
        if groups:
            axis.legend(fontsize="small")
        figure.tight_layout()
        figure.savefig(os.path.join(output_dir, f"mcs_vs_{metric}.png"), dpi=150)
        plt.close(figure)

    figure, axis = plt.subplots(figsize=(10, 5))
    for key, group in groups.items():
        points = [(numeric(item, "elapsed_s"), numeric(item, "dl_mcs"))
                  for item in group]
        points = [(x, y) for x, y in points if x is not None and y is not None]
        points.sort()
        if points:
            axis.plot([x for x, _ in points], [y for _, y in points], marker=".",
                      linewidth=1, label="/".join(value or "?" for value in key))
    axis.set_xlabel("Tempo (s)")
    axis.set_ylabel("DL MCS")
    axis.set_title("Variacao de DL MCS ao longo do tempo")
    axis.grid(True, alpha=0.25)
    if groups:
        axis.legend(fontsize="small")
    figure.tight_layout()
    figure.savefig(os.path.join(output_dir, "mcs_vs_time.png"), dpi=150)
    plt.close(figure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="+", help="um ou mais CSVs do coletor")
    parser.add_argument("--output-dir", default="graphs")
    parser.add_argument("--metrics", nargs="+",
                        default=["cqi", "snr", "pusch_snr", "dl_bler"])
    args = parser.parse_args()
    plot(read_files(args.input), args.output_dir, args.metrics)