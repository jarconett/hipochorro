"""
Hipochorro: simulador y comparador de hipotecas en España.
Streamlit Cloud + datos en GitHub (jarconett/hipochorro).
"""
import streamlit as st
import pandas as pd
import requests
from io import BytesIO

from lib import github_data as ghd
from lib import amortizacion as am

# Configuración de página
st.set_page_config(
    page_title="Hipochorro - Simulador de Hipotecas",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estado de sesión
if "usuario_actual" not in st.session_state:
    st.session_state.usuario_actual = None
if "hipotecas_cache" not in st.session_state:
    st.session_state.hipotecas_cache = []


def intentar_logo_desde_dominio(dominio: str):
    """Intenta descargar logo desde Clearbit/Logo.dev por dominio. Devuelve bytes o None."""
    dominio = dominio.strip().lower()
    if not dominio or " " in dominio:
        return None
    if not dominio.startswith("http"):
        dominio = dominio.replace("https://", "").replace("http://", "").split("/")[0]
    # Clearbit (puede estar deprecado pero a veces sigue respondiendo)
    url_clearbit = f"https://logo.clearbit.com/{dominio}"
    try:
        r = requests.get(url_clearbit, timeout=5)
        if r.status_code == 200 and len(r.content) > 100:
            return r.content
    except Exception:
        pass
    # Alternativa: img.logo.dev si se configura token
    return None


def formulario_hipoteca(usuario_id: int):
    """Formulario de alta de hipoteca con todos los campos."""
    st.subheader("Alta de hipoteca bancaria")
    logo_subir = st.file_uploader("Logo: sube imagen (PNG/JPG) si no usas dominio", type=["png", "jpg", "jpeg"], key="logo_upload")
    with st.form("form_hipoteca"):
        nombre_entidad = st.text_input("Nombre entidad *", placeholder="Ej: BBVA, Santander, CaixaBank")
        dominio_logo = st.text_input(
            "Dominio web para logo (opcional)",
            placeholder="Ej: bbva.com, santander.es — se intentará descargar el logo"
        )
        nombre_hipoteca = st.text_input("Nombre de la hipoteca *", placeholder="Ej: Hipoteca Fija 25 años")
        duracion_anos = st.number_input("Duración del préstamo (años) *", min_value=1, max_value=40, value=25)
        cantidad_solicitada = st.number_input("Cantidad solicitada (€) *", min_value=0.0, value=150000.0, step=5000.0)
        valor_inmueble = st.number_input("Valor del inmueble (€)", min_value=0.0, value=cantidad_solicitada, step=5000.0)
        if valor_inmueble > 0:
            pct_financiacion = round(100 * cantidad_solicitada / valor_inmueble, 1)
            st.caption(f"Porcentaje de financiación: {pct_financiacion}%")
        tin = st.number_input("% TIN *", min_value=0.0, max_value=30.0, value=3.5, step=0.05, format="%.2f")
        tae = st.number_input("% TAE *", min_value=0.0, max_value=30.0, value=3.8, step=0.05, format="%.2f")
        st.markdown("---")
        st.caption("Comisiones y productos vinculados")
        comision_amort_parcial = st.number_input("Comisión amortización parcial (%)", min_value=0.0, value=0.0, step=0.1, format="%.2f")
        mantenimiento = st.number_input("Mantenimiento (€/año)", min_value=0.0, value=0.0, step=10.0)
        tasacion = st.number_input("Tasación (€)", min_value=0.0, value=0.0, step=50.0)
        bonif_nomina = st.number_input("Bonificación nómina (€/año)", min_value=0.0, value=0.0, step=50.0)
        seguro_hogar = st.number_input("Seguro hogar (€/año)", min_value=0.0, value=0.0, step=20.0)
        seguro_vida = st.number_input("Seguro vida (€/año)", min_value=0.0, value=0.0, step=20.0)
        alarma = st.number_input("Alarma (€/año)", min_value=0.0, value=0.0, step=20.0)
        proteccion_pagos = st.number_input("Protección de pagos (€/año)", min_value=0.0, value=0.0, step=20.0)
        pension = st.number_input("Pensión (€/año)", min_value=0.0, value=0.0, step=20.0)
        bizum = st.checkbox("Bizum vinculado")
        tarjeta_credito = st.checkbox("Tarjeta de crédito vinculada")

        submitted = st.form_submit_button("Guardar hipoteca")
        if submitted and nombre_entidad and nombre_hipoteca:
            logo_path = None
            if dominio_logo:
                img_bytes = intentar_logo_desde_dominio(dominio_logo)
                if img_bytes:
                    logo_path = ghd.subir_logo_desde_bytes(nombre_entidad, img_bytes)
            if not logo_path and logo_subir is not None:
                logo_path = ghd.subir_logo_desde_bytes(nombre_entidad, logo_subir.getvalue())
            if dominio_logo and not logo_path and logo_subir is None:
                st.warning("No se pudo descargar el logo desde el dominio. Puedes subir la imagen manualmente.")
            hipoteca = {
                "nombre_entidad": nombre_entidad,
                "logo_path": logo_path,
                "nombre_hipoteca": nombre_hipoteca,
                "duracion_anos": int(duracion_anos),
                "cantidad_solicitada": float(cantidad_solicitada),
                "valor_inmueble": float(valor_inmueble),
                "pct_financiacion": round(100 * cantidad_solicitada / valor_inmueble, 1) if valor_inmueble else 0,
                "tin": float(tin),
                "tae": float(tae),
                "comision_amort_parcial": float(comision_amort_parcial),
                "mantenimiento": float(mantenimiento),
                "tasacion": float(tasacion),
                "bonif_nomina": float(bonif_nomina),
                "seguro_hogar": float(seguro_hogar),
                "seguro_vida": float(seguro_vida),
                "alarma": float(alarma),
                "proteccion_pagos": float(proteccion_pagos),
                "pension": float(pension),
                "bizum": bool(bizum),
                "tarjeta_credito": bool(tarjeta_credito),
            }
            out = ghd.añadir_hipoteca(usuario_id, hipoteca)
            if out:
                st.session_state.hipotecas_cache = ghd.get_hipotecas(usuario_id)
                st.success("Hipoteca guardada correctamente.")
            else:
                st.error("Error al guardar. Comprueba que GITHUB_TOKEN esté configurado en Streamlit Cloud.")
        elif submitted:
            st.warning("Rellena al menos nombre de entidad y nombre de hipoteca.")


def coste_anual_vinculados(h: dict) -> float:
    """Coste anual en productos vinculados (mantenimiento, seguros, etc.)."""
    return (
        h.get("mantenimiento", 0) + h.get("seguro_hogar", 0) + h.get("seguro_vida", 0)
        + h.get("alarma", 0) + h.get("proteccion_pagos", 0) + h.get("pension", 0)
    ) - h.get("bonif_nomina", 0)


def coste_total_primero_ano(h: dict) -> float:
    """Aproximación coste primer año: intereses + vinculados + tasación (una vez)."""
    from lib.amortizacion import cuota_mensual_frances
    c = h.get("cantidad_solicitada", 0)
    n = h.get("duracion_anos", 25) * 12
    tin = h.get("tin", 0)
    cuota = cuota_mensual_frances(c, tin, n)
    # Intereses primer año aprox
    intereses_ano1 = 12 * cuota - (c / (n / 12))  # aproximación
    # Mejor: primer año intereses reales
    i_mensual = tin / 100 / 12
    cap = c
    intereses = 0
    for _ in range(12):
        im = cap * i_mensual
        am = cuota - im
        intereses += im
        cap -= am
    return intereses + coste_anual_vinculados(h) + h.get("tasacion", 0)


def comparador(usuario_id: int):
    """Pestaña comparador: selección de hipotecas, indicación ventajosa, amortización y tabla."""
    hipotecas = ghd.get_hipotecas(usuario_id)
    st.session_state.hipotecas_cache = hipotecas
    if not hipotecas:
        st.info("No hay hipotecas dadas de alta. Ve a **Alta de hipotecas** para añadir al menos una.")
        return

    opts = [f"{h.get('nombre_entidad','')} - {h.get('nombre_hipoteca','')} (TIN {h.get('tin')}%)" for h in hipotecas]
    sel = st.multiselect("Selecciona hipotecas a comparar", opts, default=opts[:2] if len(opts) >= 2 else opts)
    indices = [opts.index(o) for o in sel if o in opts]
    elegidas = [hipotecas[i] for i in indices]

    if not elegidas:
        st.warning("Elige al menos una hipoteca.")
        return

    # Amortización anual extra común para el comparador
    amort_anual = st.number_input(
        "Amortización extraordinaria por año (€) — opcional",
        min_value=0.0,
        value=0.0,
        step=500.0,
        key="amort_anual_comp",
    )

    # Métricas para “más ventajosa”: TAE, coste primer año, vinculados
    def puntuacion(h):
        tae = h.get("tae", 999)
        c1 = coste_total_primero_ano(h)
        vinc = coste_anual_vinculados(h)
        return (-tae * 10 - c1 * 0.01 - vinc * 0.01)

    elegidas_orden = sorted(elegidas, key=puntuacion, reverse=True)
    mejor = elegidas_orden[0] if elegidas_orden else None

    # Columnas para comparación visual
    n = len(elegidas)
    cols = st.columns(n)
    for i, h in enumerate(elegidas):
        with cols[i]:
            es_mejor = h == mejor
            entidad = h.get("nombre_entidad", "")
            logo_path = h.get("logo_path")
            if logo_path:
                try:
                    url = ghd.get_logo_raw_url(logo_path)
                    st.image(url, width=80, caption=entidad)
                except Exception:
                    st.caption(entidad)
            else:
                st.caption(entidad)
            st.subheader(h.get("nombre_hipoteca", ""))
            if es_mejor:
                st.success("Más ventajosa")
            st.metric("TAE", f"{h.get('tae', 0):.2f}%")
            st.metric("TIN", f"{h.get('tin', 0):.2f}%")
            st.metric("Cuota aprox. (€)", f"{am.cuota_mensual_frances(h.get('cantidad_solicitada',0), h.get('tin',0), h.get('duracion_anos',25)*12):,.0f}")
            st.caption(f"Coste vinculados/año: {coste_anual_vinculados(h):,.0f} €")

    # Tabla de cuotas por año (amortización francesa) para la primera selección o selector
    st.markdown("---")
    st.subheader("Cuadro de amortización (sistema francés)")
    if len(elegidas) == 1:
        hipo_tabla = elegidas[0]
    else:
        hipo_tabla = st.selectbox(
            "Hipoteca para el cuadro de amortización",
            [f"{h.get('nombre_entidad')} - {h.get('nombre_hipoteca')}" for h in elegidas],
            key="sel_tabla",
        )
        idx = next((i for i, h in enumerate(elegidas) if f"{h.get('nombre_entidad')} - {h.get('nombre_hipoteca')}" == hipo_tabla), 0)
        hipo_tabla = elegidas[idx]

    c = hipo_tabla.get("cantidad_solicitada", 0)
    anos = hipo_tabla.get("duracion_anos", 25)
    tin = hipo_tabla.get("tin", 0)
    cuadro = am.cuadro_amortizacion_anual(c, tin, anos, amort_anual)
    df = pd.DataFrame(cuadro)
    df = df.rename(columns={
        "año": "Año",
        "cuota_mensual": "Cuota mensual (€)",
        "intereses_año": "Intereses año (€)",
        "amortizado_año": "Amortizado año (€)",
        "deuda_restante": "Deuda restante (€)",
    })
    st.dataframe(df, use_container_width=True, hide_index=True)


def main():
    st.title("Hipochorro")
    st.caption("Simulador y comparador de hipotecas en España — datos en GitHub")

    # --- Inicio: usuario
    usuarios = ghd.get_usuarios()
    if st.session_state.usuario_actual is None:
        st.header("Inicio de sesión")
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Usuario existente")
            if usuarios:
                sel_user = st.selectbox(
                    "Selecciona usuario",
                    [f"{u.get('nombre','')} ({u.get('email','')})" for u in usuarios],
                    key="sel_user",
                )
                if st.button("Entrar con este usuario"):
                    idx = next(i for i, u in enumerate(usuarios) if f"{u.get('nombre','')} ({u.get('email','')})" == sel_user)
                    st.session_state.usuario_actual = usuarios[idx]
                    st.rerun()
            else:
                st.caption("No hay usuarios. Crea uno nuevo.")
        with col2:
            st.subheader("Nuevo usuario")
            with st.form("form_user"):
                nombre = st.text_input("Nombre *", placeholder="Tu nombre")
                email = st.text_input("Email", placeholder="opcional")
                if st.form_submit_button("Crear y entrar"):
                    if nombre.strip():
                        u = ghd.crear_usuario(nombre.strip(), email.strip())
                        if u:
                            st.session_state.usuario_actual = u
                            st.rerun()
                        else:
                            st.error("Error al crear usuario. ¿GITHUB_TOKEN configurado?")
                    else:
                        st.warning("Indica un nombre.")
        st.stop()

    # Usuario ya seleccionado
    u = st.session_state.usuario_actual
    st.sidebar.success(f"Sesión: **{u.get('nombre', '')}**")
    if st.sidebar.button("Cerrar sesión"):
        st.session_state.usuario_actual = None
        st.rerun()

    tab1, tab2, tab3 = st.tabs(["Alta de hipotecas", "Comparador", "Info"])
    with tab1:
        formulario_hipoteca(u["id"])
        st.markdown("---")
        hipotecas = ghd.get_hipotecas(u["id"])
        if hipotecas:
            st.subheader("Hipotecas dadas de alta")
            for h in hipotecas:
                with st.expander(f"{h.get('nombre_entidad')} — {h.get('nombre_hipoteca')}"):
                    logo_path = h.get("logo_path")
                    if logo_path:
                        try:
                            st.image(ghd.get_logo_raw_url(logo_path), width=60)
                        except Exception:
                            pass
                    st.json({k: v for k, v in h.items() if k != "id"})

    with tab2:
        comparador(u["id"])

    with tab3:
        st.markdown("""
        **Hipochorro** guarda usuarios e hipotecas en el repositorio GitHub **jarconett/hipochorro**.
        - En **Streamlit Cloud** configura el secret `GITHUB_TOKEN` con un token de acceso al repo (con permisos de escritura).
        - Los logos se intentan descargar por dominio (ej. `bbva.com`) y se almacenan en `data/logos/`.
        - El comparador ordena por TAE, coste primer año y productos vinculados para señalar la opción más ventajosa.
        - El cuadro de amortización usa el **sistema francés** (cuota constante) y permite amortización extraordinaria anual.
        """)


if __name__ == "__main__":
    main()
