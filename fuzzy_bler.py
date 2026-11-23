"""AMC fuzzy por célula usando somente CQI como entrada de decisão.

O menor CQI entre os UEs determina o MCS alvo da célula. BLER e contadores
não são lidos. A tabela CQI/MCS é heurística e deve ser calibrada para a rede.
O MCS observado serve apenas para evitar comandos redundantes.
Ao encerrar, o MCS forçado persiste; pdsch_mcs=-1 libera o controle nativo.
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
CQI_TO_MCS = {0: 0, 1: 0, 2: 1, 3: 3, 4: 5, 5: 7, 6: 9,
              7: 11, 8: 13, 9: 15, 10: 17, 11: 19, 12: 21,
              13: 23, 14: 25, 15: 27}

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


def get_max_mcs_for_cqi(cqi):
    # CQI 0 indica fora de alcance; permite apenas o MCS mínimo experimental.
    return CQI_TO_MCS.get(math.floor(number(cqi, 0, 15)), 0)


# Um termo triangular por índice de CQI; valores fracionários ativam termos
# vizinhos. Consequentes simétricos preservam os alvos da tabela nos inteiros.
cqi = ctrl.Antecedent(np.arange(0, 16), 'cqi')
mcs_target = ctrl.Consequent(np.linspace(-0.5, 28.5, 581), 'mcs_target')
rules = []
for index, target in CQI_TO_MCS.items():
    label = f'cqi_{index}'
    cqi[label] = fuzz.trimf(cqi.universe,
                          [max(0, index - 1), index, min(15, index + 1)])
    mcs_target[label] = fuzz.trimf(mcs_target.universe,
                                  [target - 0.5, target, target + 0.5])
    rules.append(ctrl.Rule(cqi[label], mcs_target[label]))
amc_ctrl = ctrl.ControlSystem(rules)


def infer_mcs(current_cqi, max_mcs=28):
    """Retorna índice inteiro de MCS; CQI é a única entrada da inferência."""
    current_cqi = number(current_cqi, 0, 15)
    max_mcs = number(max_mcs, 0, 28)
    if int(max_mcs) != max_mcs:
        raise ValueError("max_mcs deve ser inteiro")
    sim = ctrl.ControlSystemSimulation(amc_ctrl, clip_to_bounds=False)
    sim.input['cqi'] = current_cqi
    sim.compute()
    output = sim.output.get('mcs_target')
    if output is None or not math.isfinite(output):
        raise ValueError("inferência fuzzy sem saída válida")
    # O teto conservador também depende exclusivamente do CQI.
    return int(max(0, min(max_mcs, get_max_mcs_for_cqi(current_cqi), round(output))))


class FuzzyController:
    def __init__(self, api, max_mcs=28):
        self.api = api
        number(max_mcs, 0, 28)
        if int(max_mcs) != max_mcs:
            raise ValueError("max_mcs deve ser inteiro")
        self.max_mcs = int(max_mcs)

    def poll(self):
        response = self.api.request("ue_get", stats=True)
        ues = response.get("ue_list")
        if not isinstance(ues, list):
            raise APIError("ue_get não retornou ue_list")
        groups = {}
        for ue in ues:
            if not isinstance(ue, dict) or not isinstance(ue.get("cells"), list):
                raise APIError("UE sem estrutura cells válida")
            for cell in ue["cells"]:
                if not isinstance(cell, dict):
                    raise APIError("métricas de célula inválidas")
                cell_id = cell.get("cell_id")
                if isinstance(cell_id, bool) or not isinstance(cell_id, int):
                    raise APIError("cell_id inválido")
                groups.setdefault(cell_id, []).append(cell)
        for cell_id, samples in groups.items():
            try:
                # Um CQI ausente impede a decisão que afetaria a célula inteira.
                measured_cqi = min(number(s.get("cqi"), 0, 15) for s in samples)
                proposed = infer_mcs(measured_cqi, self.max_mcs)
            except ValueError as exc:
                logging.warning("Célula %s: sem ajuste (%s); confira CQI.", cell_id, exc)
                continue
            # MCS observado é opcional: nunca determina o alvo nem bloqueia CQI.
            # Não arredonda uma média para concluir que o alvo já foi aplicado.
            try:
                observed = [number(s.get("dl_mcs"), 0, 28) for s in samples]
            except ValueError:
                observed = []
            if observed and all(value == proposed for value in observed):
                continue
            self.api.request("config_set", cells={str(cell_id): {"pdsch_mcs": proposed}})
            logging.info("Célula %s: CQI %.2f -> MCS alvo %s", cell_id, measured_cqi, proposed)


def run_fuzzy_xapp(url=WS_URL, max_mcs=28):
    api = None
    try:
        api = RemoteAPI(url)
        controller = FuzzyController(api, max_mcs)
        logging.info("AMC fuzzy por célula iniciado; decisão exclusivamente por CQI.")
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
    parser.add_argument("--max-mcs", type=int, choices=range(29), default=28)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        run_fuzzy_xapp(args.url, args.max_mcs)
    except KeyboardInterrupt:
        pass
    except (APIError, ValueError, OSError, websocket.WebSocketException) as exc:
        logging.error("Controle interrompido: %s", exc)
        raise SystemExit(1)
