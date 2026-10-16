# -*- coding: utf-8 -*-
"""Fotos da ronda pelo Fracttal (rodada 3, 09/10/2026): 1 pedido à API por OS aberta, guardado 20 min; só imagens; o
arquivo vem pelo link (S3), que não sai para o navegador; sem credencial não pede nada; recusa por cota vira `Ocupado`
na hora. Tudo com o Fracttal falso — nada de rede."""
import io
import json
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import fotos_ronda as fr  # noqa: E402


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def fracttal(monkeypatch):
    class Lista(list):
        pass
    pedidos = Lista()
    agentes = []
    monkeypatch.setattr(fr, "_tok", {"v": "", "exp": 0.0})
    monkeypatch.setattr(fr, "_listas", {})
    monkeypatch.setattr(fr, "_fotos", fr.OrderedDict())
    monkeypatch.setattr(fr, "_minis", fr.OrderedDict())
    monkeypatch.setattr(fr.fonte_api, "segredo", lambda n: "x" if n.startswith("FRACTTAL_CLIENT") else "")

    def abrir(req, timeout=None):
        url = req.full_url
        pedidos.append(url)
        agentes.append(req.get_header("User-agent"))
        if url.endswith("/oauth/token"):
            return Resp(json.dumps({"access_token": "t", "expires_in": 3600}).encode())
        if "/api/work_orders_attachments" in url:
            return Resp(json.dumps({"data": [
                {"description": "Sujidade dos módulos — 2", "value": "https://s3/a.jpg?sig=1"},
                {"description": "planilha", "value": "https://s3/b.xlsx?sig=1"},
                {"description": "Pragas — pontual", "value": "https://s3/c.png?sig=1"}]}).encode())
        return Resp(b"\xff\xd8 foto")
    monkeypatch.setattr(fr, "_abrir", abrir)
    pedidos.agentes = agentes
    return pedidos


def test_lista_so_imagens_e_guarda_20_min(fracttal):
    a = fr.anexos(15176)
    assert [(x["desc"], x["mime"]) for x in a] == [("Sujidade dos módulos — 2", "image/jpeg"),
                                                   ("Pragas — pontual", "image/png")]
    fr.anexos("15176")
    lista = [p for p in fracttal if "/api/work_orders_attachments" in p]
    assert len(lista) == 1 and "folio=15176" in lista[0]          # o 2º veio da memória


def test_foto_baixa_pelo_link_e_indice_fora_e_semfoto(fracttal):
    corpo, mime = fr.foto(15176, 1)
    assert corpo == b"\xff\xd8 foto" and mime == "image/png" and fracttal[-1] == "https://s3/c.png?sig=1"
    with pytest.raises(fr.SemFoto):
        fr.foto(15176, 9)


def test_sem_credencial_avisa_sem_pedir(monkeypatch, fracttal):
    monkeypatch.setattr(fr.fonte_api, "segredo", lambda n: "")
    with pytest.raises(fr.SemCredencial):
        fr.anexos(15176)
    assert fracttal == []


def test_cota_do_fracttal_vira_ocupado(monkeypatch, fracttal):
    def abrir(req, timeout=None):
        if req.full_url.endswith("/oauth/token"):
            return Resp(json.dumps({"access_token": "t"}).encode())
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
    monkeypatch.setattr(fr, "_abrir", abrir)
    with pytest.raises(fr.Ocupado):
        fr.anexos(15176)


def test_token_vencido_pede_outro_uma_vez(monkeypatch, fracttal):
    estado = {"n": 0}

    def abrir(req, timeout=None):
        if req.full_url.endswith("/oauth/token"):
            return Resp(json.dumps({"access_token": "t"}).encode())
        estado["n"] += 1
        if estado["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        return Resp(json.dumps({"data": []}).encode())
    monkeypatch.setattr(fr, "_abrir", abrir)
    assert fr.anexos(15176) == [] and estado["n"] == 2


def test_miniatura_reduz(monkeypatch, fracttal):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (1280, 1700), "white").save(b, "JPEG")
    monkeypatch.setattr(fr, "_baixar", lambda url: b.getvalue())
    corpo, mime = fr.miniatura(15176, 0)
    assert mime == "image/jpeg" and max(Image.open(io.BytesIO(corpo)).size) == fr.MINI_PX


def test_miniatura_sem_pillow_vai_a_inteira(monkeypatch, fracttal):
    monkeypatch.setitem(sys.modules, "PIL", None)                # "sem Pillow": o import falha
    corpo, mime = fr.miniatura(15176, 1)
    assert (corpo, mime) == (b"\xff\xd8 foto", "image/png")


def test_todo_pedido_leva_o_nosso_agente(fracttal):
    # 09/10: a Cloudflare do Fracttal recusou o "Python-urllib/3.14" (403, error code 1010) no 1º ensaio real
    fr.foto(15176, 0)
    assert len(fracttal.agentes) == 3 and all(a and "gridco" in a for a in fracttal.agentes), fracttal.agentes
