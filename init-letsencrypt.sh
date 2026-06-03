#!/bin/bash
set -e

if ! [ -x "$(command -v docker)" ]; then
  echo 'Error: docker no está instalado.' >&2
  exit 1
fi

domains=(tu-dominio.com www.tu-dominio.com)
rsa_key_size=4096
data_path="./nginx/certbot"
email="tucorreo@gmail.com" # Cambiar esto
staging=1 # Set a 1 si estás probando para evitar ban limits. Set 0 para prod real.

if [ -d "$data_path" ]; then
  read -p "Datos de Certbot existentes encontrados. ¿Continuar y reemplazar certificados existentes? (y/N) " decision
  if [ "$decision" != "Y" ] && [ "$decision" != "y" ]; then
    exit
  fi
fi

echo "### Descargando parámetros TLS recomendados ..."
mkdir -p "$data_path/conf"
curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf > "$data_path/conf/options-ssl-nginx.conf"
curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem > "$data_path/conf/ssl-dhparams.pem"
echo

echo "### Generando certificado dummy por primera vez para $domains ..."
path="/etc/letsencrypt/live/$domains"
mkdir -p "$data_path/conf/live/$domains"
docker compose -f docker-compose.prod.yml run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:$rsa_key_size -days 1\
    -keyout '$path/privkey.pem' \
    -out '$path/fullchain.pem' \
    -subj '/CN=localhost'" certbot
echo


echo "### Iniciando nginx ..."
docker compose -f docker-compose.prod.yml up --force-recreate -d nginx
echo

echo "### Borrando certificado dummy y pidiendo el real ..."
docker compose -f docker-compose.prod.yml run --rm --entrypoint "\
  rm -Rf /etc/letsencrypt/live/$domains && \
  rm -Rf /etc/letsencrypt/archive/$domains && \
  rm -Rf /etc/letsencrypt/renewal/$domains.conf" certbot
echo

domain_args=""
for domain in "${domains[@]}"; do
  domain_args="$domain_args -d $domain"
done

email_arg="--email $email"

if [ $staging != "0" ]; then staging_arg="--staging"; fi

docker compose -f docker-compose.prod.yml run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $staging_arg \
    $email_arg \
    $domain_args \
    --rsa-key-size $rsa_key_size \
    --agree-tos \
    --force-renewal" certbot
echo

echo "### Reiniciando nginx para cargar los certificados ..."
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
