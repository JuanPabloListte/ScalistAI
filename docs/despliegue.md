# Despliegue en producción

Scalist corre en un servidor propio (VPS) con Docker. `docker-compose.prod.yml` levanta todo:
Postgres, Redis, backend (FastAPI con gunicorn), worker (procesa los IFC), frontend (Next.js),
nginx (HTTPS) y certbot (renueva el certificado).

```
Internet ──► nginx :443 ──► /api, /docs ──► backend ──► Postgres
                       └──► /           ──► frontend      Redis ◄── worker (IFC)
                                           storage/ (archivos subidos, en el disco del servidor)
```

## 1. Servidor

- **Mínimo recomendado:** 4 vCPU, 8 GB de RAM, 80–160 GB de disco. Con 2 vCPU / 4 GB anda, pero
  un IFC grande (hasta 500 MB) puede dejar sin memoria al worker. No hace falta GPU.
- **Sistema:** Ubuntu 24.04 LTS.
- **Proveedores:** Hetzner (mejor precio), DigitalOcean o Vultr (Nueva York / Miami, buena llegada
  desde Argentina), AWS Lightsail en São Paulo (menor latencia, más caro).

Preparación, como root:

```bash
# Docker oficial
curl -fsSL https://get.docker.com | sh

# Firewall: SSH, HTTP y HTTPS
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable

# Swap de 4 GB: colchón para los IFC grandes
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## 2. Dominio

En el proveedor del dominio, creá dos registros **A** apuntando a la IP del servidor:
`tudominio.com` y `www.tudominio.com`. Esperá a que resuelvan (`ping tudominio.com`) antes de
pedir el certificado.

## 3. Código

El repo es privado: generá una *deploy key* en el servidor y agregala en GitHub
(Settings → Deploy keys, solo lectura).

```bash
ssh-keygen -t ed25519 -f ~/.ssh/scalist_deploy -N ""
cat ~/.ssh/scalist_deploy.pub        # pegarla en GitHub
GIT_SSH_COMMAND="ssh -i ~/.ssh/scalist_deploy" git clone git@github.com:JuanPabloListte/ScalistAI.git /opt/scalist
cd /opt/scalist
git config core.sshCommand "ssh -i ~/.ssh/scalist_deploy"
```

## 4. Configuración (`.env`)

```bash
cp .env.example .env
nano .env
```

| Variable | Valor en producción |
|---|---|
| `ENVIRONMENT` | `production` (con un `JWT_SECRET` débil, el backend no arranca) |
| `JWT_SECRET` | resultado de `openssl rand -hex 32` |
| `POSTGRES_USER` / `POSTGRES_DB` | `scalist` |
| `POSTGRES_PASSWORD` | resultado de `openssl rand -hex 16` |
| `POSTGRES_HOST` | `postgres` |
| `CORS_ORIGINS` | `https://tudominio.com,https://www.tudominio.com` |
| `NEXT_PUBLIC_API_URL` | vacío (la API se sirve en el mismo dominio, bajo `/api`) |
| `NEXT_PUBLIC_MAPBOX_TOKEN` | token público de Mapbox (lo usa el paso Ubicación) |
| `NEXT_PUBLIC_FEATURE_*` | `false` |

Las variables `NEXT_PUBLIC_*` se graban en el frontend al construirlo: si las cambiás, hay que
volver a construir (`./deploy.sh`).

## 5. Dominio en nginx y certificado

```bash
sed -i 's/tudominio\.com/TU-DOMINIO.com/g' nginx/conf.d/default.conf init-letsencrypt.sh
sed -i 's/tucorreo@gmail\.com/TU-MAIL/' init-letsencrypt.sh

docker compose -f docker-compose.prod.yml build
chmod +x init-letsencrypt.sh deploy.sh backup.sh
./init-letsencrypt.sh          # primera vez con staging=1 (certificado de prueba)
```

Si salió bien, poné `staging=0` en `init-letsencrypt.sh`, correlo de nuevo para el certificado
real y levantá todo:

```bash
./init-letsencrypt.sh
docker compose -f docker-compose.prod.yml up -d
```

El backend aplica las migraciones solo al arrancar. El contenedor `certbot` renueva el
certificado cada 12 h si hace falta.

## 6. Primer usuario

No hay registro público. Creá el superadmin (pide la contraseña por teclado):

```bash
docker compose -f docker-compose.prod.yml exec backend python -m scripts.crear_superadmin vos@tuempresa.com
```

Después entrá a `https://tudominio.com/login`, andá a **Organizaciones** y creá la organización de
cada cliente con su primer administrador (ver el manual de usuario, capítulo 11).

## 7. Verificar

- `https://tudominio.com` muestra la landing y `https://tudominio.com/login` el ingreso.
- `https://tudominio.com/docs` muestra la API.
- Creá un proyecto de prueba y subí un IFC: tiene que pasar de «Procesando» a «Listo».
- Estado de los servicios: `docker compose -f docker-compose.prod.yml ps`.
- Logs: `docker compose -f docker-compose.prod.yml logs -f backend worker`.

## 8. Actualizar

```bash
./deploy.sh
```

Hace `git pull`, baja los contenedores, construye y vuelve a levantar. Hay un corte de uno o dos
minutos mientras se reconstruye: conviene hacerlo fuera de horario.

## 9. Backups

Todo lo importante vive en el servidor: la base (volumen `postgres_data`) y los archivos subidos
(`storage/`). `backup.sh` guarda los dos en `backups/<fecha>/` y borra los de más de 14 días.

```bash
crontab -e
# Todos los días a las 3:
0 3 * * * cd /opt/scalist && ./backup.sh >> backups/backup.log 2>&1
```

**Copia fuera del servidor** (si el disco muere, los backups locales mueren con él): instalá
`rclone`, configurá un remoto (Backblaze B2, S3, Google Drive…) con `rclone config` y agregá la
variable al cron:

```bash
0 3 * * * cd /opt/scalist && BACKUP_REMOTE=b2:scalist-backups ./backup.sh >> backups/backup.log 2>&1
```

### Restaurar un backup

```bash
docker compose -f docker-compose.prod.yml stop backend worker
set -a; . ./.env; set +a
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < backups/<fecha>/db.dump
tar -xzf backups/<fecha>/storage.tar.gz          # restaura storage/
docker compose -f docker-compose.prod.yml start backend worker
```

Probá restaurar al menos una vez, en otra máquina: un backup que nunca se restauró no está
probado.

## 10. Opcional: el manual en el mismo dominio

Para servir el manual en `https://tudominio.com/manual/`, montá la carpeta en nginx
(`docker-compose.prod.yml`, servicio `nginx`, en `volumes`):

```yaml
      - ./manual:/usr/share/nginx/manual:ro
```

y agregá en el bloque `server { listen 443 … }` de `nginx/conf.d/default.conf`:

```nginx
    location /manual/ {
        alias /usr/share/nginx/manual/;
        index index.html;
    }
```

## Antes del primer despliegue

- [ ] `git push` de `main` (los commits locales todavía no están en GitHub).
- [ ] `.env` de producción con `JWT_SECRET` y contraseñas propias (nunca los del `.env` de desarrollo).
- [ ] Dominio real en `nginx/conf.d/default.conf` e `init-letsencrypt.sh`.
- [ ] Backup diario configurado y una restauración probada.
- [ ] Revisión legal de `/legal/terms`.
