# API PV Operation — Referência de Coleta de Dados

Referência para coletar dados da API PV Operation (geração, irradiação, strings).
Acompanha o script `coletar_geracao_hoje.py`.

> 📚 Documentação relacionada: [Índice](README.md) · [Arquitetura](arquitetura.md) ·
> [Regras de negócio](regras-de-negocio.md) · [Coleta SunOp](coleta-sunop.md)

---

## 1. Autenticação

- **Base URL:** `https://apipv.pvoperation.com.br/api/v1`
- **Login:** `POST /authenticate`
  ```json
  { "username": "<PV_USERNAME>", "password": "<PV_PASSWORD>" }
  ```
  → resposta: `{ "token": "..." }`
- **Uso do token:** em **todas** as chamadas seguintes, enviar o header:
  ```
  x-access-token: <token>
  ```
- O token expira; basta autenticar de novo para obter um novo.

---

## 2. Endpoints

### `GET /plants`
Lista todas as usinas da conta (~142).
```json
[ { "id": 22854, "nome": "Nova Londrina 1 (152)" }, ... ]
```

### `POST /plant_devices`  `json={"id": plant_id}`
Dispositivos da usina. Inversores têm `device_type = "INVERTER"`.
```json
[ { "plant_devices": [
    { "device_id": 46058, "device_name": "INVERSOR01", "device_type": "INVERTER" }, ...
] } ]
```
Usado para dar **nome ao inversor** (o `idinversor` da energia casa com `device_id`).

### `POST /custom_query`  → **GERAÇÃO (tem histórico)**
```json
{ "id": plant_id, "data_type": "energy", "period": "YYYY-MM", "day": N }
```
Energia diária por inversor. Retorna:
```json
[ { "dataleitura_new": "2026-06-03 00:00:00", "eday": "1490.51", "idinversor": 46058 }, ... ]
```
- `eday` = energia do dia (kWh) daquele inversor.
- **É o único `data_type` com histórico e sem timeout.** Funciona para dias passados (basta mudar `period`/`day`).

### `POST /day_meteo`  `json={"id": plant_id}`  → **IRRADIÂNCIA (só dia corrente)**
Leituras meteorológicas **intradiárias do dia de hoje** (centenas a milhares).
Cada registro tem `tsleitura_new` e `conteudojson` com os campos de sensor.
- POA (W/m²): primeiro válido entre `IrPOA`, `Ir`, `Ir1`, `piraPOA1`
- GHI (W/m²): primeiro válido entre `IrGHI`, `piraGHI1`
- **Não há histórico** — só devolve o dia corrente. Dias passados retornam vazio.

---

## 3. O que NÃO existe (testado)

No `custom_query`, apenas `energy` (e `meteo`, mas só dia corrente) são válidos.
Estes retornam **401 "Invalid input"** (não existem):
`irradiance`, `irradiation`, `string`, `strings`, `current`, `mppt`, `dc`, `combiner`.

→ **Não há endpoint para histórico de irradiação nem para corrente por string**
   além do que o `day_inverter`/`day_meteo` já trazem do dia corrente.

---

## 4. Como o script coleta (`coletar_geracao_hoje.py`)

Para o **dia de hoje**, em todas as usinas (ou só Full O&M):

**A) Geração por inversor**
1. `custom_query` com `data_type=energy` (mês/dia de hoje) → `eday` por inversor.
2. Nome do inversor via `plant_devices`.

**B) Irradiação por usina**
1. `day_meteo` → todas as leituras de hoje.
2. Para cada leitura, extrai POA e GHI instantâneos (campos com *fallback*).
3. **Integra no tempo** (trapézio) os valores de W/m² ao longo do dia
   e divide por 1000 → **kWh/m²** (≈ horas de sol pleno / HSP).
4. Também guarda o **pico** (W/m²) e o nº de leituras.

Saída: Excel com 2 abas — `Geracao_Inversor` e `Irradiacao_Usina`.

---

## 5. Restrições e cuidados

- **Irradiação só do dia corrente.** Para histórico, rodar 1x por dia
  (de preferência no fim do dia, para pegar o dia completo).
- **Campos variam por usina.** Algumas usam `IrPOA`, outras `Ir`/`Ir1`.
  Por isso o script tenta vários campos em ordem.
- **GHI pode vir 0/None.** Nem toda usina tem piranômetro horizontal ativo
  (ou usa outro campo). O POA costuma ser o mais confiável.
- **Códigos de erro de sensor:** valores com |x| ≥ 2000 W/m² (ex.: -666)
  são descartados; negativos pequenos (noite) viram 0 na integração.
- **Concorrência:** usar ~5 workers paralelos. O `energy` é o único
  data_type sem timeout; os demais podem ser lentos/instáveis sob carga.

---

## 6. Como rodar

```bat
python coletar_geracao_hoje.py                 :: todas as UFVs, hoje
python coletar_geracao_hoje.py --fullom        :: só Full O&M
python coletar_geracao_hoje.py --plant 22854   :: uma usina (teste)
python coletar_geracao_hoje.py --out arq.xlsx  :: nome do arquivo
```

Credenciais vêm das variáveis `PV_USERNAME` / `PV_PASSWORD` definidas no `.env`
da raiz do projeto (modelo em `.env.example`).
