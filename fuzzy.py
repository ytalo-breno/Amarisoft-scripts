"""AMC fuzzy experimental por célula, com BLER válido em fração [0, 1].

O campo selecionado por --bler-field pode ser fornecido pela versão instalada.
Quando ele não existe, o BLER é calculado por janela como delta de dl_err
dividido por delta de dl_tx. Sem uma janela válida, a célula não é alterada.
O comando afeta todos os seus UEs.

A restrição CQI/MCS importada do AMC é heurística: calibre-a para as tabelas
da rede. Ao encerrar, o MCS forçado persiste; pdsch_mcs=-1 libera o controle
nativo. Autenticação, quando exigida, precisa de cliente autenticado.
"""
import argparse
import json
import logging
import math
import time
import itertools
import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl
import websocket



WS_URL = "ws://172.16.2.226:9001"
TARGET_BLER = 0.10
RECOVERY_BLER = 0.05
RECOVERY_SAMPLES = 3
CQI_TO_MCS = {1: 0, 2: 0, 3: 2, 4: 4, 5: 6, 6: 8, 7: 11,
              8: 14, 9: 17, 10: 20, 11: 23, 12: 25, 13: 27, 14: 28, 15: 28}

class RemoteAPI:
    def __init__(self, url, timeout=5):
        self.timeout = timeout
        self.ids = itertools.count(1)
        self.ws = websocket.create_connection(url, timeout=timeout)
        try:
            hello = self.receive()
            if hello.get("message") == "authenticate":
                raise APIError("API exige autenticação; configure um cliente autenticado")
            if hello.get("message") != "ready" or hello.get("type") != "ENB":
                raise APIError("endpoint não é uma API eNB/gNB pronta")
        except Exception:
            self.close()
            raise

    def receive(self):
        raw = self.ws.recv()
        if not raw:
            raise APIError("WebSocket encerrado")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise APIError("resposta JSON não é um objeto")
        return result

    def request(self, message, **params):
        request_id = next(self.ids)
        self.ws.send(json.dumps(dict(params, message=message, message_id=request_id)))
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise APIError(f"timeout aguardando {message}")
                self.ws.settimeout(remaining)
                result = self.receive()
                if result.get("message_id") != request_id or result.get("notification"):
                    continue
                if result.get("error"):
                    raise APIError(str(result["error"]))
                if result.get("message") != message:
                    raise APIError("resposta incompatível com a requisição")
                return result
        finally:
            self.ws.settimeout(self.timeout)

    def close(self):
        self.ws.close()

class APIError(RuntimeError):
    pass

def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("métrica ausente ou não numérica")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("métrica fora do intervalo")
    return value


def counter(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"contador {field} ausente ou não numérico")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"contador {field} inválido")
    return value


def get_max_mcs_for_cqi(cqi):
    # CQI 0 indica fora de alcance; permite apenas o MCS mínimo experimental.
    return CQI_TO_MCS.get(math.floor(number(cqi, 0, 15)), 0)


# Partições sobrepostas, incluindo CQI 0 e todos os extremos do universo.
bler = ctrl.Antecedent(np.linspace(0, 1, 101), 'bler')
cqi = ctrl.Antecedent(np.arange(0, 16), 'cqi')
mcs_delta = ctrl.Consequent(np.linspace(-4, 2, 121), 'mcs_delta')
bler['baixo'] = fuzz.trapmf(bler.universe, [0, 0, 0.03, 0.10])
bler['medio'] = fuzz.trimf(bler.universe, [0.03, 0.10, 0.30])
bler['alto'] = fuzz.trapmf(bler.universe, [0.10, 0.30, 1, 1])
cqi['ruim'] = fuzz.trapmf(cqi.universe, [0, 0, 2, 6])
cqi['razoavel'] = fuzz.trimf(cqi.universe, [4, 8, 12])
cqi['bom'] = fuzz.trapmf(cqi.universe, [10, 13, 15, 15])
mcs_delta['reduz_muito'] = fuzz.trimf(mcs_delta.universe, [-4, -4, -2])
mcs_delta['reduz_pouco'] = fuzz.trimf(mcs_delta.universe, [-3, -1, 0])
mcs_delta['mantem'] = fuzz.trimf(mcs_delta.universe, [-1, 0, 1])
mcs_delta['aumenta'] = fuzz.trimf(mcs_delta.universe, [0, 2, 2])

# BLER alto independe de CQI; as outras duas faixas cobrem os três CQIs.
amc_ctrl = ctrl.ControlSystem([
    ctrl.Rule(bler['alto'], mcs_delta['reduz_muito']),
    ctrl.Rule(bler['medio'] & cqi['ruim'], mcs_delta['reduz_muito']),
    ctrl.Rule(bler['medio'] & cqi['razoavel'], mcs_delta['reduz_pouco']),
    ctrl.Rule(bler['medio'] & cqi['bom'], mcs_delta['reduz_pouco']),
    ctrl.Rule(bler['baixo'] & cqi['ruim'], mcs_delta['mantem']),
    ctrl.Rule(bler['baixo'] & (cqi['razoavel'] | cqi['bom']), mcs_delta['aumenta']),
])


def infer_delta(current_bler, current_cqi):
    """Inferência isolada: entradas inválidas e saída ausente não viram ação."""
    current_bler = number(current_bler, 0, 1)
    current_cqi = number(current_cqi, 0, 15)
    sim = ctrl.ControlSystemSimulation(amc_ctrl, clip_to_bounds=False)
    sim.input['bler'] = current_bler
    sim.input['cqi'] = current_cqi
    sim.compute()
    output = sim.output.get('mcs_delta')
    if output is None or not math.isfinite(output):
        raise ValueError("inferência fuzzy sem saída válida")
    return int(round(output))


class FuzzyController:
    def __init__(self, api, bler_field="dl_bler", max_mcs=28,
                 tx_field="dl_tx", err_field="dl_err"):
        self.api = api
        self.bler_field = bler_field
        self.tx_field = tx_field
        self.err_field = err_field
        self.max_mcs = int(number(max_mcs, 0, 28))
        self.stable = {}
        self.counter_history = {}

    def _window_bler(self, sample_key, sample):
        tx = counter(sample.get(self.tx_field), self.tx_field)
        errors = counter(sample.get(self.err_field), self.err_field)
        if errors > tx:
            raise ValueError("contador de erros maior que transmissões")
        previous = self.counter_history.get(sample_key)
        self.counter_history[sample_key] = (tx, errors)
        if previous is None:
            raise ValueError("janela BLER ainda não disponível")
        previous_tx, previous_errors = previous
        delta_tx = tx - previous_tx
        delta_errors = errors - previous_errors
        if delta_tx <= 0 or delta_errors < 0:
            raise ValueError("contadores reiniciados ou sem novas transmissões")
        if delta_errors > delta_tx:
            raise ValueError("delta de erros maior que delta de transmissões")
        return number(delta_errors / delta_tx, 0, 1)

    def _read_bler(self, sample_key, sample):
        if self.bler_field and sample.get(self.bler_field) is not None:
            return number(sample.get(self.bler_field), 0, 1)
        return self._window_bler(sample_key, sample)

    def poll(self):
        response = self.api.request("ue_get", stats=True)
        #logging.info("Resposta ue_get: %s", response)
        ues = response.get("ue_list")
        if not isinstance(ues, list):
            raise APIError("ue_get não retornou ue_list")
        groups = {}
        active_samples = set()
        for ue_index, ue in enumerate(ues):
            if not isinstance(ue, dict) or not isinstance(ue.get("cells"), list):
                raise APIError("UE sem estrutura cells válida")
            ue_key = ue.get("rnti", ue_index)
            for cell_index, cell in enumerate(ue["cells"]):
                if not isinstance(cell, dict):
                    raise APIError("métricas de célula inválidas")
                cell_id = cell.get("cell_id")
                if isinstance(cell_id, bool) or not isinstance(cell_id, int):
                    raise APIError("cell_id inválido")
                sample_key = (ue_key, cell_index, cell_id)
                sample = dict(ue)
                sample.update(cell)
                groups.setdefault(cell_id, []).append((sample_key, sample))
                active_samples.add(sample_key)
        self.counter_history = {
            key: value for key, value in self.counter_history.items()
            if key in active_samples
        }
        self.stable = {key: value for key, value in self.stable.items() if key in groups}
        for cell_id, entries in groups.items():
            try:
                # Valida TODOS os UEs; uma amostra ausente impede o ajuste global.
                measured_bler = max(self._read_bler(sample_key, sample)
                                    for sample_key, sample in entries)
                samples = [sample for _, sample in entries]
                measured_cqi = min(number(s.get("cqi"), 0, 15) for s in samples)
                current_mcs = math.floor(min(number(s.get("dl_mcs"), 0, 28) for s in samples))
                cap = min(self.max_mcs, get_max_mcs_for_cqi(measured_cqi))
                delta = infer_delta(measured_bler, measured_cqi)
            except ValueError as exc:
                self.stable.pop(cell_id, None)
                logging.warning("Célula %s: sem ajuste (%s); confira %s, %s, %s, CQI e MCS.",
                                cell_id, exc, self.bler_field, self.tx_field, self.err_field)
                continue
            self.stable[cell_id] = (self.stable.get(cell_id, 0) + 1
                                    if measured_bler < RECOVERY_BLER else 0)
            # Não aumenta no alvo/fora da margem; exige três amostras saudáveis.
            if delta > 0 and self.stable[cell_id] < RECOVERY_SAMPLES:
                delta = 0
            if measured_bler > TARGET_BLER:
                delta = min(delta, -1)
            proposed = int(max(0, min(cap, current_mcs + delta)))
            if proposed == current_mcs:
                continue
            # Falhas são propagadas: não se presume que o gNB aplicou a decisão.
            self.api.request("config_set", cells={str(cell_id): {"pdsch_mcs": proposed}})
            self.stable[cell_id] = 0
            logging.info("Célula %s: BLER %.3f, CQI %.2f, delta %s, MCS %s -> %s",
                         cell_id, measured_bler, measured_cqi, delta, current_mcs, proposed)


def run_fuzzy_xapp(url=WS_URL, bler_field="dl_bler", tx_field="dl_tx",
                   err_field="dl_err", max_mcs=28):
    api = None
    try:
        api = RemoteAPI(url)
        controller = FuzzyController(api, bler_field, max_mcs, tx_field, err_field)
        logging.info("AMC fuzzy por célula iniciado; BLER por métrica ou janela de contadores.")
        while True:
            controller.poll()
            time.sleep(1)
    finally:
        if api is not None:
            api.close()
        logging.warning("Confira as células alteradas: MCS forçado persiste no gNB. "
                        "pdsch_mcs=-1 libera a adaptação nativa.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=WS_URL)
    parser.add_argument("--bler-field", default="dl_bler", help="campo por UE/célula em fração [0, 1]")
    parser.add_argument("--tx-field", default="dl_tx", help="contador acumulado de transmissões")
    parser.add_argument("--err-field", default="dl_err", help="contador acumulado de erros")
    parser.add_argument("--max-mcs", type=int, choices=range(29), default=28)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        run_fuzzy_xapp(args.url, args.bler_field, args.tx_field, args.err_field, args.max_mcs)
    except KeyboardInterrupt:
        pass
    except (APIError, ValueError, OSError, websocket.WebSocketException) as exc:
        logging.error("Controle interrompido: %s", exc)
        raise SystemExit(1)
