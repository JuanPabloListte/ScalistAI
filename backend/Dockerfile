FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias del sistema: build tools + Qt6 + xvfb + xauth.
# ODA File Converter es una app Qt; en un servidor headless necesita:
#   - xvfb + xauth: `xvfb-run` le da un display X11 efímero por invocación
#     (sin esto: "Error: 'DISPLAY'" / "xauth command not found").
#   - set COMPLETO de libs xcb: sin ellas el plugin "xcb" de Qt no inicializa
#     ("Could not load the Qt platform plugin xcb even though it was found").
# Receta verificada en vivo contra un DWG real de AutoCAD 2018 (AC1032).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libglib2.0-0 \
    libgl1 \
    libegl1 \
    libfontconfig1 \
    libdbus-1-3 \
    libxcb1 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-shm0 \
    libxcb-sync1 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libxkbcommon-x11-0 \
    libsm6 \
    libice6 \
    xvfb \
    xauth \
    && rm -rf /var/lib/apt/lists/*

# ODA File Converter: convierte DWG → DXF en el servidor.
# El .deb NO está en git (54 MB). Descargalo de:
#   https://www.opendesign.com/guestfiles/oda_file_converter
# y colocalo en backend/ antes de hacer docker build.
COPY ODAFileConverter_QT6_lnxX64_8.3dll_27.1.deb /tmp/oda.deb
RUN apt-get update \
    && apt-get install -y /tmp/oda.deb \
    && rm /tmp/oda.deb \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Cola de trabajos pesados (IFC/vector/ML) — capa separada a propósito: agrega
# rq sin invalidar la caché del install grande de requirements.txt.
RUN pip install --no-cache-dir rq==1.16.2

# OCR de facturas escaneadas (fallback cuando el PDF no trae capa de texto).
# Capa tardía a propósito: tesseract + pytesseract sin recompilar torch & cía.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytesseract==0.3.13

COPY . .

RUN chmod +x /app/scripts/start.sh || true

EXPOSE 8000

# No se necesita un Xvfb daemon: la conversión DWG usa `xvfb-run` por llamada
# (ver app/services/dxf_import.py:_read_dwg), que crea y destruye su propio
# display efímero. Más robusto que coordinar un display global.
CMD ["bash", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]
