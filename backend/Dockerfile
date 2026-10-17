FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libpq para psycopg; libgl/libglib para la geometría de ifcopenshell.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Cola de trabajos pesados (parseo IFC) — capa separada a propósito: agrega
# rq sin invalidar la caché del install grande de requirements.txt.
RUN pip install --no-cache-dir rq==1.16.2

# OCR de facturas escaneadas (fallback cuando el PDF no trae capa de texto).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytesseract==0.3.13

COPY . .

RUN chmod +x /app/scripts/start.sh || true

EXPOSE 8000

CMD ["bash", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]
