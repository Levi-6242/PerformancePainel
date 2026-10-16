# Dashboard Thopen: login por pessoa, contas no Nexus (14/10/2026)

**Pedido.** Levi, 14/10/2026: "É possível implementarmos uma visão de login e senha para o dashboard thopen?". Decisões:
contas **por pessoa, ligada a um cliente** (cada uma vê só as carteiras dela); administradas **no Nexus, em Contratos e
clientes**; o dashboard sobe **no servidor da T.I.**, em `https://app.gridco.com.br/performance/` (entrada em
`/performance/login`). Desenho aprovado ("fora isso pode seguir!").

**Por quê.** Hoje o 5080 é público: quem tem o link vê as quatro carteiras (Thopen, Copel, Matrix, Polaris) e grava os
Comentários adicionais (o POST não pede nada).

## Princípios

- **Nenhum segredo compartilhado entre os dois sistemas.** O 5080 tem um par X25519 próprio: a privada fica só no
  servidor do 5080 (`THOPEN_ACESSOS_CHAVE_PRIVADA`); o Nexus conhece a pública (`NEXUS_ACESSOS_5080_PUBLICA`, pela tela
  Chaves do Nexus). É o espelho das contestações (lá o Nexus tem a privada e o 5080 a pública).
- **O banco tem leitura aberta** (nexus/dados/CLAUDE.md, regra 8): nome, e-mail e hash de senha só cifrados.
- **Um livro por sistema que grava** (cada um troca o seu livro inteiro, sob trava, relido antes e conferido depois):
  o Nexus grava as contas, o 5080 grava as senhas. Nenhum sobrescreve o do outro.
- **Desligável**: `THOPEN_LOGIN=1` liga. Sem ela, o 5080 segue público como hoje (sobe o código antes das contas).

## Dados

`nexus_acessos_clientes` · `dim_conta_cliente` — o Nexus grava (registrado em `catalogo.LIVROS` antes da 1ª gravação). 1 linha =
1 conta, o estado atual: `conta_id`, `carteiras` (`Thopen;Polaris`), `papel` (`cliente` | `grid`), `status` (`ativa` |
`desativada`), `convite_hash` (sha256 do link de uso único), `convite_expira` (UTC), `criada_em`, `alterada_em`,
`alterada_por_hmac`, `dados_5080` (nome e e-mail selados para a pública do 5080: X25519 + HKDF + AES-GCM, `cx1:`, presos
à conta) e `dados_nexus` (os mesmos, no Cofre do Nexus, para a tela dele).

`thopen_acessos` · `senhas` — o 5080 grava (declarado em `catalogo.CONHECIDAS`, controle). 1 linha = 1 senha definida:
`id`, `conta_id`, `definida_em`, `convite_hash` (o link usado: uso único), `senha_cifrada` (o hash scrypt da senha,
cifrado com AES-GCM numa chave derivada da privada do 5080, preso à linha). Vale a mais nova da conta.

## Nexus — Contratos e clientes → Acessos dos clientes

Só administrador age (`session["admin"]`); a tela lista as contas (nome, e-mail, carteiras, papel, situação, senha
definida em, link pendente até). Ações: **nova conta** (nome, e-mail, carteiras, papel) — já gera o link; **gerar link**
(nova senha ou senha esquecida; o anterior deixa de valer); **desativar / reativar**. O link aparece uma vez, com botão de
copiar, para mandar pelo Teams ou WhatsApp (o e-mail do servidor está barrado no tenant): `…/performance/convite/<token>`,
uso único, 72 h. Sem a pública do 5080, a tela avisa e não cria conta.

## 5080

- **Caminho**: `THOPEN_PREFIXO=/performance` (o app funciona com o Caddy tirando ou não o prefixo); todas as chamadas da
  tela saem relativas à raiz do app (`RAIZ + '/api/t/…'`). Cookie próprio: `thopen_sessao`, caminho do prefixo, Secure,
  HttpOnly, SameSite=Lax, 12 h (não colide com o `session` da plataforma nem o `nexus_sessao`).
- **Entrar** (`/login`): e-mail e senha; 5 erros por conta ou por endereço em 15 min = espera de 15 min. **Convite**
  (`/convite/<token>`): link válido → definir senha (mínimo 10 caracteres, repetida) → grava a linha em
  `thopen_acessos` → entra. **Sair** (`/logout`).
- **Portão**: com `THOPEN_LOGIN=1`, tudo pede sessão (menos entrar, convite, sair e os estáticos); a API responde 401 e a
  página vai para `/login`. A conta é relida a cada 2 min: desativada no Nexus = fora em até 2 min.
- **O que cada um vê**: só as usinas das carteiras da conta (lista, visão geral, mensal, diário, operação, rondas, fotos,
  PDF Carteira, contestação); usina fora = 403. Papel `grid`: todas as carteiras, e só ele grava os Comentários
  adicionais e força o "Atualizar".
- **Contestação**: nome e contato vêm da conta.

## Erros previstos

Banco fora no login: as contas lidas por último valem (cache em disco cifrado não — só memória; 5080 recém-subido sem
banco = ninguém entra, e a tela diz). Leitura parcial do livro de senhas nunca regrava (a mesma trava das contestações).
Link vencido, usado ou de conta desativada: a tela diz qual e pede um novo à Grid Co. Chave privada ausente com
`THOPEN_LOGIN=1`: ninguém entra e a tela diz "login não configurado" (nunca abre sem senha).

## Entrega

1. Nexus (contas, links, chave pública na tela Chaves, catálogo). 2. 5080 (caminho, entrar, convite, portão, carteiras,
`THOPEN_LOGIN`). 3. Ponta a ponta no link de teste: conta TESTE no Nexus → link → senha → entra vendo só a carteira →
desativar → sai em 2 min. 4. Deploy da T.I. (serviço do 5080 e o Caddy em `/performance`), com o roteiro.
