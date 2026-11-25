"""Compara dl_retx e ul_retx por sample_id em coletas independentes.

O pareamento representa a posição da amostra em cada ensaio, não instantes
simultâneos ou condições de rádio idênticas. Os valores reportados são usados
diretamente, sem diferenciar contadores, interpolar ou calcular médias.
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


def read_entries(path, ue_index, cell_id):
    entries = {}
    excluded = 0
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        required = {'sample_id', 'ue_index', 'cell_id', 'elapsed_s', 'dl_retx', 'ul_retx'}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f'{path}: colunas ausentes: {sorted(missing)}')
        for line, row in enumerate(reader, start=2):
            if int(row['ue_index']) != ue_index or int(row['cell_id']) != cell_id:
                excluded += 1
                continue
            sample = int(row['sample_id'])
            values = tuple(float(row[key]) for key in ('elapsed_s', 'dl_retx', 'ul_retx'))
            if sample < 0 or not all(math.isfinite(v) and v >= 0 for v in values):
                raise ValueError(f'{path}:{line}: amostra ou métrica inválida')
            if sample in entries:
                raise ValueError(f'{path}:{line}: sample_id duplicado: {sample}')
            entries[sample] = values
    if not entries:
        raise ValueError(f'{path}: nenhum registro para UE {ue_index}, célula {cell_id}')
    print(f'{path}: {len(entries)} entradas selecionadas; {excluded} excluídas por UE/célula')
    return entries


def generate(paths, output, ue_index=0, cell_id=1):
    datasets = {label: read_entries(path, ue_index, cell_id) for label, path in paths.items()}
    # Índices inteiros intermediários preservam lacunas também quando todas as
    # coletas perderam o mesmo sample_id.
    samples = np.arange(min(min(d) for d in datasets.values()),
                        max(max(d) for d in datasets.values()) + 1)
    aligned = {label: np.array([data.get(int(i), (np.nan,) * 3) for i in samples])
               for label, data in datasets.items()}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    colors = {'Base': '#546e7a', 'SNR': '#d55e00', 'CQI': '#0072b2'}
    plt.rcParams.update({'font.size': 11, 'axes.spines.top': False,
                         'axes.spines.right': False})

    def save(fig, name):
        fig.suptitle(f'Retransmissões por entrada — UE {ue_index}, célula {cell_id}')
        fig.text(.5, .015, 'Pareamento por sample_id em coletas independentes; '
                 'lacunas indicam amostras ausentes.', ha='center', fontsize=9)
        fig.tight_layout(rect=(0, .045, 1, .95))
        for extension in ('png', 'pdf'):
            fig.savefig(output / f'{name}.{extension}', dpi=180, bbox_inches='tight')
        plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)
    for index, axis in enumerate(axes, start=1):
        for label, data in aligned.items():
            axis.plot(samples, data[:, index], label=label, color=colors[label],
                      linewidth=.85, marker='.', markersize=2, alpha=.85)
        axis.set(title='Downlink (dl_retx)' if index == 1 else 'Uplink (ul_retx)',
                 ylabel='Retransmissões reportadas', ylim=(0, None))
        axis.grid(alpha=.2)
        axis.legend()
    axes[-1].set_xlabel('Índice da amostra (sample_id)')
    save(fig, 'retransmissoes_entrada_a_entrada')

    fig, axes = plt.subplots(2, 2, figsize=(16, 9), sharex=True, sharey='row')
    for index, direction in enumerate(('DL', 'UL'), start=1):
        for column, label in enumerate(('SNR', 'CQI')):
            axis = axes[index - 1, column]
            delta = aligned[label][:, index] - aligned['Base'][:, index]
            axis.axhline(0, color='#444444', linewidth=1)
            axis.plot(samples, delta, color=colors[label], linewidth=.85,
                      marker='.', markersize=2)
            axis.set_title(f'{direction}: {label} − Base')
            axis.set_ylabel('Diferença de retransmissões')
            axis.grid(alpha=.2)
            if index == 2:
                axis.set_xlabel('Índice da amostra (sample_id)')
    save(fig, 'diferencas_entrada_a_entrada')

    csv_path = output / 'comparacao_entrada_a_entrada.csv'
    with csv_path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['sample_id'] +
                        [f'{label.lower()}_{field}' for label in aligned
                         for field in ('elapsed_s', 'dl_retx', 'ul_retx')] +
                        [f'{label.lower()}_menos_base_{direction}_retx'
                         for label in ('SNR', 'CQI') for direction in ('dl', 'ul')])
        for position, sample in enumerate(samples):
            values = [v for data in aligned.values() for v in data[position]]
            values += [aligned[label][position, i] - aligned['Base'][position, i]
                       for label in ('SNR', 'CQI') for i in (1, 2)]
            writer.writerow([int(sample)] + [v if np.isfinite(v) else '' for v in values])
    common = set.intersection(*(set(data) for data in datasets.values()))
    print(f'{len(common)} sample_ids presentes nas três coletas. Saída: {output.resolve()}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='amarisoft_metrics_base_close.csv')
    parser.add_argument('--snr', default='amarisoft_metrics_snr_close.csv')
    parser.add_argument('--cqi', default='amarisoft_metrics_cqi2.csv')
    parser.add_argument('--ue-index', type=int, default=0)
    parser.add_argument('--cell-id', type=int, default=1)
    parser.add_argument('--output-dir', default='graphs/retransmissions/entries')
    args = parser.parse_args()
    generate({'Base': args.base, 'SNR': args.snr, 'CQI': args.cqi},
             args.output_dir, args.ue_index, args.cell_id)
