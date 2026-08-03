# subir_tunel.ps1 — GARANTE o servidor (porta 5050) no ar e sobe o Cloudflare Tunnel, salvando a URL
# em tunnel_url.txt. Chamado pelo "Compartilhar Dashboard.bat". Fechar esta janela encerra o TUNEL;
# o servidor segue no ar (escondido) - para para-lo, use o Gerenciador de Tarefas > pythonw.exe.
$ErrorActionPreference = "SilentlyContinue"
$dir = $PSScriptRoot
Set-Location $dir
$errlog  = Join-Path $dir "cloudflared_tunnel.log"
$outlog  = Join-Path $dir "cloudflared_tunnel.out.log"
$urlfile = Join-Path $dir "tunnel_url.txt"

function Porta5050 {
  try { return [bool](Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction Stop) }
  catch { return $false }
}

# 1) SERVIDOR (5050): so sobe se estiver FORA do ar, e com o Python REAL (nao o 'python' do PATH, que
#    pode ser o alias da Microsoft Store e abrir a Loja em vez de rodar). Assim nunca sobem 2 servidores.
if (Porta5050) {
  Write-Host "Servidor ja esta no ar (porta 5050)." -ForegroundColor Gray
} else {
  Write-Host "Subindo o servidor local (porta 5050)..." -ForegroundColor Cyan
  $pyw = "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\pythonw.exe"
  if (Test-Path $pyw) {
    Start-Process -FilePath $pyw -ArgumentList 'app.py' -WorkingDirectory $dir -WindowStyle Hidden
  } else {
    Write-Host "  (Python real nao achado; tentando pythonw/python do PATH)" -ForegroundColor DarkGray
    $alt = 'python'; if (Get-Command pythonw -ErrorAction SilentlyContinue) { $alt = 'pythonw' }
    Start-Process -FilePath $alt -ArgumentList 'app.py' -WorkingDirectory $dir -WindowStyle Minimized
  }
  for ($i = 0; $i -lt 20; $i++) { Start-Sleep 2; if (Porta5050) { break } }
  if (Porta5050) { Write-Host "Servidor no ar." -ForegroundColor Green }
  else { Write-Host "NAO consegui subir o servidor - chame o Claude." -ForegroundColor Red }
}

# 2) TUNEL: mata cloudflared antigo e apaga logs velhos (evita 2 tuneis e URL morta ressuscitada no log).
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 1
Remove-Item $errlog, $outlog -Force -ErrorAction SilentlyContinue

# Acha o cloudflared: PATH ou caminho do WinGet
$cf = "cloudflared"
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
  $cf = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe"
}

Write-Host "Abrindo o tunel Cloudflare..." -ForegroundColor Cyan
# --protocol http2 forca TCP em vez de QUIC/UDP. Nesta rede o QUIC falha ("failed to dial to edge
# with quic: no recent network activity") e o link nasce com erro 530 / "origin unregistered".
$proc = Start-Process -FilePath $cf -ArgumentList 'tunnel', '--protocol', 'http2', '--url', 'http://localhost:5050' `
        -PassThru -NoNewWindow -RedirectStandardError $errlog -RedirectStandardOutput $outlog

# Espera a URL aparecer no log e grava no arquivo (UTF-8 sem BOM, sem quebra de linha)
$url = $null
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  $txt = [string](Get-Content $errlog, $outlog -Raw -ErrorAction SilentlyContinue)
  $m = [regex]::Match($txt, 'https://[a-z0-9-]+\.trycloudflare\.com')
  if ($m.Success) { $url = $m.Value; break }
}

if ($url) {
  [System.IO.File]::WriteAllText($urlfile, $url)
  try { Set-Clipboard -Value $url } catch {}
  Write-Host ""
  Write-Host "===================================================================" -ForegroundColor Green
  Write-Host "  LINK PUBLICO (ja copiado p/ a area de transferencia):" -ForegroundColor Green
  Write-Host "  $url" -ForegroundColor Yellow
  Write-Host "  (senha = DASH_PASSWORD do .env  |  link salvo em tunnel_url.txt)" -ForegroundColor Gray
  Write-Host "===================================================================" -ForegroundColor Green
  # Bonus: manda o link no seu WhatsApp (best-effort; ignora se o servico estiver fora).
  try {
    $cfg = Get-Content (Join-Path $dir "whats_ronda.json") -Raw | ConvertFrom-Json
    if ($cfg.service_url -and $cfg.token -and $cfg.confirmar_para) {
      $body = @{ para = "$($cfg.confirmar_para)"; texto = "Link novo do dashboard: $url  (senha de sempre)" } | ConvertTo-Json
      Invoke-RestMethod -Uri "$($cfg.service_url)/send" -Method Post `
        -Headers @{ 'x-token' = $cfg.token } -ContentType 'application/json' `
        -Body $body -TimeoutSec 15 | Out-Null
      Write-Host "  (tambem te enviei o link no WhatsApp)" -ForegroundColor Gray
    }
  } catch {}
  Write-Host ""
  Write-Host "  NAO FECHE esta janela enquanto quiser manter o link no ar." -ForegroundColor Cyan
} else {
  Write-Host "Nao consegui capturar a URL. Ultimas linhas do log:" -ForegroundColor Red
  Get-Content $errlog -Tail 12 -ErrorAction SilentlyContinue
}

# Segura a janela enquanto o tunel roda (fechar a janela encerra o tunel)
Wait-Process -Id $proc.Id
Write-Host "(Tunel encerrado.)"
