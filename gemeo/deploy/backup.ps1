# gemeo/deploy/backup.ps1
# Copia consistente do banco SQLite do gemeo (API de backup do proprio SQLite, via python) para a pasta que a T.I. ja
# copia. Guarda 14 dias. ASCII puro (ver instalar_tarefas.ps1). Copiar o arquivo "na mao" com o gemeo rodando pode
# pegar o WAL pela metade - por isso a API de backup, que e atomica.
# Uso: .\backup.ps1 -Destino "D:\Backups\gemeo" -Banco "C:\Users\<user>\AppData\Local\GridCo\gemeo\gemeo.sqlite" -Python "C:\Python312\python.exe"
param(
  [Parameter(Mandatory = $true)][string]$Destino,
  [string]$Banco = "",
  [string]$Python = "python",
  [int]$Dias = 14
)
$ErrorActionPreference = "Stop"
if (-not $Banco) { $Banco = Join-Path $env:LOCALAPPDATA "GridCo\gemeo\gemeo.sqlite" }
if (-not (Test-Path $Banco)) { throw ("Banco nao encontrado: " + $Banco) }
New-Item -ItemType Directory -Force $Destino | Out-Null
$arq = Join-Path $Destino ("gemeo_" + (Get-Date -Format "yyyyMMdd_HHmm") + ".sqlite")
$codigo = "import sqlite3,sys; o=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); o.backup(d); d.close(); o.close()"
& $Python -c $codigo $Banco $arq
if ($LASTEXITCODE -ne 0) { throw ("backup falhou com codigo " + $LASTEXITCODE) }
Get-ChildItem $Destino -Filter "gemeo_*.sqlite" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$Dias) } | Remove-Item -Force
Write-Host ("backup ok: " + $arq)
