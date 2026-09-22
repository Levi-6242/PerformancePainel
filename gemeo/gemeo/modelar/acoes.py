# gemeo/gemeo/modelar/acoes.py
"""Traduz o que o gemeo DETECTOU no que alguem deve FAZER (21/09/2026).

POR QUE EXISTE
O relatorio IEA-PVPS T13-34 separa *Digital Shadow* (fluxo automatico so fisico->digital) de
*Digital Twin* (automatico nos dois sentidos). Pela taxonomia somos Sombra Digital, e o passo que
falta esta descrito la quase como se nos conhecesse: o gestor abre a tela, ve os alarmes **e uma
lista de acoes propostas**, e aprova. Deep link do OS Creator e escrita na API do Fracttal ja
existem — o que faltava era o gemeo PROPOR.

A REGRA QUE GOVERNA O MODULO: propor nao e executar. Aqui se decide O QUE fazer, POR QUE e QUANTO
custa; quem abre a OS e uma pessoa, na tela. O modulo e PURO — sem banco, sem rede, sem escrita —
e ha teste travando isso, porque o dia em que uma "sugestao" virar uma OS aberta sozinha e o dia
em que ninguem mais confia na tela.

O QUE NAO VIRA ACAO, e por que importa tanto quanto o que vira:
  - **clipping**: decisao do Levi em 17/09 — e limite de PROJETO, nao falha de operacao. Mandar
    gente a campo investigar um projeto funcionando como desenhado queima a credibilidade da lista.
  - **evento sem custo**: tracker detectado que a cascata valorou em zero nao move ninguem.
  - **residuo**: vira INVESTIGAR a usina, nunca uma OS de equipamento — resíduo e, por definicao, o
    que a cascata nao explicou; abrir OS sobre o nao-explicado e mandar procurar no escuro.
"""
from __future__ import annotations

# Prioridade 1 = faca hoje. O criterio nao e so o kWh: sensor congelado custa ZERO e e o mais
# urgente da lista, porque enquanto ele nao for resolvido TODO numero da usina esta errado.
PRIO_URGENTE, PRIO_ALTA, PRIO_NORMAL = 1, 2, 3

# Fracao do esperado a partir da qual o residuo deixa de ser ruido e vira investigacao.
RESIDUO_FRACAO_MIN = 0.05

# Eventos de sensor comprometem a ENTRADA do modelo (a POA medida), nao uma parcela de perda.
_SENSOR = ("sensor_congelado", "sensor_em_falha")


def _brl(kwh: float, preco_mwh: float | None) -> float | None:
    return round(kwh / 1000.0 * preco_mwh, 2) if (preco_mwh and kwh) else None


def _texto_valor(kwh: float, brl: float | None) -> str:
    s = f"{kwh:,.0f} kWh".replace(",", ".")
    return f"{s} (R$ {brl:,.2f})".replace(",", "X").replace(".", ",").replace("X", ".") if brl else s


def _do_evento(ev: dict, preco_mwh: float | None) -> dict | None:
    tipo = ev.get("tipo") or ""
    equip = ev.get("equipamento")
    kwh = float(ev.get("kwh") or 0.0)
    brl = _brl(kwh, preco_mwh)
    janela = f"das {ev.get('hora_ini')} às {ev.get('hora_fim')}" if ev.get("hora_fim") else f"desde {ev.get('hora_ini')}"

    if tipo in _SENSOR:
        d = ev.get("detalhe") or {}
        valor = d.get("valor")
        trava = f" travado em {valor:g}" if isinstance(valor, (int, float)) else ""
        # `sensor_congelado` traz a medida no detalhe; o `sensor_em_falha` (gate POA x GHI, tipo
        # antigo) NAO traz — e escrever "SENSOR" ali nao diz a ninguem o que ir verificar (visto ao
        # vivo em Sete Lagoas e Tupi, 21/09).
        medida = (str(d.get("medida")).upper() if d.get("medida")
                  else ("razão POA/GHI fora da faixa" if tipo == "sensor_em_falha" else "Sensor"))
        return {"tipo": tipo, "prioridade": PRIO_URGENTE, "equipamento": equip, "kwh": kwh, "brl": brl,
                "acao": "Verificar o sensor da estação solarimétrica",
                "porque": (f"{medida}{trava} {janela}. A POA medida é a ENTRADA do modelo: "
                           "enquanto isso não for resolvido, o esperado e toda a cascata desta usina "
                           "estão comprometidos — o déficit mostrado não é confiável."),
                "compromete_diagnostico": True}

    if kwh <= 0:                       # detectado e sem custo: nao mobiliza ninguem
        return None

    if tipo == "inversor_parado":
        return {"tipo": tipo, "prioridade": PRIO_URGENTE, "equipamento": equip, "kwh": kwh, "brl": brl,
                "acao": f"Abrir OS corretiva — {equip}",
                "porque": f"Parado {janela}, custando {_texto_valor(kwh, brl)} no dia.",
                "compromete_diagnostico": False}

    if tipo == "string_sem_corrente":
        return {"tipo": tipo, "prioridade": PRIO_ALTA, "equipamento": equip, "kwh": kwh, "brl": brl,
                "acao": f"Verificar string e fusível — {equip}",
                "porque": f"Sem corrente {janela}, custando {_texto_valor(kwh, brl)}.",
                "compromete_diagnostico": False}

    if tipo == "tracker_sem_comunicacao":
        return {"tipo": tipo, "prioridade": PRIO_ALTA, "equipamento": equip, "kwh": kwh, "brl": brl,
                "acao": f"Verificar comunicação do tracker — {equip}",
                "porque": f"Mudo {janela}; o período foi valorado em {_texto_valor(kwh, brl)}.",
                "compromete_diagnostico": False}

    if tipo in ("tracker_travado", "tracker_fora_alvo"):
        d = ev.get("detalhe") or {}
        exc = d.get("excesso_max")
        desvio = f" com desvio máximo de {exc:g}°" if isinstance(exc, (int, float)) else ""
        return {"tipo": tipo, "prioridade": PRIO_NORMAL, "equipamento": equip, "kwh": kwh, "brl": brl,
                "acao": f"Inspeção mecânica do tracker — {equip}",
                "porque": f"Fora do alvo {janela}{desvio}, custando {_texto_valor(kwh, brl)}.",
                "compromete_diagnostico": False}

    if tipo == "inversor_abaixo":
        return {"tipo": tipo, "prioridade": PRIO_ALTA, "equipamento": equip, "kwh": kwh, "brl": brl,
                "acao": f"Comparar com os pares em campo — {equip}",
                "porque": f"Produzindo abaixo dos inversores irmãos {janela} ({_texto_valor(kwh, brl)}).",
                "compromete_diagnostico": False}
    return None


def propor(eventos: list[dict], cascata: dict | None = None, preco_mwh: float | None = None) -> list[dict]:
    """Eventos + cascata do dia -> lista de acoes, a mais cara primeiro dentro de cada prioridade.

    `cascata` entra so para o residuo: e a unica acao que nasce da conta, e nao de um evento."""
    out = [a for a in (_do_evento(e, preco_mwh) for e in (eventos or [])) if a]

    c = cascata or {}
    residuo = float(c.get("residuo") or 0.0)
    esperado = float(c.get("e_esperado") or 0.0)
    if esperado > 0 and residuo / esperado >= RESIDUO_FRACAO_MIN:
        brl = _brl(residuo, preco_mwh)
        out.append({"tipo": "residuo_sem_causa", "prioridade": PRIO_NORMAL, "equipamento": None,
                    "kwh": residuo, "brl": brl,
                    "acao": "Investigar a usina — perda sem causa atribuída",
                    "porque": (f"{_texto_valor(residuo, brl)} ({residuo / esperado * 100:.0f}% do esperado) "
                               "sobraram depois de descontar inversor parado, trackers e strings. "
                               "A cascata não sabe explicar — vale olhar sujeira, sombreamento ou o cadastro."),
                    "compromete_diagnostico": False})

    # Sensor comprometido primeiro: com ele aberto, os numeros das outras acoes nao valem.
    out.sort(key=lambda a: (a["prioridade"], -a["kwh"]))
    return out
