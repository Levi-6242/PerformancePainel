# -*- coding: utf-8 -*-
"""Finalizar ticket de STRINGS pela plataforma (Levi, 23/09/2026).

O pedido: *"ao clicar no inversor ver as informações do ticket e conseguir finalizar ele pela plataforma, veja como
está sendo feito a parte de tickets de strings hoje para implementarmos de forma que o que mudar na plataforma também
muda na base de dados de tickets"*. Decidido com ele: a plataforma grava DIRETO, pelo relay que já grava os tickets do
OS Creator de mesa, com as regras do Salvar do OS Creator web (repo oem, os_web/rotas_tickets.py::api_salvar).

As amostras são linhas REAIS da API em 23/09 13:16: a 312 (MTS200, PV15, criada pelo app, números como texto), a 241
(Boa Esperança do Sul, vinda do Excel, números como número e vazios como None) e o registro 119 do diário v3, que é
onde mora a OS 13762 do ticket do MTS200 (a planilha não tem coluna de OS).
"""
import datetime as dt
import pathlib
import sys

import pytest

import tickets_str_fechar as tkf

HEADERS = ["", "Usina", "Código da usina", "Cliente", "UF", "Supervisor", "Responsável", "Inversor",
           "Quantidade de strings no inversor", "Quantidade de strings no afetadas", "Causa raiz",
           "Responsabilidade da Grid Co.?", "Início da ocorrência", "Início do chamado pela Grid Co.",
           "Fim da ocorrência", "Indisponibilidade (horas)", "Indisponibilidade da Grid Co. (horas)",
           "Comentários para os clientes", "Comentários gerais"]
V312 = ["", "MTS200", "", "", "", "", "", "Inversor 1.6", "", "1", "", "", "2026-09-17 06:00:02",
        "2026-09-17 11:00:34", "", "", "", "", "PV15 com corrente nula em 17/09/2026 06:00"]
V241 = [None, "Boa Esperança do Sul 1 e 2", 0, "Thopen", "Sao Paulo", "Fred Alexandrino", None, "Inversor 1.10", 20, 1,
        "Solicitada uma investigação do time de campo", None, "2026-08-25 14:00:00", "2026-08-26 11:40:00", None, 4, 0,
        None, "27/08: Boa Esperança do Sul 1 - OS 12261"]
DH = ["quando", "quem", "aba", "linha", "impressao", "Causa raiz", "Responsabilidade da Grid Co.?", "Início da ocorrência",
      "Início do chamado pela Grid Co.", "Fim da ocorrência", "Comentários gerais", "OS", "Ativo", "Status do ticket"]
D119 = ["2026-09-17 11:00:36", "Levi Maia", "Strings", 312, "mts200|inversor 1.6", "", "", "", "2026-09-17 11:00:34", "",
        "", "13762", "", "OS Programada"]
AGORA = dt.datetime(2026, 9, 23, 13, 20, 0)
ESPERADO_312 = {"usina_planilha": "MTS200", "inversor": "Inversor 1.6", "desde": "17/09/2026"}


def _ln(n, valores, headers=HEADERS):
    return {"row_number": n, "headers": list(headers), "values": list(valores), "formulas": []}


def _diario(*regs):
    return [_ln(i + 2, r, DH) for i, r in enumerate(regs)]


# ── o que o OS Creator já faz, e a plataforma tem de fazer igual ────────────────
def test_impressao_e_a_mesma_do_os_creator():
    """O registro 119 do diário real foi gravado pelo OS Creator com esta impressão; a nossa tem de casar com ele."""
    assert tkf.impressao(tkf.linha_dict(_ln(312, V312))) == "mts200|inversor 1.6"


def test_diario_por_cima_traz_a_os_e_o_status():
    atual = tkf.aplicar_diario(tkf.linha_dict(_ln(312, V312)), tkf.registros(_diario(D119)))
    assert atual["OS"] == "13762" and atual["Status do ticket"] == "OS Programada"
    assert atual["Comentários gerais"] == "PV15 com corrente nula em 17/09/2026 06:00", "vazio no registro não apaga"


def test_registro_de_outra_ocorrencia_na_mesma_linha_e_ignorado():
    """Linha apagada no Excel desce as de baixo: o registro da 312 passa a apontar para outro ticket, e aplicar
    corrigiria a ocorrência errada em silêncio."""
    outro = list(V312)
    outro[1] = "MTS100"
    atual = tkf.aplicar_diario(tkf.linha_dict(_ln(312, outro)), tkf.registros(_diario(D119)))
    assert not atual.get("OS")


def test_vale_o_registro_mais_novo_da_linha():
    novo = list(D119)
    novo[0], novo[11] = "2026-09-20 08:00:00", "14000"
    assert tkf.aplicar_diario(tkf.linha_dict(_ln(312, V312)), tkf.registros(_diario(novo, D119)))["OS"] == "14000"


def test_data_nos_formatos_da_planilha_e_da_tela():
    assert tkf.para_iso("2026-09-17T06:00") == "2026-09-17 06:00:00"
    assert tkf.para_iso("23/09/2026 13:20") == "2026-09-23 13:20:00"
    assert tkf.para_iso("2026-09-17 06:00:02.51") == "2026-09-17 06:00:02"
    assert tkf.para_dt("A ser verificado") is None


# ── o que vai para o banco ─────────────────────────────────────────────────────
def test_o_put_leva_a_linha_inteira_so_com_o_fim_mudado():
    """O PUT da API troca a linha INTEIRA: coluna que não vai volta vazia (22/09). Ordem, tipos e a coluna sem nome da
    frente seguem como estão; só o Fim muda."""
    ln = _ln(241, V241)
    corpo = tkf.corpo_da_linha(ln, tkf.linha_dict(ln), "2026-09-23 13:20:00")
    assert corpo["headers"] == HEADERS
    esperado = ["" if v is None else v for v in V241]
    esperado[HEADERS.index("Fim da ocorrência")] = "2026-09-23 13:20:00"
    assert corpo["values"] == esperado
    assert corpo["values"][HEADERS.index("Quantidade de strings no inversor")] == 20, "número continua número"


def test_o_diario_grava_o_retrato_inteiro_e_nao_perde_a_os():
    """Dos registros de uma linha só o mais novo vale. Um registro só com o Fim faria a OS 13762 sumir da tela do OS
    Creator, porque a OS só existe no diário."""
    atual = tkf.aplicar_diario(tkf.linha_dict(_ln(312, V312)), tkf.registros(_diario(D119)))
    corpo = tkf.corpo_do_diario(atual, "2026-09-23 13:20:00", "Levi Maia (plataforma)", AGORA)
    assert corpo["headers"] == DH == tkf.COLUNAS
    reg = dict(zip(corpo["headers"], corpo["values"]))
    assert (reg["quando"], reg["quem"], reg["aba"], reg["linha"], reg["impressao"]) == \
        ("2026-09-23 13:20:00", "Levi Maia (plataforma)", "Strings", 312, "mts200|inversor 1.6")
    assert reg["Fim da ocorrência"] == "2026-09-23 13:20:00"
    assert (reg["OS"], reg["Status do ticket"]) == ("13762", "OS Programada")
    assert reg["Início da ocorrência"] == "2026-09-17 06:00:02"
    assert reg["Comentários gerais"] == "PV15 com corrente nula em 17/09/2026 06:00"


# ── o que impede gravar ────────────────────────────────────────────────────────
@pytest.mark.parametrize("campo,valor", [("usina_planilha", "MTS100"), ("inversor", "Inversor 1.7"),
                                         ("desde", "18/09/2026")])
def test_linha_que_virou_outro_ticket_nao_grava(campo, valor):
    esperado = dict(ESPERADO_312, **{campo: valor})
    with pytest.raises(tkf.Recusa) as e:
        tkf.conferir(tkf.linha_dict(_ln(312, V312)), esperado)
    assert e.value.status == 409 and "Nada foi gravado" in str(e.value)


def test_ticket_que_ja_tem_fim_nao_grava():
    v = list(V312)
    v[HEADERS.index("Fim da ocorrência")] = "2026-09-22 10:00:00"
    with pytest.raises(tkf.Recusa) as e:
        tkf.conferir(tkf.linha_dict(_ln(312, v)), ESPERADO_312)
    assert e.value.status == 409 and "já tem Fim" in str(e.value)


@pytest.mark.parametrize("fim,trecho", [("lixo", "inválido"), ("2026-09-16T10:00", "antes do início"),
                                        ("2026-09-24T13:20", "no futuro")])
def test_fim_invalido_nao_grava(fim, trecho):
    with pytest.raises(tkf.Recusa) as e:
        tkf.validar_fim(fim, tkf.linha_dict(_ln(312, V312)), AGORA)
    assert e.value.status == 400 and trecho in str(e.value)


# ── a orquestração, com a API de mentira ───────────────────────────────────────
class _Banco:
    """Aba 128 + diário 399 em memória. O PUT troca a linha INTEIRA (como a API real)."""

    def __init__(self, linhas, diario, falha=None):
        self.abas = {128: {ln["row_number"]: ln for ln in linhas}, 399: {ln["row_number"]: ln for ln in diario}}
        self.falha, self.chamadas = falha or {}, []

    def ler(self, sid):
        if ("ler", sid) in self.falha:
            raise OSError("sem rede")
        return [dict(v) for _, v in sorted(self.abas[sid].items())]

    def gravar(self, metodo, sid, row, corpo):
        self.chamadas.append((metodo, sid, row, corpo))
        st = self.falha.get((metodo, sid))
        if st:
            return st, '{"error":"recusado"}'
        if metodo == "PUT":
            self.abas[sid][row] = {"row_number": row, "headers": corpo["headers"], "values": corpo["values"]}
        else:
            n = max(self.abas[sid] or [1]) + 1
            self.abas[sid][n] = {"row_number": n, "headers": corpo["headers"], "values": corpo["values"]}
        return 200, '{"ok":true}'


def _fin(banco, **kw):
    args = dict(linha=312, esperado=ESPERADO_312, fim="2026-09-23T13:20", quem="Levi Maia (plataforma)")
    args.update(kw)
    return tkf.finalizar(args["linha"], args["esperado"], args["fim"], args["quem"],
                         ler_aba=banco.ler, gravar=banco.gravar, agora=AGORA)


def test_finalizar_grava_a_linha_e_o_diario_nesta_ordem():
    b = _Banco([_ln(312, V312)], _diario(D119))
    r = _fin(b)
    assert r == {"ok": True, "linha": 312, "fim": "2026-09-23 13:20:00", "confirmado": True, "aviso": ""}
    assert [(m, s, row) for m, s, row, _ in b.chamadas] == [("PUT", 128, 312), ("POST", 399, None)], \
        "planilha antes do diário: registrar antes de saber se gravou criaria um restaurado de algo que não existe"
    gravada = dict(zip(HEADERS, b.abas[128][312]["values"]))
    assert gravada["Fim da ocorrência"] == "2026-09-23 13:20:00" and gravada["Usina"] == "MTS200"


def test_sem_o_diario_nada_e_gravado():
    b = _Banco([_ln(312, V312)], _diario(D119), falha={("ler", 399): True})
    with pytest.raises(tkf.Recusa) as e:
        _fin(b)
    assert e.value.status == 502 and not b.chamadas, "sem ler o diário, o retrato novo apagaria a OS vinculada"


def test_linha_que_sumiu_nao_grava():
    b = _Banco([_ln(311, V312)], _diario(D119))
    with pytest.raises(tkf.Recusa) as e:
        _fin(b)
    assert e.value.status == 404 and not b.chamadas


def test_banco_recusou_o_put_nao_escreve_no_diario():
    b = _Banco([_ln(312, V312)], _diario(D119), falha={("PUT", 128): 500})
    with pytest.raises(tkf.Recusa) as e:
        _fin(b)
    assert e.value.status == 502 and [c[0] for c in b.chamadas] == ["PUT"]


def test_diario_recusado_depois_do_put_avisa():
    b = _Banco([_ln(312, V312)], _diario(D119), falha={("POST", 399): 500})
    r = _fin(b)
    assert r["ok"] and r["confirmado"] and "diário" in r["aviso"]


def test_sem_quem_nao_grava():
    b = _Banco([_ln(312, V312)], _diario(D119))
    with pytest.raises(tkf.Recusa) as e:
        _fin(b, quem="   ")
    assert e.value.status == 400 and not b.chamadas


def test_releitura_sem_o_fim_nao_confirma():
    """A API respondeu 200 mas a linha relida não tem o Fim: a tela não pode esconder o ticket."""
    b = _Banco([_ln(312, V312)], _diario(D119))
    antigo = b.gravar

    def _engole(metodo, sid, row, corpo):
        if metodo == "PUT":
            b.chamadas.append((metodo, sid, row, corpo))
            return 200, "{}"
        return antigo(metodo, sid, row, corpo)
    b.gravar = _engole
    assert _fin(b)["confirmado"] is False


def test_hora_de_brasilia_mesmo_com_o_servidor_em_utc():
    """O servidor Linux roda em UTC (22/09). O diário ordena por `quando` em texto: hora de parede errada põe o registro
    fora de ordem com os do OS Creator, que grava em Brasília."""
    utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    assert abs((utc - dt.timedelta(hours=3)) - tkf.agora_brasilia()) < dt.timedelta(seconds=5)


# ── o contrato do diário é do OS Creator ───────────────────────────────────────
OEM = pathlib.Path(r"C:\GridcoBuild\oem\os_creator")


def test_contrato_do_diario_bate_com_o_oem(monkeypatch):
    """Dois gravadores do mesmo diário: colunas, nome da aba e impressão têm de ser os mesmos. Só roda onde o clone do
    oem existe (a máquina do Levi); no servidor, pula."""
    if not (OEM / "tickets_diario.py").exists():
        pytest.skip("clone do oem ausente")
    monkeypatch.syspath_prepend(str(OEM))
    for m in ("tickets_diario", "tickets_escrita", "tickets_calc"):
        sys.modules.pop(m, None)
    import tickets_calc
    import tickets_diario
    assert tkf.CAMPOS == tickets_diario.CAMPOS and tkf.COLUNAS == tickets_diario.COLUNAS
    assert tkf.NOME_DIARIO == tickets_diario.NOME_ABA
    oc = tkf.linha_dict(_ln(241, V241))
    assert tkf.impressao(oc) == tickets_diario.impressao("Strings", oc)
    for v in ("2026-09-17T06:00", "23/09/2026 13:20", "2026-09-17 06:00:02", "17/09/2026", "lixo"):
        assert tkf.para_dt(v) == tickets_calc._para_dt(v)
