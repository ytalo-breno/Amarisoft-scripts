"""BLER UL (CRC) e estimativa DL baseada em retransmissões, por entrada.

UL = 100 * ul_retx / (ul_tx + ul_retx).
DL estimada = 100 * dl_retx / (dl_tx + dl_retx).
DL não mede a BLER exata da primeira transmissão: uma mesma TB pode causar
várias retransmissões. dl_err/ul_err são falhas finais e não entram na fórmula.
Referência: https://tech-academy.amarisoft.com/lteenb.doc (ue_get).
Contagens são usadas por registro, sem diferenças entre entradas sucessivas.
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


def bler(tx, retx):
    return 100 * retx / (tx + retx) if tx + retx else math.nan


def read_samples(path, direction, ue_index, cell_id):
    samples = {}
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        fields = ('elapsed_s', f'{direction}_tx', f'{direction}_retx')
        required = {'sample_id', 'ue_index', 'cell_id', *fields}
        if required - set(reader.fieldnames or []):
            raise ValueError(f'{path}: colunas ausentes: {required - set(reader.fieldnames or [])}')
        for row in reader:
            if int(row['ue_index']) != ue_index or int(row['cell_id']) != cell_id:
                continue
            sample = int(row['sample_id'])
            values = tuple(float(row[field]) for field in fields)
            if sample < 0 or not all(math.isfinite(v) and v >= 0 for v in values):
                raise ValueError(f'{path}: métrica inválida na amostra {sample}')
            if sample in samples:
                raise ValueError(f'{path}: amostra duplicada: {sample}')
            samples[sample] = (*values, bler(values[1], values[2]))
    if not samples:
        raise ValueError(f'{path}: nenhum registro para UE/célula selecionados')
    return samples


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: '' if isinstance(v, float) and not math.isfinite(v) else v
                         for k, v in row.items()} for row in rows)


def generate(base, snr, cqi, output, ue_index=0, cell_id=1):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(16, 9), sharex='row')
    summary = []
    for column, (direction, label, path, color) in enumerate(
            [('ul', 'SNR', snr, '#d55e00'), ('dl', 'CQI', cqi, '#0072b2')]):
        data = {'Base': read_samples(base, direction, ue_index, cell_id),
                label: read_samples(path, direction, ue_index, cell_id)}
        samples = np.arange(min(min(d) for d in data.values()),
                            max(max(d) for d in data.values()) + 1)
        aligned = {name: np.array([d.get(int(i), (math.nan,) * 4) for i in samples])
                   for name, d in data.items()}
        title = 'UL: BLER por CRC' if direction == 'ul' else 'DL: BLER estimada por retransmissões'
        for name, values in aligned.items():
            axes[0, column].plot(samples, values[:, 3], label=name,
                                 color='#546e7a' if name == 'Base' else color,
                                 linewidth=.8, marker='.', markersize=2)
        axes[0, column].set(title=title, ylabel='BLER (%)', ylim=(0, 100))
        axes[0, column].legend()
        delta = aligned[label][:, 3] - aligned['Base'][:, 3]
        axes[1, column].axhline(0, color='#444444', linewidth=1)
        axes[1, column].plot(samples, delta, color=color, linewidth=.8,
                             marker='.', markersize=2)
        axes[1, column].set(title=f'{label} − Base', ylabel='Diferença (pontos percentuais)',
                            xlabel='Índice da amostra (sample_id)')
        for axis in axes[:, column]:
            axis.grid(alpha=.2)
        rows = []
        for pos, sample in enumerate(samples):
            row = {'sample_id': int(sample)}
            for name, values in aligned.items():
                for key, value in zip(('elapsed_s', 'tx', 'retx', 'bler_pct'), values[pos]):
                    row[f'{name.lower()}_{key}'] = float(value)
            row['diferenca_pp'] = float(delta[pos])
            rows.append(row)
        write_csv(output / f'bler_{direction}_entrada_a_entrada.csv', rows)
        # Resumo usa somente pares com tráfego em ambas as coletas.
        paired = np.isfinite(aligned['Base'][:, 3]) & np.isfinite(aligned[label][:, 3])
        for name, values in aligned.items():
            selected = values[paired]
            tx, retx = selected[:, 1].sum(), selected[:, 2].sum()
            summary.append(dict(direcao=direction.upper(), cenario=name,
                                metrica='BLER CRC' if direction == 'ul' else 'BLER estimada retx',
                                amostras_pareadas=int(paired.sum()), soma_tx=float(tx),
                                soma_retx=float(retx), bler_ponderada_pct=bler(tx, retx)))
    fig.suptitle(f'Comparação com a Base — UE {ue_index}, célula {cell_id}')
    fig.text(.5, .015, 'UL: 100 × retx/(tx+retx). DL: mesma razão como estimativa; '
             'não é BLER da primeira transmissão.\nColetas independentes pareadas por sample_id; '
             'ausências e denominador zero ficam como lacunas.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .065, 1, .95))
    for extension in ('png', 'pdf'):
        fig.savefig(output / f'bler_comparacao_entradas.{extension}', dpi=180)
    plt.close(fig)
    write_csv(output / 'resumo_bler.csv', summary)
    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    for column, axis in enumerate(axes):
        pair = summary[column * 2:column * 2 + 2]
        bars = axis.bar([r['cenario'] for r in pair],
                        [r['bler_ponderada_pct'] for r in pair],
                        color=['#546e7a', '#d55e00' if column == 0 else '#0072b2'])
        axis.bar_label(bars, fmt='%.2f%%', padding=4)
        axis.set(title='UL — SNR' if column == 0 else 'DL — CQI (estimativa)',
                 ylabel='BLER ponderada (%)', ylim=(0, 100))
        axis.grid(axis='y', alpha=.2)
        axis.set_axisbelow(True)
    fig.suptitle('Razão das somas nas amostras pareadas com tráfego')
    fig.tight_layout()
    for extension in ('png', 'pdf'):
        fig.savefig(output / f'bler_resumo.{extension}', dpi=180)
    plt.close(fig)
    for row in summary:
        print(row)
    print(f'Arquivos gerados em {output.resolve()}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='amarisoft_metrics_base_close.csv')
    parser.add_argument('--snr', default='amarisoft_metrics_snr_close.csv')
    parser.add_argument('--cqi', default='amarisoft_metrics_cqi2.csv')
    parser.add_argument('--ue-index', type=int, default=0)
    parser.add_argument('--cell-id', type=int, default=1)
    parser.add_argument('--output-dir', default='graphs/bler')
    args = parser.parse_args()
    generate(args.base, args.snr, args.cqi, args.output_dir, args.ue_index, args.cell_id)
