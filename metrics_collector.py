"""Coleta passiva de metricas da API WebSocket da Amarisoft.

Nenhuma decisao de AMC e enviada. Cada execucao recebe um rotulo para permitir
comparar o funcionamento nativo com execucoes dos controladores experimentais.
"""
import argparse
import csv
import json
import time
from datetime import datetime, timezone

from fuzzy_bler import APIError, RemoteAPI


CSV_FIELDS = (
    "timestamp_utc", "elapsed_s", "sample_id", "run_label", "ue_index",
    "rnti", "cell_id", "cqi", "dl_mcs", "snr", "pusch_snr", "dl_bler",
    "dl_tx", "dl_err", "ul_mcs", "raw_metrics",
)
METRIC_FIELDS = CSV_FIELDS[7:-1]


def rows_from_response(response, run_label, sample_id, elapsed_s):
    """Converte uma resposta ue_get em uma linha por UE/celula."""
    ues = response.get("ue_list")
    if not isinstance(ues, list):
        raise APIError("ue_get nao retornou ue_list")
    timestamp = datetime.now(timezone.utc).isoformat()
    rows = []
    for ue_index, ue in enumerate(ues):
        if not isinstance(ue, dict) or not isinstance(ue.get("cells"), list):
            raise APIError("UE sem estrutura cells valida")
        for cell in ue["cells"]:
            if not isinstance(cell, dict):
                raise APIError("metrica de celula invalida")
            if not isinstance(cell.get("cell_id"), int) or isinstance(cell.get("cell_id"), bool):
                raise APIError("cell_id invalido")
            sample = dict(ue)
            sample.update(cell)
            row = {
                "timestamp_utc": timestamp,
                "elapsed_s": f"{elapsed_s:.6f}",
                "sample_id": sample_id,
                "run_label": run_label,
                "ue_index": ue_index,
                "rnti": sample.get("rnti", ""),
                "cell_id": sample["cell_id"],
                "raw_metrics": json.dumps(sample, ensure_ascii=False, sort_keys=True),
            }
            row.update({field: sample.get(field, "") for field in METRIC_FIELDS})
            rows.append(row)
    return rows


def collect(url, output, run_label="native", interval=1.0, duration=None, samples=None):
    """Coleta ate duration segundos ou samples consultas, o que ocorrer primeiro."""
    api = RemoteAPI(url)
    started = time.monotonic()
    sample_id = 0
    try:
        with open(output, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            writer.writeheader()
            while (duration is None or time.monotonic() - started < duration) and \
                    (samples is None or sample_id < samples):
                rows = rows_from_response(
                    api.request("ue_get", stats=True), run_label, sample_id,
                    time.monotonic() - started,
                )
                writer.writerows(rows)
                stream.flush()
                sample_id += 1
                if (duration is None or time.monotonic() - started < duration) and \
                        (samples is None or sample_id < samples):
                    time.sleep(interval)
    finally:
        api.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://172.16.2.226:9001")
    parser.add_argument("--output", default="amarisoft_metrics.csv")
    parser.add_argument("--run-label", default="native",
                        help="rotulo da execucao: native, fuzzy_bler, fuzzy_snr...")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--samples", type=int)
    args = parser.parse_args()
    if args.interval <= 0 or (args.duration is None and args.samples is None):
        parser.error("interval deve ser positivo e duration ou samples e obrigatorio")
    try:
        collect(args.url, args.output, args.run_label, args.interval,
                args.duration, args.samples)
    except (APIError, OSError, ValueError) as exc:
        parser.error(str(exc))