#!/bin/bash
# Backup diario de producción: base de datos + archivos subidos (storage/).
#
# Uso (en el servidor, desde la raíz del repo):
#   ./backup.sh                 deja el backup en ./backups/AAAA-MM-DD_HHMM/
# Con cron, todos los días a las 3:
#   0 3 * * * cd /opt/scalist && ./backup.sh >> backups/backup.log 2>&1
#
# Copia fuera del servidor (recomendado): si está configurado rclone con un
# remoto llamado como BACKUP_REMOTE (p. ej. "b2:scalist-backups"), sube la
# carpeta del día. Sin eso, el backup queda solo en este disco.
#
# Restaurar: ver docs/despliegue.md, sección "Restaurar un backup".
set -euo pipefail

cd "$(dirname "$0")"
COMPOSE="docker compose -f docker-compose.prod.yml"
KEEP_DAYS="${KEEP_DAYS:-14}"
BACKUP_REMOTE="${BACKUP_REMOTE:-}"

# Credenciales de la base: las mismas del .env de producción.
set -a; . ./.env; set +a

dest="backups/$(date +%Y-%m-%d_%H%M)"
mkdir -p "$dest"

echo "[$(date -Is)] Base de datos → $dest/db.dump"
$COMPOSE exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$dest/db.dump"

echo "[$(date -Is)] Archivos → $dest/storage.tar.gz"
tar -czf "$dest/storage.tar.gz" storage

# Un backup vacío es peor que ninguno: avisar fuerte.
if [ ! -s "$dest/db.dump" ]; then
  echo "ERROR: el dump de la base quedó vacío" >&2
  exit 1
fi

if [ -n "$BACKUP_REMOTE" ]; then
  echo "[$(date -Is)] Subiendo a $BACKUP_REMOTE"
  rclone copy "$dest" "$BACKUP_REMOTE/$(basename "$dest")"
fi

echo "[$(date -Is)] Borrando backups locales de más de $KEEP_DAYS días"
find backups -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -r {} +

echo "[$(date -Is)] Listo: $(du -sh "$dest" | cut -f1)"
