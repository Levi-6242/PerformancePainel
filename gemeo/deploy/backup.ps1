# gemeo/deploy/backup.ps1
# pg_dump diario do banco gemeo para a pasta que a T.I. ja copia. Guarda 14 dias. ASCII puro (ver instalar_tarefas.ps1).
# Insubstituiveis no banco: modelo (calibracoes) e alias manual; o resto se reconstroi das fontes.
# Uso: .\backup.ps1 -Destino "D:\Backups\gemeo" -PgDump "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe"
# O DSN vem de GEMEO_DB_DSN (mesmo valor do gemeo.env) para nao deixar senha em linha de comando.
param(
  [Parameter(Mandatory = $true)][string]$Destino,
  [string]$PgDump = "pg_dump",
  [string]$Dsn = $env:GEMEO_DB_DSN,
  [int]$Dias = 14
)
$ErrorActionPreference = "Stop"
if (-not $Dsn) { throw "Defina GEMEO_DB_DSN (ou passe -Dsn) com o mesmo valor do gemeo.env." }
New-Item -ItemType Directory -Force $Destino | Out-Null
$arq = Join-Path $Destino ("gemeo_" + (Get-Date -Format "yyyyMMdd_HHmm") + ".dump")
& $PgDump --format=custom --no-owner --file=$arq --dbname=$Dsn
if ($LASTEXITCODE -ne 0) { throw ("pg_dump falhou com codigo " + $LASTEXITCODE) }
Get-ChildItem $Destino -Filter "gemeo_*.dump" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$Dias) } | Remove-Item -Force
Write-Host ("backup ok: " + $arq)
