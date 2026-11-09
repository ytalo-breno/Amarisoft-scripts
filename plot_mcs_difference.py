"""Gera um grafico da diferenca de MCS por linha para cada CSV de validacao."""
import argparse
import csv
import os


def read_errors(path):
    points = []
    with open(path, newline="", encoding="utf-8") as stream:
        for fallback_row, row in enumerate(csv.DictReader(stream), start=2):
            try:
                row_number = int(row.get("row_number", fallback_row))
                error = float(row["mcs_error"])
                observed = float(row["observed_ul_mcs"])
                proposed = float(row["proposed_mcs"])
            except (KeyError, TypeError, ValueError):
                continue
            points.append((row_number, error, observed, proposed))
    return points


def plot_file(path, output_dir):
    import matplotlib.pyplot as plt

    points = read_errors(path)
    if not points:
        return None
    name = os.path.splitext(os.path.basename(path))[0]
    output_path = os.path.join(output_dir, f"{name}_mcs_difference.png")
    figure, axis = plt.subplots(figsize=(11, 5))
    axis.plot([row for row, _, _, _ in points], [error for _, error, _, _ in points],
              marker=".", linewidth=1, color="#2f6690")
    axis.axhline(0, color="black", linewidth=0.8)
    axis.set_xlabel("Linha da tabela")
    axis.set_ylabel("MCS proposto - MCS observado")
    axis.set_title(f"Diferenca de MCS por linha: {os.path.basename(path)}")
    axis.grid(True, alpha=0.25)
    figure.tight_layout()
    figure.savefig(output_path, dpi=150)
    plt.close(figure)

    comparison_path = os.path.join(output_dir, f"{name}_mcs_observed_proposed.png")
    figure, axis = plt.subplots(figsize=(11, 5))
    axis.plot([row for row, _, _, _ in points],
              [observed for _, _, observed, _ in points],
              marker=".", linewidth=1, label="MCS observado", color="#2f6690")
    axis.plot([row for row, _, _, _ in points],
              [proposed for _, _, _, proposed in points],
              marker=".", linewidth=1, label="MCS proposto", color="#e07a5f")
    axis.set_xlabel("Linha da tabela")
    axis.set_ylabel("MCS")
    axis.set_title(f"MCS observado e proposto por linha: {os.path.basename(path)}")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(comparison_path, dpi=150)
    plt.close(figure)
    return output_path, comparison_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="+", help="CSV(s) de validacao")
    parser.add_argument("--output-dir", default="mcs_difference_graphs")
    args = parser.parse_args(argv)

    os.makedirs(args.output_dir, exist_ok=True)
    generated = [plot_file(path, args.output_dir) for path in args.input]
    generated = [paths for paths in generated if paths is not None]
    for paths in generated:
        print(paths[0])
        print(paths[1])
    return 0 if generated else 1


if __name__ == "__main__":
    raise SystemExit(main())