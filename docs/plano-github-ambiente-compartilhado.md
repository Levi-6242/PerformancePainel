# Plano do GitHub e do ambiente compartilhado

Levantado em **31/08/2026** consultando o GitHub e os diretórios de trabalho — não é de memória.
Escrito para ser lido por uma sessão nova do Claude Code sem contexto anterior.

---

## 1. O que existe hoje

| O quê | Onde vive | Dono | Visibilidade | Quem enxerga |
|---|---|---|---|---|
| Plataforma 5050 + Dashboard Thopen 5080 + coletor legado + docs + testes | `Levi-6242/PerformancePainel` | **pessoal do Levi** | privado, 115 MB, criado 10/06/2026 | **só o Levi** |
| OS Creator — código-fonte | `Grid-Co-CODE/oem` | **organização** | privado | `admin-gridco`, `Levi-6242` |
| OS Creator — instaladores (auto-update) | `Grid-Co-CODE/oem-release` | **organização** | público | todos |
| OS Creator — canal ANTIGO de auto-update | `Levi-6242/os-creator-releases` | **pessoal** | público | todos |
| Coletor GridCo — instaladores (auto-update) | `Levi-6242/coletor-gridco-releases` | **pessoal** | público | todos |
| **Coletor GridCo — CÓDIGO-FONTE** | `...\temp\coleta API PV` | **só neste PC** | — | ninguém |
| **Maquinário de build** (`release.py`, specs, `setup.iss`) | `C:\GridcoBuild` | **só neste PC** | — | ninguém |

**Organização `Grid-Co-CODE`** — 3 membros: `admin-gridco`, `EmersonGrid`, `Levi-6242`.

---

## 2. Os dois buracos, antes de qualquer plano

### 2.1 O código do Coletor não existe fora deste PC

`coleta API PV` **é** um repositório git, mas:

- **nenhum remote configurado** — nunca foi enviado para lugar nenhum;
- **1 único commit**, de 03/08/2026;
- **20 arquivos fora do commit**, entre eles peças centrais que nunca foram versionadas:
  `fechamento_noturno.py` (o fechamento das 23:30), `sync_gridco_api.py` (o que sobe os BD
  para o PostgreSQL), `coletar_semp.py`, `estado_coleta.py`, `backup_local.py`, e o
  `coletar_pg.py` + `_totais_pg.py` criados hoje.

Se este PC morrer, **isso tudo morre junto**. É o item mais urgente do documento.

Segredo **não** é impedimento: o `.gitignore` já cobre `config.ini`, `sunop_token.txt`,
`plat_token.txt`, `se_credentials.txt`, `token.json` e `credentials.json`, e nenhum deles está
rastreado. Antes de enviar, acrescentar ao `.gitignore`: `coleta_estado.json` (estado de runtime)
e `*.bak-*` (há um `sync_gridco_api.py.bak-antes-do-corte` solto).

### 2.2 `C:\GridcoBuild` não é versionado

Não é repositório git. Contém o `release.py` que publica **os dois** produtos, o `Coletor.spec`
(com a lista `HIDDEN`, sem a qual módulos somem do `.exe` sem erro nenhum) e o `setup.iss`.

O `release.py` do OS Creator é o que hoje publica **nos dois canais** — e é essa publicação dupla
que segura as máquinas ainda na v166 ou anterior. Perder esse arquivo sem saber disso deixa essas
máquinas sem atualização **em silêncio**, e o conserto é reinstalar uma por uma.

---

## 3. O que "ambiente compartilhado" precisa significar

Não é só "subir para a organização". São quatro coisas distintas:

1. **Código na organização**, não numa conta pessoal — se o Levi sair, nada some.
2. **Mais de uma pessoa capaz de publicar** uma versão, sem depender de uma máquina específica.
3. **Segredos com um dono claro** — hoje eles viajam dentro de um `.zip`, o que não escala.
4. **Runtime com dono** — a plataforma roda no PC do Levi, com túnel, tarefas agendadas e o chip
   do WhatsApp presos ali.

Os itens 1 e 2 se resolvem esta semana. O 3 e o 4 são projeto.

---

## 4. Plano, em ordem

### Fase 0 — parar a sangria (hoje, ~30 min)

1. Criar `Grid-Co-CODE/coletor` (privado).
2. No `coleta API PV`: acrescentar `coleta_estado.json` e `*.bak-*` ao `.gitignore`, commitar os
   20 arquivos, apontar o remote e enviar.
3. Criar `Grid-Co-CODE/build-tooling` (privado) e versionar `C:\GridcoBuild`: `release.py` (os dois),
   `Coletor.spec`, `setup.iss`, `versao.json`, notas. **Sem** `dist/`, `build/`, `installer/`.

Só isso já tira o risco de perda total.

### Fase 1 — a plataforma vai para a organização

4. Transferir `Levi-6242/PerformancePainel` → `Grid-Co-CODE`. A transferência preserva histórico,
   issues e mantém redirecionamento dos clones existentes — ninguém precisa reclonar.
5. Dar acesso a `EmersonGrid` e `admin-gridco`.
6. Renomear para algo que diga o que é (`performance` ou `plataforma`), já que `PerformancePainel`
   virou nome histórico.

### Fase 2 — canais de release na organização

7. Criar `Grid-Co-CODE/coletor-release` (público) e acrescentá-lo à lista `REPOS` do `release.py`
   do Coletor — publicando nos **dois**, como já se faz no OS Creator.
8. Publicar uma versão nova por esse caminho duplo e confirmar que uma máquina já instalada atualiza.
9. **Só depois** que ninguém estiver abaixo dessa versão, remover o canal pessoal.

> **A ordem não pode inverter.** O endereço de atualização vive **dentro do `.exe` distribuído**,
> e não há comando remoto para corrigir. Aposentar o canal antigo cedo demais deixa máquinas órfãs,
> e a única saída é reinstalar cada uma. É a mesma lição do OS Creator, que hoje ainda publica nos
> dois endereços por causa disso.

### Fase 3 — pendência herdada do OS Creator

10. Quando ninguém mais estiver abaixo da **v2026.08.31.167**, remover a segunda entrada de `REPOS`
    no `release.py` e aposentar `Levi-6242/os-creator-releases`.
    Hoje os dois canais estão na 167 (publicadas com 2 min de diferença em 31/08).

### Fase 4 — segredos e runtime (projeto, não tarefa)

11. Definir onde os segredos moram. Hoje: `tokens.txt` na raiz do repositório da plataforma
    (fora do git) e `config.ini` no Coletor (fora do git), distribuídos por `.zip`. Alternativas:
    cofre da T.I., ou variáveis de ambiente na máquina servidora.
12. Tirar a plataforma do PC do Levi — decisão já tomada em 22/07, não executada. O que está preso:
    túnel Cloudflare (o link muda a cada queda), tarefas agendadas, caminhos do OneDrive e
    **o chip do WhatsApp da ronda**, que é a maior dor da mudança.

---

## 5. O que fica preso à máquina mesmo depois de tudo

| Preso | Por quê | Saída |
|---|---|---|
| Chip do WhatsApp (ronda) | sessão do wwebjs vive num perfil local | reautenticar na máquina nova; a ronda para no meio |
| Túnel Cloudflare | link muda a cada queda | URL fixa exige domínio + conta Cloudflare da empresa |
| Tarefas agendadas | registradas por usuário | recriar; o instalador do Coletor já recria a dele |
| Caminhos do OneDrive | as planilhas mestras vivem lá | fixados no `config.ini`; autodetecção quebra |
| `C:\GridcoBuild` | PyInstaller + Inno instalados ali | Fase 0 versiona o código; as ferramentas ainda precisam ser instaladas |

---

## 6. Para a sessão nova começar

Ordem sugerida: **Fase 0 inteira** (é a que remove risco de perda), depois **Fase 1**.

Antes de enviar o Coletor, confirmar com `git status --porcelain` e `git ls-files` que nenhum
`config.ini`, token ou `credentials.json` entrou. O `.gitignore` já cobre — a conferência é porque
o custo de errar aqui é um segredo público.

**Duas ações que só o Levi pode fazer:** transferir o repositório pessoal para a organização
(exige ser dono dos dois lados) e publicar release (a permissão do `gh` é pedida a cada sessão).

Documentos relacionados: `CLAUDE.md` da raiz (mapa do repositório) e o de cada pasta.
