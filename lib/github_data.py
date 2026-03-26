"""
Módulo para leer y escribir datos en el repositorio GitHub (usuarios, hipotecas, logos).
Usa GITHUB_TOKEN desde secrets de Streamlit Cloud.
"""
import os
import json
import base64
import re
from io import BytesIO
from typing import Optional

def _get_github():
    """Obtiene cliente PyGithub usando token de secrets."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return None
    try:
        from github import Github
        return Github(token)
    except Exception:
        return None

def _repo():
    """Repo por defecto: jarconett/hipochorro."""
    g = _get_github()
    if not g:
        return None
    try:
        return g.get_repo("jarconett/hipochorro")
    except Exception:
        return None

# Rutas en el repo
DATA_DIR = "data"
USUARIOS_FILE = f"{DATA_DIR}/usuarios.json"
HIPOTECAS_DIR = f"{DATA_DIR}/hipotecas"
INMUEBLES_DIR = f"{DATA_DIR}/inmuebles"
INMUEBLES_FOTOS_DIR = f"{DATA_DIR}/inmuebles_fotos"
INMUEBLES_SUNLIGHT_DIR = f"{DATA_DIR}/inmuebles_sunlight"
OFERTAS_COMPRA_DIR = f"{DATA_DIR}/ofertas_compra"
APORTACION_EFECTIVO_DIR = f"{DATA_DIR}/aportacion_efectivo"
LOGOS_DIR = f"{DATA_DIR}/logos"

def _slug(texto: str) -> str:
    """Genera slug seguro para nombres de archivo."""
    s = re.sub(r'[^\w\s-]', '', texto.lower())
    s = re.sub(r'[-\s]+', '_', s).strip('_')
    return s[:50] if s else "sin_nombre"

def get_usuarios() -> list:
    """Lee lista de usuarios desde GitHub."""
    repo = _repo()
    if not repo:
        return []
    try:
        c = repo.get_contents(USUARIOS_FILE)
        data = json.loads(base64.b64decode(c.content).decode())
        return data.get("usuarios", [])
    except Exception:
        return []

def guardar_usuarios(usuarios: list) -> bool:
    """Guarda lista de usuarios en GitHub."""
    repo = _repo()
    if not repo:
        return False
    try:
        contenido = json.dumps({"usuarios": usuarios}, indent=2, ensure_ascii=False)
        try:
            c = repo.get_contents(USUARIOS_FILE)
            repo.update_file(USUARIOS_FILE, "Actualizar usuarios", contenido, c.sha)
        except Exception:
            repo.create_file(USUARIOS_FILE, "Crear usuarios", contenido)
        return True
    except Exception:
        return False

def crear_usuario(nombre: str, email: str = "") -> Optional[dict]:
    """Añade un usuario y devuelve el objeto usuario o None."""
    usuarios = get_usuarios()
    uid = max([u.get("id", 0) for u in usuarios], default=0) + 1
    usuario = {"id": uid, "nombre": nombre.strip(), "email": email.strip()}
    usuarios.append(usuario)
    if guardar_usuarios(usuarios):
        return usuario
    return None

def get_hipotecas(usuario_id: int) -> list:
    """Lee hipotecas de un usuario desde GitHub."""
    repo = _repo()
    if not repo:
        return []
    path = f"{HIPOTECAS_DIR}/usuario_{usuario_id}.json"
    try:
        c = repo.get_contents(path)
        data = json.loads(base64.b64decode(c.content).decode())
        return data.get("hipotecas", [])
    except Exception:
        return []

def guardar_hipotecas(usuario_id: int, hipotecas: list) -> bool:
    """Guarda hipotecas de un usuario en GitHub."""
    repo = _repo()
    if not repo:
        return False
    path = f"{HIPOTECAS_DIR}/usuario_{usuario_id}.json"
    contenido = json.dumps({"hipotecas": hipotecas}, indent=2, ensure_ascii=False)
    try:
        c = repo.get_contents(path)
        repo.update_file(path, "Actualizar hipotecas", contenido, c.sha)
    except Exception:
        try:
            repo.create_file(path, "Crear hipotecas usuario", contenido)
        except Exception:
            return False
    return True

def añadir_hipoteca(usuario_id: int, hipoteca: dict) -> Optional[dict]:
    """Añade una hipoteca y devuelve el objeto con id."""
    hipotecas = get_hipotecas(usuario_id)
    hid = max([h.get("id", 0) for h in hipotecas], default=0) + 1
    hipoteca["id"] = hid
    hipotecas.append(hipoteca)
    if guardar_hipotecas(usuario_id, hipotecas):
        return hipoteca
    return None

def actualizar_hipoteca(usuario_id: int, hipoteca: dict) -> bool:
    """Actualiza una hipoteca existente por id."""
    hipotecas = get_hipotecas(usuario_id)
    for i, h in enumerate(hipotecas):
        if h.get("id") == hipoteca.get("id"):
            hipotecas[i] = hipoteca
            return guardar_hipotecas(usuario_id, hipotecas)
    return False

def get_logo_url(entidad_nombre: str, logo_path: Optional[str] = None) -> Optional[str]:
    """
    Devuelve URL raw de GitHub para un logo si existe logo_path.
    logo_path es la ruta relativa en el repo, ej: data/logos/bbva.png
    """
    if not logo_path:
        return None
    repo = _repo()
    if not repo:
        return None
    try:
        c = repo.get_contents(logo_path)
        return c.download_url
    except Exception:
        return None

def subir_logo_desde_url(entidad_nombre: str, image_url: str) -> Optional[str]:
    """
    Descarga imagen desde image_url y la sube al repo en data/logos/{slug}.png.
    Devuelve la ruta en repo (data/logos/xxx.png) o None.
    """
    import requests
    repo = _repo()
    if not repo:
        return None
    slug = _slug(entidad_nombre)
    path = f"{LOGOS_DIR}/{slug}.png"
    try:
        r = requests.get(image_url, timeout=10)
        r.raise_for_status()
        contenido = r.content
    except Exception:
        return None
    try:
        try:
            c = repo.get_contents(path)
            repo.update_file(path, f"Actualizar logo {entidad_nombre}", contenido, c.sha)
        except Exception:
            repo.create_file(path, f"Añadir logo {entidad_nombre}", contenido)
        return path
    except Exception:
        return None

def subir_logo_desde_bytes(entidad_nombre: str, image_bytes: bytes) -> Optional[str]:
    """Sube imagen desde bytes al repo. Devuelve path en repo o None."""
    repo = _repo()
    if not repo:
        return None
    slug = _slug(entidad_nombre)
    path = f"{LOGOS_DIR}/{slug}.png"
    try:
        try:
            c = repo.get_contents(path)
            repo.update_file(path, f"Actualizar logo {entidad_nombre}", image_bytes, c.sha)
        except Exception:
            repo.create_file(path, f"Añadir logo {entidad_nombre}", image_bytes)
        return path
    except Exception:
        return None

def get_logo_raw_url(logo_path: str, branch: str = "main") -> str:
    """Construye URL raw de GitHub para un path en el repo."""
    return f"https://raw.githubusercontent.com/jarconett/hipochorro/{branch}/{logo_path}"


# --- Inmuebles (agenda de viviendas) ---

def get_inmuebles(usuario_id: int) -> list:
    """Lee inmuebles de un usuario desde GitHub."""
    repo = _repo()
    if not repo:
        return []
    path = f"{INMUEBLES_DIR}/usuario_{usuario_id}.json"
    try:
        c = repo.get_contents(path)
        data = json.loads(base64.b64decode(c.content).decode())
        return data.get("inmuebles", [])
    except Exception:
        return []


def guardar_inmuebles(usuario_id: int, inmuebles: list) -> bool:
    """Guarda inmuebles de un usuario en GitHub."""
    repo = _repo()
    if not repo:
        return False
    path = f"{INMUEBLES_DIR}/usuario_{usuario_id}.json"
    contenido = json.dumps({"inmuebles": inmuebles}, indent=2, ensure_ascii=False)
    try:
        c = repo.get_contents(path)
        repo.update_file(path, "Actualizar inmuebles", contenido, c.sha)
    except Exception:
        try:
            repo.create_file(path, "Crear inmuebles usuario", contenido)
        except Exception:
            return False
    return True


def añadir_inmueble(usuario_id: int, inmueble: dict) -> Optional[dict]:
    """Añade un inmueble y devuelve el objeto con id."""
    inmuebles = get_inmuebles(usuario_id)
    iid = max([inv.get("id", 0) for inv in inmuebles], default=0) + 1
    inmueble["id"] = iid
    inmuebles.append(inmueble)
    if guardar_inmuebles(usuario_id, inmuebles):
        return inmueble
    return None


def actualizar_inmueble(usuario_id: int, inmueble: dict) -> bool:
    """Actualiza un inmueble existente por id."""
    inmuebles = get_inmuebles(usuario_id)
    for i, inv in enumerate(inmuebles):
        if inv.get("id") == inmueble.get("id"):
            inmuebles[i] = inmueble
            return guardar_inmuebles(usuario_id, inmuebles)
    return False


def _ruta_fotos_inmueble(usuario_id: int, inmueble_id: int) -> str:
    return f"{INMUEBLES_FOTOS_DIR}/u{usuario_id}_i{inmueble_id}"


def subir_foto_inmueble(usuario_id: int, inmueble_id: int, imagen_bytes: bytes, indice: int) -> Optional[str]:
    """Sube una foto de inmueble al repo. indice empieza en 1. Devuelve path en repo o None."""
    repo = _repo()
    if not repo:
        return None
    base = _ruta_fotos_inmueble(usuario_id, inmueble_id)
    path = f"{base}/foto_{indice}.jpg"
    try:
        try:
            c = repo.get_contents(path)
            repo.update_file(path, f"Actualizar foto inmueble {inmueble_id}", imagen_bytes, c.sha)
        except Exception:
            repo.create_file(path, f"Añadir foto inmueble {inmueble_id}", imagen_bytes)
        return path
    except Exception:
        return None


def get_fotos_inmueble_urls(usuario_id: int, inmueble_id: int, branch: str = "main") -> list:
    """Devuelve lista de URLs raw de las fotos del inmueble en GitHub."""
    repo = _repo()
    if not repo:
        return []
    base = _ruta_fotos_inmueble(usuario_id, inmueble_id)
    try:
        contents = repo.get_contents(base)
        urls = []
        for c in contents:
            if c.name.endswith((".jpg", ".jpeg", ".png")):
                urls.append(get_logo_raw_url(c.path, branch))
        return sorted(urls)
    except Exception:
        return []


def get_fotos_urls_map_usuario(usuario_id: int, branch: str = "main") -> dict:
    """
    Lista todas las carpetas u{usuario_id}_i{inmueble_id} bajo inmuebles_fotos y devuelve
    {inmueble_id: [urls raw ordenadas]}. Evita N llamadas independientes desde la app cuando
    se muestra la agenda completa (las URLs ya están en GitHub; la caché de Streamlit reduce
    llamadas repetidas a la API de GitHub entre reruns).
    """
    repo = _repo()
    if not repo:
        return {}
    try:
        root = repo.get_contents(INMUEBLES_FOTOS_DIR)
    except Exception:
        return {}
    prefix = f"u{usuario_id}_i"
    out = {}
    items = root if isinstance(root, list) else [root]
    for item in items:
        if getattr(item, "type", None) != "dir" or not item.name.startswith(prefix):
            continue
        try:
            iid = int(item.name.split("_i", 1)[1])
        except (ValueError, IndexError):
            continue
        try:
            inner = repo.get_contents(item.path)
            if not isinstance(inner, list):
                inner = [inner]
            urls = []
            for c in inner:
                if c.name.endswith((".jpg", ".jpeg", ".png")):
                    urls.append(get_logo_raw_url(c.path, branch))
            out[iid] = sorted(urls)
        except Exception:
            out[iid] = []
    return out


def _path_sunlight(usuario_id: int, inmueble_id: int) -> str:
    return f"{INMUEBLES_SUNLIGHT_DIR}/u{usuario_id}_i{inmueble_id}.json"


def guardar_sunlight_inmueble(usuario_id: int, inmueble_id: int, data: dict) -> bool:
    """Guarda el JSON de horas de sol del inmueble en un archivo aparte (evita payload grande en usuario_.json)."""
    repo = _repo()
    if not repo:
        return False
    path = _path_sunlight(usuario_id, inmueble_id)
    contenido = json.dumps(data, indent=2, ensure_ascii=False)
    try:
        c = repo.get_contents(path)
        repo.update_file(path, "Actualizar datos sol inmueble", contenido, c.sha)
    except Exception:
        try:
            repo.create_file(path, "Añadir datos sol inmueble", contenido)
        except Exception:
            return False
    return True


def get_sunlight_inmueble(usuario_id: int, inmueble_id: int) -> Optional[dict]:
    """Lee el JSON de horas de sol del inmueble desde el archivo en GitHub. None si no existe."""
    repo = _repo()
    if not repo:
        return None
    path = _path_sunlight(usuario_id, inmueble_id)
    try:
        c = repo.get_contents(path)
        return json.loads(base64.b64decode(c.content).decode())
    except Exception:
        return None


def eliminar_sunlight_inmueble(usuario_id: int, inmueble_id: int) -> bool:
    """Elimina el archivo de datos de sol del inmueble en GitHub."""
    repo = _repo()
    if not repo:
        return False
    path = _path_sunlight(usuario_id, inmueble_id)
    try:
        c = repo.get_contents(path)
        repo.delete_file(path, "Eliminar datos sol inmueble", c.sha)
        return True
    except Exception:
        return False


# --- Ofertas de compra (entrada + gastos, seguimiento) ---

def _path_ofertas_compra(usuario_id: int) -> str:
    return f"{OFERTAS_COMPRA_DIR}/usuario_{usuario_id}.json"


def get_ofertas_compra(usuario_id: int) -> list:
    """Lee ofertas de compra guardadas del usuario (simulaciones con precio/gastos y estado)."""
    repo = _repo()
    if not repo:
        return []
    path = _path_ofertas_compra(usuario_id)
    try:
        c = repo.get_contents(path)
        data = json.loads(base64.b64decode(c.content).decode())
        return data.get("ofertas", [])
    except Exception:
        return []


def guardar_ofertas_compra(usuario_id: int, ofertas: list) -> bool:
    """Persiste la lista completa de ofertas de compra."""
    repo = _repo()
    if not repo:
        return False
    path = _path_ofertas_compra(usuario_id)
    contenido = json.dumps({"ofertas": ofertas}, indent=2, ensure_ascii=False)
    try:
        c = repo.get_contents(path)
        repo.update_file(path, "Actualizar ofertas de compra", contenido, c.sha)
    except Exception:
        try:
            repo.create_file(path, "Crear ofertas de compra usuario", contenido)
        except Exception:
            return False
    return True


def añadir_oferta_compra(usuario_id: int, oferta: dict) -> Optional[dict]:
    """Añade una oferta con id autogenerado."""
    ofertas = get_ofertas_compra(usuario_id)
    oid = max([o.get("id", 0) for o in ofertas], default=0) + 1
    oferta["id"] = oid
    ofertas.append(oferta)
    if guardar_ofertas_compra(usuario_id, ofertas):
        return oferta
    return None


def actualizar_oferta_compra(usuario_id: int, oferta: dict) -> bool:
    """Actualiza una oferta existente por id."""
    ofertas = get_ofertas_compra(usuario_id)
    for i, o in enumerate(ofertas):
        if o.get("id") == oferta.get("id"):
            ofertas[i] = oferta
            return guardar_ofertas_compra(usuario_id, ofertas)
    return False


def eliminar_oferta_compra(usuario_id: int, oferta_id: int) -> bool:
    """Elimina una oferta por id."""
    ofertas = [o for o in get_ofertas_compra(usuario_id) if o.get("id") != oferta_id]
    return guardar_ofertas_compra(usuario_id, ofertas)


# --- Perfiles de provisiones de fondos (mismo JSON que antes: aportacion_efectivo) ---

def _path_aportacion_efectivo(usuario_id: int) -> str:
    return f"{APORTACION_EFECTIVO_DIR}/usuario_{usuario_id}.json"


def get_aportacion_efectivo(usuario_id: int) -> dict:
    """Lee perfiles de provisiones de fondos: combinaciones de importes + Incluir (o formato legacy). Vacío si no hay fichero."""
    repo = _repo()
    if not repo:
        return {}
    path = _path_aportacion_efectivo(usuario_id)
    try:
        c = repo.get_contents(path)
        return json.loads(base64.b64decode(c.content).decode())
    except Exception:
        return {}


def guardar_aportacion_efectivo(usuario_id: int, data: dict) -> bool:
    """Persiste perfiles de provisiones: {'combinaciones': [...], 'combinacion_activa_id': int}."""
    repo = _repo()
    if not repo:
        return False
    path = _path_aportacion_efectivo(usuario_id)
    contenido = json.dumps(data, indent=2, ensure_ascii=False)
    try:
        c = repo.get_contents(path)
        repo.update_file(path, "Actualizar provisiones de fondos", contenido, c.sha)
    except Exception:
        try:
            repo.create_file(path, "Crear provisiones de fondos usuario", contenido)
        except Exception:
            return False
    return True
