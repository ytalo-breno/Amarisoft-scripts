"""AMC fuzzy experimental de uplink por célula, usando SINR em dB.

O campo selecionado por --snr-field deve ser fornecido pela versão instalada
ou por um adaptador, com unidade conhecida. Sem métricas válidas, a célula não
é alterada. O comando afeta o MCS de uplink de todos os seus UEs.

Os limiares de SNR são heurísticos e devem ser calibrados para a rede. Ao
encerrar, o MCS forçado persiste; pusch_mcs=-1 libera o controle nativo.
"""
import argparse
import logging
import math
import time

import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl
import websocket

from fuzzy_bler import APIError, RemoteAPI, number

WS_URL = "ws://172.16.2.226:9001"
SNR_MIN = -20
SNR_MAX = 40
CONFIRMATION_SAMPLES = 3
SNR_MARGIN_DB = 1.0
MCS_DEADBAND = 1

# OAI gNB_scheduler_primitives.c: SINR thresholds in dB.
SINR_MCS_THRESHOLDS = (
    -1.0, -0.4, 0.6, 1.6, 2.4, 3.4, 4.2, 5.0, 5.6, 6.2,
    8.6, 9.2, 9.8, 10.4, 11.2, 11.8, 12.4, 14.0, 14.6, 15.4,
    16.2, 17.0, 17.8, 18.6, 19.4, 20.2, 21.2, 22.0, 24.5,
)

error = ctrl.Antecedent(np.arange(-28, 29), "mcs_error")
mcs_delta = ctrl.Consequent(np.linspace(-2, 2, 161), "mcs_delta")

error["acima_do_alvo"] = fuzz.trapmf(error.universe, [-28, -28, -2, -1])
error["no_alvo"] = fuzz.trapmf(error.universe, [-2, -1, 1, 2])
error["abaixo_do_alvo"] = fuzz.trapmf(error.universe, [1, 2, 28, 28])

mcs_delta["reduz"] = fuzz.trimf(mcs_delta.universe, [-2, -2, 0])
mcs_delta["mantem"] = fuzz.trimf(mcs_delta.universe, [-1, 0, 1])
mcs_delta["aumenta"] = fuzz.trimf(mcs_delta.universe, [0, 2, 2])

amc_ctrl = ctrl.ControlSystem([
    ctrl.Rule(error["acima_do_alvo"], mcs_delta["reduz"]),
    ctrl.Rule(error["no_alvo"], mcs_delta["mantem"]),
    ctrl.Rule(error["abaixo_do_alvo"], mcs_delta["aumenta"]),
])


def get_target_mcs(current_snr, max_mcs=28, snr_margin_db=SNR_MARGIN_DB):
    """Alvo heurístico com margem configurável; não representa calibração da rede."""
    current_snr = number(current_snr, SNR_MIN, SNR_MAX)
    max_mcs = int(number(max_mcs, 0, 28))
    margin = number(snr_margin_db, 0, SNR_MAX - SNR_MIN)
    return min(max_mcs, get_max_mcs_for_snr(max(SNR_MIN, current_snr - margin)))


def infer_delta(current_snr, current_mcs, max_mcs=28, snr_margin_db=SNR_MARGIN_DB):
    """Infere um passo em direção ao alvo, mantendo uma faixa de ±1 MCS."""
    current_mcs = math.floor(number(current_mcs, 0, 28))
    target = get_target_mcs(current_snr, max_mcs, snr_margin_db)
    distance = target - current_mcs
    # O teto continua obrigatório, mesmo dentro da faixa de manutenção.
    if abs(distance) <= MCS_DEADBAND and current_mcs <= max_mcs:
        return 0
    sim = ctrl.ControlSystemSimulation(amc_ctrl, clip_to_bounds=False)
    sim.input["mcs_error"] = distance
    sim.compute()
    output = sim.output.get("mcs_delta")
    if output is None or not math.isfinite(output):
        raise ValueError("inferencia fuzzy sem saida valida")
    step = int(round(output))
    if current_mcs > max_mcs:
        return -1
    return max(-2, min(2, step))


def get_max_mcs_for_snr(current_snr, layers=1):
    """Retorna o maior MCS permitido pela tabela SINR do OAI."""
    current_snr = number(current_snr, SNR_MIN, SNR_MAX)
    if isinstance(layers, bool) or layers not in (1, 2, 4):
        raise ValueError("numero de camadas invalido")
    mimo_offset = {1: 0.0, 2: 4.0, 4: 7.0}[layers]
    for mcs in range(len(SINR_MCS_THRESHOLDS) - 1, -1, -1):
        if current_snr >= SINR_MCS_THRESHOLDS[mcs] + mimo_offset:
            return mcs
    return 0


class FuzzyController:
    def __init__(self, api, snr_field="pusch_snr", max_mcs=28,
                 snr_margin_db=SNR_MARGIN_DB):
        self.api = api
        self.snr_field = snr_field
        self.max_mcs = int(number(max_mcs, 0, 28))
        self.snr_margin_db = number(snr_margin_db, 0, SNR_MAX - SNR_MIN)
        self.stable = {}

    def poll(self):
        response = self.api.request("ue_get", stats=True)
        ues = response.get("ue_list")
        if not isinstance(ues, list):
            raise APIError("ue_get nao retornou ue_list")
        groups = {}
        for ue in ues:
            if not isinstance(ue, dict) or not isinstance(ue.get("cells"), list):
                raise APIError("UE sem estrutura cells valida")
            for cell in ue["cells"]:
                if not isinstance(cell, dict):
                    raise APIError("metricas de celula invalidas")
                cell_id = cell.get("cell_id")
                if isinstance(cell_id, bool) or not isinstance(cell_id, int):
                    raise APIError("cell_id invalido")
                groups.setdefault(cell_id, []).append(cell)
        self.stable = {key: value for key, value in self.stable.items() if key in groups}
        for cell_id, samples in groups.items():
            try:
                measured_snr = min(number(s.get(self.snr_field), SNR_MIN, SNR_MAX)
                                   for s in samples)
                current_mcs = math.floor(min(number(s.get("ul_mcs"), 0, 28)
                                             for s in samples))
                target = get_target_mcs(measured_snr, self.max_mcs, self.snr_margin_db)
                delta = infer_delta(measured_snr, current_mcs, self.max_mcs, self.snr_margin_db)
            except ValueError as exc:
                self.stable.pop(cell_id, None)
                logging.warning("Celula %s: sem ajuste (%s); confira %s e MCS.",
                                cell_id, exc, self.snr_field)
                continue
            if delta == 0:
                self.stable.pop(cell_id, None)
                continue
            # Uma queda isolada ou uma reversão de direção não herda confirmações.
            direction = 1 if delta > 0 else -1
            previous_direction, count = self.stable.get(cell_id, (0, 0))
            count = count + 1 if direction == previous_direction else 1
            self.stable[cell_id] = (direction, count)
            if count < CONFIRMATION_SAMPLES:
                continue
            proposed = int(max(0, min(self.max_mcs, current_mcs + delta)))
            self.api.request("config_set", cells={str(cell_id): {"pusch_mcs": proposed}})
            self.stable.pop(cell_id, None)
            logging.info("Celula %s: SINR %.2f dB, alvo %s, UL MCS %s -> %s (delta %s)",
                         cell_id, measured_snr, target, current_mcs, proposed, delta)


def run_fuzzy_xapp(url=WS_URL, snr_field="pusch_snr", max_mcs=28,
                  snr_margin_db=SNR_MARGIN_DB):
    api = None
    try:
        api = RemoteAPI(url)
        controller = FuzzyController(api, snr_field, max_mcs, snr_margin_db)
        logging.info("AMC fuzzy de uplink iniciado; exige SINR valido em dB.")
        while True:
            controller.poll()
            time.sleep(0.5)
    finally:
        if api is not None:
            api.close()
        logging.warning("Confira as celulas alteradas: MCS de uplink forcado persiste no gNB. "
                "pusch_mcs=-1 libera a adaptacao nativa.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=WS_URL)
    parser.add_argument("--snr-field", default="pusch_snr", help="campo por UE/celula em dB")
    parser.add_argument("--max-mcs", type=int, choices=range(29), default=28)
    parser.add_argument("--snr-margin-db", type=float, default=SNR_MARGIN_DB,
                        help="margem subtraída do SNR para calcular o alvo (padrão: 1 dB)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        run_fuzzy_xapp(args.url, args.snr_field, args.max_mcs, args.snr_margin_db)
    except KeyboardInterrupt:
        pass
    except (APIError, ValueError, OSError, websocket.WebSocketException) as exc:
        logging.error("Controle interrompido: %s", exc)
        raise SystemExit(1)
