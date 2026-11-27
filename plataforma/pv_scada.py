# -*- coding: utf-8 -*-
"""A 2C pelo SCADA da Grid no formato da API PV (26/11/2026).

Levi, 26/11/2026: "tem alguns [usinas] da 2C que estão entrando ali pelo SCADA [...] queria que você conferisse" e, ao
"posso ligar o SCADA como fonte principal e deixar a API PV de reserva?", "boa". A regra das fontes (16/11/2026): o SCADA
da Grid vem primeiro. A Araputanga e a Ipixuna do Pará (as três UGs, que a API PV chama de Santa Cecilia 1, 2 e 3) estão
no scadaGridco desde novembro; a Sete Lagoas, a Tupi Paulista e a União, não. Ligada só a IPIXUNA: a Araputanga fica
na API PV (ver ARAPUTANGA_FORA).

Como: as leituras do dia de cada inversor no supervisório (o /api/telemetria, de minuto a minuto) viram REGISTROS no
formato do `day_inverter` da API PV, com o id do inversor dela, e passam pela MESMA montagem da tabela, do detalhe por
inversor, das curvas de string e do PR do dia: os nomes (PV_INV_NOMES), as esperadas, as trancadas, as OS e a régua das
strings saem iguais aos de sempre. A API PV entra só quando o SCADA não responde ou não leu nada hoje.

O que foi provado antes de ligar (26/11/2026):
- o inversor, PELO VALOR: a energia do dia de cada equipamento contra o kWh da aba do BD_Performance, diferença 0,0 em
  todos os dias (Araputanga de 21 a 24/11, Ipixuna do Pará de 22 a 24/11) — o equipamento N da Araputanga é o
  Inversor 1.N; na Ipixuna, 1–8 = 1.1–1.8, 9–14 = 2.1–2.6, 15–20 = 3.1–3.6;
- a numeração das strings, contra o day_inverter da API PV do mesmo dia: pela mesma numeração, 0,2 a 0,4 A de
  diferença média minuto a minuto (Araputanga, 301 minutos; Santa Cecilia 1, 39), e as entradas que o SCADA tem zeradas
  o dia todo são as que a API PV não lista naqueles minutos;
- as unidades: potência em kW, energia do dia em kWh e temperatura em °C, as mesmas da API PV no mesmo minuto (a
  Araputanga 1.3 às 13:00: 250,2 kW e 560,8 kWh no SCADA, 250,3 kW e 560,5 kWh na API PV).

Puro: nada de rede aqui (o app.py busca e guarda as leituras; aqui só a conversão).
"""
import json

# id da usina na API PV → {"scada": a usina no scadaGridco, "equip": {equipamento do supervisório: id do inversor na API PV}}
# A ARAPUTANGA FICA NA API PV: o supervisório manda só 20 entradas por inversor (string_1 a string_20) e a usina tem 236
# strings esperadas, umas 24 por inversor (a API PV lê as 28 entradas). Montada pelo SCADA, a linha de 26/11 às 13:00
# dava 176 ativas de 236, um déficit FALSO de 60 (pela API PV, 236 de 236). O inversor fecha pelo valor (o N é o 1.N,
# 400771 + N − 1) e a potência e a temperatura batem: entra quando a Automação trouxer as outras entradas.
ARAPUTANGA_FORA = {"scada": "araputanga", "equip": {str(n): 400771 + n - 1 for n in range(1, 11)},
                   "motivo": "o supervisório manda 20 entradas por inversor e a usina tem ~24 strings por inversor"}
USINAS = {
    18771915: {"scada": "ipixuna_do_para",                                             # Santa Cecilia 1 (UG 01)
               "equip": {"1": 400840, **{str(k): 400841 + k for k in range(2, 9)}}},  # a API PULA 400841 e 400842
    18771929: {"scada": "ipixuna_do_para",                                             # Santa Cecilia 2 (UG 02)
               "equip": {str(9 + i): 400882 + i for i in range(6)}},
    18771930: {"scada": "ipixuna_do_para",                                             # Santa Cecilia 3 (UG 03)
               "equip": {str(15 + i): 400888 + i for i in range(6)}},
}

# a chave do day_inverter ← os pontos do supervisório, na ordem de preferência
_CAMPOS = (("Pac", ("active_power",)),
           ("Eday", ("total_daily_energy", "daily_active_energy")),
           ("Temp", ("temperature_current", "temperature_internal")))


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def registros(regs_por_equip: dict, cfg: dict, strings_de, com_ok) -> list:
    """Os registros do `day_inverter` a partir das leituras do supervisório: {"idefinversor", "tsleitura_new",
    "conteudojson"} com IpvN (a entrada N do supervisório é a N da API PV), Pac, Eday e Temp. Leitura ruim do gateway
    (communication_fault diferente do bom) é lacuna, não zero: fica fora, como o inversor que a API PV não manda."""
    out = []
    for eq, dev in (cfg or {}).get("equip", {}).items():
        vistos = set()
        for r in regs_por_equip.get(eq) or []:
            if r.get("communication_fault") not in (None, com_ok):
                continue
            ts = str(r.get("data_hora") or "")[:19]
            if len(ts) < 19 or ts in vistos:
                continue
            p = r.get("pontos") or r.get("measurements") or {}
            cj = {f"Ipv{n}": round(a, 3) for n, a in sorted((strings_de(p) or {}).items()) if _num(a) is not None}
            for chave, campos in _CAMPOS:
                v = next((_num(p.get(c)) for c in campos if _num(p.get(c)) is not None), None)
                if v is not None:
                    cj[chave] = v
            if not cj:
                continue
            vistos.add(ts)
            out.append({"idefinversor": dev, "tsleitura_new": ts, "conteudojson": json.dumps(cj)})
    return out
