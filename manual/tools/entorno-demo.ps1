# Entorno local AISLADO para generar el manual (capturas y videos).
#
#  - base, cola, backend y worker propios (docker-compose.manual.yml, proyecto "scalist-manual");
#  - puertos que no chocan con desarrollo: base 5450, redis 6390, API 8100, web 3100;
#  - el frontend corre en el host (next dev) con NEXT_PUBLIC_API_URL apuntando a la API del manual;
#  - no se toca el .env del desarrollador ni sus contenedores.
#
# Uso:
#   .\manual\tools\entorno-demo.ps1 up        # arranca base, cola, API y worker (migra solo)
#   .\manual\tools\entorno-demo.ps1 web       # arranca el frontend en http://localhost:3100
#   .\manual\tools\entorno-demo.ps1 down      # detiene los contenedores del manual
#   .\manual\tools\entorno-demo.ps1 destroy   # borra contenedores, base y archivos demo
#
# Requiere la imagen del backend construida: `docker compose build backend` en la raíz.

param([Parameter(Mandatory = $true)][ValidateSet('up', 'web', 'down', 'destroy')][string]$Accion)

$ErrorActionPreference = 'Continue'
function Assert-Ok($paso) { if ($LASTEXITCODE -ne 0) { throw "Falló: $paso (exit $LASTEXITCODE)" } }
$tools = $PSScriptRoot
$root = Resolve-Path (Join-Path $tools '..\..')
$compose = Join-Path $tools 'docker-compose.manual.yml'

switch ($Accion) {
  'up' {
    New-Item -ItemType Directory -Force (Join-Path $tools 'datos-demo\storage') | Out-Null
    docker compose -f $compose up -d; Assert-Ok 'docker compose up'
    for ($i = 0; $i -lt 60; $i++) {
      try { if ((Invoke-WebRequest -UseBasicParsing http://localhost:8100/docs -TimeoutSec 2).StatusCode -eq 200) { break } } catch {}
      Start-Sleep -Seconds 2
    }
    Write-Host 'API del manual: http://localhost:8100/docs'
  }
  'web' {
    $env:NEXT_PUBLIC_API_URL = 'http://localhost:8100'
    # El paso Ubicación necesita el token público de Mapbox: se toma solo esa línea del .env.
    $mapbox = Get-Content (Join-Path $root '.env') -ErrorAction SilentlyContinue |
      Where-Object { $_ -match '^NEXT_PUBLIC_MAPBOX_TOKEN=' } | Select-Object -First 1
    if ($mapbox) { $env:NEXT_PUBLIC_MAPBOX_TOKEN = $mapbox.Split('=', 2)[1] }
    Set-Location (Join-Path $root 'frontend')
    npx next dev -p 3100
  }
  'down' { docker compose -f $compose stop }
  'destroy' {
    docker compose -f $compose down -v
    Remove-Item -Recurse -Force (Join-Path $tools 'datos-demo\storage') -ErrorAction SilentlyContinue
  }
}
