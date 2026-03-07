"""
Hipochorro: simulador y comparador de hipotecas en España.
Streamlit Cloud + datos en GitHub (jarconett/hipochorro).
"""
import sys
from pathlib import Path

# Asegurar que el directorio raíz del proyecto está en el path (Streamlit Cloud, etc.)
_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import math
import re
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests
from io import BytesIO
from urllib.parse import urljoin, urlparse

from lib import github_data as ghd
from lib import amortizacion as am
try:
    from lib import zonas_climaticas_cte as zcte
except ImportError:
    zcte = None

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None
try:
    import folium
    from streamlit_folium import st_folium
except Exception:  # pragma: no cover
    folium = None  # type: ignore
    st_folium = None  # type: ignore

ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_APP_PATH = ASSETS_DIR / "logo.png"
FAVICON_PATH = ASSETS_DIR / "favicon.png"

# Textos de ayuda para TIN y TAE (tooltips)
HELP_TIN = (
    "TIN (Tipo de Interés Nominal): porcentaje que cobra el banco por el dinero prestado, "
    "sin incluir comisiones ni otros gastos. Es la base para calcular la cuota mensual. "
    "Ejemplo: 150.000 € a 25 años con TIN 3,5% dan una cuota mensual de unos 750 € y unos 5.200 € de intereses el primer año."
)
HELP_TAE = (
    "TAE (Tasa Anual Equivalente): porcentaje que refleja el coste total del préstamo al año, "
    "incluyendo interés (TIN), comisiones de apertura y otros gastos obligatorios. Sirve para comparar ofertas entre bancos. "
    "Ejemplo: TIN 3,5% con TAE 3,8% indica que las comisiones y gastos elevan el coste real al equivalente de 3,8% anual."
)

# Nombre del secret en Streamlit Cloud para el token de Apify (Idealista).
# En Streamlit Cloud: Settings → Secrets → clave "APIFY_TOKEN_SECRET" con tu API token de apify.com
APIFY_TOKEN_SECRET = "APIFY_TOKEN_SECRET"

# Versión de la aplicación (visible en sidebar y changelog)
VERSION_APP = "1.11.0"

# Gastos de compra (sobre precio de la vivienda / ITP)
ITP_PCT = 7.0           # Impuesto de Transmisiones Patrimoniales: % sobre precio vivienda
NOTARIA_PCT_DEL_ITP = 10.0   # Notaría: % del importe del ITP
REGISTRO_PCT_DEL_ITP = 10.0  # Registro: % del importe del ITP
GESTORIA_EUR = 300.0    # Gestoría: importe fijo (€)

# Opciones certificado energético (consumo y emisiones)
CERT_ENERGETICO_OPCIONES = ["—", "A", "B", "C", "D", "E", "F", "G", "En trámite", "No disponible"]

# Consumo de energía (kWh/m²·año) por letra del certificado — tabla oficial (rangos de calificación)
# Fuente: tabla de consumo y emisiones del certificado energético (tabla-energetica.png)
# Rangos consumo (kWh/m²·año): A <55, B 55-85, C 85-125, D 125-175, E 175-230, F 230-275, G ≥275 → punto medio para estimar
CONSUMO_REFERENCIA_KWH_M2_POR_LETRA = {
    "A": 27.5,   # < 55
    "B": 70.0,   # 55-85
    "C": 105.0,  # 85-125
    "D": 150.0,  # 125-175
    "E": 202.5,  # 175-230
    "F": 252.5,  # 230-275
    "G": 287.5,  # ≥ 275 (representativo)
}

# Límites superiores (valor < límite → letra) para asignar letra desde valor numérico de consumo (kWh/m²·año)
_RANGOS_CONSUMO_LIMITES = [(55, "A"), (85, "B"), (125, "C"), (175, "D"), (230, "E"), (275, "F"), (float("inf"), "G")]

# Emisiones (kg CO₂/m²·año): rangos referencia y límites para asignar letra (escala habitual certificado)
RANGOS_EMISIONES_REFERENCIA_KG_M2_POR_LETRA = {
    "A": 6.1,    # < 12.2
    "B": 16.05,  # 12.2-19.9
    "C": 25.35,  # 19.9-30.8
    "D": 39.05,  # 30.8-47.3
    "E": 65.5,   # 47.3-83.7
    "F": 92.05,  # 83.7-100.4
    "G": 110.0,  # ≥ 100.4
}
_RANGOS_EMISIONES_LIMITES = [(12.2, "A"), (19.9, "B"), (30.8, "C"), (47.3, "D"), (83.7, "E"), (100.4, "F"), (float("inf"), "G")]


def _letra_desde_consumo_kwh_m2(valor: float) -> str:
    """Asigna la letra del certificado (A-G) según el consumo en kWh/m²·año y la tabla de rangos."""
    for limite, letra in _RANGOS_CONSUMO_LIMITES:
        if valor < limite:
            return letra
    return "G"


def _letra_desde_emisiones_kg_m2(valor: float) -> str:
    """Asigna la letra del certificado (A-G) según las emisiones en kg CO₂/m²·año y la tabla de rangos."""
    for limite, letra in _RANGOS_EMISIONES_LIMITES:
        if valor < limite:
            return letra
    return "G"

# Zona climática CTE (Código Técnico de la Edificación): opciones para selectbox
ZONAS_CTE_OPCIONES = (zcte.get_opciones_zona() if zcte else ["—"] + [f"{l}{n}" for l in "ABCDE" for n in "1234"])

# Reducción mínima demanda térmica para subvención según zona CTE (letra A–E)
# A y B: normalmente no obligatoria; C: ≥ 25 %; D y E: ≥ 35 %
def _reduccion_subvencion_por_zona_cte(zona_cte: str) -> str:
    """Devuelve texto de reducción mínima para subvención según la letra de la zona (ej. C3 → C)."""
    if not (zona_cte or "").strip():
        return ""
    letra = (zona_cte.strip().upper())[:1]
    if letra in ("A", "B"):
        return "Reducción mín. demanda térmica para subvención: normalmente no obligatoria"
    if letra == "C":
        return "Reducción mín. demanda térmica para subvención: ≥ 25 %"
    if letra in ("D", "E"):
        return "Reducción mín. demanda térmica para subvención: ≥ 35 %"
    return ""


def _reduccion_decimal_por_zona_cte(zona_cte: str) -> float | None:
    """Devuelve la reducción mínima como decimal (0.25, 0.35) para zona C, D o E; None para A/B (no obligatoria)."""
    if not (zona_cte or "").strip():
        return None
    letra = (zona_cte.strip().upper())[:1]
    if letra == "C":
        return 0.25
    if letra in ("D", "E"):
        return 0.35
    return None  # A, B: normalmente no obligatoria


# Panel típico: ~1.7 m² (1.6 m x 1 m)
AREA_PLACA_TIPICA_M2 = 1.7


def _consumo_anual_desde_certificado(inv: dict) -> float | None:
    """
    Estima el consumo eléctrico anual (kWh) a partir del certificado energético (consumo)
    y la superficie del inmueble. Si existe consumo_exacto_kwh_m2 se usa ese valor × m²;
    si no, se usa la letra (certificado_consumo) y el punto medio del rango de la tabla.
    Devuelve None si no hay dato válido o no hay superficie.
    """
    m2 = float(inv.get("m2_utiles", 0) or 0) or float(inv.get("m2_construidos", 0) or 0)
    if m2 <= 0:
        return None
    consumo_m2 = float(inv.get("consumo_exacto_kwh_m2", 0) or 0)
    if consumo_m2 > 0:
        return round(consumo_m2 * m2, 0)
    letra = (inv.get("certificado_consumo") or inv.get("certificado_energetico") or "").strip().upper()
    if letra not in CONSUMO_REFERENCIA_KWH_M2_POR_LETRA:
        return None
    kwh_m2 = CONSUMO_REFERENCIA_KWH_M2_POR_LETRA[letra]
    return round(kwh_m2 * m2, 0)


def calcular_placas_solares(
    consumo_anual_kwh: float,
    reduccion: float,
    produccion_placa_kwh_ano: float,
    area_placa_m2: float = AREA_PLACA_TIPICA_M2,
) -> tuple[int, float]:
    """
    Calcula el número de placas solares necesarias para alcanzar la reducción energética dada.
    Redondea al entero superior. También devuelve la superficie necesaria en m².

    - consumo_anual_kwh: consumo eléctrico anual en kWh.
    - reduccion: fracción de reducción (ej. 0.25 para 25 %).
    - produccion_placa_kwh_ano: producción anual por placa en kWh/año.
    - area_placa_m2: superficie por placa en m² (por defecto 1.7).

    Returns:
        (numero_placas, superficie_total_m2)
    """
    if produccion_placa_kwh_ano <= 0:
        return (0, 0.0)
    placas = (consumo_anual_kwh * reduccion) / produccion_placa_kwh_ano
    numero_placas = max(0, int(math.ceil(placas)))
    superficie_m2 = numero_placas * area_placa_m2
    return (numero_placas, superficie_m2)


def calcular_presupuesto_instalacion(
    numero_placas: int,
    costo_placa_eur: float,
    area_placa_m2: float,
    costo_instalacion_eur_m2: float,
) -> float:
    """
    Calcula el presupuesto total de instalación de placas solares.

    - numero_placas: número de placas.
    - costo_placa_eur: coste por placa en €.
    - area_placa_m2: superficie por placa en m².
    - costo_instalacion_eur_m2: coste de instalación en €/m².

    Returns:
        Presupuesto total en €.
    """
    area_total = numero_placas * area_placa_m2
    costo_placas = numero_placas * costo_placa_eur
    costo_instalacion_total = area_total * costo_instalacion_eur_m2
    return costo_placas + costo_instalacion_total


# Categorías de inmuebles en la agenda (estilo: Interesados=verde, En Estudio=azul)
CATEGORIA_INTERESADOS = "Interesados"
CATEGORIA_EN_ESTUDIO = "En Estudio"
CATEGORIAS_INMUEBLE = [CATEGORIA_INTERESADOS, CATEGORIA_EN_ESTUDIO]

# Tramos retención rentas del ahorro (España): base imponible → tipo aplicable
# Hasta 6.000 € → 19%; 6.000-50.000 → 21%; 50.000-200.000 → 23%; >200.000 → 26%
TRAMOS_RETENCION_AHORRO = [(6_000, 0.19), (50_000, 0.21), (200_000, 0.23), (float("inf"), 0.26)]


def _cargar_imagen(path: Path):
    if Image is None:
        return None
    try:
        if path.exists():
            return Image.open(path)
    except Exception:
        return None
    return None


_favicon_img = _cargar_imagen(FAVICON_PATH)

# Configuración de página (favicon)
st.set_page_config(
    page_title="Hipochorro - Comparador de Hipotecas",
    page_icon=_favicon_img if _favicon_img is not None else "🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS global: aspecto profesional (espaciado, cards, accesibilidad)
# Inspirado en web-design-guidelines: focus visible, tipografía, contraste
st.markdown(
    """
    <style>
    /* Contenedor principal: padding y lectura cómoda */
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 100%; }
    /* Encabezados: jerarquía clara y espacio */
    h1, h2, h3 { font-weight: 600; margin-top: 1.25em; margin-bottom: 0.5em; }
    h1 { font-size: 1.75rem; border-bottom: 2px solid var(--primary-color, #0d47a1); padding-bottom: 0.35rem; }
    /* Expanders tipo card: sombra sutil y borde redondeado */
    [data-testid="stExpander"] { border-radius: 0.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.06); border: 1px solid rgba(0,0,0,0.06); }
    /* Accesibilidad: anillo de foco visible (nunca outline: none sin reemplazo) */
    button:focus-visible, [data-testid="stSelectbox"]:focus-within { outline: 2px solid var(--primary-color, #0d47a1); outline-offset: 2px; }
    /* Métricas y números: tabular-nums para alineación */
    [data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
    /* Sidebar: separación visual */
    [data-testid="stSidebar"] { border-right: 1px solid rgba(0,0,0,0.08); }
    /* Botones primarios: más contraste */
    .stButton > button { font-weight: 500; border-radius: 0.5rem; }
    /* Tabs: barra fija al scroll con contraste correcto (fondo y texto legibles) */
    .stTabs [data-baseweb="tab-list"] {
      gap: 0.25rem; position: sticky; top: 0; z-index: 999;
      background: #f1f5f9 !important;
      padding-bottom: 0.25rem; margin-bottom: 0.5rem;
      box-shadow: 0 1px 0 rgba(0,0,0,0.08);
    }
    .stTabs [data-baseweb="tab-list"] [data-baseweb="tab"],
    .stTabs [data-baseweb="tab-list"] span { color: #1e293b !important; }
    .stTabs [data-baseweb="tab"] { padding: 0.5rem 1rem; border-radius: 0.5rem; }
    .stTabs [data-baseweb="tab"][aria-selected="true"],
    .stTabs [data-baseweb="tab"][aria-selected="true"] span { color: var(--primary-color, #0d47a1) !important; font-weight: 600; }
    /* Tema oscuro: barra sticky con colores dark (Streamlit aplica data-theme en un ancestro) */
    [data-theme="dark"] .stTabs [data-baseweb="tab-list"] {
      background: #1e293b !important;
    }
    [data-theme="dark"] .stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]:not([aria-selected="true"]),
    [data-theme="dark"] .stTabs [data-baseweb="tab-list"] span { color: #f1f5f9 !important; }
    [data-theme="dark"] .stTabs [data-baseweb="tab"][aria-selected="true"] span { color: #64b5f6 !important; }
    /* Si el layout duplica el bloque de tabs (p. ej. en scroll), ocultar el segundo */
    [data-testid="stTabs"] ~ [data-testid="stTabs"] { display: none !important; }
    /* Evitar que al hacer scroll se repita el bloque de login/contenido inicial (duplicado de layout) */
    .block-container ~ .block-container { display: none !important; }
    /* Ocultar bloques que contienen el formulario de login cuando están después de las pestañas (duplicado al scroll) */
    [data-testid="stVerticalBlock"]:has([data-testid="stForm"]) ~ [data-testid="stVerticalBlock"]:has([data-testid="stForm"]) { display: none !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Estado de sesión
if "usuario_actual" not in st.session_state:
    st.session_state.usuario_actual = None
if "hipotecas_cache" not in st.session_state:
    st.session_state.hipotecas_cache = []
if "inmueble_seleccionado" not in st.session_state:
    st.session_state.inmueble_seleccionado = None  # dict del inmueble o None
if "fotos_extraidas" not in st.session_state:
    st.session_state.fotos_extraidas = None  # {"inmueble_id": int, "urls": [str]} o None
if "gps_duracion_cache" not in st.session_state:
    st.session_state.gps_duracion_cache = {}  # (inv_id, destino_str) -> minutos
if "gps_coords_cache" not in st.session_state:
    st.session_state.gps_coords_cache = {}  # str (dirección) -> (lat, lon)


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


# Headers para peticiones a portales (Idealista, etc.)
_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


def _normalizar_url_imagen(u: str) -> str | None:
    """Devuelve la URL si parece una imagen de contenido; None si es logo/icono/etc."""
    if not u or not isinstance(u, str) or not u.startswith("http"):
        return None
    s = u.lower()
    if any(x in s for x in ("logo", "icon", "pixel", "avatar", "banner", "cookie", "tracking")):
        return None
    if ".jpg" in s or ".jpeg" in s or ".png" in s or ".webp" in s:
        return u
    return None


def _urls_desde_lista_imagenes(objs: list) -> list:
    """Convierte una lista (de strings o de dicts con 'url'/'src'/'image') en lista de URLs de imagen."""
    out = []
    for x in objs:
        if isinstance(x, str):
            u = _normalizar_url_imagen(x)
            if u:
                out.append(u)
        elif isinstance(x, dict):
            for key in ("url", "src", "image", "href", "link", "srcUrl"):
                u = x.get(key)
                if isinstance(u, str):
                    u = _normalizar_url_imagen(u)
                    if u:
                        out.append(u)
                        break
    return out


def _extraer_urls_desde_json(html: str, url_base: str) -> list:
    """Busca en el HTML JSON embebido (Idealista, etc.) y extrae URLs de imágenes."""
    urls = []
    # Patrones típicos: "url":"https://...", "src":"https://...", multimedia, gallery, images
    patron = re.compile(r'["\'](?:url|src|image|href)["\']\s*:\s*["\'](https?://[^"\']+\.(?:jpg|jpeg|png|webp)(?:\?[^"\']*)?)["\']', re.I)
    for m in patron.finditer(html):
        u = m.group(1)
        if _normalizar_url_imagen(u):
            urls.append(u)
    # Idealista: todas las URLs de imagen de su dominio (galería en JSON o atributos)
    patron2 = re.compile(r'https?://(?:img\d*\.)?idealista\.(?:com|pt|it)[^"\')\s]+\.(?:jpg|jpeg|png|webp)(?:\?[^"\')\s]*)?', re.I)
    for m in patron2.finditer(html):
        u = m.group(0)
        if _normalizar_url_imagen(u):
            urls.append(u)
    return list(dict.fromkeys(urls))


def _extraer_id_idealista(url: str) -> str | None:
    """Extrae el ID de inmueble de una URL de Idealista. Ej: .../inmueble/110670317/ -> 110670317."""
    if not url or "idealista" not in url.lower():
        return None
    m = re.search(r"idealista\.(?:com|pt|it)/inmueble/(\d+)", url, re.I)
    return m.group(1) if m else None


def _obtener_imagenes_idealista_zenrows(url_anuncio: str, property_id: str, api_key: str) -> list:
    """Obtiene URLs de imágenes de un anuncio Idealista vía API ZenRows. Requiere ZENROWS_API_KEY."""
    try:
        endpoint = f"https://realestate.api.zenrows.com/v1/targets/idealista/properties/{property_id}"
        r = requests.get(endpoint, params={"apikey": api_key, "url": url_anuncio}, headers=_REQUEST_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        # Respuesta puede ser lista de URLs o lista de objetos { "url": "..." }; también buscar en anidados
        urls = []
        for key in ("property_images", "images", "gallery", "multimedia", "photos", "imageUrls"):
            val = data.get(key)
            if isinstance(val, list):
                urls.extend(_urls_desde_lista_imagenes(val))
            elif isinstance(val, str) and _normalizar_url_imagen(val):
                urls.append(val)
        # Estructura anidada tipo data.property.multimedia
        for nest in ("data", "property", "result"):
            sub = data.get(nest)
            if isinstance(sub, dict):
                for key in ("property_images", "images", "gallery", "multimedia", "photos"):
                    val = sub.get(key)
                    if isinstance(val, list):
                        urls.extend(_urls_desde_lista_imagenes(val))
        return list(dict.fromkeys(urls))
    except Exception:
        return []


def _obtener_imagenes_idealista_apify(url_anuncio: str, api_token: str) -> list:
    """Obtiene URLs de imágenes de un anuncio Idealista vía Apify (actor Idealista Property Listing Scraper). Requiere APIFY_TOKEN en secrets."""
    try:
        from apify_client import ApifyClient
        client = ApifyClient(api_token)
        run_input = {
            "startUrls": [{"url": url_anuncio}],
            "maxRequestsPerCrawl": 1,
            "maxConcurrency": 1,
        }
        run = client.actor("duncan01/idealista-property-listing-scraper").call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        urls = []
        for item in items:
            for key in ("images", "property_images", "propertyImages", "photos", "imageUrls", "gallery", "multimedia"):
                val = item.get(key)
                if isinstance(val, list):
                    urls.extend(_urls_desde_lista_imagenes(val))
                elif isinstance(val, str) and _normalizar_url_imagen(val):
                    urls.append(val)
        return list(dict.fromkeys(urls))
    except Exception:
        return []


def extraer_urls_imagenes_anuncio(url_anuncio: str, max_urls: int = 50) -> list:
    """
    Extrae URLs de imágenes de una página de anuncio (Idealista y otros).
    Para Idealista: si está configurado ZENROWS_API_KEY usa ZenRows; si no, APIFY_TOKEN usa Apify.
    Si no hay ninguna key, intenta extraer del HTML (puede fallar con 403 en Idealista).
    Devuelve lista de URLs para que el usuario elija cuáles añadir a la ficha.
    """
    if not url_anuncio or not url_anuncio.strip().startswith("http"):
        return []
    url_anuncio = url_anuncio.strip()
    # Opción 1: Idealista + ZenRows API (evita 403)
    import os
    zenrows_key = os.environ.get("ZENROWS_API_KEY") or (st.secrets.get("ZENROWS_API_KEY") if hasattr(st, "secrets") else None)
    property_id = _extraer_id_idealista(url_anuncio)
    if property_id and zenrows_key:
        urls = _obtener_imagenes_idealista_zenrows(url_anuncio, property_id, zenrows_key)
        if urls:
            return urls[:max_urls]
    # Opción 2: Idealista + Apify (actor por URL; configurar APIFY_TOKEN en secrets)
    apify_token = os.environ.get(APIFY_TOKEN_SECRET) or (st.secrets.get(APIFY_TOKEN_SECRET) if hasattr(st, "secrets") else None)
    if property_id and apify_token:
        urls = _obtener_imagenes_idealista_apify(url_anuncio, apify_token)
        if urls:
            return urls[:max_urls]
    # Opción 3: Scraping directo del HTML (timeout corto para no bloquear la UI)
    try:
        from bs4 import BeautifulSoup
        r = requests.get(url_anuncio, headers=_REQUEST_HEADERS, timeout=12)
        html = r.text
        # Si 403 o 401, intentar parsear solo si el cuerpo parece una página completa (p. ej. algunos CDN)
        if r.status_code not in (200, 201) and (len(html) < 5000 or "idealista" not in html.lower()):
            if r.status_code == 403 and "idealista" in url_anuncio.lower():
                raise ValueError(
                    "Idealista ha bloqueado la petición (403). Configura APIFY_TOKEN o ZENROWS_API_KEY en secrets "
                    "(ver docs/IDEALISTA_SCRAPING.md) o añade las fotos manualmente."
                )
            r.raise_for_status()
        soup = BeautifulSoup(html, "html.parser")
        seen = set()
        urls = []

        # 1) Idealista y portales: JSON embebido en script
        for script in soup.find_all("script", type=re.compile("json|ld\\+json", re.I)):
            if script.string:
                urls.extend(_extraer_urls_desde_json(script.string, url_anuncio))
        urls.extend(_extraer_urls_desde_json(html, url_anuncio))

        # 2) Atributos data-src, data-lazy-src, data-srcset (común en galerías)
        for img in soup.find_all("img"):
            for attr in ("src", "data-src", "data-lazy-src", "data-srcset"):
                val = img.get(attr)
                if not val:
                    continue
                # data-srcset puede ser "url1 1x, url2 2x"
                for part in val.split(","):
                    part = part.strip().split()[0] if part.strip() else part.strip()
                    if part and (part.endswith(".jpg") or ".jpeg" in part or ".png" in part or ".webp" in part):
                        if not part.startswith("http"):
                            part = urljoin(url_anuncio, part)
                        if part not in seen and len(part) > 20:
                            s = part.lower()
                            if not any(x in s for x in ("logo", "icon", "pixel", "avatar", "banner", "cookie")):
                                seen.add(part)
                                urls.append(part)
                                break

        # 3) Enlaces directos src de img
        for img in soup.find_all("img"):
            src = img.get("src")
            if not src or len(src) < 15:
                continue
            if not src.startswith("http"):
                src = urljoin(url_anuncio, src)
            if src in seen:
                continue
            s = src.lower()
            if any(x in s for x in ("logo", "icon", "pixel", "avatar", "banner", "cookie")):
                continue
            if ".jpg" in s or ".jpeg" in s or ".png" in s or ".webp" in s:
                seen.add(src)
                urls.append(src)

        # 4) Cualquier URL de imagen en el HTML (p. ej. webs inmobiliarias con fotos en script o data-*)
        patron_cualquier_imagen = re.compile(
            r'https?://[^"\'<>\s]+\.(?:jpg|jpeg|png|webp)(?:\?[^"\'<>\s]*)?', re.I
        )
        for m in patron_cualquier_imagen.finditer(html):
            u = m.group(0)
            if u not in seen and _normalizar_url_imagen(u):
                seen.add(u)
                urls.append(u)

        # Orden estable y límite
        return list(dict.fromkeys(urls))[:max_urls]
    except ValueError:
        raise
    except Exception:
        return []


def _descargar_imagen_bytes(url: str) -> bytes | None:
    """Descarga una imagen desde URL y devuelve los bytes, o None si falla."""
    try:
        r = requests.get(url, headers=_REQUEST_HEADERS, timeout=12)
        if r.status_code == 200 and len(r.content) > 500:
            return r.content
    except Exception:
        pass
    return None


def _desglose_gastos_compra(inv: dict) -> dict:
    """
    Desglose de gastos de compra: precio, comisión, ITP, notaría, registro, gestoría.
    Notaría y registro son un % del importe del ITP.
    """
    precio = float(inv.get("importe", 0) or 0)
    comision = 0.0
    if inv.get("inmobiliaria"):
        comision = precio * (float(inv.get("comision_venta_pct", 0) or 0) / 100.0)
    itp = precio * (ITP_PCT / 100.0)
    notaria = itp * (NOTARIA_PCT_DEL_ITP / 100.0)
    registro = itp * (REGISTRO_PCT_DEL_ITP / 100.0)
    gestoria = GESTORIA_EUR
    total = precio + comision + itp + notaria + registro + gestoria
    return {
        "precio": precio,
        "comision": comision,
        "itp": itp,
        "notaria": notaria,
        "registro": registro,
        "gestoria": gestoria,
        "total": total,
    }


def _coste_total_inmueble(inv: dict) -> float:
    """Coste total de compra: importe + comisión inmobiliaria + ITP (7%) + notaría (10% ITP) + registro (10% ITP) + gestoría (300 €)."""
    return _desglose_gastos_compra(inv)["total"]


def _precio_m2_inmueble(inv: dict) -> float | None:
    """Precio por m² (importe / m² útiles o construidos). None si no hay superficie."""
    m2 = float(inv.get("m2_utiles", 0) or 0) or float(inv.get("m2_construidos", 0) or 0)
    if m2 <= 0:
        return None
    imp = float(inv.get("importe", 0) or 0)
    return imp / m2 if imp else None


def _categoria_inmueble(inv: dict) -> str:
    """Categoría del inmueble (Interesados | En Estudio). Por defecto Interesados."""
    c = (inv.get("categoria") or "").strip()
    return c if c in CATEGORIAS_INMUEBLE else CATEGORIA_INTERESADOS


def _titulo_inmueble(inv: dict, duracion_min: float | None = None) -> str:
    """Título para listado y selector: localización — precio € — precio/m² — XX min — ⚡ X m² (superficie placas si existe)."""
    loc = inv.get("localizacion", "") or "Sin ubicación"
    imp = float(inv.get("importe", 0) or 0)
    p = _precio_m2_inmueble(inv)
    if p is not None:
        base = f"{loc} — {imp:.0f} € — {p:.0f} €/m²"
    else:
        base = f"{loc} — {imp:.0f} €"
    if duracion_min is not None:
        base += f" — {duracion_min:.0f} min."
    sup_placas = float(inv.get("superficie_placas_m2", 0) or 0)
    if sup_placas > 0:
        base += f" — ⚡ {sup_placas:.0f} m²"
    return base


def _leyenda_placas_subvencion(inv: dict) -> str | None:
    """
    Devuelve texto de leyenda para la ficha: superficie disponible, nº placas, reducción teórica y si podría acogerse a subvención.
    Usa zona CTE (C/D/E), superficie_placas_m2, consumo desde certificado y AREA_PLACA_TIPICA_M2, produccion 510 kWh/placa.
    None si no hay superficie para placas.
    """
    sup = float(inv.get("superficie_placas_m2", 0) or 0)
    if sup <= 0:
        return None
    num_placas = int(sup / AREA_PLACA_TIPICA_M2)
    if num_placas <= 0:
        return f"⚡ Superficie disponible para placas: {sup:.0f} m² (insuficiente para una placa)."
    consumo = _consumo_anual_desde_certificado(inv)
    if consumo is None or consumo <= 0:
        consumo = 5000.0
    produccion_placa = 510.0
    produccion_total = num_placas * produccion_placa
    reduccion_teorica_pct = min(100.0, (produccion_total / consumo) * 100.0) if consumo else 0.0
    zona = (inv.get("zona_climatica_cte") or "").strip().upper()[:1]
    requerida_pct = None
    if zona == "C":
        requerida_pct = 25.0
    elif zona in ("D", "E"):
        requerida_pct = 35.0
    if requerida_pct is not None:
        apta = reduccion_teorica_pct >= requerida_pct
        return (
            f"⚡ **Superficie placas:** {sup:.0f} m² → hasta **{num_placas}** placas. "
            f"Reducción teórica: **{reduccion_teorica_pct:.0f} %**. "
            f"Subvención (zona {zona}) requiere ≥ **{requerida_pct:.0f} %**. "
            f"**{'Apta' if apta else 'No apta'}** para subvención."
        )
    return f"⚡ **Superficie disponible para placas:** {sup:.0f} m² → hasta **{num_placas}** placas (reducción teórica **{reduccion_teorica_pct:.0f} %**)."


def _geocode_nominatim(direccion: str) -> tuple[float, float] | None:
    """Geocodifica una dirección con Nominatim (OSM). Devuelve (lat, lon) o None. Respeta 1 req/s."""
    direccion = (direccion or "").strip()
    if not direccion:
        return None
    cache = st.session_state.get("gps_coords_cache", {})
    if direccion in cache:
        return cache[direccion]
    try:
        import time
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": direccion + ", España", "format": "json", "limit": 1}
        headers = {"User-Agent": "Hipochorro/1.0 (comparador inmuebles)"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data and isinstance(data, list) and len(data) > 0:
            lat = float(data[0].get("lat", 0))
            lon = float(data[0].get("lon", 0))
            st.session_state.setdefault("gps_coords_cache", {})[direccion] = (lat, lon)
            import time
            time.sleep(1)  # Nominatim: máx 1 petición por segundo
            return (lat, lon)
    except Exception:
        pass
    return None


def _ruta_coche_minutos(lon1: float, lat1: float, lon2: float, lat2: float) -> float | None:
    """Duración del trayecto en coche entre dos puntos (OSRM). Devuelve minutos o None."""
    try:
        url = f"https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("code") == "Ok" and data.get("routes"):
            segundos = float(data["routes"][0].get("duration", 0))
            return round(segundos / 60.0, 1)
    except Exception:
        pass
    return None


def _coords_inmueble(inv: dict) -> tuple[float, float] | None:
    """Obtiene (lat, lon) del inmueble: guardadas en ficha, posición temporal del pin, o geocodificación. None si no hay datos."""
    inv_id = inv.get("id")
    if inv.get("lat") is not None and inv.get("lon") is not None:
        try:
            return (float(inv["lat"]), float(inv["lon"]))
        except (TypeError, ValueError):
            pass
    if inv_id:
        tmp = st.session_state.get(f"pin_{inv_id}")
        if tmp and len(tmp) == 2:
            try:
                return (float(tmp[0]), float(tmp[1]))
            except (TypeError, ValueError):
                pass
    loc = (inv.get("localizacion") or "").strip()
    if loc:
        return _geocode_nominatim(loc)
    return None


def _duracion_minutos_a_destino(inv: dict, destino_str: str) -> float | None:
    """Duración en minutos por carretera desde la localización del inmueble hasta destino. Usa caché."""
    inv_id = inv.get("id")
    if not inv_id or not (destino_str or "").strip():
        return None
    cache = st.session_state.get("gps_duracion_cache", {})
    key = (inv_id, destino_str.strip())
    if key in cache:
        return cache[key]
    coords_origen = _coords_inmueble(inv)
    coords_destino = _geocode_nominatim(destino_str.strip())
    if not coords_origen or not coords_destino:
        st.session_state.setdefault("gps_duracion_cache", {})[key] = None
        return None
    lat1, lon1 = coords_origen
    lat2, lon2 = coords_destino
    minutos = _ruta_coche_minutos(lon1, lat1, lon2, lat2)
    st.session_state.setdefault("gps_duracion_cache", {})[key] = minutos
    return minutos


# Estilo para resaltar en rojo campos de comisiones/costes
_CSS_COMISION = '<span style="color:#c33; font-weight:bold;">'

# Estilo para resaltar en verde campos de bonificaciones
_CSS_BONIFICACION = '<span style="color:#083; font-weight:bold;">'


def _campo_bonificacion(label: str, value: float | int = 0, min_value: float | int = 0, max_value: int | None = None, step: float | int = 1, format_str: str | None = None, key: str | None = None, help_text: str | None = None):
    """Renderiza etiqueta en verde y número input con barra lateral verde (bonificaciones)."""
    # Streamlit exige que value, min_value, max_value y step sean del mismo tipo (int o float).
    if isinstance(value, float):
        min_value = float(min_value)
        step = float(step)
        max_value = float(max_value) if max_value is not None else None
    else:
        min_value = int(min_value)
        step = int(step)
        max_value = int(max_value) if max_value is not None else None
    col_bar, col_c = st.columns([0.012, 0.988])
    with col_bar:
        st.markdown('<div style="background:#083; min-height:52px; margin-top:6px; border-radius:2px;"></div>', unsafe_allow_html=True)
    with col_c:
        st.markdown(f'{_CSS_BONIFICACION}{label}</span>', unsafe_allow_html=True)
        kwargs = {"min_value": min_value, "value": value, "step": step}
        if max_value is not None:
            kwargs["max_value"] = max_value
        if format_str is not None:
            kwargs["format"] = format_str
        if key is not None:
            kwargs["key"] = key
        if help_text is not None:
            kwargs["help"] = help_text
        return st.number_input("", **kwargs)


def _campo_comision(label: str, value: float = 0.0, min_value: float = 0.0, step: float = 1.0, format_str: str | None = None, key: str | None = None, help_text: str | None = None):
    """Renderiza etiqueta en rojo y número input con barra lateral roja (comisiones/costes)."""
    col_bar, col_c = st.columns([0.012, 0.988])
    with col_bar:
        st.markdown('<div style="background:#c33; min-height:52px; margin-top:6px; border-radius:2px;"></div>', unsafe_allow_html=True)
    with col_c:
        st.markdown(f'{_CSS_COMISION}{label}</span>', unsafe_allow_html=True)
        kwargs = {"min_value": min_value, "value": value, "step": step}
        if format_str is not None:
            kwargs["format"] = format_str
        if key is not None:
            kwargs["key"] = key
        if help_text is not None:
            kwargs["help"] = help_text
        return st.number_input("", **kwargs)


def formulario_hipoteca(usuario_id: int):
    """Formulario de alta de hipoteca con todos los campos."""
    st.subheader("Alta de hipoteca bancaria")
    inv_sel = st.session_state.get("inmueble_seleccionado")
    def_valor = 150000.0
    def_cantidad = 150000.0
    if inv_sel and isinstance(inv_sel, dict):
        def_valor = _coste_total_inmueble(inv_sel)
        st.caption(f"💡 Valor del inmueble seleccionado en el sidebar: {inv_sel.get('localizacion', '')} — coste total {def_valor:.0f} €")
    logo_subir = st.file_uploader("Logo: sube imagen (PNG/JPG) si no usas dominio", type=["png", "jpg", "jpeg"], key="logo_upload")
    with st.form("form_hipoteca"):
        nombre_entidad = st.text_input("Nombre entidad *", placeholder="Ej: BBVA, Santander, CaixaBank")
        dominio_logo = st.text_input(
            "Dominio web para logo (opcional)",
            placeholder="Ej: bbva.com, santander.es — se intentará descargar el logo"
        )
        nombre_hipoteca = st.text_input("Nombre de la hipoteca *", placeholder="Ej: Hipoteca Fija 25 años")
        duracion_anos = st.number_input("Duración del préstamo (años) *", min_value=1, max_value=40, value=25)
        cantidad_solicitada = st.number_input("Cantidad solicitada (€) *", min_value=0.0, value=def_cantidad, step=5000.0)
        valor_inmueble = st.number_input("Valor del inmueble (€)", min_value=0.0, value=def_valor, step=5000.0)
        if valor_inmueble > 0:
            pct_financiacion = round(100 * cantidad_solicitada / valor_inmueble, 1)
            st.caption(f"Porcentaje de financiación: {pct_financiacion}%")
        st.markdown('<span title="' + HELP_TIN.replace('"', '&quot;') + '">**TIN**</span> (pasa el ratón para ver el concepto)', unsafe_allow_html=True)
        tin = st.number_input("% TIN *", min_value=0.0, max_value=30.0, value=3.5, step=0.05, format="%.2f", help=HELP_TIN)
        st.markdown('<span title="' + HELP_TAE.replace('"', '&quot;') + '">**TAE**</span> (pasa el ratón para ver el concepto)', unsafe_allow_html=True)
        tae = st.number_input("% TAE *", min_value=0.0, max_value=30.0, value=3.8, step=0.05, format="%.2f", help=HELP_TAE)
        st.markdown("---")
        st.caption("Comisiones y productos vinculados")
        meses_tin_bonificado = _campo_bonificacion("Meses con TIN bonificado al inicio", value=0, min_value=0, max_value=480, step=1, key="f_mes_tin_bonif")
        anos_bonif_amort_parcial = _campo_bonificacion("Años con comisión de amortización parcial bonificada", value=0, min_value=0, max_value=40, step=1, key="f_anos_bonif_amort")
        comision_amort_parcial_bonif = _campo_bonificacion("Comisión amortización parcial bonificada (%)", value=0.0, min_value=0.0, step=0.1, format_str="%.2f", key="f_com_bonif")
        comision_amort_parcial = _campo_comision("Comisión amortización parcial estándar (%)", value=0.0, min_value=0.0, step=0.1, format_str="%.2f", key="f_com_est")
        mantenimiento = _campo_comision("Mantenimiento cuenta (€/año)", value=0.0, step=10.0, key="f_man")
        mantenimiento_tarjeta = _campo_comision("Mantenimiento tarjeta (€/año)", value=0.0, step=10.0, key="f_man_tar")
        tasacion = _campo_comision("Tasación (€)", value=0.0, step=50.0, key="f_tas")
        comision_apertura = _campo_comision("Comisión de apertura (€)", value=0.0, step=50.0, key="f_com_ap", help_text="Comisión que cobra el banco al formalizar la hipoteca (una sola vez).")
        bonificacion_firma = _campo_bonificacion("Importe bonificado en la firma (€)", value=0.0, step=100.0, key="f_bonif_firma", help_text="El banco lo abona una sola vez en la firma; reduce el coste total.")
        bonif_nomina_eur = _campo_bonificacion("Bonificación nómina (descuento €/año)", value=0.0, step=50.0, key="f_bon_nom")
        bonif_tin_nomina_pp = _campo_bonificacion("Bonif. TIN por nómina (p.p.)", value=0.0, step=0.05, format_str="%.2f", key="f_bon_tin_nom")
        anos_bonif_nomina = _campo_bonificacion("Años bonif. nómina (0 = todo el préstamo)", value=0, min_value=0, max_value=40, step=1, key="f_ab_nom")
        seguro_hogar = _campo_comision("Seguro hogar (€/año)", value=0.0, step=20.0, key="f_sh")
        bonif_tin_seguro_hogar_pp = _campo_bonificacion("Bonif. TIN por seguro hogar (p.p.)", value=0.0, step=0.05, format_str="%.2f", key="f_shb")
        anos_bonif_seguro_hogar = _campo_bonificacion("Años bonif. seguro hogar (0 = todo)", value=0, min_value=0, max_value=40, step=1, key="f_ab_sh")
        seguro_vida = _campo_comision("Seguro vida (€/año)", value=0.0, step=20.0, key="f_sv")
        bonif_tin_seguro_vida_pp = _campo_bonificacion("Bonif. TIN por seguro vida (p.p.)", value=0.0, step=0.05, format_str="%.2f", key="f_svb")
        anos_bonif_seguro_vida = _campo_bonificacion("Años bonif. seguro vida (0 = todo)", value=0, min_value=0, max_value=40, step=1, key="f_ab_sv")
        alarma = _campo_comision("Alarma (€/año)", value=0.0, step=20.0, key="f_ala")
        bonif_tin_alarma_pp = _campo_bonificacion("Bonif. TIN por alarma (p.p.)", value=0.0, step=0.05, format_str="%.2f", key="f_alab")
        anos_bonif_alarma = _campo_bonificacion("Años bonif. alarma (0 = todo)", value=0, min_value=0, max_value=40, step=1, key="f_ab_ala")
        proteccion_pagos = _campo_comision("Protección de pagos (€/año)", value=0.0, step=20.0, key="f_pp")
        bonif_tin_proteccion_pagos_pp = _campo_bonificacion("Bonif. TIN por protección pagos (p.p.)", value=0.0, step=0.05, format_str="%.2f", key="f_ppb")
        anos_bonif_proteccion_pagos = _campo_bonificacion("Años bonif. protección pagos (0 = todo)", value=0, min_value=0, max_value=40, step=1, key="f_ab_pp")
        pension = _campo_comision("Pensión (€/año)", value=0.0, step=20.0, key="f_pen")
        bonif_tin_pension_pp = _campo_bonificacion("Bonif. TIN por pensión (p.p.)", value=0.0, step=0.05, format_str="%.2f", key="f_penb")
        anos_bonif_pension = _campo_bonificacion("Años bonif. pensión (0 = todo)", value=0, min_value=0, max_value=40, step=1, key="f_ab_pen")
        bizum = st.checkbox("Bizum vinculado", key="f_biz")
        bonif_tin_bizum_pp = _campo_bonificacion("Bonif. TIN por Bizum (p.p.)", value=0.0, step=0.05, format_str="%.2f", key="f_bizb")
        anos_bonif_bizum = _campo_bonificacion("Años bonif. Bizum (0 = todo)", value=0, min_value=0, max_value=40, step=1, key="f_ab_biz")
        tarjeta_credito = st.checkbox("Tarjeta de crédito vinculada", key="f_tar")
        bonif_tin_tarjeta_pp = _campo_bonificacion("Bonif. TIN por tarjeta (p.p.)", value=0.0, step=0.05, format_str="%.2f", key="f_tarb")
        anos_bonif_tarjeta = _campo_bonificacion("Años bonif. tarjeta (0 = todo)", value=0, min_value=0, max_value=40, step=1, key="f_ab_tar")

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
                "meses_tin_bonificado": int(meses_tin_bonificado),
                "anos_bonif_amort_parcial": int(anos_bonif_amort_parcial),
                "comision_amort_parcial_bonif": float(comision_amort_parcial_bonif),
                "comision_amort_parcial": float(comision_amort_parcial),
                "mantenimiento": float(mantenimiento),
                "mantenimiento_tarjeta": float(mantenimiento_tarjeta),
                "tasacion": float(tasacion),
                "comision_apertura": float(comision_apertura),
                "bonificacion_firma": float(bonificacion_firma),
                "bonif_nomina_eur": float(bonif_nomina_eur),
                "seguro_hogar": float(seguro_hogar),
                "seguro_vida": float(seguro_vida),
                "alarma": float(alarma),
                "proteccion_pagos": float(proteccion_pagos),
                "pension": float(pension),
                "bizum": bool(bizum),
                "tarjeta_credito": bool(tarjeta_credito),
                "bonif_tin_nomina_pp": float(bonif_tin_nomina_pp),
                "bonif_tin_seguro_hogar_pp": float(bonif_tin_seguro_hogar_pp),
                "bonif_tin_seguro_vida_pp": float(bonif_tin_seguro_vida_pp),
                "bonif_tin_alarma_pp": float(bonif_tin_alarma_pp),
                "bonif_tin_proteccion_pagos_pp": float(bonif_tin_proteccion_pagos_pp),
                "bonif_tin_pension_pp": float(bonif_tin_pension_pp),
                "bonif_tin_bizum_pp": float(bonif_tin_bizum_pp),
                "bonif_tin_tarjeta_pp": float(bonif_tin_tarjeta_pp),
                "años_bonif_nomina": int(anos_bonif_nomina),
                "años_bonif_seguro_hogar": int(anos_bonif_seguro_hogar),
                "años_bonif_seguro_vida": int(anos_bonif_seguro_vida),
                "años_bonif_alarma": int(anos_bonif_alarma),
                "años_bonif_proteccion_pagos": int(anos_bonif_proteccion_pagos),
                "años_bonif_pension": int(anos_bonif_pension),
                "años_bonif_bizum": int(anos_bonif_bizum),
                "años_bonif_tarjeta": int(anos_bonif_tarjeta),
                "tin_base": float(tin),
            }
            out = ghd.añadir_hipoteca(usuario_id, hipoteca)
            if out:
                st.session_state.hipotecas_cache = ghd.get_hipotecas(usuario_id)
                st.success("Hipoteca guardada correctamente.")
            else:
                st.error("Error al guardar. Comprueba que GITHUB_TOKEN esté configurado en Streamlit Cloud.")
        elif submitted:
            st.warning("Rellena al menos nombre de entidad y nombre de hipoteca.")


def _borrar_hipoteca(usuario_id: int, hipoteca_id: int) -> bool:
    hipotecas = ghd.get_hipotecas(usuario_id)
    nuevas = [h for h in hipotecas if h.get("id") != hipoteca_id]
    if len(nuevas) == len(hipotecas):
        return False
    return ghd.guardar_hipotecas(usuario_id, nuevas)


def _editor_hipoteca(usuario_id: int, h: dict):
    hid = h.get("id")
    st.markdown("#### Editar / borrar")

    # Logo: permitir actualizar por dominio o subida manual
    col_logo1, col_logo2 = st.columns([2, 1])
    with col_logo1:
        dominio_logo = st.text_input(
            "Dominio web para actualizar logo (opcional)",
            value="",
            placeholder="Ej: bbva.com, santander.es",
            key=f"edit_dom_{hid}",
        )
    with col_logo2:
        logo_subir = st.file_uploader(
            "Actualizar logo (PNG/JPG)",
            type=["png", "jpg", "jpeg"],
            key=f"edit_logo_{hid}",
        )

    with st.form(f"form_edit_{hid}"):
        nombre_entidad = st.text_input("Nombre entidad *", value=h.get("nombre_entidad", ""), key=f"e_ent_{hid}")
        nombre_hipoteca = st.text_input("Nombre de la hipoteca *", value=h.get("nombre_hipoteca", ""), key=f"e_nom_{hid}")
        duracion_anos = st.number_input("Duración del préstamo (años) *", min_value=1, max_value=40, value=int(h.get("duracion_anos", 25) or 25), key=f"e_dur_{hid}")
        cantidad_solicitada = st.number_input("Cantidad solicitada (€) *", min_value=0.0, value=float(h.get("cantidad_solicitada", 0) or 0), step=5000.0, key=f"e_cap_{hid}")
        valor_inmueble = st.number_input("Valor del inmueble (€)", min_value=0.0, value=float(h.get("valor_inmueble", cantidad_solicitada) or 0), step=5000.0, key=f"e_val_{hid}")
        if valor_inmueble > 0:
            pct_financiacion = round(100 * cantidad_solicitada / valor_inmueble, 1)
            st.caption(f"Porcentaje de financiación: {pct_financiacion}%")

        st.markdown('<span title="' + HELP_TIN.replace('"', '&quot;') + '">**TIN**</span> (pasa el ratón para ver el concepto)', unsafe_allow_html=True)
        tin = st.number_input("% TIN *", min_value=0.0, max_value=30.0, value=float(h.get("tin", 0) or 0), step=0.05, format="%.2f", help=HELP_TIN, key=f"e_tin_{hid}")
        st.markdown('<span title="' + HELP_TAE.replace('"', '&quot;') + '">**TAE**</span> (pasa el ratón para ver el concepto)', unsafe_allow_html=True)
        tae = st.number_input("% TAE *", min_value=0.0, max_value=30.0, value=float(h.get("tae", 0) or 0), step=0.05, format="%.2f", help=HELP_TAE, key=f"e_tae_{hid}")

        st.markdown("---")
        st.caption("Comisiones y productos vinculados")
        meses_tin_bonificado = _campo_bonificacion("Meses con TIN bonificado al inicio", value=int(h.get("meses_tin_bonificado", 0) or 0), min_value=0, max_value=480, step=1, key=f"e_mes_tin_bonif_{hid}")
        anos_bonif_amort_parcial = _campo_bonificacion("Años con comisión de amortización parcial bonificada", value=int(h.get("anos_bonif_amort_parcial", 0) or 0), min_value=0, max_value=40, step=1, key=f"e_anos_bonif_amort_{hid}")
        comision_amort_parcial_bonif = _campo_bonificacion("Comisión amortización parcial bonificada (%)", value=float(h.get("comision_amort_parcial_bonif", 0) or 0), min_value=0.0, step=0.1, format_str="%.2f", key=f"e_com_bonif_{hid}")
        comision_amort_parcial = _campo_comision("Comisión amortización parcial estándar (%)", value=float(h.get("comision_amort_parcial", 0) or 0), min_value=0.0, step=0.1, format_str="%.2f", key=f"e_com_{hid}")
        mantenimiento = _campo_comision("Mantenimiento cuenta (€/año)", value=float(h.get("mantenimiento", 0) or 0), step=10.0, key=f"e_man_{hid}")
        mantenimiento_tarjeta = _campo_comision("Mantenimiento tarjeta (€/año)", value=float(h.get("mantenimiento_tarjeta", 0) or 0), step=10.0, key=f"e_man_tar_{hid}")
        tasacion = _campo_comision("Tasación (€)", value=float(h.get("tasacion", 0) or 0), step=50.0, key=f"e_tas_{hid}")
        comision_apertura = _campo_comision("Comisión de apertura (€)", value=float(h.get("comision_apertura", 0) or 0), step=50.0, key=f"e_com_ap_{hid}", help_text="Comisión que cobra el banco al formalizar la hipoteca (una sola vez).")
        bonificacion_firma = _campo_bonificacion("Importe bonificado en la firma (€)", value=float(h.get("bonificacion_firma", 0) or 0), step=100.0, key=f"e_bonif_firma_{hid}", help_text="El banco lo abona una sola vez en la firma; reduce el coste total.")
        bonif_nomina_eur = _campo_bonificacion("Bonificación nómina (descuento €/año)", value=float(h.get("bonif_nomina_eur", h.get("bonif_nomina", 0) or 0)), step=50.0, key=f"e_bon_{hid}")
        bonif_tin_nomina_pp = _campo_bonificacion("Bonif. TIN por nómina (p.p.)", value=float(h.get("bonif_tin_nomina_pp", 0) or 0), step=0.05, format_str="%.2f", key=f"e_bon_tin_nom_{hid}")
        anos_bonif_nomina = _campo_bonificacion("Años bonif. nómina (0 = todo)", value=int(h.get("años_bonif_nomina", 0) or 0), min_value=0, max_value=40, step=1, key=f"e_ab_nom_{hid}")
        seguro_hogar = _campo_comision("Seguro hogar (€/año)", value=float(h.get("seguro_hogar", 0) or 0), step=20.0, key=f"e_sh_{hid}")
        bonif_tin_seguro_hogar_pp = _campo_bonificacion("Bonif. TIN por seguro hogar (p.p.)", value=float(h.get("bonif_tin_seguro_hogar_pp", 0) or 0), step=0.05, format_str="%.2f", key=f"e_shb_{hid}")
        anos_bonif_seguro_hogar = _campo_bonificacion("Años bonif. seguro hogar (0 = todo)", value=int(h.get("años_bonif_seguro_hogar", 0) or 0), min_value=0, max_value=40, step=1, key=f"e_ab_sh_{hid}")
        seguro_vida = _campo_comision("Seguro vida (€/año)", value=float(h.get("seguro_vida", 0) or 0), step=20.0, key=f"e_sv_{hid}")
        bonif_tin_seguro_vida_pp = _campo_bonificacion("Bonif. TIN por seguro vida (p.p.)", value=float(h.get("bonif_tin_seguro_vida_pp", 0) or 0), step=0.05, format_str="%.2f", key=f"e_svb_{hid}")
        anos_bonif_seguro_vida = _campo_bonificacion("Años bonif. seguro vida (0 = todo)", value=int(h.get("años_bonif_seguro_vida", 0) or 0), min_value=0, max_value=40, step=1, key=f"e_ab_sv_{hid}")
        alarma = _campo_comision("Alarma (€/año)", value=float(h.get("alarma", 0) or 0), step=20.0, key=f"e_ala_{hid}")
        bonif_tin_alarma_pp = _campo_bonificacion("Bonif. TIN por alarma (p.p.)", value=float(h.get("bonif_tin_alarma_pp", 0) or 0), step=0.05, format_str="%.2f", key=f"e_alab_{hid}")
        anos_bonif_alarma = _campo_bonificacion("Años bonif. alarma (0 = todo)", value=int(h.get("años_bonif_alarma", 0) or 0), min_value=0, max_value=40, step=1, key=f"e_ab_ala_{hid}")
        proteccion_pagos = _campo_comision("Protección de pagos (€/año)", value=float(h.get("proteccion_pagos", 0) or 0), step=20.0, key=f"e_pp_{hid}")
        bonif_tin_proteccion_pagos_pp = _campo_bonificacion("Bonif. TIN por protección pagos (p.p.)", value=float(h.get("bonif_tin_proteccion_pagos_pp", 0) or 0), step=0.05, format_str="%.2f", key=f"e_ppb_{hid}")
        anos_bonif_proteccion_pagos = _campo_bonificacion("Años bonif. protección pagos (0 = todo)", value=int(h.get("años_bonif_proteccion_pagos", 0) or 0), min_value=0, max_value=40, step=1, key=f"e_ab_pp_{hid}")
        pension = _campo_comision("Pensión (€/año)", value=float(h.get("pension", 0) or 0), step=20.0, key=f"e_pen_{hid}")
        bonif_tin_pension_pp = _campo_bonificacion("Bonif. TIN por pensión (p.p.)", value=float(h.get("bonif_tin_pension_pp", 0) or 0), step=0.05, format_str="%.2f", key=f"e_penb_{hid}")
        anos_bonif_pension = _campo_bonificacion("Años bonif. pensión (0 = todo)", value=int(h.get("años_bonif_pension", 0) or 0), min_value=0, max_value=40, step=1, key=f"e_ab_pen_{hid}")
        bizum = st.checkbox("Bizum vinculado", value=bool(h.get("bizum", False)), key=f"e_biz_{hid}")
        bonif_tin_bizum_pp = _campo_bonificacion("Bonif. TIN por Bizum (p.p.)", value=float(h.get("bonif_tin_bizum_pp", 0) or 0), step=0.05, format_str="%.2f", key=f"e_bizb_{hid}")
        anos_bonif_bizum = _campo_bonificacion("Años bonif. Bizum (0 = todo)", value=int(h.get("años_bonif_bizum", 0) or 0), min_value=0, max_value=40, step=1, key=f"e_ab_biz_{hid}")
        tarjeta_credito = st.checkbox("Tarjeta de crédito vinculada", value=bool(h.get("tarjeta_credito", False)), key=f"e_tar_{hid}")
        bonif_tin_tarjeta_pp = _campo_bonificacion("Bonif. TIN por tarjeta (p.p.)", value=float(h.get("bonif_tin_tarjeta_pp", 0) or 0), step=0.05, format_str="%.2f", key=f"e_tarb_{hid}")
        anos_bonif_tarjeta = _campo_bonificacion("Años bonif. tarjeta (0 = todo)", value=int(h.get("años_bonif_tarjeta", 0) or 0), min_value=0, max_value=40, step=1, key=f"e_ab_tar_{hid}")

        guardar = st.form_submit_button("Guardar cambios")

    if guardar:
        logo_path = h.get("logo_path")
        if dominio_logo:
            img_bytes = intentar_logo_desde_dominio(dominio_logo)
            if img_bytes:
                logo_path = ghd.subir_logo_desde_bytes(nombre_entidad, img_bytes)
            else:
                st.warning("No se pudo descargar el logo desde el dominio.")
        if logo_subir is not None:
            logo_path = ghd.subir_logo_desde_bytes(nombre_entidad, logo_subir.getvalue())

        actualizado = {
            **h,
            "nombre_entidad": nombre_entidad,
            "logo_path": logo_path,
            "nombre_hipoteca": nombre_hipoteca,
            "duracion_anos": int(duracion_anos),
            "cantidad_solicitada": float(cantidad_solicitada),
            "valor_inmueble": float(valor_inmueble),
            "pct_financiacion": round(100 * cantidad_solicitada / valor_inmueble, 1) if valor_inmueble else 0,
            "tin": float(tin),
            "tae": float(tae),
            "meses_tin_bonificado": int(meses_tin_bonificado),
            "anos_bonif_amort_parcial": int(anos_bonif_amort_parcial),
            "comision_amort_parcial_bonif": float(comision_amort_parcial_bonif),
            "comision_amort_parcial": float(comision_amort_parcial),
            "mantenimiento": float(mantenimiento),
            "mantenimiento_tarjeta": float(mantenimiento_tarjeta),
            "tasacion": float(tasacion),
            "comision_apertura": float(comision_apertura),
            "bonificacion_firma": float(bonificacion_firma),
            "bonif_nomina_eur": float(bonif_nomina_eur),
            "seguro_hogar": float(seguro_hogar),
            "seguro_vida": float(seguro_vida),
            "alarma": float(alarma),
            "proteccion_pagos": float(proteccion_pagos),
            "pension": float(pension),
            "bizum": bool(bizum),
            "tarjeta_credito": bool(tarjeta_credito),
            "bonif_tin_nomina_pp": float(bonif_tin_nomina_pp),
            "bonif_tin_seguro_hogar_pp": float(bonif_tin_seguro_hogar_pp),
            "bonif_tin_seguro_vida_pp": float(bonif_tin_seguro_vida_pp),
            "bonif_tin_alarma_pp": float(bonif_tin_alarma_pp),
            "bonif_tin_proteccion_pagos_pp": float(bonif_tin_proteccion_pagos_pp),
            "bonif_tin_pension_pp": float(bonif_tin_pension_pp),
            "bonif_tin_bizum_pp": float(bonif_tin_bizum_pp),
            "bonif_tin_tarjeta_pp": float(bonif_tin_tarjeta_pp),
            "años_bonif_nomina": int(anos_bonif_nomina),
            "años_bonif_seguro_hogar": int(anos_bonif_seguro_hogar),
            "años_bonif_seguro_vida": int(anos_bonif_seguro_vida),
            "años_bonif_alarma": int(anos_bonif_alarma),
            "años_bonif_proteccion_pagos": int(anos_bonif_proteccion_pagos),
            "años_bonif_pension": int(anos_bonif_pension),
            "años_bonif_bizum": int(anos_bonif_bizum),
            "años_bonif_tarjeta": int(anos_bonif_tarjeta),
            "tin_base": float(tin),
        }
        if ghd.actualizar_hipoteca(usuario_id, actualizado):
            st.success("Cambios guardados.")
            st.rerun()
        else:
            st.error("No se pudieron guardar cambios (¿GITHUB_TOKEN configurado?).")

    st.markdown("---")
    st.markdown("#### Duplicar hipoteca")
    st.caption("Crea una copia para probar variantes (por ejemplo cambiando TIN/TAE) sin reescribirla a mano.")
    col_dup1, col_dup2, col_dup3 = st.columns([2, 1, 1])
    with col_dup1:
        nombre_copia = st.text_input(
            "Nombre para la copia",
            value=f"{h.get('nombre_hipoteca', '')} (copia)",
            key=f"dup_name_{hid}",
        )
    with col_dup2:
        tin_copia = st.number_input(
            "% TIN (opcional)",
            min_value=0.0,
            max_value=30.0,
            value=float(h.get("tin", 0) or 0),
            step=0.05,
            format="%.2f",
            help=HELP_TIN,
            key=f"dup_tin_{hid}",
        )
    with col_dup3:
        tae_copia = st.number_input(
            "% TAE (opcional)",
            min_value=0.0,
            max_value=30.0,
            value=float(h.get("tae", 0) or 0),
            step=0.05,
            format="%.2f",
            help=HELP_TAE,
            key=f"dup_tae_{hid}",
        )

    if st.button("Duplicar ahora", key=f"dup_btn_{hid}", width="stretch"):
        copia = {k: v for k, v in h.items() if k != "id"}
        copia["nombre_hipoteca"] = nombre_copia.strip() or f"{h.get('nombre_hipoteca','')} (copia)"
        copia["tin"] = float(tin_copia)
        copia["tae"] = float(tae_copia)
        out = ghd.añadir_hipoteca(usuario_id, copia)
        if out:
            st.success("Hipoteca duplicada.")
            st.rerun()
        else:
            st.error("No se pudo duplicar (¿GITHUB_TOKEN configurado?).")

    st.markdown("---")
    st.markdown("#### Borrar hipoteca")
    confirmar = st.checkbox("Confirmo que quiero borrar esta hipoteca", key=f"del_ok_{hid}")
    if st.button("Eliminar definitivamente", key=f"del_btn_{hid}", disabled=not confirmar):
        if _borrar_hipoteca(usuario_id, hid):
            st.success("Hipoteca eliminada.")
            st.rerun()
        else:
            st.error("No se pudo eliminar.")


def _f(h: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(h.get(key, default) or default)
    except Exception:
        return float(default)


def _get_tin_base(h: dict) -> float:
    """TIN base (sin bonificaciones). Compatibilidad con hipotecas antiguas."""
    v = h.get("tin_base", None)
    if v is None:
        v = h.get("tin", 0)
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _bonif_nomina_eur(h: dict) -> float:
    """
    Descuento anual en euros por nómina (si lo usas).
    Compatibilidad: en versiones antiguas, `bonif_nomina` era un importe €/año.
    """
    if "bonif_nomina_eur" in h:
        return _f(h, "bonif_nomina_eur", 0.0)
    legacy = _f(h, "bonif_nomina", 0.0)
    # Heurística: si parece un importe en euros, lo tratamos como tal.
    return legacy if legacy > 5 else 0.0


def _bonif_tin_pp_total(h: dict, incluir: dict) -> float:
    """
    Suma bonificaciones en puntos porcentuales (p.p.) que reducen el TIN.
    `incluir` controla si un producto cuenta para la bonificación.
    """
    total = 0.0
    if incluir.get("nomina", False):
        total += _f(h, "bonif_tin_nomina_pp", 0.0)
    if incluir.get("seguro_hogar", False):
        total += _f(h, "bonif_tin_seguro_hogar_pp", 0.0)
    if incluir.get("seguro_vida", False):
        total += _f(h, "bonif_tin_seguro_vida_pp", 0.0)
    if incluir.get("alarma", False):
        total += _f(h, "bonif_tin_alarma_pp", 0.0)
    if incluir.get("proteccion_pagos", False):
        total += _f(h, "bonif_tin_proteccion_pagos_pp", 0.0)
    if incluir.get("pension", False):
        total += _f(h, "bonif_tin_pension_pp", 0.0)
    if incluir.get("bizum", False) and bool(h.get("bizum", False)):
        total += _f(h, "bonif_tin_bizum_pp", 0.0)
    if incluir.get("tarjeta", False) and bool(h.get("tarjeta_credito", False)):
        total += _f(h, "bonif_tin_tarjeta_pp", 0.0)
    return max(0.0, total)


def _coste_anual_vinculados(
    h: dict,
    precios_externos: dict | None = None,
    usar_externos: bool = False,
) -> float:
    """
    Coste anual de vinculaciones (seguros, mantenimiento, etc.).
    Si `usar_externos=True`, sustituye algunos importes por precios externos (p.ej. seguros/alarma).
    """
    precios_externos = precios_externos or {}

    mantenimiento = _f(h, "mantenimiento", 0.0)
    mantenimiento_tarjeta = _f(h, "mantenimiento_tarjeta", 0.0)
    seguro_hogar = _f(h, "seguro_hogar", 0.0)
    seguro_vida = _f(h, "seguro_vida", 0.0)
    alarma = _f(h, "alarma", 0.0)
    proteccion_pagos = _f(h, "proteccion_pagos", 0.0)
    pension = _f(h, "pension", 0.0)

    if usar_externos:
        # Si el usuario compra fuera, comparamos con los precios externos.
        seguro_hogar = float(precios_externos.get("seguro_hogar", seguro_hogar) or seguro_hogar)
        seguro_vida = float(precios_externos.get("seguro_vida", seguro_vida) or seguro_vida)
        alarma = float(precios_externos.get("alarma", alarma) or alarma)

    return (
        mantenimiento
        + mantenimiento_tarjeta
        + seguro_hogar
        + seguro_vida
        + alarma
        + proteccion_pagos
        + pension
        - _bonif_nomina_eur(h)
    )


def coste_anual_vinculados(h: dict) -> float:
    """Compatibilidad: coste anual usando importes de la hipoteca (vinculados del banco)."""
    return _coste_anual_vinculados(h, precios_externos=None, usar_externos=False)


def _anos_bonif(h: dict, key: str) -> int:
    """Años que se mantiene la bonificación para este producto. 0 = todos los años del préstamo."""
    return int(h.get("años_bonif_" + key, 0) or 0)


def get_plan_tin_anual(h: dict, num_anos: int) -> list:
    """
    TIN (%) a aplicar cada año según bonificaciones con caducidad.
    plan_tin_anual[i] = TIN para el año i+1.
    Si años_bonif de un producto es 0, se aplica todo el préstamo; si es N, solo años 1..N.
    """
    tin_base = _get_tin_base(h)
    num_anos = max(0, int(num_anos))
    plan = []
    for ano in range(1, num_anos + 1):
        bonif = 0.0
        if _anos_bonif(h, "nomina") == 0 or _anos_bonif(h, "nomina") >= ano:
            bonif += _f(h, "bonif_tin_nomina_pp", 0.0)
        if _anos_bonif(h, "seguro_hogar") == 0 or _anos_bonif(h, "seguro_hogar") >= ano:
            bonif += _f(h, "bonif_tin_seguro_hogar_pp", 0.0)
        if _anos_bonif(h, "seguro_vida") == 0 or _anos_bonif(h, "seguro_vida") >= ano:
            bonif += _f(h, "bonif_tin_seguro_vida_pp", 0.0)
        if _anos_bonif(h, "alarma") == 0 or _anos_bonif(h, "alarma") >= ano:
            bonif += _f(h, "bonif_tin_alarma_pp", 0.0)
        if _anos_bonif(h, "proteccion_pagos") == 0 or _anos_bonif(h, "proteccion_pagos") >= ano:
            bonif += _f(h, "bonif_tin_proteccion_pagos_pp", 0.0)
        if _anos_bonif(h, "pension") == 0 or _anos_bonif(h, "pension") >= ano:
            bonif += _f(h, "bonif_tin_pension_pp", 0.0)
        if (h.get("bizum")) and (_anos_bonif(h, "bizum") == 0 or _anos_bonif(h, "bizum") >= ano):
            bonif += _f(h, "bonif_tin_bizum_pp", 0.0)
        if (h.get("tarjeta_credito")) and (_anos_bonif(h, "tarjeta") == 0 or _anos_bonif(h, "tarjeta") >= ano):
            bonif += _f(h, "bonif_tin_tarjeta_pp", 0.0)
        plan.append(max(0.0, tin_base - bonif))
    return plan


def _coste_anual_vinculados_año(
    h: dict,
    ano: int,
    precios_externos: dict | None = None,
    usar_externos: bool = False,
) -> float:
    """
    Coste de vinculaciones en un año concreto.
    Solo se incluye el coste de cada producto si su bonificación sigue vigente ese año
    (años_bonif es 0 = todo el préstamo, o años_bonif >= ano).

    Seguro de hogar (obligatorio):
    - Hipoteca CON bonificación/vinculación: años 1..años_bonif usa coste banco; pasados esos años usa seguro externo.
    - Hipoteca SIN vinculación seguro hogar: todos los años usa el coste del seguro externo obligatorio.
    """
    precios_externos = precios_externos or {}
    total = 0.0
    # Siempre: mantenimiento cuenta y tarjeta (sin caducidad por defecto)
    total += _f(h, "mantenimiento", 0.0) + _f(h, "mantenimiento_tarjeta", 0.0)
    # Nómina descuento €: solo si aplica ese año
    if _anos_bonif(h, "nomina") == 0 or _anos_bonif(h, "nomina") >= ano:
        total -= _bonif_nomina_eur(h)
    # Seguro de hogar: obligatorio. Con bonificación → años de bonif = coste banco; resto = externo. Sin vinculación → siempre externo.
    tiene_seguro_hogar_vinculado = _f(h, "seguro_hogar", 0.0) > 0 or _f(h, "bonif_tin_seguro_hogar_pp", 0.0) > 0
    anos_bonif_sh = _anos_bonif(h, "seguro_hogar")
    if tiene_seguro_hogar_vinculado:
        if anos_bonif_sh == 0 or ano <= anos_bonif_sh:
            total += _f(h, "seguro_hogar", 0.0)
        else:
            total += float(precios_externos.get("seguro_hogar", 0) or 0)
    else:
        total += float(precios_externos.get("seguro_hogar", 0) or 0)
    if _anos_bonif(h, "seguro_vida") == 0 or _anos_bonif(h, "seguro_vida") >= ano:
        v = _f(h, "seguro_vida", 0.0)
        if usar_externos and precios_externos.get("seguro_vida") is not None:
            v = float(precios_externos.get("seguro_vida", v) or v)
        total += v
    if _anos_bonif(h, "alarma") == 0 or _anos_bonif(h, "alarma") >= ano:
        v = _f(h, "alarma", 0.0)
        if usar_externos and precios_externos.get("alarma") is not None:
            v = float(precios_externos.get("alarma", v) or v)
        total += v
    if _anos_bonif(h, "proteccion_pagos") == 0 or _anos_bonif(h, "proteccion_pagos") >= ano:
        total += _f(h, "proteccion_pagos", 0.0)
    if _anos_bonif(h, "pension") == 0 or _anos_bonif(h, "pension") >= ano:
        total += _f(h, "pension", 0.0)
    return total


def coste_total_primero_ano(h: dict) -> float:
    """Aproximación coste primer año: intereses + vinculados + tasación (una vez)."""
    from lib.amortizacion import cuota_mensual_frances
    c = h.get("cantidad_solicitada", 0)
    n = h.get("duracion_anos", 25) * 12
    tin = h.get("tin", 0)
    cuota = cuota_mensual_frances(c, tin, n)
    # Mejor: primer año intereses reales
    i_mensual = tin / 100 / 12
    cap = c
    intereses = 0
    for _ in range(12):
        im = cap * i_mensual
        am = cuota - im
        intereses += im
        cap -= am
    bonif_firma = float(h.get("bonificacion_firma", 0) or 0)
    com_ap = float(h.get("comision_apertura", 0) or 0)
    return intereses + coste_anual_vinculados(h) + float(h.get("tasacion", 0) or 0) + com_ap - bonif_firma


def _duracion_str(meses: int) -> str:
    meses = int(max(0, meses))
    a = meses // 12
    m = meses % 12
    if m == 0:
        return f"{a} años"
    return f"{a} años {m} meses"


def _retencion_ahorro(rendimiento_bruto: float) -> float:
    """Retención sobre rendimientos del ahorro (tramos España). Devuelve el importe a pagar."""
    if rendimiento_bruto <= 0:
        return 0.0
    base = float(rendimiento_bruto)
    impuesto = 0.0
    limite_anterior = 0.0
    for limite, tipo in TRAMOS_RETENCION_AHORRO:
        tramo = min(base, limite) - limite_anterior
        if tramo > 0:
            impuesto += tramo * tipo
        if base <= limite:
            break
        limite_anterior = limite
    return round(impuesto, 2)


def _ahorro_amortizar(
    h: dict,
    importe_amort_anual: float,
) -> tuple[float, float, float]:
    """
    Calcula ahorro neto por amortizar: intereses evitados - comisiones por amortización.
    Tiene en cuenta comisión bonificada (años bonif) vs estándar.
    Devuelve (intereses_ahorrados, comisiones_totales, ahorro_neto).
    """
    if importe_amort_anual <= 0:
        return (0.0, 0.0, 0.0)
    capital = float(h.get("cantidad_solicitada", 0) or 0)
    anos = int(h.get("duracion_anos", 0) or 0)
    if capital <= 0 or anos <= 0:
        return (0.0, 0.0, 0.0)
    tin_base = _get_tin_base(h)
    plan_tin_anual = get_plan_tin_anual(h, anos)
    tin_efectivo = float(plan_tin_anual[0]) if plan_tin_anual else tin_base
    anos_bonif = int(h.get("anos_bonif_amort_parcial", 0) or 0)
    comision_bonif = float(h.get("comision_amort_parcial_bonif", 0) or 0)
    comision_estandar = float(h.get("comision_amort_parcial", 0) or 0)

    cuadro_sin = am.cuadro_amortizacion_anual(
        capital, tin_efectivo, anos, 0.0,
        plan_tin_anual=plan_tin_anual,
    )
    cuadro_con = am.cuadro_amortizacion_anual(
        capital, tin_efectivo, anos, importe_amort_anual,
        plan_tin_anual=plan_tin_anual,
    )
    intereses_sin = sum(r.get("intereses_año", 0) for r in cuadro_sin)
    intereses_con = sum(r.get("intereses_año", 0) for r in cuadro_con)
    intereses_ahorrados = intereses_sin - intereses_con

    comisiones_totales = 0.0
    for i, fila in enumerate(cuadro_con):
        extra = float(fila.get("extra_año", 0) or 0)
        if extra <= 0:
            continue
        ano = i + 1
        pct = comision_bonif if (anos_bonif and ano <= anos_bonif) else comision_estandar
        comisiones_totales += extra * (pct / 100.0)

    ahorro_neto = intereses_ahorrados - comisiones_totales
    return (round(intereses_ahorrados, 2), round(comisiones_totales, 2), round(ahorro_neto, 2))


def _resumen_costes_hipoteca(
    h: dict,
    amort_anual: float,
    plan_anual: list,
    precios_externos: dict | None = None,
    usar_externos: bool = False,
) -> dict:
    """
    Calcula métricas útiles para ranking:
    - cuota_inicial
    - intereses_totales
    - años_hasta_fin
    - meses_hasta_fin
    - pagado_en_cuotas
    - pagado_extra
    - comisiones_por_extra
    - vinculados_totales
    - coste_total (intereses + vinculados + tasación + comisiones)
    """
    precios_externos = precios_externos or {}
    capital = float(h.get("cantidad_solicitada", 0) or 0)
    anos = int(h.get("duracion_anos", 0) or 0)
    tin_base = _get_tin_base(h)
    tae = float(h.get("tae", 0) or 0)
    comision_pct = float(h.get("comision_amort_parcial", 0) or 0)

    # Bonificaciones aplicadas (en p.p. sobre TIN)
    incluir = {
        "nomina": _f(h, "bonif_tin_nomina_pp", 0.0) > 0,
        "seguro_hogar": _f(h, "seguro_hogar", 0.0) > 0 and (not usar_externos),
        "seguro_vida": _f(h, "seguro_vida", 0.0) > 0 and (not usar_externos),
        "alarma": _f(h, "alarma", 0.0) > 0 and (not usar_externos),
        "proteccion_pagos": _f(h, "proteccion_pagos", 0.0) > 0,
        "pension": _f(h, "pension", 0.0) > 0,
        "bizum": bool(h.get("bizum", False)),
        "tarjeta": bool(h.get("tarjeta_credito", False)),
    }
    bonif_pp = _bonif_tin_pp_total(h, incluir)
    plan_tin_anual = get_plan_tin_anual(h, anos)
    tin_efectivo = float(plan_tin_anual[0]) if plan_tin_anual else max(0.0, tin_base - bonif_pp)

    cuota_inicial = (
        am.cuota_mensual_frances(capital, tin_efectivo, max(anos, 1) * 12)
        if capital > 0 and anos > 0
        else 0.0
    )
    cuadro = am.cuadro_amortizacion_anual(
        capital,
        tin_efectivo,
        anos,
        float(amort_anual or 0),
        plan_anual=plan_anual,
        plan_tin_anual=plan_tin_anual,
    )

    intereses_totales = sum(r.get("intereses_año", 0) for r in cuadro)
    meses_hasta_fin = int(sum(r.get("meses_pagados", 0) for r in cuadro))
    años_hasta_fin = (meses_hasta_fin / 12.0) if meses_hasta_fin else 0.0
    pagado_en_cuotas = sum((r.get("cuota_mensual", 0) * r.get("meses_pagados", 0)) for r in cuadro)
    pagado_extra = sum(r.get("extra_año", 0) for r in cuadro)
    comisiones_por_extra = (comision_pct / 100.0) * pagado_extra
    vinculados_totales = sum(
        _coste_anual_vinculados_año(h, y, precios_externos, usar_externos)
        for y in range(1, len(cuadro) + 1)
    )
    coste_anual = _coste_anual_vinculados_año(h, 1, precios_externos, usar_externos)

    bonificacion_firma = float(h.get("bonificacion_firma", 0) or 0)
    comision_apertura = float(h.get("comision_apertura", 0) or 0)
    tasacion = float(h.get("tasacion", 0) or 0)
    coste_total = intereses_totales + vinculados_totales + tasacion + comision_apertura + comisiones_por_extra - bonificacion_firma

    return {
        "tae": tae,
        "tin_base": float(tin_base),
        "bonif_pp": float(bonif_pp),
        "tin_efectivo": float(tin_efectivo),
        "coste_anual_vinculados": float(coste_anual),
        "cuota_inicial": float(cuota_inicial),
        "intereses_totales": float(intereses_totales),
        "años_hasta_fin": float(años_hasta_fin),
        "meses_hasta_fin": int(meses_hasta_fin),
        "pagado_en_cuotas": float(pagado_en_cuotas),
        "pagado_extra": float(pagado_extra),
        "comisiones_por_extra": float(comisiones_por_extra),
        "vinculados_totales": float(vinculados_totales),
        "comision_apertura": float(comision_apertura),
        "bonificacion_firma": float(bonificacion_firma),
        "coste_total": float(coste_total),
        "cuadro": cuadro,
    }


def _editor_inmueble(usuario_id: int, inv: dict):
    """Formulario de edición de un inmueble en expander."""
    inv_id = inv.get("id")
    with st.form(f"form_edit_inm_{inv_id}"):
        importe = st.number_input("Importe (€)", min_value=0.0, value=float(inv.get("importe", 0) or 0), step=5000.0, key=f"ei_imp_{inv_id}")
        localizacion = st.text_input("Localización", value=inv.get("localizacion", "") or "", key=f"ei_loc_{inv_id}")
        ano_construccion = st.number_input("Año construcción", min_value=1800, max_value=2030, value=int(inv.get("ano_construccion", 0) or 0), step=1, key=f"ei_ano_{inv_id}")
        m2_construidos = st.number_input("m² construidos", min_value=0.0, value=float(inv.get("m2_construidos", 0) or 0), step=1.0, key=f"ei_m2c_{inv_id}")
        m2_utiles = st.number_input("m² útiles", min_value=0.0, value=float(inv.get("m2_utiles", 0) or 0), step=1.0, key=f"ei_m2u_{inv_id}")
        superficie_placas_m2 = st.number_input("Superficie disponible para placas solares (m²)", min_value=0.0, value=float(inv.get("superficie_placas_m2", 0) or 0), step=1.0, key=f"ei_sup_placas_{inv_id}", help="Superficie útil para instalar placas; sirve para estimar nº de placas y si podría acogerse a subvención.")
        habitaciones = st.number_input("Habitaciones", min_value=0, max_value=20, value=int(inv.get("habitaciones", 0) or 0), step=1, key=f"ei_hab_{inv_id}")
        banos = st.number_input("Baños", min_value=0, max_value=10, value=int(inv.get("banos", 0) or 0), step=1, key=f"ei_ban_{inv_id}")
        cert_legacy = inv.get("certificado_energetico") or "—"
        consumo_exacto = float(inv.get("consumo_exacto_kwh_m2", 0) or 0)
        emisiones_exactas = float(inv.get("emisiones_exactas_kg_m2", 0) or 0)
        if consumo_exacto > 0:
            cert_consumo_val = _letra_desde_consumo_kwh_m2(consumo_exacto)
        else:
            cert_consumo_val = inv.get("certificado_consumo") or cert_legacy or "—"
        if emisiones_exactas > 0:
            cert_emisiones_val = _letra_desde_emisiones_kg_m2(emisiones_exactas)
        else:
            cert_emisiones_val = inv.get("certificado_emisiones") or cert_legacy or "—"
        idx_consumo = CERT_ENERGETICO_OPCIONES.index(cert_consumo_val) if cert_consumo_val in CERT_ENERGETICO_OPCIONES else 0
        idx_emisiones = CERT_ENERGETICO_OPCIONES.index(cert_emisiones_val) if cert_emisiones_val in CERT_ENERGETICO_OPCIONES else 0
        st.caption("**Certificado energético:** introduce el valor exacto (kWh/m²·año o kg CO₂/m²·año) para que se asigne la letra; si no, elige la letra y se usará el valor medio del rango.")
        col_cert1, col_cert2 = st.columns(2)
        with col_cert1:
            consumo_exacto_input = st.number_input("Consumo exacto (kWh/m²·año)", min_value=0.0, value=consumo_exacto, step=5.0, key=f"ei_consumo_ex_{inv_id}", help="Opcional. Si lo rellenas, se asigna la letra automáticamente.")
            certificado_consumo = st.selectbox("Cert. energético (consumo)", CERT_ENERGETICO_OPCIONES, index=idx_consumo, key=f"ei_cert_cons_{inv_id}", disabled=(consumo_exacto_input > 0))
            if consumo_exacto_input > 0:
                st.caption(f"→ Letra asignada: **{_letra_desde_consumo_kwh_m2(consumo_exacto_input)}**")
        with col_cert2:
            emisiones_exactas_input = st.number_input("Emisiones exactas (kg CO₂/m²·año)", min_value=0.0, value=emisiones_exactas, step=1.0, key=f"ei_emisiones_ex_{inv_id}", help="Opcional. Si lo rellenas, se asigna la letra automáticamente.")
            certificado_emisiones = st.selectbox("Cert. energético (emisiones)", CERT_ENERGETICO_OPCIONES, index=idx_emisiones, key=f"ei_cert_emis_{inv_id}", disabled=(emisiones_exactas_input > 0))
            if emisiones_exactas_input > 0:
                st.caption(f"→ Letra asignada: **{_letra_desde_emisiones_kg_m2(emisiones_exactas_input)}**")
        zona_cte_val = (inv.get("zona_climatica_cte") or "").strip() or "—"
        idx_zona = ZONAS_CTE_OPCIONES.index(zona_cte_val) if zona_cte_val in ZONAS_CTE_OPCIONES else 0
        zona_climatica_cte = st.selectbox("Zona climática CTE", ZONAS_CTE_OPCIONES, index=idx_zona, key=f"ei_zona_cte_{inv_id}", help="Clasificación según Código Técnico de la Edificación (ej. B3, C2).")
        notas = st.text_area("Notas", value=inv.get("notas", "") or "", height=80, placeholder="Ej: oferta realizada, necesita reforma…", key=f"ei_notas_{inv_id}")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            piscina = st.checkbox("Piscina", value=bool(inv.get("piscina", False)), key=f"ei_pis_{inv_id}")
        with col2:
            sotano = st.checkbox("Sótano", value=bool(inv.get("sotano", False)), key=f"ei_sot_{inv_id}")
        with col3:
            placas_solares = st.checkbox("Placas solares", value=bool(inv.get("placas_solares", False)), key=f"ei_placas_{inv_id}")
        with col4:
            inmobiliaria = st.checkbox("Venta por inmobiliaria", value=bool(inv.get("inmobiliaria", False)), key=f"ei_inm_{inv_id}")
        comision_venta_pct = st.number_input("% comisión venta (inmobiliaria)", min_value=0.0, max_value=20.0, value=float(inv.get("comision_venta_pct", 0) or 0), step=0.5, key=f"ei_com_{inv_id}")
        url_anuncio = st.text_input("URL del anuncio Idealista", value=inv.get("url_anuncio", "") or "", key=f"ei_url_{inv_id}", placeholder="https://www.idealista.com/...")
        url_inmobiliaria = st.text_input("URL inmobiliaria", value=inv.get("url_inmobiliaria", "") or "", key=f"ei_url_inm_{inv_id}", placeholder="https://...", help="Web propia de la inmobiliaria con el anuncio; suele permitir extraer las imágenes con más facilidad.")
        cat_actual = _categoria_inmueble(inv)
        categoria = st.radio("Categoría", CATEGORIAS_INMUEBLE, horizontal=True, index=CATEGORIAS_INMUEBLE.index(cat_actual) if cat_actual in CATEGORIAS_INMUEBLE else 0, key=f"ei_cat_{inv_id}")
        if st.form_submit_button("Guardar cambios"):
            cert_consumo_final = _letra_desde_consumo_kwh_m2(consumo_exacto_input) if consumo_exacto_input > 0 else (certificado_consumo if certificado_consumo != "—" else "")
            cert_emisiones_final = _letra_desde_emisiones_kg_m2(emisiones_exactas_input) if emisiones_exactas_input > 0 else (certificado_emisiones if certificado_emisiones != "—" else "")
            inv_act = {**inv, "importe": importe, "localizacion": localizacion, "ano_construccion": int(ano_construccion), "m2_construidos": m2_construidos, "m2_utiles": m2_utiles, "superficie_placas_m2": float(superficie_placas_m2), "habitaciones": int(habitaciones), "banos": int(banos), "certificado_consumo": cert_consumo_final, "certificado_emisiones": cert_emisiones_final, "consumo_exacto_kwh_m2": float(consumo_exacto_input), "emisiones_exactas_kg_m2": float(emisiones_exactas_input), "zona_climatica_cte": zona_climatica_cte if zona_climatica_cte != "—" else "", "notas": (notas or "").strip(), "piscina": piscina, "sotano": sotano, "placas_solares": placas_solares, "inmobiliaria": inmobiliaria, "comision_venta_pct": comision_venta_pct, "url_anuncio": url_anuncio.strip(), "url_inmobiliaria": url_inmobiliaria.strip(), "categoria": categoria}
            if ghd.actualizar_inmueble(usuario_id, inv_act):
                st.success("Inmueble actualizado.")
                st.rerun()
            else:
                st.error("Error al guardar.")
    if st.button("Eliminar inmueble", key=f"del_inv_{inv_id}"):
        inmuebles = [x for x in ghd.get_inmuebles(usuario_id) if x.get("id") != inv_id]
        if ghd.guardar_inmuebles(usuario_id, inmuebles):
            if st.session_state.get("inmueble_seleccionado") and st.session_state.inmueble_seleccionado.get("id") == inv_id:
                st.session_state.inmueble_seleccionado = None
            st.success("Inmueble eliminado.")
            st.rerun()
        else:
            st.error("Error al eliminar.")


def agenda_inmuebles(usuario_id: int):
    """Pestaña agenda de inmuebles: alta, listado y fotos desde URL."""
    st.subheader("Agenda de inmuebles")
    st.caption("Alta de viviendas a comparar. En cada ficha puedes usar «Obtener / Recargar imágenes» desde el anuncio Idealista y/o la URL de la inmobiliaria para elegir qué imágenes añadir.")
    with st.form("form_inmueble"):
        importe = st.number_input("Importe de la vivienda (€) *", min_value=0.0, value=150000.0, step=5000.0)
        localizacion = st.text_input("Localización", placeholder="Ej: Madrid, zona Norte")
        ano_construccion = st.number_input("Año de construcción", min_value=1800, max_value=2030, value=2000, step=1)
        m2_construidos = st.number_input("m² construidos", min_value=0.0, value=90.0, step=1.0)
        m2_utiles = st.number_input("m² útiles", min_value=0.0, value=75.0, step=1.0)
        superficie_placas_m2 = st.number_input("Superficie disponible para placas solares (m²)", min_value=0.0, value=0.0, step=1.0, help="Superficie útil para instalar placas; sirve para estimar nº de placas y si podría acogerse a subvención.")
        habitaciones = st.number_input("Habitaciones", min_value=0, max_value=20, value=3, step=1)
        banos = st.number_input("Baños", min_value=0, max_value=10, value=2, step=1)
        st.caption("**Certificado energético:** valor exacto (opcional) para asignar letra automática; si no, elige la letra y se usará el valor medio del rango.")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            consumo_exacto_alta = st.number_input("Consumo exacto (kWh/m²·año)", min_value=0.0, value=0.0, step=5.0, help="Opcional. Si lo rellenas, se asigna la letra automáticamente.")
            certificado_consumo = st.selectbox("Cert. energético (consumo)", CERT_ENERGETICO_OPCIONES, disabled=(consumo_exacto_alta > 0))
            if consumo_exacto_alta > 0:
                st.caption(f"→ Letra asignada: **{_letra_desde_consumo_kwh_m2(consumo_exacto_alta)}**")
        with col_c2:
            emisiones_exactas_alta = st.number_input("Emisiones exactas (kg CO₂/m²·año)", min_value=0.0, value=0.0, step=1.0, help="Opcional. Si lo rellenas, se asigna la letra automáticamente.")
            certificado_emisiones = st.selectbox("Cert. energético (emisiones)", CERT_ENERGETICO_OPCIONES, disabled=(emisiones_exactas_alta > 0))
            if emisiones_exactas_alta > 0:
                st.caption(f"→ Letra asignada: **{_letra_desde_emisiones_kg_m2(emisiones_exactas_alta)}**")
        zona_climatica_cte = st.selectbox("Zona climática CTE", ZONAS_CTE_OPCIONES, index=0, help="Clasificación según CTE (ej. B3, C2). Puedes rellenar desde el PDF de zonas por municipio.")
        notas = st.text_area("Notas", placeholder="Ej: oferta realizada, necesita reforma, observaciones…", height=80)
        col_ps, col_pi, col_so = st.columns(3)
        with col_ps:
            piscina = st.checkbox("Piscina", value=False)
        with col_pi:
            sotano = st.checkbox("Sótano", value=False)
        with col_so:
            placas_solares = st.checkbox("Placas solares", value=False)
        tipo_venta = st.radio("Tipo de venta", ["Particular", "Inmobiliaria"], horizontal=True)
        inmobiliaria = tipo_venta == "Inmobiliaria"
        comision_venta_pct = st.number_input("% comisión por la venta (solo inmobiliaria)", min_value=0.0, max_value=20.0, value=3.0, step=0.5)
        url_anuncio = st.text_input("URL del anuncio Idealista", placeholder="https://www.idealista.com/...")
        url_inmobiliaria = st.text_input("URL inmobiliaria", placeholder="https://...", help="Web de la inmobiliaria con el anuncio; suele permitir listar las imágenes con más facilidad.")
        categoria = st.radio("Categoría", CATEGORIAS_INMUEBLE, horizontal=True, index=0)
        if st.form_submit_button("Dar de alta inmueble"):
            cert_consumo_alta = _letra_desde_consumo_kwh_m2(consumo_exacto_alta) if consumo_exacto_alta > 0 else (certificado_consumo if certificado_consumo != "—" else "")
            cert_emisiones_alta = _letra_desde_emisiones_kg_m2(emisiones_exactas_alta) if emisiones_exactas_alta > 0 else (certificado_emisiones if certificado_emisiones != "—" else "")
            inv = {
                "importe": float(importe),
                "localizacion": (localizacion or "").strip(),
                "ano_construccion": int(ano_construccion),
                "m2_construidos": float(m2_construidos),
                "m2_utiles": float(m2_utiles),
                "superficie_placas_m2": float(superficie_placas_m2),
                "habitaciones": int(habitaciones),
                "banos": int(banos),
                "certificado_consumo": cert_consumo_alta,
                "certificado_emisiones": cert_emisiones_alta,
                "consumo_exacto_kwh_m2": float(consumo_exacto_alta),
                "emisiones_exactas_kg_m2": float(emisiones_exactas_alta),
                "zona_climatica_cte": zona_climatica_cte if zona_climatica_cte != "—" else "",
                "notas": (notas or "").strip(),
                "piscina": bool(piscina),
                "sotano": bool(sotano),
                "placas_solares": bool(placas_solares),
                "inmobiliaria": bool(inmobiliaria),
                "comision_venta_pct": float(comision_venta_pct) if inmobiliaria else 0.0,
                "url_anuncio": (url_anuncio or "").strip(),
                "url_inmobiliaria": (url_inmobiliaria or "").strip(),
                "categoria": categoria,
                "fecha_creacion": datetime.now().isoformat(),
            }
            nuevo = ghd.añadir_inmueble(usuario_id, inv)
            if nuevo:
                st.success("Inmueble dado de alta. Abre su ficha y usa «Obtener / Recargar imágenes» para elegir las fotos desde Idealista y/o la web de la inmobiliaria.")
                st.rerun()
            else:
                st.error("Error al guardar. ¿GITHUB_TOKEN configurado?")

    inmuebles = ghd.get_inmuebles(usuario_id)
    if inmuebles:
        st.markdown("---")
        st.subheader("Inmuebles dados de alta")
        # Filtros y ordenación
        destino_gps = st.session_state.get("gps_destino", "Motril, Granada") or "Motril, Granada"
        ord_opciones = [
            "Recientes (fecha creación)",
            "Precio (menor a mayor)",
            "Precio (mayor a menor)",
            "Categoría (Interesados → En Estudio)",
            "Piscina (sí primero)",
            "Sótano (sí primero)",
            "Placas solares (sí primero)",
            "Habitaciones (más primero)",
            "m² útiles (mayor primero)",
            "€/m² (menor primero)",
            "Duración a destino (menor primero)",
        ]
        f1, f2, f3 = st.columns(3)
        with f1:
            filtro_categoria = st.selectbox("Filtrar por categoría", ["Todas", CATEGORIA_INTERESADOS, CATEGORIA_EN_ESTUDIO], key="filtro_cat_inm")
        with f2:
            filtro_piscina = st.checkbox("Solo con piscina", key="filtro_piscina_inm")
            filtro_sotano = st.checkbox("Solo con sótano", key="filtro_sotano_inm")
            filtro_placas_solares = st.checkbox("Solo con placas solares", key="filtro_placas_inm")
        with f3:
            orden_por = st.selectbox("Ordenar por", ord_opciones, key="orden_inm")
        if st.button("🔄 Calcular rutas a destino (GPS)", key="btn_calc_rutas"):
            import time
            with st.spinner("Calculando rutas por carretera a " + destino_gps + "…"):
                for inv in inmuebles:
                    _duracion_minutos_a_destino(inv, destino_gps)
                    time.sleep(1)  # Nominatim: 1 petición por segundo
            st.rerun()
        # Aplicar filtros
        lista = list(inmuebles)
        if filtro_categoria != "Todas":
            lista = [inv for inv in lista if _categoria_inmueble(inv) == filtro_categoria]
        if filtro_piscina:
            lista = [inv for inv in lista if inv.get("piscina")]
        if filtro_sotano:
            lista = [inv for inv in lista if inv.get("sotano")]
        if filtro_placas_solares:
            lista = [inv for inv in lista if inv.get("placas_solares")]
        # Ordenar (Recientes: por fecha_creacion desc; si no hay fecha, por id desc)
        def _clave_recientes(inv):
            fc = inv.get("fecha_creacion") or ""
            return (fc, -(inv.get("id") or 0))
        if orden_por == "Recientes (fecha creación)":
            lista = sorted(lista, key=_clave_recientes, reverse=True)
        elif orden_por == "Precio (menor a mayor)":
            lista = sorted(lista, key=lambda i: float(i.get("importe") or 0))
        elif orden_por == "Precio (mayor a menor)":
            lista = sorted(lista, key=lambda i: float(i.get("importe") or 0), reverse=True)
        elif orden_por == "Categoría (Interesados → En Estudio)":
            lista = sorted(lista, key=lambda i: 0 if _categoria_inmueble(i) == CATEGORIA_INTERESADOS else 1)
        elif orden_por == "Piscina (sí primero)":
            lista = sorted(lista, key=lambda i: (not i.get("piscina"),))
        elif orden_por == "Sótano (sí primero)":
            lista = sorted(lista, key=lambda i: (not i.get("sotano"),))
        elif orden_por == "Placas solares (sí primero)":
            lista = sorted(lista, key=lambda i: (not i.get("placas_solares"),))
        elif orden_por == "Habitaciones (más primero)":
            lista = sorted(lista, key=lambda i: -(i.get("habitaciones") or 0))
        elif orden_por == "m² útiles (mayor primero)":
            lista = sorted(lista, key=lambda i: -(float(i.get("m2_utiles") or 0)))
        elif orden_por == "€/m² (menor primero)":
            lista = sorted(lista, key=lambda i: (float(_precio_m2_inmueble(i) or 0) or 1e9))
        elif orden_por == "Duración a destino (menor primero)":
            with st.spinner("Calculando rutas por carretera…"):
                def _clave_duracion(inv):
                    d = _duracion_minutos_a_destino(inv, destino_gps)
                    return (d is None, d if d is not None else 1e9)
                lista = sorted(lista, key=_clave_duracion)
        for inv in lista:
            cat = _categoria_inmueble(inv)
            emoji = "🟢" if cat == CATEGORIA_INTERESADOS else "🔵"
            d_min = _duracion_minutos_a_destino(inv, destino_gps)
            titulo = f"{emoji} {_titulo_inmueble(inv, d_min)}"
            fotos_urls = ghd.get_fotos_inmueble_urls(usuario_id, inv.get("id"))
            col_thumb, col_exp = st.columns([0.08, 0.92])
            with col_thumb:
                if fotos_urls:
                    try:
                        st.image(fotos_urls[0], width="stretch")
                    except Exception:
                        st.caption("—")
                else:
                    st.caption("—")
            with col_exp:
                inv_id = inv.get("id")
                with st.expander(titulo):
                    # Badge de categoría con color (verde #083 / azul #038)
                    color = "#083" if cat == CATEGORIA_INTERESADOS else "#038"
                    st.markdown(f'<span style="color:{color}; font-weight:bold;">{cat}</span>', unsafe_allow_html=True)
                    cache_duracion = st.session_state.get("gps_duracion_cache", {})
                    minutos_destino = cache_duracion.get((inv.get("id"), destino_gps))
                    if minutos_destino is not None:
                        st.caption(f"🚗 **{minutos_destino} min** en coche a {destino_gps}")
                    if fotos_urls:
                        try:
                            st.image(fotos_urls[0], caption="Foto del anuncio", width="stretch")
                        except Exception:
                            pass
                    hab = inv.get("habitaciones")
                    ban = inv.get("banos")
                    p_m2 = _precio_m2_inmueble(inv)
                    consumo_exacto_inv = float(inv.get("consumo_exacto_kwh_m2", 0) or 0)
                    emisiones_exactas_inv = float(inv.get("emisiones_exactas_kg_m2", 0) or 0)
                    if consumo_exacto_inv > 0:
                        cert_consumo = f"{consumo_exacto_inv:.0f} kWh/m²·año ({_letra_desde_consumo_kwh_m2(consumo_exacto_inv)})"
                    else:
                        cert_consumo = inv.get("certificado_consumo") or inv.get("certificado_energetico") or "—"
                    if emisiones_exactas_inv > 0:
                        cert_emisiones = f"{emisiones_exactas_inv:.1f} kg CO₂/m²·año ({_letra_desde_emisiones_kg_m2(emisiones_exactas_inv)})"
                    else:
                        cert_emisiones = inv.get("certificado_emisiones") or inv.get("certificado_energetico") or "—"
                    p_m2_str = f" · **{p_m2:.0f} €/m²**" if p_m2 is not None else ""
                    extras = []
                    if inv.get("piscina"):
                        extras.append("Piscina")
                    if inv.get("sotano"):
                        extras.append("Sótano")
                    if inv.get("placas_solares"):
                        extras.append("Placas solares")
                    extras_str = " · " + ", ".join(extras) if extras else ""
                    zona_cte = (inv.get("zona_climatica_cte") or "").strip()
                    zona_cte_str = f" · Zona climática CTE: **{zona_cte}**" if zona_cte else ""
                    st.caption(f"ID: {inv.get('id')} · m² útiles: {inv.get('m2_utiles')} · Año: {inv.get('ano_construccion')} · {hab or 0} hab. · {ban or 0} baños · Cert. consumo: {cert_consumo} · emisiones: {cert_emisiones}{p_m2_str}{zona_cte_str}{extras_str}")
                    if zona_cte:
                        reduccion = _reduccion_subvencion_por_zona_cte(zona_cte)
                        if reduccion:
                            st.caption(f"📋 **Leyenda subvención:** {reduccion}")
                    leyenda_placas = _leyenda_placas_subvencion(inv)
                    if leyenda_placas:
                        st.caption(leyenda_placas)
                    if zona_cte:
                        # Cálculo placas solares para alcanzar reducción mínima (solo zona C, D, E)
                        reduccion_decimal = _reduccion_decimal_por_zona_cte(zona_cte)
                        if reduccion_decimal is not None:
                            with st.expander("☀️ Cálculo placas solares para subvención", expanded=False):
                                st.caption("Estima el número de placas y la superficie necesaria para alcanzar la reducción energética mínima, y un presupuesto orientativo de instalación.")
                                consumo_ref = _consumo_anual_desde_certificado(inv)
                                valor_consumo = float(consumo_ref) if consumo_ref is not None else 5000.0
                                c1, c2 = st.columns(2)
                                with c1:
                                    consumo_anual = st.number_input("Consumo eléctrico anual (kWh)", min_value=0.0, value=valor_consumo, step=500.0, key=f"placas_consumo_{inv_id}", help="Por defecto: estimado desde certificado energético (consumo) y m² del inmueble.")
                                    if consumo_ref is not None:
                                        cert_consumo = inv.get("certificado_consumo") or inv.get("certificado_energetico") or ""
                                        m2 = float(inv.get("m2_utiles", 0) or 0) or float(inv.get("m2_construidos", 0) or 0)
                                        st.caption(f"↳ Estimado: cert. consumo **{cert_consumo}** × {m2:.0f} m² ≈ **{consumo_ref:.0f}** kWh/año")
                                    produccion_placa = st.number_input("Producción por placa (kWh/año)", min_value=1.0, value=510.0, step=10.0, key=f"placas_prod_{inv_id}")
                                with c2:
                                    area_placa = st.number_input("Superficie por placa (m²)", min_value=0.5, value=AREA_PLACA_TIPICA_M2, step=0.1, format="%.1f", key=f"placas_area_{inv_id}")
                                num_placas, superficie_m2 = calcular_placas_solares(consumo_anual, reduccion_decimal, produccion_placa, area_placa)
                                st.metric("Placas necesarias", num_placas)
                                st.metric("Superficie necesaria", f"{superficie_m2:.1f} m²")
                                st.markdown("---")
                                st.caption("**Presupuesto orientativo**")
                                cost_placa = st.number_input("Coste por placa (€)", min_value=0.0, value=250.0, step=25.0, key=f"placas_costo_placa_{inv_id}")
                                cost_inst_m2 = st.number_input("Coste instalación (€/m²)", min_value=0.0, value=75.0, step=5.0, key=f"placas_costo_inst_{inv_id}")
                                presupuesto = calcular_presupuesto_instalacion(num_placas, cost_placa, area_placa, cost_inst_m2)
                                st.metric("Presupuesto total instalación", f"{presupuesto:.0f} €")
                    if inv.get("notas"):
                        st.caption(f"📝 **Notas:** {inv.get('notas')}")
                    d = _desglose_gastos_compra(inv)
                    st.caption(f"Coste total compra: **{d['total']:.0f} €** (precio + comisión + ITP {ITP_PCT}% + notaría + registro + gestoría {GESTORIA_EUR:.0f} €)")
                    if inv.get("url_anuncio") or inv.get("url_inmobiliaria"):
                        enlaces = []
                        if inv.get("url_anuncio"):
                            enlaces.append(f"[Ver anuncio Idealista]({inv['url_anuncio']})")
                        if inv.get("url_inmobiliaria"):
                            enlaces.append(f"[Ver web inmobiliaria]({inv['url_inmobiliaria']})")
                        st.markdown(" · ".join(enlaces))
                    # Mapa: comprobar geocodificación y permitir recolocar el pin y guardar coordenadas
                    if folium is not None and st_folium is not None and inv_id is not None:
                        st.markdown("**Mapa** (haz clic en el mapa para recolocar el pin)")
                        coords_orig = _coords_inmueble(inv)
                        coords = coords_orig if coords_orig is not None else (37.18, -3.6)
                        if coords_orig is None:
                            st.caption("Sin coordenadas aún. Indica localización en la ficha o haz clic en el mapa y pulsa Guardar.")
                        lat, lon = coords
                        m = folium.Map(location=[lat, lon], zoom_start=14, tiles="OpenStreetMap")
                        folium.Marker(
                            location=[lat, lon],
                            popup=inv.get("localizacion") or "Inmueble",
                            tooltip="Haz clic en el mapa para mover el pin",
                        ).add_to(m)
                        out = st_folium(m, key=f"map_inv_{inv_id}", height=300, width=None)
                        if out and out.get("last_object_clicked") is None and out.get("last_clicked") is not None:
                            click = out["last_clicked"]
                            if isinstance(click, dict) and "lat" in click and "lng" in click:
                                st.session_state[f"pin_{inv_id}"] = (float(click["lat"]), float(click["lng"]))
                                st.rerun()
                        col_save, _ = st.columns([0.2, 0.8])
                        with col_save:
                            if st.button("💾 Guardar coordenadas", key=f"btn_guardar_coords_{inv_id}"):
                                pos = st.session_state.get(f"pin_{inv_id}")
                                if pos is None:
                                    pos = coords_orig
                                if pos is None:
                                    st.warning("Haz clic en el mapa para fijar la posición antes de guardar.")
                                elif isinstance(pos, (tuple, list)) and len(pos) >= 2:
                                    inv_act = {**inv, "lat": float(pos[0]), "lon": float(pos[1])}
                                    if ghd.actualizar_inmueble(usuario_id, inv_act):
                                        if f"pin_{inv_id}" in st.session_state:
                                            del st.session_state[f"pin_{inv_id}"]
                                        loc_key = (inv.get("localizacion") or "").strip()
                                        if loc_key and "gps_coords_cache" in st.session_state and loc_key in st.session_state.gps_coords_cache:
                                            del st.session_state.gps_coords_cache[loc_key]
                                        st.session_state.gps_duracion_cache = {k: v for k, v in st.session_state.get("gps_duracion_cache", {}).items() if k[0] != inv_id}
                                        st.success("Coordenadas guardadas.")
                                        st.rerun()
                                    else:
                                        st.error("Error al guardar.")
                    # Obtener fotos desde URL(s): Idealista y/o web inmobiliaria
                    if inv.get("url_anuncio") or inv.get("url_inmobiliaria"):
                        if inv.get("url_anuncio") and "idealista" in (inv.get("url_anuncio") or "").lower():
                            st.caption("Idealista suele bloquear peticiones directas (403). Configura **APIFY_TOKEN** o **ZENROWS_API_KEY** en secrets. La **URL inmobiliaria** suele permitir extraer las imágenes con más facilidad.")
                        if st.button("🖼 Obtener / Recargar imágenes", key=f"btn_obt_fotos_{inv_id}", help="Extrae imágenes del anuncio Idealista y/o de la URL de la inmobiliaria. Selecciona luego las que quieras añadir a la ficha."):
                            try:
                                todas_urls = []
                                # Primero URL inmobiliaria (suele responder más rápido que Idealista)
                                if inv.get("url_inmobiliaria"):
                                    with st.spinner("Extrayendo imágenes de la web inmobiliaria…"):
                                        u2 = extraer_urls_imagenes_anuncio(inv["url_inmobiliaria"])
                                        todas_urls.extend(u2)
                                if inv.get("url_anuncio"):
                                    with st.spinner("Extrayendo imágenes del anuncio Idealista…"):
                                        u1 = extraer_urls_imagenes_anuncio(inv["url_anuncio"])
                                        todas_urls.extend(u1)
                                urls = list(dict.fromkeys(todas_urls))
                                if urls:
                                    st.session_state.fotos_extraidas = {"inmueble_id": inv_id, "urls": urls}
                                else:
                                    st.warning("No se encontraron imágenes en ninguna de las URLs indicadas.")
                            except ValueError as e:
                                st.error(str(e))
                            st.rerun()
                    fotos_extraidas = st.session_state.get("fotos_extraidas")
                    if fotos_extraidas and fotos_extraidas.get("inmueble_id") == inv_id and fotos_extraidas.get("urls"):
                        urls_list = fotos_extraidas["urls"]
                        st.markdown("**Selecciona las fotos a añadir a la ficha:**")
                        # Grid de imágenes con checkbox cada una (máx 20 para no saturar)
                        urls_show = urls_list[:20]
                        cols = 4
                        seleccionados = []
                        for i, url in enumerate(urls_show):
                            col_ix = i % cols
                            if col_ix == 0:
                                row = st.columns(cols)
                            with row[col_ix]:
                                try:
                                    st.image(url, width="stretch")
                                except Exception:
                                    st.caption(f"Imagen {i+1}")
                                if st.checkbox("Añadir", key=f"foto_sel_{inv_id}_{i}"):
                                    seleccionados.append((i, url))
                        if st.button("Añadir seleccionadas a la ficha", key=f"btn_add_fotos_{inv_id}"):
                            if not seleccionados:
                                st.warning("Marca al menos una foto para añadir.")
                            else:
                                existentes = len(ghd.get_fotos_inmueble_urls(usuario_id, inv_id))
                                subidas = 0
                                for idx, (_, url) in enumerate(seleccionados):
                                    b = _descargar_imagen_bytes(url)
                                    if b:
                                        ghd.subir_foto_inmueble(usuario_id, inv_id, b, existentes + idx + 1)
                                        subidas += 1
                                st.session_state.fotos_extraidas = None
                                st.success(f"Se han añadido {subidas} foto(s) a la ficha.")
                                st.rerun()
                        if st.button("Cancelar", key=f"btn_cancel_fotos_{inv_id}"):
                            st.session_state.fotos_extraidas = None
                            st.rerun()
                    _editor_inmueble(usuario_id, inv)
    else:
        st.info("No hay inmuebles. Usa el formulario de arriba para dar de alta una vivienda.")


def _tab_comparador_inmuebles(usuario_id: int):
    """Pestaña Comparador de inmuebles: seleccionar varios y ver características en tabla."""
    st.subheader("Comparador de inmuebles")
    st.caption("Selecciona dos o más inmuebles para comparar sus características.")
    inmuebles = ghd.get_inmuebles(usuario_id)
    if not inmuebles:
        st.info("No hay inmuebles. Ve a **Agenda inmuebles** para dar de alta viviendas.")
        return
    opts = [_titulo_inmueble(inv, _duracion_minutos_a_destino(inv, st.session_state.get("gps_destino", "Motril, Granada") or "Motril, Granada")) for inv in inmuebles]
    seleccionados = st.multiselect(
        "Inmuebles a comparar",
        opts,
        default=opts[:2] if len(opts) >= 2 else opts,
        format_func=lambda x: x,
    )
    if len(seleccionados) < 2:
        st.warning("Selecciona al menos dos inmuebles para comparar.")
        return
    indices = [opts.index(s) for s in seleccionados if s in opts]
    elegidos = [inmuebles[i] for i in indices]
    # Atributos a comparar (etiqueta -> valor por inmueble)
    def _valor(inv: dict, clave: str, fmt=str):
        v = inv.get(clave)
        if v is None or v == "":
            return "—"
        return fmt(v) if fmt != str else str(v)

    filas = [
        ("Localización", lambda inv: _valor(inv, "localizacion")),
        ("Precio (€)", lambda inv: _valor(inv, "importe", lambda x: f"{float(x):.0f}")),
        ("m² construidos", lambda inv: _valor(inv, "m2_construidos", lambda x: f"{float(x):.0f}")),
        ("m² útiles", lambda inv: _valor(inv, "m2_utiles", lambda x: f"{float(x):.0f}")),
        ("€/m²", lambda inv: f"{_precio_m2_inmueble(inv):.0f}" if _precio_m2_inmueble(inv) is not None else "—"),
        ("Habitaciones", lambda inv: _valor(inv, "habitaciones")),
        ("Baños", lambda inv: _valor(inv, "banos")),
        ("Año construcción", lambda inv: _valor(inv, "ano_construccion")),
        ("Cert. consumo", lambda inv: f"{float(inv.get('consumo_exacto_kwh_m2') or 0):.0f} ({_letra_desde_consumo_kwh_m2(float(inv.get('consumo_exacto_kwh_m2') or 0))})" if float(inv.get("consumo_exacto_kwh_m2") or 0) > 0 else (inv.get("certificado_consumo") or inv.get("certificado_energetico") or "—")),
        ("Cert. emisiones", lambda inv: f"{float(inv.get('emisiones_exactas_kg_m2') or 0):.1f} ({_letra_desde_emisiones_kg_m2(float(inv.get('emisiones_exactas_kg_m2') or 0))})" if float(inv.get("emisiones_exactas_kg_m2") or 0) > 0 else (inv.get("certificado_emisiones") or inv.get("certificado_energetico") or "—")),
        ("Piscina", lambda inv: "Sí" if inv.get("piscina") else "No"),
        ("Sótano", lambda inv: "Sí" if inv.get("sotano") else "No"),
        ("Placas solares", lambda inv: "Sí" if inv.get("placas_solares") else "No"),
        ("Coste total compra (€)", lambda inv: f"{_coste_total_inmueble(inv):.0f}"),
        ("Zona climática CTE", lambda inv: (inv.get("zona_climatica_cte") or "").strip() or "—"),
        ("⚡ Superficie placas (m²)", lambda inv: f"{float(inv.get('superficie_placas_m2') or 0):.0f}" if float(inv.get("superficie_placas_m2") or 0) > 0 else "—"),
        ("Reducción energética mín. subvención", lambda inv: _reduccion_subvencion_por_zona_cte(inv.get("zona_climatica_cte") or "") or "—"),
        ("Categoría", lambda inv: _categoria_inmueble(inv)),
        ("Notas", lambda inv: (inv.get("notas") or "").strip() or "—"),
    ]
    # Tabla: columnas = inmuebles (título corto), filas = atributos
    destino_gps = st.session_state.get("gps_destino", "Motril, Granada") or "Motril, Granada"
    columnas_titulos = []
    for inv in elegidos:
        d_min = _duracion_minutos_a_destino(inv, destino_gps)
        t = _titulo_inmueble(inv, d_min)
        if len(t) > 50:
            t = t[:47] + "..."
        columnas_titulos.append(t)
    data = {}
    for i, inv in enumerate(elegidos):
        col_name = columnas_titulos[i] if i < len(columnas_titulos) else f"Inmueble {i+1}"
        data[col_name] = [fn(inv) for _, fn in filas]
    df = pd.DataFrame(data, index=[nombre for nombre, _ in filas])
    st.dataframe(df, use_container_width=True, height=min(500, 50 + len(filas) * 35))
    st.caption("Coste total compra incluye precio + comisión (si inmobiliaria) + ITP 7% + notaría + registro + gestoría.")


def _tab_amortizar_o_invertir(usuario_id: int):
    """Pestaña ¿Amortizar o Invertir?: compara ahorro por amortización (con comisiones) vs beneficio neto de inversión (con retención)."""
    hipotecas = ghd.get_hipotecas(usuario_id)
    if not hipotecas:
        st.info("No hay hipotecas dadas de alta. Ve a **Alta de hipotecas** para añadir al menos una.")
        return
    st.subheader("¿Amortizar o Invertir?")
    st.caption("Compara el ahorro neto por amortizar (intereses evitados menos comisiones) con el beneficio neto de invertir (después de retención por rentas del ahorro).")
    opts_hipo = [f"{h.get('nombre_entidad', '')} — {h.get('nombre_hipoteca', '')}" for h in hipotecas]
    sel_hipo = st.selectbox("Selecciona la hipoteca", opts_hipo, key="amort_inv_hipo")
    idx_hipo = opts_hipo.index(sel_hipo) if sel_hipo in opts_hipo else 0
    h = hipotecas[idx_hipo]
    importe_amort = st.number_input(
        "Importe amortización anual (€)",
        min_value=0.0,
        value=3000.0,
        step=500.0,
        key="amort_inv_importe",
        help="Cantidad que destinarías cada año a amortizar.",
    )
    st.markdown("---")
    st.markdown("**Inversión alternativa** (depósito o fondo)")
    dinero_invertido = st.number_input("Dinero invertido (€)", min_value=0.0, value=3000.0, step=500.0, key="amort_inv_capital")
    modo_rendimiento = st.radio(
        "Indicar rendimiento como",
        ["% de rendimiento", "Importe obtenido (total al vencimiento)"],
        horizontal=True,
        key="amort_inv_modo",
    )
    if modo_rendimiento == "% de rendimiento":
        pct_rendimiento = st.number_input("% rendimiento", min_value=0.0, max_value=100.0, value=3.0, step=0.25, format="%.2f", key="amort_inv_pct")
        rendimiento_bruto = dinero_invertido * (pct_rendimiento / 100.0) if dinero_invertido else 0.0
    else:
        importe_obtenido = st.number_input("Importe obtenido (€)", min_value=0.0, value=3090.0, step=50.0, key="amort_inv_obtenido")
        rendimiento_bruto = max(0.0, float(importe_obtenido) - dinero_invertido) if dinero_invertido else 0.0

    # Cálculo amortización
    intereses_ahorrados, comisiones_totales, ahorro_neto_amort = _ahorro_amortizar(h, importe_amort)
    # Cálculo inversión
    retencion = _retencion_ahorro(rendimiento_bruto)
    beneficio_neto_inv = round(rendimiento_bruto - retencion, 2)

    col_amort, col_inv = st.columns(2)
    with col_amort:
        st.markdown("### 📉 Amortizar")
        st.metric("Intereses ahorrados (vida préstamo)", f"{intereses_ahorrados:.0f} €")
        st.metric("Comisiones por amortización", f"{comisiones_totales:.0f} €")
        st.metric("**Ahorro neto**", f"**{ahorro_neto_amort:.0f} €**")
    with col_inv:
        st.markdown("### 📈 Invertir")
        st.metric("Rendimiento bruto", f"{rendimiento_bruto:.0f} €")
        st.metric("Retención (rentas ahorro)", f"{retencion:.0f} €")
        st.metric("**Beneficio neto**", f"**{beneficio_neto_inv:.0f} €**")

    st.markdown("---")
    if ahorro_neto_amort > beneficio_neto_inv:
        st.success(f"**En estos datos, sale a cuenta amortizar:** ahorro neto {ahorro_neto_amort:.0f} € frente a beneficio neto por invertir {beneficio_neto_inv:.0f} €.")
    elif beneficio_neto_inv > ahorro_neto_amort:
        st.success(f"**En estos datos, sale a cuenta invertir:** beneficio neto {beneficio_neto_inv:.0f} € frente a ahorro por amortizar {ahorro_neto_amort:.0f} €.")
    else:
        st.info("Ambas opciones dan un resultado equivalente con los datos introducidos.")
    st.markdown("**Comparativa visual**")
    df_comp = pd.DataFrame(
        {"Neto (€)": [ahorro_neto_amort, beneficio_neto_inv]},
        index=["Amortizar", "Invertir"],
    )
    st.bar_chart(df_comp, height=280)
    st.caption("Amortizar: ahorro total en vida del préstamo (intereses evitados − comisiones). Invertir: beneficio neto con los datos introducidos (después de retención).")
    if st.button("Recalcular", key="amort_inv_recalcular", help="Vuelve a calcular con los valores actuales (útil si has cambiado cantidades)."):
        st.rerun()


def comparador(usuario_id: int):
    """Pestaña comparador: selección de hipotecas, indicación ventajosa, amortización y tabla."""
    inv_sel = st.session_state.get("inmueble_seleccionado")
    if inv_sel and isinstance(inv_sel, dict):
        coste = _coste_total_inmueble(inv_sel)
        st.info(f"**Vivienda seleccionada** (sidebar): {inv_sel.get('localizacion', '')} — Coste total compra (con ITP, notaría, registro, gestoría): **{coste:.0f} €**")
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

    modo_amort = st.selectbox(
        "Aplicar amortización extraordinaria para…",
        [
            "Reducir cuota (mantener plazo)",
            "Reducir plazo (mantener cuota)",
            "Mixto (repartir años entre cuota y plazo)",
        ],
        key="modo_amortizacion_comp",
    )
    modo_tipo = (
        "reducir_cuota" if modo_amort.startswith("Reducir cuota")
        else ("reducir_plazo" if modo_amort.startswith("Reducir plazo") else "mixto")
    )

    plan_params = None
    if modo_tipo == "mixto":
        max_anos = max(int(h.get("duracion_anos", 0) or 0) for h in elegidas) if elegidas else 0
        st.markdown("#### Modo mixto")
        orden = st.radio(
            "¿Qué priorizas primero?",
            [
                "Primero reducir plazo y luego reducir cuota",
                "Primero reducir cuota y luego reducir plazo",
            ],
            key="mixto_orden",
        )
        anos_fase1 = st.slider(
            "Años dedicados a la primera fase",
            min_value=0,
            max_value=max_anos if max_anos > 0 else 1,
            value=min(5, max_anos) if max_anos > 0 else 0,
            step=1,
            key="mixto_anos_fase1",
        )
        plan_params = {"orden": orden, "anos_fase1": int(anos_fase1), "max_anos": int(max_anos)}

    st.markdown("#### Precios externos (para comparar seguros fuera del banco)")
    st.caption(
        "Seguro hogar: se usa como **obligatorio** en hipotecas sin vinculación y **tras los años de bonificación** "
        "en hipotecas que lo tienen vinculado."
    )
    col_ext1, col_ext2, col_ext3 = st.columns(3)
    with col_ext1:
        precio_ext_seguro_hogar = st.number_input(
            "Seguro hogar externo / obligatorio (€/año)",
            min_value=0.0,
            value=0.0,
            step=20.0,
            key="precio_ext_seguro_hogar",
        )
    with col_ext2:
        precio_ext_seguro_vida = st.number_input(
            "Seguro vida externo (€/año)",
            min_value=0.0,
            value=0.0,
            step=20.0,
            key="precio_ext_seguro_vida",
        )
    with col_ext3:
        precio_ext_alarma = st.number_input(
            "Alarma externa (€/año)",
            min_value=0.0,
            value=0.0,
            step=20.0,
            key="precio_ext_alarma",
        )

    precios_externos = {
        "seguro_hogar": precio_ext_seguro_hogar,
        "seguro_vida": precio_ext_seguro_vida,
        "alarma": precio_ext_alarma,
    }

    st.markdown("### Criterio de comparación")
    criterio = st.selectbox(
        "¿Qué significa “más ventajosa”?",
        [
            "Coste total (intereses + vinculados + tasación + comisión apertura + comisiones por amortización extra)",
            "TAE (menor es mejor)",
            "Cuota mensual inicial (menor es mejor)",
            "Coste primer año (intereses reales año 1 + vinculados + tasación)",
        ],
        key="criterio_comp",
    )

    resumenes = {}
    for h in elegidas:
        anos_h = int(h.get("duracion_anos", 0) or 0)
        if modo_tipo == "reducir_cuota":
            plan_h = ["reducir_cuota"] * anos_h
        elif modo_tipo == "reducir_plazo":
            plan_h = ["reducir_plazo"] * anos_h
        else:
            k = min(int(plan_params["anos_fase1"]), anos_h) if plan_params else 0
            if plan_params and plan_params["orden"].startswith("Primero reducir plazo"):
                plan_h = (["reducir_plazo"] * k) + (["reducir_cuota"] * max(0, anos_h - k))
            else:
                plan_h = (["reducir_cuota"] * k) + (["reducir_plazo"] * max(0, anos_h - k))
        resumenes[h.get("id")] = _resumen_costes_hipoteca(
            h,
            amort_anual,
            plan_h,
            precios_externos=precios_externos,
            usar_externos=True,
        )

    def clave_orden(h: dict):
        rid = h.get("id")
        r = resumenes.get(rid, {})
        if criterio.startswith("TAE"):
            return r.get("tae", 9999)
        if criterio.startswith("Cuota"):
            return r.get("cuota_inicial", 9e18)
        if criterio.startswith("Coste primer año"):
            return coste_total_primero_ano(h)
        return r.get("coste_total", 9e18)

    elegidas_orden = sorted(elegidas, key=clave_orden)
    mejor = elegidas_orden[0] if elegidas_orden else None

    st.markdown("### Ranking")
    ranking_rows = []
    for h in elegidas_orden:
        r = resumenes.get(h.get("id"), {})
        ranking_rows.append({
            "Entidad": h.get("nombre_entidad", ""),
            "Hipoteca": h.get("nombre_hipoteca", ""),
            "TAE (%)": float(h.get("tae", 0) or 0),
            "TIN base (%)": float(r.get("tin_base", h.get("tin", 0) or 0)),
            "Bonif. TIN (p.p.)": float(r.get("bonif_pp", 0) or 0),
            "TIN efectivo (%)": float(r.get("tin_efectivo", h.get("tin", 0) or 0)),
            "Cuota inicial (€)": round(r.get("cuota_inicial", 0), 2),
            "Intereses totales (€)": round(r.get("intereses_totales", 0), 2),
            "Vinculados/año usados (€)": round(r.get("coste_anual_vinculados", 0), 2),
            "Vinculados totales (€)": round(r.get("vinculados_totales", 0), 2),
            "Com. apertura (€)": round(r.get("comision_apertura", 0), 2),
            "Bonif. firma (€)": round(r.get("bonificacion_firma", 0), 2),
            "Comisiones extra (€)": round(r.get("comisiones_por_extra", 0), 2),
            "Duración": _duracion_str(int(r.get("meses_hasta_fin", 0))),
            "Coste total (€)": round(r.get("coste_total", 0), 2),
        })
    df_ranking = pd.DataFrame(ranking_rows)
    st.dataframe(df_ranking, width="stretch", hide_index=True)

    st.markdown("#### Exportar ranking")
    ranking_csv = df_ranking.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Descargar ranking (CSV)",
        data=ranking_csv,
        file_name="ranking_hipotecas.csv",
        mime="text/csv",
        width="stretch",
    )
    try:
        bio_rank = BytesIO()
        with pd.ExcelWriter(bio_rank, engine="openpyxl") as writer:
            df_ranking.to_excel(writer, index=False, sheet_name="Ranking")
        st.download_button(
            "Descargar ranking (Excel)",
            data=bio_rank.getvalue(),
            file_name="ranking_hipotecas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
    except Exception:
        st.caption("No se pudo generar Excel del ranking (falta `openpyxl` o no está disponible en el entorno).")

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
            st.metric("Cuota aprox. (€)", f"{am.cuota_mensual_frances(h.get('cantidad_solicitada',0), h.get('tin',0), h.get('duracion_anos',25)*12):.0f}")
            st.caption(f"Coste vinculados/año: {coste_anual_vinculados(h):.0f} €")
            r = resumenes.get(h.get("id"), {})
            st.caption(f"Coste total (según criterio): {r.get('coste_total', 0):.0f} €")

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
    cuota_base = am.cuota_mensual_frances(float(c or 0), float(tin or 0), int(anos or 0) * 12) if c and anos else 0.0
    rid = hipo_tabla.get("id")
    plan_tin_tabla = get_plan_tin_anual(hipo_tabla, int(anos or 0))
    cuadro = (
        resumenes.get(rid, {}).get("cuadro")
        if rid in resumenes
        else am.cuadro_amortizacion_anual(
            c, plan_tin_tabla[0] if plan_tin_tabla else tin, anos, amort_anual,
            plan_anual=(["reducir_cuota"] * int(anos or 0)),
            plan_tin_anual=plan_tin_tabla,
        )
    )

    # Resumen del efecto de la amortización según el modo (antes de la tabla)
    if amort_anual and amort_anual > 0:
        if modo_tipo == "reducir_cuota":
            cuota_y2 = float(cuadro[1].get("cuota_mensual", 0) or 0) if len(cuadro) >= 2 else None
            cuotas = [float(r.get("cuota_mensual", 0) or 0) for r in cuadro if r.get("cuota_mensual") is not None]
            cuota_min = min(cuotas) if cuotas else None
            cuota_ultimo = float(cuadro[-1].get("cuota_mensual", 0) or 0) if cuadro else None
            if cuota_y2 is not None and cuota_base:
                extra_txt = []
                if cuota_ultimo is not None:
                    extra_txt.append(
                        f"Cuota último año: {cuota_ultimo:.2f} € (↓ {(cuota_base - cuota_ultimo):.2f} €)"
                    )
                if cuota_min is not None:
                    extra_txt.append(
                        f"Cuota mínima: {cuota_min:.2f} € (↓ {(cuota_base - cuota_min):.2f} €)"
                    )
                st.info(
                    f"Con {amort_anual:.0f} €/año, la cuota bajaría aprox. de {cuota_base:.2f} € "
                    f"a {cuota_y2:.2f} € (a partir del año 2)."
                    + (("\n\n" + " · ".join(extra_txt)) if extra_txt else "")
                )
            else:
                st.info(f"Con {amort_anual:.0f} €/año, la cuota bajaría con el tiempo (ver columna de cuota por año).")
        elif modo_tipo == "reducir_plazo":
            meses_sin_extra = int(anos) * 12
            meses_con_extra = int(sum(r.get('meses_pagados', 0) for r in cuadro))
            ahorro = max(0, meses_sin_extra - meses_con_extra)
            st.info(
                f"Con {amort_anual:.0f} €/año manteniendo cuota ({cuota_base:.2f} €), la duración bajaría de "
                f"{_duracion_str(meses_sin_extra)} a {_duracion_str(meses_con_extra)} "
                f"(ahorro {_duracion_str(ahorro)})."
            )
        else:
            meses_sin_extra = int(anos) * 12
            meses_con_extra = int(sum(r.get('meses_pagados', 0) for r in cuadro))
            ahorro = max(0, meses_sin_extra - meses_con_extra)
            cuotas = [float(r.get("cuota_mensual", 0) or 0) for r in cuadro if r.get("cuota_mensual") is not None]
            cuota_min = min(cuotas) if cuotas else None
            cuota_ultimo = float(cuadro[-1].get("cuota_mensual", 0) or 0) if cuadro else None
            detalle = []
            if plan_params:
                detalle.append(f"Reparto: {plan_params['anos_fase1']} años en fase 1")
            if cuota_min is not None and cuota_base:
                detalle.append(f"Cuota mínima: {cuota_min:.2f} € (↓ {(cuota_base - cuota_min):.2f} €)")
            if cuota_ultimo is not None and cuota_base:
                detalle.append(f"Cuota último año: {cuota_ultimo:.2f} € (↓ {(cuota_base - cuota_ultimo):.2f} €)")
            st.info(
                f"Modo mixto: duración de {_duracion_str(meses_sin_extra)} a {_duracion_str(meses_con_extra)} "
                f"(ahorro {_duracion_str(ahorro)})."
                + (("\n\n" + " · ".join(detalle)) if detalle else "")
            )
    df = pd.DataFrame(cuadro)
    df = df.rename(columns={
        "año": "Año",
        "cuota_mensual": "Cuota mensual (€)",
        "meses_pagados": "Meses pagados",
        "intereses_año": "Intereses año (€)",
        "amortizado_año": "Amortizado año (€)",
        "extra_año": "Amortización extra (€)",
        "deuda_restante": "Deuda restante (€)",
    })
    st.dataframe(df, width="stretch", hide_index=True)

    st.markdown("### Exportar")
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Descargar CSV",
        data=csv_bytes,
        file_name="amortizacion.csv",
        mime="text/csv",
    )
    try:
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Amortización")
        st.download_button(
            "Descargar Excel",
            data=bio.getvalue(),
            file_name="amortizacion.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception:
        st.caption("No se pudo generar Excel (falta `openpyxl` o no está disponible en el entorno).")


def main():
    # Portada: logo + título
    logo_img = _cargar_imagen(LOGO_APP_PATH)
    if logo_img is not None:
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            st.image(logo_img, width="stretch")
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
        st.session_state.inmueble_seleccionado = None
        st.rerun()

    if "gps_destino" not in st.session_state:
        st.session_state.gps_destino = "Motril, Granada"
    st.sidebar.markdown("**GPS**")
    gps_destino = st.sidebar.text_input(
        "Ciudad de destino (ruta por carretera)",
        value=st.session_state.get("gps_destino", "Motril, Granada"),
        key="gps_destino",
        help="Se usa para calcular la duración en coche desde cada inmueble y como criterio de ordenación en la agenda.",
    )

    # Selector de inmueble: Interesados (verde) primero, separador, En Estudio (azul)
    inmuebles = ghd.get_inmuebles(u["id"])
    interesados = [inv for inv in inmuebles if _categoria_inmueble(inv) == CATEGORIA_INTERESADOS]
    en_estudio = [inv for inv in inmuebles if _categoria_inmueble(inv) == CATEGORIA_EN_ESTUDIO]
    SEPARADOR_EN_ESTUDIO = "———— En Estudio ————"
    opts_inv = ["— Ninguno —"]
    lista_inv_ordenada = [None]
    for inv in interesados:
        d_min = _duracion_minutos_a_destino(inv, gps_destino)
        opts_inv.append("🟢 " + _titulo_inmueble(inv, d_min))
        lista_inv_ordenada.append(inv)
    opts_inv.append(SEPARADOR_EN_ESTUDIO)
    lista_inv_ordenada.append(None)
    for inv in en_estudio:
        d_min = _duracion_minutos_a_destino(inv, gps_destino)
        opts_inv.append("🔵 " + _titulo_inmueble(inv, d_min))
        lista_inv_ordenada.append(inv)
    sel_inv = st.sidebar.selectbox(
        "Inmueble para simular hipoteca",
        opts_inv,
        key="sel_inmueble",
    )
    idx_sel = opts_inv.index(sel_inv) if sel_inv in opts_inv else 0
    st.session_state.inmueble_seleccionado = lista_inv_ordenada[idx_sel] if idx_sel < len(lista_inv_ordenada) else None
    if st.session_state.inmueble_seleccionado:
        inv = st.session_state.inmueble_seleccionado
        d = _desglose_gastos_compra(inv)
        coste = d["total"]
        st.sidebar.caption(f"Coste total compra: **{coste:.0f} €**")
        with st.sidebar.expander("Desglose gastos compra"):
            st.caption(f"Precio: {d['precio']:.0f} €")
            if d["comision"] > 0:
                st.caption(f"Comisión: {d['comision']:.0f} €")
            st.caption(f"ITP ({ITP_PCT}%): {d['itp']:.0f} €")
            st.caption(f"Notaría ({NOTARIA_PCT_DEL_ITP}% ITP): {d['notaria']:.0f} €")
            st.caption(f"Registro ({REGISTRO_PCT_DEL_ITP}% ITP): {d['registro']:.0f} €")
            st.caption(f"Gestoría: {d['gestoria']:.0f} €")
            st.caption("---")
            st.caption(f"**Total gastos compra: {d['total']:.0f} €**")

    st.sidebar.markdown("---")
    st.sidebar.caption(f"**Hipochorro** v{VERSION_APP}")

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Alta de hipotecas", "Comparador", "Agenda inmuebles", "Comparador inmuebles", "¿Amortizar o Invertir?", "Info"])
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
                    st.caption(f"ID: {h.get('id')}")
                    _editor_hipoteca(u['id'], h)

    with tab2:
        comparador(u["id"])

    with tab3:
        agenda_inmuebles(u["id"])

    with tab4:
        _tab_comparador_inmuebles(u["id"])

    with tab5:
        _tab_amortizar_o_invertir(u["id"])

    with tab6:
        st.markdown("""
        **Hipochorro** guarda usuarios e hipotecas en el repositorio GitHub **jarconett/hipochorro**.
        - En **Streamlit Cloud** configura el secret `GITHUB_TOKEN` con un token de acceso al repo (con permisos de escritura).
        - Los logos se intentan descargar por dominio (ej. `bbva.com`) y se almacenan en `data/logos/`.
        - El comparador ordena por TAE, coste primer año y productos vinculados para señalar la opción más ventajosa.
        - El cuadro de amortización usa el **sistema francés** (cuota constante) y permite amortización extraordinaria anual.
        """)
        st.markdown("---")
        st.subheader("Changelog")
        st.markdown(f"**Versión actual: {VERSION_APP}**")
        st.markdown("""
        - **1.11.0** — Inmuebles: superficie disponible para placas solares (m²) en alta y ficha; leyenda con nº de placas, reducción teórica y apta/no apta para subvención; indicador ⚡ en títulos (sidebar y listado). Certificado energético: valores exactos de consumo (kWh/m²·año) y emisiones (kg CO₂/m²·año) con asignación automática de letra; si no se indica valor exacto se usa el valor medio del rango. Zonas climáticas CTE en módulo y datos (import opcional). Scraper Idealista: extracción de todas las imágenes (listas de objetos y estructuras anidadas en ZenRows/Apify). Botón «Recargar imágenes desde Idealista» en cada ficha.
        - **1.10.0** — Rediseño UI: tema profesional en `.streamlit/config.toml` (colores claro/oscuro, Plus Jakarta Sans), CSS global (espaciado, expanders tipo card, focus visible, tabular-nums en métricas).
        - **1.9.0** — Nueva pestaña «¿Amortizar o Invertir?»: selección de hipoteca, importe de amortización anual, comisiones bonificadas o estándar; comparativa con depósito/fondo (dinero invertido y % rendimiento o importe obtenido); retención por rentas del ahorro (tramos España 19–26 %); comparativa visual amortizar vs invertir.
        - **1.8.0** — Sección GPS en sidebar: ciudad de destino (por defecto Motril, Granada) para rutas por carretera; duración en minutos como criterio de ordenación en la agenda; botón «Calcular rutas a destino». Visor de mapa en cada ficha de inmueble (Folium): pin para comprobar geocodificación, clic en el mapa para recolocar el pin, botón «Guardar coordenadas» para persistir lat/lon en la ficha.
        - **1.7.0** — Agenda de inmuebles: categorías Interesados / En Estudio (estilo verde/azul); filtros por categoría, piscina y sótano; ordenar por recientes (fecha creación), precio, categoría, piscina, sótano, habitaciones, m² o €/m²; miniatura de la foto en la línea del desplegable; fecha de creación al dar de alta.
        - **1.6.0** — Resaltado en verde de todos los campos de bonificación (bonif., bonificado, bonificación) en alta y edición de hipotecas.
        - **1.5.0** — Resaltado en rojo de campos de comisiones y costes (comisión amortización, mantenimiento, tasación, seguros, alarma, protección pagos, pensión, comisión de apertura). Comisión de apertura e importe bonificado en la firma en formularios.
        - **1.4.0** — Gastos de compra completos: ITP 7%, notaría y registro (10% del ITP cada uno), gestoría 300 €. Desglose en sidebar con total de gastos. Inmuebles: certificado energético, habitaciones, baños, notas; título con precio/m².
        - **1.3.0** — Agenda de inmuebles: pestaña dedicada, formulario (importe, localización, año, m², piscina, sótano, particular/inmobiliaria, comisión venta). Obtención de fotos desde URL de anuncio (Idealista vía ZenRows/Apify o scraping). Selector de inmueble en sidebar para simular hipoteca.
        - **1.2.0** — Selector “Aplicar amortización extraordinaria para…” movido debajo del campo de amortización extraordinaria anual. Modo mixto de amortización en comparador.
        - **1.1.0** — En comparador: seguro de hogar con años de bonificación usa coste banco durante bonificación y coste externo después; hipotecas sin vinculación de seguro hogar consideran siempre el coste externo obligatorio.
        - **1.0.0** — Versión base: usuarios e hipotecas en GitHub, logos por dominio, comparador por TAE y coste primer año, cuadro de amortización sistema francés con amortización extraordinaria.
        """)

    # Ocultar bloque de login duplicado (script en iframe)
    _ocultar_login_duplicado_en_scroll()


def _ocultar_login_duplicado_en_scroll():
    """Inyecta un script que oculta en el documento principal cualquier bloque con 'Usuario existente' que esté después de las pestañas (duplicado al hacer scroll)."""
    html = """
    <script>
    (function() {
      var doc = window.parent.document;
      var tabs = doc.querySelector('[data-testid="stTabs"]');
      if (!tabs) return;
      var blocks = doc.querySelectorAll('[data-testid="stVerticalBlock"]');
      for (var i = 0; i < blocks.length; i++) {
        var el = blocks[i];
        if (el.textContent.indexOf('Usuario existente') !== -1 && (tabs.compareDocumentPosition(el) & 4) === 4)
          el.style.setProperty('display', 'none', 'important');
      }
    })();
    </script>
    """
    components.html(html, height=0)


if __name__ == "__main__":
    main()
