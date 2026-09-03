# gemeo/tests/test_core_alias.py
"""O de-para e DADO com confianca, nao codigo. A planilha docs/de-para-trackers-supervisorio-fracttal.xlsx
(4.313 pares, 03/09) entra linha a linha; a coluna 'Como casou' vira a confianca."""
import openpyxl
from tools.importar_alias import ler_planilha, CONFIANCA_POR_COMO_CASOU


def _xlsx(tmp_path):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "De-Para Trackers"
    ws.append(["Fonte", "UFV Supervisório", "UFV Fracttal", "Tracker Supervisório", "Tracker Fracttal", "Code Fracttal", "Cabine (Fracttal)", "Como casou", "Observação"])
    ws.append(["Athon (SunOp)", "MRO100", "Athon - Mãe do Rio 1 - PA", "TRK_7", "Tracker 7", "MRO100-ETKR7.101", "101", "por limite dos skids (CONFIRMAR)", ""])
    ws.append(["API PV", "Guatambu 2 (129)", "Thopen - Guatambú 1 - SC", "TRK11", "Tracker 1.101", "THPN-GTB100-ETKR1.101", "101", "por contagem da sub-usina", ""])
    ws.append(["API PV", "Junco 2.3 (136)", "Thopen - Junco 1 - PI", "TRK5", "", "", "", "", "excedente do supervisorio - este tracker nao existe no Fracttal"])
    p = tmp_path / "depara.xlsx"; wb.save(p); return p


def test_le_planilha_e_mapeia_confianca(tmp_path):
    linhas = ler_planilha(_xlsx(tmp_path))
    assert len(linhas) == 2                         # a linha sem code e ignorada
    a, b = linhas
    assert (a.usina_sup, a.tracker_sup, a.numero, a.code_fracttal, a.confianca) == ("MRO100", "TRK_7", 7, "MRO100-ETKR7.101", "limite_skid")
    assert (b.numero, b.confianca) == (11, "contagem")


def test_todo_como_casou_conhecido_tem_confianca():
    assert set(CONFIANCA_POR_COMO_CASOU.values()) <= {"direto", "contagem", "ordem", "limite_skid", "manual"}
