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

import re
import streamlit as st
import pandas as pd
import requests
from io import BytesIO
from urllib.parse import urljoin, urlparse

from lib import github_data as ghd
from lib import amortizacion as am

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

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

# Gastos de compra (sobre precio de la vivienda / ITP)
ITP_PCT = 7.0           # Impuesto de Transmisiones Patrimoniales: % sobre precio vivienda
NOTARIA_PCT_DEL_ITP = 10.0   # Notaría: % del importe del ITP
REGISTRO_PCT_DEL_ITP = 10.0  # Registro: % del importe del ITP
GESTORIA_EUR = 300.0    # Gestoría: importe fijo (€)

# Opciones certificado energético (consumo y emisiones)
CERT_ENERGETICO_OPCIONES = ["—", "A", "B", "C", "D", "E", "F", "G", "En trámite", "No disponible"]


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
    page_title="Hipo-Cachorro - Comparador de Hipotecas",
    page_icon=_favicon_img if _favicon_img is not None else "🏠",
    layout="wide",
    initial_sidebar_state="expanded",
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


def _extraer_urls_desde_json(html: str, url_base: str) -> list:
    """Busca en el HTML JSON embebido (Idealista, etc.) y extrae URLs de imágenes."""
    urls = []
    # Patrones típicos: "url":"https://...", "src":"https://...", multimedia, gallery, images
    patron = re.compile(r'["\'](?:url|src|image|href)["\']\s*:\s*["\'](https?://[^"\']+\.(?:jpg|jpeg|png|webp)(?:\?[^"\']*)?)["\']', re.I)
    for m in patron.finditer(html):
        u = m.group(1)
        if any(x in u.lower() for x in ("logo", "icon", "pixel", "avatar", "banner", "cookie", "tracking")):
            continue
        urls.append(u)
    # Idealista: a veces usa "multimedia": [{"url": "..."}] o "images": ["..."]
    patron2 = re.compile(r'https?://(?:img\d*\.)?idealista\.(?:com|pt|it)[^"\')\s]+\.(?:jpg|jpeg|png|webp)(?:\?[^"\')\s]*)?', re.I)
    for m in patron2.finditer(html):
        urls.append(m.group(0))
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
        r = requests.get(endpoint, params={"apikey": api_key, "url": url_anuncio}, headers=_REQUEST_HEADERS, timeout=25)
        if r.status_code != 200:
            return []
        data = r.json()
        images = data.get("property_images") or data.get("images") or []
        if isinstance(images, list):
            return [u for u in images if isinstance(u, str) and u.startswith("http") and (".jpg" in u or ".jpeg" in u or ".png" in u or ".webp" in u)]
        return []
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
            for key in ("images", "property_images", "propertyImages", "photos", "imageUrls"):
                val = item.get(key)
                if isinstance(val, list):
                    for u in val:
                        if isinstance(u, str) and u.startswith("http") and (".jpg" in u or ".jpeg" in u or ".png" in u or ".webp" in u):
                            urls.append(u)
                elif isinstance(val, str) and val.startswith("http"):
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
    # Opción 3: Scraping directo del HTML
    try:
        from bs4 import BeautifulSoup
        r = requests.get(url_anuncio, headers=_REQUEST_HEADERS, timeout=20)
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


def _titulo_inmueble(inv: dict) -> str:
    """Título para listado y selector: localización — precio € — precio/m² (si hay m²)."""
    loc = inv.get("localizacion", "") or "Sin ubicación"
    imp = float(inv.get("importe", 0) or 0)
    p = _precio_m2_inmueble(inv)
    if p is not None:
        return f"{loc} — {imp:,.0f} € — {p:,.0f} €/m²"
    return f"{loc} — {imp:,.0f} €"


def formulario_hipoteca(usuario_id: int):
    """Formulario de alta de hipoteca con todos los campos."""
    st.subheader("Alta de hipoteca bancaria")
    inv_sel = st.session_state.get("inmueble_seleccionado")
    def_valor = 150000.0
    def_cantidad = 150000.0
    if inv_sel and isinstance(inv_sel, dict):
        def_valor = _coste_total_inmueble(inv_sel)
        st.caption(f"💡 Valor del inmueble seleccionado en el sidebar: {inv_sel.get('localizacion', '')} — coste total {def_valor:,.0f} €")
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
        meses_tin_bonificado = st.number_input(
            "Meses con TIN bonificado al inicio",
            min_value=0,
            max_value=480,
            value=0,
            step=1,
        )
        anos_bonif_amort_parcial = st.number_input(
            "Años con comisión de amortización parcial bonificada",
            min_value=0,
            max_value=40,
            value=0,
            step=1,
        )
        comision_amort_parcial_bonif = st.number_input(
            "Comisión amortización parcial bonificada (%)",
            min_value=0.0,
            value=0.0,
            step=0.1,
            format="%.2f",
        )
        comision_amort_parcial = st.number_input(
            "Comisión amortización parcial estándar (%)",
            min_value=0.0,
            value=0.0,
            step=0.1,
            format="%.2f",
        )
        mantenimiento = st.number_input("Mantenimiento cuenta (€/año)", min_value=0.0, value=0.0, step=10.0)
        mantenimiento_tarjeta = st.number_input("Mantenimiento tarjeta (€/año)", min_value=0.0, value=0.0, step=10.0)
        tasacion = st.number_input("Tasación (€)", min_value=0.0, value=0.0, step=50.0)
        bonificacion_firma = st.number_input("Importe bonificado en la firma (€)", min_value=0.0, value=0.0, step=100.0, help="El banco lo abona una sola vez en la firma; reduce el coste total.")
        bonif_nomina_eur = st.number_input("Bonificación nómina (descuento €/año)", min_value=0.0, value=0.0, step=50.0)
        bonif_tin_nomina_pp = st.number_input("Bonif. TIN por nómina (p.p.)", min_value=0.0, value=0.0, step=0.05, format="%.2f")
        anos_bonif_nomina = st.number_input("Años bonif. nómina (0 = todo el préstamo)", min_value=0, max_value=40, value=0, step=1)
        seguro_hogar = st.number_input("Seguro hogar (€/año)", min_value=0.0, value=0.0, step=20.0)
        bonif_tin_seguro_hogar_pp = st.number_input("Bonif. TIN por seguro hogar (p.p.)", min_value=0.0, value=0.0, step=0.05, format="%.2f")
        anos_bonif_seguro_hogar = st.number_input("Años bonif. seguro hogar (0 = todo)", min_value=0, max_value=40, value=0, step=1)
        seguro_vida = st.number_input("Seguro vida (€/año)", min_value=0.0, value=0.0, step=20.0)
        bonif_tin_seguro_vida_pp = st.number_input("Bonif. TIN por seguro vida (p.p.)", min_value=0.0, value=0.0, step=0.05, format="%.2f")
        anos_bonif_seguro_vida = st.number_input("Años bonif. seguro vida (0 = todo)", min_value=0, max_value=40, value=0, step=1)
        alarma = st.number_input("Alarma (€/año)", min_value=0.0, value=0.0, step=20.0)
        bonif_tin_alarma_pp = st.number_input("Bonif. TIN por alarma (p.p.)", min_value=0.0, value=0.0, step=0.05, format="%.2f")
        anos_bonif_alarma = st.number_input("Años bonif. alarma (0 = todo)", min_value=0, max_value=40, value=0, step=1)
        proteccion_pagos = st.number_input("Protección de pagos (€/año)", min_value=0.0, value=0.0, step=20.0)
        bonif_tin_proteccion_pagos_pp = st.number_input("Bonif. TIN por protección pagos (p.p.)", min_value=0.0, value=0.0, step=0.05, format="%.2f")
        anos_bonif_proteccion_pagos = st.number_input("Años bonif. protección pagos (0 = todo)", min_value=0, max_value=40, value=0, step=1)
        pension = st.number_input("Pensión (€/año)", min_value=0.0, value=0.0, step=20.0)
        bonif_tin_pension_pp = st.number_input("Bonif. TIN por pensión (p.p.)", min_value=0.0, value=0.0, step=0.05, format="%.2f")
        anos_bonif_pension = st.number_input("Años bonif. pensión (0 = todo)", min_value=0, max_value=40, value=0, step=1)
        bizum = st.checkbox("Bizum vinculado")
        bonif_tin_bizum_pp = st.number_input("Bonif. TIN por Bizum (p.p.)", min_value=0.0, value=0.0, step=0.05, format="%.2f")
        anos_bonif_bizum = st.number_input("Años bonif. Bizum (0 = todo)", min_value=0, max_value=40, value=0, step=1)
        tarjeta_credito = st.checkbox("Tarjeta de crédito vinculada")
        bonif_tin_tarjeta_pp = st.number_input("Bonif. TIN por tarjeta (p.p.)", min_value=0.0, value=0.0, step=0.05, format="%.2f")
        anos_bonif_tarjeta = st.number_input("Años bonif. tarjeta (0 = todo)", min_value=0, max_value=40, value=0, step=1)

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
        meses_tin_bonificado = st.number_input(
            "Meses con TIN bonificado al inicio",
            min_value=0,
            max_value=480,
            value=int(h.get("meses_tin_bonificado", 0) or 0),
            step=1,
            key=f"e_mes_tin_bonif_{hid}",
        )
        anos_bonif_amort_parcial = st.number_input(
            "Años con comisión de amortización parcial bonificada",
            min_value=0,
            max_value=40,
            value=int(h.get("anos_bonif_amort_parcial", 0) or 0),
            step=1,
            key=f"e_anos_bonif_amort_{hid}",
        )
        comision_amort_parcial_bonif = st.number_input(
            "Comisión amortización parcial bonificada (%)",
            min_value=0.0,
            value=float(h.get("comision_amort_parcial_bonif", 0) or 0),
            step=0.1,
            format="%.2f",
            key=f"e_com_bonif_{hid}",
        )
        comision_amort_parcial = st.number_input(
            "Comisión amortización parcial estándar (%)",
            min_value=0.0,
            value=float(h.get("comision_amort_parcial", 0) or 0),
            step=0.1,
            format="%.2f",
            key=f"e_com_{hid}",
        )
        mantenimiento = st.number_input("Mantenimiento cuenta (€/año)", min_value=0.0, value=float(h.get("mantenimiento", 0) or 0), step=10.0, key=f"e_man_{hid}")
        mantenimiento_tarjeta = st.number_input("Mantenimiento tarjeta (€/año)", min_value=0.0, value=float(h.get("mantenimiento_tarjeta", 0) or 0), step=10.0, key=f"e_man_tar_{hid}")
        tasacion = st.number_input("Tasación (€)", min_value=0.0, value=float(h.get("tasacion", 0) or 0), step=50.0, key=f"e_tas_{hid}")
        bonificacion_firma = st.number_input("Importe bonificado en la firma (€)", min_value=0.0, value=float(h.get("bonificacion_firma", 0) or 0), step=100.0, key=f"e_bonif_firma_{hid}", help="El banco lo abona una sola vez en la firma; reduce el coste total.")
        bonif_nomina_eur = st.number_input("Bonificación nómina (descuento €/año)", min_value=0.0, value=float(h.get("bonif_nomina_eur", h.get("bonif_nomina", 0) or 0)), step=50.0, key=f"e_bon_{hid}")
        bonif_tin_nomina_pp = st.number_input("Bonif. TIN por nómina (p.p.)", min_value=0.0, value=float(h.get("bonif_tin_nomina_pp", 0) or 0), step=0.05, format="%.2f", key=f"e_bon_tin_nom_{hid}")
        anos_bonif_nomina = st.number_input("Años bonif. nómina (0 = todo)", min_value=0, max_value=40, value=int(h.get("años_bonif_nomina", 0) or 0), step=1, key=f"e_ab_nom_{hid}")
        seguro_hogar = st.number_input("Seguro hogar (€/año)", min_value=0.0, value=float(h.get("seguro_hogar", 0) or 0), step=20.0, key=f"e_sh_{hid}")
        bonif_tin_seguro_hogar_pp = st.number_input("Bonif. TIN por seguro hogar (p.p.)", min_value=0.0, value=float(h.get("bonif_tin_seguro_hogar_pp", 0) or 0), step=0.05, format="%.2f", key=f"e_shb_{hid}")
        anos_bonif_seguro_hogar = st.number_input("Años bonif. seguro hogar (0 = todo)", min_value=0, max_value=40, value=int(h.get("años_bonif_seguro_hogar", 0) or 0), step=1, key=f"e_ab_sh_{hid}")
        seguro_vida = st.number_input("Seguro vida (€/año)", min_value=0.0, value=float(h.get("seguro_vida", 0) or 0), step=20.0, key=f"e_sv_{hid}")
        bonif_tin_seguro_vida_pp = st.number_input("Bonif. TIN por seguro vida (p.p.)", min_value=0.0, value=float(h.get("bonif_tin_seguro_vida_pp", 0) or 0), step=0.05, format="%.2f", key=f"e_svb_{hid}")
        anos_bonif_seguro_vida = st.number_input("Años bonif. seguro vida (0 = todo)", min_value=0, max_value=40, value=int(h.get("años_bonif_seguro_vida", 0) or 0), step=1, key=f"e_ab_sv_{hid}")
        alarma = st.number_input("Alarma (€/año)", min_value=0.0, value=float(h.get("alarma", 0) or 0), step=20.0, key=f"e_ala_{hid}")
        bonif_tin_alarma_pp = st.number_input("Bonif. TIN por alarma (p.p.)", min_value=0.0, value=float(h.get("bonif_tin_alarma_pp", 0) or 0), step=0.05, format="%.2f", key=f"e_alab_{hid}")
        anos_bonif_alarma = st.number_input("Años bonif. alarma (0 = todo)", min_value=0, max_value=40, value=int(h.get("años_bonif_alarma", 0) or 0), step=1, key=f"e_ab_ala_{hid}")
        proteccion_pagos = st.number_input("Protección de pagos (€/año)", min_value=0.0, value=float(h.get("proteccion_pagos", 0) or 0), step=20.0, key=f"e_pp_{hid}")
        bonif_tin_proteccion_pagos_pp = st.number_input("Bonif. TIN por protección pagos (p.p.)", min_value=0.0, value=float(h.get("bonif_tin_proteccion_pagos_pp", 0) or 0), step=0.05, format="%.2f", key=f"e_ppb_{hid}")
        anos_bonif_proteccion_pagos = st.number_input("Años bonif. protección pagos (0 = todo)", min_value=0, max_value=40, value=int(h.get("años_bonif_proteccion_pagos", 0) or 0), step=1, key=f"e_ab_pp_{hid}")
        pension = st.number_input("Pensión (€/año)", min_value=0.0, value=float(h.get("pension", 0) or 0), step=20.0, key=f"e_pen_{hid}")
        bonif_tin_pension_pp = st.number_input("Bonif. TIN por pensión (p.p.)", min_value=0.0, value=float(h.get("bonif_tin_pension_pp", 0) or 0), step=0.05, format="%.2f", key=f"e_penb_{hid}")
        anos_bonif_pension = st.number_input("Años bonif. pensión (0 = todo)", min_value=0, max_value=40, value=int(h.get("años_bonif_pension", 0) or 0), step=1, key=f"e_ab_pen_{hid}")
        bizum = st.checkbox("Bizum vinculado", value=bool(h.get("bizum", False)), key=f"e_biz_{hid}")
        bonif_tin_bizum_pp = st.number_input("Bonif. TIN por Bizum (p.p.)", min_value=0.0, value=float(h.get("bonif_tin_bizum_pp", 0) or 0), step=0.05, format="%.2f", key=f"e_bizb_{hid}")
        anos_bonif_bizum = st.number_input("Años bonif. Bizum (0 = todo)", min_value=0, max_value=40, value=int(h.get("años_bonif_bizum", 0) or 0), step=1, key=f"e_ab_biz_{hid}")
        tarjeta_credito = st.checkbox("Tarjeta de crédito vinculada", value=bool(h.get("tarjeta_credito", False)), key=f"e_tar_{hid}")
        bonif_tin_tarjeta_pp = st.number_input("Bonif. TIN por tarjeta (p.p.)", min_value=0.0, value=float(h.get("bonif_tin_tarjeta_pp", 0) or 0), step=0.05, format="%.2f", key=f"e_tarb_{hid}")
        anos_bonif_tarjeta = st.number_input("Años bonif. tarjeta (0 = todo)", min_value=0, max_value=40, value=int(h.get("años_bonif_tarjeta", 0) or 0), step=1, key=f"e_ab_tar_{hid}")

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

    if st.button("Duplicar ahora", key=f"dup_btn_{hid}", use_container_width=True):
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
    return intereses + coste_anual_vinculados(h) + float(h.get("tasacion", 0) or 0) - bonif_firma


def _duracion_str(meses: int) -> str:
    meses = int(max(0, meses))
    a = meses // 12
    m = meses % 12
    if m == 0:
        return f"{a} años"
    return f"{a} años {m} meses"


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
    coste_total = intereses_totales + vinculados_totales + float(h.get("tasacion", 0) or 0) + comisiones_por_extra - bonificacion_firma

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
        habitaciones = st.number_input("Habitaciones", min_value=0, max_value=20, value=int(inv.get("habitaciones", 0) or 0), step=1, key=f"ei_hab_{inv_id}")
        banos = st.number_input("Baños", min_value=0, max_value=10, value=int(inv.get("banos", 0) or 0), step=1, key=f"ei_ban_{inv_id}")
        cert_legacy = inv.get("certificado_energetico") or "—"
        cert_consumo_val = inv.get("certificado_consumo") or cert_legacy or "—"
        cert_emisiones_val = inv.get("certificado_emisiones") or cert_legacy or "—"
        idx_consumo = CERT_ENERGETICO_OPCIONES.index(cert_consumo_val) if cert_consumo_val in CERT_ENERGETICO_OPCIONES else 0
        idx_emisiones = CERT_ENERGETICO_OPCIONES.index(cert_emisiones_val) if cert_emisiones_val in CERT_ENERGETICO_OPCIONES else 0
        col_cert1, col_cert2 = st.columns(2)
        with col_cert1:
            certificado_consumo = st.selectbox("Cert. energético (consumo)", CERT_ENERGETICO_OPCIONES, index=idx_consumo, key=f"ei_cert_cons_{inv_id}")
        with col_cert2:
            certificado_emisiones = st.selectbox("Cert. energético (emisiones)", CERT_ENERGETICO_OPCIONES, index=idx_emisiones, key=f"ei_cert_emis_{inv_id}")
        notas = st.text_area("Notas", value=inv.get("notas", "") or "", height=80, key=f"ei_notas_{inv_id}")
        col1, col2, col3 = st.columns(3)
        with col1:
            piscina = st.checkbox("Piscina", value=bool(inv.get("piscina", False)), key=f"ei_pis_{inv_id}")
        with col2:
            sotano = st.checkbox("Sótano", value=bool(inv.get("sotano", False)), key=f"ei_sot_{inv_id}")
        with col3:
            inmobiliaria = st.checkbox("Venta por inmobiliaria", value=bool(inv.get("inmobiliaria", False)), key=f"ei_inm_{inv_id}")
        comision_venta_pct = st.number_input("% comisión venta (inmobiliaria)", min_value=0.0, max_value=20.0, value=float(inv.get("comision_venta_pct", 0) or 0), step=0.5, key=f"ei_com_{inv_id}")
        url_anuncio = st.text_input("URL del anuncio", value=inv.get("url_anuncio", "") or "", key=f"ei_url_{inv_id}")
        if st.form_submit_button("Guardar cambios"):
            inv_act = {**inv, "importe": importe, "localizacion": localizacion, "ano_construccion": int(ano_construccion), "m2_construidos": m2_construidos, "m2_utiles": m2_utiles, "habitaciones": int(habitaciones), "banos": int(banos), "certificado_consumo": certificado_consumo if certificado_consumo != "—" else "", "certificado_emisiones": certificado_emisiones if certificado_emisiones != "—" else "", "notas": (notas or "").strip(), "piscina": piscina, "sotano": sotano, "inmobiliaria": inmobiliaria, "comision_venta_pct": comision_venta_pct, "url_anuncio": url_anuncio.strip()}
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
    st.caption("Alta de viviendas a comparar. En cada ficha puedes usar «Obtener fotos desde anuncio» (URL del anuncio) y elegir qué imágenes añadir.")
    with st.form("form_inmueble"):
        importe = st.number_input("Importe de la vivienda (€) *", min_value=0.0, value=150000.0, step=5000.0)
        localizacion = st.text_input("Localización", placeholder="Ej: Madrid, zona Norte")
        ano_construccion = st.number_input("Año de construcción", min_value=1800, max_value=2030, value=2000, step=1)
        m2_construidos = st.number_input("m² construidos", min_value=0.0, value=90.0, step=1.0)
        m2_utiles = st.number_input("m² útiles", min_value=0.0, value=75.0, step=1.0)
        habitaciones = st.number_input("Habitaciones", min_value=0, max_value=20, value=3, step=1)
        banos = st.number_input("Baños", min_value=0, max_value=10, value=2, step=1)
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            certificado_consumo = st.selectbox("Cert. energético (consumo)", CERT_ENERGETICO_OPCIONES)
        with col_c2:
            certificado_emisiones = st.selectbox("Cert. energético (emisiones)", CERT_ENERGETICO_OPCIONES)
        notas = st.text_area("Notas", placeholder="Observaciones sobre la vivienda…", height=80)
        piscina = st.checkbox("Piscina", value=False)
        sotano = st.checkbox("Sótano", value=False)
        tipo_venta = st.radio("Tipo de venta", ["Particular", "Inmobiliaria"], horizontal=True)
        inmobiliaria = tipo_venta == "Inmobiliaria"
        comision_venta_pct = st.number_input("% comisión por la venta (solo inmobiliaria)", min_value=0.0, max_value=20.0, value=3.0, step=0.5)
        url_anuncio = st.text_input("URL del anuncio (portal inmobiliario)", placeholder="https://...")
        if st.form_submit_button("Dar de alta inmueble"):
            inv = {
                "importe": float(importe),
                "localizacion": (localizacion or "").strip(),
                "ano_construccion": int(ano_construccion),
                "m2_construidos": float(m2_construidos),
                "m2_utiles": float(m2_utiles),
                "habitaciones": int(habitaciones),
                "banos": int(banos),
                "certificado_consumo": certificado_consumo if certificado_consumo != "—" else "",
                "certificado_emisiones": certificado_emisiones if certificado_emisiones != "—" else "",
                "notas": (notas or "").strip(),
                "piscina": bool(piscina),
                "sotano": bool(sotano),
                "inmobiliaria": bool(inmobiliaria),
                "comision_venta_pct": float(comision_venta_pct) if inmobiliaria else 0.0,
                "url_anuncio": (url_anuncio or "").strip(),
            }
            nuevo = ghd.añadir_inmueble(usuario_id, inv)
            if nuevo:
                st.success("Inmueble dado de alta. Abre su ficha y usa «Obtener fotos desde anuncio» para elegir las imágenes.")
                st.rerun()
            else:
                st.error("Error al guardar. ¿GITHUB_TOKEN configurado?")

    inmuebles = ghd.get_inmuebles(usuario_id)
    if inmuebles:
        st.markdown("---")
        st.subheader("Inmuebles dados de alta")
        for inv in inmuebles:
            titulo = _titulo_inmueble(inv)
            with st.expander(titulo):
                fotos_urls = ghd.get_fotos_inmueble_urls(usuario_id, inv.get("id"))
                if fotos_urls:
                    try:
                        st.image(fotos_urls[0], caption="Foto del anuncio", use_container_width=True)
                    except Exception:
                        pass
                hab = inv.get("habitaciones")
                ban = inv.get("banos")
                p_m2 = _precio_m2_inmueble(inv)
                cert_consumo = inv.get("certificado_consumo") or inv.get("certificado_energetico") or "—"
                cert_emisiones = inv.get("certificado_emisiones") or inv.get("certificado_energetico") or "—"
                p_m2_str = f" · **{p_m2:,.0f} €/m²**" if p_m2 is not None else ""
                st.caption(f"ID: {inv.get('id')} · m² útiles: {inv.get('m2_utiles')} · Año: {inv.get('ano_construccion')} · {hab or 0} hab. · {ban or 0} baños · Cert. consumo: {cert_consumo} · emisiones: {cert_emisiones}{p_m2_str}")
                if inv.get("notas"):
                    st.caption(f"📝 Notas: {inv.get('notas')}")
                d = _desglose_gastos_compra(inv)
                st.caption(f"Coste total compra: **{d['total']:,.0f} €** (precio + comisión + ITP {ITP_PCT}% + notaría + registro + gestoría {GESTORIA_EUR:.0f} €)")
                if inv.get("url_anuncio"):
                    st.markdown(f"[Ver anuncio]({inv['url_anuncio']})")
                # Obtener fotos desde URL y que el usuario elija cuáles añadir
                inv_id = inv.get("id")
                if inv.get("url_anuncio"):
                    if "idealista" in (inv.get("url_anuncio") or "").lower():
                        st.caption("Idealista suele bloquear peticiones directas (403). Configura **APIFY_TOKEN** o **ZENROWS_API_KEY** en secrets (ver `docs/IDEALISTA_SCRAPING.md`).")
                    if st.button("🖼 Obtener fotos desde anuncio", key=f"btn_obt_fotos_{inv_id}"):
                        try:
                            with st.spinner("Extrayendo imágenes del anuncio…"):
                                urls = extraer_urls_imagenes_anuncio(inv["url_anuncio"])
                            if urls:
                                st.session_state.fotos_extraidas = {"inmueble_id": inv_id, "urls": urls}
                            else:
                                st.warning("No se encontraron imágenes en el anuncio o el portal no permite extraerlas.")
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
                                st.image(url, use_column_width=True)
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


def comparador(usuario_id: int):
    """Pestaña comparador: selección de hipotecas, indicación ventajosa, amortización y tabla."""
    inv_sel = st.session_state.get("inmueble_seleccionado")
    if inv_sel and isinstance(inv_sel, dict):
        coste = _coste_total_inmueble(inv_sel)
        st.info(f"**Vivienda seleccionada** (sidebar): {inv_sel.get('localizacion', '')} — Coste total compra (con ITP, notaría, registro, gestoría): **{coste:,.0f} €**")
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
            "Coste total (intereses + vinculados + tasación + comisiones por amortización extra)",
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
            "Bonif. firma (€)": round(r.get("bonificacion_firma", 0), 2),
            "Comisiones extra (€)": round(r.get("comisiones_por_extra", 0), 2),
            "Duración": _duracion_str(int(r.get("meses_hasta_fin", 0))),
            "Coste total (€)": round(r.get("coste_total", 0), 2),
        })
    df_ranking = pd.DataFrame(ranking_rows)
    st.dataframe(df_ranking, use_container_width=True, hide_index=True)

    st.markdown("#### Exportar ranking")
    ranking_csv = df_ranking.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Descargar ranking (CSV)",
        data=ranking_csv,
        file_name="ranking_hipotecas.csv",
        mime="text/csv",
        use_container_width=True,
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
            use_container_width=True,
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
            st.metric("Cuota aprox. (€)", f"{am.cuota_mensual_frances(h.get('cantidad_solicitada',0), h.get('tin',0), h.get('duracion_anos',25)*12):,.0f}")
            st.caption(f"Coste vinculados/año: {coste_anual_vinculados(h):,.0f} €")
            r = resumenes.get(h.get("id"), {})
            st.caption(f"Coste total (según criterio): {r.get('coste_total', 0):,.0f} €")

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
                        f"Cuota último año: {cuota_ultimo:,.2f} € (↓ {(cuota_base - cuota_ultimo):,.2f} €)"
                    )
                if cuota_min is not None:
                    extra_txt.append(
                        f"Cuota mínima: {cuota_min:,.2f} € (↓ {(cuota_base - cuota_min):,.2f} €)"
                    )
                st.info(
                    f"Con {amort_anual:,.0f} €/año, la cuota bajaría aprox. de {cuota_base:,.2f} € "
                    f"a {cuota_y2:,.2f} € (a partir del año 2)."
                    + (("\n\n" + " · ".join(extra_txt)) if extra_txt else "")
                )
            else:
                st.info(f"Con {amort_anual:,.0f} €/año, la cuota bajaría con el tiempo (ver columna de cuota por año).")
        elif modo_tipo == "reducir_plazo":
            meses_sin_extra = int(anos) * 12
            meses_con_extra = int(sum(r.get('meses_pagados', 0) for r in cuadro))
            ahorro = max(0, meses_sin_extra - meses_con_extra)
            st.info(
                f"Con {amort_anual:,.0f} €/año manteniendo cuota ({cuota_base:,.2f} €), la duración bajaría de "
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
                detalle.append(f"Cuota mínima: {cuota_min:,.2f} € (↓ {(cuota_base - cuota_min):,.2f} €)")
            if cuota_ultimo is not None and cuota_base:
                detalle.append(f"Cuota último año: {cuota_ultimo:,.2f} € (↓ {(cuota_base - cuota_ultimo):,.2f} €)")
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
    st.dataframe(df, use_container_width=True, hide_index=True)

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
            st.image(logo_img, use_container_width=True)
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

    # Selector de inmueble para simular hipoteca
    inmuebles = ghd.get_inmuebles(u["id"])
    opts_inv = ["— Ninguno —"] + [_titulo_inmueble(inv) for inv in inmuebles]
    sel_inv = st.sidebar.selectbox(
        "Inmueble para simular hipoteca",
        opts_inv,
        key="sel_inmueble",
    )
    if sel_inv == "— Ninguno —":
        st.session_state.inmueble_seleccionado = None
    else:
        idx_inv = opts_inv.index(sel_inv) - 1
        if 0 <= idx_inv < len(inmuebles):
            st.session_state.inmueble_seleccionado = inmuebles[idx_inv]
        else:
            st.session_state.inmueble_seleccionado = None
    if st.session_state.inmueble_seleccionado:
        inv = st.session_state.inmueble_seleccionado
        d = _desglose_gastos_compra(inv)
        coste = d["total"]
        st.sidebar.caption(f"Coste total compra: **{coste:,.0f} €**")
        with st.sidebar.expander("Desglose gastos compra"):
            st.caption(f"Precio: {d['precio']:,.0f} €")
            if d["comision"] > 0:
                st.caption(f"Comisión: {d['comision']:,.0f} €")
            st.caption(f"ITP ({ITP_PCT}%): {d['itp']:,.0f} €")
            st.caption(f"Notaría ({NOTARIA_PCT_DEL_ITP}% ITP): {d['notaria']:,.0f} €")
            st.caption(f"Registro ({REGISTRO_PCT_DEL_ITP}% ITP): {d['registro']:,.0f} €")
            st.caption(f"Gestoría: {d['gestoria']:,.0f} €")
            st.caption("---")
            st.caption(f"**Total gastos compra: {d['total']:,.0f} €**")

    tab1, tab2, tab3, tab4 = st.tabs(["Alta de hipotecas", "Comparador", "Agenda inmuebles", "Info"])
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
        st.markdown("""
        **Hipochorro** guarda usuarios e hipotecas en el repositorio GitHub **jarconett/hipochorro**.
        - En **Streamlit Cloud** configura el secret `GITHUB_TOKEN` con un token de acceso al repo (con permisos de escritura).
        - Los logos se intentan descargar por dominio (ej. `bbva.com`) y se almacenan en `data/logos/`.
        - El comparador ordena por TAE, coste primer año y productos vinculados para señalar la opción más ventajosa.
        - El cuadro de amortización usa el **sistema francés** (cuota constante) y permite amortización extraordinaria anual.
        """)


if __name__ == "__main__":
    main()
