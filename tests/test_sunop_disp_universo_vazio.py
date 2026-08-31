"""Universo vazio não vira resposta cacheada (disponibilidade por tempo da SunOp/Axis).

No boot o worker DERIVA o metadata da API — nunca o restaura do snapshot, de propósito, para
um metadata velho não se eternizar. Consequência: nos primeiros segundos `_si(inst)["meta"]`
está vazio. Se `_sunop_eventos_calc` roda nessa janela, ele calcula sobre ZERO usinas e cacheia
`disp_pid={}` como se fosse resposta; o `_build_sunop_trk_payload` então publica
`disponibilidade_tempo=None` em TODAS as usinas e fica preso nisso por um TTL inteiro.

Pego em 26/08 na verificação do deploy: 0/9 usinas com disponibilidade depois do restart, contra
92,0 / 93,0 / 84,1 no ciclo da manhã. Latente desde antes (o comentário da ETAPA 1 do prewarm já
descrevia o sintoma), mas o SUNOP_TTL de 600s dobrou o tempo que a tela fica assim.

Mesma família do `_sunop_guarda_vazio` e do "foto vazia não vira referência" do
`_sunop_str_med_ent`: leitura que não veio é DESCONHECIDA, não é zero.
"""
import app


def _prepara(monkeypatch, meta):
    monkeypatch.setattr(app, "ensure_sunop_meta", lambda inst="gridco": None)
    monkeypatch.setattr(app, "_si", lambda inst="gridco": {"meta": meta})
    monkeypatch.setitem(app._sunop_ev_cache, "gridco", {})
    monkeypatch.setattr(app, "_trk_ev_save", lambda: None)
    return app.datetime.now().strftime("%Y-%m-%d")


def test_meta_vazia_nao_fica_cacheada(monkeypatch):
    hoje = _prepara(monkeypatch, {})
    ent = app._sunop_eventos_calc("gridco", hoje)
    assert ent["disp_pid"] == {}
    assert hoje not in app._sunop_ev_cache["gridco"], \
        "universo vazio cacheado = overview preso com disponibilidade nula por um TTL inteiro"


def test_proxima_chamada_recalcula_quando_a_meta_chega(monkeypatch):
    """O que fecha o buraco: assim que o metadata carrega, o ciclo seguinte já enxerga."""
    hoje = _prepara(monkeypatch, {})
    app._sunop_eventos_calc("gridco", hoje)          # 1ª: meta vazia, não cacheia

    chamou = {"n": 0}

    def _falso_um(pid, nome, data_br, curve=None):
        chamou["n"] += 1
        return {"eventos": [], "disponibilidade": 97.5, "cobertura": 1.0, "classes": {}}

    monkeypatch.setattr(app, "_si", lambda inst="gridco": {"meta": {"MAB100": {"trackers": {"TRK_1": {}}}}})
    monkeypatch.setattr(app, "_trk_eventos_do_dia", _falso_um)
    monkeypatch.setattr(app, "_sunop_curve_for", lambda *a, **k: {})
    ent = app._sunop_eventos_calc("gridco", hoje)
    assert chamou["n"] == 1
    assert ent["disp_pid"] == {"MAB100": 97.5}
    assert hoje in app._sunop_ev_cache["gridco"], "resposta REAL tem de cachear normalmente"
