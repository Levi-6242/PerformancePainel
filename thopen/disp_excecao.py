# -*- coding: utf-8 -*-
"""A disponibilidade por exceção: o número do dia que o Levi trouxe, no lugar da conta (06/11/2026).

Levi, 06/11/2026, com a planilha "disponibilidades outubro.xlsx" e a lista das usinas: "pegue a disponibilidade dessas
UFVs e coloque como disponibilidade de outubro segundo a lista, será uma exceção para outubro!". São as usinas do
outubro em que a conta (as OS da Ronda COS na plataforma, ou os comentários do BD_Thopen) não valia para o mês: o
número do dia passa a ser o da planilha. Só no mês que tem linha no livro: os outros meses seguem a conta de sempre.

De onde vem: o livro `thopen_disp_excecao` · `disp_dia` (1 linha = 1 parte da usina × 1 dia), gravado uma vez a partir
da planilha (a carga não é do 5080: o 5080 só lê). A parte é o nome do supervisório da lista do Levi (as Sol Maior GD I
a V são a Lyon; as Pacaembu 1.1 e 1.2, a Areia Branca; as Nova Iguaçu 2.1 e 2.2, a Nova Iguaçu; as Segredo 1.1 a 1.5,
a Segredo), com o `kwp` dela (a soma dos inversores na aba Equipamentos). O dia da usina = Σ(kWp × disp) ÷ Σ kWp das
partes; o mês = a média dos dias, como sempre.

Relido a cada 10 min. Se o banco não responde, vale a última leitura boa; sem nenhuma, a conta de sempre (nunca um 0).
"""
import threading
import time
import datetime as dt

import fonte_api
import livro_banco

LIVRO, ABA = "thopen_disp_excecao", "disp_dia"
TTL = 600                      # s
ESPERA_ERRO = 60               # s sem tentar de novo depois de uma falha
_TRAVA = threading.Lock()
_CACHE = {"linhas": None, "lido": 0.0, "falhou": 0.0}


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


def combinar(linhas, usina, ano, mes):
    """{date: disp %} da usina no mês, ponderado pelo kWp das partes. {} sem linha. Linha sem dia, sem disp ou sem
    kWp não entra (a carga confere antes de gravar: não há nenhuma assim)."""
    soma = {}
    for l in linhas or ():
        if str(l.get("usina") or "").strip() != usina:
            continue
        d, v, w = _dia(l.get("dia")), _num(l.get("disp_pct")), _num(l.get("kwp"))
        if d is None or v is None or not w or (d.year, d.month) != (ano, mes):
            continue
        a = soma.setdefault(d, [0.0, 0.0])
        a[0] += w * v
        a[1] += w
    return {d: s / w for d, (s, w) in sorted(soma.items())}


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
            print("[disp_excecao] leitura falhou:", type(e).__name__, str(e)[:120], flush=True)
        return _CACHE["linhas"] or []


def por_dia(usina, ano, mes):
    """{date: disp %} por exceção da usina no mês, ou None (a usina segue a conta de sempre)."""
    return combinar(_linhas(), usina, ano, mes) or None


def invalidar():
    """O Atualizar da conta da Grid relê também a exceção."""
    with _TRAVA:
        _CACHE["lido"] = 0.0
        _CACHE["falhou"] = 0.0
