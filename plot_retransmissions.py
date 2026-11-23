"""Compara registros de retransmissão Base/CQI/SNR, sem diferenciar contadores.

Os CSVs são tratados como contagens reportadas por amostra, não contadores
acumulados. Somas representam somente os registros capturados. Confirmar a
janela da API na versão instalada antes de interpretá-las como total do ensaio.
"""
import argparse
import csv
import math
import os
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR', '/tmp/amarisoft-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def read_samples(path):
    groups = {}
    seen = set()
    with open(path, newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            key = (row['sample_id'], row['cell_id'], row['rnti'])
            if key in seen:
                raise ValueError(f'Registro duplicado em {path}: {key}')
            seen.add(key)
            values = [float(row[field]) for field in ('elapsed_s', 'dl_retx', 'ul_retx', 'dl_tx')]
            if not all(math.isfinite(v) and v >= 0 for v in values):
                raise ValueError(f'Métrica inválida em {path}: {key}')
            t, dl, ul, tx = values
            point = groups.setdefault(row['sample_id'], [t, 0, 0, 0])
            point[1] += dl
            point[2] += ul
            point[3] += tx
    if not groups:
        raise ValueError(f'CSV vazio: {path}')
    return np.array(sorted(groups.values()))


def generate(paths, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    datasets = {label: read_samples(path) for label, path in paths.items()}
    colors = ['#546e7a', '#0072b2', '#d55e00']
    plt.rcParams.update({'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False})
    summary = []
    for label, data in datasets.items():
        summary.append(dict(cenario=label, arquivo=str(paths[label]), amostras=len(data),
                            inicio_s=data[0, 0], fim_s=data[-1, 0],
                            soma_dl=data[:, 1].sum(), soma_ul=data[:, 2].sum(),
                            media_dl=data[:, 1].mean(), media_ul=data[:, 2].mean()))
    with (output / 'resumo.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)

    def save(fig, name, note):
        fig.text(.5, .015, note, ha='center', fontsize=9, color='#444444')
        fig.tight_layout(rect=(0, .07, 1, .94))
        for suffix in ('png', 'pdf'):
            fig.savefig(output / f'{name}.{suffix}', dpi=180, bbox_inches='tight')
        plt.close(fig)

    labels = list(datasets)
    def decimal(value):
        return f'{value:.1f}'.replace('.', ',')

    # Resumo: apenas uma métrica por painel, com valores e referência explícitos.
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for index, axis in enumerate(axes, start=1):
        values = [data[:, index].mean() for data in datasets.values()]
        axis.barh(labels, values, color=colors, height=.55)
        axis.invert_yaxis()
        axis.set_xlim(0, max(values) * 1.48)
        for y, value in enumerate(values):
            change = 100 * (value / values[0] - 1) if values[0] else None
            suffix = '' if y == 0 or change is None else f'  ({decimal(change)}% vs. Base)'
            axis.text(value + max(values)*.02, y, decimal(value) + suffix, va='center', fontsize=11)
        axis.set_title('Downlink' if index == 1 else 'Uplink', loc='left', weight='bold')
        axis.set_xlabel('Contagem média reportada por amostra')
        axis.grid(axis='x', alpha=.15)
        axis.set_axisbelow(True)
    fig.suptitle('CQI tem menor contagem média no DL; SNR, no UL', fontsize=17, weight='bold')
    save(fig, 'retransmissoes_resumo', 'Coletas independentes de ~10 min. Contagens menores não demonstram, isoladamente, maior eficiência.')

    # Médias em janelas fixas; lacunas ficam como NaN, nunca como zero.
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    bin_width = 30
    bins = int(max(data[-1, 0] for data in datasets.values()) // bin_width) + 1
    centers = (np.arange(bins) + .5) * bin_width / 60
    for index, axis in enumerate(axes, start=1):
        for (label, data), color in zip(datasets.items(), colors):
            bin_ids = (data[:, 0] // bin_width).astype(int)
            means = [data[bin_ids == k, index].mean() if np.any(bin_ids == k) else np.nan
                     for k in range(bins)]
            axis.plot(centers, means, color=color, lw=2.5, marker='o', markersize=4, label=label)
        axis.set_title('Downlink' if index == 1 else 'Uplink', loc='left', weight='bold')
        axis.set_ylabel('Contagem média por amostra')
        axis.set_ylim(bottom=0)
        axis.grid(alpha=.18)
        axis.legend(frameon=False, ncol=3)
    axes[-1].set_xlabel('Tempo decorrido de cada coleta (min)')
    fig.suptitle('Evolução das retransmissões — médias a cada 30 s', fontsize=17, weight='bold')
    save(fig, 'retransmissoes_tempo', 'Agrupamento reduz ruído e pode ocultar picos. Cada curva representa uma coleta independente.')

    # DL: relação contagem/volume, sem chamar a razão de BLER ou probabilidade.
    fig, axis = plt.subplots(figsize=(10, 5))
    ratios = [100 * data[:, 1].sum() / data[:, 3].sum()
              if data[:, 3].sum() else np.nan for data in datasets.values()]
    axis.barh(labels, ratios, color=colors, height=.55)
    axis.invert_yaxis()
    axis.set_xlim(0, max(v for v in ratios if math.isfinite(v)) * 1.25)
    for y, value in enumerate(ratios):
        axis.text(value + .1, y, decimal(value), va='center', fontsize=13)
    axis.set_xlabel('100 × soma(dl_retx) / soma(dl_tx)')
    axis.grid(axis='x', alpha=.15)
    axis.set_axisbelow(True)
    fig.suptitle('Downlink: retransmissões por 100 transmissões iniciais', fontsize=16, weight='bold')
    save(fig, 'retransmissoes_normalizadas_dl', 'Razão entre registros capturados; não é BLER. Depende da janela da API e da comparabilidade dos ensaios.')
    with (output / 'comparacao_dl.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['cenario', 'soma_dl_retx', 'soma_dl_tx', 'retx_por_100_tx'])
        for (label, data), ratio in zip(datasets.items(), ratios):
            writer.writerow([label, data[:, 1].sum(), data[:, 3].sum(), ratio])
    print('Razão DL por 100 transmissões:', dict(zip(labels, ratios)))
    for row in summary:
        print(row)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='amarisoft_metrics_base_close.csv')
    parser.add_argument('--cqi', default='amarisoft_metrics_cqi.csv')
    parser.add_argument('--snr', default='amarisoft_metrics_snr_close.csv')
    parser.add_argument('--output-dir', default='graphs/retransmissions')
    args = parser.parse_args()
    generate({'Base': args.base, 'CQI': args.cqi, 'SNR': args.snr}, args.output_dir)
