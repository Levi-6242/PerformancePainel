# gemeo/deploy/instalar_tarefas.ps1
# Cria (ou recria) as tres tarefas agendadas do Gemeo Digital no Windows da T.I.
# ASCII puro de proposito: o PowerShell 5.1 le .ps1 sem BOM como ANSI e um acento vira erro de parse.
# Uso (PowerShell como administrador, na pasta deploy):
#   .\instalar_tarefas.ps1 -Raiz "C:\gemeo" -Python "C:\Python312\pythonw.exe" -SecretsDir "C:\gemeo-secrets"
# -Python precisa ser o caminho REAL do pythonw.exe (o alias da Microsoft Store nao roda em tarefa agendada).
#
# -SemAdmin: PC de uso (sem elevacao), como o do Levi em 03/09/2026. Nesse PC tudo que o usuario sobe a mao morre
# no logoff - foi assim que ingest, app e modelar sumiram junto com a plataforma na noite de 03/09. Com -SemAdmin
# a tarefa nao pede RunLevel Highest, sobe no LOGON e um gatilho de 5 min faz de guardiao (IgnoreNew nao duplica
# quando ja esta rodando), e a acao passa por um .vbs para nao piscar console na tela (mesmo truque do
# plataforma\tunel_guardian_oculto.vbs).
#
# Caminhos com acento ("Area de Trabalho" no OneDrive): o .cmd e lido pelo cmd.exe na pagina de codigo OEM e o
# Set-Content -Encoding Ascii trocava o acento por "?" (primeira tentativa em 03/09 gerou "?rea de Trabalho" e a
# tarefa nem achava a pasta). Por isso os wrappers usam o nome curto 8.3 da pasta (100% ASCII) sempre que o caminho
# tem algo fora do ASCII.
#
# -Banco: caminho do gemeo.sqlite, gravado no wrapper como GEMEO_DB_CAMINHO. Sem isso o gemeo cai no padrao
# %LOCALAPPDATA%\GridCo\gemeo, e dentro de tarefa agendada essa variavel pode nao existir: em 03/09 as tarefas
# abriram um banco VAZIO em outro lugar ("no such table: usina") enquanto o banco de verdade ficava intocado.
param(
  [string]$Raiz = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
  [string]$Python = "",
  [string]$SecretsDir = "",
  [string]$Banco = (Join-Path $env:LOCALAPPDATA "GridCo\gemeo\gemeo.sqlite"),
  [string]$Usuario = "$env:USERDOMAIN\$env:USERNAME",
  [switch]$SemAdmin
)
$ErrorActionPreference = "Stop"
if (-not $Python) { $Python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source }
if (-not $Python) { throw "Informe -Python com o caminho REAL do pythonw.exe." }
if (-not $SecretsDir) { $SecretsDir = Join-Path $Raiz "secrets" }
if (-not (Test-Path (Join-Path $SecretsDir "gemeo.env"))) { throw ("Nao achei " + (Join-Path $SecretsDir "gemeo.env") + " - crie os segredos antes (ver deploy\README.md).") }
if (-not (Test-Path (Split-Path -Parent $Banco))) { New-Item -ItemType Directory -Force (Split-Path -Parent $Banco) | Out-Null }
$Logs = Join-Path $Raiz "logs"
New-Item -ItemType Directory -Force $Logs | Out-Null
$Cmds = Join-Path $Raiz "deploy\cmd"
New-Item -ItemType Directory -Force $Cmds | Out-Null

$fso = New-Object -ComObject Scripting.FileSystemObject
function PastaAscii($p) {
  # Nome curto 8.3 quando ha acento; se o Windows nao gerar nome curto (8.3 desligado no volume), avisa em vez de gravar lixo.
  if ($p -notmatch '[^\x00-\x7F]') { return $p }
  $curto = $fso.GetFolder($p).ShortPath
  if ($curto -match '[^\x00-\x7F]') { throw ("A pasta " + $p + " tem acento e o volume nao gera nome curto 8.3 - mova o projeto para um caminho ASCII (ex.: C:\gemeo).") }
  return $curto
}
function ArquivoAscii($p) {
  if ($p -notmatch '[^\x00-\x7F]') { return $p }
  return (Join-Path (PastaAscii (Split-Path -Parent $p)) (Split-Path -Leaf $p))
}
$RaizA = PastaAscii $Raiz
$SecretsA = PastaAscii $SecretsDir
$PythonA = ArquivoAscii $Python
$BancoA = ArquivoAscii $Banco
$LogsA = Join-Path $RaizA "logs"

function Wrapper($Comando) {
  # Um .cmd por tarefa: ambiente, pasta e log num lugar so - e o que se abre para depurar as 23h.
  $arq = Join-Path $Cmds ("gemeo_" + $Comando + ".cmd")
  $arqA = Join-Path (PastaAscii $Cmds) ("gemeo_" + $Comando + ".cmd")
  $linhas = @(
    "@echo off",
    ("set SECRETS_DIR=" + $SecretsA),
    ("set GEMEO_CONFIG=" + (Join-Path $RaizA "config.toml")),
    ("set GEMEO_DB_CAMINHO=" + $BancoA),
    ("cd /d """ + $RaizA + """"),
    ("""" + $PythonA + """ -m gemeo.cli " + $Comando + " >> """ + (Join-Path $LogsA ($Comando + ".log")) + """ 2>&1")
  )
  foreach ($l in $linhas) { if ($l -match '[^\x00-\x7F]') { throw ("Linha fora do ASCII no wrapper: " + $l) } }
  Set-Content -Path $arq -Value $linhas -Encoding Ascii
  if (-not $SemAdmin) { return @{ Exe = $arq; Args = $null } }
  # Sessao interativa: o cmd.exe abriria (e manteria) um console na tela. O wscript roda o .cmd oculto e espera.
  $vbs = Join-Path $Cmds ("gemeo_" + $Comando + ".vbs")
  $lv = @(
    "Option Explicit",
    "Dim sh",
    "Set sh = CreateObject(""WScript.Shell"")",
    ("WScript.Quit sh.Run(""cmd.exe /c """""" & """ + $arqA + """ & """""""", 0, True)")
  )
  Set-Content -Path $vbs -Value $lv -Encoding Ascii
  return @{ Exe = "wscript.exe"; Args = ("""" + $vbs + """") }
}

function Registrar($Nome, $Comando, $Gatilho, $Reinicia) {
  $w = Wrapper $Comando
  if ($w.Args) { $acao = New-ScheduledTaskAction -Execute $w.Exe -Argument $w.Args } else { $acao = New-ScheduledTaskAction -Execute $w.Exe }
  if ($Reinicia) {
    $cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
  } else {
    $cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 14) -MultipleInstances IgnoreNew
  }
  Unregister-ScheduledTask -TaskName $Nome -Confirm:$false -ErrorAction SilentlyContinue
  if ($SemAdmin) {
    Register-ScheduledTask -TaskName $Nome -Action $acao -Trigger $Gatilho -Settings $cfg -User $Usuario | Out-Null
  } else {
    Register-ScheduledTask -TaskName $Nome -Action $acao -Trigger $Gatilho -Settings $cfg -User $Usuario -RunLevel Highest | Out-Null
  }
  Write-Host ("tarefa registrada: " + $Nome)
}

$dezAnos = New-TimeSpan -Days 3650
$cada15 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration $dezAnos
if ($SemAdmin) {
  $continuo = @((New-ScheduledTaskTrigger -AtLogOn -User $Usuario),
                (New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration $dezAnos))
} else {
  $continuo = New-ScheduledTaskTrigger -AtStartup
}
Registrar "Gemeo Ingest" "ingest" $continuo $true
Registrar "Gemeo App" "app" $continuo $true
Registrar "Gemeo Modelar" "modelar" $cada15 $false
Write-Host ("banco das tarefas: " + $Banco)
Write-Host "Pronto. Para iniciar agora: Start-ScheduledTask 'Gemeo Ingest'; Start-ScheduledTask 'Gemeo App'; Start-ScheduledTask 'Gemeo Modelar'"
