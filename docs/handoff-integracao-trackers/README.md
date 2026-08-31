# Handoff de integração — trackers parados

Pacote para outro aplicativo replicar a **identificação de trackers parados** e falar a mesma
**nomenclatura de usinas** que a Plataforma de Performance (Fracttal ↔ supervisórios).

## Arquivos

| Arquivo | Conteúdo |
|---|---|
| `INSTRUCOES-INTEGRADOR.md` | **COMECE AQUI (integrador).** Passo a passo pra ligar a integração campo→plataforma: endpoints, auth, os App Settings dos dois lados, o alerta do endereço estável, o diagnóstico e a realidade dos dados. Sem segredo. |
| `usinas_cross_reference.json` / `.csv` | **De-para de nomes por usina**: exibição ↔ Fracttal (code-base + nome) ↔ Athon/SunOp ↔ Axis ↔ API PV ↔ Thopen/PG ↔ 2C. Uma linha por usina. |
| `parametros-trackers-parados.md` | **Régua completa** de detecção (parado / freeze / desvio / atraso / sem comunicação / on-alvo), com todos os limiares, janelas e a lógica. |
| `parametros-trackers.json` | Mesmos parâmetros em formato **consumível por máquina** (nome, valor, unidade, regra). |
| `fontes-autenticacao.md` | Por fonte: **endpoints, header, onde o token mora, renovação**. Como cada fonte entrega a curva de ângulo. |
| `dump_cross_reference.py` | Script que **regenera** o cross-reference a partir dos mapas vivos do app (para reusar quando entrarem/saírem usinas). |
| `notas-de-fidelidade.md` | Auditoria do de-para: fidelidade ao que a plataforma usa, **bug do BD corrigido 04/08** (Alto Paraná 1 apontava pro ativo do 2 → agora APR100), code-bases repetidos que **não** são erro, e lacunas (axis vazio, 7 sem Fracttal). |
| `levantamento_supervisorio_x_fracttal.xlsx` | **Nível TRACKER.** Contagem de trackers do **supervisório vivo** (SunOp/API PV/PG, do cache) por usina/code-base × contagem de ativos **ETKR** do Fracttal. Mostra onde **BATE** (22) e onde **DIVERGE** (29) — a lista pra melhorar a relação. Fracttal codifica cada tracker como `{CB}-ETKR{N}.{grupo}`. |
| `trackers_supervisorio_x_fracttal.xlsx` | Nível tracker, âncora Fracttal × **BD_Trackers** (por code-base+número). 3 abas (Trackers / Sem conexão Fracttal / Sem conexão Supervisório). Conexão limitada (~36%) pela cobertura do BD_Trackers. |
| `api-campo-ronda.md` | **Integração de campo (CONSTRUÍDO 05/08).** Endpoints `GET /api/campo/ronda?usina=…` e `/api/campo/usinas` que o app de campo chama: técnico escolhe a usina → ronda de parados pronta. Token e régua ficam na plataforma; o campo usa só uma `x-api-key`. Desligado (fail-closed) até setar `CAMPO_API_KEY`. Sem Fracttal por enquanto (tracker = nº do supervisório). |

## Como identificar um tracker parado (resumo)

1. Obter a **curva de ângulo do dia** (POSAT) por tracker da fonte da usina (ver
   `fontes-autenticacao.md`), janela solar **06:00–18:00**.
2. Classificar cada tracker pela **amplitude robusta** (p02–p98) e pelos padrões de freeze —
   limiares em `parametros-trackers-parados.md`. Regra definitiva: amplitude do dia
   **< 3,0°** = parado.
3. Rotular **sem comunicação** (sensor morto ≈ 0,00° ou curva defasada > 45 min atrás da
   frota) e **exonerar** os que estão em cima do alvo (disparidade ≤ 12° e com comunicação).
4. O de-para de nomes (`usinas_cross_reference.*`) liga a usina da fonte ao ativo no Fracttal.

## Segredos

Nenhum valor de token/senha está neste pacote — só o **local** de onde sair cada um
(`fontes-autenticacao.md` → §Tokens). Para receber um arquivo de config com os valores reais
preenchidos, num caminho fora do git, é sob demanda.

## Origem

Gerado de `plataforma/app.py` (seção `TRK_*` e mapas de nomes). Para regenerar o de-para,
rodar `dump_cross_reference.py` com o Python real da máquina (ver cabeçalho do script).
