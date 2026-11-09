# Amarisoft Scripts

Scripts Python para experimentos de adaptação de modulação e codificação (AMC) em redes Amarisoft, usando lógica fuzzy e a API remota WebSocket do eNB/gNB. O projeto permite ajustar MCS de downlink por BLER/CQI e MCS de uplink por SINR, coletar telemetria em CSV e gerar gráficos para comparar experimentos.

## Estrutura

| Arquivo | Função |
| --- | --- |
| `fuzzy_bler.py` | Controlador fuzzy por BLER e CQI; também implementa o cliente `RemoteAPI` compartilhado. |
| `fuzzy_snr.py` | Controlador fuzzy de uplink por SINR em dB, com limite de MCS baseado em uma tabela de limiares. |
| `metrics_collector.py` | Coleta passiva de métricas, com uma linha por UE/célula. |
| `validate_fuzzy_snr.py` | Reproduz o fuzzy por SNR offline a partir dos CSVs coletados. |
| `plot_metrics.py` | Gera gráficos PNG a partir de um ou mais CSVs do coletor. |
| `TestScript.py` | Envia uma mensagem JSON à API WebSocket e imprime a resposta. |
| `fuzzy_old.py` | Implementação antiga, mantida como referência. |
| `tests/` | Testes unitários de inferência, controle e coleta. |

## Requisitos e instalação

- Python 3 com `pip` e suporte a ambientes virtuais.
- Acesso de rede à API WebSocket Amarisoft para coleta e controle.
- API retornando `ready` com tipo `ENB`, e suporte a `ue_get` e, para controle, `config_set`.

Na raiz do projeto, em Linux/macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install numpy scipy scikit-fuzzy networkx websocket-client matplotlib
```

As dependências ainda não possuem versões fixadas no repositório. O pacote que fornece o módulo `websocket` é `websocket-client`.

Os scripts de controle e coleta usam por padrão `ws://172.16.2.226:9001`. Substitua o endereço com `--url` conforme seu ambiente. O cliente compartilhado detecta exigência de autenticação e encerra com erro; ele não implementa a autenticação.

## Controle fuzzy por SNR

```sh
python fuzzy_snr.py --url ws://172.16.2.226:9001 --snr-field pusch_snr --max-mcs 28
```

O controlador consulta `ue_get` com estatísticas e espera 0,5 segundo entre ciclos. Para cada célula, utiliza o menor `pusch_snr` e o menor `ul_mcs` reportados entre seus UEs. O campo selecionado deve existir dentro das métricas de cada célula e conter um valor em dB no intervalo de -20 a 40.

- SNR baixo reduz o MCS; SNR alto pode aumentá-lo.
- Aumentos exigem três amostras consecutivas com SNR acima de 15 dB.
- Abaixo de 5 dB, o ajuste força uma redução de pelo menos um índice, respeitando o limite inferior.
- O MCS de uplink fica entre 0 e `--max-mcs` e também respeita o teto da tabela de limiares presente no código.
- Métricas ausentes ou inválidas impedem o ajuste da célula naquele ciclo.

O padrão da linha de comando e da classe `FuzzyController` é `pusch_snr`. Confirme o significado e a unidade do campo disponível na sua instalação: `pusch_snr` é uma medida de uplink usada aqui para orientar o MCS de uplink. Os limiares são experimentais e precisam de calibração. O laço de controle usa o teto calculado para uma camada.

## Controle fuzzy por BLER e CQI

```sh
python fuzzy_bler.py --url ws://172.16.2.226:9001 --bler-field dl_bler --max-mcs 28
```

O controlador espera um segundo entre ciclos e utiliza o maior BLER, o menor CQI e o menor `dl_mcs` de cada célula. O BLER deve ser uma fração entre 0 e 1, e o CQI deve estar entre 0 e 15.

Quando `dl_bler` está ausente ou é `null`, o script tenta calcular o BLER por janela:

```text
BLER = variação de dl_err / variação de dl_tx
```

Os campos dos contadores podem ser configurados:

```sh
python fuzzy_bler.py --url ws://172.16.2.226:9001 --tx-field dl_tx --err-field dl_err
```

A primeira leitura de contadores estabelece a referência. Sem novas transmissões, com contadores reiniciados ou métricas inválidas, a célula não é ajustada. Um BLER presente, mas inválido, também bloqueia o ajuste.

BLER acima de 10% força uma redução de pelo menos um índice, respeitando o limite inferior. Aumentos exigem três amostras consecutivas abaixo de 5%. O teto de MCS também depende da tabela heurística de CQI definida no código.

## Escopo do controle e encerramento

O controlador por BLER envia `config_set` com `cells.<cell_id>.pdsch_mcs`; o controlador por SINR envia `cells.<cell_id>.pusch_mcs`. A alteração ocorre por célula e afeta todos os seus UEs. Execute um controlador por vez para evitar comandos concorrentes sobre a mesma célula.

Use `Ctrl+C` para encerrar. O MCS forçado permanece no eNB/gNB após o encerramento. Para devolver uma célula ao controle nativo do uplink, envie `pusch_mcs=-1`, substituindo o endereço e o ID da célula:

```sh
python TestScript.py 172.16.2.226:9001 '{"message":"config_set","cells":{"1":{"pusch_mcs":-1}}}'
```

## Coleta de métricas

O coletor consulta a API sem enviar decisões de AMC. Exemplo de coleta durante 60 segundos:

```sh
python metrics_collector.py --url ws://172.16.2.226:9001 --output native.csv --run-label native --interval 1 --duration 60
```

Também é possível limitar o número de consultas:

```sh
python metrics_collector.py --output fuzzy_snr.csv --run-label fuzzy_snr --interval 1 --samples 60
```

Informe `--duration` em segundos ou `--samples` em número de consultas. Se ambos forem usados, a coleta termina no primeiro limite atingido. O intervalo deve ser positivo. O arquivo de saída é sobrescrito a cada execução.

O CSV inclui horário UTC, tempo decorrido, identificação da execução, RNTI, célula, CQI, MCS, SNR, BLER, contadores e `raw_metrics` com os dados em JSON. Campos não fornecidos pela API ficam vazios; o coletor não calcula BLER a partir dos contadores.

Para comparar o controle nativo com os controladores fuzzy, faça uma coleta de referência com a adaptação nativa habilitada. Depois execute cada controlador junto do coletor em outro terminal, usando rótulos e arquivos diferentes e condições de experimento comparáveis. O parâmetro `--run-label` apenas identifica os dados; ele não inicia um controlador.

## Geração de gráficos

```sh
python plot_metrics.py native.csv fuzzy_snr.csv --output-dir graphs
```

Por padrão, são gerados gráficos de `dl_mcs` contra `cqi`, `snr`, `pusch_snr` e `dl_bler`, além de `mcs_vs_time.png`. As séries são agrupadas por rótulo de execução, célula e RNTI. Valores ausentes ou não numéricos são ignorados.

Para selecionar métricas:

```sh
python plot_metrics.py native.csv fuzzy_snr.csv --output-dir graphs --metrics cqi pusch_snr
```

## Validação offline do fuzzy por SNR

Use os CSVs coletados para reproduzir a decisão do fuzzy sem enviar comandos ao
Amarisoft. O validador prioriza `pusch_snr` e usa `snr` como fallback. Para cada
linha válida, calcula o delta fuzzy, o limite máximo de MCS da tabela SINR e o
MCS de uplink proposto a partir do `ul_mcs` observado na coleta:

```sh
python validate_fuzzy_snr.py amarisoft_metrics.csv amarisoft_metrics1.csv \
	amarisoft_metrics2.csv --output fuzzy_snr_validation.csv
```

O resumo mostra o erro médio absoluto entre o MCS de uplink proposto e o observado e a
porcentagem de observações que respeitam o limite da tabela SINR. Essa é uma
validação offline das regras e dos valores coletados; para medir o efeito
causal do controlador, compare uma coleta `native` com outra feita enquanto o
`fuzzy_snr` estiver ativo, sob condições equivalentes.

## Validação offline do fuzzy por BLER

Para validar o controlador que usa BLER e CQI, execute:

```sh
python validate_fuzzy_bler.py amarisoft_metrics.csv amarisoft_metrics1.csv \
	amarisoft_metrics2.csv --output fuzzy_bler_validation.csv
```

O validador usa `dl_bler` quando disponível. Quando esse campo está vazio,
calcula o BLER pela variação de `dl_err/dl_tx`, como o controlador. O `cqi_mcs_limit`
é o MCS máximo permitido pela tabela `CQI_TO_MCS`, e a decisão reproduzida é
comparada com o `dl_mcs` observado.

## Consulta manual à API

O utilitário recebe o endereço sem o prefixo `ws://` e a mensagem JSON:

```sh
python TestScript.py 172.16.2.226:9001 '{"message":"ue_get","stats":true}'
```

Ele é um utilitário simples de diagnóstico; o cliente com correlação de respostas por `message_id` está em `fuzzy_bler.py`.

## Testes

Os testes dos módulos disponíveis podem ser executados sem conexão com o equipamento:

```sh
python -m unittest discover -s tests -p 'test_fuzzy*.py'
python -m unittest discover -s tests -p 'test_metrics_collector.py'
```

O arquivo `tests/test_amc.py` importa `AMCBasedMitigation`, que não está presente nesta versão do repositório. Por isso, a descoberta completa com `python -m unittest discover -s tests` depende da restauração ou atualização desse módulo/teste.
