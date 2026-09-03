# gemeo/deploy/instalar_tarefas.ps1
# Cria (ou recria) as tres tarefas agendadas do Gemeo Digital no Windows da T.I.
# ASCII puro de proposito: o PowerShell 5.1 le .ps1 sem BOM como ANSI e um acento vira erro de parse.
# Uso (PowerShell como administrador, na pasta deploy):
#   .\instalar_tarefas.ps1 -Raiz "C:\gemeo" -Python "C:\Python312\pythonw.exe" -SecretsDir "C:\gemeo-secrets"
# -Python precisa ser o caminho REAL do pythonw.exe (o alias da Microsoft Store nao roda em tarefa agendada).
param(
  [string]$Raiz = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
  [string]$Python = "",
  [string]$SecretsDir = "",
  [string]$Usuario = "$env:USERDOMAIN\$env:USERNAME"
)
$ErrorActionPreference = "Stop"
if (-not $Python) { $Python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source }
if (-not $Python) { throw "Informe -Python com o caminho REAL do pythonw.exe." }
if (-not $SecretsDir) { $SecretsDir = Join-Path $Raiz "secrets" }
if (-not (Test-Path (Join-Path $SecretsDir "gemeo.env"))) { throw ("Nao achei " + (Join-Path $SecretsDir "gemeo.env") + " - crie os segredos antes (ver deploy\README.md).") }
$Logs = Join-Path $Raiz "logs"
New-Item -ItemType Directory -Force $Logs | Out-Null
$Cmds = Join-Path $Raiz "deploy\cmd"
New-Item -ItemType Directory -Force $Cmds | Out-Null

function Wrapper($Comando) {
  # Um .cmd por tarefa: ambiente, pasta e log num lugar so - e o que se abre para depurar as 23h.
  $arq = Join-Path $Cmds ("gemeo_" + $Comando + ".cmd")
  $linhas = @(
    "@echo off",
    ("set SECRETS_DIR=" + $SecretsDir),
    ("set GEMEO_CONFIG=" + (Join-Path $Raiz "config.toml")),
    ("cd /d """ + $Raiz + """"),
    ("""" + $Python + """ -m gemeo.cli " + $Comando + " >> """ + (Join-Path $Logs ($Comando + ".log")) + """ 2>&1")
  )
  Set-Content -Path $arq -Value $linhas -Encoding Ascii
  return $arq
}

function Registrar($Nome, $Comando, $Gatilho, $Reinicia) {
  $acao = New-ScheduledTaskAction -Execute (Wrapper $Comando)
  if ($Reinicia) {
    $cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
  } else {
    $cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 14) -MultipleInstances IgnoreNew
  }
  Unregister-ScheduledTask -TaskName $Nome -Confirm:$false -ErrorAction SilentlyContinue
  Register-ScheduledTask -TaskName $Nome -Action $acao -Trigger $Gatilho -Settings $cfg -User $Usuario -RunLevel Highest | Out-Null
  Write-Host ("tarefa registrada: " + $Nome)
}

$noBoot = New-ScheduledTaskTrigger -AtStartup
$cada15 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration ([TimeSpan]::MaxValue)
Registrar "Gemeo Ingest" "ingest" $noBoot $true
Registrar "Gemeo App" "app" $noBoot $true
Registrar "Gemeo Modelar" "modelar" $cada15 $false
Write-Host "Pronto. Para iniciar agora: Start-ScheduledTask 'Gemeo Ingest'; Start-ScheduledTask 'Gemeo App'; Start-ScheduledTask 'Gemeo Modelar'"
