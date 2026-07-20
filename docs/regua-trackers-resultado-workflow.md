# Régua de trackers — resultado do workflow (17/07/2026)

Workflow multi-agente (TDD) que traduziu a metodologia do PDF (`docs/metodologia-analise-trackers.md`) em
`_trk_analise_dia(grafico)` e validou contra as 16 fixtures (`tests/fixtures/trackers/*.raw.json`+`.gab.json`).
Régua WIP preservada em **`tests/_trk_analise_wip.py`** (438 linhas). A síntese/correção final foi cortada
pelo limite de sessão — este doc é o que ela ia consolidar.

## Placar: 5/16 passaram
- ✅ **`sunop__mab200__2026-07-09`** — o ALVO. parado 10/10, severo 7/7, normal 133/133 **exato** (comm-morta
  separada de travado-mecânico; os 7 severos-por-freeze que a régua de curso PERDIA, todos pegos; cluster 3/4/5).
- ✅ `apipv__primavera-1` (06, 07, 08, 09) — 4 dias "perfeitos", 22/22 normal, zero falso-positivo.
- ❌ os outros 11.

## Diagnóstico: a régua acertou o MAB200 LARGANDO as defesas que a régua atual já tinha (overfit)
As 11 falhas caem em **poucas causas sistemáticas** — o caminho da correção é claro: **fundir** a metodologia
nova (casos triviais 24h + sub-tipo comm-morta + severo-por-freeze que pega os 7 do MAB200) **COM as guardas
provadas do `_trk_classifica_curso` atual** que o build descartou.

1. **Guarda de BATENTE largada (a falha nº1).** Freeze em ±55° (batente mecânico legítimo) vira "severo" falso.
   Aparece em fernandopolis-1/3, altair-5, cidade-gaucha, aracoiaba, tim100, mab100. A régua atual tem
   `TRK_BATENTE=53` (|V|≥53 = batente, não é freeze); o build trocou pela validação pura de mediana da frota
   (DEV_MIN=13), que falha no batente. **Fix: re-adicionar o corte |V|≥~53.**
2. **Contaminação da mediana da frota.** Quando >40% da frota está parada/no batente, a mediana ACOMPANHA os
   congelados → DEV_MIN<13 descarta freezes REAIS (severo-no-batente PERDIDO). Direção oposta: mab100 (4/16
   severos), altair-5, aracoiaba. **Fix: quando a frota-ativa encolhe, usar o batente + o histórico do dia
   (a frota moveu-e-voltou FORA da janela do freeze), não só |mediana−valor| dentro da janela.**
3. **"Congelou e NÃO retomou → PARADO" não implementado.** fernandopolis-1 (15 falsos-negativos): freeze longo
   sem retomada vira severo, devia ser parado. A régua atual promove freeze-até-o-fim a parado. **Fix: portar.**
4. **Amplitude robusta p02–p98 no Passo A.** Ruído de 1 leitura infla max−min e o "travado_antes_meia_noite"
   não dispara (ceu-azul-1 TRK3, tim100 TRK_25/32). **Fix: usar `_amp_robusta`<3 em vez de (max−min)<2.**
5. **Severidade por RECUPERAÇÃO, não só duração.** Gabaritos: severo=sustentado/crítico, leve=transitório/recupera
   — não é `dur>=30`. alto-parana-1. **Fix: critério de recuperação (o `_trk_classifica_curso` já tem jump/fim).**
6. **Camada de DESVIO LEVE ausente** (desvio persistente 3–10° da frota, sem freeze). aracoiaba, cidade-gaucha,
   alto-parana-1 perdem a classe leve inteira. **Fix: portar o run de desvio-leve sustentado do `_curso_perdas`.**
7. **Fuso UTC** (SunOp): tim100 usa janela fixa 06–18h local sobre dado UTC → desalinha o meio-dia. **Fix:
   `use_plant_timezone` / ajustar a janela por fonte.**
8. **Sub-tipo de PARADO novo** (alto-parana-2 TRK39): motor travado/glitch — teleporta entre platôs, valores
   fora da faixa ±55, amplitude alta mas parado. **Fix: detectar flatness alta + valores fora-de-faixa → parado.**

## Conclusão
A metodologia do PDF **funciona pro caso difícil** (MAB200 exato) — mas sozinha ela regride nos casos que a
régua atual já resolvia. O produto final é a **fusão**: régua atual (`_trk_classifica_curso` — batente, amp
robusta, freeze→parado, leve sustentado) **+** as camadas novas do PDF (triviais 24h, comm-morta vs mecânico,
a ocorrência-de-freeze que enxerga os severos que o curso perde, agrupamento por causa). As fixtures são o
juiz: alvo = passar as 16 (ou marcar as divergências que forem genuína decisão do Levi, não bug).

## Gabarito NOVO 16/07 — Nova Londrina 1 (apipv, 46 trackers) — usina SAUDÁVEL
PDF do Sonnet 5 (`Relatorio_NovaLondrina1_16-07-2026.pdf`). Vira fixture (falta puxar o raw da plataforma:
`apipv__nova-londrina-1__2026-07-16.raw.json`). ESPERADO: **parado 0, severo 1, leve 4, normal 41**.
- **SEVERO — TRK_8 (2 eventos):** (a) manhã bateu -55,8° CEDO DEMAIS e ficou enquanto a frota descia (juntou
  09:44); (b) tarde travou no pico +55° enquanto a frota descia (voltou 18:00). **É freeze NO BATENTE que É
  SEVERO** — divergiu do TIMING da frota. Prova que a correção da falha-nº1 NÃO é "corte |V|≥53=benigno", e sim
  "a frota moveu e este não". Threshold do gabarito: **desvio máx vs mediana da frota na janela > 8°** (o build
  usou 13° = overfit do MAB200; o certo é ~8°, com batente-aware p/ não pegar o dwell-com-a-frota).
- **LEVE (4):** TRK_29 travado -42,9° por 113min sem seguir a descida ao -55 (recuperou 10:26); TRK_19/33/35
  segurados no stow 06:00-07:16 (76min, recuperaram). = a camada de leve que a régua nova perde hoje.
- **NORMAL 41 + 0 parado** = dia saudável; guarda contra falso-positivo de batente (a frota inteira nos batentes
  ±55 é legítima). Complementa o MAB200 (que tinha comm-morta + freeze-mid-curso): juntos cobrem os dois lados
  do batente (benigno-com-a-frota vs severo-divergindo-do-timing).

## Gabarito NOVO 17/07 — TIM100 (sunop, 150 trackers) — o insight que UNIFICA (baseline por usina)
PDF do Sonnet 5 (`Relatorio_TIM100_17-07-2026.pdf`, 2ª análise da usina; 1ª foi 10/07 = fixture que MAIS
falhou no workflow). ESPERADO: **parado 37** (35 comm-morta + 2 crônico-perto-de-zero TRK_25/99, var<2°) ·
**"Observação" 32** (amplitude reduzida ~-37/+40°, TRK_15/31/33/35-51/54/61-67/70-75 — **CONFIG de zona, NÃO
falha**; flag p/ engenharia, recorrente do 10/07) · **severo 13** (17 ocorrências, TRK_105=447min pior, TRK_5=287,
vários com 2 eventos) · **leve 0** · normal ~68.
- **3.4 — CALIBRAÇÃO DO LIMIAR POR USINA (o pulo do gato):** limiar fixo de 8° sinalizou **78 trackers**, mas
  **65** eram o padrão DA USINA — dessincronização ~14-18° nas MESMAS 2 janelas de transição (07:47-08:39,
  15:20-16:17), em dezenas de trackers AO MESMO TEMPO. Diferente de batente (mediana parada), aqui **a mediana
  se move** mas uma fração grande da frota atrasa JUNTO = normal desta usina. **Ocorrência real = desvio que
  EXCEDE o baseline/espalhamento da própria frota naquele instante (aqui >20°), NÃO um limiar universal.**
- **Isto UNIFICA os 3 gabaritos** e mata a contradição de threshold (MAB200 pedia ~13°, Nova Londrina ~8°, TIM100
  >20°): não é constante — é **relativo ao espalhamento da frota da usina**. Se muita gente desvia junto = baseline;
  só foge quem é OUTLIER vs a distribuição da frota (não vs a mediana). Resolve de vez: (a) falso-positivo de
  batente, (b) contaminação da mediana quando >40% para junto, (c) degrau escalonado, (d) cluster de amplitude
  reduzida — todos são "a frota se comporta assim junto" = baseline.
- **Categorias novas:** "Parado crônico perto de zero" (var<2° mas ≠ 0.00 comm-morta) e "Observação" (amplitude
  reduzida = limite de projeto). **Recorrência entre dias** (34/35 comm-morta = 10/07) dá confiança: persistente=
  hardware/config; novo=candidato operacional.
- Vira fixtures `sunop__tim100__2026-07-17` (+ o 10/07 já existente) — os dois dias da MESMA usina testam a
  calibração por usina E a recorrência.

## Gabarito NOVO 17/07 — MRO100 (120 trackers, 2ª análise) — fecha a metodologia (alvo real + distribuição)
PDF do Sonnet 5 (`Relatorio_MRO100_17-07-2026.pdf`; 1ª foi 12/07). ESPERADO: **parado 1** (TRK_4, var<2° recorrente)
· **severo 3** (TRK_63/67/68, desvio 23,6-34,1° vs ALVO) · **leve 13** (17,5-20,7°) · normal 103. Dois refinamentos
que FECHAM a régua:
- **3.2 — ÂNGULO-ALVO REAL > mediana da frota:** o arquivo tem a série "Alvo (referência)" do sistema de controle.
  Quando disponível, usar o desvio vs o ALVO (não a mediana). Motivo: a mediana se distorce quando uma fração
  grande da frota atrasa junto (incorpora o próprio desvio que se quer medir) — exatamente a contaminação do
  TIM100. O alvo é independente das leituras. **Regra: alvo real se disponível E confiável (PG tem série; API PV é
  FURADO → mediana); senão mediana.** (Resolve o "MRO100 119 falsos" antigo — [[trackers-deteccao-por-alvo]].)
- **3.4/3.5 — LIMIAR e SEVERO/LEVE por LACUNA na DISTRIBUIÇÃO (não corte fixo):** olhar a distribuição dos
  desvios-máximos de TODAS as candidatas. No MRO100: cluster 0,6-1,7° (ruído) + cluster 11,9-14,7° (de-sync normal
  DA usina) + esparso 17,5-34,1° (anomalias). Limiar = **na LACUNA** entre baseline e anomalia (=17°). Depois,
  DENTRO do grupo de anomalias, se há nova lacuna (~3°): leve (17,5-20,7) vs severo (23,6-34,1). O corte EMERGE dos
  dados, por usina, não é constante.

## Gabarito NOVO 16/07 — Aracoiaba Serra 2 (pg, 46 trackers) — a PROVA "nenhum limiar fixo serve"
PDF do Sonnet 5 (`Relatorio_AracoiabaSerra2_16-07-2026.pdf`; tem série de alvo). ESPERADO: **parado 5** (1 comm-morta
TRK_36 + 4 crônico var<2° TRK_15/29/37/47) · **severo 1** (TRK_19, travado -55,3° 08:55-10:10, 14,9° vs ALVO — batente
severo por timing, igual Nova Londrina TRK_8) · leve 0 · normal 40. **PROVA (3.3):** distribuição SIMPLES e de ruído
BAIXO — ruído 0,4-0,9° + ruído-da-usina **5,9-7,1°** (menor que os 12-18° do TIM100/MRO100) + isolado **14,9°** →
limiar **10°** (na lacuna). O relatório crava: **17-20° (bom p/ TIM100/MRO100) seria permissivo demais aqui** (perde o
14,9°); **8° (1ºs relatórios) marcaria o ruído 5,9-7,1° como falso**. ⇒ cada usina tem faixa de ruído própria, **reestabelecer
a CADA arquivo** — nenhuma constante universal funciona. Reforça 100% o núcleo distribuição-por-usina. Fixture
`pg__aracoiaba-serra-2__2026-07-16`.

## Gabarito NOVO 16/07 — Santo Inácio XII (pg, 40 trackers) — VALIDA CONTRA CAMPO + batente por usina
PDF do Sonnet 5 (`Relatorio_SantoInacioXII_16-07-2026.pdf`; tem alvo). ESPERADO: parado 0-comm-morta + **2 crônico
(TRK_22, TRK_40)** · **2 severo** (TRK_15 -47,7° 08:20-09:20 17,6°; TRK_24 +44,8° 14:35-16:00 20,9°) · leve 0 · normal 36.
**VALIDAÇÃO DE CAMPO:** a ronda tem TRK_22=acoplamento, TRK_40=TCU ([[ronda-exclui-tickets-parado-aberto]]) — e o
gabarito marca EXATAMENTE TRK_22/40 como os crônicos. A régua reproduz o diagnóstico de campo → o "crônico" (var<2°)
pega falha mecânica real. NOVO: **stow e batente são POR USINA** (esta: stow -45°, batente -58,7/+58,6°) → o guard de
batente NÃO pode ser ±55 fixo, tem que ser o limite real da frota da usina. 3ª faixa de ruído (9,5-10,6°→limiar 15°),
entre Aracoiaba (5,9-7,1) e TIM100/MRO100 (12-20) = per-usina confirmado 3×. Fixture `pg__santo-inacio-xii__2026-07-16`.

## Régua-alvo CRISTALIZADA (síntese dos 6 gabaritos — pronta p/ codar)
1. **Referência**: ângulo-alvo real se disponível E confiável (PG); senão mediana da frota (API PV=furado). Desvio =
   |leitura − referência|.
2. **Triviais 24h**: comm-morta (0.00°/24h) · crônico (var<2° na janela, ≠0). + "Observação" (amplitude reduzida =
   config de zona, flag engenharia).
3. **Freeze por tolerância 2°** → janelas candidatas; desvio MÁXIMO absoluto na janela.
4. **Limiar POR USINA via DISTRIBUIÇÃO** (o núcleo, TIM100+MRO100): histograma dos desvios-máximos de todas as
   candidatas → as LACUNAS separam ruído + baseline-da-usina (de-sync/degrau/amplitude-reduzida, muitos juntos na
   mesma hora) das anomalias; limiar = a lacuna. **Absorve batente, contaminação-da-mediana, degrau e sync-delay de
   uma vez** — é o antídoto às 4 causas das 11 falhas do workflow.
5. **Severo/leve por LACUNA** dentro do grupo de anomalias (não corte fixo de duração/ângulo).
6. **Batente ±55** guarda extra (Nova Londrina TRK_8: batente PODE ser severo se foge do TIMING da frota).
7. **Fechamento 18:00** + exceção de dado parcial (fica aberto, não presume).
8. **Causa raiz** (mesma janela/valor/zona) + **recorrência entre dias** (persistente=hardware/config; novo=operacional).
9. **Fuso por fonte** (SunOp=UTC → ajustar a janela 06-18h).
Validar contra ~20 fixtures (as 16 + Nova Londrina-16 + TIM100-17 + MRO100-17; puxar os raws novos da plataforma).

## Integração (mapa do agente, quando a régua fechar)
- Plugar em **`_trk_classifica_curso` (app.py:4283)** + **`_trk_classifica_curso_perdas` (4355)** — os dois
  choke-points; overview e perdas herdam.
- **Fundir sub-abas**: `renderTrkParados`+`renderTrkEventos` → 1 grid, coluna FONTE via **`_perdaBdg(status)`**
  (já existe: parado→vermelho/severo→âmbar/leve). Fonte de dados = os 2 endpoints de perdas concatenados.
- **Histórico**: reusar `trk_eventos.json` (já persiste + sobrevive restart) OU clonar `perdas_strings.json`
  como `perdas_trackers.json`.


---

## STATUS DA FUSÃO — 18/07 madrugada (run wf_b2b1911c-234)

A fusão rodou mas **bateu no limite de sessão** (reset 4:20am Fortaleza) no meio da fase Validar. Concluídos 11/23 agentes: 4 Entender + build + 6 validações. Faltaram 10 validações + captura dos casos novos + a síntese-correção.

- **Régua construída:** `tests/_trk_regua_v2.py` (592 linhas — copiada do scratchpad p/ não perder). Implementa: referência ALVO-real-senão-mediana, triviais 24h (comm-morta/crônico com amp robusta), freeze tolerância 2°, **limiar por usina via lacuna na distribuição** (o núcleo, substitui DEV_MIN=13 fixo), severo/leve por 2ª lacuna, batente por usina, fechamento 18:00, causa-raiz + recorrência.
- **Placar parcial (6 das 16 fixtures rodaram): 2 OK, 4 fail.** OK: alto-parana-2, ceu-azul-1. Fail: cidade-gaucha-09 (falta 1 leve), cidade-gaucha-10 (severo 2 vs 3), alto-parana-1 (2 falsos severo — sem alvo no raw), **altair-5 (severo 4 vs 9, leve 0 vs 4 — o pior, precisa da síntese)**.
- **NÃO integrada no app.py** — régua não convergiu; plugar assim regrediria a classificação. Plano de integração pronto (chokepoint `_trk_classifica_curso` 4283 + `_trk_classifica_curso_perdas` 4355 → todas as fontes herdam; fundir sub-abas parados+ocorrências numa só c/ coluna FONTE; histórico via `perdas_trackers.json`).
- **Retomar:** `Workflow({scriptPath: '.../workflows/scripts/trk-regua-fusao-wf_b2b1911c-234.js', resumeFromRunId: 'wf_b2b1911c-234'})` — os 11 agentes concluídos voltam do cache; roda só validações restantes + síntese. Ou iterar `tests/_trk_regua_v2.py` na mão contra as 16 fixtures (foco altair-5).
- **Decisões do Levi pendentes (do build):** (1) SPARSE_FRAC=0.30 teto de anomalia; (2) classe `observacao` (amplitude reduzida) é categoria própria no overview?; (3) fallback severo/leve por duração (30min) quando não há lacuna de magnitude (MAB200 depende).


---

## INTEGRAÇÃO no app.py — 18/07 (flag DESLIGADO)

A régua v2 foi integrada atrás de flag, **sem mudar nada ao vivo ainda**:
- Módulo importável `trk_regua_v2.py` (raiz, cópia do `tests/_trk_regua_v2.py`). Flag `TRK_REGUA_V2` (env/tokens.txt), **default OFF**.
- Dois dispatchers em `app.py` (`_trk_classifica_curso` e `_trk_classifica_curso_perdas`) chamam a v2 sob flag, senão a legacy (renomeadas `*_legacy`). Qualquer erro cai p/ legacy. Overview/perdas/disponibilidade herdam sem tocar nos 4 call sites.
- Endpoint de comparação `GET /api/trk/regua/diff?fonte=&dia=&max=` (NÃO altera nada — roda os dois na mesma curva).

**Comparação ao vivo (PG 17/07, 6 usinas) — v2 NÃO está pronta p/ virar padrão:**
- agg legacy parado/severo/leve/normal = 21/71/30/145 ; v2 = 55/60/**0**/152.
- v2 acha MAIS parado (55 vs 21) — pega `congelou_nao_retomou` (bom); mas Aparecida 3 = 37 parados (revisar: evento real vs super-promoção).
- **v2 zera o LEVE (0 vs 30) = REGRESSÃO**: falta a camada de DESVIO SUSTENTADO (tracker que segue mas fica N° fora da frota, banda 3-12°). A legacy tem (`drun`); a v2 só detecta leve por freeze curto. É o item (f) da análise da WIP, ainda não portado.
- Performance v2 ~1.5-2× a legacy, <120ms/usina (ok).

**Antes de ligar o flag:** (1) portar a camada de desvio-sustentado p/ leve na v2 SEM re-quebrar MAB200 (a WIP achou 21 falsos ao adicioná-la — precisa do gate por-usina); (2) revisar a promoção a parado (Aparecida 3); (3) opcional: wire do magnitude-gap severo/leve. Rodar `/api/trk/regua/diff` por fonte p/ ver o delta.


---

## CAMADA LEVE (desvio sustentado) portada — 18/07

Portei a camada de leve por desvio sustentado que faltava na v2 (item f da WIP), com calibração POR USINA:
- Helper `_run_sustentado` (run >=15min de |tracker-mediana| na banda, FORA do batente) + `_piso_leve` (só dispara se ha LACUNA clara na distribuicao dos niveis tipicos de desvio da usina — anomalia destacada do chao de-sync). `theta_leve` do gap, `None` se usina uniforme.
- **Resultado fixtures: 8/16 exatas, PARADO 15/16 — MAB200 preservado (0 falso leve)**. O gate de lacuna evita os 18 falsos que a banda fixa 3-12° gerava. Custo: conservador — TRK49 do Cidade Gaucha (leve real) NAO e pego (sem lacuna limpa la), e no PG ao vivo o leve fica ~0 (usinas reais tem ruido gradual sem lacuna).
- **TENSAO REAL (precisa de gabarito/decisao):** leve sensivel (legacy, banda fixa: Caxambu=12 leve) vs leve seguro (v2, gap-gated: ~0). Qual e certo depende de ground-truth por usina — capturar Caxambu como fixture com o gabarito do Levi resolve.

## Aparecida 3: os 37 parados da v2 sao REAIS (investigado na curva crua 17/07)
- Tracker 02/04: amplitude do dia so ~27° (oscilam -6 a +21, nunca batente) = travados perto da horizontal.
- Tracker 11: -55.8° ao meio-dia (deveria ~0) = posicao errada.
- v2 rotula "parado" (amp reduzida pos-freeze), legacy "severo". Ambos validos; v2 mais util p/ OS. Preferencia do Levi.

## ESTADO: integração pronta e SEGURA, flag OFF. Falta: decisao do Levi p/ ligar (semantica parado muda visivelmente: Aparecida 2->37) + calibrar leve com gabaritos. Ligar = TRK_REGUA_V2=1 no tokens.txt + restart (1 comando).

---

## FLAG LIGADO 19/07 (trial ao vivo)
TRK_REGUA_V2=1 gravado no tokens.txt -> a v2 esta VALENDO em todas as fontes (overview/perdas/disponibilidade). Confirmado ao vivo: PG (2 usinas, 18/07) parado 7->35, severo 82->56. DESLIGAR = remover a linha TRK_REGUA_V2 do tokens.txt + restart (ou trocar p/ =0). Tunel do trial: link efemero em tunnel_url.txt.
