# -*- coding: utf-8 -*-
"""O relatório diário da PV Operation, a disponibilidade que a Thopen vê (26/11/2026).

Levi, 26/11/2026: "Todo dia eu recebo um e-mail de relatório das visitas da Thopen. E aí vem a disponibilidade desses
dias. Eu queria que a partir de novembro a gente puxasse do meu e-mail essas informações de disponibilidade para estar
contabilizando e sempre fazendo a comparação com a disponibilidade das ocorrências da grid, porque em tese é para estar
tudo batendo. O que não tiver tem que ter alguma justificativa"; e "já cruza automaticamente com as ocorrências do COS e
já dá as diferenças para o COS poder analisar em tempo real".

De onde vem: a PV Operation (o monitoramento da Thopen) manda todo dia, às 08:00, o "Relatório Diário das Usinas" ao
responsável da Thopen, que encaminha à Grid. Anexos: `relatorio_usinas_AAAA-MM-DD.xlsx` (1 linha por usina da PV
Operation, "Altair 1 (73)": geração, prognóstico, irradiação, PR, Disponibilidade geração e Disponibilidade comunicação
do dia) e `debug_usinas_diario_DD-MM-AAAA.txt` (por inversor, os períodos de 10 min ou mais com potência ativa zerada ou
sem comunicação, e a janela do dia: 08:30 às 17:30 em 25/11). A `leituras_*.xlsx` vem vazia. Até a leitura do e-mail
ser liberada (a credencial do Nexus não lê e-mail; a T.I. precisa dar o Mail.Read), a conta Grid solta o zip (ou os
arquivos) na aba Conferência PV Operation.

Os livros (o 5080 grava; o dia que chega de novo troca as linhas daquele dia):
- `thopen_pvop_disp` · `disp_dia`: 1 linha = 1 usina da PV Operation × dia, ligada à usina do dashboard e ao kWp da parte;
- `thopen_pvop_periodo` · `periodo`: 1 linha = 1 período de 10 min ou mais de um inversor (geração zerada ou comunicação);
- `thopen_pvop_justificativa` · `justificativa`: 1 linha = 1 usina do dashboard × dia com a justificativa da diferença
  (só o texto e a hora: quem escreveu não vai ao banco).
O de-para do nome da PV Operation para a usina do dashboard é o da planilha de outubro (a coluna "Usina supervisório" da
aba Equipamentos do BD_Performance, e os casos à mão abaixo).
"""
import datetime as dt
import io as _io
import re
import unicodedata
import zipfile

LIVRO_DISP, ABA_DISP = "thopen_pvop_disp", "disp_dia"
NOME_DISP = "Dashboard Thopen · disponibilidade do relatório diário da PV Operation"
CAB_DISP = ("dia", "nome", "pvop_id", "usina", "kwp", "disp_geracao", "disp_comunicacao", "geracao",
            "prognostico_geracao", "irradiacao", "prognostico_irradiacao", "pr", "minutos_janela", "minutos_pac0",
            "minutos_comunicacao", "arquivo", "recebido_em")
LIVRO_PER, ABA_PER = "thopen_pvop_periodo", "periodo"
NOME_PER = "Dashboard Thopen · períodos dos inversores do relatório diário da PV Operation"
CAB_PER = ("dia", "nome", "pvop_id", "usina", "inversor", "tipo", "inicio", "fim", "minutos", "recebido_em")
LIVRO_JUS, ABA_JUS = "thopen_pvop_justificativa", "justificativa"
NOME_JUS = "Dashboard Thopen · justificativa da diferença entre a PV Operation e a Grid"
CAB_JUS = ("usina", "dia", "texto", "em")
TOLERANCIA = 0.5          # pontos: até aqui a PV Operation e a Grid "batem"


def n(s):
    return " ".join(unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
                    .replace("-", " ").split())


def sem_id(s):
    return " ".join(re.sub(r"\(\d+\)", " ", n(s)).replace("ufv ", "").split())


# a usina da aba Equipamentos -> a usina do dashboard (quando o nome muda); e os nomes que o supervisório não casa sozinho
# (os mesmos da planilha de outubro de 09/11/2026: nome sem id -> (usina do dashboard, parte no supervisório ou None))
USINA_5080 = {"Primavera 1": "Primavera", "Primavera 2": "Primavera", "Nova Londrina 1": "Nova Londrina",
              "Nova Londrina 2": "Nova Londrina", "Taguaí 1 (173)": "Taguaí", "Taguaí 2 (174)": "Taguaí",
              "Santo Antonio do Platina": "Santo Antonio da Platina", "Corrego do Sapucaia": "Córrego do Sapucaia"}
MANUAL = {
    "assis 1": ("Assis", "Assis Chateaubriand  Skid 1 (79)"), "assis 2": ("Assis", "Assis Chateaubriand Skid 2 (80)"),
    "assis 3": ("Assis", "Assis Chateaubriand Skid 3 (81)"), "assis 4": ("Assis", "Assis Chateaubriand Skid 4 (82)"),
    "assis 5": ("Assis", "Assis Chateaubriand Skid 5 (2)"),
    "bernardino": ("Bernardino de Campos", "Bernardino de Campos (84)"),
    "caico 1": ("Caicó", "Caicó 1.1 (224)"), "caico 2": ("Caicó", "Caicó 1.2 (225)"),
    "corrego 1": ("Córrego do Sapucaia", "Corrego Sapucaia 1 (113)"),
    "corrego 2": ("Córrego do Sapucaia", "Corrego Sapucaia 2 (114)"),
    "jucurutu 1": ("Jucurutu", "Jucurutu 1.1 (271)"), "jucurutu 2": ("Jucurutu", "Jucurutu 1.2 (884)"),
    "nova iguacu 1": ("Nova Iguaçu", "Nova Iguaçu 2.1 (180)"), "nova iguacu 2": ("Nova Iguaçu", "Nova Iguaçu 2.2 (180)"),
    "pacaembu sitio areia branca 01": ("Areia Branca", "Pacaembu - Sítio Areia Branca 1.1 (169)"),
    "pacaembu sitio areia branca 02": ("Areia Branca", "Pacaembu - Sítio Areia Branca 1.2 (170)"),
    "aparecida do taboado 2 1": ("Aparecida do Taboado 1", "(323) Aparecida do Taboado 1"),
    "aparecida do taboado 2 2": ("Aparecida do Taboado 2", "(324) Aparecida do taboado 2"),
    "aparecida iii 1": ("Aparecida 3", "(298) Aparecida 3"),
    "aracoiaba da serra i 1": ("Araçoiaba da Serra 1", "(299) Araçoiaba da Serra 1"),
    "aracoiaba da serra i 2": ("Araçoiaba da Serra 2", "(300) Araçoiaba da Serra 2"),
    "boa esperanca do sul i 1": ("Boa Esperança do Sul 1", "(289) Boa Esperança do Sul 1"),
    "boa esperanca do sul i 2": ("Boa Esperança do Sul 2", "(290) Boa Esperança do Sul 2"),
    "caxambu i 1": ("Caxambu", "(292) Caxambu"), "goytacazes 1 1": ("Goytacazes 1", "(295) Goytacazes 1"),
    "guaratingueta 5 1": ("Guaratinguetá V", "(305) Guaratinguetá V"),
    "ibate 1 1": ("Ibaté 1", "(306) Ibaté 1"), "ibate 2 1": ("Ibaté 2", "(307) Ibaté 2"),
    "ipixuna 1 1": ("Ipixuna 1", "(308) Ipixuna 1"), "ipixuna 2 1": ("Ipixuna 2", "(296) Ipixuna 2"),
    "marajoara 1 1": ("Marajoara 1", "(321) Marajoara I"), "piracicaba 1 1": ("Piracicaba 1", "(309) Piracicaba I"),
    "salto pirapora 3 1": ("Salto Pirapora 3", "(310) Salto Pirapora III"),
    "santa barbara 1 1": ("Santa Bárbara I", "(311) Santa Bárbara I"),
    "santarem 1 1": ("Santarém 1", "(317) Santarém 1"), "santarem 1 2": ("Santarém 2", "(318) Santarém 2"),
    "santo inacio 12 1": ("Santo Inácio XII", "(327) Santo Inácio XII"),
    "sao bento 5 1": ("São Bento V", "(312) São Bento V"), "vargem grande 1 1": ("Vargem Grande 1", "Vargem Grande IB"),
    "pianco 1 1": ("Piancó 1", None),
    "pharma ii": ("Pharma II", "Pharma 2"), "pharma iii": ("Pharma III", "Pharma 3"), "pharma iv": ("Pharma IV", "Pharma 4"),
    "caroa 1": ("Caroá", None), "caroa 2": ("Caroá", None),
    "inhapi uc01": ("Inhapi", "Inhapi 1 (576)"), "inhapi uc02": ("Inhapi", "Inhapi 2 (577)"),
    "inhapi uc03": ("Inhapi", "Inhapi 3 (578)"),
    "ouro branco uc01": ("Ouro Branco I", "Ouro Branco 1 (579)"), "ouro branco uc02": ("Ouro Branco II", "Ouro Branco 2 (640)"),
    "ouro branco uc03": ("Ouro Branco III", "Ouro Branco 3 (774)"), "ouro branco uc04": ("Ouro Branco IV", "Ouro Branco 4 (773)"),
    "ouro branco uc05": ("Ouro Branco V", "Ouro Branco 5 (775)"),
    "santana": ("Santana do Ipanema", "Santana do Ipanema (552)"), "sao bento": ("São Bento do Una", "São Bento do Una (667)"),
}


def depara(equipamentos):
    """(sup_usina, sup_kwp) da aba Equipamentos do BD_Performance: {nome sem id: (nome no supervisório, usina)} e
    {nome sem id: kWp dos inversores}."""
    if not equipamentos:
        return {}, {}
    ks = next((x for x in equipamentos[0] if "supervis" in n(x) and "usina" in n(x)), None)
    kp = next((x for x in equipamentos[0] if n(x).startswith("pot")), None)
    sup_usina, sup_kwp = {}, {}
    for r in equipamentos:
        u, s, e = str(r.get("Usina") or "").strip(), str(r.get(ks) or "").strip(), str(r.get("Equipamento") or "").strip()
        try:
            p = float(r.get(kp) or 0)
        except (TypeError, ValueError):
            p = 0.0
        if s and u:
            sup_usina.setdefault(sem_id(s), (s, u))
        if s and e.lower().startswith("inversor"):
            sup_kwp[sem_id(s)] = sup_kwp.get(sem_id(s), 0.0) + p
    return sup_usina, sup_kwp


def casar(nome, sup_usina, sup_kwp):
    """(usina do dashboard, kWp da parte) do nome da PV Operation, ou (None, None)."""
    k = sem_id(nome)
    if k in MANUAL:
        usina, parte = MANUAL[k]
        return usina, (sup_kwp.get(sem_id(parte)) if parte else None)
    if k in sup_usina:
        _parte, ueq = sup_usina[k]
        return USINA_5080.get(ueq, ueq), sup_kwp.get(k)
    return None, None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def dia_do_nome(arquivo):
    """O dia do dado pelo nome do anexo: relatorio_usinas_2026-11-25.xlsx ou debug_usinas_diario_25-11-2026.txt."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", arquivo or "")
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", arquivo or "")
    return dt.date(int(m[3]), int(m[2]), int(m[1])) if m else None


def ler_planilha(conteudo):
    """[{nome, colunas...}] da relatorio_usinas_*.xlsx (o cabeçalho é a linha que começa com "Nome")."""
    import openpyxl
    rows = list(openpyxl.load_workbook(_io.BytesIO(conteudo), data_only=True, read_only=True).worksheets[0]
                .iter_rows(values_only=True))
    i0 = next((i for i, r in enumerate(rows) if r and n(r[0]) == "nome"), None)
    if i0 is None:
        raise ValueError("a planilha não tem a coluna Nome")
    cab = [n(c) for c in rows[i0]]
    col = {k: i for i, k in enumerate(cab) if k}

    def v(r, k):
        i = col.get(k)
        return r[i] if i is not None and i < len(r) else None
    out = []
    for r in rows[i0 + 1:]:
        if not r or not str(r[0] or "").strip():
            continue
        out.append({"nome": str(r[0]).strip(), "geracao": _num(v(r, "geracao")),
                    "prognostico_geracao": _num(v(r, "prognostico geracao")), "irradiacao": _num(v(r, "irradiacao")),
                    "prognostico_irradiacao": _num(v(r, "prognostico irradiacao")), "pr": _num(v(r, "pr")),
                    "disp_comunicacao": _num(v(r, "disponibilidade comunicacao")),
                    "disp_geracao": _num(v(r, "disponibilidade geracao"))})
    return out


_SEC = re.compile(r"DEBUG: PER.ODOS DOS INVERSORES USINA (\d+) - (.+?)\s+- DIA (\d{2})/(\d{2})/(\d{4})")
_RES = re.compile(r"RESUMO GERAL USINA (\d+) - (.+?)\s+- DIA")
_INV = re.compile(r"USINA\s*(\d+) - .+? - INVERSOR (\S+?):")
_PER = re.compile(r"^\s*\d+\.\s+(\d{4}-\d{2}-\d{2})\s+\|\s+(\d{2}:\d{2})\s+\S+\s+(\d{2}:\d{2})\s+\|\s+([\d.]+)\s+min")


def ler_debug(texto):
    """{nome sem id: {pvop_id, nome, janela, pac0, com, periodos: [(inversor, tipo, inicio, fim, minutos)]}} do debug."""
    out, atual, inv, tipo = {}, None, None, None
    for linha in (texto or "").splitlines():
        m = _SEC.search(linha) or _RES.search(linha)
        if m:
            atual = out.setdefault(sem_id(m[2]), {"pvop_id": m[1], "nome": m[2].strip(), "janela": None, "pac0": None,
                                                 "com": None, "periodos": []})
            inv = tipo = None
            continue
        if atual is None:
            continue
        m = _INV.search(linha)
        if m:
            inv, tipo = m[2], None
            continue
        if "PROBLEMAS DE COMUNICA" in linha:
            tipo = "comunicação"
        elif "PROBLEMAS DE GERA" in linha:
            tipo = "geração zerada"
        m = _PER.match(linha)
        if m and inv and tipo:
            atual["periodos"].append((inv, tipo, m[1] + "T" + m[2], m[1] + "T" + m[3], float(m[4])))
            continue
        for chave, rx in (("janela", r"Tempo total de gera..o:\s+([\d.]+)"),
                          ("pac0", r"problemas Pot.ncia ativa zerada:\s+([\d.]+)"),
                          ("com", r"problemas comunica..o:\s+([\d.]+)")):
            m = re.search(rx, linha)
            if m:
                atual[chave] = float(m[1])
    return out


def ler_arquivos(arquivos):
    """(dia, nome da planilha, planilha, debug, avisos) de {nome do arquivo: bytes} — o zip do e-mail é aberto aqui.
    Sem a planilha: ValueError."""
    soltos = {}
    for nome, b in arquivos.items():
        if nome.lower().endswith(".zip"):
            with zipfile.ZipFile(_io.BytesIO(b)) as z:
                for i in z.infolist():
                    if not i.is_dir():
                        soltos[i.filename.rsplit("/", 1)[-1]] = z.read(i)
        else:
            soltos[nome] = b
    plan = next(((k, v) for k, v in soltos.items()
                 if k.lower().startswith("relatorio_usinas") and k.lower().endswith(".xlsx")), None)
    if plan is None:
        raise ValueError("faltou a relatorio_usinas_AAAA-MM-DD.xlsx (o anexo do e-mail da PV Operation)")
    dia = dia_do_nome(plan[0])
    if dia is None:
        raise ValueError("o nome da planilha não traz o dia (relatorio_usinas_AAAA-MM-DD.xlsx)")
    dbg = next(((k, v) for k, v in soltos.items()
                if k.lower().startswith("debug_usinas") and k.lower().endswith(".txt")), None)
    avisos = [] if dbg else ["veio sem o debug: os períodos dos inversores ficam de fora"]
    if dbg and dia_do_nome(dbg[0]) not in (None, dia):
        avisos.append("o debug é de outro dia (%s): ficou de fora" % dbg[0])
        dbg = None
    texto = dbg[1].decode("utf-8", "replace") if dbg else ""
    return dia, plan[0], ler_planilha(plan[1]), ler_debug(texto), avisos


def montar(dia, arquivo, planilha, debug, sup_usina, sup_kwp, agora):
    """(linhas de disp_dia, linhas de periodo, nomes sem de-para)."""
    disp, per, sem = [], [], []
    em = agora.isoformat(timespec="seconds")
    for r in planilha:
        usina, kwp = casar(r["nome"], sup_usina, sup_kwp)
        if usina is None:
            sem.append(r["nome"])
        d = debug.get(sem_id(r["nome"])) or {}
        disp.append({"dia": dia.isoformat(), "nome": r["nome"], "pvop_id": d.get("pvop_id") or "", "usina": usina or "",
                     "kwp": round(kwp, 2) if kwp else "", "disp_geracao": r["disp_geracao"],
                     "disp_comunicacao": r["disp_comunicacao"], "geracao": r["geracao"],
                     "prognostico_geracao": r["prognostico_geracao"], "irradiacao": r["irradiacao"],
                     "prognostico_irradiacao": r["prognostico_irradiacao"], "pr": r["pr"],
                     "minutos_janela": d.get("janela"), "minutos_pac0": d.get("pac0"),
                     "minutos_comunicacao": d.get("com"), "arquivo": arquivo, "recebido_em": em})
        for inv, tipo, ini, fim, minutos in d.get("periodos") or ():
            per.append({"dia": dia.isoformat(), "nome": r["nome"], "pvop_id": d.get("pvop_id") or "",
                        "usina": usina or "", "inversor": inv, "tipo": tipo, "inicio": ini, "fim": fim,
                        "minutos": minutos, "recebido_em": em})
    return disp, per, sem


def trocar_dia(livro_banco, tok, livro, nome, aba, cab, dia, novas):
    """Grava as linhas do dia no livro, trocando as que já houver do mesmo dia (o e-mail que chega de novo). → linhas."""
    atuais = livro_banco.ler(livro, aba, tok)
    if not atuais:
        return livro_banco.acrescentar(livro, nome, aba, cab, novas, tok) if novas else 0
    ficam = [l for l in atuais if str(l.get("dia") or "")[:10] != dia.isoformat()]
    return livro_banco.regravar(livro, nome, aba, cab, ficam + list(novas), len(atuais), tok)


def por_usina(linhas, ano, mes):
    """{usina: {date: {pvop, sem_dado, partes}}} do mês, ponderado pelo kWp das partes (sem kWp: pesos iguais).
    `sem_dado`: toda parte com comunicação 0% e geração 0% (a PV Operation não teve dado; não é parada)."""
    acc = {}
    for l in linhas or ():
        u = str(l.get("usina") or "").strip()
        try:
            d = dt.date.fromisoformat(str(l.get("dia") or "")[:10])
        except ValueError:
            continue
        g = _num(l.get("disp_geracao"))
        if not u or g is None or (d.year, d.month) != (ano, mes):
            continue
        a = acc.setdefault(u, {}).setdefault(d, {"soma": 0.0, "peso": 0.0, "partes": [], "sem": True})
        w = _num(l.get("kwp")) or 1.0
        a["soma"] += g * w
        a["peso"] += w
        a["partes"].append(l)
        if (_num(l.get("disp_comunicacao")) or 0) > 0 or g > 0:
            a["sem"] = False
    return {u: {d: {"pvop": a["soma"] / a["peso"], "sem_dado": a["sem"], "partes": a["partes"]}
                for d, a in dias.items() if a["peso"]} for u, dias in acc.items()}


def resumo_periodos(periodos):
    """As linhas do que a PV Operation viu no dia: por parte e tipo, os trechos que se encostam juntados (do 1º início ao
    último fim) e em quantos inversores. Em 25/11 a Brodowski tinha 31 inversores sem comunicação de 16:52 a 17:24/17:25,
    cada um com o seu minuto de fim: uma linha por fim enchia a célula."""
    por = {}
    for p in periodos or ():
        ini, fim = str(p.get("inicio") or "")[11:16], str(p.get("fim") or "")[11:16]
        if ini and fim:
            por.setdefault((str(p.get("nome") or "").strip(), p.get("tipo") or ""), []).append((ini, fim, p.get("inversor")))
    out = []
    for (nome, tipo), trechos in por.items():
        blocos = []
        for ini, fim, inv in sorted(trechos):
            if blocos and ini <= blocos[-1][1]:
                blocos[-1][1] = max(blocos[-1][1], fim)
                blocos[-1][2].add(inv)
            else:
                blocos.append([ini, fim, {inv}])
        for ini, fim, invs in blocos:
            q = len(invs)
            out.append((nome, ini, tipo, "%s: %s de %s a %s (%d inversor%s)" % (nome, tipo, ini, fim, q,
                                                                              "es" if q > 1 else "")))
    return [x[3] for x in sorted(out)]
