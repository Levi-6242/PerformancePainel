# -*- coding: utf-8 -*-
"""A disponibilidade pelos comentários do BD_Thopen (30/10/2026), para as usinas que a Ronda COS não cobre.

Levi, 30/10/2026, com a lista das usinas: "A disponibilidade dessas UFVs devem ser calculados de acordo com os
comentários do BD_Thopen e os comentários também". São as que não têm normalização do COS nem conta na plataforma (só a
Cambé tem). A coluna de disponibilidade do BD não serve em outubro: vazia em quase todas, 100% na Nova Iguaçu com a usina
desligada de 30/09 a 09/10 pelo comentário, e 0% na Segredo o mês inteiro. O que vale é o período escrito no comentário
da equipe, que segue um molde: "<tipo> - <detalhe> - 04/10 às 09:35h ao 09/10 às 07:14h" (ou "08/10 08:38 às 09:55" no
mesmo dia), uma linha por evento.

Decisões dele no mesmo dia: falha de comunicação NÃO conta (a regra de sempre: falta de comunicação não é parada);
desligamento de cabine conta a potência média de uma cabine da usina pelo cadastro de equipamentos do Nexus (1 ÷ nº de
cabines; sem cabines no cadastro, a usina inteira); desligamento de usina (ou usina parada), a usina inteira. A conta é a
mesma do Gerencial: janela de sol 06–18 h, 12 h por dia, perda = fração da potência × horas. Módulo puro: sem rede.
"""
import re
import unicodedata
from datetime import date, datetime, timedelta

# as usinas do Dashboard Thopen (o nome da aba do BD_Thopen) que seguem os comentários; a lista do Levi trazia os
# nomes de lá: "Aparecida do Taboado" = AP. do Taboado, "Pacaembu - Sítio Areia Branca 1.1 e 1.2" = Areia Branca,
# "Nova Iguaçu 2.1 e 2.2" = Nova Iguaçu, "Segredo 1.1 a 1.5" = Segredo. As Sol Maior GD I a V não estão no dashboard
USINAS = frozenset({"Rondonópolis", "Aruanã", "AP. do Taboado", "Areia Branca", "Monte Aprazível", "Nova Iguaçu",
                    "Sapopema", "Segredo", "Cambé"})
SOL_INI_H, SOL_FIM_H = 6, 18

_PERIODO = re.compile(
    r"(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\s*(?:as|a)?\s*(\d{1,2})[:h](\d{2})\s*h?\s*"
    r"(?:as|ao|a|ate|-)\s*(?:(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\s*(?:as|a)?\s*)?(\d{1,2})[:h](\d{2})")


def _norm(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def tipo_da_linha(linha):
    """'comunicacao' (não conta), 'cabine', 'usina' ou None (não é parada)."""
    t = _norm(linha)
    if "comunic" in t:
        return "comunicacao"
    if "deslig" in t or "parad" in t:
        return "cabine" if any(k in t for k in ("cabine", "skid", "qgbt")) else "usina"
    return None


def _ano(mes_lido, ref):
    """O ano da data do comentário: o do dia em que ele foi escrito, virando o ano quando o mês está do outro lado."""
    if mes_lido - ref.month > 6:
        return ref.year - 1
    if ref.month - mes_lido > 6:
        return ref.year + 1
    return ref.year


def periodos(texto, ref):
    """[(tipo, início, fim, linha)] das linhas do comentário escrito no dia `ref` (date). Linha sem período ou com o
    fim antes do início não entra."""
    out = []
    for linha in str(texto or "").splitlines():
        linha = linha.strip()
        tipo = tipo_da_linha(linha)
        m = _PERIODO.search(_norm(linha))
        if not linha or tipo is None or not m:
            continue
        d1, m1, h1, n1, d2, m2, h2, n2 = m.groups()
        try:
            ini = datetime(_ano(int(m1), ref), int(m1), int(d1), int(h1), int(n1))
            fd, fm = (int(d2), int(m2)) if d2 else (int(d1), int(m1))
            fim = datetime(_ano(fm, ref), fm, fd, int(h2), int(n2))
        except ValueError:
            continue
        if fim > ini:
            out.append((tipo, ini, fim, linha))
    return out


def _perda_do_dia(dia, eventos):
    """Horas equivalentes perdidas no dia: a maior fração ativa em cada trecho da janela de sol (a usina inteira cobre a
    cabine; duas cabines ao mesmo tempo somam, até a usina)."""
    js, jf = datetime(dia.year, dia.month, dia.day, SOL_INI_H), datetime(dia.year, dia.month, dia.day, SOL_FIM_H)
    evs = [(max(a, js), min(b, jf), f) for a, b, f in eventos if b > js and a < jf]
    bordas = sorted({x for a, b, _f in evs for x in (a, b)})
    h = 0.0
    for a, b in zip(bordas, bordas[1:]):
        ativos = [(ini, fim, f) for ini, fim, f in evs if ini <= a and fim >= b]
        if ativos:
            h += min(1.0, sum(f for *_x, f in ativos)) * (b - a).total_seconds() / 3600
    return h


def por_dia(registros, ano, mes, ate, n_cabines=None):
    """({dia: disponibilidade %}, {dia: [linhas do comentário]}) da usina no mês, dos dias até `ate` (inclusive).
    `registros`: os do BD_Thopen ({data, com}), do mês e de antes (o comentário de 30/09 diz o desligamento que entra em
    outubro). O mesmo evento escrito em vários dias conta uma vez. Dia sem evento = 100."""
    eventos, linhas, comentarios = set(), {}, {}
    for r in registros:
        d = r.get("data")
        if not d or not r.get("com"):
            continue
        for tipo, ini, fim, linha in periodos(r["com"], d):
            if tipo == "usina":
                eventos.add((ini, fim, 1.0))
            elif tipo == "cabine":
                eventos.add((ini, fim, 1.0 / n_cabines if n_cabines else 1.0))
            linhas.setdefault((ini, fim), linha)
        if (d.year, d.month) == (ano, mes) and d <= ate:
            comentarios[d] = [x.strip() for x in str(r["com"]).splitlines() if x.strip()]
    disp, d = {}, date(ano, mes, 1)
    while d.month == mes and d <= ate:
        disp[d] = round(100.0 * (1 - _perda_do_dia(d, eventos) / 12.0), 3)
        if disp[d] < 100 and d not in comentarios:      # o desligamento escrito noutro dia e que pega este
            js, jf = datetime(d.year, d.month, d.day, SOL_INI_H), datetime(d.year, d.month, d.day, SOL_FIM_H)
            comentarios[d] = sorted({linhas[(a, b)] for a, b, _f in eventos if b > js and a < jf})
        d += timedelta(days=1)
    return disp, comentarios
