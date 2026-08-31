# ============================ DESATIVADO EM 27/08/2026 ============================
# NAO REARMAR. A porta 5080 ja tem dono: C:/GridcoAuto/vigia_thopen.ps1 (tarefa
# "Dashboard Thopen - Vigia", a cada 3 min), que sobe o SERVIDOR + o tunel e registra a
# URL em C:/GridcoAuto/thopen_url.txt (espelho em thopen/tunnel_url.txt).
# Este guardiao rodou por ~10 min em paralelo e os dois ENTRARAM EM GUERRA - cada um
# matava o tunel do outro a cada ciclo e o link trocava sem parar. A tarefa deste script
# foi removida; o arquivo fica como referencia (DNS-check/PID-file/dedup ja foram
# portados para o vigia). Se um dia o vigia for desligado, ai sim este pode assumir.
# ==================================================================================
# tunel_guardian_5080.ps1 - mantem o tunel do dashboard do CLIENTE (porta 5080) vivo.
#
# ASCII PURO DE PROPOSITO: o PowerShell 5.1 le .ps1 como ANSI; acento vira byte solto e o parser
# quebra em linha que nem e a culpada. Nao escreva acento aqui (mesma regra do guardiao da 5050).
#
# POR QUE EXISTE (27/08/2026, ordem do Levi: "proteja esse link a todo custo")
# O link do cliente caiu varias vezes em 2 dias. Pior: alguem/algo sobe cloudflared da 5080 SEM
# log (vimos processos 08:59 e 09:09 de 27/08 sem redirecionamento) - o tunel ate vive, mas a URL
# e IRRECUPERAVEL e o link morre "de pe". Este guardiao e o UNICO dono legitimo do tunel da 5080:
# registra URL (tunnel_url.txt) e PID (tunnel_pid.txt), derruba processos-fantasma da 5080 e
# ressuscita com log. Herda do guardiao da 5050: guarda da porta local (app fora != tunel morto),
# DNS-check antes de publicar, causa da morte registrada, e a REGRA DE OURO invertida - este
# script SO olha e SO mexe no que serve localhost:5080; o tunel da 5050 e INTOCAVEL aqui.
#
# COMO RODA: Tarefa Agendada "GridCo Tunel Guardian 5080", a cada 5 min (mesmo padrao da 5050).
$ErrorActionPreference = 'SilentlyContinue'
$dir  = $PSScriptRoot
$log  = Join-Path $dir 'cloudflared_5080.log'
$urlf = Join-Path $dir 'tunnel_url.txt'
$pidf = Join-Path $dir 'tunnel_pid.txt'
$hist = Join-Path $dir 'tunel_guardian_5080.log'

function Registra($m) { Add-Content -Path $hist -Value ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) }

$vivos = @(Get-CimInstance Win32_Process |
           Where-Object { $_.Name -like 'cloudflared*' -and $_.CommandLine -like '*localhost:5080*' })

$urlReg = $null
if (Test-Path $urlf) { $urlReg = (Get-Content $urlf -Raw).Trim() }
if (-not $urlReg -and (Test-Path $log)) {
    $mm = [regex]::Matches([string](Get-Content $log -Raw), 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($mm.Count -gt 0) { $urlReg = $mm[$mm.Count - 1].Value }
}
$pidReg = $null
if (Test-Path $pidf) { $pidReg = [int]((Get-Content $pidf -Raw).Trim()) }

# 1) A URL registrada responde? Tres tentativas - mas se a porta 5080 LOCAL estiver fora, o
#    problema e o APP (restart/deploy do dashboard), nao o tunel: nao mexe, o proximo ciclo julga.
$saudavel = $false
if ($vivos.Count -gt 0 -and $urlReg) {
    foreach ($t in 1..3) {
        if (-not (Get-NetTCPConnection -LocalPort 5080 -State Listen)) {
            Registra 'porta 5080 local fora durante o teste - e o app do cliente, nao o tunel; nao mexo'
            exit 0
        }
        if (Resolve-DnsName -Name ([uri]$urlReg).Host -Type A -ErrorAction SilentlyContinue) {
            try {
                $rr = Invoke-WebRequest -Uri $urlReg -TimeoutSec 20 -UseBasicParsing
                if ($rr.StatusCode -eq 200) { $saudavel = $true; break }
            } catch { }
        }
        Start-Sleep -Seconds 10
    }
}

if ($saudavel) {
    # URL boa no ar. Se ha MAIS de um cloudflared na 5080, os extras sao fantasmas (subidos por
    # fora, sem log): derruba quem nao e o PID registrado - um tunel so, o rastreavel.
    if ($vivos.Count -gt 1 -and $pidReg) {
        foreach ($v in $vivos) {
            if ($v.ProcessId -ne $pidReg) {
                Registra ("fantasma na 5080 (PID {0}) com a URL registrada saudavel - derrubado" -f $v.ProcessId)
                Stop-Process -Id $v.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
    }
    exit 0
}

# 2) URL registrada nao responde (ou nao ha registro). Tudo que serve a 5080 esta condenado:
#    processo vivo com URL morta/desconhecida e um tunel zumbi.
foreach ($v in $vivos) {
    Registra ("derrubando cloudflared 5080 PID {0} (URL registrada fora ou desconhecida)" -f $v.ProcessId)
    Stop-Process -Id $v.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($vivos.Count -gt 0) { Start-Sleep -Seconds 3 }

# 3) Sem o app de pe nao ha o que publicar.
if (-not (Get-NetTCPConnection -LocalPort 5080 -State Listen)) {
    Registra 'porta 5080 fechada - nao subi o tunel (o dashboard do cliente nao esta no ar)'
    exit 0
}

# 4) Sobe com log (Start-Process direto, sem cmd.exe no meio - a arvore fragil ja matou tuneis).
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) {
    $cf = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe"
}
if (-not (Test-Path $cf)) { Registra "cloudflared nao encontrado (tentei: $cf)"; exit 1 }
if (Test-Path $log) {
    $causa = (Select-String -Path $log -Pattern 'signal terminated|Tunnel not found|Unauthorized|no recent network activity|context canceled' -ErrorAction SilentlyContinue |
              Select-Object -Last 1).Line
    if ($causa) { Registra ('causa provavel da queda anterior: ' + $causa.Trim()) }
    Move-Item $log "$log.anterior" -Force
}
$proc = Start-Process -FilePath $cf -WindowStyle Hidden -PassThru `
    -ArgumentList 'tunnel','--protocol','http2','--ha-connections','1','--edge-ip-version','4','--url','http://localhost:5080' `
    -RedirectStandardError $log -RedirectStandardOutput ($log + '.out')

# 5) Captura a URL e SO publica depois do DNS resolver (link que nao resolve e pior que nenhum).
$url = $null
foreach ($i in 1..25) {
    Start-Sleep -Seconds 3
    $m = [regex]::Match([string](Get-Content $log -Raw), 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($m.Success) { $url = $m.Value; break }
}
if (-not $url) { Registra 'subi o cloudflared mas nao capturei a URL'; exit 1 }
$dns_ok = $false
foreach ($i in 1..12) {
    Start-Sleep -Seconds 5
    if (Resolve-DnsName -Name ([uri]$url).Host -Type A -ErrorAction SilentlyContinue) { $dns_ok = $true; break }
}
if (-not $dns_ok) {
    Registra "URL $url nao resolve no DNS; derrubei e o proximo ciclo tenta limpo"
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    exit 1
}
[System.IO.File]::WriteAllText($urlf, $url)
[System.IO.File]::WriteAllText($pidf, [string]$proc.Id)
Registra "tunel do CLIENTE ressuscitado -> $url (PID $($proc.Id))"

# 6) Avisa o admin no WhatsApp (best-effort; config do whats_ronda.json da plataforma).
try {
    $cfg = Get-Content (Join-Path (Split-Path $dir -Parent) 'plataforma\whats_ronda.json') -Raw | ConvertFrom-Json
    if ($cfg.service_url -and $cfg.token -and $cfg.confirmar_para) {
        $txt = "O tunel do dashboard do CLIENTE (5080) caiu e subiu de novo. Link novo: $url"
        $body = @{ para = "$($cfg.confirmar_para)"; texto = $txt } | ConvertTo-Json
        Invoke-RestMethod -Uri "$($cfg.service_url)/send" -Method Post -Headers @{ 'x-token' = $cfg.token } `
            -ContentType 'application/json' -Body $body -TimeoutSec 15 | Out-Null
        Registra 'aviso enviado no WhatsApp'
    }
} catch { Registra 'nao consegui avisar no WhatsApp' }
