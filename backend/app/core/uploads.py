"""Lectura de uploads con tope de tamaño, sin cargar de más en memoria.

Starlette ya dejó el archivo en un SpooledTemporaryFile (a disco pasado 1 MB),
así que `file.size` suele venir resuelto: si excede, cortamos sin leer nada.
Si no viene, leemos por bloques y cortamos apenas se pasa del tope.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile

_CHUNK = 1024 * 1024


def _too_big(max_bytes: int) -> HTTPException:
    mb = max_bytes // (1024 * 1024)
    return HTTPException(status_code=413, detail=f"Archivo demasiado grande (máx {mb} MB)")


async def read_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Devuelve el contenido; 413 si supera `max_bytes`."""
    if file.size is not None and file.size > max_bytes:
        raise _too_big(max_bytes)
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise _too_big(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


async def save_upload(file: UploadFile, dest: Path, max_bytes: int) -> int:
    """Copia el upload a `dest` por bloques (nunca entero en memoria).
    413 si supera `max_bytes` (y no deja el archivo a medias). Devuelve bytes."""
    if file.size is not None and file.size > max_bytes:
        raise _too_big(max_bytes)
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(_CHUNK):
                total += len(chunk)
                if total > max_bytes:
                    raise _too_big(max_bytes)
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return total
