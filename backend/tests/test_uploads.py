"""Tope de tamaño en uploads: corta sin dejar archivos a medias.

Corre directo: python tests/test_uploads.py (dentro del contenedor).
"""
import asyncio
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _upload(data: bytes, with_size: bool = True):
    from fastapi import UploadFile
    return UploadFile(io.BytesIO(data), filename="x.bin",
                      size=len(data) if with_size else None)


def test_read_upload_corta_por_tamano():
    from fastapi import HTTPException

    from app.core.uploads import read_upload

    assert asyncio.run(read_upload(_upload(b"a" * 10), 10)) == b"a" * 10
    for with_size in (True, False):  # con size declarado y leyendo por bloques
        try:
            asyncio.run(read_upload(_upload(b"a" * 11, with_size), 10))
            raise AssertionError("debió cortar con 413")
        except HTTPException as exc:
            assert exc.status_code == 413


def test_save_upload_no_deja_archivo_a_medias():
    from fastapi import HTTPException

    from app.core.uploads import save_upload

    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "sub" / "f.part"
        assert asyncio.run(save_upload(_upload(b"x" * 5), dest, 10)) == 5
        assert dest.read_bytes() == b"x" * 5
        dest.unlink()
        try:
            asyncio.run(save_upload(_upload(b"x" * (3 * 1024 * 1024), False), dest, 1024 * 1024))
            raise AssertionError("debió cortar con 413")
        except HTTPException as exc:
            assert exc.status_code == 413
        assert not dest.exists(), "quedó el archivo parcial"


if __name__ == "__main__":
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests pasaron")
    sys.exit(1 if failed else 0)
