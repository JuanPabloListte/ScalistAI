"""Clasificador semántico de nombres de capa CAD vía LLM local (Ollama).

Cada estudio nombra las capas distinto (TUONG, S-COLS, A-MURO, cerramiento...).
El clasificador por keywords (`_classify_layer`) cubre lo predecible; lo que no
reconoce se le pasa a un LLM local que entiende el SIGNIFICADO, no las letras.

Diseño:
- Corre en Ollama (CPU, sin GPU) → no compite con el entrenamiento, gratis,
  sin apikey. Si Ollama no responde, devuelve vacío y el import sigue con
  keywords (degradación elegante, nunca rompe).
- Cachea cada decisión en `storage/models/layer_cache.json`. Esa caché evita
  re-preguntar Y acumula un dataset (nombre → tipo) para, a futuro, destilar un
  clasificador propio que reemplace al LLM.
- Parsing defensivo: el 3B a veces responde "wall (muro...)" en vez de "wall";
  mapeamos por substring a los tipos canónicos.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "ollama")
_OLLAMA_PORT = os.environ.get("OLLAMA_PORT", "11434")
_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
_OLLAMA_URL = f"http://{_OLLAMA_HOST}:{_OLLAMA_PORT}/api/generate"
_TIMEOUT_S = int(os.environ.get("OLLAMA_TIMEOUT_S", "120"))

_CACHE_FILE = Path("storage/models/layer_cache.json")

# Tipos canónicos → substrings (en minúscula) que, si aparecen en la respuesta
# del LLM, lo mapean a ese tipo. Orden importa: pluvial se chequea primero y
# devuelve None (no es cloaca, ver pdf_vector_import._PLUVIAL_KEYS).
_PLUVIAL_HINTS = ("pluvial",)
_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("wall", ("wall", "muro", "pared", "tabique", "mamposter")),
    ("opening", ("opening", "puerta", "ventana", "abertura", "door", "window", "carpinter", "vano")),
    ("column", ("column", "columna", "pilar", "pilote")),
    ("beam", ("beam", "viga")),
    ("escalera", ("escalera", "stair", "escalon")),
    ("cloaca", ("cloaca", "cloacal", "sanitari", "desague", "desagüe", "sewer")),
    ("electricidad", ("electric", "eléctric", "ilumina", "tablero", "tomacorriente")),
    ("pozo", ("pozo", "zapata", "cimiento", "fundacion", "fundación", "dado")),
    ("roof", ("roof", "techo", "losa", "cubierta", "azotea")),
]

# Solo estos tipos los EXTRAE hoy el import PDF; el resto (beam/roof) el LLM los
# puede nombrar pero no generan elementos todavía — igual se cachean.
_PROMPT = """Sos experto en planos CAD de arquitectura argentina. Para cada nombre de capa, respondé el tipo de elemento constructivo que representa, usando EXACTAMENTE una de estas palabras en inglés:
wall, opening, column, beam, cloaca, electricidad, escalera, pozo, roof, otro

Reglas ESTRICTAS:
- wall = muro, pared, tabique, mampostería, medianera. NO pisos/solados/hatch/equipamiento/árboles.
- opening = puerta, ventana, vidrio, carpintería, glazing.
- column = columna, pilar (S-COLS). Armadura/hierros/estructura son "otro".
- beam = viga.
- cloaca = SOLO desagüe sanitario/cloacal y cañerías de desagüe (caños, CAÑERIA, sanitario). NO pluvial, NO agua, NO gas.
- electricidad = SOLO instalación eléctrica/iluminación/tablero/bocas/tomas. GAS y AGUA son "otro".
- escalera = escalera.
- pozo = zapata, cimiento, fundación, dado.
- roof = techo, losa, cubierta.
- otro = cotas, textos, mobiliario, ejes, hatch, solados, pisos, vegetación, agua, gas, pluvial, equipamiento, armadura, y todo lo que no sea un elemento constructivo claro.

Ante la duda, respondé "otro" (preferimos no clasificar antes que clasificar mal).

Capas:
{layers}

Respondé SOLO un objeto JSON {{"nombre exacto de capa": "tipo"}}."""


def _parse_answer(value: str) -> str | None:
    """Mapea la respuesta (posiblemente sucia) del LLM a un tipo canónico."""
    a = (value or "").strip().lower()
    if not a or any(h in a for h in _PLUVIAL_HINTS):
        return None
    for canon, keys in _ALIASES:
        if any(k in a for k in keys):
            return canon
    return None  # "otro" / no reconocido


def _load_cache() -> dict[str, str | None]:
    try:
        if _CACHE_FILE.exists():
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("layer_llm: no se pudo guardar caché: %s", exc)


def _call_ollama(names: list[str]) -> dict[str, str | None]:
    """Una llamada batch al LLM. Devuelve {name: tipo_canónico|None}."""
    prompt = _PROMPT.format(layers="\n".join(f"- {n}" for n in names))
    body = json.dumps({
        "model": _OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(_OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=_TIMEOUT_S).read())
    raw = json.loads(resp["response"])
    out: dict[str, str | None] = {}
    for n in names:
        # match por nombre exacto o, si el LLM cambió mayúsculas, case-insensitive
        val = raw.get(n)
        if val is None:
            low = {k.lower(): v for k, v in raw.items()}
            val = low.get(n.lower())
        out[n] = _parse_answer(val) if isinstance(val, str) else None
    return out


def classify_layers_cached(names: list[str]) -> dict[str, str | None]:
    """Solo lee la caché, sin red. Para endpoints síncronos (ej. dxf-info del
    wizard) que no pueden bloquear esperando al LLM.

    Devuelve únicamente los nombres que YA tienen decisión cacheada (incluida
    la decisión None = "otro"); los ausentes son misses a resolver con
    `prewarm_layers_async`.
    """
    cache = _load_cache()
    return {n: cache[n] for n in {n.strip() for n in names} if n and n in cache}


def prewarm_layers_async(names: list[str]) -> None:
    """Clasifica capas en un hilo daemon (fire-and-forget) para calentar la
    caché. El próximo fetch del endpoint ya encuentra las sugerencias.
    Nunca lanza; si Ollama no está, classify_layers degrada solo."""
    cache = _load_cache()
    pending = [n for n in {n.strip() for n in names} if n and n not in cache]
    if not pending:
        return
    threading.Thread(
        target=classify_layers, args=(pending,), daemon=True,
        name="layer-llm-prewarm",
    ).start()


def classify_layers(names: list[str]) -> dict[str, str | None]:
    """Clasifica nombres de capa desconocidos vía LLM, con caché.

    Devuelve {name: tipo|None}. Nunca lanza: si Ollama falla, devuelve lo que
    haya en caché (o vacío) y loguea — el import sigue con keywords.
    """
    names = [n for n in {n.strip() for n in names} if n]
    if not names:
        return {}
    cache = _load_cache()
    result: dict[str, str | None] = {}
    misses: list[str] = []
    for n in names:
        if n in cache:
            result[n] = cache[n]
        else:
            misses.append(n)

    if misses:
        try:
            fresh = _call_ollama(misses)
            cache.update(fresh)
            result.update(fresh)
            _save_cache(cache)
            logger.info("layer_llm: clasificadas %d capas nuevas vía %s", len(fresh), _OLLAMA_MODEL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("layer_llm: Ollama no disponible (%s) — sigo con keywords", exc)
            for n in misses:
                result[n] = None
    return result
