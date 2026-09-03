# Independência da Plataforma — PC próprio, sem OneDrive

Requisito (Levi, 02/09/2026): **PC dedicado, pode gravar JSON em disco, não pode ter contato com
o OneDrive.** Medido no código e no sistema em execução, não de memória.

---

## Resposta curta

**A restrição já está atendida** — e por dois caminhos independentes, um deles ativo agora.

O que o levantamento anterior listava como pendência (as 11 leituras por caminho, o espelho em
disco, os 50 MB de JSON) **não era dependência de OneDrive**. Era dependência de *arquivo local* —
que, com PC próprio e JSON liberado, é o desenho pretendido, não um problema.

---

## O que já garante o "sem OneDrive"

### Alimentação 1 — `bd_api`: a plataforma PUXA da API  ← ativo

As três bases vêm da Gridco Performance API e são materializadas em `plataforma/bases/`.
Estado real do espelho agora:

| Base | Sincronizada em |
|---|---|
| `bd_performance` | 02/09 14:51 |
| `bd_thopen` | 02/09 14:26 |
| `tickets_performance` | 30/08 01:42 |

O `_bd_api_sync.json` foi tocado hoje às **16:02**. É esta a alimentação viva.

### Alimentação 2 — `push_bases.py`: a máquina do analista EMPURRA por HTTPS

Existe e foi escrita para exatamente este requisito. O próprio cabeçalho do arquivo diz por quê:

> o servidor **NÃO monta OneDrive** — ele recebe as três planilhas por HTTPS, atrás da mesma senha
> do dashboard. Sincronizar OneDrive numa máquina exposta é o que queremos evitar: se ela for
> comprometida, o invasor alcança as bases da empresa e o ransomware sobe para a nuvem junto.

Roda na máquina que **tem** o OneDrive, pelo Agendador. Último uso: 25/07 — foi substituída pelo
`bd_api`, mas continua disponível como plano B.

### A plataforma não escreve nada no OneDrive

Varredura de `.save()` / `to_excel()` / escrita de arquivo cruzada com caminho de nuvem:
**nenhuma ocorrência**. Os `save()` que existem são exportação de Excel para o usuário baixar.

### O acoplamento com o Thopen está limpo

`thopen/dashboard_thopen.py` já registra que o servidor de produção roda sem OneDrive e que um
fallback para arquivo lá seria armadilha. Desde 28/08 ele lê do PostgreSQL.

---

## O que REALMENTE falta — três itens

### 1. A pasta dos CSVs do 2C (`OWEN_ROOT`)

**É o único caminho de runtime que hoje cai dentro do OneDrive.** A lista de candidatos em
`app.py` resolve, nesta máquina, para `...\temp\Projetos e-mail` — irmã do projeto, dentro da
nuvem.

No PC novo não há OneDrive, então: a tarefa **"2C - Baixar E-mails GridCo"** precisa rodar lá
também, gravando numa pasta local, e `OWEN_ROOT` aponta para ela. A variável de ambiente já é o
primeiro candidato da lista — **é configuração, não mudança de código.**

### 2. Tirar a pasta do projeto de dentro do OneDrive

Hoje o repositório inteiro está em `OneDrive - GRID CO\Área de Trabalho\temp\`. Ou seja: os 50 MB
de estado em JSON estão sincronizando na nuvem agora.

A boa notícia é que a mudança é uma **mudança de lugar, não de código**. Tudo resolve por `_AQUI`
e `_RAIZ`, então o estado viaja junto com a pasta. Os únicos caminhos absolutos no runtime são os
do `C:\GridcoWhats` — que já estão fora do OneDrive. (Há um caminho fixo em
`trk_regua_v2.py:592`, mas está dentro de `if __name__ == "__main__"`: é o banco de fixtures de
teste, não roda no servidor.)

### 3. Os segredos vão à mão

`.env` e `tokens.txt` ficam no `_RAIZ`. Viajam com a pasta, mas devem ser **copiados
manualmente** — nunca por sincronização.

---

## Some da lista de pendências

| Item do levantamento anterior | Por quê |
|---|---|
| 11 leituras por caminho de arquivo | leem do espelho `bases/`, que a **API** enche — não é OneDrive |
| Espelho `bases/*.xlsx` em disco | é o desenho pretendido, não um resíduo |
| 50 MB de estado em JSON | liberado; e é 58× mais rápido que ida e volta ao PG |
| "A máquina" | vira mudança de lugar, não eliminação |

---

## Continua valendo (independe do OneDrive)

- **Chip do WhatsApp** — a sessão do wwebjs vive num perfil local. É a dor real da mudança de PC.
- **Log no laço de backup** — `_estado_backup_loop` não escreve log; com `pythonw` (sem console),
  só dá para saber se rodou perguntando ao banco. Exige restart.
- **`restaurar_se_vazio()`** só age com disco vazio. Backup antigo restaurado = disco cheio e
  velho, banco com o dado bom, ninguém consulta. Deveria comparar idade.
- **Túnel Cloudflare** — o link muda a cada queda; a T.I. definiu porta fixa no PC dedicado.

---

## Ordem sugerida

1. Definir a pasta do 2C no PC novo e apontar `OWEN_ROOT` — junto com a tarefa de baixar e-mails.
2. Mover o projeto para fora do OneDrive (ex.: `C:\GridcoPlataforma`), copiando `.env` e
   `tokens.txt` à mão.
3. Recriar as tarefas agendadas e o túnel na porta que a T.I. definiu.
4. Migrar o chip do WhatsApp — o item que exige presença.
5. Log no laço de backup e a correção do `restaurar_se_vazio`, no primeiro restart.
