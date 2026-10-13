# -*- coding: utf-8 -*-
"""Publica a meta do mês por usina no banco: livro `nexus_performance`, aba `fato_meta_usina_mes` (12/10/2026).

Levi: "Agora temos em um canto só as metas da performance, a disponibilidade, o tanto que o ativo parou, o tempo que o COS
demora para abrir a OS, os chamados, rondas, PTs e APRs (...) construa a visão dos responsáveis da usina!". A Visão do
responsável, no Nexus, lê a meta do mês daqui: os MESMOS números da Visão gerencial, porque é a mesma conta
(`_gerencial_payload`, que o worker já refaz a cada 5 min), sem o Nexus refazer a conta nem chamar a plataforma.

A aba `fato_desempenho_usina_dia` (12/10/2026, Levi: "PR ao clicar aparece um card (...) essa mesma visão do PAINEL NOC >
HISTÓRICO > PR > PR DIÁRIO EXPANDIDO"; e a meta "com uma tabelinha de dia do mês, geração meta, geração real"): a série
do PR diário do Painel NOC (`/api/g/diario`, a MESMA que o gráfico expandido desenha), 1 linha = 1 usina do Gerencial ×
1 dia com ponto, com a geração, a meta diária (a meta do mês ÷ os dias do mês, como lá), o POA, a meta de POA, o PR e a
meta de PR. Medido em 12/10/2026: 129 das 161 usinas têm série; na Boa Esperança do Sul 1, a soma dos dias (74,2 MWh) e
a meta dos dias (7 × 18,57 = 130,0) são as do Gerencial (57,1%).

Grão (governança do Nexus, `nexus/dados/CLAUDE.md`, registrado no catálogo antes da 1ª gravação): 1 linha = 1 usina (o
nome do Gerencial: a aba do BD ou a carteira do banco da Thopen) × 1 mês. Foto acumulada: o mês corrente se refaz a cada
hora até fechar; o anterior, até o dia 5 (OS e BD fechados com atraso); os outros meses ficam como estão (o arquivo leva
todos: o `replace` troca a aba inteira). Sem pessoa e sem texto livre (a API do banco tem leitura aberta): o `pr_motivo`
do Gerencial fica de fora. A energia vai em kWh (a regra 3 do catálogo do Nexus aceita só `_kwh` como unidade de energia
no nome da coluna; o Gerencial mostra MWh com 1 casa, então o kWh publicado é esse MWh × 1000). Puro: a leitura, a
gravação e o laço moram no app.py (`_ger_publicar`).
"""
LIVRO = "nexus_performance"
NOME = "Nexus · Performance (meta do mês por usina)"
ABA = "fato_meta_usina_mes"
CAB = ["mes_id", "usina", "cliente", "carteira", "prod_kwh", "meta_kwh", "atingimento_pct", "pr_pct", "pr_meta_pct",
       "ipoa_kwh_m2", "ipoa_meta_kwh_m2", "dias_cobertos_qtd", "dias_mes_qtd", "meta_dias_qtd", "full_om", "fonte",
       "meta_fonte"]
ABA_DIA = "fato_desempenho_usina_dia"
CAB_DIA = ["mes_id", "usina", "data_id", "geracao_kwh", "meta_kwh", "ipoa_kwh_m2", "ipoa_meta_kwh_m2", "pr_pct",
           "pr_meta_pct"]
MESES_REFEITOS_ATE_DIA = 5          # o mês anterior se refaz até o dia 5 do mês seguinte


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _kwh(mwh):
    v = _num(mwh)
    return None if v is None else round(v * 1000)


def _txt(v):
    s = str(v or "").strip()
    return None if s in ("", "—") else s


def linhas(payload, mes_id: int) -> list[list]:
    """As linhas de um mês do Gerencial (`_gerencial_payload`), na ordem do CAB, pela usina."""
    out = []
    for u in (payload or {}).get("usinas") or []:
        nome = _txt(u.get("usina"))
        if not nome:
            continue
        out.append([int(mes_id), nome, _txt(u.get("cliente")), _txt(u.get("carteira")), _kwh(u.get("prod")),
                    _kwh(u.get("p50")), _num(u.get("atingimento")), _num(u.get("pr")), _num(u.get("pr_meta")),
                    _num(u.get("ipoa")), _num(u.get("ipoa_prev")), _num(u.get("dias_cob")), _num(u.get("dias_mes")),
                    _num(u.get("meta_dias")), 1 if u.get("full_oem") else 0, _txt(u.get("src")), _txt(u.get("p50_src"))])
    out.sort(key=lambda r: r[1].lower())
    return out


def _pct(frac):
    """A fração do /api/g/diario (0,827) em % com 1 casa (82,7); o que já vier em % (> 2) fica como está."""
    v = _num(frac)
    if v is None:
        return None
    return round(v if v > 2 else v * 100, 1)


def linhas_dia(series: dict, mes_id: int) -> list[list]:
    """As linhas da aba diária de um mês: `series` = {usina do Gerencial: o payload do `/api/g/diario`}, na ordem do
    CAB_DIA, pela usina e pelo dia. A meta do dia é a mesma em todos os dias (a meta do mês ÷ os dias do mês, como o
    gráfico do Painel NOC desenha); o PR vazio fica vazio (dia sem POA)."""
    ano, mes = divmod(int(mes_id), 100)
    out = []
    for usina, d in (series or {}).items():
        nome = _txt(usina)
        if not nome or not d:
            continue
        meta, meta_poa, pr_meta = _kwh(d.get("meta_ger")), _num(d.get("meta_poa")), _pct(d.get("meta"))
        for p in d.get("pontos") or []:
            dia = p.get("dia")
            if not isinstance(dia, int) or not 1 <= dia <= 31:
                continue
            out.append([int(mes_id), nome, ano * 10000 + mes * 100 + dia, _kwh(p.get("geracao")), meta,
                        _num(p.get("poa")), meta_poa, _pct(p.get("realizado")), pr_meta])
    out.sort(key=lambda r: (r[1].lower(), r[2]))
    return out


def xlsx_bytes(tabelas: dict) -> bytes:
    """{aba: (cabeçalho, linhas)} num xlsx só (o `replace` troca o livro inteiro: as duas abas vão juntas). Vazio de
    verdade: o sync da API recusa a célula de texto vazio ("inlineStr sem elemento <is>", 11/10/2026)."""
    import io
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for aba, (cab, linhas) in tabelas.items():
        ws = wb.create_sheet(aba)
        ws.append(list(cab))
        for lin in linhas:
            ws.append([None if v == "" else v for v in lin])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _mes(lin) -> int | None:
    try:
        return int(float(lin[0]))
    except (TypeError, ValueError, IndexError):
        return None


def mesclar(atuais, novas_por_mes: dict) -> list[list]:
    """As linhas que o banco já tem, com os meses refeitos trocados pelas linhas novas (mês sem linha nova fica como
    estava). Ordem: mês e usina."""
    refeitos = {int(m) for m in novas_por_mes}
    out = [list(r) for r in (atuais or []) if _mes(r) is not None and _mes(r) not in refeitos]
    for m in sorted(refeitos):
        out += [list(r) for r in novas_por_mes[m]]
    out.sort(key=lambda r: (_mes(r), str(r[1] or "").lower()))
    return out


def meses_a_refazer(ano: int, mes: int, dia: int) -> list[tuple[int, int]]:
    """[(ano, mês)] que a volta refaz: o corrente e, até o dia 5, o anterior."""
    out = [(ano, mes)]
    if dia <= MESES_REFEITOS_ATE_DIA:
        out.append((ano, mes - 1) if mes > 1 else (ano - 1, 12))
    return out
