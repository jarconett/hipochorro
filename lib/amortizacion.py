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
    plan_tin_anual=None,
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

    plan_tin_anual:
      - Lista opcional de TIN (%) por año: plan_tin_anual[i] es el TIN del año i+1.
        Si se indica, se usa en lugar de tin_anual_pct para ese año (permite bonificaciones que caducan).
    """
    capital = float(capital_inicial)
    tin = float(tin_anual_pct or 0)
    num_anos = int(num_anos or 0)
    if num_anos <= 0 or capital <= 0:
        return []

    # TIN por año (bonificaciones con caducidad)
    if plan_tin_anual is not None and len(plan_tin_anual) > 0:
        plan_tin = []
        for i in range(num_anos):
            if i < len(plan_tin_anual):
                try:
                    plan_tin.append(float(plan_tin_anual[i]) if plan_tin_anual[i] is not None else tin)
                except (TypeError, ValueError):
                    plan_tin.append(tin)
            else:
                plan_tin.append(tin)
    else:
        plan_tin = [tin] * num_anos

    # Normalizar plan anual (modo reducir_cuota / reducir_plazo)
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

    resultado = []

    def meses_para_saldar(cap: float, cuota: float, i_m: float) -> int:
        """Meses necesarios para saldar cap con cuota fija (sistema francés). i_m = tipo mensual."""
        if cap <= 0:
            return 0
        if cuota <= 0:
            return 10**9
        if abs(i_m) < 1e-12:
            return int(math.ceil(cap / cuota))
        if cuota <= cap * i_m:
            return 10**9
        n = math.log(cuota / (cuota - cap * i_m)) / math.log(1 + i_m)
        return int(math.ceil(n))

    meses_restantes_programados = num_anos * 12
    tin_ano = plan_tin[0]
    i_mensual = (tin_ano / 100.0) / 12.0
    cuota_actual = cuota_mensual_frances(capital, tin_ano, meses_restantes_programados)

    for ano in range(1, num_anos + 1):
        if capital <= 0:
            break

        tin_ano = plan_tin[ano - 1]
        i_mensual = (tin_ano / 100.0) / 12.0

        modo_ano = plan[ano - 1]
        if modo_ano == "reducir_cuota":
            cuota_actual = cuota_mensual_frances(capital, tin_ano, max(1, meses_restantes_programados))

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
            meses_restantes_programados = meses_para_saldar(capital, cuota_actual, i_mensual)

    return resultado


def cuadro_mensual_frances(capital: float, tin_anual_pct: float, num_meses: int) -> List[dict]:
    """
    Sistema francés mes a mes: cuota (casi) constante, interés sobre saldo y amortización de capital.
    Devuelve lista de dicts: mes, cuota, intereses, amort_capital, capital_pendiente.
    """
    capital = float(capital or 0)
    num_meses = int(num_meses or 0)
    if num_meses <= 0 or capital <= 0:
        return []
    tin = float(tin_anual_pct or 0)
    cuota = cuota_mensual_frances(capital, tin, num_meses)
    i_m = (tin / 100.0) / 12.0
    saldo = capital
    out: List[dict] = []
    for mes in range(1, num_meses + 1):
        interes = saldo * i_m
        amort = cuota - interes
        if amort > saldo:
            amort = saldo
        cuota_mes = amort + interes
        saldo = max(0.0, saldo - amort)
        out.append(
            {
                "mes": mes,
                "cuota_€": round(cuota_mes, 2),
                "intereses_€": round(interes, 2),
                "amort_capital_€": round(amort, 2),
                "capital_pendiente_€": round(saldo, 2),
            }
        )
        if saldo <= 0.005:
            break
    return out
