# -*- coding: utf-8 -*-
"""Relatório Potência Ativa dos Inversores (13/10/2026): as contas, sem rede.

Levi, 13/10/2026: "Teria como ter um novo relatório de performance pegando a potência ativa de cada inversor e
sobrepondo por dia. Cada inversor terá uma cor diferente. Se chamará relatório Potência Ativa dos Inversores!"

Um gráfico por dia, com a potência ativa (kW) de CADA inversor da usina ao longo do dia, todas as linhas no mesmo
gráfico. Este módulo é PURO (como o `relatorio_semanal.py`): valida o pedido, junta as leituras em passos de 5 min e
monta o dia. Quem lê as fontes é o `app.py` (bloco "RELATÓRIO POTÊNCIA ATIVA"), reaproveitando as leituras que a
plataforma já faz para as curvas do Tempo real e do drill — nenhuma leitura nova a fonte paga.

De onde vem a potência de cada fonte (a tabela `FONTES`):
- API PV (Thopen API PV, 2C, SEMP, Alves Lima): o `Pac` de cada leitura do inversor, as MESMAS leituras da Curva das
  strings (`_spv_day_records`): hoje o `day_inverter`; dia passado o `custom_query` v2, que custa 1 consulta da cota
  histórica da conta por usina e dia (a Tupi Paulista, grande demais para uma consulta, custa uma por inversor);
- Banco da Thopen: o `active_power` do `public.raw_inverter`, a mesma coluna da correlação tracker × inversor do drill
  (`_pg_series_inversores`), para qualquer dia;
- GreenYellow e Apolo (scadaGridco, MQTT): a potência que a telemetria de cada inversor já traz junto com as strings, a mesma
  curva da aba Curva (`_sg_curvas`), até 45 dias atrás;
- RenoGrid (SolarEdge): a POTÊNCIA CC, a soma das strings de cada inversor, de 15 em 15 min, pela mesma curva das strings
  do drill (`_se_strings_curva`). A SolarEdge não entrega a potência ativa (CA) do inversor; a grandeza vai escrita na
  tela (`grandeza`), e não como potência ativa (Levi, 13/10/2026: "Quero sim", para a soma rotulada "potência CC").
Sem histórico de potência por inversor, e a tela diz isso em vez de inventar: Sal Energia (Modbus: o histórico do
scadaGridco é por string, sem a potência do inversor). Athon e Axis SAÍRAM do relatório (Levi, 13/10/2026: "Não, por hora
pode tirar Axis e Athon"): a SunOp só é lida na última leitura de potência, e o histórico seria um pedido novo a uma fonte
paga de cota estourada. Voltam se o Levi pedir, lendo o histórico da medida P da SunOp (~1 pedido por usina e dia).
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta

# Teto de dias seguidos num relatório. Três razões, as três de custo e de leitura:
# 1. dia passado da API PV gasta 1 consulta da cota histórica da CONTA (800/dia e 200/h, divididas com a combiner e a
#    coleta da noite, que precisa de 300), e a Tupi Paulista gasta 20 por dia; 7 dias da Tupi já são 140 numa hora;
# 2. o scadaGridco atende uma chamada por vez (regra da Automação) e cada inversor de cada dia é um pedido de ~0,5 s:
#    7 dias × 16 inversores da Castelo do Piauí ≈ 1 min;
# 3. sete gráficos são uma semana, o período do relatório semanal, e cabem no PDF sem virar um catálogo.
MAX_DIAS = 7
PASSO_MIN = 5             # média de 5 min: a cadência do banco da Thopen; a API PV e o scadaGridco leem de minuto a minuto
LACUNA_MAX_MIN = 15       # mais que isto entre dois passos com leitura = a tela quebra a linha (lacuna não é zero)


class Recusado(ValueError):
    """Pedido que não dá para atender (fonte, usina ou período). A mensagem vai para a tela como está."""


class FonteNaoRespondeu(RuntimeError):
    """A leitura do dia não veio (rede, cota, credencial). NÃO é "dia sem dado": a tela diz que a fonte não respondeu, a
    falha não fica guardada e o dia pode ser lido de novo (regra de 10/10/2026: leitura que falha não vira zero)."""


class ForaDoPerfil(FonteNaoRespondeu):
    """A leitura nem foi pedida: o perfil não abre a fonte (o gestor pelo Nexus não abre a API PV, spec 5.3 da porta
    única). A tela não diz "a fonte não respondeu" (ninguém perguntou) nem oferece tentar de novo (não adiantaria)."""


# As fontes do Tempo real, na ordem dos cards da Entrada (`_ENTRADA_GRUPOS`), mais a aba 2C · API PV do Monitoramento,
# menos Athon e Axis (fora a pedido do Levi, 13/10/2026; ver a docstring). `familia` = quem lê (None = sem
# histórico de potência por inversor, com o motivo); `grandeza` = o que a curva mostra, quando não é a potência ativa.
FONTES = (
    {"fonte": "pv", "rotulo": "Thopen · API PV", "familia": "apipv",
     "origem": "API PV Operation: o Pac de cada leitura do inversor (de minuto a minuto), as mesmas leituras da Curva "
               "das strings do Tempo real"},
    {"fonte": "pg", "rotulo": "Thopen · Banco de dados", "familia": "pg",
     "origem": "Banco de dados da Thopen: a potência ativa (active_power) de cada leitura do inversor (a cada ~5 min), "
               "a mesma da correlação tracker × inversor do drill"},
    {"fonte": "solaredge", "rotulo": "RenoGrid · SolarEdge (potência CC)", "familia": "solaredge",
     "grandeza": "Potência CC",
     "origem": "SolarEdge: a potência CC de cada inversor, a soma das strings dele de 15 em 15 min (a mesma curva das "
               "strings do drill do Tempo real). Não é a potência ativa (CA) do inversor: a SolarEdge não a entrega à "
               "plataforma"},
    {"fonte": "2capi", "rotulo": "2C · API PV", "familia": "apipv",
     "origem": "API PV Operation (conta oem@): o Pac de cada leitura do inversor (de minuto a minuto), as mesmas "
               "leituras da Curva das strings do Tempo real"},
    {"fonte": "semp", "rotulo": "SEMP · API PV", "familia": "apipv",
     "origem": "API PV Operation (conta oem@): o Pac de cada leitura do inversor (de minuto a minuto)"},
    {"fonte": "alveslima", "rotulo": "Alves Lima · API PV", "familia": "apipv",
     "origem": "API PV Operation (conta oem@): o Pac de cada leitura do inversor (de minuto a minuto)"},
    {"fonte": "greenyellow", "rotulo": "GreenYellow · scadaGridco", "familia": "scadagridco",
     "origem": "scadaGridco (gateway MQTT): a potência ativa de cada inversor na telemetria de minuto a minuto, a "
               "mesma curva da aba Curva do Tempo real; o supervisório guarda 45 dias"},
    {"fonte": "salenergia", "rotulo": "Sal Energia · scadaGridco", "familia": None,
     "motivo": "A Sal Energia chega ao scadaGridco por Modbus, e o histórico dele para essas usinas é por string "
               "(corrente), sem a potência do inversor."},
    {"fonte": "apolo", "rotulo": "Apolo · scadaGridco", "familia": "scadagridco",
     "origem": "scadaGridco (gateway MQTT, o mesmo da GreenYellow): a potência ativa de cada inversor na telemetria de "
               "minuto a minuto, a mesma curva da aba Curva do Tempo real; o histórico dela começa em 28/10/2026"},
)
_POR_FONTE = {f["fonte"]: f for f in FONTES}
GRANDEZA_PADRAO = "Potência ativa"


def grandeza(f: dict) -> str:
    """O que a curva da fonte mostra: a potência ativa, ou a grandeza dela (o RenoGrid é potência CC)."""
    return f.get("grandeza") or GRANDEZA_PADRAO


def fonte(chave) -> dict:
    """A fonte pedida, ou Recusado."""
    f = _POR_FONTE.get(str(chave or "").strip())
    if not f:
        raise Recusado("fonte desconhecida: escolha uma das fontes do Tempo real")
    return f


def _data(texto, campo) -> date:
    try:
        return datetime.strptime(str(texto or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        raise Recusado(f"{campo} no formato AAAA-MM-DD") from None


def periodo(ini, fim, hoje: date) -> list:
    """Os dias do pedido, do mais antigo ao mais novo. Recusado: data fora do formato, fim antes do início, dia que
    ainda não chegou ou mais que MAX_DIAS seguidos (o porquê está no MAX_DIAS)."""
    a, b = _data(ini, "início"), _data(fim, "fim")
    if b < a:
        raise Recusado("o fim do período vem antes do início")
    if b > hoje:
        raise Recusado("o período não pode passar de hoje: dia que ainda não chegou não tem leitura")
    n = (b - a).days + 1
    if n > MAX_DIAS:
        raise Recusado(f"no máximo {MAX_DIAS} dias seguidos por relatório (foram pedidos {n}): cada dia passado da API "
                       "PV gasta a cota histórica da conta, e o scadaGridco atende um pedido por vez")
    return [a + timedelta(days=i) for i in range(n)]


_RX_TOKENS = re.compile(r"(\d+)")


def chave_natural(nome) -> tuple:
    """Ordem de gente: "Inversor 1.10" depois do "Inversor 1.9", "INV 2" antes do "INV 10". A tela usa a mesma régua
    (`chaveNatural` no template): é ela que fixa a cor de cada inversor."""
    partes = _RX_TOKENS.split(str(nome or "").strip().lower())
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in partes if p != "")


def minuto(hora) -> int | None:
    """Minuto do dia de "HH:MM", "AAAA-MM-DD HH:MM[:SS]" ou datetime; None se não der para ler."""
    if isinstance(hora, datetime):
        return hora.hour * 60 + hora.minute
    m = re.search(r"(\d{1,2}):(\d{2})", str(hora or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return h * 60 + mi if 0 <= h < 24 and 0 <= mi < 60 else None


def _kw(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def em_passos(pontos, passo: int = PASSO_MIN) -> list:
    """[(hora, kW)] → [[minuto do início do passo, média kW]], em ordem. Passo sem leitura não entra (lacuna não é
    zero); valor nulo, texto ou NaN fica de fora. A média, e não o último valor, é o que deixa o banco (~5 min) e a
    API PV (1 min) desenhados na mesma escala."""
    soma, n = {}, {}
    for hora, v in pontos or ():
        m, kw = minuto(hora), _kw(v)
        if m is None or kw is None:
            continue
        p = m - m % passo
        soma[p] = soma.get(p, 0.0) + kw
        n[p] = n.get(p, 0) + 1
    return [[p, round(soma[p] / n[p], 2)] for p in sorted(soma)]


def monta_dia(dia: date, leitura: dict, hoje: date, agora: datetime | None = None) -> dict:
    """O dia pronto para a tela, a partir do que o leitor da fonte devolveu:
    `{"inversores": [{"id", "nome", "pontos": [(hora, kW)]}], "motivo"?, "faltaram"?, "obs"?}`.

    - inversor sem nenhum ponto de potência vai para `sem_leitura` (a fonte o listou, mas sem potência), nunca para
      uma linha em zero;
    - dois ids com o mesmo nome de cadastro (o INVERSOR08 da Morada Nova trocou de id em 10/2026) não se misturam
      numa linha só: o nome ganha o id;
    - nenhum inversor com ponto = `sem_dado`, com o motivo da fonte (a fonte respondeu e não tinha leitura)."""
    agora = agora or datetime.now()
    brutos = list((leitura or {}).get("inversores") or [])
    nomes = {}
    for x in brutos:
        nomes.setdefault(str(x.get("nome") or x.get("id") or "?").strip(), set()).add(str(x.get("id")))
    invs, sem = [], []
    for x in brutos:
        nome = str(x.get("nome") or x.get("id") or "?").strip()
        if len(nomes.get(nome) or ()) > 1:
            nome = f"{nome} ({x.get('id')})"
        pts = em_passos(x.get("pontos"))
        if pts:
            invs.append({"nome": nome, "pontos": pts})
        else:
            sem.append(nome)
    invs.sort(key=lambda i: chave_natural(i["nome"]))
    sem.sort(key=chave_natural)
    out = {"dia": dia.isoformat(), "situacao": "ok" if invs else "sem_dado", "parcial": dia >= hoje,
           "lido_em": agora.strftime("%H:%M"), "inversores": invs, "sem_leitura": sem,
           "faltaram": sorted({str(n) for n in (leitura or {}).get("faltaram") or ()}, key=chave_natural),
           "motivo": None, "obs": (leitura or {}).get("obs") or None}
    if not invs:
        out["motivo"] = (leitura or {}).get("motivo") or "a fonte respondeu sem leitura de potência por inversor neste dia"
    return out


def dia_que_falhou(dia: date, motivo: str, agora: datetime | None = None, perfil: bool = False) -> dict:
    """O dia cuja leitura não veio: sem linha nenhuma, com o motivo e a hora (não é usina parada nem dia sem dado).
    `perfil` = a leitura nem foi pedida, por causa do perfil (ver ForaDoPerfil)."""
    agora = agora or datetime.now()
    return {"dia": dia.isoformat(), "situacao": "falhou", "parcial": False, "lido_em": agora.strftime("%H:%M"),
            "inversores": [], "sem_leitura": [], "faltaram": [], "motivo": str(motivo or "a fonte não respondeu"),
            "obs": None, "perfil": bool(perfil)}
