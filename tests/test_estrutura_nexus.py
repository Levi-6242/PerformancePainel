"""A estrutura do Nexus no lugar da aba Equipamentos (fase 2, 13/10/2026; Levi: "pode fazer todas as fases! vamos pra
cima!"). A tela Base > Equipamentos das usinas do Nexus publica a visão `nexus_estrutura_usina · aba_equipamentos` (o
formato da aba) das chaves marcadas "no lugar da aba"; o cadastro da plataforma troca as linhas dessas chaves pelas da
visão. A prova principal: a usina montada no Nexus igual à aba não muda NENHUM mapa do cadastro; mudar no Nexus muda.
Nenhum teste vai ao banco: a aba e a visão são dubladas (o conftest desliga a leitura do livro: ESTRUTURA_NEXUS=0)."""
import pandas as pd
import pytest

import app
import estrutura_nexus as en
from test_porta_nexus import _sem_rede, cli, entrar_com_senha  # noqa: F401  (fixtures e passos da porta)

COLS = ["", "Cliente", "Usina", "Usina Supervisório", "Usina Fractall", "Equipamento", "Equipamento Supervisório",
        "Equipamento Parente", "Chave", "Chave 2", "Potência (kWp)", "N de Inversores", "String Box", "Full O&M",
        "Strings Ativas", "Observações"]


def _l(usina, sup, eq, esup=None, pai=None, kwp=None, n=None, strings=None, full="Sim", sb="Não", fr="Thopen - Brodowski 1 - SP"):
    return {"": None, "Cliente": "Thopen", "Usina": usina, "Usina Supervisório": sup, "Usina Fractall": fr,
            "Equipamento": eq, "Equipamento Supervisório": esup, "Equipamento Parente": pai,
            "Chave": f"{sup or ''}{esup}" if esup else None, "Chave 2": f"{sup or ''}{eq}", "Potência (kWp)": kwp,
            "N de Inversores": n, "String Box": sb, "Full O&M": full, "Strings Ativas": strings, "Observações": None}


# a aba como ela é: a UFV e as UG sem "Usina Supervisório" (a chave é o nome, como 103 das 146 UFV) e os inversores em
# duas chaves; e uma usina que fica de fora (Pedra do Sal)
ABA = [_l("Brodowski", None, "UFV", kwp=1000.0, n=4),
       _l("Brodowski", None, "UG 01", pai="UFV", kwp=500.0, n=2),
       _l("Brodowski", None, "UG 02", pai="UFV", kwp=500.0, n=2),
       _l("Brodowski", "Brodowski", "Inversor 1.1", "INVERSOR01", "UG 01", 250.0, strings=20),
       _l("Brodowski", "Brodowski", "Inversor 1.2", "INVERSOR02", "UG 01", 250.0, strings=20),
       _l("Brodowski", "Brodowski 2 (91)", "Inversor 2.1", "INVERSOR01", "UG 02", 250.0, strings=18),
       _l("Brodowski", "Brodowski 2 (91)", "Inversor 2.2", "INVERSOR02", "UG 02", 250.0, strings=18),
       _l("Pedra do Sal", "Pedra do Sal", "UFV", kwp=300.0, n=1, full="Não", fr=None),
       _l("Pedra do Sal", "Pedra do Sal", "Inversor 1", "INV-1", None, 100.0, strings=10, full="Não", fr=None)]


def _visao(**muda):
    """A visão do Nexus para as duas chaves da Brodowski, montada igual à aba (como a tela publica: a UFV e as UG na
    chave da usina, sem "Usina Supervisório" porque a chave é o próprio nome; os IDs no fim)."""
    comum = {"Cliente": "Thopen", "Usina": "Brodowski", "Usina Fractall": "Thopen - Brodowski 1 - SP", "String Box": "Não",
             "Full O&M": "Sim", "usina_id": 1}
    linhas = [dict(comum, **{"Usina Supervisório": None, "Equipamento": "UFV", "Chave 2": "UFV", "Potência (kWp)": 1000.0,
                             "N de Inversores": 4, "supervisorio_id": 1}),
              dict(comum, **{"Usina Supervisório": None, "Equipamento": "UG 01", "Equipamento Parente": "UFV",
                             "Chave 2": "UG 01", "Potência (kWp)": 500.0, "N de Inversores": 2, "supervisorio_id": 1,
                             "cabine_id": 1}),
              dict(comum, **{"Usina Supervisório": None, "Equipamento": "UG 02", "Equipamento Parente": "UFV",
                             "Chave 2": "UG 02", "Potência (kWp)": 500.0, "N de Inversores": 2, "supervisorio_id": 1,
                             "cabine_id": 2})]
    for sid, sup, pre, cab, s in ((1, "Brodowski", "1", "UG 01", 20), (2, "Brodowski 2 (91)", "2", "UG 02", 18)):
        for n in (1, 2):
            eq, esup = f"Inversor {pre}.{n}", f"INVERSOR0{n}"
            linhas.append(dict(comum, **{"Usina Supervisório": sup, "Equipamento": eq, "Equipamento Supervisório": esup,
                                         "Equipamento Parente": cab, "Chave": f"{sup}{esup}", "Chave 2": f"{sup}{eq}",
                                         "Potência (kWp)": 250.0, "Strings Ativas": muda.get(eq, s), "supervisorio_id": sid,
                                         "inversor_id": len(linhas)}))
    return [{c: x.get(c) for c in en.CAB} for x in linhas]


MAPAS = ("ESPERADO_INV", "EQUIP_NAMES", "USINA_DISPLAY", "USINA_GRUPO", "ESPERADO", "FULL_OM", "STRING_BOX", "POWER_INV",
         "POWER_UFV", "FULL_OM_DISP", "POWER_INV_DISP", "FULL_OM_DISP_NOMES", "ESPERADO_INV_DISP",
         # o Modo de-para (20/10/2026): o código do Fracttal gravado no Nexus e a cabine do inversor
         "FRAC_COD_INV", "FRAC_COD_INV_DISP", "FRAC_COD_CAB", "EQUIP_PARENTE")


@pytest.fixture
def cadastro(monkeypatch):
    """Carrega o cadastro com a aba dublada e a visão que o teste mandar; devolve os mapas. Os mapas de verdade (os do
    `import app`) voltam no fim, sem reler nada."""
    guardado = {m: getattr(app, m) for m in MAPAS}
    estado = dict(app._EN_ESTADO)
    monkeypatch.setattr(app, "_aba_equipamentos_df", lambda: pd.DataFrame(ABA, columns=COLS))
    monkeypatch.setattr(app, "ESTRUTURA_NEXUS", True)

    def carregar(visao):
        monkeypatch.setattr(app, "_en_visao", lambda: [dict(x) for x in visao])
        app.load_equipamentos()
        return {m: getattr(app, m) for m in MAPAS}
    yield carregar
    for m, v in guardado.items():
        setattr(app, m, v)
    app._EN_ESTADO.clear()
    app._EN_ESTADO.update(estado)


def test_sobrepor_troca_so_ufv_ug_e_inversor_das_chaves_da_visao():
    df = pd.DataFrame(ABA + [_l("Brodowski", "Brodowski", "Medidor")], columns=COLS)
    visao = [x for x in _visao() if x["Usina Supervisório"] == "Brodowski 2 (91)"]
    out, saiu = en.sobrepor_df(df, visao)
    assert saiu == 2 and len(out) == len(df)                       # saem os 2 inversores da chave 91, entram os 2 do Nexus
    assert list(out.columns[:len(COLS)]) == COLS and "inversor_id" in out.columns
    assert (out["Equipamento"] == "Medidor").sum() == 1            # o que não é UFV, UG nem inversor fica da aba
    linhas, n = en.sobrepor(ABA, [])
    assert linhas == ABA and n == 0                                # sem visão, a aba como está
    assert en.chave_efetiva({"Usina Supervisório": float("nan"), "Usina": "Brodowski"}) == "Brodowski"


def test_montada_igual_a_aba_o_cadastro_nao_muda_e_mudar_no_nexus_muda(cadastro):
    so_aba = cadastro([])
    com_nexus = cadastro(_visao())
    for m in MAPAS:
        assert com_nexus[m] == so_aba[m], m                        # a troca é invisível quando a estrutura é a mesma
    assert app._EN_ESTADO["trocadas"] == 7 and set(app._EN_ESTADO["chaves"]) == {"Brodowski", "Brodowski 2 (91)"}
    assert app._EN_ESTADO["chaves"]["Brodowski 2 (91)"] == {"inversores": 2, "strings": 36, "usina_id": 1, "linhas": 2}
    # no Nexus o Inversor 2.1 tem 22 strings: a esperada do cadastro acompanha, e o total da usina também
    mudou = cadastro(_visao(**{"Inversor 2.1": 22}))
    assert mudou["ESPERADO_INV"]["Brodowski 2 (91)"]["INVERSOR01"] == 22
    assert mudou["ESPERADO"]["Brodowski 2 (91)"] == {"inv_esp": 2, "str_esp": 40}
    assert mudou["ESPERADO"]["Pedra do Sal"] == so_aba["ESPERADO"]["Pedra do Sal"]     # fora da visão: a aba


def test_a_visao_que_muda_rele_o_cadastro_sem_o_bd_mudar(cadastro, monkeypatch):
    cadastro(_visao())
    chamadas = []
    monkeypatch.setattr(app, "load_equipamentos", lambda: chamadas.append("load_equipamentos"))
    monkeypatch.setattr(app, "_bd_perf_path", lambda: __file__)
    monkeypatch.setattr(app, "_bd_mtime", __import__("os").path.getmtime(__file__))   # o BD não mudou
    app.maybe_reload_equipamentos()
    assert chamadas == []                                          # a mesma visão: nada a reler
    monkeypatch.setattr(app, "_en_visao", lambda: _visao(**{"Inversor 1.1": 21}))
    app.maybe_reload_equipamentos()
    assert chamadas == ["load_equipamentos"]


def test_o_diagnostico_diz_o_que_veio_do_nexus(cadastro, cli):
    cadastro(_visao())
    entrar_com_senha(cli)
    j = cli.get("/api/estrutura-nexus").get_json()
    assert j["ligado"] is True and j["linhas_da_aba_trocadas"] == 7 and j["livro"] == "nexus_estrutura_usina · aba_equipamentos"
    assert j["chaves"]["Brodowski"]["inversores"] == 2 and j["visao_mudou_desde_a_carga"] is False


# a Assis Chateaubriand Skid 1 de 20/10: a aba e a API PV escrevem a chave com espaço DUPLO; o Nexus a grava com o texto()
DUPLA, UNICA = "Assis Chateaubriand  Skid 1 (79)", "Assis Chateaubriand Skid 1 (79)"
_FR_ASSIS = "Thopen - Assis Chateaubriand - PR"
ABA_ASSIS = ([_l("Assis", "Assis", "UFV", kwp=6296.0, n=20, fr=_FR_ASSIS),
              _l("Assis", "Assis", "UG 01", pai="UFV", kwp=1293.6, n=4, fr=_FR_ASSIS)]
             + [_l("Assis", DUPLA, f"Inversor 1.{m}", f"INVERSOR0{m}", "UG 01", 323.4, strings=21, fr=_FR_ASSIS) for m in (1, 2, 3, 4)])


def _visao_assis(kwp=323.4):
    """A visão que o Nexus publica da Skid 1 marcada no lugar da aba: a chave como ELE a grava (espaço único)."""
    return [{c: x.get(c) for c in en.CAB} for x in (
        dict(_l("Assis", UNICA, f"Inversor 1.{m}", f"INVERSOR0{m}", "UG 01", kwp, strings=21, fr=_FR_ASSIS), usina_id=212,
             supervisorio_id=259, cabine_id=401, inversor_id=4010 + m, **{"Código Fracttal": f"THPN-ACB100-INVR1.{m}"})
        for m in (1, 2, 3, 4))]


def test_a_chave_com_espaco_duplo_herda_a_grafia_da_aba(cadastro, monkeypatch):
    """D-g (20/10, a alta da 1ª revisão): marcada no lugar da aba, a "Assis Chateaubriand  Skid 1 (79)" perdia o cadastro
    INTEIRO no tempo real, sem aviso: o sobrepor tirava as linhas da aba pelo texto() e a visão entrava com a grafia do Nexus;
    o `load_equipamentos` guardava a chave de espaço único e o `build_summary` procura pela grafia exata da API (esperadas,
    kWp, nome de exibição e Full O&M = None; string morta deixava de acusar). A linha da visão herda a grafia da aba: pela
    chave da API, tudo segue preenchido, agora com o que o Nexus gravou (o kWp da regra e o código do Fracttal)."""
    monkeypatch.setattr(app, "_aba_equipamentos_df", lambda: pd.DataFrame(ABA_ASSIS, columns=COLS))
    monkeypatch.setattr(app, "_dp_apelidos_da_tela", lambda: {})
    so_aba = cadastro([])
    assert so_aba["ESPERADO_INV"][DUPLA] == {f"INVERSOR0{m}": 21 for m in (1, 2, 3, 4)}
    m = cadastro(_visao_assis(kwp=314.052))
    assert app._EN_ESTADO["trocadas"] == 4                                    # as 4 linhas da aba saíram
    assert m["ESPERADO_INV"][DUPLA] == so_aba["ESPERADO_INV"][DUPLA]
    assert m["EQUIP_NAMES"][DUPLA] == {f"INVERSOR0{n}": f"Inversor 1.{n}" for n in (1, 2, 3, 4)}
    assert m["POWER_INV"][DUPLA][app._nrm("INVERSOR01")] == 314.052          # o kWp que o Nexus gravou chegou
    assert DUPLA in m["FULL_OM"] and m["USINA_DISPLAY"].get(DUPLA) == "Assis"
    assert m["FRAC_COD_INV"][DUPLA][app._nrm("INVERSOR01")] == "THPN-ACB100-INVR1.1"
    assert UNICA not in m["ESPERADO_INV"] and UNICA not in m["POWER_INV"]
    assert app._pv_chave_da_linha({"id": 18747433, "nome": DUPLA}) == {"chave_cadastro": DUPLA}
    # o sobrepor de listas (o diagnóstico e o Nexus) faz o mesmo; a chave que a aba não tem fica como o Nexus escreve
    lidas, saiu = en.sobrepor(ABA_ASSIS, _visao_assis() + [dict(_visao_assis()[0], **{"Usina Supervisório": "Nova  Chave"})])
    assert saiu == 4 and {x["Usina Supervisório"] for x in lidas if x.get("inversor_id")} == {DUPLA, "Nova  Chave"}


# a Belo Jardim (usina 32, `pv`) de 20/10: na aba, no Fracttal e nas Ligações o nome é "Thopen - Belo Jardim  1 - PE", com
# espaço DUPLO; o índice de code-base da plataforma (_frac_codebase_index) guarda a description exata
BJ = "Thopen - Belo Jardim  1 - PE"
ABA_BJ = ([_l("Belo Jardim", "Belo Jardim (588)", "UFV", kwp=2664.0, n=8, fr=BJ),
           _l("Belo Jardim", "Belo Jardim (588)", "UG 01", pai="UFV", kwp=2664.0, n=8, fr=BJ)]
          + [_l("Belo Jardim", "Belo Jardim (588)", f"Inversor 1.{m}", f"INVERSOR0{m}", "UG 01", 333.0, strings=21, fr=BJ)
             for m in range(1, 9)])


def test_belo_jardim_o_nome_do_fracttal_herda_a_grafia_da_aba_e_segue_no_fracttal(monkeypatch):
    """A 2ª revisão (dado, alta): o Nexus escrevia o "Usina Fractall" com os espaços juntados, a comparação dele não via
    (o `norm`) e a chave marcava. Com o fracttal_index.json real, _frac_usina_ent('Belo Jardim') ia de {cb: BJD100, site:
    46256021} para None: a usina perdia o badge de OS abertas, as OS no Diagnóstico e as últimas OS do drill, e a cascata de
    queda (h_rede/h_equip) virava 0. A linha da visão herda a grafia da aba da MESMA chave quando o texto() bate."""
    idx = {BJ.lower(): {"cb": "BJD100", "site": 46256021}}
    monkeypatch.setattr(app, "_frac_codebase_index", lambda: idx)
    visao = [{c: x.get(c) for c in en.CAB} for x in (
        dict(r, **{"Usina Fractall": "Thopen - Belo Jardim 1 - PE", "usina_id": 32, "supervisorio_id": 31,
                   "inversor_id": n if str(r["Equipamento"]).startswith("Inversor") else None})
        for n, r in enumerate(ABA_BJ, 1))]

    def ent(df):
        monkeypatch.setattr(app, "_equipamentos_df", lambda: df)
        monkeypatch.setattr(app, "_frac_bd_map", {})
        return [app._frac_usina_ent(u) for u in ("Belo Jardim", "Belo Jardim (588)")]
    aba = pd.DataFrame(ABA_BJ, columns=COLS)
    assert ent(aba) == [idx[BJ.lower()]] * 2                                    # hoje, pela aba
    com_nexus, saiu = en.sobrepor_df(aba, visao)
    assert saiu == 10 and set(com_nexus["Usina Fractall"]) == {BJ}
    assert ent(com_nexus) == [idx[BJ.lower()]] * 2                              # marcada, segue no Fracttal
    # sem a herança (o que era): o nome com os espaços juntados não acha a usina no índice
    sem = pd.concat([aba[[False] * len(aba)], pd.DataFrame(visao, columns=list(en.CAB))], ignore_index=True)
    assert ent(sem) == [None, None]
    # a herança é da MESMA chave e só de espaços: nome de outra chave, ou de outra letra, fica como o Nexus escreve
    lidas, _ = en.sobrepor(ABA_BJ, [dict(visao[2], **{"Usina Fractall": "Thopen - Belo Jardím 1 - PE"}),
                                    dict(visao[3], **{"Usina Supervisório": "Outra", "Usina Fractall": "Thopen - Belo Jardim 1 - PE"})])
    assert [x["Usina Fractall"] for x in lidas if x.get("inversor_id")] == ["Thopen - Belo Jardím 1 - PE",
                                                                           "Thopen - Belo Jardim 1 - PE"]
