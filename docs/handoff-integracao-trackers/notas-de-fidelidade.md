# Notas de fidelidade e lacunas — cross-reference de usinas

Auditoria do de-para (`usinas_cross_reference.json/.csv`). O valor deste arquivo é ser fiel.

## Fidelidade
- As colunas **Fracttal** (code-base + nome longo) vêm dos **próprios mapas da plataforma**
  (`_frac_codebase` / `_frac_fractall_map`, alimentados pela coluna "Usina Fractall" do
  `BD_Performance/Equipamentos`). O de-para reflete **exatamente o que a plataforma usa hoje**
  — inclusive imperfeições do BD (ver abaixo).
- Junção entre fontes = **display normalizado** (minúsculo, sem acento, sem "(...)", espaços
  colapsados). Rótulo canônico por prioridade `pv > pg > owen > sunop > axis`.
- Cada usina vive em **uma** fonte de telemetria (não houve fusão cross-fonte):
  `api_pv 77 · thopen_pg 17 · athon_sunop 9 · dois_c_owen 4 · axis 0` = 107.
- Fracttal preenchido: **100/107 code-base, 102/107 nome longo**.

## Bug de dados — CORRIGIDO (04/08)
- **Alto Paraná 1** estava mapeado no BD ("Usina Fractall") para o ativo Fracttal
  **"Alto Paraná 2" → APR200**, embora exista o ativo distinto "Alto Paraná 1" → **APR100**.
  **Corrigido em 04/08:** a coluna "Usina Fractall" das **12 linhas** de Alto Paraná 1 foi
  ajustada para "Thopen - Alto Paraná 1 - PR" no **BD master ONLINE**
  (`...\6.Gerencial\4. Gestão à vista\1. Banco de Dados\BD_Performance.xlsx`) **e** na cópia
  local de fallback, via **Excel COM** (lossless — validações/formatação preservadas), com backup.
  Verificado: `_frac_codebase("Alto Paraná 1") → APR100` (este CSV já reflete). A plataforma viva
  atualiza quando o cache do de-para expira (`FRAC_CODE_TTL`) ou no próximo restart.

## Code-bases repetidos que NÃO são erro
- `ALT100` (Altair 1–5), `CLN100` (Ceilândia 1.1–1.3), `CLN200` (Ceilândia II ×4),
  `CAZ100` (Céu Azul I–III), `INP100` (Inhapi 1–3), `IND100` (Indaiatuba 1–4),
  `GTB100` (Guatambu 1–4), `SDN100` (Sítio dos Nogueiras 1–4) etc. — **sub-usinas do dashboard
  que compartilham UM único ativo Fracttal** (só existe um no parque).
- Ativos "X 1 e 2" (Santarém → STR100, Ipixuna → IPX100, Boa Esperança do Sul → BES100,
  Santo Inácio) são **um único ativo por design** no Fracttal.

## Lacunas
- **7 usinas sem code-base Fracttal:** `Coração 2 (112)`, `Santo Antônio da Platina 1`,
  `Santo Antônio da Platina 2`, `Sarandi 1`, `Sarandi 2` (5 PV sem vínculo no BD); e
  `Santo Inácio XII` (pg) e `Saturnino 1` (pv) — têm nome longo mas sem code-base no índice.
- **Axis vazio (0):** o processo de geração não tinha o `axis` trk_cache persistido nem meta
  viva (voltou vazia). Sabidamente **2 usinas** (PE III, Ponto Belo — axis.sunop.net). Para
  preencher: rodar `dump_cross_reference.py` num processo com o Axis quente / token válido.
- **IPX100 aparece 2×:** `(308) Ipixuna 1` (pg) e `Ipixuna do Pará` (owen) — mesma usina física,
  nomes divergentes; deixadas **separadas** (candidata a merge manual).

## Campo auxiliar
- No **JSON** há `_plant_ids` (fora das 9 colunas): ids numéricos `pv`/`pg` — as chaves reais de
  API para o handoff. O **CSV** mantém só as 9 colunas pedidas.

## Regenerar
- `dump_cross_reference.py` (Python real da máquina). Usa o estado persistido (`cache_snapshot`)
  para pv/pg e chamadas leves para o resto; não grava tokens. Imprime diagnóstico + contagens.
