@echo off
REM ============================================================================
REM  TESTE do deep link  gridos://  ->  OS Creator  (Fatia 2)
REM  Simula o botao "Criar OS" da Plataforma de Performance.
REM
REM  ESPERADO ao rodar: o OS Creator abre na aba "Criar OS", no plano
REM  "Recomposicao de String", com o INVERSOR marcado e a OBSERVACAO preenchida.
REM  (Se pedir login, faca o login normal do Fracttal — a sugestao aplica depois.)
REM
REM  EDITE so os valores de  usina=  e  ativo=  abaixo, trocando por uma
REM  usina/inversor que voce SABE que tem o plano de Recomposicao de String.
REM  NAO remova as aspas nem os "&".
REM ============================================================================
cd /d "%~dp0"
"C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\python.exe" main.py "gridos://performance?usina=Cedro Rosa&ativo=Inversor 1.1&obs=Strings 1.1.7 e 1.1.9 com corrente nula, verificar e normalizar&template=recomposicao&origem=teste"
if errorlevel 1 pause
