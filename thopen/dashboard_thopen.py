# -*- coding: utf-8 -*-
"""Dashboard Thopen — Performance da Usina (réplica do Power BI), fonte = PostgreSQL.

Desde 28/08/2026 (Levi): "vamos continuar atualizando a geração no BD_Thopen mas todos os
dados vão ser puxados pelo postgresql". A coleta segue escrevendo no BD_Thopen.xlsx, o
`sync_gridco_api.py` leva o arquivo para o banco, e daqui o dashboard só LÊ do banco — o
`fonte_api` monta o mesmo workbook em memória, então todos os leitores abaixo continuam
operando sobre worksheets, sem uma linha de regra de negócio mudando de lugar.

Este app NÃO ABRE ARQUIVO NENHUM ("não pode ter nada de excel, tem que ser 100% postgresql"):
não há caminho de planilha nem pasta de snapshot. Se a API não responder, quem segura é o cache
em disco do `fonte_api` — a última leitura boa, com a idade dela na tela.

Reproduz o relatório "Performance da Usina":

  • Página Mensal: barras Produzida × Meta + tabela (Meta, Produzida, Diferença %,
    FC Meta, FC Real).  Fonte: tabela diária da usina (soma por mês) + `Historico_2026`
    (Meta/FC/PR) + `T_Usinas` (Potência MWp para o FC Real).
  • Página Diária: barras de energia/dia + linha de irradiação + linha de meta diária,
    KPIs (acumulado mês, irradiação real/meta, disponibilidade), produção anual
    (2023→2026, via `Historico`) e tabela de comentários.

Contas idênticas ao Power BI (ver as queries M de referência):
  • Produzida (MWh)  = Σ "Energia Produzida (kWh)" do mês / 1000
  • FC Real          = Produzida_kWh / (Pot_kWp × 24 × dias)   [dias = dia de hoje no
                       mês corrente, senão dias do mês] — espelha "Historico Atual (%)"
  • Diferença (%)    = (Produzida − Meta) / Meta
  • Meta diária      = Meta_mensal / dias_do_mês  (linha plana do gráfico diário)

Foco V1: Altair (mas o seletor lista todas as usinas que têm tabela diária).
Recarrega sozinho pelo TTL do `fonte_api`; o botão Atualizar derruba o cache. Porta 5080.
"""
import io
import os
import re
import json
import secrets
import threading
import unicodedata
import datetime as dt
from calendar import monthrange

from openpyxl.utils import range_boundaries
from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, send_file, session

import fonte_api             # leitura pelo PostgreSQL (Gridco Performance API) — ÚNICA fonte
import fonte_operacao        # Operação no Mês (08/10/2026): leitura própria, recarga em segundo plano
import operacao_mes          # ... e as contas puras do card do Diário (nada dos dois roda no import)
import rondas_cliente        # rodada 3 (09/10/2026): as rondas do mês na janela do card (puro)
import fotos_ronda           # ... as fotos delas, dos anexos da OS no Fracttal (nada roda no import)
import contestacao           # rodada 4: a contestação do cliente sobre um dia da tabela, que avisa a Grid Co. no Teams
import contestacao_banco     # rodada 5 (13/10/2026): ... e fica no banco, cifrada, para o Nexus (Contratos e clientes)
import acessos               # login por pessoa (14/10/2026): as contas vêm do Nexus, a senha o 5080 grava (o banco)
import geracao_possivel      # 20/10/2026: a geração possível pelo IPOA da Visão Geral e do Diário (puro)
import trip_os               # 23/10/2026: o trip das OS no comentário do dia, lido do Fracttal (nada roda no import)
import fonte_zeladoria       # 26/10/2026: a Zeladoria que o Nexus publica no banco (nada roda no import)
import zeladoria_cliente     # ... e a tela da semana (puro)

# ── Localização dos dados: não há ──────────────────────────────────────────────
# Este app NÃO ABRE ARQUIVO NENHUM (Levi, 28/08/2026: "não pode ter nada de excel, tem que ser
# 100% postgresql"). Não há caminho de planilha, pasta de snapshot nem THOPEN_DATA_DIR: o
# servidor de produção roda num link fixo, sem OneDrive, e um fallback para arquivo lá seria só
# uma forma silenciosa de servir dado velho. Se a API não responder, quem segura é o cache em
# disco do `fonte_api` — a última leitura boa, com a idade dela na tela.

ANO = 2026   # relatório do ano corrente (tabela Historico_2026 é 2026-específica)

# ── Comentários adicionais (campo digitável por usina, aba Diário) ───────────────
# ÚNICO dado que o app GRAVA (o resto é só leitura). Guardado num JSON {usina: texto}.
# Em servidor efêmero (Railway) o disco some a cada re-deploy → apontar COMENTARIOS_DIR para um
# VOLUME PERSISTENTE (ex.: /data). Sem a env, grava ao lado do script (ok local / máquina própria).
_COMENTARIOS_DIR = os.environ.get("COMENTARIOS_DIR") or os.path.dirname(os.path.abspath(__file__))
_COMENTARIOS_PATH = os.path.join(_COMENTARIOS_DIR, "comentarios_adicionais.json")
_com_lock = threading.Lock()


def _load_comentarios():
    try:
        with open(_COMENTARIOS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save_comentarios(data):
    with _com_lock:
        tmp = _COMENTARIOS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _COMENTARIOS_PATH)   # troca atômica


def _planilha_em():
    """Data/hora do dado que está na tela, formatada (ou None).

    É QUANDO ESTE DASHBOARD LEU o banco — não a hora do boot e não a hora de um arquivo. Com o
    cache em disco em uso, é a hora da leitura ORIGINAL: a tela mostra a idade real do dado."""
    ts = fonte_api.estado()["carregado_em"]
    return dt.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M") if ts else None


# ── Cache do workbook ──────────────────────────────────────────────────────────
_lock = threading.Lock()
_state = {"mtime": None, "path": None, "wb": None, "tbl": {}, "daily": {}, "df": {}}


def _ref_of(obj):
    return obj if isinstance(obj, str) else obj.ref


def _range_rows(ws, ref):
    c1, r1, c2, r2 = range_boundaries(ref)
    return list(ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2,
                             values_only=True))


def _header(ws, ref):
    c1, r1, c2, r2 = range_boundaries(ref)
    row = next(ws.iter_rows(min_row=r1, max_row=r1, min_col=c1, max_col=c2,
                            values_only=True), ())
    return [str(h).strip() if h is not None else "" for h in row]


def _usina_da_aba(ws, ref, hdr):
    """Nome OFICIAL da usina = valor da coluna 'Usina' DENTRO da aba (o dado real, que casa
    com as tabelas de meta/cadastro). É a chave correta — o título da aba é só um rótulo e
    às vezes vem abreviado/sem acento. Cai pro título da aba se não houver coluna 'Usina'."""
    iu = next((i for i, h in enumerate(hdr) if h.lower() == "usina"), None)
    if iu is None:
        return ws.title
    c1, r1, _c2, r2 = range_boundaries(ref)
    col = c1 + iu
    for row in ws.iter_rows(min_row=r1 + 1, max_row=min(r1 + 50, r2),
                            min_col=col, max_col=col, values_only=True):
        if row[0] not in (None, ""):
            return str(row[0]).strip()
    return ws.title


def _indexa(wb):
    """(tbl, daily) de um workbook: tabelas nomeadas + as tabelas diárias (header com
    'Energia Produzida')."""
    tbl, daily = {}, {}
    for ws in wb.worksheets:
        try:
            names = list(ws.tables.keys())
        except Exception:
            names = []
        for nm in names:
            ref = _ref_of(ws.tables[nm])
            tbl[nm] = (ws.title, ref)
            hdr = _header(ws, ref)
            hl = [h.lower() for h in hdr]
            # aba diária = tem 'Energia Produzida' E 'Data' (exclui resumos como "Clientes");
            # chave = nome da coluna 'Usina' (oficial), não o rótulo da aba
            if any("energia produzida" in h for h in hl) and "data" in hl:
                daily[_usina_da_aba(ws, ref, hdr)] = (ws.title, ref)
        if names:
            continue
        # ABA SEM TABELA NOMEADA -> sintetiza a "tabela" da própria aba (migração 25/08:
        # o espelho gerado da Gridco Performance API não carrega tabelas do Excel — a API
        # não as expõe — e sem este fallback `daily` ficava VAZIO e o dashboard inteiro
        # mudo). A régua de conteúdo continua a mesma; só a DESCOBERTA muda de fonte.
        ref = _ref_da_aba(ws)
        if not ref:
            continue
        hdr = _header(ws, ref)
        hl = [h.lower() for h in hdr]
        tbl[ws.title] = (ws.title, ref)
        if any("energia produzida" in h for h in hl) and "data" in hl:
            daily[_usina_da_aba(ws, ref, hdr)] = (ws.title, ref)
    return tbl, daily


def _wb():
    """Workbook em cache, indexado. A FONTE É O POSTGRESQL, e só ele (Levi, 28/08/2026).

    `fonte_api` monta o workbook em memória a partir da Gridco Performance API, então todos os
    leitores abaixo continuam sendo código de planilha e nenhuma regra de negócio mudou de lugar
    na migração. Se a API não responder, ele mesmo segura com a última leitura boa (memória ou
    cache em disco) — aqui não há segundo caminho.

    Assinatura do cache = o instante da carga (`carregado_em`), que muda a cada refresh de TTL.
    É o que invalida `_state['sheets']` e `_state['polaris']` junto."""
    with _lock:
        wb = fonte_api.workbook()
        if wb is None:
            raise RuntimeError(
                "sem dado: a API não respondeu e não há cache em disco. "
                "Confira %s e o /api/t/fonte." % fonte_api.BASE)
        if _state["wb"] is not wb:
            tbl, daily = _indexa(wb)
            _state.update(mtime=fonte_api.estado()["carregado_em"], path="api",
                          wb=wb, tbl=tbl, daily=daily, df={})
        return _state["wb"]


def _ref_da_aba(ws):
    """Ref sintética da área útil de uma aba SEM tabela nomeada: acha a linha de cabeçalho e a
    primeira coluna com conteúdo, e fecha no fim da aba.

    A linha de cabeçalho é a primeira (entre as 4 primeiras) que contenha "Usina" ou "Data" —
    é o que separa cabeçalho de LINHA DE TÍTULO: no BD_Thopen real, "Dados Mensais 2026",
    "Historico", "Dados Gerais Usinas", "Clientes", "Santana", "Sapopema" e "Saturnino" têm
    título/linha vazia acima do cabeçalho, e 5 abas começam na coluna B. Ler "de A1 até o fim"
    nessas oito daria cabeçalho errado e a aba sumiria das telas em silêncio."""
    from openpyxl.utils import get_column_letter
    for r in range(1, min(4, ws.max_row) + 1):
        vals = [str(c.value).strip().lower() if c.value is not None else "" for c in ws[r]]
        if any(v in ("usina", "data") for v in vals):
            c1 = next((i + 1 for i, v in enumerate(vals) if v), 1)
            return (f"{get_column_letter(c1)}{r}:"
                    f"{get_column_letter(ws.max_column)}{ws.max_row}")
    return None


def _cols(rows):
    """rows[0] = header. Devolve (header_list, data_rows)."""
    if not rows:
        return [], []
    hdr = [str(h).strip() if h is not None else "" for h in rows[0]]
    return hdr, rows[1:]


def _ci(hdr, *subs):
    """Índice da 1ª coluna cujo nome (minúsculo) contém TODOS os pedaços."""
    for i, h in enumerate(hdr):
        hl = h.lower()
        if all(s in hl for s in subs):
            return i
    return None


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    if "," in s:                       # formato pt-BR: 1.038.500,67
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _table(name):
    """(header, data_rows) de uma tabela nomeada, em cache."""
    wb = _wb()
    if name in _state["df"]:
        return _state["df"][name]
    # ALIAS DO HISTÓRICO ANUAL — e SÓ entre nomes com ANO. Este arquivo usa DUAS tabelas cujo
    # nome começa com "Historico", e elas têm formatos incompatíveis:
    #   Historico_2026 -> Usina | Ano | Mês | FC | Meta | Meta Irradiação | PR   (largo; _meta_mes)
    #   Historico      -> Usina | Ano | Mês | Tipo | Valor                       (longo; usado em
    #                                                                            outras duas telas)
    # Um alias por prefixo faria `_table("Historico_2026")` cair na `Historico` quando o ano virasse,
    # e a página anual mostraria meta/FC/PR vazios SEM erro nenhum. Então só troca de ano por ano —
    # nunca para a tabela sem sufixo.
    if name not in _state["tbl"] and re.fullmatch(r"(?i)historico[_ ]?\d{4}", str(name) or ""):
        _alt = next((k for k in _state["tbl"]
                     if re.fullmatch(r"(?i)historico[_ ]?\d{4}", str(k) or "")), None)
        if _alt:
            print(f"[BD_Thopen] tabela '{name}' não existe; usando '{_alt}' (mesmo formato anual)")
            name = _alt
    if name not in _state["tbl"]:
        # ESPELHO DA API: as tabelas nomeadas não existem (a API não as expõe) e as entradas de
        # `tbl` são as próprias ABAS. Cada nome fixo resolve pela ASSINATURA DE COLUNAS — nunca
        # por posição ou palpite, porque tabela errada aqui devolve dado plausível e errado:
        #   Historico_2026 -> formato LARGO (Meta + Irradiação + PR)
        #   Historico      -> formato LONGO (Tipo + Valor)
        #   T_Usinas       -> cadastro (Cliente + Estado/Cidade)
        _ASSIN = {
            "historico_2026": ("meta", "irradia"),
            "historico":      ("tipo", "valor"),
            "t_usinas":       ("cliente", "estado"),
        }
        _chave = str(name).strip().lower()
        _quer = _ASSIN.get(re.sub(r"[_ ]?\d{4}$", "_2026", _chave) if _chave.startswith("historico") and _chave != "historico" else _chave)
        if _quer:
            wb2 = _state["wb"]
            for k, (aba, ref) in _state["tbl"].items():
                hl = [h.lower() for h in _header(wb2[aba], ref)]
                if (any("usina" in h for h in hl)
                        and all(any(q in h for h in hl) for q in _quer)):
                    name = k
                    break
    out = ([], [])
    if name in _state["tbl"]:
        sheet, ref = _state["tbl"][name]
        out = _cols(_range_rows(wb[sheet], ref))
    _state["df"][name] = out
    return out


# ── Polaris: a aba "Histórico Polaris" do BD_Thopen é a CAMADA DE CORREÇÃO MANUAL por cima
#    das abas diárias (que vêm do PG do OEM). O de-para abaixo existe porque o nome que a
#    Polaris usa não é o nome canônico da coleta. ─────────────────────────────────────────
# nome no Budget (coluna "UFV 1")  →  nome de coleta canônico (igual T_Usinas/CARTEIRAS).
# De-para EXPLÍCITO (em vez da cadeia frágil de substituições do Power Query).
_POLARIS_NOME = {
    "UFV Aparecida do Taboado 2 1": "Aparecida do Taboado 1",
    "UFV Aparecida do Taboado 2 2": "Aparecida do Taboado 2",
    "UFV Aparecida III 1": "Aparecida 3",
    "UFV Araçoiaba da Serra I 1": "Araçoiaba da Serra 1",
    "UFV Araçoiaba da Serra I 2": "Araçoiaba da Serra 2",
    "UFV Boa Esperança do Sul I 1": "Boa Esperança do Sul 1",
    "UFV Boa Esperança do Sul I 2": "Boa Esperança do Sul 2",
    "UFV Caxambu I 1": "Caxambu",
    "UFV Goytacazes 1 1": "Goytacazes 1",
    "UFV Guaratinguetá 5 1": "Guaratinguetá V",
    "UFV Ibaté 1 1": "Ibaté 1",
    "UFV Ibaté 2 1": "Ibaté 2",
    "UFV Ipixuna 1 1": "Ipixuna 1",
    "UFV Ipixuna 2 1": "Ipixuna 2",
    "UFV Marajoara 1 1": "Marajoara 1",
    "UFV Piracicaba 1 1": "Piracicaba 1",
    "UFV Salto Pirapora 3 1": "Salto Pirapora 3",
    "UFV Santa Bárbara 1 1": "Santa Bárbara I",
    "UFV Santarem 1 1": "Santarém 1",
    "UFV Santarem 1 2": "Santarém 2",
    "UFV Santo Inácio 12 1": "Santo Inácio XII",
    "UFV São Bento 5 1": "São Bento V",
    "UFV Vargem Grande 1 1": "Vargem Grande 1",
    "UFV Araci 1 1": "Araci 1",
    "UFV Betânia 1 1": "Betânia 1",
    "UFV Boa Viagem 2 1": "Boa Viagem 2 1",
    "UFV Boa Viagem I 1": "Boa Viagem I 1",
    "UFV Ceará Mirim I 1": "Ceará Mirim I 1",
    "UFV Ceará Mirim I 2": "Ceará Mirim I 2",
    "UFV Delmiro Gouvea 1 1": "Delmiro Gouvea 1",
    "UFV Delmiro Gouvea 1 2": "Delmiro Gouvea 2",
    "UFV Delmiro Gouvea 1 3": "Delmiro Gouvea 3",
    "UFV Delmiro Gouvea 1 4": "Delmiro Gouvea 4",
    "UFV Goytacazes 4 2": "Goytacazes 4 2",
    "UFV Marajoara 2 1": "Marajoara 2 1",
    "UFV Piancó 1 1": "Piancó 1",
    "UFV Porteiras 1 1": "Porteiras 1",
    "UFV Porto Real 2 1": "Porto Real 2 1",
    "UFV Porto Real 3 1": "Porto Real 3",
    "UFV Urupês 1 1": "Urupês 1",
}
# lookup robusto (caixa-insensível) aceitando tanto o nome do Budget ("UFV …") quanto o já
# canônico — os Comentários Polaris usam o nome canônico ("Aparecida 3"), às vezes em CAIXA ALTA.
_POLARIS_LOOKUP = {}
for _k, _v in _POLARIS_NOME.items():
    _POLARIS_LOOKUP[_k.lower()] = _v
    _POLARIS_LOOKUP[_v.lower()] = _v

# Grafias que a planilha de Comentários usa e que não são nem o nome do Budget nem o canônico.
# "Aparecida III" apareceu em 09/09/2026: ao levar os comentários de agosto para o Histórico
# Polaris, 9 deles não casavam com nada e sumiriam CALADOS — o de-para conhecia "UFV Aparecida
# III 1" e "Aparecida 3", mas não a forma que o analista digita. Confirmado pelo Levi:
# "Aparecida 3 = Aparecida III". Nome que não casa some sem erro; por isso o alias fica aqui,
# e não num script solto.
_POLARIS_APELIDO = {
    "Aparecida III": "Aparecida 3",
}
for _k, _v in _POLARIS_APELIDO.items():
    _POLARIS_LOOKUP[_k.lower()] = _v


def _polaris_records():
    """{usina_canônica: {date: {ger, ipoa, disp, com}}} — a CAMADA DE CORREÇÃO da Polaris.

    Desde 28/08/2026 a fonte é a aba "Histórico Polaris" do próprio BD_Thopen (e portanto o
    PostgreSQL), não mais o Excel de Budget. Ela não repete o automático: as 22 usinas Polaris
    têm aba diária própria, alimentada pelo PG do OEM, e esta aba SOBRESCREVE campo a campo o
    que o Levi corrigir à mão — foi para isso que ele a pediu ("quando o BD falhar ou tiver com
    informação incompleta eu preencho lá"). Valor vazio aqui não apaga nada; deixa passar o
    automático.

    O Budget continua como FALLBACK e só isso: o snapshot da nuvem (data/) pode não ter a aba
    ainda, e sem ele essas usinas sumiriam do site publicado em silêncio."""
    _wb()
    entry = _state["tbl"].get("T_Hist_Polaris") or _state["tbl"].get("Histórico Polaris")
    if entry:
        sig = ("bd", _state["mtime"])
        cache = _state.get("polaris")
        if cache and cache.get("mtime") == sig:
            return cache["recs"]
        aba, ref = entry
        hdr, rows = _cols(_range_rows(_state["wb"][aba], ref))
        iD = _ci(hdr, "data"); iU = _ci(hdr, "usina")
        iG = _ci(hdr, "gera"); iI = _ci(hdr, "irradia")
        iP = _ci(hdr, "dispon"); iC = _ci(hdr, "coment")
        recs = {}
        for r in rows:
            u = str(r[iU]).strip() if iU is not None and r[iU] else None
            d = r[iD] if iD is not None else None
            if isinstance(d, dt.datetime):
                d = d.date()
            if not u or not isinstance(d, dt.date):
                continue
            recs.setdefault(_POLARIS_LOOKUP.get(u.lower(), u), {})[d] = {
                "ger": _num(r[iG]) if iG is not None else None,
                "ipoa": _num(r[iI]) if iI is not None else None,
                "disp": _num(r[iP]) if iP is not None else None,
                "com": (str(r[iC]).strip() or None) if iC is not None and r[iC] else None,
            }
        _state["polaris"] = {"mtime": sig, "recs": recs}
        return recs

    return {}          # sem a aba, não há Polaris — e não há de onde inventar


# ── Copel, Matrix, Caroá e Piancó: os actuals diários dessas usinas moram na aba
#    "Histórico Carteira" do BD_Thopen (coluna Fonte separa as carteiras). Antes vinham de
#    planilhas soltas no OneDrive; desde 28/08/2026 é tudo banco. A régua de corte segue: para
#    usina que TAMBÉM tem aba diária, o histórico vale até 01/06 e a aba diária depois disso.
_SHEET_CORTE = dt.date(2026, 6, 1)


def _corte_da_usina(bd):
    """Data a partir da qual a aba diária manda, para ESTA usina.

    POR QUE NÃO BASTA A DATA FIXA (achado de 04/09/2026): o corte em 01/06 valia para Santo
    Antonio, Sarandi e Segredo, onde o histórico termina em 31/05 e a aba diária começa em
    01/06 — emenda perfeita. Nos Pharmas não: o histórico do cliente vai até 31/07, mas a aba
    diária só começa em 01/08 (Pharma II), 27/08 (Pharma IV) ou nunca (Pharma III). Junho e
    julho caíam no vão — o histórico já tinha sido cortado e a aba ainda não tinha nascido — e
    o cliente via o gráfico com dois meses vazios.

    A régua passa a ser a MAIS TARDIA entre a data fixa e o primeiro dia em que a aba diária
    tem geração de fato. Assim:
      - quem emenda em 01/06 continua idêntico (a data fixa vence);
      - quem tem aba começando depois usa o histórico até lá;
      - aba sem nenhuma geração no ano devolve `date.max`, ou seja, histórico o ano inteiro.
    Linha com geração nula ou zero NÃO conta como início: as abas são criadas com o mês todo em
    branco, e contar a linha vazia traria de volta exatamente o buraco que isto conserta.
    """
    prim = min((r["data"] for r in bd.values()
                if r.get("ger") not in (None, 0) and r["data"].year == ANO), default=None)
    return max(_SHEET_CORTE, prim) if prim else dt.date.max


_NOME_CANON = {"Santo Antonio do Platina": "Santo Antonio da Platina"}
_BD_ALIAS = {v: k for k, v in _NOME_CANON.items()}   # canônico -> nome da aba no BD_Thopen


def _sheet_records():
    """{usina_canônica: {date: {ger,ipoa,disp,com}}} dos actuals de Copel, Matrix, Caroá e Piancó.

    Fonte única: a aba "Histórico Carteira" do BD_Thopen (tabela T_Hist_Carteira), onde a coluna
    Fonte separa as carteiras. Antes de 28/08/2026 cada uma vinha de uma planilha solta no
    OneDrive, e o Caroá tinha aba própria; hoje a atualização mensal do cliente entra direto no
    consolidado. O nome antigo da aba fica de alternativa porque o rename é recente."""
    _wb()                                     # garante _state['tbl'] atualizado
    sig = ("bd", _state["mtime"])
    cache = _state.get("sheets")
    if cache and cache.get("sig") == sig:
        return cache["recs"]

    def _acha(*nomes):
        for n in nomes:                       # tabela nomeada OU, no espelho da API, a própria aba
            if n in _state["tbl"]:
                return _state["tbl"][n]
        return None

    def _data(v):
        if isinstance(v, dt.datetime):
            return v.date()
        if isinstance(v, dt.date):
            return v
        try:                                  # espelho da API grava a data como texto ISO
            return dt.date.fromisoformat(str(v).strip()[:10])
        except (ValueError, TypeError):
            return None

    # A aba se chamava "Histórico Copel e Matrix" até 28/08/2026, quando passou a carregar
    # também Caroá e Piancó e virou "Histórico Carteira". Os dois nomes são aceitos.
    fontes_bd = [_acha("T_Hist_Carteira", "Histórico Carteira",
                       "T_Hist_Copel_Matrix", "Histórico Copel e Matrix")]
    fontes_bd = [f for f in fontes_bd if f]
    if fontes_bd:
        out = {}
        wb = _state["wb"]
        for aba, ref in fontes_bd:
            hdr, rows = _cols(_range_rows(wb[aba], ref))
            iD = _ci(hdr, "data"); iU = _ci(hdr, "usina")
            iG = _ci(hdr, "gera"); iI = _ci(hdr, "irradia")
            iP = _ci(hdr, "disp"); iC = _ci(hdr, "coment")
            if iD is None or iU is None:
                continue
            for r in rows:
                u = str(r[iU]).strip() if r[iU] else None
                day = _data(r[iD])
                if not u or not day:
                    continue
                u = _NOME_CANON.get(u, u)
                out.setdefault(u, {})[day] = {
                    "ger": _num(r[iG]) if iG is not None else None,
                    "ipoa": _num(r[iI]) if iI is not None else None,
                    "disp": _num(r[iP]) if iP is not None else None,
                    "com": (str(r[iC]).strip() or None) if iC is not None and r[iC] else None,
                }
        _state["sheets"] = {"sig": sig, "recs": out}
        return out

    return {}          # sem as abas, essas carteiras não têm outra fonte


# ── Leitura por domínio ─────────────────────────────────────────────────────────
def _daily_bd(usina):
    """Registros diários {data, ger, ipoa, disp, com} da tabela do BD_Thopen da usina."""
    key = ("recs", usina)
    if key in _state["df"]:
        return _state["df"][key]
    wb = _wb()
    entry = _state["daily"].get(usina)
    if entry is None and usina in _BD_ALIAS:
        entry = _state["daily"].get(_BD_ALIAS[usina])   # "Santo Antonio da Platina" -> aba "do Platina"
    recs = []
    if entry:
        sheet_title, ref = entry
        hdr, rows = _cols(_range_rows(wb[sheet_title], ref))
        iD = _ci(hdr, "data")
        iG = _ci(hdr, "energia produzida")
        iI = _ci(hdr, "ipoa")
        iDp = _ci(hdr, "disponibilidade", "usina")
        iC = _ci(hdr, "coment")
        for r in rows:
            d = r[iD] if iD is not None else None
            if not isinstance(d, (dt.datetime, dt.date)):
                continue
            com = None
            if iC is not None and r[iC] not in (None, ""):
                com = str(r[iC]).strip()
            recs.append({
                "data": d.date() if isinstance(d, dt.datetime) else d,
                "ger": _num(r[iG]) if iG is not None else None,
                "ipoa": _num(r[iI]) if iI is not None else None,
                "disp": _num(r[iDp]) if iDp is not None else None,
                "com": com,
            })
    _state["df"][key] = recs
    return recs


def _ghi_das_linhas(hdr, rows):
    """{data: GHI (kWh/m²)} das linhas de uma aba diária do BD_Thopen; `{}` sem a coluna GHI."""
    iD, iGhi = _ci(hdr, "data"), _ci(hdr, "ghi")
    if iD is None or iGhi is None:
        return {}
    out = {}
    for r in rows:
        d, v = r[iD], _num(r[iGhi])
        if isinstance(d, (dt.datetime, dt.date)) and v is not None:
            out[d.date() if isinstance(d, dt.datetime) else d] = v
    return out


def _ghi_por_dia(usina):
    """O GHI do dia da aba diária do BD_Thopen (20/10/2026: a reserva da ETM na geração possível, quando o IPOA falta ou
    é < 0,3). Leitor próprio de propósito: o `_daily_records` é usado pela plataforma e não muda de formato. As fontes
    da Polaris, Copel e Matrix não têm GHI: `{}` e só a ETM conta."""
    key = ("ghi", usina)
    if key in _state["df"]:
        return _state["df"][key]
    wb = _wb()
    entry = _state["daily"].get(usina)
    if entry is None and usina in _BD_ALIAS:
        entry = _state["daily"].get(_BD_ALIAS[usina])
    out = {}
    if entry:
        sheet_title, ref = entry
        out = _ghi_das_linhas(*_cols(_range_rows(wb[sheet_title], ref)))
    _state["df"][key] = out
    return out


def _daily_inversores(usina):
    """Registros diários da tabela do BD_Thopen da usina COM a geração por inversor (colunas "Inversor N.M"):
    [{data, ger, ipoa, validacao, inv: {nome da coluna: kWh}}]. Mesma tabela e mesma resolução de aba do
    `_daily_bd`; separado porque o dashboard 5080 não olha inversor e a plataforma 5050 precisa dele para o
    histórico do Diagnóstico ("para usinas Thopen as informações de histórico do diagnóstico tem que pegar do
    BD_Thopen" — Levi, 08/09/2026). Célula vazia não vira zero: é ausência (linha pré-criada do mês)."""
    key = ("recs_inv", usina)
    if key in _state["df"]:
        return _state["df"][key]
    wb = _wb()
    entry = _state["daily"].get(usina)
    if entry is None and usina in _BD_ALIAS:
        entry = _state["daily"].get(_BD_ALIAS[usina])
    recs = []
    if entry:
        sheet_title, ref = entry
        hdr, rows = _cols(_range_rows(wb[sheet_title], ref))
        iD = _ci(hdr, "data")
        iG = _ci(hdr, "energia produzida")
        iI = _ci(hdr, "ipoa")
        iV = _ci(hdr, "valida")
        inv_cols = [(i, h) for i, h in enumerate(hdr) if h.lower().startswith("inversor")]
        for r in rows:
            d = r[iD] if iD is not None else None
            if not isinstance(d, (dt.datetime, dt.date)):
                continue
            inv = {}
            for i, nome in inv_cols:
                v = _num(r[i]) if i < len(r) else None
                if v is not None:
                    inv[nome] = v
            recs.append({
                "data": d.date() if isinstance(d, dt.datetime) else d,
                "ger": _num(r[iG]) if iG is not None else None,
                "ipoa": _num(r[iI]) if iI is not None else None,
                "validacao": _num(r[iV]) if (iV is not None and iV < len(r)) else None,
                "inv": inv,
            })
    _state["df"][key] = recs
    return recs


def _daily_records(usina):
    """Idem `_daily_records_todos`, mas SEM os dias que ainda não aconteceram.

    O BD nasce com o mês inteiro pré-criado, e os dias futuros chegam com geração 0 e
    disponibilidade 0. Se entrassem na conta, o mês corrente ficaria irreconhecível: em
    17/08/2026 a frota aparecia com disponibilidade de ~42% e a produção do mês ~77% abaixo
    da meta, só porque 14 dias que nem existiam ainda entravam como zero."""
    hoje = dt.date.today()
    return [r for r in _daily_records_todos(usina) if r["data"] <= hoje]


def _daily_records_todos(usina):
    """{data, ger, ipoa, disp, com} por usina. Polaris = aba diária (PG do OEM) CORRIGIDA pela
    aba "Histórico Polaris"; Matrix/Copel = planilha externa com corte (planilha < 01/06 +
    BD_Thopen >= 01/06 se a usina existir no BD; senão planilha inteira); o resto = BD_Thopen."""
    pol = _polaris_records()
    if usina in pol:
        # correção manual SOBRESCREVE o automático campo a campo — célula vazia lá não apaga o
        # dado daqui. Usina sem aba diária (Vargem Grande 1) fica só com a correção, que é a
        # única fonte que ela tem.
        base = {r["data"]: dict(r) for r in _daily_bd(usina)}
        for d, e in pol[usina].items():
            alvo = base.setdefault(d, {"data": d, "ger": None, "ipoa": None,
                                       "disp": None, "com": None})
            for k in ("ger", "ipoa", "disp", "com"):
                if e.get(k) is not None:
                    alvo[k] = e[k]
        return sorted(base.values(), key=lambda r: r["data"])
    sheet = _sheet_records().get(usina)
    if sheet:
        bd = {r["data"]: r for r in _daily_bd(usina)}
        if bd:   # usina existe no BD_Thopen → histórico antes do corte + BD a partir do corte
            corte = _corte_da_usina(bd)
            recs = [{"data": d, "ger": e.get("ger"), "ipoa": e.get("ipoa"),
                     "disp": e.get("disp"), "com": e.get("com")}
                    for d, e in sheet.items() if d.year == ANO and d < corte]
            recs += [r for r in bd.values() if r["data"] >= corte]
        else:    # usina fora do BD_Thopen → planilha inteira (todas as datas do ano)
            recs = [{"data": d, "ger": e.get("ger"), "ipoa": e.get("ipoa"),
                     "disp": e.get("disp"), "com": e.get("com")}
                    for d, e in sheet.items() if d.year == ANO]
        recs.sort(key=lambda r: r["data"])
        return recs
    return _daily_bd(usina)


def _norm_nome(s):
    """Chave de comparação de nome: sem acento, sem caixa, sem espaço repetido.
    SÓ CASA — nunca renomeia nada na planilha (regra do Levi para todo de-para daqui)."""
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


# De-para de nome usado APENAS para ACHAR a meta. Cada linha é um caso real medido em 10/09/2026:
# a usina existe no cadastro (`T_Usinas`) com um nome e a meta do cliente veio com outro, e o
# dashboard mostrava a usina "sem meta" em silêncio — o mesmo sintoma que fez a Cipó Guaçu passar
# meses invisível. Explícito de propósito, como o `_POLARIS_NOME`: uma regra automática do tipo
# "ignore o I" ou "ignore o 1 solto" casaria `Ouro Branco 1` com `Ouro Branco 2`.
_META_NOME = {
    # nome no cadastro          nome onde a meta está
    "Boa Viagem I 1":           "Boa Viagem 1",
    "Ceará Mirim I 1":          "Ceará Mirim 1",
    "Ceará Mirim I 2":          "Ceará Mirim 2",
    "Delmiro Gouvea 2":         "Delmiro Gouvea 1 2",
    "Delmiro Gouvea 3":         "Delmiro Gouvea 1 3",
    "Delmiro Gouvea 4":         "Delmiro Gouvea 1 4",
    "Porto Real 3":             "Porto Real 3 1",
    # a aba `Historico` escreve sem o "a" final; o cadastro e a tabela derivada escrevem com ele
    "Córrego do Sapucaia":      "Córrego do Sapucai",
}

_META_CAMPOS = ("meta", "fc", "metairr", "pr")


def _mes_do_valor(mv):
    """Numero do mes (1..12) a partir da coluna `Mês`, venha ela como for.

    Em 11/09/2026 a coluna `Mês` da tabela `Historico_2026` perdeu o formato de data e passou a
    chegar como o SERIAL cru do Excel (46023, 46054...). O código fazia `_num(mv)` e gravava a
    meta na chave 46023; a tela procura 1..12, não acha, e a usina aparece SEM META — em 32
    usinas de uma vez, calado. Formatação de planilha não pode derrubar dado: aqui o serial vira
    data antes de virar mês.
    """
    if isinstance(mv, (dt.datetime, dt.date)):
        return mv.month
    n = _num(mv)
    if not n:
        return None
    n = int(n)
    if 1 <= n <= 12:
        return n
    if n > 366:                      # serial do Excel (base 30/12/1899)
        try:
            return (dt.date(1899, 12, 30) + dt.timedelta(days=n)).month
        except (OverflowError, ValueError):
            return None
    return None


def _hist_pivot():
    """{(nome_normalizado, mês): {meta, fc, metairr, pr}} pivotado da tabela `Historico`.

    POR QUE NÃO BASTA A `Historico_2026`: aquela tabela é **saída de Power Query** ("Consulta -
    Historico") e só se refaz quando um humano abre o Excel e manda atualizar. Em 10/09/2026 a
    Cipó Guaçu aparecia "sem meta" por isso — os 12 meses dela estavam na `Historico` desde
    sempre e a tabela derivada nunca tinha sido refeita. Pivotando na leitura, meta colada na
    `Historico` vale na hora, sem depender de ninguém abrir a planilha.

    A `Historico` é LONGA (Usina | Ano | Mês | Tipo | Valor) e guarda vários anos; aqui entram só
    os quatro tipos do ANO corrente.
    """
    if ("hist_piv",) in _state["df"]:
        return _state["df"][("hist_piv",)]
    alvo = {"fc (%d)" % ANO: "fc", "meta (%d)" % ANO: "meta",
            "meta irradiação (%d)" % ANO: "metairr", "pr (%d)" % ANO: "pr"}
    hdr, rows = _table("Historico")
    out = {}
    iU = _ci(hdr, "usina") if hdr else None
    iMes = (_ci(hdr, "mês") if hdr and _ci(hdr, "mês") is not None else
            (_ci(hdr, "mes") if hdr else None))
    iTipo = _ci(hdr, "tipo") if hdr else None
    iVal = _ci(hdr, "valor") if hdr else None
    if None not in (iU, iMes, iTipo, iVal):
        for r in rows:
            u = r[iU]
            # o `Tipo` chega com espaço sobrando em parte das linhas (ex.: " Produzida (2023)")
            k = alvo.get(str(r[iTipo]).strip().lower()) if r[iTipo] is not None else None
            if not isinstance(u, str) or not k:
                continue
            mv = r[iMes]
            m = _mes_do_valor(mv)
            if not m:
                continue
            out.setdefault((_norm_nome(u), int(m)), {})[k] = _num(r[iVal])
    _state["df"][("hist_piv",)] = out
    return out


def _meta_tabela():
    """{(nome_normalizado, mês): {meta, fc, metairr, pr}} da tabela LARGA `Historico_2026`."""
    if ("meta_tbl",) in _state["df"]:
        return _state["df"][("meta_tbl",)]
    hdr, rows = _table("Historico_2026")
    out = {}
    if hdr:
        iU = _ci(hdr, "usina")
        iMes = _ci(hdr, "mês") if _ci(hdr, "mês") is not None else _ci(hdr, "mes")
        iFC = _ci(hdr, "fc")
        iMeta = _ci(hdr, "meta (%d)" % ANO)
        iIrr = _ci(hdr, "irradia")
        iPR = _ci(hdr, "pr")
        for r in rows:
            if iU is None or not isinstance(r[iU], str):
                continue
            mv = r[iMes]
            m = _mes_do_valor(mv)
            if not m:
                continue
            out[(_norm_nome(r[iU]), int(m))] = {
                "meta": _num(r[iMeta]) if iMeta is not None else None,
                "fc": _num(r[iFC]) if iFC is not None else None,
                "metairr": _num(r[iIrr]) if iIrr is not None else None,
                "pr": _num(r[iPR]) if iPR is not None else None,
            }
    _state["df"][("meta_tbl",)] = out
    return out


def _meta2026(usina):
    """{mes: {meta(kWh), fc, metairr, pr}} para a usina.

    Duas fontes, nesta ordem de precedência, campo a campo:
      1. `Historico` pivotada — a verdade, porque é onde a meta é COLADA (ver `_hist_pivot`);
      2. `Historico_2026`, a tabela derivada — reserva. Não é redundância: Caicó, Diamantino e
         Itajá existem SÓ nela, e cortar a reserva apagaria a meta dessas três da tela.

    Campo vazio na fonte 1 NÃO apaga o valor da fonte 2 — foi o que se viu no Lyon, cujo PR está
    preenchido na `Historico` e vazio na tabela derivada (e o inverso acontece em outras).
    """
    chaves = []
    for c in (usina, _META_NOME.get(usina)):
        k = _norm_nome(c) if c else None
        if k and k not in chaves:
            chaves.append(k)

    piv, tbl = _hist_pivot(), _meta_tabela()
    out = {}
    for fonte in (tbl, piv):                    # piv depois: sobrescreve campo a campo
        for k in chaves:
            for mes in range(1, 13):
                e = fonte.get((k, mes))
                if not e:
                    continue
                alvo = out.setdefault(mes, {c: None for c in _META_CAMPOS})
                for c in _META_CAMPOS:
                    if e.get(c) is not None:
                        alvo[c] = e[c]
    return out


def _registro():
    """{usina: {nome, cidade, estado, cliente, pot_mwp}} (tabela T_Usinas)."""
    if ("reg",) in _state["df"]:
        return _state["df"][("reg",)]
    hdr, rows = _table("T_Usinas")
    out = {}
    if hdr:
        iU = _ci(hdr, "usina")
        iNome = _ci(hdr, "nome")
        iCid = _ci(hdr, "cidade")
        iEst = _ci(hdr, "estado")
        iCli = _ci(hdr, "cliente")
        iPot = _ci(hdr, "mwp")
        for r in rows:
            u = r[iU] if iU is not None else None
            if not u:
                continue
            out[str(u).strip()] = {
                "nome": r[iNome] if iNome is not None else None,
                "cidade": r[iCid] if iCid is not None else None,
                "estado": r[iEst] if iEst is not None else None,
                "cliente": r[iCli] if iCli is not None else None,
                "pot_mwp": _num(r[iPot]) if iPot is not None else None,
            }
    # Dado inconsistente no BD_Thopen: T_Usinas chama "Vargem Grande IB", mas meta/histórico/
    # relatório usam "Vargem Grande 1" (o de-para do Power BI normaliza p/ "Vargem Grande 1").
    # Alias p/ a potência/cadastro casar com o nome canônico que usamos.
    if "Vargem Grande IB" in out:
        out.setdefault("Vargem Grande 1", out["Vargem Grande IB"])
    _state["df"][("reg",)] = out
    return out


# De-para do nome da PRODUÇÃO dos anos anteriores na aba `Historico` (Levi, 09/10/2026: "O dado de Produzida 2025
# sumiu do dash do cliente"). A aba guarda alguns anos com outro nome que o resto da usina (metas, FC, PR e os outros
# anos): a Nova Londrina tem 2025 como "Nova Londrina 1", e o 5080, que procura o nome exato, perdia o ano calado.
# Explícito de propósito, como o `_META_NOME`: uma regra automática ("ignore o 1") juntaria a Nova Londrina 2 ou a
# Primavera 1 com a usina inteira. Cada linha conferida pelos números em 09/10. Um ano lido pelo nome do 5080 VENCE o
# mesmo ano por um nome daqui — nunca soma os dois (seria o ano em dobro).
_HIST_NOME = {
    # nome no 5080            nome(s) onde a produção daquele ano está
    "Nova Londrina":          ("Nova Londrina 1",),                 # 2025 = 98% da meta 2025 da usina (jan a mai)
    "Rondonópolis":           ("Rondonopolis",),                    # 2025 = 98% da meta 2025
    "Monte Aprazível":        ("Monte Aprazivel", "Monte APrazivel"),   # 2024 e 2023
    "Poconé 1":               ("Poconé",),                          # 2025
    "Vargem Grande 1":        ("Vargem Grande",),                   # 2025
    # Levi, 09/10: A = Araçoiaba da Serra 1 (THPN-ADS100), B = 2 (THPN-ADS200) — os números não decidem sozinhos
    "Araçoiaba da Serra 1":   ("Araçoiaba da Serra A",),
    "Araçoiaba da Serra 2":   ("Araçoiaba da Serra B",),
}


def _nomes_hist(usina):
    """O nome do 5080 primeiro, depois os do `_HIST_NOME` — a ordem é a preferência."""
    return (usina,) + _HIST_NOME.get(usina, ())


def _produzida_mensal(usina, ano):
    """{mes: kWh} de 'Produzida (<ano>)' (linhas COM mês) — para o comparativo mensal. O ano vem do primeiro nome da
    usina (`_nomes_hist`) que o tem."""
    hdr, rows = _table("Historico")
    if not hdr:
        return {}
    iU = _ci(hdr, "usina")
    iMes = _ci(hdr, "mês")
    iTipo = _ci(hdr, "tipo")
    iVal = _ci(hdr, "valor")
    alvo = str(ano)
    nomes = _nomes_hist(usina)
    por_nome = {}
    for r in rows:
        nome = str(r[iU]).strip() if iU is not None else ""
        if nome not in nomes:
            continue
        tipo = str(r[iTipo]).strip().lower() if iTipo is not None else ""
        if "produzida" not in tipo or alvo not in tipo:
            continue
        mv = r[iMes] if iMes is not None else None
        if isinstance(mv, (dt.datetime, dt.date)):
            v = _num(r[iVal]) if iVal is not None else None
            if v is not None:
                out = por_nome.setdefault(nome, {})
                out[mv.month] = out.get(mv.month, 0.0) + v
    return next((por_nome[n] for n in nomes if por_nome.get(n)), {})


def _produzida_anual(usina):
    """{ano(str): kWh}. Usa o TOTAL anual explícito (linha com Mês vazio) quando existe;
    senão soma os meses. Evita contar em DOBRO quando há AMBOS (ex.: 2023/2024 ganharam
    linhas mensais mas mantiveram a linha de total anual)."""
    hdr, rows = _table("Historico")
    if not hdr:
        return {}
    iU = _ci(hdr, "usina")
    iAno = _ci(hdr, "ano")
    iMes = _ci(hdr, "mês")
    iTipo = _ci(hdr, "tipo")
    iVal = _ci(hdr, "valor")
    nomes = _nomes_hist(usina)
    total, mensal = {n: {} for n in nomes}, {n: {} for n in nomes}
    for r in rows:
        nome = str(r[iU]).strip() if iU is not None else ""
        if nome not in nomes:
            continue
        tipo = str(r[iTipo]).strip().lower() if iTipo is not None else ""
        if not tipo.startswith("produzida"):
            continue
        v = _num(r[iVal]) if iVal is not None else None
        if v is None:
            continue
        ano = str(r[iAno]).strip() if iAno is not None else ""
        mv = r[iMes] if iMes is not None else None
        if isinstance(mv, (dt.datetime, dt.date)):
            mensal[nome][ano] = mensal[nome].get(ano, 0.0) + v
        else:
            total[nome][ano] = total[nome].get(ano, 0.0) + v
    out = {}
    for n in nomes:                       # o ano fica com o primeiro nome que o tem (_HIST_NOME): nunca soma os dois
        for a in set(total[n]) | set(mensal[n]):
            if a not in out:
                out[a] = total[n][a] if a in total[n] else mensal[n].get(a)
    return out


def _prod_mensal_ano(usina, ano):
    """{mes: kWh} de um ANO. Usinas de planilha externa (Matrix/Copel) puxam o histórico da
    PRÓPRIA planilha — não do BD Historico. É por isso que 'Produzida 2025' = o que a planilha
    registra em 2025 (só dez/2025, quando essas séries começam), igual ao Power BI; o BD Historico
    dessas usinas pode ter o ano inteiro real (ex.: Sarandi 2025 no BD = 11,6M) e NÃO deve ser usado."""
    e = _sheet_records().get(usina)
    if e is not None:
        out = {}
        for day, cel in e.items():
            if day.year == ano and cel.get("ger") is not None:
                out[day.month] = out.get(day.month, 0.0) + cel["ger"]
        return out
    return _produzida_mensal(usina, ano)


def _prod_anual_por_usina(usina):
    """{ano(str): kWh} p/ o gráfico anual. Usinas de planilha → soma da planilha (anos < ANO);
    demais → BD Historico."""
    if usina in _sheet_records():
        out = {}
        for y in (ANO - 3, ANO - 2, ANO - 1):
            mm = _prod_mensal_ano(usina, y)
            if mm:
                out[str(y)] = sum(mm.values())
        return out
    return _produzida_anual(usina)


# ── Endpoints ─────────────────────────────────────────────────────────────────
app = Flask(__name__)

# ── Login por pessoa (Levi, 14/10/2026: "É possível implementarmos uma visão de login e senha para o dashboard
# thopen?"; spec docs/superpowers/specs/2026-10-14-thopen-login-por-pessoa-design.md). Contas por pessoa, ligadas a um
# cliente (as carteiras que ela vê), administradas no Nexus (Contratos e clientes → Acessos dos clientes); o dashboard
# sobe no servidor da T.I. em https://app.gridco.com.br/performance/ (entrada em /performance/login).
# THOPEN_LOGIN=1 liga; sem ela o 5080 segue público como antes (o código sobe antes das contas existirem).
# THOPEN_PREFIXO=/performance: o app funciona com o Caddy tirando ou não o prefixo, e gera os endereços com ele.
PREFIXO = (os.environ.get("THOPEN_PREFIXO") or "").strip().rstrip("/")
# a chave da sessão (assina o cookie): sem ela, uma por processo — quem estava dentro entra de novo depois de reiniciar
app.secret_key = fonte_api.segredo("THOPEN_SESSAO_CHAVE") or secrets.token_hex(32)
# cookie próprio: o mesmo domínio tem o `session` da plataforma e o `nexus_sessao` do Nexus (a porta única de 09/10
# mostrou o `session` colidindo). Secure por padrão (HTTPS no servidor); THOPEN_COOKIE_SEGURO=0 só para o http local
app.config.update(SESSION_COOKIE_NAME="thopen_sessao", SESSION_COOKIE_PATH=PREFIXO or "/", SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("THOPEN_COOKIE_SEGURO", "1").strip() != "0",
                  PERMANENT_SESSION_LIFETIME=dt.timedelta(hours=12))


class _Prefixo:
    """Serve o app debaixo de um caminho (/performance): o Caddy pode passar o caminho inteiro (handle) ou sem o prefixo
    (handle_path) — os dois funcionam, e os endereços gerados (url_for, request.script_root) levam o prefixo."""

    def __init__(self, app_wsgi, prefixo):
        self.app_wsgi, self.prefixo = app_wsgi, prefixo

    def __call__(self, environ, start_response):
        caminho = environ.get("PATH_INFO", "")
        if caminho == self.prefixo or caminho.startswith(self.prefixo + "/"):
            environ["PATH_INFO"] = caminho[len(self.prefixo):] or "/"
        environ["SCRIPT_NAME"] = self.prefixo
        return self.app_wsgi(environ, start_response)


if PREFIXO:
    app.wsgi_app = _Prefixo(app.wsgi_app, PREFIXO)

_TENTATIVAS = acessos.Limite(tentativas=5, janela=900)    # 5 erros em 15 min, por conta ou por endereço = espera
_LIVRES = {"login", "logout", "convite", "static"}       # o que abre sem sessão


def _login_ligado():
    return os.environ.get("THOPEN_LOGIN", "").strip() == "1"


def _ip():
    return request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For", "").split(",")[0].strip() \
        or request.remote_addr or "?"


def _usuario():
    """A conta da sessão, relida a cada pedido do cache de 2 min: desativada no Nexus = fora."""
    if "usuario" not in g:
        cid = session.get("conta_id")
        g.usuario = acessos.conta(cid) if cid else None
        if cid and g.usuario is None:
            session.clear()
    return g.usuario


def _pode(usina):
    """A conta vê esta usina? Login desligado ou papel grid: todas. Cliente: só as das carteiras dele."""
    if not _login_ligado():
        return True
    u = _usuario()
    if not u:
        return False
    if u["papel"] == "grid":
        return True
    return _CARTEIRA_DE.get(_NOME_CANON.get(usina, usina)) in set(u["carteiras"])


def _carteiras_vistas():
    if not _login_ligado():
        return list(CARTEIRA_ORDEM)
    u = _usuario() or {}
    return list(CARTEIRA_ORDEM) if u.get("papel") == "grid" else [c for c in CARTEIRA_ORDEM if c in (u.get("carteiras") or [])]


def _e_grid():
    return not _login_ligado() or (_usuario() or {}).get("papel") == "grid"


# O que o cliente já pode ver (Levi, 27/10/2026: "vamos subir as atualizações primeiro para o usuário de performance, o
# usuário thopen que é o do cliente só vê se eu liberar"). Novidade sobe com a chave aqui em False: o papel grid (a conta
# Performance) vê assim que o servidor anda; a conta de cliente só quando o Levi liberar (trocar para True e subir).
LIBERADO_AO_CLIENTE = {
    "zeladoria": False,   # a aba Zeladoria (26/10/2026); 27/10: "zeladoria pode tirar da visualização do cliente"
}


def _liberado(chave):
    return _e_grid() or bool(LIBERADO_AO_CLIENTE.get(chave))


def _op_dados():
    """A operação do mês (a disponibilidade da Thopen pelas normalizações do COS desde 29/10/2026, a mesma para todas as
    contas desde a liberação de 30/10/2026: a conta de antes, só do Fracttal, saiu)."""
    return fonte_operacao.dados()


_POR_USINA = {"overview", "diario", "api_operacao", "api_rondas"}       # ?usina=
_SO_GRID = {"comentario_extra", "reload_bd"}                           # gravar e forçar a releitura


@app.before_request
def _portao():
    """Com THOPEN_LOGIN=1: tudo pede sessão (menos entrar, convite, sair e os estáticos) e cada conta só vê as usinas
    das carteiras dela. A API responde 401/403; a página vai para a entrada."""
    if not _login_ligado() or request.endpoint in _LIVRES:
        return None
    if not _usuario():
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "erro": "Sua sessão terminou. Entre de novo."}), 401
        return redirect(request.script_root + "/login")
    ep = request.endpoint
    if ep == "api_zeladoria" and not _liberado("zeladoria"):
        return jsonify({"ok": False, "erro": "Esta tela ainda não está liberada."}), 403
    fora = jsonify({"ok": False, "erro": "Esta usina não está no seu acesso."}), 403
    if ep in _POR_USINA and not _pode(request.args.get("usina", "")):
        return fora
    if ep in ("geral", "registros", "registros_xlsx", "api_zeladoria")             and request.args.get("carteira", "Thopen") not in _carteiras_vistas():
        return fora
    if ep == "api_contestar" and not _pode(str((request.get_json(silent=True) or {}).get("usina") or "").strip()):
        return fora
    if ep in ("api_ronda", "api_ronda_foto"):
        r = rondas_cliente.da_os(fonte_operacao.dados(), (request.view_args or {}).get("os_"))
        nomes = {str(x.get("chave_externa") or "") for x in (fonte_operacao.dados() or {}).get("de_para") or []
                 if r and operacao_mes._int(x.get("usina_id")) == operacao_mes._int(r.get("usina_id"))}
        if r and not any(_pode(n) for n in nomes):
            return jsonify({"ok": False, "erro": "ronda não encontrada"}), 404
    if ep in _SO_GRID and not _e_grid():
        return jsonify({"ok": False, "erro": "Só a Grid Co. pode fazer isto."}), 403
    return None


def _entrar(conta):
    session.clear()                       # sessão nova a cada entrada (nada da anterior sobra)
    session.permanent = True
    session["conta_id"] = conta["conta_id"]


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        # o usuário de hoje do cliente ou um e-mail (15/10/2026, Levi: "Mesmo usuário e senha de hoje")
        login_ = str(request.form.get("usuario") or "").strip().lower()
        chaves = ("ip:" + _ip(), "conta:" + login_)
        if any(_TENTATIVAS.bloqueado(k) for k in chaves):
            erro = "Muitas tentativas. Espere 15 minutos e tente de novo."
        else:
            conta = acessos.verificar(login_, request.form.get("senha") or "")
            if conta:
                for k in chaves:
                    _TENTATIVAS.zerar(k)
                _entrar(conta)
                return redirect(request.script_root + "/")
            for k in chaves:
                _TENTATIVAS.erro(k)
            erro = ("O login não está disponível agora. Fale com a Grid Co." if acessos.estado()["erro"]
                    and not acessos.estado()["contas"] else "Usuário ou senha não conferem.")
    return render_template("entrar.html", modo="login", erro=erro, raiz=request.script_root,
                           usuario=request.form.get("usuario", "") if request.method == "POST" else "")


@app.route("/convite/<token>", methods=["GET", "POST"])
def convite(token):
    """O link de uso único que a Grid Co. gera no Nexus: definir a senha (a 1ª, ou uma nova) e já entrar."""
    conta, motivo = acessos.convite(token)
    # 15/10/2026: o "Salvar e entrar" clicado várias vezes mandava o formulário de novo — o 1º gravava a senha e já
    # entrava, e o 2º mostrava "Este link já foi usado" por cima. Link usado com a pessoa já conectada: vai ao painel
    if motivo == "usado" and _usuario():
        return redirect(request.script_root + "/")
    erro = None if motivo == "ok" else acessos.MOTIVOS.get(motivo, acessos.MOTIVOS["invalido"])
    if request.method == "POST" and conta:
        s1, s2 = request.form.get("senha") or "", request.form.get("senha2") or ""
        if s1 != s2:
            erro = "As duas senhas não são iguais."
        else:
            try:
                _entrar(acessos.definir_senha(token, s1))
                return redirect(request.script_root + "/")
            except acessos.Recusada as e:
                erro = str(e)
            except Exception as e:               # noqa: BLE001 — banco fora: a senha não foi gravada
                print("[acessos] não gravei a senha: %s" % type(e).__name__, flush=True)
                erro = "Não consegui gravar agora. Tente de novo em alguns minutos."
    return render_template("entrar.html", modo="convite", erro=erro, conta=conta, raiz=request.script_root,
                           minimo=acessos.SENHA_MIN)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(request.script_root + "/login")


# ── Carteiras (cliente dono do portfólio) → usinas pelo NOME DE COLETA (coluna "Usina") ──────
# De-para fixo aqui porque a coluna "Cliente" da aba "Dados Gerais Usinas" está vazia. Os nomes
# usados pelo cliente ("UFV …", "Ouro Branco X - Y", "Aparecida III"…) foram casados com a coluna
# de coleta via "Usina"/"Nome" do T_Usinas. Inclui usinas ainda NÃO coletadas (sem aba de dados):
# elas só aparecem no botão quando passarem a ter dados — o frontend filtra pela lista disponível.
CARTEIRAS = {
    "Thopen": [
        "Altair", "Alto Paraná 1", "Alto Paraná 2", "AP. do Taboado", "Areia Branca", "Aruanã",
        "Barretos", "Bernardino de Campos", "Brodowski", "Canarana 1", "Canarana 2", "Ceilândia 1",
        "Ceilândia 2", "Céu Azul", "Cidade Gaucha", "Colorado 1", "Colorado 2", "Coração 1",
        "Coração 2", "Embu Guaçu", "Fazenda Limão", "Fernandópolis", "Indaiatuba", "Junco",
        "Linhares", "Lyon", "Mandaguaçu", "Matão 1", "Matão 2", "Monte Aprazível", "Nova Iguaçu",
        "Nova Londrina", "Paranavaí", "Parelhas", "Poconé 1", "Primavera", "Ribeirão Cascalheiras",
        # "Rodrigues" foi APOSENTADA (contador travado em 12.298,3 kWh desde nov/2025) e
        # substituída por Rodrigues 1 e 2 — ver _ignorar() no fonte_api. A lista ficou com o
        # nome morto, então as duas novas ficavam com carteira None e o filtro do seletor as
        # escondia de TODAS as abas: apareciam na API e em nenhum botão. (01/09/2026)
        "Rodrigues 1", "Rodrigues 2",
        "Rondonópolis", "Sapopema", "Saturnino 1", "Senador", "Sitio Bonfim",
        "Sitio dos Nogueiras", "Sorocaba", "Tanabi",
        # Coleta iniciada em 07/2026 (dado no BD_Thopen a partir de 31/07); estavam sem carteira.
        "Cipó Guaçu", "Córrego do Sapucaia", "Guatambu", "Jucurutu",
        # Entraram em operação em 08/2026 (meta e geração começam em agosto).
        "Assis", "Caicó", "Diamantino", "Itajá",
        # Usinas novas, com histórico trazido da API PV em 11/09/2026: Álvares Machado e
        # Santo Anastácio desde junho, Taguaí desde março. "Santo Anastacio" vai SEM acento de
        # propósito: a chave daqui é o valor da coluna `Usina` DENTRO da aba (ver
        # `_usina_da_aba`), e lá está sem acento. Escrever com acento aqui deixaria as três
        # fora de toda carteira e o seletor as esconderia — mesmo caso do "Rodrigues" acima.
        "Alvares Machado", "Santo Anastacio", "Taguaí",
        # Cambé ficou de fora do lote de 11/09 e só entrou em 16/09 (Levi: "só Cambé mesmo,
        # carteira Thopen"). O dado já estava completo antes disso — 30 dias na aba e metas de
        # set a dez no `Historico` —, faltava só o nome aqui: sem constar na carteira, a usina
        # não aparece no seletor por mais cheia que a aba esteja.
        "Cambé",
    ],
    "Copel": [
        "Pharma II", "Pharma III", "Pharma IV", "Santo Antonio do Platina",
        "Santo Antonio da Platina", "Sarandi", "Segredo",
    ],
    "Matrix": [
        "Belo Jardim", "Caroá", "Inhapi", "Ouro Branco I", "Ouro Branco II", "Ouro Branco III",
        "Ouro Branco IV", "Ouro Branco V", "Santana do Ipanema", "São Bento do Una", "Vertentes",
    ],
    "Polaris": [
        "Aparecida do Taboado 1", "Aparecida do Taboado 2", "Aparecida 3",
        "Araçoiaba da Serra 1", "Araçoiaba da Serra 2", "Betânia 1", "Boa Esperança do Sul 1",
        "Boa Esperança do Sul 2", "Boa Viagem 2 1", "Boa Viagem I 1", "Caxambu", "Ceará Mirim I 1",
        "Ceará Mirim I 2", "Delmiro Gouvea 1", "Delmiro Gouvea 2", "Delmiro Gouvea 3",
        "Delmiro Gouvea 4", "Goytacazes 1", "Goytacazes 4 2", "Guaratinguetá V", "Ibaté 1",
        "Ibaté 2", "Ipixuna 1", "Ipixuna 2", "Marajoara 1", "Marajoara 2 1", "Piancó 1",
        "Piracicaba 1", "Porteiras 1", "Porto Real 2 1", "Porto Real 3", "Salto Pirapora 3",
        "Santa Bárbara I", "Santarém 1", "Santarém 2", "Santo Inácio XII", "São Bento V",
        "Urupês 1", "Vargem Grande 1",
    ],
}
CARTEIRA_ORDEM = ["Thopen", "Copel", "Matrix", "Polaris"]
_CARTEIRA_DE = {u: c for c in CARTEIRA_ORDEM for u in CARTEIRAS[c]}  # usina -> carteira

# Usinas que aparecem no dashboard (seletor/drill) mas NÃO entram no cálculo da Visão Geral (aba Geral).
EXCLUIR_GERAL = {"Piancó 1"}

# Usinas que existem na fonte mas NÃO são carteira nossa — ficam fora do relatório inteiro.
# Araci: vem no Budget da Polaris, mas o cliente confirmou que não é dele (31/07/2026).
FORA_DO_RELATORIO = {"Araci 1"}


def _usinas_disponiveis():
    """As usinas que o painel mostra (o seletor). A contestação só aceita uma delas: o 5080 é público."""
    _wb()
    return sorted({_NOME_CANON.get(u, u) for u in
                   (set(_state["daily"].keys()) | set(_polaris_records().keys()) | set(_sheet_records().keys()))}
                  - FORA_DO_RELATORIO)


@app.route("/api/t/usinas")
def usinas():
    us = [u for u in _usinas_disponiveis() if _pode(u)]     # login (14/10/2026): só as das carteiras da conta
    default = "Altair" if "Altair" in us else (us[0] if us else None)
    carteira_de = {u: _CARTEIRA_DE.get(u) for u in us}  # carteira de cada usina disponível
    today = dt.date.today()
    mes_max = today.month if today.year == ANO else 12  # p/ o filtro de mês GLOBAL do frontend
    return jsonify({"usinas": us, "default": default,
                    "carteiras": _carteiras_vistas(), "carteira_de": carteira_de,
                    "ano": ANO, "mes_max": mes_max})


@app.route("/api/t/overview")
def overview():
    usina = request.args.get("usina", "Altair")
    recs = _daily_records(usina)
    reg = _registro().get(usina, {})
    pot_mwp = reg.get("pot_mwp")
    meta = _meta2026(usina)
    today = dt.date.today()

    prod = {}
    for r in recs:
        if r["data"].year == ANO and r["ger"] is not None:
            prod[r["data"].month] = prod.get(r["data"].month, 0.0) + r["ger"]
    p2023 = _prod_mensal_ano(usina, 2023)  # anos anteriores, mês a mês (planilha p/ Matrix/Copel)
    p2024 = _prod_mensal_ano(usina, 2024)
    p2025 = _prod_mensal_ano(usina, 2025)

    meses = []
    for m in range(1, 13):
        mt = meta.get(m, {})
        meta_kwh = mt.get("meta")
        pz = prod.get(m)
        pz23 = p2023.get(m)
        pz24 = p2024.get(m)
        pz25 = p2025.get(m)
        dias = today.day if (ANO == today.year and m == today.month) else monthrange(ANO, m)[1]
        fc_real = (pz / (pot_mwp * 1000 * 24 * dias)) if (pz is not None and pot_mwp) else None
        dif = ((pz - meta_kwh) / meta_kwh) if (pz is not None and meta_kwh) else None
        meses.append({
            "mes": m,
            "meta": (meta_kwh / 1000) if meta_kwh else None,
            "produzida": (pz / 1000) if pz is not None else None,
            "produzida_2023": (pz23 / 1000) if pz23 else None,
            "produzida_2024": (pz24 / 1000) if pz24 else None,
            "produzida_2025": (pz25 / 1000) if pz25 else None,
            "dif": dif,
            "fc_meta": mt.get("fc"),
            "fc_real": fc_real,
        })

    pa = _prod_anual_por_usina(usina)
    prod2026 = sum(prod.values())
    # Meta 2026 = meta acumulada (YTD) dos meses em que a usina gerou — espelha a medida DAX
    # do Power BI (SUM(meta) WHERE Date <= mês) p/ usinas contínuas (casa exato c/ Altair).
    # Acumula SÓ nos meses com produção de propósito: não cobra meta de meses em que a usina
    # ainda não existia (usinas que entraram no meio do ano). Ver nota p/ alternar p/ calendário.
    meta2026_ytd = sum((meta.get(m, {}).get("meta") or 0) for m in prod)
    anual = [
        {"label": "Produzida 2023", "valor": pa.get("2023")},
        {"label": "Produzida 2024", "valor": pa.get("2024")},
        {"label": "Produzida 2025", "valor": pa.get("2025")},
        {"label": "Meta 2026", "valor": meta2026_ytd or None},
        {"label": "Produzida 2026", "valor": prod2026 or None},
    ]

    per = sorted({(r["data"].year, r["data"].month) for r in recs if r["ger"] is not None})
    periodos = [{"ano": a, "mes": mm} for a, mm in per]

    return jsonify({
        "usina": usina, "nome": reg.get("nome") or usina, "cidade": reg.get("cidade"),
        "estado": reg.get("estado"), "cliente": reg.get("cliente"),
        "potencia_mwp": pot_mwp, "ano": ANO, "meses": meses,
        "anual": anual, "periodos": periodos, "planilha_em": _planilha_em(),
        "comentario_extra": _load_comentarios().get(usina, ""),
    })


@app.route("/api/t/comentario_extra", methods=["POST"])
def comentario_extra():
    """Salva/atualiza o texto livre 'Comentários adicionais' de uma usina (aba Diário)."""
    data = request.get_json(force=True, silent=True) or {}
    usina = (data.get("usina") or "").strip()
    texto = (data.get("texto") or "").strip()[:5000]   # teto p/ evitar abuso (campo é aberto)
    if not usina:
        return jsonify({"ok": False, "erro": "usina não informada"}), 400
    com = _load_comentarios()
    if texto:
        com[usina] = texto
    else:
        com.pop(usina, None)   # texto vazio = apaga a entrada
    _save_comentarios(com)
    return jsonify({"ok": True})


@app.route("/api/t/diario")
def diario():
    usina = request.args.get("usina", "Altair")
    ano = int(request.args.get("ano", ANO))
    mes = int(request.args.get("mes", 1))
    recs = [r for r in _daily_records(usina)
            if r["data"].year == ano and r["data"].month == mes]
    recs.sort(key=lambda r: r["data"])

    meta = _meta2026(usina).get(mes, {}) if ano == ANO else {}
    dias_mes = monthrange(ano, mes)[1]
    meta_kwh = meta.get("meta")
    meta_dia = (meta_kwh / dias_mes) if meta_kwh else None

    # de 10/2026 em diante o comentário e a disponibilidade do cliente são só os das OS do Fracttal (_so_os_fracttal):
    # o comentário da equipe e a disponibilidade do BD_Thopen nem saem daqui — a tela monta tudo pelo /api/t/operacao
    so_os = _so_os_fracttal(ano, mes)
    pontos = [{"dia": r["data"].day, "ger": r["ger"], "ipoa": r["ipoa"], "com": None if so_os else r["com"]}
              for r in recs]
    # a linha preta de 10/2026 em diante é a geração possível do dia (Levi, 20/10/2026; geracao_possivel.py): meta do
    # mês × IPOA medido do dia ÷ meta de IPOA do mês, com o IPOA da ETM (≥ 0,3) ou o GHI (≥ 1,0). Mês com medição em
    # menos da metade dos dias com geração: sem a linha, e a tela diz por quê. Antes de outubro, a irradiação de sempre
    info = None
    if so_os:
        ghi = _ghi_por_dia(usina)
        per = geracao_possivel.periodo(recs, ghi, meta_kwh, meta.get("metairr"), dias_mes, None)
        for pt, r in zip(pontos, recs):
            med, fonte = geracao_possivel.ipoa_do_dia(r["ipoa"], ghi.get(r["data"]))
            pt.update(ipoa_med=med, fonte_ipoa=fonte, possivel=None if per["sem_etm"] else
                      geracao_possivel.possivel_do_dia(meta_kwh, meta.get("metairr"), med))
        info = {"sem_etm": per["sem_etm"], "motivo": per["motivo"], "dias": per["dias"],
                "dias_medidos": per["dias_medidos"]}
    disp_vals = [] if so_os else [r["disp"] for r in recs if r["disp"] is not None]
    kpis = {
        "acum_prod": sum((r["ger"] or 0) for r in recs),
        "acum_meta": meta_kwh,
        "irr_real": round(sum((r["ipoa"] or 0) for r in recs), 2),
        "irr_meta": meta.get("metairr"),
        "disp": (sum(disp_vals) / len(disp_vals)) if disp_vals else None,
    }
    # Agrupa dias CONSECUTIVOS com o MESMO comentário num intervalo
    # (ex.: "01/05/2026 a 06/05/2026"). Dia sem comentário ou texto diferente quebra a sequência.
    grupos = []
    prev_d = None
    for r in ([] if so_os else recs):
        c, d = r["com"], r["data"]
        if c:
            if (grupos and grupos[-1]["com"] == c and prev_d is not None
                    and (d - prev_d).days == 1 and grupos[-1]["fim"] == prev_d):
                grupos[-1]["fim"] = d
            else:
                grupos.append({"ini": d, "fim": d, "com": c})
        prev_d = d

    def _drange(g):
        a = g["ini"].strftime("%d/%m/%Y")
        b = g["fim"].strftime("%d/%m/%Y")
        return a if a == b else a + " a " + b

    coment = [{"data": _drange(g), "com": g["com"]} for g in grupos]

    out = {"usina": usina, "ano": ano, "mes": mes, "pontos": pontos,
           "meta_dia": meta_dia, "kpis": kpis, "comentarios": coment}
    if info is not None:
        out["possivel_info"] = info
    return jsonify(out)


def _so_os_fracttal(ano, mes):
    """De 10/2026 em diante o comentário e a disponibilidade do cliente são SÓ os das OS do Fracttal (Levi, 14/10/2026:
    "A partir de outubro quero os comentários 100% OS Fracttal. Comentários e disponibilidade! Antes deixe como
    estava!"). Por quê: o comentário da equipe no BD_Thopen e a disponibilidade do Gerencial são duas contas que não se
    conversam — em 1 a 13/10, em 37 dias de 14 usinas a equipe registrava parada e o Gerencial dizia 100%, e em 90 dias
    o mesmo desligamento saía duas vezes (Ipixuna II 01/10). Antes de outubro, o BD_Thopen como sempre."""
    return (ano, mes) >= operacao_mes.DESDE


def _disp_gerencial(usina, ano, mes):
    """A disponibilidade do mês pelo Gerencial (fração 0–1), a mesma do card do Diário: a média dos dias da
    disponibilidade_dia. None sem o dado (carregando, card desligado, usina fora do Gerencial) — nunca o 0 de
    "não preenchido" do BD_Thopen (a Visão Geral de outubro mostrava a Altair com 0,0%)."""
    dsp = _disp_dias(usina, ano, mes)
    return (sum(dsp.values()) / len(dsp)) / 100.0 if dsp else None


def _disp_dias(usina, ano, mes):
    """{data: disponibilidade %} das OS do Fracttal (a disponibilidade_dia da plataforma), ou None sem o dado
    (carregando, desligado, usina fora do Gerencial): a Visão Geral fica sem o expurgo, nunca com um 0."""
    if os.environ.get("THOPEN_OPERACAO", "1").strip() == "0":
        return None
    dados = _op_dados()
    return (operacao_mes.disp_por_dia(dados, usina, ano, mes) or None) if dados else None


def _resumo_usina(usina, ano, mes, ate=None):
    """Linha do resumo (Visão Geral) de uma usina num mês — espelha as medidas DAX:
    Produzida/Meta/Irradiação/Disp do mês + FC = Produzida / (Pot_kWp × 24 × dias). De 10/2026 em diante a Disp é a do
    Gerencial (OS do Fracttal, `_so_os_fracttal`)."""
    recs = [r for r in _daily_records(usina) if r["data"].year == ano and r["data"].month == mes]
    gers = [r["ger"] for r in recs if r["ger"] is not None]
    ipoas = [r["ipoa"] for r in recs if r["ipoa"] is not None]
    disps = [r["disp"] for r in recs if r["disp"] is not None]
    produzida = sum(gers) if gers else None
    irr_med = sum(ipoas) if ipoas else None
    disp = _disp_gerencial(usina, ano, mes) if _so_os_fracttal(ano, mes) else (
        (sum(disps) / len(disps)) if disps else None)
    mt = _meta2026(usina).get(mes, {}) if ano == ANO else {}
    meta, irr_esp = mt.get("meta"), mt.get("metairr")
    pot_kwp = (_registro().get(usina, {}).get("pot_mwp") or 0) * 1000 or None
    today = dt.date.today()
    dias = today.day if (ano == today.year and mes == today.month) else monthrange(ano, mes)[1]
    fc = (produzida / (pot_kwp * 24 * dias)) if (produzida is not None and pot_kwp) else None
    dif_prod = ((produzida - meta) / meta) if (produzida is not None and meta) else None
    dif_irr = ((irr_med - irr_esp) / irr_esp) if (irr_med and irr_esp) else None
    linha = {"usina": usina, "pot_kwp": pot_kwp, "meta": meta, "produzida": produzida,
             "dif_prod": dif_prod, "irr_esp": irr_esp, "irr_med": irr_med, "dif_irr": dif_irr,
             "disp": disp, "fc": fc}
    if _so_os_fracttal(ano, mes):
        linha.update(_resumo_possivel(usina, ano, mes, recs, produzida, meta, irr_esp, ate))
    return linha


def _resumo_possivel(usina, ano, mes, recs, produzida, meta_mes, metairr_mes, ate=None):
    """De 10/2026 em diante a Visão Geral pela regra da geração possível (Levi, 20/10/2026; geracao_possivel.py): a meta
    e a irradiação esperada só dos dias com geração (no meio do mês a meta do mês inteiro punha toda usina "abaixo"), a
    medida ajustada pela cobertura, a possível pelo IPOA e com o expurgo das OS. Meta, Irradiação Esperada e Medida
    mudam de significado em vez de ganhar colunas: a tabela vai para a folha A4."""
    p = geracao_possivel.periodo(recs, _ghi_por_dia(usina), meta_mes, metairr_mes, monthrange(ano, mes)[1],
                                 _disp_dias(usina, ano, mes), ate=ate)
    return {"meta": p["meta"], "irr_esp": p["meta_ipoa"], "irr_med": p["ipoa_ajustado"], "dif_irr": p["dif_ipoa"],
            "dif_prod": ((produzida - p["meta"]) / p["meta"]) if (produzida is not None and p["meta"]) else None,
            "real": p["real"], "meta_ipoa": p["meta_ipoa"], "ipoa_ajustado": p["ipoa_ajustado"],
            "possivel": p["possivel"], "dif_possivel": p["dif_possivel"], "possivel_exp": p["possivel_exp"],
            "dif_possivel_exp": p["dif_possivel_exp"], "sem_etm": p["sem_etm"], "motivo": p["motivo"],
            "cobertura": p["cobertura"], "dias": p["dias"], "dias_medidos": p["dias_medidos"],
            "furos": [d.strftime("%d/%m") for d in p["furos"]]}


def _ultimo_coletado(usinas, ano, mes):
    """O último dia do mês que a carteira já coletou: o mais recente em que pelo menos METADE das usinas com dado no mês
    tem geração (None sem nenhum). Não o de qualquer usina: em 20/10/2026 uma usina da Thopen já tinha 19/10 e as outras
    58 paravam em 18/10 — com o máximo, as 58 saíam com "1 dia sem dado"."""
    por_usina = [{r["data"] for r in _daily_records(u)
                  if r["data"].year == ano and r["data"].month == mes and (r["ger"] or 0) > 0} for u in usinas]
    por_usina = [s for s in por_usina if s]
    for d in sorted(set().union(*por_usina), reverse=True) if por_usina else []:
        if 2 * sum(d in s for s in por_usina) >= len(por_usina):
            return d
    return None


@app.route("/api/t/geral")
def geral():
    """Resumo (Visão Geral) de uma CARTEIRA num mês de referência: 1 linha por usina em operação,
    + a data de corte (p/ a capa). Espelha o relatório 'Performance UFVs - Geração'."""
    carteira = request.args.get("carteira", "Thopen")
    ano = int(request.args.get("ano", ANO))
    mes = int(request.args.get("mes", dt.date.today().month))
    _wb()
    disponiveis = {_NOME_CANON.get(u, u) for u in
                   (set(_state["daily"].keys()) | set(_polaris_records().keys())
                    | set(_sheet_records().keys()))} - FORA_DO_RELATORIO
    nomes = sorted({u for u in CARTEIRAS.get(carteira, [])
                    if u in disponiveis and u not in EXCLUIR_GERAL})
    # o último dia coletado da carteira: até ele, o dia sem dado de uma usina é furo (a coleta parada aparece)
    ate = _ultimo_coletado(nomes, ano, mes) if _so_os_fracttal(ano, mes) else None
    linhas = [r for r in (_resumo_usina(u, ano, mes, ate) for u in nomes) if r["produzida"] is not None]
    # Usinas da carteira que aparecem ABAIXO do Total (não entram no cálculo). Ex.: Piancó.
    fora_nomes = sorted({u for u in CARTEIRAS.get(carteira, [])
                         if u in disponiveis and u in EXCLUIR_GERAL})
    fora = [r for r in (_resumo_usina(u, ano, mes, ate) for u in fora_nomes) if r["produzida"] is not None]
    today = dt.date.today()
    corte = (today if (ano == today.year and mes == today.month)
             else dt.date(ano, mes, monthrange(ano, mes)[1]))
    nome_carteira = next((c for c in CARTEIRA_ORDEM if c == carteira), carteira)
    out = {"carteira": nome_carteira, "ano": ano, "mes": mes,
           "corte": corte.strftime("%d/%m/%Y"), "linhas": linhas, "fora": fora}
    if _so_os_fracttal(ano, mes):
        # a linha Total pelo portfólio (regra 6 do Levi, 20/10/2026): a possível só das usinas com ETM contra o real
        # delas, a meta só das usinas com meta, o IPOA ponderado pela potência; a Disponibilidade, a média simples de
        # sempre (até 20/10 o Total era somado no navegador)
        dv = [r["disp"] for r in linhas if r.get("disp") is not None]
        out.update(regra="possivel", total=dict(geracao_possivel.portfolio(linhas),
                                                disp=(sum(dv) / len(dv)) if dv else None))
    return jsonify(out)


def _registros(carteira, ano, mes):
    """A aba Registros (Levi, 23/10/2026: drill-down carteira → usinas → dias; "Geração e irradiação continua sendo da
    BD_Thopen, disponibilidade vai ser da forma nova!"): cada usina da carteira com o mês dia a dia. A geração e o IPOA
    do BD_Thopen; a disponibilidade de 10/2026 em diante a das OS do Fracttal (a mesma do card do Diário e da Visão
    Geral, `_disp_dias`, em fração como a do BD), antes a do BD_Thopen. Dia sem nenhum dos três fica fora; usina sem dia
    no mês também. As usinas fora do cálculo da Visão Geral (Piancó) entram: aqui é o registro, não o resumo."""
    _wb()
    disponiveis = {_NOME_CANON.get(u, u) for u in
                   (set(_state["daily"].keys()) | set(_polaris_records().keys())
                    | set(_sheet_records().keys()))} - FORA_DO_RELATORIO
    so_os, hoje = _so_os_fracttal(ano, mes), dt.date.today()
    usinas = []
    for u in sorted(x for x in set(CARTEIRAS.get(carteira, [])) if x in disponiveis):
        recs = {r["data"]: r for r in _daily_records(u) if (r["data"].year, r["data"].month) == (ano, mes)}
        dsp = (_disp_dias(u, ano, mes) or {}) if so_os else {}
        # o BD nasce com o mês pré-criado: o dia ainda não coletado vem com geração 0 e nada mais (em 23/10/2026 a
        # Altair tinha 22 e 23/10 assim, com 22/10 já a 100% nas OS). Depois do último dia coletado, esse 0 é "sem
        # dado" (—), não geração zero; no meio do mês, o 0 é o que a usina gerou
        coletados = [d for d, r in recs.items() if (r.get("ger") or 0) > 0 or r.get("ipoa") is not None]
        ultimo = max(coletados) if coletados else None
        dias = []
        for d in sorted(set(recs) | {x for x in dsp if x <= hoje}):
            r = recs.get(d) or {}
            ger = None if (not r.get("ger") and r.get("ipoa") is None and (ultimo is None or d > ultimo)) else r.get("ger")
            disp = (dsp[d] / 100.0 if dsp.get(d) is not None else None) if so_os else r.get("disp")
            if ger is None and r.get("ipoa") is None and disp is None:
                continue
            dias.append({"data": d.isoformat(), "ger": ger, "ipoa": r.get("ipoa"), "disp": disp})
        if not dias:
            continue
        soma = lambda k: (sum(x[k] for x in dias if x[k] is not None)                 # noqa: E731
                          if any(x[k] is not None for x in dias) else None)
        dv = [x["disp"] for x in dias if x["disp"] is not None]
        usinas.append({"usina": u, "ger": soma("ger"), "ipoa": soma("ipoa"),
                       "disp": (sum(dv) / len(dv)) if dv else None, "dias": dias})
    carregando = so_os and (os.environ.get("THOPEN_OPERACAO", "1").strip() == "0" or not fonte_operacao.dados())
    return {"carteira": carteira, "ano": ano, "mes": mes, "fonte_disp": "os" if so_os else "bd",
            "disp_carregando": bool(carregando), "usinas": usinas}


def _carteira_ano_mes():
    """(carteira, ano, mes, None) ou (..., resposta 400)."""
    carteira = request.args.get("carteira", "")
    try:
        ano, mes = int(request.args.get("ano", "")), int(request.args.get("mes", ""))
    except ValueError:
        ano = mes = 0
    if carteira not in CARTEIRAS or not 1 <= mes <= 12 or not 2000 <= ano <= 2100:
        return None, None, None, (jsonify({"ok": False, "erro": "carteira, ano ou mês inválido"}), 400)
    return carteira, ano, mes, None


@app.route("/api/t/registros")
def registros():
    carteira, ano, mes, erro = _carteira_ano_mes()
    return erro or jsonify(_registros(carteira, ano, mes))


@app.route("/api/t/registros.xlsx")
def registros_xlsx():
    """O Exportar da aba Registros: só Usina, Data, Geração, Irradiação e Disponibilidade, a carteira no mês (Levi,
    23/10/2026). A disponibilidade vai como fração com formato de %: soma e média funcionam no Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    carteira, ano, mes, erro = _carteira_ano_mes()
    if erro:
        return erro
    d = _registros(carteira, ano, mes)
    wb = Workbook()
    ws = wb.active
    ws.title = "Registros"
    ws.append(["Usina", "Data", "Geração (kWh)", "Irradiação (kWh/m²)", "Disponibilidade (%)"])
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F2E6E")
    for u in d["usinas"]:
        for x in u["dias"]:
            ws.append([u["usina"], dt.date.fromisoformat(x["data"]), x["ger"], x["ipoa"], x["disp"]])
    for linha in ws.iter_rows(min_row=2):
        linha[1].number_format, linha[2].number_format = "dd/mm/yyyy", "#,##0.00"
        linha[3].number_format, linha[4].number_format = "0.00", "0.00%"
    for col, larg in zip("ABCDE", (28, 12, 16, 20, 20)):
        ws.column_dimensions[col].width = larg
    ws.freeze_panes, ws.auto_filter.ref = "A2", ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    nome = "Registros_%s_%d-%02d.xlsx" % (re.sub(r"[^A-Za-z0-9]+", "_", carteira), ano, mes)
    return send_file(buf, as_attachment=True, download_name=nome,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/t/zeladoria")
def api_zeladoria():
    """A aba Zeladoria (Levi, 26/10/2026: "agora faz a mesma tela no dashboard do cliente"): a visão que o Nexus publica
    (usina × semana; zeladoria_cliente) para as usinas da carteira que a conta vê, na semana escolhida (?semana=2026-W43;
    sem ela, a mais nova). O nome da usina no 5080 sai do de-para do sistema do 5080 pelo usina_id do Nexus."""
    carteira = request.args.get("carteira", "")
    if carteira not in CARTEIRAS:
        return jsonify({"ok": False, "erro": "carteira inválida"}), 400
    vazio = {"disponivel": False, "carteira": carteira}
    if not fonte_zeladoria.ligada():
        return jsonify(dict(vazio, motivo="desligado"))
    d, op = fonte_zeladoria.dados(), fonte_operacao.dados()
    if d is None or op is None:
        return jsonify(dict(vazio, motivo="carregando"))
    usinas = [u for u in _usinas_disponiveis() if _CARTEIRA_DE.get(u) == carteira and _pode(u)]
    atu = zeladoria_cliente.ultima_atualizacao(d) or {}
    r = zeladoria_cliente.montar(d.get("linhas"), zeladoria_cliente.nomes_por_id(op.get("de_para")), usinas,
                                 semana=(request.args.get("semana") or "").strip() or None,
                                 semana_corrente=str(atu.get("semana_corrente") or "").strip() or None)
    r.update(disponivel=True, motivo=None, carteira=carteira,
             atualizado_em=str(atu.get("atualizado_em") or "")[:16] or None)
    return jsonify(r)


@app.route("/api/t/fonte")
def fonte():
    """Saúde da fonte de dados — de onde veio o que está na tela e há quanto tempo.

    Existe para o servidor de produção, que não tem arquivo nenhum para inspecionar: sem isto,
    descobrir se o dashboard está servindo o banco ou um cache velho exigiria ler log. Serve
    também de healthcheck: `origem == "api"` e `idade < ttl` é o estado saudável."""
    _wb()
    e = fonte_api.estado() if fonte_api is not None else {}
    return jsonify({
        "fonte": _state.get("path"),          # sempre "api": não há outra fonte
        "origem": e.get("origem"),            # "api" | "cache" (disco) | None
        "carregado_em": (dt.datetime.fromtimestamp(e["carregado_em"]).strftime("%d/%m/%Y %H:%M:%S")
                         if e.get("carregado_em") else None),
        "idade_s": round(e["idade"]) if e.get("idade") is not None else None,
        "ttl_s": e.get("ttl"), "abas": e.get("abas"),
        "erro_ultima_tentativa": e.get("erro"),
        "cache_em_disco": e.get("cache"), "base": e.get("base"),
        "usinas": len(_state.get("daily") or {}),
    })


def _trips_da_tela(dados, usina, ano, mes):
    """({nº da OS: trip}, buscando?) das OS da usina no mês. A rota nunca espera o Fracttal: o que falta vai para a linha
    em segundo plano (trip_os) e a tela relê enquanto `buscando`."""
    if not dados or not trip_os.ligado() or (ano, mes) < operacao_mes.DESDE:
        return {}, False
    achou, falta = trip_os.guardados(operacao_mes.os_desligamento_do_mes(dados, usina, ano, mes))
    return achou, trip_os.em_segundo_plano(falta) if falta else False


@app.route("/api/t/reload")
def reload_bd():
    """Força reler a fonte (limpa o cache) — usado pelo botão Atualizar. Com ?usina=&ano=&mes= (a usina na tela), busca
    de novo no Fracttal o trip das OS dela no mês (Levi, 23/10/2026: "GOSTARIA QUE O BOTÃO ATUALIZAR PUXASSE
    DIRETAMENTE"); o que não couber em trip_os.LIMITE_ATUALIZAR segue em segundo plano."""
    if fonte_api is not None:
        fonte_api.invalidar()      # derruba o TTL: o botão tem de buscar o banco AGORA
    with _lock:
        _state["wb"] = None
        _state["mtime"] = None
        _state["df"] = {}
        _state["polaris"] = None   # força reler os registros da Polaris também
        _state["sheets"] = None    # e as planilhas externas (Matrix, Copel)
    _wb()  # recarrega agora (chamado FORA do lock — _wb() readquire o lock)
    usina = (request.args.get("usina") or "").strip()
    try:
        ano, mes = int(request.args.get("ano", 0)), int(request.args.get("mes", 0))
    except ValueError:
        ano = mes = 0
    if usina and 1 <= mes <= 12 and trip_os.ligado() and (ano, mes) >= operacao_mes.DESDE             and os.environ.get("THOPEN_OPERACAO", "1").strip() != "0":
        oss = operacao_mes.os_desligamento_do_mes(_op_dados(), usina, ano, mes)
        trip_os.buscar(oss, forcar=True, limite_s=trip_os.LIMITE_ATUALIZAR)
        trip_os.em_segundo_plano(oss)
    return jsonify({"ok": True, "planilha_em": _planilha_em(),
                    "atualizado_em": dt.datetime.now().strftime("%H:%M:%S")})


# A publicação sob demanda saiu em 28/08/2026 junto com o Excel: ela existia para o PC da
# Grid copiar as planilhas e republicar o snapshot da nuvem. Lendo do banco, o dado do site
# é o dado do banco — não há o que publicar, e o botão Atualizar apenas relê.


@app.route("/api/t/operacao")
def api_operacao():
    """Operação no Mês do card do Diário (Levi, 08/10/2026): strings com saída, trackers parados com a usina
    comunicando e a zeladoria da última ronda. Só agregados (operacao_mes.CHAVES — o 5080 é público, sem senha).

    A requisição nunca espera a rede: o `fonte_operacao` serve o que tem e recarrega em segundo plano, fora do
    `_lock` do `_wb()` e do /api/t/reload (a recarga do BD_Thopen já segura o 1º acesso do cliente por ~130 s).
    `THOPEN_OPERACAO=0` no ambiente do processo desliga o card sem mexer no código (a tela o esconde)."""
    usina, ano, mes, erro = _usina_ano_mes()
    if erro:
        return erro
    hoje = dt.date.today()
    if os.environ.get("THOPEN_OPERACAO", "1").strip() == "0":
        r = operacao_mes.resposta(None, usina, ano, mes, hoje)
        r["motivo"] = "desligado"
        return jsonify(r)
    dados = _op_dados()
    trips, buscando = _trips_da_tela(dados, usina, ano, mes)
    r = operacao_mes.resposta(dados, usina, ano, mes, hoje, trips)
    r["trip_pendente"] = bool(buscando and r["disponivel"])
    # rodada 4: que canais do Teams recebem a contestação — item sem canal configurado não aparece na tela
    r["contestar"] = _canais_da_contestacao() if r["disponivel"] else None
    return jsonify(r)


def _usina_ano_mes():
    """(usina, ano, mes, None) ou (..., resposta 400): os limites do card valem para a janela das rondas."""
    usina = (request.args.get("usina") or "").strip()
    try:
        ano, mes = int(request.args.get("ano", "")), int(request.args.get("mes", ""))
    except ValueError:
        return usina, 0, 0, (jsonify({"erro": "ano e mes precisam ser números"}), 400)
    if not usina or not 1 <= mes <= 12 or not 2020 <= ano <= 2100:
        return usina, ano, mes, (jsonify({"erro": "usina, ano (2020 a 2100) e mes (1 a 12) são obrigatórios"}), 400)
    return usina, ano, mes, None


# ── Rondas do mês e dúvida do cliente (rodada 3, Levi, 09/10/2026) ───────────────────────────────────────────────
# O ícone do card abre as rondas do mês com as fotos ("Checklist + fotos, sem nome") e um campo de dúvida que avisa a
# Grid Co. no Teams. O 5080 é público: foto e dúvida só de OS de ronda de usina do de-para do 5080, de 10/2026 em diante
# (rondas_cliente.da_os). THOPEN_RONDAS=0 desliga as quatro rotas sem mexer no código.
def _rondas_desligadas():
    return os.environ.get("THOPEN_RONDAS", "1").strip() == "0"


@app.route("/api/t/rondas")
def api_rondas():
    """As rondas do mês da usina, para a janela. Sem pedido ao Fracttal: as fotos vêm só quando a ronda é aberta."""
    usina, ano, mes, erro = _usina_ano_mes()
    if erro:
        return erro
    vazio = {"disponivel": False, "rondas": []}
    if _rondas_desligadas():
        return jsonify(dict(vazio, motivo="desligado"))
    if (ano, mes) < operacao_mes.DESDE:
        return jsonify(dict(vazio, disponivel=True, motivo="antes de 10/2026"))
    dados = fonte_operacao.dados()
    if dados is None:
        return jsonify(dict(vazio, motivo="carregando"))
    return jsonify({"disponivel": True, "motivo": None, "rondas": rondas_cliente.do_mes(dados, usina, ano, mes)})


def _ronda_ou_404(os_):
    r = None if _rondas_desligadas() else rondas_cliente.da_os(fonte_operacao.dados(), os_)
    if r is None:
        abort(404)
    return r


@app.route("/api/t/ronda/<int:os_>")
def api_ronda(os_):
    """Uma ronda montada para a janela, com as fotos casadas aos itens (1 pedido ao Fracttal por OS, guardado 20 min).
    Fracttal fora ou sem credencial: a ronda aparece do mesmo jeito, com o aviso no lugar das fotos."""
    r = _ronda_ou_404(os_)
    descs, aviso = [], None
    try:
        descs = [a["desc"] for a in fotos_ronda.anexos(os_)]
    except fotos_ronda.SemCredencial:
        aviso = "As fotos desta ronda não estão disponíveis neste painel."
    except fotos_ronda.Ocupado:
        aviso = "O sistema de fotos está ocupado agora. Tente de novo em 1 minuto."
    except Exception as e:                    # noqa: BLE001 — a ronda aparece mesmo sem as fotos
        print("[rondas] anexos da OS %s: %s" % (os_, type(e).__name__), flush=True)
        aviso = "Não consegui carregar as fotos agora. Tente de novo em 1 minuto."
    out = rondas_cliente.detalhe(r, descs)
    out["fotos_erro"] = aviso
    return jsonify(out)


@app.route("/api/t/ronda/<int:os_>/foto/<int:i>")
def api_ronda_foto(os_, i):
    """A foto (ou a miniatura, ?mini=1): o 5080 baixa do Fracttal e entrega — o link assinado não sai daqui."""
    _ronda_ou_404(os_)
    try:
        corpo, mime = (fotos_ronda.miniatura if request.args.get("mini") else fotos_ronda.foto)(os_, i)
    except fotos_ronda.SemFoto:
        abort(404)
    except Exception as e:                    # noqa: BLE001
        print("[rondas] foto %s/%s: %s" % (os_, i, type(e).__name__), flush=True)
        return Response("foto indisponível agora", status=502, mimetype="text/plain")
    return Response(corpo, mimetype=mime, headers={"Cache-Control": "private, max-age=3600"})


_LIMITE = contestacao.Limite()


def _canais_da_contestacao():
    """{setor: a tela pode oferecer}. Desde 19/10/2026 (Levi: "vai direto para contestações do Nexus e a gente resolve
    lá, esquece teams") o banco, que o Nexus mostra em Contratos e clientes → Contestações, basta: Disponibilidade e
    Desligamento (COS) não marcavam por falta do fluxo do Teams do COS. Sem o banco, só o setor com fluxo do Teams."""
    banco = contestacao_banco.configurado()
    return {k: banco or v for k, v in contestacao.canais().items()}


@app.route("/api/t/contestar", methods=["POST"])
def api_contestar():
    """A contestação do cliente sobre um dia do Diário (rodada 4, Levi 09/10/2026). Desde 19/10/2026 o destino é o
    banco (livro thopen_contestacoes), que o Nexus mostra por setor (geração, string e tracker → Performance;
    disponibilidade e desligamento → COS; ronda → Zeladoria); o Teams, onde o setor tem fluxo, é um aviso a mais. Só diz
    "enviada" quando cada setor ficou no banco ou no Teams. Só de 10/2026 em diante e só para usina do painel."""
    b = request.get_json(silent=True) or {}
    usina = str(b.get("usina") or "").strip()
    try:
        ano, mes, ini, fim = (int(b.get(k)) for k in ("ano", "mes", "dia_ini", "dia_fim"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro": "Dia inválido."}), 400
    ultimo = monthrange(ano, mes)[1] if 1 <= mes <= 12 and 2020 <= ano <= 2100 else 0
    if (ano, mes) < operacao_mes.DESDE or not 1 <= ini <= fim <= ultimo:
        return jsonify({"ok": False, "erro": "Dia inválido."}), 400
    if usina not in _usinas_disponiveis():
        return jsonify({"ok": False, "erro": "Usina não encontrada."}), 404
    u = _usuario() if _login_ligado() else None
    # login (15/10/2026, Levi: "com a pessoa conectada, na contestação a pessoa não precisa preencher o e-mail, só o
    # nome!"): o nome é o que a pessoa escreveu; o contato é o da conta — o e-mail dela ou, na conta pelo usuário de hoje,
    # o usuário (a Grid Co. sabe de que conta veio)
    conta_contato = (u["email"] or "usuário %s (conta do painel)" % (u.get("usuario") or "")) if u else None
    d, erro = contestacao.validar(b, contato_da_conta=conta_contato)
    if erro == "isca":
        return jsonify({"ok": True, "destinos": []})        # robô: não avisa ninguém, e ele não fica sabendo
    if erro:
        return jsonify({"ok": False, "erro": erro}), 400
    alvo = contestacao.destinos(d["itens"])
    urls = {k: contestacao.url(k) for k in alvo}
    banco = contestacao_banco.configurado()
    if not banco and not all(urls.values()):  # setor sem banco e sem Teams: nunca dizer "enviada" sem ter registrado
        return jsonify({"ok": False, "erro": "O envio de contestações não está disponível agora."}), 503
    if not _LIMITE.tenta(request.headers.get("CF-Connecting-IP") or request.remote_addr or "?"):
        return jsonify({"ok": False, "erro": "Muitas mensagens em pouco tempo. Tente de novo mais tarde."}), 429
    data_txt = ("%02d/%02d/%d" % (ini, mes, ano)) if ini == fim else ("%02d a %02d/%02d/%d" % (ini, fim, mes, ano))
    no_teams = set()
    for k in alvo:
        if not urls[k]:
            continue                          # setor sem fluxo do Teams (o COS, 19/10/2026): só o banco
        try:
            contestacao.enviar(contestacao.cartao(d, usina, data_txt, k), urls[k])
            no_teams.add(k)
        except Exception as e:                # noqa: BLE001 — sem dado pessoal no log
            print("[contestacao] o Teams (%s) não recebeu: %s" % (k, type(e).__name__), flush=True)
    # uma linha por setor no livro thopen_contestacoes, com o setor que o Teams recebeu (rodada 5, 13/10/2026). Na hora,
    # não mais em segundo plano: é o registro que o setor vê no Nexus. O usina_id sai do de-para do Nexus; usina com dois
    # ids (Primavera) fica sem (nunca chutar)
    no_banco = False
    if banco:
        try:
            ids = operacao_mes.ids_da_usina((fonte_operacao.dados() or {}).get("de_para") or [], usina)
        except Exception:                     # noqa: BLE001 — leitura da Operação no Mês fora: grava sem o id
            ids = set()
        try:
            contestacao_banco.registrar_contestacao(d, usina, next(iter(ids)) if len(ids) == 1 else None, ano, mes,
                                                    ini, fim, {k: (k in no_teams) if urls[k] else None for k in alvo})
            no_banco = True
        except Exception as e:                # noqa: BLE001 — sem dado pessoal no log
            print("[contestacao] não gravei no banco: %s %s" % (type(e).__name__, str(e)[:120]), flush=True)
    foi = [contestacao.CANAL[k] for k in alvo if no_banco or k in no_teams]
    nao = [contestacao.CANAL[k] for k in alvo if not (no_banco or k in no_teams)]
    if nao:
        msg = ("Enviado para %s, mas não para %s." % (" e ".join(foi), " e ".join(nao)) if foi
               else "Não consegui enviar agora.") + " Tente de novo em alguns minutos."
        return jsonify({"ok": False, "erro": msg, "destinos": foi}), 502
    return jsonify({"ok": True, "destinos": foi})


@app.route("/api/t/versao")
def versao():
    """Carimbo do dado que está na tela — quando o dashboard leu o banco."""
    return jsonify({"planilha_em": _planilha_em()})


@app.route("/")
def index():
    # regua: as frases dos 5 níveis da zeladoria para a aba Metodologia (08/10/2026) — a mesma cópia que a rota da
    # Operação no Mês manda para o card (operacao_mes.REGUA); o HTML não repete frase nenhuma
    u = _usuario() if _login_ligado() else None
    return render_template("dashboard_thopen.html", regua=operacao_mes.REGUA, raiz=request.script_root,
                           libera={k: _liberado(k) for k in LIBERADO_AO_CLIENTE},
                           usuario={"nome": u["nome"], "email": u["email"], "usuario": u.get("usuario") or u["email"],
                                    "papel": u["papel"]} if u else None)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5080, debug=False, threaded=True)
