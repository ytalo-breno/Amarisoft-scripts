"""Valida offline o controlador fuzzy por BLER usando CSVs coletados."""
import argparse
import csv
import math
import sys

from fuzzy_bler import get_max_mcs_for_cqi, infer_delta


OUTPUT_FIELDS = (
    "source_file", "row_number", "cell_id", "rnti", "cqi", "bler",
    "bler_source", "observed_dl_mcs", "fuzzy_delta", "cqi_mcs_limit",
    "proposed_mcs", "mcs_error", "within_cqi_limit",
)


def numeric(row, field, low=None, high=None):
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if low is not None and value < low or high is not None and value > high:
        return None
    return value


def validate_rows(rows, source_file=""):
    """Reproduz a decisão fuzzy por linha e retorna linhas válidas e contadores."""
    validated = []
    skipped = 0
    previous_counters = {}
    for row_number, row in enumerate(rows, start=2):
        cqi = numeric(row, "cqi", 0, 15)
        observed_mcs = numeric(row, "dl_mcs", 0, 28)
        bler = numeric(row, "dl_bler", 0, 1)
        bler_source = "dl_bler"
        key = (row.get("cell_id", ""), row.get("rnti", ""))
        if bler is None:
            tx = numeric(row, "dl_tx", 0)
            errors = numeric(row, "dl_err", 0)
            previous = previous_counters.get(key)
            previous_counters[key] = (tx, errors) if tx is not None and errors is not None else None
            if previous is not None and tx is not None and errors is not None:
                delta_tx = tx - previous[0]
                delta_errors = errors - previous[1]
                if delta_tx > 0 and 0 <= delta_errors <= delta_tx:
                    bler = delta_errors / delta_tx
                    bler_source = "dl_err/dl_tx"
        if cqi is None or observed_mcs is None or bler is None:
            skipped += 1
            continue
        try:
            delta = infer_delta(bler, cqi)
            cqi_limit = get_max_mcs_for_cqi(cqi)
        except ValueError:
            skipped += 1
            continue
        proposed_mcs = max(0, min(28, int(round(observed_mcs + delta)), cqi_limit))
        validated.append({
            "source_file": source_file,
            "row_number": row_number,
            "cell_id": row.get("cell_id", ""),
            "rnti": row.get("rnti", ""),
            "cqi": f"{cqi:.6g}",
            "bler": f"{bler:.6g}",
            "bler_source": bler_source,
            "observed_dl_mcs": f"{observed_mcs:.6g}",
            "fuzzy_delta": delta,
            "cqi_mcs_limit": cqi_limit,
            "proposed_mcs": proposed_mcs,
            "mcs_error": f"{proposed_mcs - observed_mcs:.6g}",
            "within_cqi_limit": str(observed_mcs <= cqi_limit).lower(),
        })
    return validated, skipped


def summarize(rows, skipped=0):
    """Calcula métricas do replay fuzzy contra o CSV."""
    if not rows:
        return {"validated": 0, "skipped": skipped}
    errors = [abs(float(row["mcs_error"])) for row in rows]
    within_limit = sum(row["within_cqi_limit"] == "true" for row in rows)
    return {
        "validated": len(rows),
        "skipped": skipped,
        "mae_mcs": sum(errors) / len(errors),
        "within_cqi_limit_pct": 100 * within_limit / len(rows),
    }


def validate_files(paths):
    all_rows = []
    skipped = 0
    for path in paths:
        with open(path, newline="", encoding="utf-8") as stream:
            rows, file_skipped = validate_rows(csv.DictReader(stream), path)
        all_rows.extend(rows)
        skipped += file_skipped
    return all_rows, summarize(all_rows, skipped)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="+", help="CSV(s) produzido(s) pelo coletor")
    parser.add_argument("--output", help="CSV detalhado de validacao")
    args = parser.parse_args(argv)

    rows, summary = validate_files(args.input)
    if args.output:
        with open(args.output, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    print(f"Linhas validas: {summary['validated']}")
    print(f"Linhas ignoradas: {summary['skipped']}")
    if rows:
        print(f"MAE entre MCS proposto e observado: {summary['mae_mcs']:.3f}")
        print(f"Observado dentro do limite CQI: {summary['within_cqi_limit_pct']:.1f}%")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())