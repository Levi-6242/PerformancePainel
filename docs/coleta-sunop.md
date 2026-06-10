# API SunOp — Referência de Coleta de Dados
> Documento de referência/handover. Última atualização: 2026-06-05.
> Como coletar, da API SunOp, **energia diária por inversor** e **irradiância (POA, GHI, POA-RI)** — com histórico de dias passados.
>
> 📚 Documentação relacionada: [Índice](README.md) · [Arquitetura](arquitetura.md) ·
> [Regras de negócio](regras-de-negocio.md) · [API PV Operation](api-pv-operation.md)

---

## 1. O QUE DÁ PRA COLETAR

| Dado | Tag (pathname) | Unidade | Como obter o valor do dia |
|---|---|---|---|
| **Energia diária por inversor** | `<PLANTA>.INV_N.MEDIDAS.EPD` | kWh | **MÁX do dia** (EPD é acumulador que zera à meia-noite) |
| **POA** (irradiância no plano) | `<PLANTA>.ESTM[_n].POA.IRAD` | W/m² | integral da curva → kWh/m² |
| **GHI** (horizontal global) | `<PLANTA>.ESTM[_n].GHI.IRAD` | W/m² | integral da curva → kWh/m² |
| **POA-RI** (traseira/refletida) | `<PLANTA>.ESTM[_n].POA_R.IRAD` | W/m² | integral da curva → kWh/m² |

> POA-RI = irradiância posterior (rear) — usada em módulos bifaciais. Pico típico bem menor
> que POA (ex.: CPP100 em 05/06: POA 1144, GHI 1112, **POA-RI 180** W/m²).

---

## 2. O ENDPOINT (a "chave" da coleta) 🔑

**`POST https://gridco-api.sunop.net/data/v2/analog_values`** — retorna a **série intradiária**
(timestamp + valor) de QUALQUER medida analógica, **inclusive dias passados**.

- **Auth:** header `Authorization: JWT <token>` (o token de sessão normal — ver §5).
- **Query string:**
  - `source=Historical` ← obrigatório pra vir o histórico
  - `start_time=YYYY-MM-DDTHH:MM:SS`
  - `end_time=YYYY-MM-DDTHH:MM:SS`
  - `use_plant_timezone=true`
  - `fill_missing=false`
- **Corpo (JSON):** `{"pathnames": ["CPP100.INV_1.MEDIDAS.EPD", ...]}`
- **Resposta:** lista plana `[{"timestamp","value","quality","pathname"}, ...]`
  (~950 pontos/dia por tag, intervalo ~1,5 min).

### cURL de referência
```bash
curl 'https://gridco-api.sunop.net/data/v2/analog_values?fill_missing=false&source=Historical&start_time=2026-06-05T00:00:00&end_time=2026-06-05T23:59:59&use_plant_timezone=true' \
  -H 'authorization: JWT <TOKEN>' \
  -H 'content-type: application/json; charset=UTF-8' \
  --data-raw '{"pathnames":["CPP100.INV_1.MEDIDAS.EPD"]}'
```

### Como o app já faz (reutilizar)
`app.py` tem o helper **`_sunop_analog_history(pathnames, start, end)`** → `{pathname: [(ts, val), ...]}`
(faz lotes de 40 pathnames, ordena por tempo). Use-o direto.

⚠️ **NÃO confundir** com o *API token* (`Authorization: API ...`): é de uma API pública restrita,
dá 459/401 em tudo — **não serve**. O que funciona é o **JWT de sessão** (§5).

---

## 3. CÁLCULO DOS VALORES DIÁRIOS

### Energia por inversor (kWh)
EPD é acumulador diário (zera 00:00). Energia do dia = **`max(valores de EPD do dia)`**.
Para o total da usina, somar o MÁX de cada inversor.
> Validado 05/06: CPP100.INV_1 EPD máx = **1937,75 kWh**.

### Irradiância (kWh/m²)
Integrar a curva (W/m²) ao longo do dia:
- Trapézio: `Σ (v[i]+v[i+1])/2 * Δt_h` / 1000, com `Δt_h` = horas entre leituras.
- Aproximação simples (usada no projeto): `soma das leituras × Δt_h / 1000`
  (ex.: leituras de 5 min → `soma / 12000`). Como aqui o passo é ~1,5 min,
  **preferir o trapézio com o Δt real entre timestamps** (mais fiel; o passo não é fixo).
- Clamp recomendado: negativos → 0; teto ~1600 W/m².

---

## 4. DESCOBRIR OS PATHNAMES (metadata)

`GET https://gridco-api.sunop.net/data/v2/metadata?plant=<NOME>&size=6000` (header JWT).
Retorna `{"data":[{"pathname", "description", "eu", "source", ...}]}`.

Filtrar por:
- Energia inversor: `parts[1].startswith("INV_")` e termina em `.MEDIDAS.EPD`.
- Irradiância: `parts[1].startswith("ESTM")` e `.POA.IRAD` / `.GHI.IRAD` / `.POA_R.IRAD`.

O app já parseia isso em `_load_sunop_plant_meta()` → `meta["inv_other"][INV_N]["EPD"]`
e `meta["etm_stations"][ESTM][poa|ghi|poari]`. Use `app.ensure_sunop_meta()` e
`app._sunop_meta[<planta>]`.

> Estações: algumas plantas têm `ESTM` única; outras `ESTM_1`, `ESTM_2` (uma por linha).
> Inversores: CPP100 ~14 c/ EPD; outras variam. MTS100 só tem dados até INV_40 (`SUNOP_INV_MAX`).

---

## 5. AUTENTICAÇÃO (JWT, automático)

- Config base: `https://gridco-api.sunop.net/api` · Dados: `.../data`
- O app guarda o token em `_sunop_token` (env `SUNOP_TOKEN` como semente) e renova sozinho:
  `get_sunop_token()` chama `GET /api/check_token` e, se inválido, `GET /api/refresh_token`.
- Header pronto: **`app._sunop_headers()`** → `{"Authorization": "JWT <token>", ...}`.
- ⚠️ O token expira; se a coleta for agendada, garantir que o refresh funcione (ou semear
  `SUNOP_TOKEN` atualizado). Pelo `iat/exp` do JWT, validade é de alguns dias.

---

## 6. PLANTAS SunOp (10 GD)

`SMP100, CPP100, TIM200, MRO100, TIM100, MTS100, MTS200, MAB200, MAB100, JCD100`
(`GET /api/plants` → lista com `name`). Todas têm ETM (POA/GHI/POA-RI) e inversores com EPD.

---

## 7. ESBOÇO DE UM COLETOR (pseudo)

```python
import app, requests
app.ensure_sunop_meta()
def coletar_dia(planta, dia):  # dia = "YYYY-MM-DD"
    meta = app._sunop_meta[planta]
    # pathnames de energia (EPD) + irradiância
    epd = {inv: o["EPD"] for inv, o in meta["inv_other"].items() if "EPD" in o}
    irr = {f"{est}:{k}": p for est, d in meta["etm_stations"].items() for k, p in d.items()}
    hist = app._sunop_analog_history(list(epd.values()) + list(irr.values()),
                                     f"{dia}T00:00:00", f"{dia}T23:59:59")
    energia = {inv: max((v for _, v in hist.get(p, [])), default=None)   # kWh do dia
               for inv, p in epd.items()}
    def integral(serie):  # kWh/m² (trapézio com Δt real)
        from datetime import datetime
        tot = 0.0
        for (t0, v0), (t1, v1) in zip(serie, serie[1:]):
            dt = (datetime.fromisoformat(t1) - datetime.fromisoformat(t0)).total_seconds()/3600
            tot += (max(v0,0)+max(v1,0))/2 * dt / 1000
        return round(tot, 3)
    irrad = {k: integral(hist.get(p, [])) for k, p in irr.items()}
    return {"energia_inversor": energia, "irradiacao": irrad}
```
> (Ajustar parênteses/imports — é só o esqueleto. O endpoint e os pathnames são os validados aqui.)

---

## 8. NOTAS / LIMITAÇÕES

- O endpoint dá histórico de dias passados — bom p/ backfill (rodar 1x/dia ou recuperar atrasados).
- Saída do `analog_values` não vem alinhada por timestamp entre tags — cada pathname tem sua série.
- "Quality" no retorno: 1 = ok (observado). Vale filtrar quality ruim se aparecer.
- Para o de/para de nomes (Usina/Inversor supervisório → Check/BD_Thopen), reaproveitar a aba
  "Strings 2" do `Check Diário` (mesma lógica do projeto API PV → BD_Thopen).
- Este endpoint também destrava a **curva real de ETM** (POA/GHI) e de **trackers** no dashboard.
