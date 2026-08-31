# Runbook — túnel Cloudflare NOMEADO (endereço estável da plataforma)

**Rota A** (decisão do Levi, 06/08): túnel nomeado num **domínio da Grid via T.I.** — sem domínio
fora da marca. (O programador preferia B pra não depender do T.I.; B fica documentada como plano
de contingência se a rota A emperrar — a mecânica é idêntica, só muda o dono do domínio.)

## O que o programador precisa receber no fim
1. A **origem**: `https://perf.gridco.com.br` (ou o nome que o T.I. definir) — sem `/api`.
2. **De quem é o domínio** — resposta da rota A: "da Grid, sem data de saída". A melhor possível.

---

## Fase 1 — humana (T.I. + Levi): zona DNS + autorização (uma vez só)

1. **T.I.: o domínio da Grid numa conta Cloudflare.** Dois jeitos:
   - **Zona na Cloudflare** — adicionar `gridco.com.br` (ou um domínio da Grid dedicado a
     aplicações) numa conta Cloudflare (plano Free basta) e apontar os nameservers no registrador.
     É o caminho padrão; o DNS continua sendo do T.I., só muda onde ele é servido.
   - Se mover a zona for inviável pro T.I., registrar **um domínio da Grid específico de apps**
     (ex.: `gridco.app`) direto na Cloudflare resolve igual — segue sendo da empresa.
2. **Autorizar o túnel na conta:** no PC da plataforma, rodar `cloudflared tunnel login` com o
   login da conta Cloudflare do passo 1 (o T.I. digita a senha dele — não precisa compartilhá-la;
   basta estar junto ou por acesso remoto). Grava o `cert.pem` em `%USERPROFILE%\.cloudflared\`.
   **Fim da parte humana.**

## Fase 2 — execução (Claude faz, ~15 min)

4. Criar o túnel com identidade fixa:
   `cloudflared tunnel create gridco-perf` → gera UUID + credencial JSON (o arquivo que "viaja"
   na migração de máquina).
5. `%USERPROFILE%\.cloudflared\config.yml`:

```yaml
tunnel: <UUID>
credentials-file: C:\Users\Levi Maia\.cloudflared\<UUID>.json
ingress:
  - hostname: perf.<dominio>
    service: http://localhost:5050
  - service: http_status:404
```

   (Opcional: segunda entrada `cliente.<dominio>` → `http://localhost:5080` pro dashboard Thopen
   ganhar endereço fixo também.)
6. Apontar o DNS: `cloudflared tunnel route dns gridco-perf perf.<dominio>`.
7. Instalar como **serviço do Windows** (sobe no boot, reconecta sozinho):
   `cloudflared service install` → iniciar o serviço.
8. Smoke: `https://perf.<dominio>/healthz` → 200; `/api/campo/ronda?usina=TIM100` com a
   `x-api-key` → 200. (O quick tunnel antigo pode continuar até o novo provar; depois desligar.)
9. Entregar ao programador: a origem + o dono do domínio (+ data de saída se pessoal). Ele roda o
   `/perf/diag` em Ibaté 1 e Ceilândia 2 e liga o `PERF_PULL_ATIVO=1`.

## Migração futura (B → A, quando o T.I. der a zona da Grid)
- Nosso lado: `cloudflared tunnel route dns gridco-perf perf.gridco.com.br` (mesma identidade).
- Lado dele: trocar o App Setting `PERF_API_BASE`. Só isso.

## Notas
- Nenhuma porta aberta no firewall — o serviço conecta de dentro pra fora (mesma postura do quick).
- Segurança do app não muda: dashboard atrás da `DASH_PASSWORD`; `/api/campo/*` atrás da `x-api-key`.
- Bônus: a URL fixa destrava o login Microsoft (Entra SSO), que pedia exatamente isso.
