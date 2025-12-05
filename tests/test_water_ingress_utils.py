# tests/test_water_ingress_utils.py
import numpy as np
from water_ingress import d8_flow_direction_and_accum, mitigation_rules

def test_d8_flow_direction_and_accum_simple_bowl():
    # Bol : centre plus bas
    dem = np.array([
        [10,10,10,10,10],
        [10, 8, 7, 8,10],
        [10, 8, 5, 8,10],
        [10, 8, 7, 8,10],
        [10,10,10,10,10],
    ], dtype=float)
    acc, dirs = d8_flow_direction_and_accum(dem)
    # Vérifie que le centre a une accumulation élevée
    assert acc[2,2] == np.max(acc)

def test_mitigation_rules_thresholds():
    dem = np.array([[0,0,0],[0,0,0]], dtype=float)
    slope = np.zeros_like(dem)
    acc = np.zeros_like(dem)
    risk = np.ones_like(dem, dtype=bool)  # 100% risque -> devrait déclencher plusieurs actions
    actions = mitigation_rules(dem, slope, acc, risk)
    # Verify we have at least generic maintenance actions
    descriptions = {a["description"] for a in actions}
    assert any("Regularly clean" in d or "Nettoyer régulièrement" in d for d in descriptions)
    assert any("Check the sealing" in d or "Vérifier l’étanchéité" in d for d in descriptions)
