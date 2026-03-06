"""
Cálculo de cuotas y cuadro de amortización francés.
"""
from typing import List

def cuota_mensual_frances(capital: float, tin_anual_pct: float, num_meses: int) -> float:
    """
    Cuota mensual constante (sistema francés).
    capital: cantidad prestada
    tin_anual_pct: TIN en tanto por ciento (ej: 3.5)
    num_meses: duración en meses
    """
    if num_meses <= 0 or capital <= 0:
        return 0.0
    i = (tin_anual_pct / 100.0) / 12.0
    if abs(i) < 1e-12:
        return capital / num_meses
    factor = (i * (1 + i) ** num_meses) / ((1 + i) ** num_meses - 1)
    return round(capital * factor, 2)

def cuadro_amortizacion_anual(
    capital_inicial: float,
    tin_anual_pct: float,
    num_anos: int,
    amortizacion_anual_extra: float = 0.0,
    modo: str = "reducir_cuota",
) -> List[dict]:
    """
    Genera cuadro por años con sistema francés.
    Si amortizacion_anual_extra > 0, se aplica al final de cada año (reduciendo capital).
    Devuelve lista de dicts: año, cuota_mensual, meses_pagados, intereses_año, amortizado_año, extra_año, deuda_restante.

    modo:
      - "reducir_cuota": mantiene plazo y recalcula la cuota (cuota baja con amortizaciones).
      - "reducir_plazo": mantiene la cuota inicial y reduce la duración (plazo baja con amortizaciones).
    """
    capital = float(capital_inicial)
    tin = tin_anual_pct
    resultado = []

    modo = (modo or "reducir_cuota").strip().lower()
    if modo not in ("reducir_cuota", "reducir_plazo"):
        modo = "reducir_cuota"

    i_mensual = (tin / 100.0) / 12.0

    if modo == "reducir_plazo":
        cuota_constante = cuota_mensual_frances(capital, tin, max(num_anos, 1) * 12)
        ano = 1
        while capital > 0 and ano <= num_anos:
            intereses_ano = 0.0
            amortizado_ano = 0.0
            meses_pagados = 0
            for _ in range(12):
                if capital <= 0:
                    break
                interes_mes = capital * i_mensual
                amort_mes = cuota_constante - interes_mes
                if amort_mes > capital:
                    amort_mes = capital
                intereses_ano += interes_mes
                amortizado_ano += amort_mes
                capital -= amort_mes
                meses_pagados += 1

            extra = 0.0
            if amortizacion_anual_extra > 0 and capital > 0:
                extra = min(amortizacion_anual_extra, capital)
                capital -= extra
                amortizado_ano += extra

            resultado.append({
                "año": ano,
                "cuota_mensual": round(cuota_constante, 2),
                "meses_pagados": int(meses_pagados),
                "intereses_año": round(intereses_ano, 2),
                "amortizado_año": round(amortizado_ano, 2),
                "extra_año": round(extra, 2),
                "deuda_restante": round(max(0, capital), 2),
            })
            ano += 1
        return resultado

    # modo == "reducir_cuota"
    for ano in range(1, num_anos + 1):
        if capital <= 0:
            break
        meses_restantes = (num_anos - ano + 1) * 12
        cuota = cuota_mensual_frances(capital, tin, meses_restantes)
        intereses_ano = 0.0
        amortizado_ano = 0.0
        meses_pagados = 0
        for _ in range(12):
            if capital <= 0:
                break
            interes_mes = capital * i_mensual
            amort_mes = cuota - interes_mes
            if amort_mes > capital:
                amort_mes = capital
            intereses_ano += interes_mes
            amortizado_ano += amort_mes
            capital -= amort_mes
            meses_pagados += 1
        # Amortización extraordinaria al final del año
        extra = 0.0
        if amortizacion_anual_extra > 0 and capital > 0:
            extra = min(amortizacion_anual_extra, capital)
            capital -= extra
            amortizado_ano += extra
        resultado.append({
            "año": ano,
            "cuota_mensual": round(cuota, 2),
            "meses_pagados": int(meses_pagados),
            "intereses_año": round(intereses_ano, 2),
            "amortizado_año": round(amortizado_ano, 2),
            "extra_año": round(extra, 2),
            "deuda_restante": round(max(0, capital), 2),
        })
    return resultado
