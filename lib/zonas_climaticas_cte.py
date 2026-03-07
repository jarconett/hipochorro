"""
Zonas climáticas CTE (Código Técnico de la Edificación) por municipio en Andalucía.
Carga data/zonas_climaticas_cte_andalucia.json: { "Provincia": { "Municipio": "ZONA" } }.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "zonas_climaticas_cte_andalucia.json"

# Todas las zonas posibles: letra (invierno A-E) + número (verano 1-4)
ZONAS_CTE_VALIDAS = [f"{l}{n}" for l in "ABCDE" for n in "1234"]

_db: dict[str, dict[str, str]] | None = None


def _normalizar(nombre: str) -> str:
    """Minúsculas y sin acentos para búsqueda."""
    if not nombre:
        return ""
    n = unicodedata.normalize("NFD", nombre.lower().strip())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return n.replace(" ", "")


def cargar_db() -> dict[str, dict[str, str]]:
    """Carga el JSON de zonas por provincia/municipio. Cache en memoria."""
    global _db
    if _db is not None:
        return _db
    if not _DATA_PATH.exists():
        _db = {}
        return _db
    try:
        with open(_DATA_PATH, encoding="utf-8") as f:
            _db = json.load(f)
    except Exception:
        _db = {}
    return _db


def get_zona_por_municipio(municipio: str, provincia: str | None = None) -> str | None:
    """
    Busca la zona CTE para un municipio. Si se indica provincia, busca solo en ella.
    Devuelve ej. "B3" o None si no está en la base de datos.
    """
    db = cargar_db()
    m = _normalizar(municipio)
    if not m:
        return None
    provincias = [provincia] if provincia else list(db.keys())
    for prov in provincias:
        if prov not in db:
            continue
        for nombre, zona in db[prov].items():
            if _normalizar(nombre) == m:
                return zona
    return None


def get_opciones_zona() -> list[str]:
    """Lista para selectbox: primera opción vacía/No indicada, luego A1..E4."""
    return ["—"] + ZONAS_CTE_VALIDAS
