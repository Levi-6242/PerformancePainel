# Renovar o token da PV Plataforma automaticamente

O token dos **Trackers / Curva de strings** vem da PV Plataforma (`plataforma.pvoperation.com`).
É um JWT de sessão que **vence a cada ~7 dias**. A Plataforma **não tem endpoint de refresh** e o
login exige **CAPTCHA (Cloudflare Turnstile) + MFA por e-mail** — ou seja, **ninguém consegue mintar
um token novo sem um humano passar pelo login**. O que dá pra automatizar é a **captura e o envio**
do token pro dashboard, sem copiar e colar.

Como funciona: um **userscript** roda dentro da Plataforma e, sempre que a página está aberta,
pega o header `x-auth-token-update` que o próprio site já usa e o envia para o dashboard
(`http://localhost:5050/api/pv/trackers/token`). O dashboard grava na chave `plat` do `plataforma/tokens_runtime.json` e recarrega.

## Instalação (uma vez só, na máquina do dashboard)

1. Instale a extensão **Tampermonkey** no Chrome/Edge (loja de extensões — grátis).
2. Abra o painel do Tampermonkey → **Criar novo script** → apague o conteúdo padrão.
3. Cole o conteúdo de **`plat_token_autocapture.user.js`** (raiz do projeto) → **Salvar** (Ctrl+S).
4. **Chave (desde 10/10/2026):** abra `/tokens` no dashboard (logado), clique em **Mostrar chave** → **Copiar** e cole
   no campo `chave` do destino desse endereço, em `DESTINOS`, no topo do script → **Salvar**. Sem ela o servidor
   responde 401 e o aviso diz "chave recusada". A chave fica só na cópia do Tampermonkey — **nunca** commite o
   arquivo com ela preenchida (o repositório é público). Instalação local sem senha não pede chave.
5. Abra/atualize `https://plataforma.pvoperation.com` e faça login normalmente.
   - No canto inferior direito aparece um aviso discreto: **"GridCo: token enviado ao dashboard"**.
   - A partir daí, toda vez que a Plataforma estiver aberta o token é reenviado sozinho (sem clique).

## Para ficar o mais "automático" possível

- **Deixe uma aba da Plataforma fixada (pinada)** no navegador da máquina do dashboard, logada.
  Enquanto ela estiver aberta, o token é capturado continuamente e renovado sem nenhuma ação.
- Quando o token vencer (a cada ~7 dias), essa aba vai pedir login. Faça o login (CAPTCHA + MFA) **uma vez**
  — o userscript captura o token novo na hora. Esse é o único passo manual que **não tem como eliminar**
  (é a própria proteção da Plataforma).
- Se o MFA tiver "lembrar deste dispositivo", o relogin fica quase invisível.

## Conferir / diagnosticar

- Status do token: `GET http://localhost:5050/api/tokens` → procure a linha **"plat"** (status `ok` + validade).
- Se a aba Trackers zerar (0 usinas / 0 parados), o token venceu → abra a Plataforma e relogue.
- Outra máquina? Acrescente um destino em `DESTINOS`, no topo do userscript, com a URL e a chave do `/tokens`
  daquele endereço (cada instalação tem a sua chave).
- "chave recusada" no aviso: a chave do script não é a do servidor (ou foi trocada) — copie de novo em `/tokens`.

## Plano B (manual, se a extensão não estiver disponível)

- Bookmarklet de 1 clique (versão antiga) ou: F12 na Plataforma → aba Network → qualquer chamada →
  header `x-auth-token-update` → copiar o valor → colar na chave `"plat"` do
  `plataforma/tokens_runtime.json` (vale na hora, sem reiniciar) ou em `PLAT_TOKEN` no `tokens.txt`
  (aí sim precisa reiniciar).
