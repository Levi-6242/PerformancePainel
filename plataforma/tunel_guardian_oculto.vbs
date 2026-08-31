' Lancador SILENCIOSO do guardiao do tunel da plataforma (porta 5050).
'
' Por que existe (25/08): a tarefa "GridCo Tunel Guardian" chamava powershell.exe direto, a cada
' 5 minutos, SEM janela oculta - um console piscava na tela do Levi a cada execucao ("fica
' pulando uns prompts"). Mesmo -WindowStyle Hidden nao resolve: com LogonType=Interactive o
' Windows cria o console ANTES de o parametro fazer efeito. O wscript nao cria janela nenhuma.
' Mesmo padrao do C:\GridcoAuto\agente_publicar_oculto.vbs.
'
' Para voltar atras: aponte a acao da tarefa de novo para
'   powershell -NoProfile -ExecutionPolicy Bypass -File "<esta pasta>\tunel_guardian.ps1"
Option Explicit
Dim sh, cmd, pasta
Set sh = CreateObject("WScript.Shell")
pasta = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & pasta & "tunel_guardian.ps1"""
' 0 = janela oculta ; True = espera terminar, para o resultado da tarefa refletir o do script
WScript.Quit sh.Run(cmd, 0, True)
