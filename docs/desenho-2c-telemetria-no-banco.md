# Desenho — tirar o 2C da dependência de disco

Levantado em **01/09/2026**, medindo o sistema, não de memória.

---

## A premissa caiu, e isso encurta o trabalho

Eu propus "colocar a geração do 2C no PostgreSQL". **Ela já está lá.** As quatro usinas —
Araputanga, Ipixuna do Pará, Sete Lagoas e Tupi Paulista — vivem no workbook `bd_performance`
do banco da Grid Co, com dado até 31/08, incluindo o que foi recuperado hoje.

O erro veio de eu confundir dois bancos:

| | O que é | O que tem |
|---|---|---|
| **PG da Thopen** (`PG_HOST`) | TimescaleDB supervisório de **um** cliente | `tb_customer` = 1 linha, 34 usinas, `raw_inverter` com 15,7 milhões de leituras |
| **Gridco Performance API** | o banco da Grid Co | `bd_performance`, `bd_thopen`, `tickets`, estado da plataforma |

Quando você disse "o PG guarda todo o histórico de geração dos nossos clientes", é o **segundo**.
O primeiro é telemetria crua de uma carteira só.

---

## O que realmente falta: a assimetria da telemetria

O que existe hoje para cada família:

| | Geração diária | Telemetria de 5 em 5 min |
|---|---|---|
| **22 usinas Thopen** | no banco (`bd_thopen`) | **no banco** — `raw_inverter`, 15,7 M linhas |
| **4 usinas 2C** | no banco (`bd_performance`) | **só em CSV, num disco** |

Essa assimetria não é teórica — ela decidiu o dia de hoje. Quando as 22 da Thopen sumiram da
apipv, reconstruí cinco dias em minutos, lendo o `raw_inverter`. Quando as 4 do 2C ficaram sem
e-mail, **não havia de onde reconstruir**: dependeu de você baixar um anexo à mão.

O acervo do 2C hoje: **3,4 GB, 5.290 arquivos, desde 13/05/2026**, numa pasta só. Entram 33 a
45 MB por dia, em 52 a 66 arquivos.

---

## A cadeia atual, e onde ela quebra

```
e-mail  →  CSV no disco  →  planilha .xlsx  →  sync  →  banco
```

Quatro saltos. **Os quatro modos de falha foram observados hoje**, no mesmo dia:

1. **E-mail não chega** — cota do Gmail lotou; a caixa parou de receber de todo mundo em 30/08
   12:03 e ninguém soube por dois dias.
2. **CSV não é varrido** — o varredor procura em `2C_historico/*/geração/*.csv`; fora dessa
   estrutura o arquivo é invisível.
3. **Planilha travada** — o BD_Thopen aberto no Excel derrubou a coleta com `PermissionError`,
   duas vezes.
4. **Sync não roda** — depende do fechamento noturno, que por sua vez depende dos anteriores.

---

## Três desenhos

### A — Ingestão crua pela `/api/raw/*`

A API **já tem a porta**, e ela espelha exatamente a estrutura do PG da Thopen:

```
/api/raw/customers      GET, POST
/api/raw/device-types   GET, POST
/api/raw/power-plants   GET, POST
/api/raw/devices        GET, POST
/api/raw/{device_type}  POST          ← ingestão das leituras
/api/raw/queue/{id}     GET           ← fila assíncrona
/api/raw/{type}/latest  GET
```

**Está completamente vazia**: zero clientes, zero tipos, zero usinas, zero dispositivos. É um
caminho construído e nunca usado.

**O que dá:** o 2C passa a ter o mesmo pé que a Thopen — série de 5 min consultável, e
reconstrução de dia perdido sem depender de e-mail nem de disco.

**O que custa:**
- **O roteamento do POST está quebrado.** `POST /api/raw/customers` é atendido por
  `/api/raw/{device_type}` e exige `records`. Sem correção do autor da API, o caminho não abre.
- Cadastrar o catálogo: cliente, tipos de dispositivo, 4 usinas, ~60 inversores + estações.
- Volume: ~19,6 mil leituras/dia só de geração e irradiância; a telemetria completa é maior.
- Backfill opcional dos 3,4 GB já acumulados.

### B — Escrita direta da geração diária, sem passar pelo `.xlsx`

A API tem escrita por linha, que hoje não usamos:

```
POST   /api/sheets/{sheet_id}/rows
PUT    /api/sheets/{sheet_id}/rows/{row_number}
DELETE /api/sheets/{sheet_id}/rows/{row_number}
GET    /api/sheets/{sheet_id}/rows/{row_number}/history   ← histórico por linha
```

**O que dá:** elimina os saltos 3 e 4 — a planilha travada no Excel deixa de derrubar a gravação,
e o dado não espera o fechamento noturno. E o `history` por linha dá auditoria de quem mudou o quê.

**O que custa:** pouco. É reescrever o alvo do `rodar_2c.coletar_dia`. Mas **não resolve o que
aconteceu hoje** — se o e-mail não chega, não há o que escrever.

### C — Segunda caixa de entrada

Hoje o baixador lê só o Gmail. **O Outlook recebeu tudo** enquanto o Gmail estava lotado —
inclusive os relatórios de 31/08 que se perderam do outro lado.

**O que dá:** tira o ponto único de falha que causou a parada de hoje.

**O que custa:** o menor dos três. O conector do Microsoft 365 já está disponível e é leitura.

---

## Recomendação

**C primeiro, A depois, B por último.**

- **C** é o conserto do problema que de fato aconteceu, e é o mais barato. Duas caixas, uma cota
  cheia deixa de virar perda.
- **A** é o que corrige a assimetria estrutural — e é o único que faz o 2C ser recuperável
  sozinho. Mas está **bloqueado** pelo defeito de roteamento, que precisa ir para o autor da API.
- **B** é elegante e barato, mas resolve o salto que menos dói. Vale como consequência de A, não
  como projeto próprio.

---

## O que já foi feito hoje nessa direção

As quatro usinas do 2C entraram no `PERF_SCOPE` do `_verificar_coleta.py`. Elas estavam **fora**,
o que significa que a única fonte dependente de e-mail de terceiro era justamente a que ninguém
vigiava — por isso o silêncio de 30/08 passou dois dias.

**Ainda não validado:** o verificador morre inteiro com `PermissionError` se o BD_Thopen estiver
aberto no Excel, então a checagem do BD_Performance nunca roda. Isolar cada checagem num `try` é
correção pequena e vale por si.
