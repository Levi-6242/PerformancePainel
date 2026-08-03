Fontes do PDF de strings
========================

O gerador de PDF (api_spv_pdf no app.py) registra QUALQUER .ttf/.otf desta pasta
no matplotlib e prefere, nesta ordem: Poppins -> Satoshi -> fallback (DejaVu Sans).

PARA USAR POPPINS, dropar aqui (de preferência os pesos estáticos):
  - Poppins-Regular.ttf
  - Poppins-Bold.ttf

Por que os dois: o PDF usa negrito em títulos/observações e o matplotlib não
sintetiza bem o negrito de fontes customizadas — precisa do arquivo Bold separado.

Onde baixar (licença OFL, grátis p/ uso comercial):
  https://fonts.google.com/specimen/Poppins
  https://github.com/google/fonts/tree/main/ofl/poppins

Depois de colocar os arquivos aqui, é só gerar o PDF de novo (o servidor relê a
pasta a cada PDF).
