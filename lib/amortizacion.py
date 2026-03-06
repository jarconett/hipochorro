"""
Cálculo de cuotas y cuadro de amortización francés.
"""
from typing import List
import math

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
    plan_anual=None,
) -> List[dict]:
    """
    Genera cuadro por años con sistema francés.
    Si amortizacion_anual_extra > 0, se aplica al final de cada año (reduciendo capital).
    Devuelve lista de dicts: año, cuota_mensual, meses_pagados, intereses_año, amortizado_año, extra_año, deuda_restante.

    modo:
      - "reducir_cuota": mantiene plazo y recalcula la cuota (cuota baja con amortizaciones).
      - "reducir_plazo": mantiene la cuota inicial y reduce la duración (plazo baja con amortizaciones).

    plan_anual:
      - Lista opcional de modos por año, longitud `num_anos`, con valores "reducir_cuota" o "reducir_plazo".
        Si se indica, tiene prioridad sobre `modo` y permite un enfoque mixto.
    """
    capital = float(capital_inicial)
    tin = float(tin_anual_pct or 0)
    num_anos = int(num_anos or 0)
    if num_anos <= 0 or capital <= 0:
        return []

    # Normalizar plan anual
    if plan_anual is None:
        modo = (modo or "reducir_cuota").strip().lower()
        if modo not in ("reducir_cuota", "reducir_plazo"):
            modo = "reducir_cuota"
        plan = [modo] * num_anos
    else:
        plan = []
        for x in list(plan_anual)[:num_anos]:
            m = (x or "reducir_cuota").strip().lower()
            plan.append(m if m in ("reducir_cuota", "reducir_plazo") else "reducir_cuota")
        if len(plan) < num_anos:
            plan += ["reducir_cuota"] * (num_anos - len(plan))

    i_mensual = (tin / 100.0) / 12.0
    resultado = []

    def meses_para_saldar(cap: float, cuota: float) -> int:
        """Meses necesarios para saldar cap con cuota fija (sistema francés)."""
        if cap <= 0:
            return 0
        if cuota <= 0:
            return 10**9
        if abs(i_mensual) < 1e-12:
            return int(math.ceil(cap / cuota))
        # Si la cuota no cubre intereses, no amortiza
        if cuota <= cap * i_mensual:
            return 10**9
        n = math.log(cuota / (cuota - cap * i_mensual)) / math.log(1 + i_mensual)
        return int(math.ceil(n))

    meses_restantes_programados = num_anos * 12
    cuota_actual = cuota_mensual_frances(capital, tin, meses_restantes_programados)

    for ano in range(1, num_anos + 1):
        if capital <= 0:
            break

        modo_ano = plan[ano - 1]
        if modo_ano == "reducir_cuota":
            cuota_actual = cuota_mensual_frances(capital, tin, max(1, meses_restantes_programados))

        intereses_ano = 0.0
        amortizado_ano = 0.0
        meses_pagados = 0

        for _ in range(12):
            if capital <= 0:
                break
            interes_mes = capital * i_mensual
            amort_mes = cuota_actual - interes_mes
            if amort_mes <= 0:
                # Evitar bucles si la cuota no amortiza
                amort_mes = 0.0
                intereses_ano += interes_mes
                meses_pagados += 1
                break
            if amort_mes > capital:
                amort_mes = capital
            intereses_ano += interes_mes
            amortizado_ano += amort_mes
            capital -= amort_mes
            meses_pagados += 1

        extra = 0.0
        if amortizacion_anual_extra > 0 and capital > 0:
            extra = min(float(amortizacion_anual_extra), capital)
            capital -= extra
            amortizado_ano += extra

        resultado.append({
            "año": ano,
            "cuota_mensual": round(float(cuota_actual), 2),
            "meses_pagados": int(meses_pagados),
            "intereses_año": round(intereses_ano, 2),
            "amortizado_año": round(amortizado_ano, 2),
            "extra_año": round(extra, 2),
            "deuda_restante": round(max(0, capital), 2),
        })

        if capital <= 0:
            break

        # Actualizar "plazo programado" para el siguiente año
        if modo_ano == "reducir_cuota":
            meses_restantes_programados = max(0, meses_restantes_programados - meses_pagados)
        else:
            meses_restantes_programados = meses_para_saldar(capital, cuota_actual)

    return resultado
