"""Reproduz os gráficos de reunião com todos os RNTIs das três coletas.

Proporção por amostra: 100 * retx / (tx + retx); denominador zero não
gera ponto. Resumo: razão das somas, excluindo a primeira linha de dados
de cada CSV. O gráfico por amostra inclui essa linha, como na referência.
DL representa proporção de retransmissões, não BLER da primeira tentativa.
UL representa proporção de blocos recebidos com erro de CRC.
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
from matplotlib.ticker import FuncFormatter, MultipleLocator


INK = '#172b3d'
MUTED = '#455b76'
BASE = '#536a80'
TEAL = '#00847e'


def read_collection(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        required = {'elapsed_s', 'rnti', 'dl_tx', 'dl_retx', 'ul_tx', 'ul_retx'}
        if required - set(reader.fieldnames or []):
            raise ValueError(f'{path}: colunas ausentes')
        rows = []
        for line, row in enumerate(reader, 2):
            item = {'rnti': int(row['rnti'])}
            for key in required - {'rnti'}:
                value = float(row[key])
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f'{path}:{line}: valor inválido em {key}')
                item[key] = value
            rows.append(item)
    if len(rows) < 2:
        raise ValueError(f'{path}: são necessárias pelo menos duas linhas')
    return rows


def proportion(tx, retx):
    return 100 * retx / (tx + retx) if tx + retx else math.nan


def format_pt(value, digits=0):
    return f'{value:,.{digits}f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def style_axis(axis):
    axis.set_axisbelow(True)
    axis.grid(axis='y', color='#dfe7ef', linewidth=.8)
    axis.tick_params(axis='both', length=0, labelcolor=MUTED, pad=6)
    for spine in axis.spines.values():
        spine.set_visible(False)


def save(fig, output, name):
    for extension in ('png', 'pdf', 'svg'):
        fig.savefig(output / f'{name}.{extension}', dpi=180, facecolor='white')
    plt.close(fig)


def generate(base, snr, cqi, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    data = {label: read_collection(path) for label, path in
            [('Padrão', base), ('SNR', snr), ('CQI', cqi)]}
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'text.color': INK, 'axes.titleweight': 'bold'})
    summary = []
    for direction, algorithm in [('dl', 'CQI'), ('ul', 'SNR')]:
        for label in ('Padrão', algorithm):
            rows = data[label][1:]
            tx = sum(row[f'{direction}_tx'] for row in rows)
            retx = sum(row[f'{direction}_retx'] for row in rows)
            summary.append(dict(direcao=direction.upper(), cenario=label,
                                entradas=len(rows), tx=tx, retx=retx,
                                proporcao_pct=proportion(tx, retx)))
    with (output / 'resumo_reuniao.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)

    fig, axes = plt.subplots(2, 2, figsize=(10.5, 7.16))
    fig.subplots_adjust(left=.10, right=.97, top=.80, bottom=.17, hspace=.68, wspace=.32)
    fig.text(.10, .94, 'Comparação com o funcionamento padrão', fontsize=22, weight='bold')
    fig.text(.10, .895, 'CQI no downlink e SNR no uplink', fontsize=13, color=MUTED)
    for row_index, direction in enumerate(('downlink', 'uplink')):
        pair = summary[row_index * 2:row_index * 2 + 2]
        for column in range(2):
            axis = axes[row_index, column]
            values = [r['retx' if column == 0 else 'proporcao_pct'] for r in pair]
            axis.bar([r['cenario'] for r in pair], values, color=[BASE, TEAL], width=.5)
            axis.set_title(('Retransmissões no ' if column == 0 else
                            'Proporção de retransmissões no ') + direction,
                           loc='left', fontsize=11, pad=22)
            style_axis(axis)
            for index, value in enumerate(values):
                axis.text(index, value + max(values)*.045,
                          format_pt(value, 0 if column == 0 else 2) + ('' if column == 0 else '%'),
                          ha='center', va='bottom', weight='bold', fontsize=11)
            axis.set_ylim(0, max(values)*1.22)
            if column == 0:
                axis.yaxis.set_major_locator(MultipleLocator(30000 if row_index == 0 else 25000))
                axis.yaxis.set_major_formatter(FuncFormatter(lambda x, _: format_pt(x)))
            else:
                axis.yaxis.set_major_locator(MultipleLocator(4 if row_index == 0 else 15))
                axis.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f'{x:.0f}%'))
    fig.text(.10, .055, 'Coletas de aproximadamente 600 s. Primeira leitura de cada CSV excluída.\n'
             'Proporções calculadas sobre o total de tentativas em DL e de blocos recebidos em UL.\n'
             'No uplink, ul_retx mede blocos recebidos com erro de CRC no gNB.',
             fontsize=9.5, color=MUTED, linespacing=1.5)
    save(fig, output, 'comparacao_funcionamento_padrao')

    fig, axes = plt.subplots(3, 2, figsize=(10.7, 7.28), sharex=True, sharey=True)
    fig.subplots_adjust(left=.09, right=.97, top=.86, bottom=.165, hspace=.34, wspace=.24)
    fig.text(.09, .95, 'Indicadores de BLER por amostra', fontsize=22, weight='bold')
    palette = ['#3475a4', '#cf6b36', '#9467bd']
    for row_index, (label, rows) in enumerate(data.items()):
        rntis = sorted({row['rnti'] for row in rows})
        for column, direction in enumerate(('dl', 'ul')):
            axis = axes[row_index, column]
            for rnti, color in zip(rntis, palette):
                selected = [row for row in rows if row['rnti'] == rnti and
                            row[f'{direction}_tx'] + row[f'{direction}_retx'] > 0]
                axis.scatter([r['elapsed_s'] for r in selected],
                             [proportion(r[f'{direction}_tx'], r[f'{direction}_retx']) for r in selected],
                             s=5, color=color, alpha=.75, linewidths=0, label=str(rnti))
            style_axis(axis)
            axis.set(xlim=(-5, 605), ylim=(-3, 103))
            axis.yaxis.set_major_locator(MultipleLocator(25))
            axis.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f'{x:.0f}%'))
            axis.xaxis.set_major_locator(MultipleLocator(100))
            if column == 0:
                axis.set_ylabel(label, color='black', weight='bold', labelpad=10)
            if len(rntis) > 1:
                axis.legend(title='RNTI', loc='upper right', ncol=len(rntis),
                            fontsize=6, title_fontsize=6, fancybox=False,
                            columnspacing=1, handletextpad=.4, borderpad=.5)
            if row_index == 2:
                axis.set_xlabel('Tempo desde o início da coleta (s)', color='black', fontsize=9)
    axes[0, 0].set_title('Downlink · Proporção de retransmissões', loc='left', fontsize=11, color='black', pad=12)
    axes[0, 1].set_title('Uplink · Proporção de erros de CRC', loc='left', fontsize=11, color='black', pad=12)
    fig.text(.09, .07, 'Cada ponto representa uma linha do CSV. Amostras com tx + retx igual a zero ficam sem ponto.',
             color=MUTED, fontsize=9)
    save(fig, output, 'indicadores_bler_por_amostra')
    for row in summary:
        print(row)
    print(f'Saída: {output.resolve()}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='amarisoft_metrics_base_close.csv')
    parser.add_argument('--snr', default='amarisoft_metrics_snr_close.csv')
    parser.add_argument('--cqi', default='amarisoft_metrics_cqi2.csv')
    parser.add_argument('--output-dir', default='graphs/reuniao_reproduzida')
    args = parser.parse_args()
    generate(args.base, args.snr, args.cqi, args.output_dir)
