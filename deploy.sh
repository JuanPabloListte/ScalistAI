#!/bin/bash
set -e

# Asegurar que estamos en el root del repo
cd "$(dirname "$0")"

echo "=== ScalistAI Deployment Script ==="

echo "[1/4] Descargando últimos cambios de GitHub..."
git pull origin main

echo "[2/4] Deteniendo contenedores de producción..."
docker compose -f docker-compose.prod.yml down

echo "[3/4] Re-construyendo imágenes (Frontend y Backend)..."
docker compose -f docker-compose.prod.yml build

echo "[4/4] Levantando entorno de producción..."
docker compose -f docker-compose.prod.yml up -d

echo "=== Despliegue completado con éxito! ==="
echo "Los contenedores están corriendo. Nginx debería estar ruteando el tráfico."
echo "Si es la primera vez, asegúrate de correr ./init-letsencrypt.sh para el SSL."
