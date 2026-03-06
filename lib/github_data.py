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
