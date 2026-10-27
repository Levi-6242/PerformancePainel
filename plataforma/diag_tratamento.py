# -*- coding: utf-8 -*-
"""O que já tem tratamento no Diagnóstico da usina (fase 1, 27/10/2026): desligamentos/religamentos e chamados.

Levi, 27/10/2026, sobre NEXUS > PERFORMANCE > DIAGNÓSTICO (o `/painel/usina/<id>` desta plataforma, aberto pela porta
única): cada problema do diagnóstico sai com CAUSA PROVÁVEL + PROVA + AÇÃO, e o que já tem tratamento vai para um grupo
"Explicado / em tratamento", deixando na frente só o que ninguém está olhando. Fase 1 = só desligamentos/religamentos e
chamados, com regra SEM parâmetro (nenhum limite de dias, nenhum filtro inventado):

- OS de desligamento/religamento NO PERÍODO do problema que cobre o ativo = explicado. "Desligamento/religamento" é o que
  a Disponibilidade já conta (`disponibilidade.TIPOS_ALVO`: Religamento, Religamento Remoto, Corretiva Emergencial), lido
  do MESMO índice que o worker monta para o Gerencial (`frac_disp_index.json`, as `oss` do mês, sem as excluídas): é o
  que a aba `falhas_performance · disponibilidade_os` publica no banco. Nenhuma chamada nova ao Fracttal.
  Cobrir o ativo = a hierarquia da Disponibilidade: OS da usina inteira cobre todos os inversores; da cabine N, os
  inversores da cabine N; do inversor, só ele.
  Período: o problema "de agora" (o motor R-07..R-10 e o básico das strings) só se explica por OS que pega HOJE (aberta,
  ou fechada hoje); o problema "do mês" (PR do mês abaixo da meta/dos pares) por OS que pegou algum dia do mês.
- Chamado de garantia aberto (o "Acompanhamento de chamados" do Nexus, NÃO a planilha de tickets: regra do Levi de
  12/10/2026) para o ativo = em tratamento, "aguardando fabricante há N dias". Lido do livro que o Nexus publica,
  `nexus_chamados · fato_chamado` (o mesmo dado do quadro), situação `aberto` ou `verificacao`. O ativo sai do código do
  Fracttal da OS de acompanhamento, pela mesma régua da Disponibilidade (INVR/DINV N.M = inversor; CABN/SKID/QGBT/PECN/DTRF
  N = cabine; o code-base sozinho = a usina). Chamado de tracker, NCU, RSU e estação NÃO liga a problema nesta fase (o nº
  do tracker do Fracttal não tem de-para provado com o do supervisório): fica em `outros`, só contado.

Puro: sem Flask, sem rede, sem arquivo. O app.py injeta o mês do índice, as linhas do livro e a hora.
"""
import re
import unicodedata
from datetime import date, datetime

import disponibilidade as _disp   # a régua Fracttal → cadastro é dela (INV_RENUMERADO)

# o cabeçalho do livro `nexus_chamados · fato_chamado` — CÓPIA do `nexus/dados/fato_chamado.py` (CAB_CHAMADO), o dono.
# A leitura do banco é por NOME de coluna (`cobertura.Decisoes`): coluna nova lá não quebra aqui, só não chega.
LIVRO_CHAMADO, ABA_CHAMADO = "nexus_chamados", "fato_chamado"
NOME_LIVRO_CHAMADO = "Nexus · chamados de garantia (OS de acompanhamento de chamado do Fracttal)"
CAB_CHAMADO = ("os", "data_id_abertura", "data_id_fim", "usina_id", "usina_ligada_por", "site_fracttal",
               "equipamento_id", "equipamento_ligado_por", "codigo_ativo", "situacao", "fabricante", "componente",
               "duracao_min", "abertura_por")
# a OS de acompanhamento em processo e a em verificação: o chamado não fechou (a concluída sai)
CHAMADO_EM_ABERTO = ("aberto", "verificacao")

SUF_CABINE = ("CABN", "SKID", "QGBT", "PECN", "DTRF")     # a mesma lista do disponibilidade.SUF_CABINE
_RX_INV = re.compile(r"-D?INVR?(\d+(?:\.\d+)?)$")
_RX_CAB = re.compile(r"-(" + "|".join(SUF_CABINE) + r")(\d+)$")
_RX_RAIZ = re.compile(r"[A-Z]{3}\d{3}$")
_RX_INV_NOME = re.compile(r"(\d+)(?:\.(\d+))?")

ORIGEM_TXT = {"queda": "queda de energia", "equipamento": "falha de equipamento"}


def nrm(s) -> str:
    """Chave de comparação de nome: sem acento, sem espaço, minúscula ("Inversor 1.2" ≡ "inversor1.2")."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", "", s).lower()


def ativo_do_codigo(code) -> tuple:
    """(nivel, rotulo) do código do ativo do Fracttal: ("inversor", "Inversor 3.3") de "MAB100-INVR3.3"; ("cabine",
    "Cabine 2") de "ACB100-CABN2"; ("usina", "Usina inteira") do code-base sozinho ("FRN100", "THPN-CLN100"); ("outro",
    código) para tracker, NCU, RSU, estação e o resto."""
    c = str(code or "").strip().upper()
    if not c:
        return "outro", ""
    m = _RX_INV.search(c)
    if m and ("INVR" in c or "DINV" in c):
        return "inversor", "Inversor " + _disp.inv_do_fracttal(c, m.group(1))   # a numeração própria (Barretos)
    m = _RX_CAB.search(c)
    if m:
        return "cabine", "Cabine " + str(int(m.group(2)))
    if _RX_RAIZ.search(c):
        return "usina", "Usina inteira"
    return "outro", c


def cabine_do_inversor(nome):
    """2 de "Inversor 2.3"; None sem o padrão N.M (o inversor numerado sozinho, "Inversor 16", não diz a cabine)."""
    m = _RX_INV_NOME.search(str(nome or ""))
    return int(m.group(1)) if (m and m.group(2) is not None) else None


def _dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:19])
    except ValueError:
        return None


def _data_id(v):
    try:
        n = int(v)
        return date(n // 10000, n // 100 % 100, n % 100)
    except (TypeError, ValueError):
        return None


def _dm(d) -> str:
    return d.strftime("%d/%m %H:%M") if isinstance(d, datetime) else (d.strftime("%d/%m/%Y") if d else "")


def _dias(n: int) -> str:
    return f"{n} dia" if n == 1 else f"{n} dias"


def _horas(h) -> str:
    """2,5 h / 0,4 h / 12 h (pt-BR, uma casa até 10 h)."""
    h = float(h)
    return (f"{h:.1f}".replace(".", ",") if h < 10 else f"{h:.0f}") + " h"


def _mes_limites(mes: str):
    a, m = int(mes[:4]), int(mes[5:7])
    ini = datetime(a, m, 1)
    fim = datetime(a + (m == 12), m % 12 + 1, 1)
    return ini, fim


def itens_os(mes_idx: dict, chaves_usina, mes: str, agora: datetime) -> list:
    """As OS de desligamento/religamento do índice da Disponibilidade (o mês `mes`) que tocam a usina (`chaves_usina` =
    as `nrm` dos nomes da usina no índice), uma por OS × escopo nesta usina. Cada item já diz se pega HOJE e se pegou o
    MÊS — é isso que decide qual problema ela explica. A excluída da conta (cancelada, ativo que não é de geração...) não
    entra: a Disponibilidade também não a conta."""
    chaves = {nrm(k) for k in chaves_usina or () if k}
    if not chaves or not mes_idx:
        return []
    m0, m1 = _mes_limites(mes)
    hoje0 = datetime(agora.year, agora.month, agora.day)
    out = []
    for o in mes_idx.get("oss") or ():
        if o.get("excl"):
            continue
        ini = _dt(o.get("ini")) or _dt(o.get("criada"))
        fim = _dt(o.get("fim"))
        aberta = bool(o.get("aberta"))
        if ini is None:
            continue
        fim_conta = None if aberta else fim                # a aberta segue até agora
        no_mes = ini < min(m1, agora) and (fim_conta is None or fim_conta >= m0)
        hoje = ini <= agora and (fim_conta is None or fim_conta >= hoje0)
        if not no_mes:
            continue
        tipos = [str(t) for t in o.get("tipos") or [] if t]
        tipo = " + ".join(tipos) or "OS"
        origem = str(o.get("origem") or "")
        for e in o.get("escopo") or ():
            if nrm(e.get("usina")) not in chaves:
                continue
            nivel, rotulo = str(e.get("nivel") or ""), str(e.get("rotulo") or "")
            folio = o.get("folio")
            dias_ab = max(0, (agora.date() - ini.date()).days)
            if aberta:
                estado = "aberta"
                acao = f"Já tem OS {folio} aberta há {_dias(dias_ab)}: acompanhar a OS."
            else:
                estado = f"fechada em {_dm(fim)}" if fim else "fechada"
                acao = f"Já tratado pela OS {folio} ({estado})."
            out.append({
                "tipo": "os", "os": folio, "link": f"/os/os/folio/{folio}" if str(folio or "").isdigit() else None,
                "nivel": nivel, "rotulo": rotulo, "tipos": tipos, "origem": origem,
                "aberta": aberta, "hoje": hoje, "mes": True,
                "desde": ini.isoformat(timespec="minutes"), "ate": fim.isoformat(timespec="minutes") if fim else None,
                "causa": f"Desligamento por {ORIGEM_TXT.get(origem, 'OS de desligamento')} ({tipo}) — {rotulo}",
                # o tamanho da OS vai junto (as horas de sol que ela tirou na conta da Disponibilidade, no mês): a regra
                # não pesa nada, mas quem lê vê se 2 h de religamento "explicam" um mês abaixo da meta
                "h_sol": o.get("h_solar"),
                "prova": (f"OS {folio} · {tipo} · {rotulo} · desde {_dm(ini)} · {estado}"
                          + (f" · {_horas(o.get('h_solar'))} de sol fora no mês" if o.get("h_solar") else "")),
                "acao": acao,
            })
    return out


def itens_chamado(linhas, sites_usina, agora: datetime, mes: str = None) -> list:
    """Os chamados de garantia EM ABERTO da usina (`sites_usina` = os nomes do site no Fracttal, a "Usina Fractall"), um
    por OS de acompanhamento. `linhas` = as do livro `fato_chamado` (dicionários pelo cabeçalho). Aberto agora = pega hoje;
    pega o `mes` (AAAA-MM) quando abriu antes do fim dele (o mês passado escolhido no seletor não ganha chamado de depois)."""
    sites = {nrm(s) for s in sites_usina or () if s}
    if not sites:
        return []
    out = []
    for c in linhas or ():
        if str(c.get("situacao") or "") not in CHAMADO_EM_ABERTO or nrm(c.get("site_fracttal")) not in sites:
            continue
        nivel, rotulo = ativo_do_codigo(c.get("codigo_ativo"))
        ab = _data_id(c.get("data_id_abertura"))
        dias = max(0, (agora.date() - ab).days) if ab else None
        fab, comp = str(c.get("fabricante") or "").strip(), str(c.get("componente") or "").strip()
        quem = " · ".join(x for x in (fab, comp) if x) or "fabricante"
        n = c.get("os")
        verif = c.get("situacao") == "verificacao"
        if dias is None:
            acao = "Em verificação no Acompanhamento de chamados." if verif else "Aguardando fabricante."
        else:
            acao = (f"Chamado em verificação (aberto há {_dias(dias)})." if verif
                    else f"Aguardando fabricante há {_dias(dias)}.")
        out.append({
            "tipo": "chamado", "os": n, "link": f"/os/os/folio/{n}" if str(n or "").isdigit() else None,
            "nivel": nivel, "rotulo": rotulo, "codigo": c.get("codigo_ativo"), "fabricante": fab, "componente": comp,
            "situacao": c.get("situacao"), "aberta": True, "hoje": True,
            "mes": (ab is None or not mes or ab < _mes_limites(mes)[1].date()),
            "desde": ab.isoformat() if ab else None, "dias": dias,
            "causa": f"Chamado de garantia com {quem} — {rotulo}",
            "prova": (f"OS de acompanhamento {n} · {c.get('codigo_ativo') or 'sem código'} · aberto desde "
                      f"{_dm(ab) or '—'} · {'em verificação' if verif else 'aberto'}"),
            "acao": acao,
        })
    return out


def _ordem(x):
    # o que está aberto primeiro (é o que alguém está olhando agora), depois o mais recente
    return (0 if x.get("aberta") else 1, "" if x.get("desde") is None else str(x["desde"]))


def montar(itens, inversores=()) -> dict:
    """Distribui os itens pelos alvos que eles cobrem. → {usina, cabines, inversores, outros}:
    - `usina`: o que cobre a usina inteira (serve ao problema de nível usina e a todo inversor);
    - `cabines`: {N: itens da cabine N};
    - `inversores`: {nome: tudo o que cobre o inversor (usina + cabine dele + o próprio)}, para os inversores do cadastro
      (`inversores` = [(nome, cabine ou None)]) e os que aparecem nos próprios itens;
    - `outros`: chamados de ativo que não liga a problema nesta fase (tracker, NCU, RSU, estação)."""
    usina, cabines, proprios, outros = [], {}, {}, []
    for x in itens or ():
        nv = x.get("nivel")
        if nv == "usina":
            usina.append(x)
        elif nv == "cabine":
            m = re.search(r"(\d+)\s*$", str(x.get("rotulo") or ""))       # "Cabine 2"
            if m:
                cabines.setdefault(int(m.group(1)), []).append(x)
        elif nv == "inversor":
            proprios.setdefault(nrm(x.get("rotulo")), []).append(x)
        else:
            outros.append(x)
    nomes = {}
    for nome, cab in inversores or ():
        if nome:
            nomes[nrm(nome)] = (nome, cab if cab is not None else cabine_do_inversor(nome))
    for k, lst in proprios.items():
        if k not in nomes:
            r = lst[0].get("rotulo")
            nomes[k] = (r, cabine_do_inversor(r))
    por_inv = {}
    for k, (nome, cab) in nomes.items():
        tudo, vistos = [], set()
        for x in usina + (cabines.get(cab, []) if cab is not None else []) + proprios.get(k, []):
            if (x.get("tipo"), x.get("os")) not in vistos:        # a mesma OS em dois níveis conta uma vez
                vistos.add((x.get("tipo"), x.get("os")))
                tudo.append(x)
        if tudo:
            por_inv[nome] = sorted(tudo, key=_ordem)
    return {"usina": sorted(usina, key=_ordem), "cabines": {str(k): sorted(v, key=_ordem) for k, v in cabines.items()},
            "inversores": por_inv, "outros": sorted(outros, key=_ordem)}
