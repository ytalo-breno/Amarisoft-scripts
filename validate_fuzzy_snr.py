"""Valida offline o controlador fuzzy por SNR usando CSVs coletados."""
import argparse
import csv
import math
import os
import sys

from fuzzy_snr import get_max_mcs_for_snr, infer_delta


OUTPUT_FIELDS = (
    "source_file", "row_number", "cell_id", "rnti", "sinr", "observed_ul_mcs",
    "fuzzy_delta", "sinr_mcs_limit", "proposed_mcs", "mcs_error",
    "within_sinr_limit",
)


def numeric(row, field):
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def validate_rows(rows, source_file=""):
    """Reproduz uma decisão por linha e retorna linhas válidas e contadores."""
    validated = []
    skipped = 0
    for row_number, row in enumerate(rows, start=2):
        sinr = numeric(row, "pusch_snr")
        if sinr is None:
            sinr = numeric(row, "snr")
        observed_mcs = numeric(row, "ul_mcs")
        if sinr is None or observed_mcs is None:
            skipped += 1
            continue
        try:
            delta = infer_delta(sinr)
            sinr_limit = get_max_mcs_for_snr(sinr)
        except ValueError:
            skipped += 1
            continue
        proposed_mcs = max(0, min(28, int(round(observed_mcs + delta)), sinr_limit))
        validated.append({
            "source_file": source_file,
            "row_number": row_number,
            "cell_id": row.get("cell_id", ""),
            "rnti": row.get("rnti", ""),
            "sinr": f"{sinr:.6g}",
            "observed_ul_mcs": f"{observed_mcs:.6g}",
            "fuzzy_delta": delta,
            "sinr_mcs_limit": sinr_limit,
            "proposed_mcs": proposed_mcs,
            "mcs_error": f"{proposed_mcs - observed_mcs:.6g}",
            "within_sinr_limit": str(observed_mcs <= sinr_limit).lower(),
        })
    return validated, skipped


def summarize(rows, skipped=0):
    """Calcula métricas simples para avaliar o replay contra o CSV."""
    if not rows:
        return {"validated": 0, "skipped": skipped}
    errors = [abs(float(row["mcs_error"])) for row in rows]
    within_limit = sum(row["within_sinr_limit"] == "true" for row in rows)
    return {
        "validated": len(rows),
        "skipped": skipped,
        "mae_mcs": sum(errors) / len(errors),
        "within_sinr_limit_pct": 100 * within_limit / len(rows),
    }


def validate_file(path):
    """Valida uma tabela e retorna somente suas linhas e seu resumo."""
    with open(path, newline="", encoding="utf-8") as stream:
        rows, skipped = validate_rows(csv.DictReader(stream), path)
    return rows, summarize(rows, skipped)


def validate_files(paths):
    """Retorna a validação separada por caminho de entrada."""
    return {path: validate_file(path) for path in paths}


def write_validation(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="+", help="CSV(s) produzido(s) pelo coletor")
    parser.add_argument("--output-dir", default="validation_snr",
                        help="diretorio dos CSVs de validacao, um por entrada")
    args = parser.parse_args(argv)

    results = validate_files(args.input)
    os.makedirs(args.output_dir, exist_ok=True)
    has_valid_rows = False
    for path, (rows, summary) in results.items():
        output_name = f"{os.path.splitext(os.path.basename(path))[0]}_validation.csv"
        output_path = os.path.join(args.output_dir, output_name)
        write_validation(output_path, rows)
        print(f"\nTabela: {path}")
        print(f"Relatorio: {output_path}")
        print(f"Linhas validas: {summary['validated']}")
        print(f"Linhas ignoradas: {summary['skipped']}")
        if rows:
            has_valid_rows = True
            print(f"MAE entre MCS proposto e observado: {summary['mae_mcs']:.3f}")
            print(f"Observado dentro do limite SINR: {summary['within_sinr_limit_pct']:.1f}%")
    return 0 if has_valid_rows else 1


if __name__ == "__main__":
    sys.exit(main())