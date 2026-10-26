"""AMC fuzzy experimental por célula, usando SNR em dB.

O campo selecionado por --snr-field deve ser fornecido pela versão instalada
ou por um adaptador, com unidade conhecida. Sem métricas válidas, a célula não
é alterada. O comando afeta todos os seus UEs.

Os limiares de SNR são heurísticos e devem ser calibrados para a rede. Ao
encerrar, o MCS forçado persiste; pdsch_mcs=-1 libera o controle nativo.
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
TARGET_SNR = 5
RECOVERY_SNR = 15
RECOVERY_SAMPLES = 3

# OAI gNB_scheduler_primitives.c: SINR thresholds multiplied by 10.
SINR_X10_MCS_THRESHOLDS = (
    -10, -4, 6, 16, 24, 34, 42, 50, 56, 62,
    86, 92, 98, 104, 112, 118, 124, 140, 146, 154,
    162, 170, 178, 186, 194, 202, 212, 220, 245,
)

snr = ctrl.Antecedent(np.linspace(SNR_MIN, SNR_MAX, 121), "snr")
cqi = ctrl.Antecedent(np.arange(0, 16), "cqi")
mcs_delta = ctrl.Consequent(np.linspace(-4, 2, 121), "mcs_delta")

snr["baixo"] = fuzz.trapmf(snr.universe, [SNR_MIN, SNR_MIN, 0, 10])
snr["medio"] = fuzz.trimf(snr.universe, [0, 10, 20])
snr["alto"] = fuzz.trapmf(snr.universe, [10, 20, SNR_MAX, SNR_MAX])

cqi["ruim"] = fuzz.trapmf(cqi.universe, [0, 0, 2, 6])
cqi["razoavel"] = fuzz.trimf(cqi.universe, [4, 8, 12])
cqi["bom"] = fuzz.trapmf(cqi.universe, [10, 13, 15, 15])

mcs_delta["reduz_muito"] = fuzz.trimf(mcs_delta.universe, [-4, -4, -2])
mcs_delta["reduz_pouco"] = fuzz.trimf(mcs_delta.universe, [-3, -1, 0])
mcs_delta["mantem"] = fuzz.trimf(mcs_delta.universe, [-1, 0, 1])
mcs_delta["aumenta"] = fuzz.trimf(mcs_delta.universe, [0, 2, 2])

amc_ctrl = ctrl.ControlSystem([
    ctrl.Rule(snr["baixo"], mcs_delta["reduz_muito"]),
    ctrl.Rule(snr["medio"] & cqi["ruim"], mcs_delta["reduz_muito"]),
    ctrl.Rule(snr["medio"] & cqi["razoavel"], mcs_delta["reduz_pouco"]),
    ctrl.Rule(snr["medio"] & cqi["bom"], mcs_delta["reduz_pouco"]),
    ctrl.Rule(snr["alto"] & cqi["ruim"], mcs_delta["mantem"]),
    ctrl.Rule(snr["alto"] & (cqi["razoavel"] | cqi["bom"]), mcs_delta["aumenta"]),
])


def infer_delta(current_snr, current_cqi):
    """Infere a variacao de MCS a partir de SNR e CQI validados."""
    current_snr = number(current_snr, SNR_MIN, SNR_MAX)
    current_cqi = number(current_cqi, 0, 15)
    sim = ctrl.ControlSystemSimulation(amc_ctrl, clip_to_bounds=False)
    sim.input["snr"] = current_snr
    sim.input["cqi"] = current_cqi
    sim.compute()
    output = sim.output.get("mcs_delta")
    if output is None or not math.isfinite(output):
        raise ValueError("inferencia fuzzy sem saida valida")
    return int(round(output))


def get_max_mcs_for_snr(current_snr, layers=1):
    """Retorna o maior MCS permitido pela tabela SINR do OAI."""
    current_snr = number(current_snr, SNR_MIN, SNR_MAX)
    if isinstance(layers, bool) or layers not in (1, 2, 4):
        raise ValueError("numero de camadas invalido")
    mimo_offset_x10 = {1: 0, 2: 40, 4: 70}[layers]
    snr_x10 = current_snr * 10
    for mcs in range(len(SINR_X10_MCS_THRESHOLDS) - 1, -1, -1):
        if snr_x10 >= SINR_X10_MCS_THRESHOLDS[mcs] + mimo_offset_x10:
            return mcs
    return 0


class FuzzyController:
    def __init__(self, api, snr_field="snr", max_mcs=28):
        self.api = api
        self.snr_field = snr_field
        self.max_mcs = int(number(max_mcs, 0, 28))
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
                measured_cqi = min(number(s.get("cqi"), 0, 15) for s in samples)
                current_mcs = math.floor(min(number(s.get("dl_mcs"), 0, 28)
                                             for s in samples))
                cap = min(self.max_mcs, get_max_mcs_for_snr(measured_snr))
                delta = infer_delta(measured_snr, measured_cqi)
            except ValueError as exc:
                self.stable.pop(cell_id, None)
                logging.warning("Celula %s: sem ajuste (%s); confira %s, CQI e MCS.",
                                cell_id, exc, self.snr_field)
                continue
            self.stable[cell_id] = (self.stable.get(cell_id, 0) + 1
                                    if measured_snr > RECOVERY_SNR else 0)
            if delta > 0 and self.stable[cell_id] < RECOVERY_SAMPLES:
                delta = 0
            if measured_snr < TARGET_SNR:
                delta = min(delta, -1)
            proposed = int(max(0, min(cap, current_mcs + delta)))
            if proposed == current_mcs:
                continue
            self.api.request("config_set", cells={str(cell_id): {"pdsch_mcs": proposed}})
            self.stable[cell_id] = 0
            logging.info("Celula %s: SNR %.2f dB, CQI %.2f, delta %s, MCS %s -> %s",
                         cell_id, measured_snr, measured_cqi, delta, current_mcs, proposed)


def run_fuzzy_xapp(url=WS_URL, snr_field="snr", max_mcs=28):
    api = None
    try:
        api = RemoteAPI(url)
        controller = FuzzyController(api, snr_field, max_mcs)
        logging.info("AMC fuzzy por celula iniciado; exige SNR valido em dB.")
        while True:
            controller.poll()
            time.sleep(0.5)
    finally:
        if api is not None:
            api.close()
        logging.warning("Confira as celulas alteradas: MCS forcado persiste no gNB. "
                        "pdsch_mcs=-1 libera a adaptacao nativa.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=WS_URL)
    parser.add_argument("--snr-field", default="pusch_snr", help="campo por UE/celula em dB")
    parser.add_argument("--max-mcs", type=int, choices=range(29), default=28)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        run_fuzzy_xapp(args.url, args.snr_field, args.max_mcs)
    except KeyboardInterrupt:
        pass
    except (APIError, ValueError, OSError, websocket.WebSocketException) as exc:
        logging.error("Controle interrompido: %s", exc)
        raise SystemExit(1)
