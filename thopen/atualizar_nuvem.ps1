# Atualiza os dados do dashboard Thopen na nuvem (Railway):
# recopia as planilhas do OneDrive para data/, comita e envia pro GitHub.
# O Railway re-publica sozinho em ~2-3 min. NAO altera codigo, so os dados.
$ErrorActionPreference = "Stop"
$proj = $PSScriptRoot
Set-Location $proj
$base = "C:\Users\Levi Maia\OneDrive - GRID CO\Grid Co_ - 17. Acesso Externo Thopen"

Write-Host ""
Write-Host "==  ATUALIZAR DADOS DO DASHBOARD NA NUVEM  ==" -ForegroundColor Cyan
Write-Host ""

# Garante que estamos na main atualizada. Descarta copias locais pendentes de data/
# (serao recopiadas abaixo) para o checkout nao travar. NAO mexe em codigo.
git checkout -- data/ 2>$null
$sw = git checkout main 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host "Nao consegui trocar para a branch main:" -ForegroundColor Yellow
  Write-Host $sw -ForegroundColor Yellow
  Write-Host "Chame o Claude para organizar o repositorio." -ForegroundColor Yellow
  Read-Host "Enter para fechar"; exit 1
}
git pull --ff-only 2>&1 | Out-Null

Write-Host "1/3  Recopiando as planilhas do OneDrive..." -ForegroundColor Gray
Copy-Item "$base\1. Registro usinas Thopen\BD_Thopen.xlsx" "$proj\data\BD_Thopen.xlsx" -Force
Copy-Item "$base\6. Matrix\Geração Matrix.xlsx"           "$proj\data\Matrix\Geração Matrix.xlsx" -Force
Copy-Item "$base\5. Copel\Geração Copel.xlsx"             "$proj\data\Copel\Geração Copel.xlsx" -Force
Copy-Item "$base\3. Polaris\Comentários Polaris.xlsx"     "$proj\data\Polaris\Comentários Polaris.xlsx" -Force
# Budget Polaris: mantem so o mais recente
Get-ChildItem "$proj\data\Polaris\Budget_2025_UFVs_Raizen*.xlsx" -ErrorAction SilentlyContinue | Remove-Item -Force
$bud = Get-ChildItem "$base\3. Polaris\Budget_2025_UFVs_Raizen*.xlsx" | Where-Object { -not $_.Name.StartsWith('~') } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item $bud.FullName "$proj\data\Polaris\$($bud.Name)" -Force

Write-Host "2/3  Verificando o que mudou..." -ForegroundColor Gray
git add data/
if (-not (git status --short data/)) {
  Write-Host ""
  Write-Host "Nada novo: a nuvem ja esta com os dados atuais do seu OneDrive." -ForegroundColor Green
  Read-Host "Enter para fechar"; exit 0
}

Write-Host "3/3  Enviando pro GitHub..." -ForegroundColor Gray
git commit -m "chore(data): atualiza snapshot das planilhas ($(Get-Date -Format 'dd/MM HH:mm'))" | Out-Null
git push

Write-Host ""
Write-Host "PRONTO! Enviado. O Railway vai re-publicar o link em ~2-3 minutos." -ForegroundColor Green
Write-Host "Depois disso, de Ctrl+F5 no link do cliente para ver os dados novos." -ForegroundColor Green
Write-Host ""
Read-Host "Enter para fechar"
