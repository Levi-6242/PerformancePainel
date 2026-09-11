# -*- coding: utf-8 -*-
"""O WEB tem de reler o cadastro sozinho quando o BD_Performance muda (10/09/2026).

Caso real: o Levi preencheu Cliente = Thopen para Cambé, Taguaí, Alvares Machado e Santo Anastacio na Info Geral;
a API mudou às 17:34, o worker reescreveu o espelho às 17:58 e releu o cadastro no ciclo seguinte — mas o app.py (web,
no ar desde 14:31) só chamava `maybe_reload_equipamentos()` num `?force=1` (botão Atualizar). Ninguém clicou, e a
Entrada (montada no web) seguiu com as 5 usinas em "Sem cliente" até as 23h.

Duas coisas se provam aqui:
  1. quando o mtime do espelho mudou, a recarga REVALIDA a base em memória antes de reler — o `bd_api.carregar()`
     padrão devolve bytes de até 30 min atrás (TTL) e a recarga leria a versão velha carimbando o mtime novo
     (a armadilha "metas só são lidas no boot", em outra roupa);
  2. o web tem um vigia (`_cadastro_watch_tick`) que faz essa checagem barata (um os.stat) sem depender de clique."""
import os

import app
import bd_api


class _Gravador:
    def __init__(self):
        self.chamadas = []

    def __call__(self, nome):
        def _f(*a, **kw):
            self.chamadas.append((nome, kw))
        return _f


def _arma(monkeypatch, tmp_path, mem=True):
    """Espelho falso com mtime conhecido; loaders e bd_api.carregar substituídos por gravadores."""
    esp = tmp_path / "BD_Performance.xlsx"
    esp.write_bytes(b"x")
    monkeypatch.setattr(app, "_bd_perf_path", lambda: str(esp))
    monkeypatch.setattr(app, "_BD_MEM", mem)
    g = _Gravador()
    for nome in ("load_equipamentos", "load_metas", "load_usina_codigos", "load_bd_trackers"):
        monkeypatch.setattr(app, nome, g(nome))
    monkeypatch.setattr(bd_api, "carregar", lambda chave, **kw: g("carregar")(chave, **kw) or b"x")
    return esp, g


def test_mtime_novo_revalida_a_memoria_antes_de_reler(monkeypatch, tmp_path):
    esp, g = _arma(monkeypatch, tmp_path)
    monkeypatch.setattr(app, "_bd_mtime", 0.0)                       # como se o boot tivesse visto outro arquivo
    app.maybe_reload_equipamentos()
    nomes = [c[0] for c in g.chamadas]
    assert nomes[0] == "carregar" and g.chamadas[0][1].get("revalidar") is True, nomes
    assert nomes[1:] == ["load_equipamentos", "load_metas", "load_usina_codigos", "load_bd_trackers"]
    # (o carimbo de _bd_mtime é do load_equipamentos REAL — e só quando o cadastro veio preenchido)


def test_mesmo_mtime_nao_faz_nada(monkeypatch, tmp_path):
    esp, g = _arma(monkeypatch, tmp_path)
    monkeypatch.setattr(app, "_bd_mtime", os.path.getmtime(str(esp)))
    app.maybe_reload_equipamentos()
    assert g.chamadas == []


def test_sem_base_em_memoria_nao_revalida_so_rele(monkeypatch, tmp_path):
    esp, g = _arma(monkeypatch, tmp_path, mem=False)
    monkeypatch.setattr(app, "_bd_mtime", 0.0)
    app.maybe_reload_equipamentos()
    assert [c[0] for c in g.chamadas] == ["load_equipamentos", "load_metas", "load_usina_codigos", "load_bd_trackers"]


def test_vigia_do_web_chama_as_duas_recargas(monkeypatch):
    g = _Gravador()
    monkeypatch.setattr(app, "maybe_reload_equipamentos", g("equipamentos"))
    monkeypatch.setattr(app, "maybe_reload_tickets", g("tickets"))
    app._cadastro_watch_tick()
    assert [c[0] for c in g.chamadas] == ["equipamentos", "tickets"]


def test_vigia_nao_morre_se_a_recarga_estourar(monkeypatch):
    def _boom():
        raise RuntimeError("planilha trancada")
    monkeypatch.setattr(app, "maybe_reload_equipamentos", _boom)
    monkeypatch.setattr(app, "maybe_reload_tickets", lambda: None)
    app._cadastro_watch_tick()                                       # não levanta
