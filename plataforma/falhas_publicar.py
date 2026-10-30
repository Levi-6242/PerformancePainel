# -*- coding: utf-8 -*-
"""Publica as falhas de strings e trackers no workbook `falhas_performance` da Gridco API (25/09/2026).

O Levi decidiu guardar no workbook, e não numa tabela no PostgreSQL da Thopen (nosso usuário não cria tabela lá):
"pode ser guardado no workbook". São as tabelas que ele pediu no começo, já montadas pelo worker em
`falhas_AAAA-MM.json` — este módulo só as põe no formato da planilha e sincroniza.

Caminho que grava cabeçalho na API (o do gêmeo, em produção desde 03/09): xlsx com a linha 1 = cabeçalho, célula
vazia = None (o parser do sync rejeita texto vazio) e POST /api/workbooks/<chave>/sync-xlsx?replace=true. A API não
tem DELETE de workbook: o `sincronizar` só cria quando falta. O `replace` troca as abas presentes no arquivo e apaga
o excedente — por isso o arquivo leva TODOS os meses publicados.

As linhas vão pela data de início (o novo entra no fim) e nenhuma coluna muda sozinha a cada volta: o sync é de hora
em hora e a API guarda histórico por linha — regravar o mês inteiro a cada volta encheria esse histórico. O "quando"
mora na aba `atualizacao`, uma linha por mês. Exceções que crescem no mês corrente, como o episódio em aberto: a aba
`cobertura` (08/10/2026) vai pelo 1º dia medido, mas os dias_* de cada linha sobem a cada dia (e o vazio de uma régua
vira número no dia em que ela registra o cadastro); e o dias_sem_prova do tracker volta a 0 quando a geração do dia
chega (não o relógio: revisão adversarial de 11/10/2026). Na `strings_os`, o status muda quando a OS fecha e a
estimativa de outubro cresce durante o dia do evento; na `trackers_dia`, o "sem prova" vira "sim" (ou sai) quando a
geração do dia chega;
na `disponibilidade_dia`, o dia fechado muda quando o Gerencial o recalcula (a OS fechada com atraso), também no mês
anterior enquanto ele estiver no índice (app._falhas_disp_fora_da_volta, 11/10/2026); e a `disponibilidade_os_dia`
(14/10/2026) muda junto com ela.
"""
import io

WORKBOOK = "falhas_performance"
NOME = "Falhas de strings e trackers"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FONTE_ROT = {"pv": "Thopen · API PV", "pvsb": "Thopen · API PV · String Box", "pg": "Thopen · Banco", "sunop": "Athon",
             "axis": "Axis", "owen": "2C · e-mail", "solaredge": "RenoGrid", "greenyellow": "GreenYellow",
             "salenergia": "Sal Energia", "apolo": "Apolo"}

CABECALHOS = {
    "strings_inversor_dia": ["mes", "dia", "fonte", "cliente", "usina", "inversor", "qtd_strings", "strings",
                             "horas_x_strings", "perda_kwh", "perda_nominal_kwh", "kwp_string", "kwh_kwp_dia", "avisos"],
    # plant_id no FIM (08/10/2026, Dashboard Thopen): sem ele, quem conta string/tracker distinto junta cadastros de
    # mesmo nome — a Brodowski são dois cadastros na API PV (52 em vez de 103 em setembro). Coluna nova só no fim: o BI
    # e o Nexus leem por posição.
    "strings_episodios": ["mes", "fonte", "cliente", "usina", "inversor", "string", "saiu", "voltou", "situacao", "dias",
                          "horas_sol", "perda_kwh", "perda_inferida_kwh", "kwp_string", "metodo", "avisos", "plant_id"],
    # dias_comunicou: dias do episódio em que a USINA leu string ou gerou (Levi, 08/10: "quando fica parado sem
    # comunicação essa ocorrência é ignorada; se a usina comunicou inversor ou string então aí conta").
    # dias_sem_prova: dias do episódio que a geração ainda não cobre e sem prova nenhuma — a usina sem string lida
    # (Barretos, Matão 2 em 08/10) só prova pela geração, que o BD_Thopen grava 0 até o fechamento e a busca da aba
    # (_falhas_geracao) corta no D-1 de quando roda; não é "sem comunicação". Volta a 0 quando a geração do dia chega
    "trackers_episodios": ["mes", "fonte", "cliente", "usina", "tracker", "inversor", "parou", "voltou", "situacao",
                           "horas_sol", "desvio_pico_graus", "fator_perda", "kwp_tracker", "perda_kwh", "cronico", "avisos",
                           "plant_id", "dias_comunicou", "dias_sem_prova"],
    # quem a plataforma MEDIU no mês, com ou sem falha (08/10/2026): separa "0" de "sem monitoramento" no dashboard do
    # cliente. Entra antes da `atualizacao` só pela ordem das abas no xlsx; o conteúdo das abas existentes não muda.
    # 1 linha = SISTEMA × plant_id (revisão adversarial de 11/10/2026: a String Box sai na linha da API PV, e o tracker
    # pela fonte do cadastro). dias_strings/dias_trackers: 0 = a régua registrou o cadastro e não houve leitura; vazio =
    # a régua nem o registrou no mês (não medido — a de trackers na usina sem tracker monitorado)
    "cobertura": ["mes", "fonte", "cliente", "usina", "plant_id", "dias_strings", "dias_trackers", "dias_comunicou"],
    # "Strings é OS" (Levi, 08/10/2026, tarde): 1 linha = 1 OS de recomposição de string do Fracttal × inversor, com a
    # DATA DO EVENTO no mês (a OS 13585 da Altair tem seis inversores: seis linhas com o mesmo nº, cada uma com as
    # strings do seu) — a chave é (mes, os, inversor), não (mes, os). origem = de onde veio a quantidade: texto (a linha
    # "Strings sem corrente: N (...)" do OS Creator), citadas (strings citadas no texto), estimado (outubro: o que a
    # régua viu no inversor no dia do evento) ou sem_quantidade (qtd vazio — nunca 0)
    "strings_os": ["mes", "data_evento", "cliente", "usina", "plant_id", "inversor", "os", "status", "strings", "qtd",
                   "origem"],
    # 1 linha = usina-fonte-plant_id × dia com tracker parado e a usina comunicando ("sim") ou no dia que a geração
    # ainda não cobre, sem outra prova ("sem prova"); o dia em que a usina não comunicou não entra (Levi: "essa
    # ocorrência é ignorada"). A fonte é a do cadastro (falhas_job.fonte_de), não a do tamanho do id
    "trackers_dia": ["mes", "dia", "fonte", "cliente", "usina", "plant_id", "trackers", "qtd", "comunicou"],
    # Disponibilidade do dia por usina (rodada 4 do Dashboard Thopen, Levi 09/10/2026: "coluna para disponibilidade,
    # calculada pelo Fracttal, da mesma forma que calculamos pelo gerencial da plataforma"): a régua da aba
    # Disponibilidade do Gerencial (disponibilidade.py — OS de religamento e corretiva emergencial, 06–18 h, ponderada
    # pela potência afetada). Uma linha por usina do catálogo × dia FECHADO (até D-1); o dia sem OS sai 100, escrito — o
    # 5080 nunca deduz o 100 pela falta da linha. usina_fracttal liga ao de-para do Nexus (o nome da usina é o do
    # BD_Performance)
    "disponibilidade_dia": ["mes", "dia", "cliente", "usina", "usina_fracttal", "pot_kwp", "disp", "h_perdidas"],
    # As OS que formaram a disponibilidade do mês (12/10/2026, Levi, para a janela de Disponibilidade da Visão do
    # responsável do Nexus: "a OS, que tipo de religamento foi, quanto tempo demorou, qual foi o total de perda de
    # energia"): 1 linha = 1 OS da conta × usina. tipo = o tipo da tarefa no Fracttal; origem = queda (religamento) ou
    # equipamento (corretiva emergencial); escopo = usina inteira, cabine N ou inversor N.M; duracao_sol_min = as horas de
    # sol (06–18 h) da OS dentro do mês; perda_kwh = a perda da OS NAQUELA usina pela régua do Gerencial (kWp afetado ×
    # horas, sem a irradiação; `kwh_usina` do índice, 13/10/2026) — as linhas de uma usina somam a perda dela. Sem a
    # descrição nem quem criou (leitura aberta)
    "disponibilidade_os": ["mes", "os", "usina", "usina_fracttal", "tipo", "origem", "codigo_ativo", "escopo", "kwp",
                           "inicio", "fim", "aberta", "duracao_sol_min", "perda_kwh"],
    # A parcela de cada OS em cada dia (14/10/2026, Dashboard Thopen, Levi: "A partir de outubro quero os comentários 100%
    # OS Fracttal. Comentários e disponibilidade!"): 1 linha = OS × usina × dia em que ela tirou disponibilidade, com os
    # trechos das 06–18 h em que foi dona da perda ("06:00-08:06; 10:55-12:05") e as horas equivalentes do dia. Sai da
    # MESMA varredura que a `disponibilidade_dia` (disponibilidade._varrer): somadas, as linhas de uma usina num dia dão
    # o h_perdidas dela. A OS de cabine coberta por uma de usina não tem linha (não tirou nada; até 15/10/2026 o dia
    # que a geração desmentia também não tinha). O 5080 escreve o comentário do dia só com estas linhas
    "disponibilidade_os_dia": ["mes", "dia", "usina", "usina_fracttal", "os", "tipo", "origem", "escopo", "kwp",
                               "inicio", "fim", "aberta", "trechos", "h_perdidas", "fonte", "protecoes"],
    # A Thopen pelas normalizações do COS (29/10/2026): as duas abas acima levam a conta nova (`fonte` = cos na OS da
    # Ronda COS, com as `protecoes` que atuaram, separadas por "; "); estas duas, a de antes (só do Fracttal) e só da
    # Thopen, para o cliente do Dashboard Thopen até o Levi liberar. Mesmas colunas
    "disponibilidade_dia_fracttal": ["mes", "dia", "cliente", "usina", "usina_fracttal", "pot_kwp", "disp", "h_perdidas"],
    "disponibilidade_os_dia_fracttal": ["mes", "dia", "usina", "usina_fracttal", "os", "tipo", "origem", "escopo", "kwp",
                                        "inicio", "fim", "aberta", "trechos", "h_perdidas", "fonte", "protecoes"],
    "atualizacao": ["mes", "periodo_inicio", "periodo_fim", "atualizado_em", "strings_inversor_dia", "strings_episodios",
                    "trackers_episodios", "regua_strings", "regua_trackers", "cobertura", "strings_os", "trackers_dia",
                    "disponibilidade_dia", "disponibilidade_os", "disponibilidade_os_dia",
                    "disponibilidade_dia_fracttal", "disponibilidade_os_dia_fracttal"],
}


def _v(x):
    """Vazio de verdade (None) para None, "" e lista vazia; lista vira texto separado por "; "; booleano, sim/não."""
    if x is None or x == "" or x == []:
        return None
    if isinstance(x, bool):
        return "sim" if x else "não"
    if isinstance(x, (list, tuple)):
        return "; ".join(str(i) for i in x)
    return x


def _pid(x):
    """plant_id sempre texto: "297378" e 297378 viram células diferentes na planilha, e o 5080 junta os cadastros da
    mesma usina pelo id (Brodowski 297378 + 297381). Vazio continua vazio (pacote de antes de 08/10/2026)."""
    return None if x in (None, "") else str(x)


def _situacao_tracker(r):
    if not r.get("fim"):
        return "em aberto"
    fl = [str(f) for f in r.get("flags") or []]
    saiu = next((f for f in fl if f.startswith("saiu:")), None)
    if saiu:
        return saiu
    if any("parou de novo" in f for f in fl):
        return "voltou e parou de novo"
    if any("hora não registrada" in f for f in fl):
        return "voltou (hora não registrada)"
    return "voltou a girar"


def tabelas(pacotes):
    """[pacote do mês] → {aba: [linhas na ordem do cabeçalho]}. Meses na ordem, cada um pela data de início."""
    out = {aba: [] for aba in CABECALHOS}
    for p in sorted(pacotes, key=lambda p: p.get("mes") or ""):
        mes = p.get("mes") or (p.get("periodo") or [""])[0][:7]
        s, t = p.get("strings") or {}, p.get("trackers") or {}
        rs = sorted(s.get("rows") or [], key=lambda r: (r["dia"], r["fonte"], r["usina"], r["inversor"]))
        for r in rs:
            out["strings_inversor_dia"].append([_v(x) for x in (
                mes, r["dia"], FONTE_ROT.get(r["fonte"], r["fonte"]), r.get("cliente"), r["usina"], r["inversor"],
                r.get("qtd"), r.get("strings"), r.get("h_sol"), r.get("perda_kwh"), r.get("perda_nominal_kwh"),
                r.get("kwp_string"), r.get("yield"), r.get("flags"))])
        es = sorted(s.get("episodios") or [], key=lambda e: (e["inicio"], e["fonte"], e["usina"], e["inversor"], e["string"]))
        for e in es:
            out["strings_episodios"].append([_v(x) for x in (
                mes, FONTE_ROT.get(e["fonte"], e["fonte"]), e.get("cliente"), e["usina"], e["inversor"], e["string"],
                e["inicio"], e.get("fim"), e.get("fim_motivo"), e.get("dias"), e.get("h_sol"), e.get("perda_kwh"),
                e.get("perda_inferida_kwh"), e.get("kwp_string"), e.get("metodo"), e.get("flags"),
                _pid(e.get("plant_id")))])
        ts = sorted(t.get("rows") or [], key=lambda r: (r["inicio"], r["fonte"], r["usina"], str(r["tracker"])))
        for r in ts:
            out["trackers_episodios"].append([_v(x) for x in (
                mes, FONTE_ROT.get(r["fonte"], r["fonte"]), r.get("cliente"), r["usina"], r["tracker"], r.get("inversor"),
                r["inicio"], r.get("fim"), _situacao_tracker(r), r.get("h_sol"), r.get("desvio_pico"), r.get("fator"),
                r.get("kwp_tracker"), r.get("perda_kwh"), bool(r.get("cronico")),
                [f for f in r.get("flags") or [] if f != "em aberto"], _pid(r.get("plant_id")),
                r.get("dias_comunicou"), r.get("dias_sem_prova"))])
        # _v(0) devolve 0: dias_trackers = 0 (olhou e não houve leitura) não vira célula vazia, e o vazio (a régua nem
        # registrou o cadastro no mês, ou coluna não publicada) não vira 0.
        # Pelo 1º dia medido, como os episódios pela data de início: o cadastro que aparece no meio do mês entra no fim
        # e não empurra as linhas de baixo (a API guarda histórico por row_number)
        cs = sorted(p.get("cobertura") or [],
                    key=lambda c: (c.get("primeiro_dia") or "", c["usina"], c["fonte"], str(c["plant_id"])))
        for c in cs:
            out["cobertura"].append([_v(x) for x in (
                mes, FONTE_ROT.get(c["fonte"], c["fonte"]), c.get("cliente"), c["usina"], _pid(c["plant_id"]),
                c.get("dias_strings"), c.get("dias_trackers"), c.get("dias_comunicou"))])
        # pela data do evento (a OS nova entra no fim); qtd vazio fica vazio — a OS sem quantidade não é "0 strings"
        so = sorted(p.get("strings_os") or [],
                    key=lambda o: (o.get("data_evento") or "", _ordem_os(o.get("os")), o.get("inversor") or ""))
        for o in so:
            out["strings_os"].append([_v(x) for x in (
                mes, o.get("data_evento"), o.get("cliente"), o.get("usina"), _pid(o.get("plant_id")), o.get("inversor"),
                _pid(o.get("os")), o.get("status"), o.get("strings"), o.get("qtd"), o.get("origem"))])
        td = sorted(p.get("trackers_dia") or [], key=lambda r: (r["dia"], r["usina"], r["fonte"], str(r["plant_id"])))
        for r in td:
            out["trackers_dia"].append([_v(x) for x in (
                mes, r["dia"], FONTE_ROT.get(r["fonte"], r["fonte"]), r.get("cliente"), r["usina"], _pid(r["plant_id"]),
                r.get("trackers"), r.get("qtd"), r.get("comunicou"))])
        dsp = _disp_linhas(p.get("disponibilidade"))
        for r in dsp:
            out["disponibilidade_dia"].append([_v(x) for x in (mes,) + r])
        dos = _disp_os_linhas(p.get("disponibilidade"))
        for r in dos:
            out["disponibilidade_os"].append([_v(x) for x in (mes,) + r])
        dod = _disp_os_dia_linhas(p.get("disponibilidade"))
        for r in dod:
            out["disponibilidade_os_dia"].append([_v(x) for x in (mes,) + r])
        dsp_fr = _disp_linhas(p.get("disponibilidade_fracttal"))
        for r in dsp_fr:
            out["disponibilidade_dia_fracttal"].append([_v(x) for x in (mes,) + r])
        dod_fr = _disp_os_dia_linhas(p.get("disponibilidade_fracttal"))
        for r in dod_fr:
            out["disponibilidade_os_dia_fracttal"].append([_v(x) for x in (mes,) + r])
        per = p.get("periodo") or [None, None]
        reg = p.get("regua") or {}
        # a contagem de cada aba é o que o 5080 confere na leitura: o sync troca linhas no lugar e, lida no meio dele,
        # uma linha pode vir duas vezes ou faltar. Aba que o pacote não montou (pacote de antes de 08/10/2026, ou o
        # índice de OS do Fracttal ainda não publicado) conta VAZIO, não 0 — revisão do Nexus: 0 diria "nenhuma OS" /
        # "nenhuma usina medida" onde só não houve publicação
        def _n(chave, linhas):
            return len(linhas) if p.get(chave) is not None else None
        out["atualizacao"].append([_v(x) for x in (
            mes, per[0], per[1], p.get("gerado_em"), len(rs), len(es), len(ts), reg.get("janela_strings"),
            reg.get("fator_tracker"), _n("cobertura", cs), _n("strings_os", so), _n("trackers_dia", td),
            _n("disponibilidade", dsp),
            # pacote de antes de 12/10/2026 (sem as OS) conta VAZIO, não 0
            len(dos) if (p.get("disponibilidade") or {}).get("oss") is not None else None,
            # índice de antes de 14/10/2026 (sem a parcela de cada OS no dia) conta VAZIO, não 0: o 5080 sabe que não
            # foi publicada, e não que nenhuma OS tirou nada
            len(dod) if _tem_os_do_dia(p.get("disponibilidade")) else None,
            # a de antes, para o cliente (29/10/2026): VAZIO quando o índice não a tem (a Thopen já está pelo Fracttal)
            _n("disponibilidade_fracttal", dsp_fr),
            len(dod_fr) if _tem_os_do_dia(p.get("disponibilidade_fracttal")) else None)])
    return out


def _disp_linhas(d):
    """{periodo [ini, fim exclusivo], usinas, diario} → [(dia, cliente, usina, usina_fracttal, pot_kwp, disp, h)] pela
    ordem do dia (o dia novo entra no fim). Dia sem OS = 100 e 0 h, escritos."""
    if not d or not d.get("periodo"):
        return []
    import datetime as _dt
    ini, fim = (_dt.date.fromisoformat(str(x)[:10]) for x in d["periodo"])
    us = sorted(d.get("usinas") or [], key=lambda u: str(u.get("usina")))
    diario = d.get("diario") or {}
    out, dia = [], ini
    while dia < fim:
        k = dia.isoformat()
        for u in us:
            v = (diario.get(u.get("usina")) or {}).get(k) or {}
            out.append((k, u.get("cliente"), u.get("usina"), u.get("fracttal"), u.get("pot_kwp"),
                        v.get("disp", 100.0), v.get("h_eq", 0)))
        dia += _dt.timedelta(days=1)
    return out


def _disp_os_linhas(d):
    """{usinas, oss} → [(os, usina, usina_fracttal, tipo, origem, codigo_ativo, escopo, kwp, inicio, fim, aberta,
    duracao_sol_min, perda_kwh)] pela ordem do início (a OS nova entra no fim). Uma linha por OS × usina do escopo, com a
    perda da OS NAQUELA usina: somadas, as linhas de uma usina dão a perda dela no Gerencial."""
    if not d or not d.get("oss"):
        return []
    fr = {u.get("usina"): u.get("fracttal") for u in d.get("usinas") or []}
    out = []
    for o in sorted(d["oss"], key=lambda o: (str(o.get("ini") or ""), _ordem_os(o.get("folio")))):
        por = {}
        for e in o.get("escopo") or []:
            x = por.setdefault(e.get("usina"), {"rotulos": [], "kwp": 0.0})
            x["rotulos"].append(e.get("rotulo"))
            x["kwp"] += float(e.get("kwp") or 0)
        for u in o.get("usinas") or []:
            por.setdefault(u, {"rotulos": [], "kwp": 0.0})
        tot = sum(x["kwp"] for x in por.values())
        kwh = o.get("kwh")
        # a perda de cada usina é a que o índice mediu nela (`kwh_usina`, 13/10/2026). Repartir a da OS pela potência
        # erra quando o teto de 100% pega uma usina e não a outra (e, até 15/10/2026, quando a geração desmentia o dia
        # numa só): em setembro a Rodrigues 1 e 2 trocavam ~47,9 MWh por essa conta, e em outubro a Boa Esperança do Sul
        # 1 e 2 ~2,5 MWh. A usina do escopo que não está no `kwh_usina` (nenhuma hora de sol nela) perdeu 0 com esta OS
        # — e a linha fica, em 0. O índice publicado antes do campo (até a 1ª varredura do worker com o código de 13/10/2026) não o
        # tem: aí segue a repartição pela potência, a única conta possível sem ele
        kwh_u = o.get("kwh_usina")
        for u, x in sorted(por.items(), key=lambda kv: str(kv[0])):
            if not u:
                continue
            if kwh_u is not None:
                parte = kwh_u.get(u, 0)
            else:
                parte = (kwh * x["kwp"] / tot if tot else kwh / len(por)) if isinstance(kwh, (int, float)) else None
            h = o.get("h_solar")
            out.append((_pid(o.get("folio")), u, fr.get(u), "; ".join(o.get("tipos") or []) or None, o.get("origem"),
                        o.get("code"), "; ".join(r for r in x["rotulos"] if r) or None, round(x["kwp"], 1) or None,
                        o.get("ini"), o.get("fim"), bool(o.get("aberta")),
                        round(h * 60) if isinstance(h, (int, float)) else None,
                        round(parte) if parte is not None else None))
    return out


def _tem_os_do_dia(d):
    """O índice já traz a parcela de cada OS no dia (a chave "os" nos dias do diário, código de 14/10/2026)?"""
    diario = (d or {}).get("diario")
    if not diario:
        return bool(d and d.get("periodo"))         # mês sem perda nenhuma: 0 linhas, publicadas
    return all("os" in v for dias in diario.values() for v in (dias or {}).values())


def _disp_os_dia_linhas(d):
    """{usinas, diario[u][dia].os, oss} → [(dia, usina, usina_fracttal, os, tipo, origem, escopo, kwp, inicio, fim,
    aberta, trechos, h_perdidas)] pela ordem do dia (o dia novo entra no fim), depois da usina e do 1º trecho. O escopo
    e o kWp são os da OS NAQUELA usina (a OS de duas usinas leva o de cada uma). Índice sem a parcela: nada."""
    if not d or not d.get("diario") or not _tem_os_do_dia(d):
        return []
    fr = {u.get("usina"): u.get("fracttal") for u in d.get("usinas") or []}
    por_os = {str(o.get("folio")): o for o in d.get("oss") or []}
    out = []
    for u in sorted(d["diario"], key=str):
        for dia in sorted(d["diario"][u] or {}):
            for x in (d["diario"][u][dia] or {}).get("os") or []:
                o = por_os.get(str(x.get("folio"))) or {}
                esc = [e for e in o.get("escopo") or [] if e.get("usina") == u]
                kwp = sum(float(e.get("kwp") or 0) for e in esc)
                # a OS do COS sem nº (normalização sem OS) tem folio negativo: o nº sai vazio, nunca "-123"
                fol = x.get("folio")
                num = None if isinstance(fol, (int, float)) and fol < 0 else _pid(fol)
                out.append((str(dia)[:10], u, fr.get(u), num, "; ".join(o.get("tipos") or []) or None,
                            o.get("origem"), "; ".join(e.get("rotulo") for e in esc if e.get("rotulo")) or None,
                            round(kwp, 1) or None, o.get("ini"), o.get("fim"), bool(o.get("aberta")),
                            x.get("trechos"), x.get("h"), o.get("fonte") or "fracttal",
                            "; ".join(o.get("protecoes") or []) or None))
    out.sort(key=lambda r: (r[0], str(r[1]), str(r[11] or "")))
    return out


def _ordem_os(folio):
    """O nº da OS em ordem numérica (9915 antes de 12728), texto no fim."""
    s = str(folio or "")
    return (0, int(s), "") if s.isdigit() else (1, 0, s)


def xlsx_bytes(tabs):
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for aba, cab in CABECALHOS.items():
        ws = wb.create_sheet(aba)
        ws.append(cab)
        for lin in tabs.get(aba, []):
            ws.append(lin)
        ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def sincronizar(conteudo, *, base, token, sessao=None, chave=WORKBOOK, nome=NOME):
    """Garante o workbook (cria só se faltar — não há DELETE na API) e sincroniza com replace=true.
    → o JSON da API: {sheets, inserted, updated, deleted}. Erro HTTP levanta (quem chama registra e segue)."""
    import requests
    s = sessao or requests
    base = base.rstrip("/")
    h = {"Authorization": f"Bearer {token}"}
    r = s.get(f"{base}/api/workbooks", headers=h, timeout=60)
    r.raise_for_status()
    if chave not in {w.get("key") for w in r.json()}:
        rc = s.post(f"{base}/api/workbooks", headers=h, json={"key": chave, "display_name": nome}, timeout=60)
        rc.raise_for_status()
    r = s.post(f"{base}/api/workbooks/{chave}/sync-xlsx", headers=h, params={"replace": "true"},
               files={"file": (f"{chave}.xlsx", conteudo, MIME_XLSX)}, timeout=300)
    r.raise_for_status()
    return r.json()
