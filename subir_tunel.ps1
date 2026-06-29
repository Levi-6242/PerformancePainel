# subir_tunel.ps1 — sobe o Cloudflare Tunnel e SALVA a URL em tunnel_url.txt (paliativo do "link fixo").
# Chamado pelo "Compartilhar Dashboard.bat". Fechar esta janela encerra o túnel.
$ErrorActionPreference = "SilentlyContinue"
$dir = $PSScriptRoot
Set-Location $dir
$errlog  = Join-Path $dir "cloudflared_tunnel.log"
$outlog  = Join-Path $dir "cloudflared_tunnel.out.log"
$urlfile = Join-Path $dir "tunnel_url.txt"
Remove-Item $errlog, $outlog -Force -ErrorAction SilentlyContinue

# Acha o cloudflared: PATH ou caminho do WinGet
$cf = "cloudflared"
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
  $cf = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe"
}

Write-Host "Abrindo o tunel Cloudflare..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $cf -ArgumentList 'tunnel', '--url', 'http://localhost:5050' `
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
  Write-Host ""
  Write-Host "===================================================================" -ForegroundColor Green
  Write-Host "  LINK PUBLICO (compartilhe com a equipe):" -ForegroundColor Green
  Write-Host "  $url" -ForegroundColor Yellow
  Write-Host "  (senha = DASH_PASSWORD do .env  |  link salvo em tunnel_url.txt)" -ForegroundColor Gray
  Write-Host "===================================================================" -ForegroundColor Green
  Write-Host ""
  Write-Host "  NAO FECHE esta janela enquanto quiser manter o link no ar." -ForegroundColor Cyan
} else {
  Write-Host "Nao consegui capturar a URL. Ultimas linhas do log:" -ForegroundColor Red
  Get-Content $errlog -Tail 12 -ErrorAction SilentlyContinue
}

# Segura a janela enquanto o tunel roda (fechar a janela encerra o tunel)
Wait-Process -Id $proc.Id
Write-Host "(Tunel encerrado.)"
