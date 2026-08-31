# tunel_guardian.ps1 - mantem o tunel da PLATAFORMA (porta 5050) vivo.
#
# ASCII PURO DE PROPOSITO: o PowerShell 5.1 le arquivo .ps1 como ANSI, nao UTF-8. Um travessao
# ou acento vira byte solto e o parser quebra a string ("A cadeia de caracteres nao tem o
# terminador") em uma linha que nem e a culpada. Nao escreva acento aqui.
#
# POR QUE EXISTE
# Em 11/08/2026 o tunel da 5050 caiu quatro vezes num dia. O log nao mostra queda de rede:
# mostra "Initiating graceful shutdown due to signal terminated" - alguem MATA o processo.
# O suspeito e o embrulho `cmd.exe /c` usado para redirecionar o log: quando a arvore dele
# morre, o cloudflared vai junto. Enquanto a causa nao e fechada (ou o named tunnel entra),
# este guardiao ressuscita o tunel e avisa a URL nova.
#
# REGRA DE OURO (ja custou caro): NUNCA matar todos os cloudflared. O da 5080 e o dashboard
# do CLIENTE e nao pode cair. Este script so olha e so mexe no que serve localhost:5050.
#
# COMO RODAR (Tarefa Agendada, a cada 5 min, mesmo padrao do ronda_guardian):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "<esta pasta>\tunel_guardian.ps1"
$ErrorActionPreference = 'SilentlyContinue'
$dir  = $PSScriptRoot
$log  = Join-Path $dir 'cloudflared_5050.log'
$urlf = Join-Path $dir 'tunnel_url.txt'
$hist = Join-Path $dir 'tunel_guardian.log'

function Registra($m) { Add-Content -Path $hist -Value ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) }

# 1) Ja existe cloudflared servindo a 5050? (filtro pela PORTA, nunca pelo nome do processo)
$vivo = @(Get-CimInstance Win32_Process |
          Where-Object { $_.Name -like 'cloudflared*' -and $_.CommandLine -like '*localhost:5050*' })

# 1b) PROCESSO VIVO NAO E TUNEL VIVO. Falha real de 24/08: o Cloudflare expirou o quick tunnel do
# lado dele, o hostname virou NXDOMAIN, e o cloudflared local seguiu reconectando e logando
# "Registered tunnel connection" contra um nome que nao existe mais. Como o processo existia, o
# guardiao saia no exit 0 acima e NUNCA socorria - o link ficava fora o dia inteiro ate alguem
# reclamar. Entao: se tem processo, o hostname dele PRECISA resolver e responder. Tres tentativas
# antes de condenar, para um soluco de rede nao trocar um link que estava bom.
if ($vivo.Count -gt 0) {
    $urlLog = $null
    if (Test-Path $log) {
        $mm = [regex]::Matches([string](Get-Content $log -Raw), 'https://[a-z0-9-]+\.trycloudflare\.com')
        if ($mm.Count -gt 0) { $urlLog = $mm[$mm.Count - 1].Value }
    }
    if (-not $urlLog -and (Test-Path $urlf)) { $urlLog = (Get-Content $urlf -Raw).Trim() }
    if (-not $urlLog) { exit 0 }          # sem URL conhecida nao da para julgar; nao mexe

    $saudavel = $false
    foreach ($t in 1..3) {
        # Porta 5050 local FORA = quem caiu foi o APP (restart/deploy de codigo), nao o tunel.
        # Sem esta guarda, o guardiao condenava um cloudflared BOM que so estava publicando 502
        # enquanto o python reiniciava: as 3 tentativas falhavam, ele matava o processo e o link
        # trocava por causa de um deploy que cruzou com o ciclo dos 5 min. Regra do Levi (26/08):
        # alteracao de codigo NAO pode derrubar o link. App fora nao e problema do tunel - o
        # ronda_guardian sobe o app de volta e este guardiao reavalia no proximo ciclo, com o
        # MESMO link no ar.
        if (-not (Get-NetTCPConnection -LocalPort 5050 -State Listen)) {
            Registra 'porta 5050 local fora durante o teste da URL - e o app, nao o tunel; nao mexo'
            exit 0
        }
        if (Resolve-DnsName -Name ([uri]$urlLog).Host -Type A -ErrorAction SilentlyContinue) {
            try {
                $rr = Invoke-WebRequest -Uri ($urlLog + '/healthz') -TimeoutSec 20 -UseBasicParsing
                if ($rr.StatusCode -eq 200) { $saudavel = $true; break }
            } catch { }
        }
        Start-Sleep -Seconds 10
    }
    if ($saudavel) { exit 0 }

    Registra "tunel ZUMBI: processo vivo mas $urlLog nao responde - derrubando para subir outro"
    foreach ($z in $vivo) { Stop-Process -Id $z.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 3
}

# 2) A plataforma esta de pe? Sem ela o tunel so publicaria erro; melhor esperar o guardiao
#    do python subir o app primeiro.
if (-not (Get-NetTCPConnection -LocalPort 5050 -State Listen)) {
    Registra 'porta 5050 fechada - nao subi o tunel (o app ainda nao esta no ar)'
    exit 0
}

# 3) Sobe. Resolve o CAMINHO COMPLETO: guardar so o nome 'cloudflared' fazia o Test-Path abaixo
#    dar falso e o guardiao se declarar "nao encontrado" justamente quando o binario ESTAVA no
#    PATH (pego no teste de 11/08). --protocol http2 porque nesta rede o QUIC falha.
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) {
    $cf = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe"
}
if (-not (Test-Path $cf)) { Registra "cloudflared nao encontrado (tentei: $cf)"; exit 1 }
# ANTES de descartar o log, GUARDA A CAUSA DA MORTE. Em 25/08 o tunel caiu 3x e eu nao tinha
# como saber por que: "signal terminated" (alguem matou), "Tunnel not found" (o Cloudflare
# expirou) e queda de rede sao problemas DIFERENTES, com solucoes diferentes, e o log era
# sobrescrito antes de alguem ler. Agora cada ressurreicao registra a ultima linha relevante.
if (Test-Path $log) {
  $causa = (Select-String -Path $log -Pattern 'signal terminated|Tunnel not found|Unauthorized|no recent network activity|context canceled' -ErrorAction SilentlyContinue |
            Select-Object -Last 1).Line
  if ($causa) { Registra ('causa provavel da queda anterior: ' + $causa.Trim()) }
  else { Registra 'causa da queda anterior: nao identificada no log' }
  Move-Item $log "$log.anterior" -Force
}
# Start-Process OCULTO, sem cmd.exe no meio (25/08). O embrulho cmd via WMI tinha dois
# defeitos: abria um console VISIVEL quando o guardiao rodava na sessao interativa da
# tarefa, e criava a arvore fragil que o cabecalho deste script ja culpava pelas mortes
# por 'signal terminated'. O cloudflared escreve o log (e a URL) no STDERR - e dele que
# o passo 4 abaixo le; o stdout vai para um .out separado porque o Start-Process exige
# arquivos diferentes para os dois fluxos.
Start-Process -FilePath $cf -WindowStyle Hidden `
    -ArgumentList 'tunnel','--protocol','http2','--ha-connections','1','--edge-ip-version','4','--url','http://localhost:5050' `
    -RedirectStandardError $log -RedirectStandardOutput ($log + '.out')

# 4) Captura a URL do log
$url = $null
foreach ($i in 1..25) {
    Start-Sleep -Seconds 3
    $m = [regex]::Match([string](Get-Content $log -Raw), 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($m.Success) { $url = $m.Value; break }
}
if (-not $url) { Registra 'subi o cloudflared mas nao capturei a URL'; exit 1 }

# 5) CONFERE O DNS ANTES DE PUBLICAR. O log dizer "Registered tunnel connection" NAO garante
#    que o hostname exista: em 11/08 a borda deu tres i/o timeout, o tunel registrou e o nome
#    ficou NXDOMAIN nos dois resolvedores. O guardiao chegou a publicar e avisar no WhatsApp um
#    link MORTO. Link que nao resolve e pior que link nenhum: manda o time bater numa porta que
#    nao existe. Se nao resolver, derruba o proprio tunel e deixa o proximo ciclo tentar limpo.
$alvo = ([uri]$url).Host
$dns_ok = $false
foreach ($i in 1..12) {
    Start-Sleep -Seconds 5
    if (Resolve-DnsName -Name $alvo -Type A -ErrorAction SilentlyContinue) { $dns_ok = $true; break }
}
if (-not $dns_ok) {
    Registra "URL $url nao resolve no DNS (hostname nao provisionado); derrubei e vou tentar no proximo ciclo"
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -like 'cloudflared*' -and $_.CommandLine -like '*localhost:5050*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    exit 1
}

[System.IO.File]::WriteAllText($urlf, $url)
Registra "tunel caiu e foi RESSUSCITADO -> $url"

# 6) Avisa no WhatsApp (best-effort, mesmo canal do subir_tunel.ps1). Link novo so serve se
#    alguem souber dele.
try {
    $cfg = Get-Content (Join-Path $dir 'whats_ronda.json') -Raw | ConvertFrom-Json
    if ($cfg.service_url -and $cfg.token -and $cfg.confirmar_para) {
        $txt = "O tunel da plataforma caiu e subiu de novo. Link novo: $url  (senha de sempre)"
        $body = @{ para = "$($cfg.confirmar_para)"; texto = $txt } | ConvertTo-Json
        Invoke-RestMethod -Uri "$($cfg.service_url)/send" -Method Post -Headers @{ 'x-token' = $cfg.token } `
            -ContentType 'application/json' -Body $body -TimeoutSec 15 | Out-Null
        Registra 'aviso enviado no WhatsApp'
    }
} catch { Registra 'nao consegui avisar no WhatsApp' }
