# -*- coding: utf-8 -*-
"""O que deixava lenta a abertura dos trackers de uma usina do banco da Thopen (Levi, 18/11/2026: "Trackers da Thopen:
antes de corrigir, medir onde vai o tempo (consulta lenta ou falta de índice)").

Medido em 18/11 (Aparecida 3, 66 trackers, 24.051 pontos no dia):
- o banco NÃO é o gargalo: a consulta usa o índice (power_plant_id, timestamp) e roda em 0,17 s lá dentro (0,45 s para
  trazer as linhas);
- em produção, três aberturas SEGUIDAS levaram 6,8 s, 5,0 s e 4,9 s com a curva já em memória: o tempo é do cálculo em
  Python, refeito a cada abertura;
- 69% desse cálculo era uma função só, a `_trk_mins`, que tira a hora de cada ponto com expressão regular e era chamada
  383 mil vezes para 24 mil pontos.

As duas correções: a hora do ponto sai por posição no formato de sempre (o resultado é o MESMO da expressão regular, e
este arquivo prova), e a rota da usina serve o detalhe que o ciclo do servidor já calcula a cada volta."""
import datetime
import random
import re
import time

import pytest

import app
import trk_regua_v2


def _referencia(x):
    """A conta de antes, como estava escrita."""
    m = re.search(r"(\d{1,2}):(\d{2})", str(x))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _casos():
    fixos = ["2026-11-18T05:07:33", "2026-11-18 05:07:33", "2026-11-18T05:07", "2026-11-18T05:07:33Z", "2026-11-18T05:07:33.123456",
             "2026-11-18T23:59:59-03:00", "2026-11-18T00:00:00", "2026-11-18T24:61:00", "05:07", "5:07", "23:59:59", "", " ", "2026-11-18",
             "Sat, 12 Jul 2026 05:07:00 GMT", "2026-11-18T5:07:00", "2026-1-18T05:07:00", "18/11/2026 05:07", "abc", "12:3", "1:2:3", ":12",
             "2026-11-18T05-07-33", "2026-11-18X05:07:33", "٠٥:٠٧", "2026-11-18T٠٥:٠٧:00", "²²²²-11-18T05:07:33", "2026:11:18T05:07:33",
             "20261118T05:07:33", "2026-11-18T05:0", "2026-11-18T05:", None, 0, 307, 5.07, datetime.datetime(2026, 11, 18, 5, 7, 33),
             datetime.time(5, 7), datetime.date(2026, 11, 18)]
    rnd = random.Random(18112026)
    alfabeto = "0123456789:-T Z.+٠٥"
    solto = ["".join(rnd.choice(alfabeto) for _ in range(rnd.randint(0, 26))) for _ in range(30000)]
    perto = []
    for _ in range(30000):                                  # o formato de sempre com até 3 letras trocadas
        l = list("2026-11-18T05:07:33")
        for _k in range(rnd.randint(0, 3)):
            l[rnd.randrange(len(l))] = rnd.choice(alfabeto)
        perto.append("".join(l))
    horas = ["2026-11-%02dT%02d:%02d:%02d" % (rnd.randint(1, 30), rnd.randint(0, 23), rnd.randint(0, 59), rnd.randint(0, 59)) for _ in range(5000)]
    return fixos + solto + perto + horas


def test_a_hora_do_ponto_sai_igual_a_da_expressao_regular():
    """A conversão nova não pode mudar UM resultado: ela alimenta a régua de trackers de todas as fontes."""
    casos = _casos()
    assert len(casos) > 65000
    for c in casos:
        esperado = _referencia(c)
        assert app._trk_mins(c) == esperado, repr(c)
        assert app._trk_mins(c) == esperado, repr(c)                          # de novo: a que sai do guardado (19/11/2026)
        assert trk_regua_v2.min_do_dia(c) == esperado, repr(c)
    assert app._trk_mins("2026-11-18T05:07:33") == 307 and app._trk_mins("2026-11-18 23:59:00") == 1439


def test_no_formato_de_sempre_a_hora_nao_passa_pela_expressao_regular(monkeypatch):
    """O ganho é este: o ponto no formato "AAAA-MM-DDTHH:MM..." (o de toda curva) sai por posição."""
    def nunca(_s):
        raise AssertionError("passou pela expressão regular")
    monkeypatch.setattr(app, "_trk_mins_regex", nunca)
    monkeypatch.setattr(trk_regua_v2, "_min_do_dia_regex", nunca)
    monkeypatch.setattr(app, "_TRK_MINS_MEMO", {}, raising=False)             # nada guardado de outro teste
    for s in ("2026-11-18T05:07:33", "2026-11-18 05:07:33", "2026-11-18T05:07", "2026-11-18T05:07:33Z"):
        assert app._trk_mins(s) == 307 and trk_regua_v2.min_do_dia(s) == 307
    with pytest.raises(AssertionError):                    # fora do formato, vale a expressão regular de antes
        app._trk_mins("05:07")


# ── a cópia do detalhe ──────────────────────────────────────────────────────────────────────────────────────────────
class _Cursor:
    def __init__(self, linhas):
        self._l = linhas

    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return list(self._l)


class _Conexao:
    def __init__(self, linhas):
        self._l = linhas

    def cursor(self):
        return _Cursor(self._l)

    def close(self):
        pass


def _curvas():
    """Dois trackers andando (-50° às 06h até +50° às 18h) e um parado em 0°, de 5 em 5 min."""
    base = datetime.datetime(2026, 11, 18, 6, 0)
    pts = [base + datetime.timedelta(minutes=5 * k) for k in range(145)]
    anda = [(t, -50 + 100 * k / 144) for k, t in enumerate(pts)]
    return {"TRK01": {"atual": list(anda), "alvo": list(anda)}, "TRK02": {"atual": list(anda), "alvo": list(anda)},
            "TRK03": {"atual": [(t, 0.0) for t in pts], "alvo": list(anda)}}


@pytest.fixture
def cli(monkeypatch):
    app.app.config["TESTING"] = True
    monkeypatch.setattr(app, "_pg_trk_det_cache", {"payload": None, "ts": 0.0})
    with app.app.test_client() as c:
        yield c


def _monta_a_volta(monkeypatch):
    monkeypatch.setattr(app, "_pg_conn", lambda: _Conexao([(8, "Aparecida 3")]))
    monkeypatch.setattr(app, "_cob_entra", lambda fonte, chave: True)
    monkeypatch.setattr(app, "_pg_trk_default_date", lambda: "2026-11-18")
    monkeypatch.setattr(app, "_pg_trk_plant_curvas", lambda pid, date, date_fim=None: _curvas())
    monkeypatch.setattr(app, "_pg_trk_curvas_erro", lambda *a, **k: None)
    monkeypatch.setattr(app, "_pg_disp_hoje", lambda ov_rows=None: {})
    monkeypatch.setattr(app, "_persist_mark", lambda: None)
    return app._pg_trackers_overview()


def test_a_volta_do_ciclo_guarda_o_detalhe_de_cada_usina(cli, monkeypatch):
    """O ciclo já classifica tracker a tracker para montar o resumo, e jogava a lista fora. Agora ela fica guardada (e vai
    para o web pela cópia de sempre: a chave "pg_trk_det")."""
    ov = _monta_a_volta(monkeypatch)
    assert [r["plant_id"] for r in ov["rows"]] == ["8"] and "trackers" not in ov["rows"][0]      # o resumo segue enxuto
    det = app._pg_trk_det_cache["payload"]
    assert det["date"] == "2026-11-18" and list(det["plantas"]) == ["8"]
    d8 = det["plantas"]["8"]
    assert d8["usina"] == "Aparecida 3" and d8["total"] == 3 and [t["id"] for t in d8["trackers"]] == ["TRK01", "TRK02", "TRK03"]
    assert d8["total"] == ov["rows"][0]["total"] and d8["parados"] == ov["rows"][0]["parados"]     # o detalhe e o resumo são a MESMA conta
    assert app._persist_registry()["pg_trk_det"] is app._pg_trk_det_cache
    assert time.time() - app._pg_trk_det_cache["ts"] < 5


def test_a_rota_da_usina_serve_a_copia_sem_ir_ao_banco(cli, monkeypatch):
    _monta_a_volta(monkeypatch)
    vivo = []

    def ao_vivo(pid, date=None):
        vivo.append((pid, date))
        return {"usina": "ao vivo", "plant_id": str(pid), "date": date, "total": 0, "trackers": [], "tem_trackers": False}
    monkeypatch.setattr(app, "_pg_trackers_analise", ao_vivo)
    r = cli.get("/api/pg/trackers/8").get_json()
    assert vivo == [] and r["da_copia"] is True and r["usina"] == "Aparecida 3" and len(r["trackers"]) == 3 and 0 <= r["idade_s"] < 5
    assert r["copia_das"] == time.strftime("%H:%M", time.localtime(app._pg_trk_det_cache["ts"]))
    assert cli.get("/api/pg/trackers/8?date=2026-11-18").get_json()["da_copia"] is True and vivo == []   # o dia da cópia, dito por extenso
    # o que a cópia não cobre continua ao vivo, como antes
    assert cli.get("/api/pg/trackers/8?date=2026-11-17").get_json()["usina"] == "ao vivo" and vivo == [("8", "2026-11-17")]
    assert cli.get("/api/pg/trackers/9").get_json()["usina"] == "ao vivo"                               # usina que a volta não trouxe
    assert cli.get("/api/pg/trackers/8?vivo=1").get_json()["usina"] == "ao vivo"                        # pedido ao vivo, por extenso
    app._pg_trk_det_cache["ts"] = time.time() - app.PG_TRK_DET_VALE_S - 1                               # cópia velha demais
    assert cli.get("/api/pg/trackers/8").get_json()["usina"] == "ao vivo"
    assert len(vivo) == 4


def test_a_usina_que_falhou_na_volta_nao_entra_na_copia(cli, monkeypatch):
    """O banco fora numa usina: ela não vira "sem tracker" guardado por 15 min; a rota tenta ao vivo."""
    def analise(pid, date=None):
        return {"usina": pid, "plant_id": str(pid), "date": date, "total": 0, "parados": 0, "severos": 0, "medios": 0, "leves": 0,
                "trackers": [], "tem_trackers": False, "fonte_ok": False, "erro": "PG: fora"}
    monkeypatch.setattr(app, "_pg_conn", lambda: _Conexao([(8, "Aparecida 3")]))
    monkeypatch.setattr(app, "_cob_entra", lambda fonte, chave: True)
    monkeypatch.setattr(app, "_pg_trk_default_date", lambda: "2026-11-18")
    monkeypatch.setattr(app, "_pg_trackers_analise", analise)
    monkeypatch.setattr(app, "_pg_disp_hoje", lambda ov_rows=None: {})
    monkeypatch.setattr(app, "_persist_mark", lambda: None)
    app._pg_trackers_overview()
    assert app._pg_trk_det_cache["payload"]["plantas"] == {}
    assert cli.get("/api/pg/trackers/8").status_code == 503                                             # ao vivo, e o banco segue fora


def test_a_curva_de_strings_do_banco_diz_os_tempos_dela(monkeypatch):
    """A abertura fria da curva levou 33,5 s e 10,3 s em produção, e de fora as consultas somam 2,2 s. Antes de montar a
    cópia que se aquece sozinha (Levi, 18/11/2026), a resposta diz onde o tempo foi: a consulta, a mediana da usina e a
    montagem. A tela ignora o campo."""
    ts = datetime.datetime(2026, 11, 18, 12, 0)
    monkeypatch.setattr(app, "_pg_conn", lambda: _Conexao([(7, "INV 7", "Usina X", 1, ts, 8.0), (7, "INV 7", "Usina X", 2, ts, 7.5)]))
    monkeypatch.setattr(app, "_pg_str_med_usina", lambda pid, dia: 8.0)
    monkeypatch.setattr(app, "_trancadas", set())
    r = app._pg_strings_curva(100, "2026-11-18")
    t = r["tempos"]
    assert set(t) == {"consulta_s", "mediana_s", "mediana_de", "montagem_s", "total_s", "linhas", "lido_em"} and t["linhas"] == 2
    assert all(isinstance(t[k], float) and 0 <= t[k] < 5 for k in ("consulta_s", "mediana_s", "montagem_s", "total_s"))
    assert len(t["lido_em"]) == 8 and [i["nome_api"] for i in r["inversores"]] == ["INV 7"]         # o resto da resposta é o de sempre
    assert set(r) == {"plant_id", "data", "inversores", "mediana_usina", "tempos"}


def test_a_hora_do_ponto_convertida_fica_guardada(monkeypatch):
    """19/11/2026: depois da conta por posição, a `_trk_mins` ainda era chamada 383 a 431 mil vezes para os 24 mil
    pontos de uma usina (16 a 18 vezes por ponto). A resposta de cada texto fica guardada; o guardado é limitado."""
    monkeypatch.setattr(app, "_TRK_MINS_MEMO", {})
    assert app._trk_mins("2026-11-18T05:07:33") == 307 and app._TRK_MINS_MEMO == {"2026-11-18T05:07:33": 307}
    monkeypatch.setitem(app._TRK_MINS_MEMO, "2026-11-18T05:07:33", 999)
    assert app._trk_mins("2026-11-18T05:07:33") == 999                       # a 2ª vez sai do guardado: nenhuma conta é refeita
    assert app._trk_mins("abc") is None and "abc" in app._TRK_MINS_MEMO and app._trk_mins("abc") is None   # "sem hora" também fica
    assert app._trk_mins(datetime.datetime(2026, 11, 18, 5, 7, 33)) == 307 and "2026-11-18 05:07:33" in app._TRK_MINS_MEMO
    monkeypatch.setattr(app, "_TRK_MINS_MEMO_MAX", 5)                        # encheu, esvazia: nunca cresce sem limite
    for k in range(20):
        assert app._trk_mins("2026-11-18T05:%02d:00" % k) == 300 + k
    assert len(app._TRK_MINS_MEMO) <= 5


def _grafico():
    return {n: [{"x": t.strftime("%Y-%m-%dT%H:%M:%S"), "y": v} for t, v in d["atual"]] for n, d in _curvas().items()}


def test_o_sem_comunicacao_e_calculado_uma_vez_por_analise(monkeypatch):
    """19/11/2026: o conjunto do "sem comunicação" era calculado duas vezes sobre a mesma curva (uma para promover a
    parado, dentro da classificação, e outra para rotular): ~0,1 s por usina. Agora é uma conta só, e o resultado é o
    mesmo."""
    import inspect
    g = _grafico()
    esperado = app._trk_semcom_set(g)
    assert esperado == {"TRK03"}                                              # o sensor morto em 0,00°
    antes = [dict(id=n, status="normal") for n in g]
    app._trk_status_from_curva(antes, g)                                      # a resposta de referência, com a função de verdade
    real, vezes = app._trk_semcom_set, []
    monkeypatch.setattr(app, "_trk_semcom_set", lambda g_, jini=6 * 60, jfim=18 * 60: vezes.append((jini, jfim)) or real(g_, jini, jfim))
    lst = [dict(id=n, status="normal") for n in g]
    r = app._trk_status_from_curva(lst, g)
    assert vezes == [(360, 1080)], vezes                                      # uma vez, na janela de sempre
    assert lst == antes and {t["id"] for t in lst if t["sem_comunicacao"]} == esperado and r[0] >= 1   # o TRK03 é parado e sem comunicação
    # quem classifica sem ter o conjunto continua calculando por conta própria (os outros caminhos não mudam)
    vezes.clear()
    assert app._trk_classifica_curso(g)["TRK03"] == "parado" and len(vezes) == 1
    # e o conjunto passado é o que vale: com ele vazio, ninguém é promovido por falta de comunicação
    vezes.clear()
    sem = app._trk_classifica_curso(g, semcom=set())
    assert vezes == [] and sem == app._trk_promove_semcom(g, dict(sem), semcom=set())
    assert "semcom=sc" in inspect.getsource(app._pv_trk_refina_curva)          # o refino da API PV também fazia a conta duas vezes


def test_a_mediana_da_usina_sai_das_linhas_da_curva_sem_segunda_consulta(monkeypatch):
    """19/11/2026: a curva de strings do banco fazia duas consultas sobre a mesma tabela; a 2ª (a mediana da usina) levou
    de 0,65 a 4,7 s em produção. Com a usina inteira pedida, as linhas da 1ª já têm a resposta (igual à da consulta em
    19 usinas e 2 dias, conferido no banco)."""
    from decimal import Decimal
    ts, ts2 = datetime.datetime(2026, 11, 18, 12, 0), datetime.datetime(2026, 11, 18, 12, 5)
    D = Decimal
    linhas = [(7, "INV 7", "Usina X", 1, ts, D("8.00")), (7, "INV 7", "Usina X", 1, ts2, D("9.00")),      # 17,00
              (7, "INV 7", "Usina X", 2, ts, D("-1.00")), (7, "INV 7", "Usina X", 2, ts2, D("5.00")),    # o negativo vale zero: 5,00
              (8, "INV 8", "Usina X", 1, ts, D("3.00")),                                                 # 3,00
              (8, "INV 8", "Usina X", 2, ts, D("4.00"))]                                                 # trancada: fora
    monkeypatch.setattr(app, "_pg_conn", lambda: _Conexao(linhas))
    monkeypatch.setattr(app, "_trancadas", {app._str_key(100, 8, "2")})
    monkeypatch.setattr(app, "_pg_str_med_cache", {})

    def nao(pid, dia):
        raise AssertionError("fez a 2ª consulta")
    monkeypatch.setattr(app, "_pg_str_med_usina", nao)
    r = app._pg_strings_curva(100, "2026-11-18")
    assert r["mediana_usina"] == 5.0 and r["tempos"]["mediana_de"] == "linhas"      # [3, 5, 17]: o do meio
    assert app._pg_str_med_cache[(100, "2026-11-18")]["med"] == 5.0                  # fica onde a consulta guardava
    assert [i["mediana_usina"] for i in r["inversores"]] == [5.0, 5.0]
    # um inversor só no pedido: as linhas não são a usina inteira, vale a consulta de sempre
    idas = []
    monkeypatch.setattr(app, "_pg_str_med_usina", lambda pid, dia: idas.append((pid, dia)) or 9.0)
    r = app._pg_strings_curva(100, "2026-11-18", inv=7)
    assert idas == [(100, "2026-11-18")] and r["mediana_usina"] == 9.0 and r["tempos"]["mediana_de"] == "consulta"
