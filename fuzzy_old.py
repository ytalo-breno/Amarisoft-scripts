import warnings
import warnings
import websocket
import json
import time
import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl

# ==========================================
# 1. DEFINIÇÃO DO SISTEMA FUZZY
# ==========================================
CELL_ID_STR = "1"
# Variáveis de Entrada (Antecedentes)
# BLER varia de 0.0 a 1.0 (0% a 100%)
bler = ctrl.Antecedent(np.arange(0, 1.01, 0.01), 'bler')
# CQI varia de 1 a 15
cqi = ctrl.Antecedent(np.arange(1, 16, 1), 'cqi')

# Variável de Saída (Consequente)
# Ajuste do MCS: de -4  a +2 
mcs_delta = ctrl.Consequent(np.arange(-4, 3, 1), 'mcs_delta')

# Funções de Pertinência para BLER
bler['baixo'] = fuzz.trimf(bler.universe, [0, 0, 0.15])
bler['medio'] = fuzz.trimf(bler.universe, [0.05, 0.20, 0.40])
bler['alto'] = fuzz.trimf(bler.universe, [0.30, 1.0, 1.0])

# Funções de Pertinência para CQI
cqi['ruim'] = fuzz.trimf(cqi.universe, [1, 1, 6])
cqi['razoavel'] = fuzz.trimf(cqi.universe, [4, 8, 12])
cqi['bom'] = fuzz.trimf(cqi.universe, [10, 15, 15])

# Funções de Pertinência para o Ajuste de MCS
mcs_delta['reduz_muito'] = fuzz.trimf(mcs_delta.universe, [-4, -4, -2])
mcs_delta['reduz_pouco'] = fuzz.trimf(mcs_delta.universe, [-3, -1, 0])
mcs_delta['mantem'] = fuzz.trimf(mcs_delta.universe, [-1, 0, 1])
mcs_delta['aumenta'] = fuzz.trimf(mcs_delta.universe, [0, 2, 2])

# Regras Fuzzy
regra1 = ctrl.Rule(bler['alto'], mcs_delta['reduz_muito'])
regra2 = ctrl.Rule(bler['medio'] & cqi['ruim'], mcs_delta['reduz_muito'])
regra3 = ctrl.Rule(bler['medio'] & cqi['razoavel'], mcs_delta['reduz_pouco'])
regra4 = ctrl.Rule(bler['baixo'] & cqi['ruim'], mcs_delta['mantem'])
regra5 = ctrl.Rule(bler['baixo'] & (cqi['razoavel'] | cqi['bom']), mcs_delta['aumenta'])

# Controlador e Simulador
amc_ctrl = ctrl.ControlSystem([regra1, regra2, regra3, regra4, regra5])
fuzzy_sim = ctrl.ControlSystemSimulation(amc_ctrl)


# 2. LAÇO DE TELEMETRIA E CONTROLE (AMARISOFT)


ue_counters_history = {}

def extract_instantaneous_bler(ue):
    rnti = ue.get("rnti")
    cells = ue.get("cells", [])
    
    # Se o UE não estiver reportando métricas de célula no momento, retorna 0
    if not cells:
        return 0.0
        
    # Acessa a célula primária (índice 0 da lista)
    primary_cell = cells[0]
    
    current_tx = primary_cell.get("dl_tx", 0)
    current_err = primary_cell.get("dl_err", 0)
    
    if rnti not in ue_counters_history:
        ue_counters_history[rnti] = {"tx": current_tx, "err": current_err}
        return 0.0 
        
    prev_tx = ue_counters_history[rnti]["tx"]
    prev_err = ue_counters_history[rnti]["err"]
    
    delta_tx = current_tx - prev_tx
    delta_err = current_err - prev_err
    
    ue_counters_history[rnti] = {"tx": current_tx, "err": current_err}
    
    if delta_tx > 0:
        return delta_err / delta_tx
    return 0.0

WS_URL = "ws://172.16.2.32:9001"
ue_mcs_state = {}

def run_fuzzy_xapp():
    ws = websocket.create_connection(WS_URL)
    print("xApp AMC Fuzzy iniciado.")
    
    while True:
        ws.send(json.dumps({"message": "ue_get","stats":True}))
        response = json.loads(ws.recv())
        print(response)
        
        for ue in response.get("ue_list", []):
            rnti = ue.get("rnti")
            cells = ue.get("cells", [])
            
            # Pula este UE se ele não tiver métricas de rádio reportadas ainda
            if not cells:
                continue
                
            primary_cell = cells[0]
            
            # Extração 
            current_bler = extract_instantaneous_bler(ue)
            current_cqi = primary_cell.get("cqi", 15)
            network_mcs = primary_cell.get("dl_mcs", 28)
            
            if rnti not in ue_mcs_state:
                ue_mcs_state[rnti] = network_mcs
                
            current_mcs = ue_mcs_state[rnti]
            
            # Injeta os valores reais no simulador Fuzzy
            fuzzy_sim.input['bler'] = current_bler
            fuzzy_sim.input['cqi'] = current_cqi
            
            # Executa a inferência e defuzzificação (cálculo do centro de gravidade)
            try:
                fuzzy_sim.compute()
                delta = fuzzy_sim.output['mcs_delta']
            except ValueError:
                delta = 0 # Fallback caso os valores caiam fora do universo mapeado
            
            # O Fuzzy retorna um valor float contínuo. Arredondamos para o passo inteiro mais próximo.
            delta_int = int(round(delta))
            new_mcs = max(1, min(28, current_mcs + delta_int))
            
            # Aplica o novo MCS se houver mudança
            if new_mcs != current_mcs:
                print(f"[RNTI {rnti}] BLER: {current_bler:.2f} | CQI: {current_cqi} -> Ação Fuzzy: Delta {delta_int} | Novo MCS: {new_mcs}")
                ue_mcs_state[rnti] = new_mcs
                
                payload = {
                                "message": "config_set",
                                "cells": {
                                    CELL_ID_STR: {
                                        "pdsch_mcs": new_mcs
                                    }
                                }
                            }
                ws.recv()
                
        time.sleep(0.5)

if __name__ == "__main__":
    run_fuzzy_xapp()