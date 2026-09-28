# -*- coding: utf-8 -*-
"""OS de TRACKER criada direto da plataforma (Levi, 25/09/2026, item 4 da lista: "clico no botão, vou clicando nos
trackers e aí preencho responsável; a data do incidente será a data que o tracker parou e a data programada sempre um
dia para frente").

A OS nasce pela API do OS Creator web (proxy /os/ da plataforma, sessão do Fracttal de quem está logado), com o plano
"Verificação de Tracker Parado" — o mesmo POST que a tela do OS Creator faz. Aqui ficam:
  - a rota que diz DESDE QUANDO cada tracker está parado (a data do incidente), pela mesma varredura da curva que a
    lista de parados usa (`_trk_parado_desde_hist`), com o livro de ocorrências como reserva só na API PV — igual ao
    `_pv_parados_rows`;
  - as regras puras da tela (casar a usina e o ativo do Fracttal, datas, lotes e o corpo do POST), rodadas no node.
"""
import json
import pathlib
import shutil
import subprocess
from datetime import datetime, timedelta

import pytest

import app


# ── a rota "parado desde" ─────────────────────────────────────────────────────
def _cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return app.app.test_client()


def test_parado_desde_vem_da_varredura_da_curva(monkeypatch):
    """Mesmo motor da lista de parados: o histórico de eventos dia a dia (trk_eventos)."""
    hoje = datetime.now().date()
    ontem, anteontem = hoje - timedelta(days=1), hoje - timedelta(days=2)
    ev = {
        anteontem.isoformat(): {"297381": {"cobertura": 1.0, "eventos": [{"tracker": "TRK7", "parada": "13:40", "retorno": None}]}},
        ontem.isoformat(): {"297381": {"cobertura": 1.0, "eventos": [{"tracker": "TRK7", "parada": "06:30", "retorno": None}]}},
    }
    monkeypatch.setattr(app, "_trk_eventos", ev)
    monkeypatch.setattr(app, "_TRACKER_WATCH_OK", False)   # o livro real desta máquina tem o 297381|TRK9 aberto
    d = _cli(monkeypatch).get("/api/trackers/parado-desde?fonte=pv&plant_id=297381&trackers=TRK7,TRK9").get_json()
    # TRK7 girou de manhã e travou à tarde anteontem, e não voltou mais: a cadeia começa ali
    assert d["desde"]["TRK7"] == f"{anteontem.isoformat()}T13:40"
    assert d["desde"]["TRK9"] is None, "sem evento nenhum: a tela avisa e deixa a pessoa pôr a hora"
    assert d["origem"] == {"TRK7": "curva", "TRK9": None}


def test_sem_varredura_a_api_pv_cai_no_livro_de_ocorrencias(monkeypatch):
    """Reserva do `_pv_parados_rows`: a data de detecção do livro (tracker_watch), sem os segundos."""
    monkeypatch.setattr(app, "_trk_eventos", {})

    class _Livro:
        @staticmethod
        def get_issues_json():
            return {"active": {"297381|TRK3": {"data_deteccao": "2026-09-20T06:31:12"}}}
    monkeypatch.setattr(app, "_tw", _Livro, raising=False)
    monkeypatch.setattr(app, "_TRACKER_WATCH_OK", True)
    c = _cli(monkeypatch)
    d = c.get("/api/trackers/parado-desde?fonte=pv&plant_id=297381&trackers=TRK3").get_json()
    assert d["desde"]["TRK3"] == "2026-09-20T06:31"
    # o livro guarda a hora da DETECÇÃO, não a da parada (26/09: nesta máquina, sem curva da Embu Guaçu 2, dois
    # trackers parados havia dias vieram "desde 23:28" de hoje, a hora em que o livro os reabriu) — a tela avisa
    assert d["origem"]["TRK3"] == "livro"
    # o livro é da API PV: noutra fonte o mesmo par (pid|tracker) não quer dizer nada
    assert c.get("/api/trackers/parado-desde?fonte=pg&plant_id=297381&trackers=TRK3").get_json()["desde"]["TRK3"] is None


def test_parado_desde_sem_usina_ou_sem_tracker_e_400(monkeypatch):
    c = _cli(monkeypatch)
    assert c.get("/api/trackers/parado-desde?fonte=pv&trackers=TRK1").status_code == 400
    assert c.get("/api/trackers/parado-desde?fonte=pv&plant_id=1").status_code == 400


# ── a tela ────────────────────────────────────────────────────────────────────
MON = (pathlib.Path(app.__file__).resolve().parents[1] / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")


def _func(nome, fim="\n}\n"):
    i = MON.index(f"function {nome}(")
    return MON[i:MON.index(fim, i) + len(fim)]


def _node(js):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    p = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


_PURAS = ("_trkOsNorm", "_trkOsUsinaMatch", "_trkOsAlvoPorCode", "_trkOsLocalISO", "_trkOsProgPadrao", "_trkOsLotes",
          "_trkOsCorpo")


def _rodar(expr):
    i = MON.index("const TRK_OS_FRASE=")
    const = MON[i:MON.index("\n", i)] + "\n"                     # a frase do plano, a mesma que a tela manda
    js = const + "".join(_func(n) for n in _PURAS) + f"process.stdout.write(JSON.stringify({expr}));"
    return _node(js)


def test_usina_casa_pelo_nome_do_fracttal_mesmo_com_espaco_e_acento_diferentes():
    lista = ["Thopen - Araçoiaba da Serra 1 - SP", "Thopen - Belo Jardim 1 - PE", "Thopen - Colorado 1 - PR",
             "Thopen - Colorado 2 - PR"]
    # o de-para tem "1- SP" e espaço duplo; a lista do OS Creator é a verdade (o POST exige o nome EXATO dela)
    assert _rodar(f"_trkOsUsinaMatch(['Thopen - Araçoiaba da Serra 1- SP'], {json.dumps(lista)})") == lista[0]
    assert _rodar(f"_trkOsUsinaMatch(['Thopen - Belo Jardim  1 - PE'], {json.dumps(lista)})") == lista[1]
    # 1º candidato sem par → tenta o seguinte (nome do BD_Performance, depois o da plataforma)
    assert _rodar(f"_trkOsUsinaMatch([null, 'x', 'Thopen - Colorado 2 - PR'], {json.dumps(lista)})") == lista[3]
    # 'Colorado' está contido em DUAS usinas: não chuta, devolve null e a pessoa escolhe
    assert _rodar(f"_trkOsUsinaMatch(['Colorado'], {json.dumps(lista)})") is None


def test_ativo_do_fracttal_casa_pelo_code_do_de_para():
    alvos = [{"id": 1, "code": "THPN-CLR100-ETKR1", "label": "Estrutura Trackers"},
             {"id": 7, "code": "THPN-CLR100-ETKR12.100", "label": "Tracker 12.100"}]
    assert _rodar(f"_trkOsAlvoPorCode('thpn-clr100-etkr12.100', {json.dumps(alvos)})")["id"] == 7
    assert _rodar(f"_trkOsAlvoPorCode('', {json.dumps(alvos)})") is None
    assert _rodar(f"_trkOsAlvoPorCode('XXX', {json.dumps(alvos)})") is None


def test_programada_e_um_dia_depois_de_agora():
    assert _rodar("_trkOsProgPadrao(new Date(2026,8,25,22,47,31))") == "2026-09-26T22:47"
    assert _rodar("_trkOsProgPadrao(new Date(2026,8,30,9,5))") == "2026-10-01T09:05"
    assert _rodar("_trkOsLocalISO(new Date(2026,0,3,7,4))") == "2026-01-03T07:04"


_ITENS = [
    {"k": "a", "usinaFr": "Thopen - Colorado 1 - PR", "cliente": "Thopen", "base": "Verificação de Tracker Parado",
     "evento": "2026-09-20T06:30", "gerar": True, "obs": "Tracker parado, verificar e normalizar.",
     "alvo": {"id": 7, "code": "THPN-CLR100-ETKR12.100", "label": "Tracker 12.100", "tipo": "Estrutura Trackers",
              "plano_id_task": 55, "plano_id_item": 1, "linkar": False}},
    {"k": "b", "usinaFr": "Thopen - Colorado 1 - PR", "cliente": "Thopen", "base": "Verificação de Tracker Parado",
     "evento": "2026-09-20T06:30", "gerar": True, "obs": "Tracker parado, verificar e normalizar.",
     "alvo": {"id": 8, "code": "THPN-CLR100-ETKR13.100", "label": "Tracker 13.100", "tipo": "Estrutura Trackers",
              "plano_id_task": 55, "plano_id_item": 1, "linkar": False}},
    # mesmo dia, outra hora de parada → outro POST (o OS Creator aceita UMA data de incidente por pedido)
    {"k": "c", "usinaFr": "Thopen - Colorado 1 - PR", "cliente": "Thopen", "base": "Verificação de Tracker Parado",
     "evento": "2026-09-22T13:10", "gerar": True, "obs": "Tracker parado, verificar e normalizar.",
     "alvo": {"id": 9, "code": "THPN-CLR100-ETKR30.100", "label": "Tracker 30.100", "tipo": "Estrutura Trackers",
              "plano_id_task": 55, "plano_id_item": 1, "linkar": False}},
    # já tem ticket aberto → OS sem ticket novo, e isso também separa o pedido (a caixa é uma por pedido)
    {"k": "d", "usinaFr": "Thopen - Colorado 1 - PR", "cliente": "Thopen", "base": "Verificação de Tracker Parado",
     "evento": "2026-09-20T06:30", "gerar": False, "obs": "Tracker parado, verificar e normalizar.",
     "alvo": {"id": 10, "code": "THPN-CLR100-ETKR40.100", "label": "Tracker 40.100", "tipo": "Estrutura Trackers",
              "plano_id_task": 55, "plano_id_item": 1, "linkar": False}},
]


def test_lotes_sao_por_usina_hora_de_parada_e_ticket():
    lotes = _rodar(f"_trkOsLotes({json.dumps(_ITENS)})")
    assert [(l["evento"], l["gerar"], [i["k"] for i in l["itens"]]) for l in lotes] == [
        ("2026-09-20T06:30", True, ["a", "b"]), ("2026-09-22T13:10", True, ["c"]), ("2026-09-20T06:30", False, ["d"])]


def test_corpo_do_post_e_o_mesmo_da_tela_do_os_creator():
    resp = {"id_personnel": 321, "name": "Fulano de Tal"}
    c = _rodar(f"_trkOsCorpo(_trkOsLotes({json.dumps(_ITENS)})[0], {json.dumps(resp)}, '2026-09-26T22:47')")
    assert c["frase"] == "verificacao de tracker parado" and c["modo"] == "geracao"
    assert c["base"] == "Verificação de Tracker Parado"
    assert c["evento"] == "2026-09-20T06:30" and c["programada"] == "2026-09-26T22:47"
    assert c["gerar_ticket"] is True and c["responsavel"] == resp
    it = c["itens"][0]
    assert it["asset"] == {"id": 7, "code": "THPN-CLR100-ETKR12.100", "label": "Tracker 12.100",
                           "tipo": "Estrutura Trackers", "usina": "Thopen - Colorado 1 - PR", "cliente": "Thopen"}
    assert (it["plano_id_task"], it["plano_id_item"], it["linkar"]) == (55, 1, False)
    assert it["note"] == "Tracker parado, verificar e normalizar." and it["qtd_ticket"] == 1
    assert it["os_pai"] == "" and it["imagens"] == []


def test_tela_de_trackers_tem_o_botao_e_o_chip_seleciona_no_modo_os():
    assert "${_trkOsBtn()}" in _func("renderTrackers"), "o botão fica no cabeçalho da tabela de trackers"
    chip = _func("_trkChip")
    assert "trkOsToggle(" in chip and "toggleTrkHide(" in chip, "no modo OS o clique seleciona; fora dele, oculta no gráfico"
    criar = MON[MON.index("window.trkOsCriar="):]
    assert "'/os/api/performance/criar'" in criar[:4000], "a OS nasce pela API do OS Creator (proxy /os/)"
    assert "const TRK_OS_FRASE='verificacao de tracker parado'" in MON


def test_trocar_de_aba_ou_de_fonte_sai_do_modo_os_de_trackers():
    for f in ("window.setView=", "window.setSource="):
        linha = MON[MON.index(f):MON.index("\n", MON.index(f))]
        assert "trkOsMode=false" in linha and "_trkOsSel.clear()" in linha, f


def test_janela_diz_quando_a_hora_nao_e_da_parada():
    """Hora da curva passa quieta; hora do livro (detecção) e falta de hora pedem conferência — a pessoa não pode
    tomar a hora em que o livro reabriu a ocorrência pela hora em que o tracker parou."""
    js = ("const _he=s=>String(s==null?'':s);" + _func("_trkCor") + _func("_trkOsLocalISO") + _func("_trkOsAlvoOpts")
          + _func("_trkOsGrupoHTML")
          + "const it=(tid,o,reg)=>({tid,status:'parado',code:'C'+tid,situacao:'casado',alvoId:'1',alvoDepara:'1',ticket:'',"
            "desde:'2026-09-23T16:10',desdeOrigem:o,desdeReg:reg});"
          + "const g={usina:'Embu Guaçu 2 (120)',usinaFr:'Thopen - Embu Guaçu 1 - SP',alvos:[{id:1,code:'C',label:'Tracker 18.100'}],"
            "erroAlvos:'',itens:[it('TRK18','curva',true),it('TRK19','livro',false),it('TRK24',null,false)]};"
          + "const h=_trkOsGrupoHTML({usinasFr:[g.usinaFr],gerar:true},g,0,false,'');"
          + "const linhas=h.split('<tr style').slice(1);"
          + "process.stdout.write(JSON.stringify(linhas.map(l=>[l.includes('confira'),l.includes('detecção')])));")
    assert _node(js) == [[False, False], [True, True], [True, False]]


def test_abrir_a_janela_reresolve_o_de_para_de_cada_tracker():
    """O de-para chega DEPOIS do drill (_loadDepara): tracker clicado nesse meio-tempo ficava sem o code do Fracttal.
    Ao abrir a janela, cada marcado é refeito com o que a tela sabe agora (de-para e ticket)."""
    abrir = MON[MON.index("window.trkOsAbrir="):]
    abrir = abrir[:abrir.index("\n};\n")]
    assert "_trkOsReg(" in abrir
