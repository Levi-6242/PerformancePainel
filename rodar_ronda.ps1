# rodar_ronda.ps1 - dispara a RONDA DE TRACKERS AGORA nos 5 grupos reais (fallback manual, caso a
# automatica das 08:25/13:15 nao tenha ido). Garante o servidor no ar, pede confirmacao e envia.
# Chamado por "Rodar Ronda Agora.bat".
$ErrorActionPreference = 'SilentlyContinue'
$dir = $PSScriptRoot
Set-Location $dir

function Porta5050 {
  try { return [bool](Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction Stop) }
  catch { return $false }
}

Write-Host ''
Write-Host '======  RODAR A RONDA DE TRACKERS AGORA  ======' -ForegroundColor Cyan
Write-Host ''

# 1) Servidor no ar? (a ronda precisa dele)
if (Porta5050) {
  Write-Host '1) Servidor ja esta no ar.' -ForegroundColor Gray
} else {
  Write-Host '1) Servidor fora do ar - subindo...' -ForegroundColor Yellow
  $pyw = "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\pythonw.exe"
  if (-not (Test-Path $pyw)) { $pyw = 'pythonw' }
  Start-Process -FilePath $pyw -ArgumentList 'app.py' -WorkingDirectory $dir -WindowStyle Hidden
  for ($i = 0; $i -lt 20; $i++) { Start-Sleep 2; if (Porta5050) { break } }
}
if (-not (Porta5050)) { Write-Host 'Nao consegui subir o servidor. Chame o Claude.' -ForegroundColor Red; Read-Host 'Enter'; exit 1 }

# 2) Servico do WhatsApp (5099) conectado?
$tok = ''
try { $tok = (Get-Content (Join-Path $dir 'whats_ronda.json') -Raw | ConvertFrom-Json).token } catch {}
$waok = $false
try { $waok = ((Invoke-RestMethod -Uri 'http://127.0.0.1:5099/status' -Headers @{ 'x-token' = $tok } -TimeoutSec 8).status -eq 'conectado') } catch {}
if ($waok) {
  Write-Host '2) Servico do WhatsApp: conectado.' -ForegroundColor Gray
} else {
  Write-Host '2) AVISO: o WhatsApp ainda nao esta conectado (sobe sozinho em 1-2 min).' -ForegroundColor Yellow
  Write-Host '   Se o envio falhar, espere um pouco e rode de novo.' -ForegroundColor Yellow
}

# 3) Confirmacao (evita disparo acidental / duplicado)
Write-Host ''
Write-Host 'Isto vai ENVIAR a ronda AGORA nos 5 grupos reais (COS x Tecnicos O&M).' -ForegroundColor White
$c = Read-Host 'Digite  ENVIAR  para confirmar (ou Enter para cancelar)'
if ($c -ne 'ENVIAR') { Write-Host 'Cancelado - nada foi enviado.' -ForegroundColor Gray; Read-Host 'Enter'; exit 0 }

# 4) Login (senha do .env, nunca impressa) + dispara
$pw = ''
foreach ($ln in (Get-Content (Join-Path $dir '.env'))) {
  if ($ln -match '^\s*DASH_PASSWORD\s*=\s*(.+?)\s*$') { $pw = $Matches[1].Trim('"').Trim("'") }
}
$sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
try {
  Invoke-WebRequest -Uri 'http://127.0.0.1:5050/login' -Method Post -Body @{ senha = $pw } `
    -WebSession $sess -MaximumRedirection 0 -UseBasicParsing -TimeoutSec 15 | Out-Null
} catch {}

Write-Host ''
Write-Host 'Enviando... a coleta AO VIVO das 5 fontes leva ~5-7 min. Aguarde.' -ForegroundColor Cyan
try {
  $r = Invoke-RestMethod -Uri 'http://127.0.0.1:5050/api/ronda/whats/testar' -Method Post `
    -ContentType 'application/json' -Body '{}' -WebSession $sess -TimeoutSec 600
  Write-Host ''
  Write-Host 'RESULTADO DO ENVIO:' -ForegroundColor Green
  $r | ConvertTo-Json -Depth 6
} catch {
  Write-Host ''
  Write-Host 'O pedido demorou, mas o envio CONTINUA no servidor e conclui.' -ForegroundColor Yellow
  Write-Host 'Confira nos grupos do WhatsApp em ~5 min.' -ForegroundColor Yellow
}
Write-Host ''
Read-Host 'Enter para fechar'
