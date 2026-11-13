# -*- coding: utf-8 -*-
"""O fechamento do mês: a disponibilidade de um mês fechado não muda mais (13/11/2026).

O caso que criou a regra: em 13/11/2026 o cliente reclamou que tinha validado a disponibilidade de outubro da Polaris
num dia e, no outro, os mesmos números já tinham mudado ("estamos no dia 13/11 e os dados de Outubro estão sendo
alterados ainda? quando podemos confiar no valor correto da disponibilidade?"). De 10/2026 em diante a conta vem das
ocorrências da Ronda COS, e cada correção do COS refazia o mês inteiro: em 12/11 as ocorrências abertas passaram a
chegar completas e o COS corrigiu registros de outubro, e em 13/11 tirou uma ocorrência aberta da Vargem Grande (de
91,72% para 99,87%). Decisões do Levi (13/11/2026): outubro fecha com o número daquele momento, e daqui para frente cada
mês fecha no DIA 10 do mês seguinte; até lá a tela diz "em apuração".

Fechar = gravar o número de cada usina do 5080 em cada dia do mês, como o dashboard mostra naquela hora (`_disp_dias`:
a exceção, os comentários do BD, as ocorrências do COS ou o Histórico Carteira), no livro `thopen_disp_fechamento` ·
`disp_dia` (1 linha = 1 usina × 1 dia de um mês fechado). Mês com linha no livro = mês fechado: o 5080 lê o número dali
e nada mais (a usina sem linha num mês fechado fica sem número, não volta para a conta). Reabrir é tirar as linhas do
mês (`fechar_mes.py --reabrir`), só com o OK do Levi, e o cliente é avisado antes.

Relido a cada 10 min. Se o banco não responde, vale a última leitura boa. `THOPEN_FECHAMENTO=0` desliga a leitura e o
fechamento automático (os testes rodam assim, `conftest.py`).
"""
import datetime as dt
import os
import threading
import time

import fonte_api
import livro_banco

LIVRO, ABA = "thopen_disp_fechamento", "disp_dia"
NOME = "Dashboard Thopen · disponibilidade dos meses fechados"
CAB = ("mes", "usina", "dia", "disp_pct", "fechado_em", "origem")
DIA_DO_FECHAMENTO = 10
DESDE = (2026, 10)             # a conta pelas ocorrências do COS começa aqui (operacao_mes.DESDE)
TTL = 600                      # s
ESPERA_ERRO = 60               # s sem tentar de novo depois de uma falha
_TRAVA = threading.Lock()
_CACHE = {"linhas": None, "lido": 0.0, "falhou": 0.0}


def ligado():
    return os.environ.get("THOPEN_FECHAMENTO", "1").strip() != "0"


def chave(ano, mes):
    return "%04d-%02d" % (ano, mes)


def fecha_em(ano, mes):
    """O dia em que o mês fecha sozinho: o DIA_DO_FECHAMENTO do mês seguinte."""
    a, m = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return dt.date(a, m, DIA_DO_FECHAMENTO)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dia(v):
    try:
        return dt.date.fromisoformat(str(v or "").strip()[:10])
    except ValueError:
        return None


def _linhas():
    """As linhas do livro, da memória por TTL. Falha = a última leitura boa (ou [] sem nenhuma), sem travar a tela."""
    agora = time.time()
    with _TRAVA:
        if _CACHE["linhas"] is not None and agora - _CACHE["lido"] < TTL:
            return _CACHE["linhas"]
        if agora - _CACHE["falhou"] < ESPERA_ERRO:
            return _CACHE["linhas"] or []
        try:
            _CACHE["linhas"] = livro_banco.ler(LIVRO, ABA, fonte_api._token())
            _CACHE["lido"] = agora
        except Exception as e:     # noqa: BLE001 — sem rede ou contagem que não bate: a última boa
            _CACHE["falhou"] = agora
            print("[disp_fechamento] leitura falhou:", type(e).__name__, str(e)[:120], flush=True)
        return _CACHE["linhas"] or []


def invalidar():
    with _TRAVA:
        _CACHE.update(linhas=None, lido=0.0, falhou=0.0)


def fechados(linhas=None):
    """{"2026-10": "2026-11-13T11:40:00-03:00"}: os meses fechados e quando."""
    out = {}
    for l in (_linhas() if linhas is None else linhas):
        m = str(l.get("mes") or "").strip()[:7]
        if m:
            out[m] = max(out.get(m, ""), str(l.get("fechado_em") or ""))
    return out


def por_dia(usina, ano, mes, linhas=None):
    """{date: disp %} da usina no mês fechado ({} quando ela não tem linha: fica sem número), ou None com o mês aberto
    (a conta de sempre)."""
    if not ligado():
        return None
    linhas = _linhas() if linhas is None else linhas
    k = chave(ano, mes)
    if k not in fechados(linhas):
        return None
    out = {}
    for l in linhas:
        if str(l.get("mes") or "").strip()[:7] != k or str(l.get("usina") or "").strip() != usina:
            continue
        d, v = _dia(l.get("dia")), _num(l.get("disp_pct"))
        if d is not None and v is not None:
            out[d] = v
    return dict(sorted(out.items()))


def situacao(ano, mes, hoje=None):
    """O que a tela diz do mês: {"fechado": True, "fechado_em": "13/11/2026"}, {"fechado": False, "fecha_em":
    "10/12/2026"}, ou None antes de 10/2026 (a base da Grid, que não passa por aqui)."""
    if (ano, mes) < DESDE:
        return None
    em = fechados().get(chave(ano, mes)) if ligado() else None
    if em:
        d = _dia(em)
        return {"fechado": True, "fechado_em": d.strftime("%d/%m/%Y") if d else ""}
    return {"fechado": False, "fecha_em": fecha_em(ano, mes).strftime("%d/%m/%Y")}


def a_fechar(hoje, linhas=None):
    """Os meses (ano, mes) que já passaram do dia do fechamento e ainda estão abertos, do mais antigo."""
    feitos = fechados(linhas)
    out, a, m = [], DESDE[0], DESDE[1]
    while fecha_em(a, m) <= hoje:
        if chave(a, m) not in feitos:
            out.append((a, m))
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return out


def linhas_do_mes(ano, mes, usinas, disp_dias, agora, origem):
    """As linhas do livro para fechar o mês: o número de cada usina em cada dia, como `disp_dias(usina, ano, mes)`
    devolve agora. Dia sem número não entra."""
    k, em = chave(ano, mes), agora.isoformat(timespec="seconds")
    out = []
    for u in sorted(set(usinas)):
        for d, v in sorted((disp_dias(u, ano, mes) or {}).items()):
            if v is None or (d.year, d.month) != (ano, mes):
                continue
            out.append({"mes": k, "usina": u, "dia": d.isoformat(), "disp_pct": round(float(v), 4),
                        "fechado_em": em, "origem": origem})
    return out


def fechar(ano, mes, linhas, tok):
    """Grava o mês fechado (soma ao livro e confere). Recusa o mês já fechado e o mês sem nenhuma linha."""
    k = chave(ano, mes)
    if not linhas:
        raise livro_banco.GravacaoErro("nenhum número para fechar %s: o mês fica aberto" % k)
    if any(l.get("mes") != k for l in linhas):
        raise livro_banco.GravacaoErro("linha de outro mês no fechamento de %s" % k)
    invalidar()
    if k in fechados(livro_banco.ler(LIVRO, ABA, tok)):
        raise livro_banco.GravacaoErro("%s já está fechado: reabra antes de fechar de novo" % k)
    n = livro_banco.acrescentar(LIVRO, NOME, ABA, CAB, linhas, tok)
    invalidar()
    return n


def reabrir(ano, mes, tok):
    """Tira as linhas do mês do livro (o mês volta para a conta). Devolve quantas linhas saíram."""
    k = chave(ano, mes)
    atuais = livro_banco.ler(LIVRO, ABA, tok)
    ficam = [l for l in atuais if str(l.get("mes") or "").strip()[:7] != k]
    if len(ficam) == len(atuais):
        return 0
    livro_banco.regravar(LIVRO, NOME, ABA, CAB, ficam, len(atuais), tok)
    invalidar()
    return len(atuais) - len(ficam)
