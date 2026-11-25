"""Valida BLER/CQI e SINR e gera paineis legiveis por UE, sem descartar linhas."""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import validate_fuzzy_bler as bler
import validate_fuzzy_snr as snr


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def trend(axis, time, values, label, color, window):
    bins = defaultdict(list)
    for t, value in zip(time, values):
        bins[int(t // window)].append(value)
    centers = [(k + .5) * window for k in sorted(bins)]
    quantiles = np.array([np.percentile(bins[k], [10, 50, 90]) for k in sorted(bins)])
    axis.plot(centers, quantiles[:, 1], label=label, color=color, linewidth=1.8)
    axis.fill_between(centers, quantiles[:, 0], quantiles[:, 2], color=color, alpha=.15)


def panels(rows, source, kind, output, window):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["cell_id"], row["rnti"])].append(row)
    observed_field = "observed_dl_mcs" if kind == "bler" else "observed_ul_mcs"
    limit_field = "cqi_mcs_limit" if kind == "bler" else "sinr_mcs_limit"
    paths = []
    for index, ((cell, rnti), group) in enumerate(sorted(groups.items()), 1):
        times = [float(source[int(r["row_number"]) - 2]["elapsed_s"]) for r in group]
        observed = [float(r[observed_field]) for r in group]
        proposed = [float(r["proposed_mcs"]) for r in group]
        errors = np.array([float(r["mcs_error"]) for r in group])
        figure, axes = plt.subplots(2, 2, figsize=(15, 9), layout="constrained")
        axis = axes[0, 0]
        for values, label, color in [(observed, "Observado", "#2166ac"),
                                     (proposed, "Proposto", "#d6604d"),
                                     ([float(r[limit_field]) for r in group], "Teto da tabela", "#26854a")]:
            trend(axis, times, values, label, color, window)
        all_mcs = observed + proposed + [float(r[limit_field]) for r in group]
        axis.set(xlabel="Tempo decorrido (s)", ylabel="MCS",
                 ylim=(max(-1, min(all_mcs) - 1), min(29, max(all_mcs) + 1)),
                 title=f"Mediana por janela de {window:g} s; faixa P10–P90")
        axis.legend()
        axis = axes[0, 1]
        counts = axis.hist2d(observed, proposed, bins=[np.arange(-.5, 29.5), np.arange(-.5, 29.5)],
                             cmap="Blues", cmin=1)
        axis.plot([0, 28], [0, 28], "--", color="#d6604d", label="Igualdade")
        axis.set(xlabel="MCS observado", ylabel="MCS proposto", title="Frequência de todas as amostras")
        figure.colorbar(counts[3], ax=axis, label="Amostras")
        axis.legend()
        axis = axes[1, 0]
        axis.hist(errors, bins=np.arange(-29, 30, .5), color="#2166ac")
        axis.axvline(0, color="black", linewidth=1)
        axis.set_xlim(min(-1, float(errors.min()) - .5), max(1, float(errors.max()) + .5))
        axis.set(xlabel="MCS proposto − observado", ylabel="Amostras",
                 title=f"Distribuição do erro; MAE = {np.mean(abs(errors)):.3f}")
        axis = axes[1, 1]
        if kind == "bler":
            values = [100 * float(r["bler"]) for r in group]
            trend(axis, times, values, "BLER (%)", "#7b3294", window)
            axis.axhline(10, color="#d6604d", linestyle="--", label="Alvo 10%")
            axis.set(ylabel="BLER (%)", ylim=(-1, max(12, max(values) * 1.05)))
        else:
            trend(axis, times, [float(r["sinr"]) for r in group], "SINR", "#7b3294", window)
            axis.set(ylabel="SINR (dB)")
        axis.set(xlabel="Tempo decorrido (s)", title="Entrada do controlador; mediana e P10–P90")
        axis.legend()
        for axis in axes.flat:
            axis.grid(alpha=.2)
        figure.suptitle(f"{'DL · BLER/CQI' if kind == 'bler' else 'UL · SINR'} | célula {cell} | RNTI {rnti} | {len(group)} amostras", fontsize=15)
        path = output / f"{kind}_ue_{index}.png"
        figure.savefig(path, dpi=170)
        plt.close(figure)
        paths.append(path.name)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--output-dir", default="reports/amarisoft_metrics3")
    parser.add_argument("--window-seconds", type=float, default=5)
    parser.add_argument("--bler-mode", choices=("totals", "window"), default="totals")
    args = parser.parse_args()
    if not np.isfinite(args.window_seconds) or args.window_seconds <= 0:
        parser.error("--window-seconds deve ser positivo e finito")
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with open(args.input, newline="", encoding="utf-8") as stream:
        source = list(csv.DictReader(stream))
    summary = {"input": args.input, "total_rows": len(source), "window_seconds": args.window_seconds,
               "bler_mode": args.bler_mode, "bler_mcs_field": "dl_mcs", "snr_mcs_field": "ul_mcs"}
    images = []
    for kind, module in [("bler", bler), ("snr", snr)]:
        rows, skipped = (module.validate_rows(source, args.input, args.bler_mode)
                         if kind == "bler" else module.validate_rows(source, args.input))
        summary[kind] = module.summarize(rows, skipped)
        write_csv(output / f"{kind}_validation.csv", rows, module.OUTPUT_FIELDS)
        if rows:
            images.extend(panels(rows, source, kind, output, args.window_seconds))
        if kind == "bler" and rows:
            values = [float(r["bler"]) for r in rows]
            summary[kind].update(mean_bler_pct=100 * float(np.mean(values)),
                                 above_10_pct=100 * sum(v > .1 for v in values) / len(values),
                                 bler_sources=dict((s, sum(r["bler_source"] == s for r in rows))
                                                   for s in sorted({r["bler_source"] for r in rows})))
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    html = """<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Validação Amarisoft</title>
<style>body{font:16px system-ui;max-width:1500px;margin:32px auto;padding:0 20px;background:#f5f7fa;color:#182334}img{width:100%;background:white;margin:16px 0}pre{white-space:pre-wrap}a{color:#2166ac}</style>
<h1>Validação offline · Amarisoft metrics3</h1>
<p>Reutiliza os validadores existentes: decisões independentes por linha, sem reproduzir a histerese e a agregação por célula do controlador online. Diferença de MCS não é erro de medição nem prova de ganho na rede.</p>
<p>Todas as linhas válidas entram nas distribuições. Séries temporais separadas por UE mostram mediana e percentis 10–90 por janela; picos raros podem ficar fora dessa faixa. BLER médio é a média das janelas válidas, sem ponderação por transmissões. Linhas ignoradas não equivalem a BLER zero.</p>
<p><a href="bler_validation.csv">CSV BLER/DL</a> · <a href="snr_validation.csv">CSV SINR/UL</a> · <a href="summary.json">Resumo JSON</a></p>"""
    html += "<p>BLER/CQI avalia dl_mcs (downlink); SINR avalia ul_mcs (uplink). "
    html += ("BLER = dl_err / dl_tx em cada registro; sem subtração entre leituras. "
             if args.bler_mode == "totals" else "BLER = Δdl_err / Δdl_tx entre leituras. ")
    html += "Registros sem transmissões ou com contadores inválidos são ignorados.</p>"
    html += "<pre>" + json.dumps(summary, indent=2, ensure_ascii=False) + "</pre>"
    html += "".join(f'<a href="{name}"><img src="{name}" loading="lazy"></a>' for name in images)
    (output / "index.html").write_text(html, encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Relatório: {output / 'index.html'}")


if __name__ == "__main__":
    main()
