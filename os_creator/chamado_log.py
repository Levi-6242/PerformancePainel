"""Histórico de atualizações do chamado — o que substitui a coluna "Observações" da planilha
`Gestão de Chamados - Grid Co - V02.xlsx`.

POR QUE EXISTE: naquela planilha a coluna Observações não é texto solto, é um DIÁRIO datado —
uma linha por atualização, no formato `DD/MM - o que aconteceu`. Medido na planilha real:
566 chamados, **4.334 entradas**, mediana de 7 por chamado (o mais movimentado com 32), 91% com
mais de uma linha. É ali que mora o trabalho da equipe de chamados, e é o que faltava no app.

POR QUE FICA FORA DO FRACTTAL (por enquanto): a API não tem método de EDIÇÃO de OS já criada —
só criar, cancelar, mudar status, sincronizar etiqueta e anexar arquivo. Então o app não consegue
reescrever a observação da OS a cada atualização. O log fica num arquivo próprio (mesmo padrão das
notas dos analistas na plataforma) e o formato já sai pronto pra migrar pro Fracttal no dia em que
houver o método de escrita.

CHAVE: o Ticket/RMA, que na planilha está preenchido em 97% (contra 5% da "OS de Abertura") —
é a única coluna confiável pra casar chamado↔registro. Sem ticket, cai pro número da OS.
"""
import json
import os
import re
from datetime import datetime

_ARQ = "chamados_historico.json"
_CACHE = {"path": None, "dados": None, "mtime": 0}


def _caminho():
    """Arquivo do log, ao lado das outras configurações do app."""
    try:
        import api
        return os.path.join(api._data_dir(), _ARQ)
    except Exception:
        return None


def chave(ticket="", folio="") -> str:
    """Identificador do chamado no log. Ticket/RMA quando existe (é o que a planilha usa e o que
    sobrevive a recriar a OS); senão o nº da OS."""
    t = re.sub(r"\s+", "", str(ticket or "")).upper()
    if t:
        return "TK:" + t
    f = str(folio or "").strip()
    return ("OS:" + f) if f else ""


def _ler():
    """Lê o arquivo (com cache por mtime — o painel chama isso muitas vezes por carga)."""
    p = _caminho()
    if not p or not os.path.exists(p):
        return {}
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return {}
    if _CACHE["path"] == p and _CACHE["mtime"] == mt and _CACHE["dados"] is not None:
        return _CACHE["dados"]
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    d = d if isinstance(d, dict) else {}
    _CACHE.update({"path": p, "dados": d, "mtime": mt})
    return d


def _gravar(d):
    p = _caminho()
    if not p:
        return False
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        _CACHE.update({"path": p, "dados": d, "mtime": os.path.getmtime(p)})
        return True
    except Exception:
        return False


def entradas(ch) -> list:
    """Entradas do chamado, MAIS RECENTE PRIMEIRO → [{'data','texto','autor','origem'}]."""
    if not ch:
        return []
    out = list((_ler().get(ch) or {}).get("entradas") or [])
    out.sort(key=lambda e: str(e.get("data") or ""), reverse=True)
    return out


def adicionar(ch, texto, autor="", data=None) -> bool:
    """Nova atualização. A data é carimbada pelo app — na planilha havia 3 datas digitadas no
    futuro (2027), justamente por serem preenchidas à mão."""
    texto = str(texto or "").strip()
    if not ch or not texto:
        return False
    d = dict(_ler())
    reg = dict(d.get(ch) or {})
    ents = list(reg.get("entradas") or [])
    ents.append({"data": (data or datetime.now()).strftime("%Y-%m-%d %H:%M"),
                 "texto": texto, "autor": str(autor or "").strip(), "origem": "app"})
    reg["entradas"] = ents
    d[ch] = reg
    return _gravar(d)


def campos(ch) -> dict:
    """Situação gravada pelo app (status / esperando). Vazio se nunca foi editada aqui."""
    if not ch:
        return {}
    reg = _ler().get(ch) or {}
    return {k: v for k, v in (reg.get("campos") or {}).items() if v}


def set_campos(ch, novos: dict) -> bool:
    """Grava a situação do chamado NO APP. É o que permite a equipe mudar o status sem sair pro
    Fracttal — a API não deixa o app escrever na OS, então a subtarefa continua sendo o registro
    lá, e aqui fica o valor corrente com que a equipe trabalha."""
    if not ch or not isinstance(novos, dict):
        return False
    d = dict(_ler())
    reg = dict(d.get(ch) or {})
    at = dict(reg.get("campos") or {})
    at.update({k: str(v or "").strip() for k, v in novos.items()})
    reg["campos"] = at
    d[ch] = reg
    return _gravar(d)


def migrar_chave(de, para) -> bool:
    """Move o histórico de uma chave pra outra. NECESSÁRIO quando o chamado nasce sem ticket
    (chave `OS:<folio>`) e depois recebe o protocolo do fabricante (`TK:<ticket>`) — sem isso o
    histórico escrito antes da abertura ficaria órfão."""
    de, para = str(de or ""), str(para or "")
    if not de or not para or de == para:
        return False
    d = dict(_ler())
    if de not in d:
        return False
    orig = d.pop(de)
    dest = dict(d.get(para) or {})
    ents = list(dest.get("entradas") or []) + list(orig.get("entradas") or [])
    ents.sort(key=lambda e: str(e.get("data") or ""))
    dest["entradas"] = ents
    camp = dict(orig.get("campos") or {}); camp.update(dest.get("campos") or {})
    if camp:
        dest["campos"] = camp
    d[para] = dest
    return _gravar(d)


def ultima(ch):
    """datetime da última atualização (None se não houver)."""
    for e in entradas(ch):
        dt = _data(e.get("data"))
        if dt:
            return dt
    return None


def dias_sem_atualizacao(ch, agora=None):
    """Dias desde a última entrada — a régua da COBRANÇA. Na planilha real: dos 301 chamados em
    aberto, mediana de 22 dias e 104 parados há mais de 30. None se nunca teve atualização."""
    u = ultima(ch)
    if not u:
        return None
    return max(0, ((agora or datetime.now()) - u).days)


def _data(s):
    s = str(s or "").strip()
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y", "%d/%m"):
        try:
            dt = datetime.strptime(s, f)
            return dt.replace(year=datetime.now().year) if f == "%d/%m" else dt
        except ValueError:
            continue
    return None


# ── importação do histórico da planilha ──────────────────────────────────────
_LINHA = re.compile(r"^\s*(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?\s*[-–—:]\s*(.+?)\s*$")


def parse_log(texto, ano_ref=None) -> list:
    """Quebra a coluna Observações da planilha em entradas. Formato dominante: `DD/MM - texto`
    (99% das 566 linhas trazem data). Linhas sem data entram como continuação da anterior — na
    planilha há cabeçalhos soltos antes do diário começar.

    ANO: quase nenhuma entrada traz o ano, e os logs CRUZAM a virada ("11/12 … 22/12 … 05/01").
    Como a equipe escreve em ordem cronológica, o ano é deduzido de trás pra frente: a última
    entrada é do `ano_ref` (o ano da 'Data da Última Atualização' da planilha) e, andando pra
    trás, o ano cai 1 sempre que o mês AUMENTA."""
    brutos = []
    ano_ref = ano_ref or datetime.now().year
    for linha in str(texto or "").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        m = _LINHA.match(linha)
        if m:
            dia, mes, ano, corpo = m.groups()
            a = int(ano) if ano else None
            if a is not None and a < 100:
                a += 2000
            brutos.append({"dia": int(dia), "mes": int(mes), "ano": a, "texto": corpo})
        elif brutos:
            brutos[-1]["texto"] = (brutos[-1]["texto"] + " " + linha).strip()
        else:
            brutos.append({"dia": None, "mes": None, "ano": None, "texto": linha})
    # ── atribui o ano andando de trás pra frente ──
    ano = ano_ref
    ult_mes = None
    for b in reversed(brutos):
        if b["mes"] is None:
            continue
        if b["ano"] is not None:
            ano = b["ano"]
        elif ult_mes is not None and b["mes"] > ult_mes:
            ano -= 1                      # virou o ano indo pra trás (jan → dez anterior)
        b["ano"] = ano
        ult_mes = b["mes"]
    out = []
    for b in brutos:
        if b["mes"] is None:
            out.append({"data": "", "texto": b["texto"], "autor": "", "origem": "planilha"})
            continue
        try:
            dt = datetime(b["ano"], b["mes"], b["dia"])
        except ValueError:
            continue
        out.append({"data": dt.strftime("%Y-%m-%d %H:%M"), "texto": b["texto"],
                    "autor": "", "origem": "planilha"})
    return out


def importar(registros, substituir=False) -> dict:
    """Traz o histórico da planilha. `registros` = [{'ticket','folio','obs','ano'}].
    Por padrão NÃO mexe em chamado que já tem entrada do app (o importado é histórico, não
    verdade corrente). → {'chamados', 'entradas', 'pulados'}."""
    d = dict(_ler())
    n_ch = n_ent = pulados = 0
    for r in (registros or []):
        ch = chave(r.get("ticket"), r.get("folio"))
        if not ch:
            continue
        reg = dict(d.get(ch) or {})
        ja = list(reg.get("entradas") or [])
        if ja and not substituir:
            if any(e.get("origem") == "app" for e in ja):
                pulados += 1
                continue
        novas = parse_log(r.get("obs"), r.get("ano"))
        if not novas:
            continue
        reg["entradas"] = novas if substituir or not ja else ja + novas
        for k in ("ticket", "folio"):
            if r.get(k):
                reg[k] = str(r[k]).strip()
        d[ch] = reg
        n_ch += 1
        n_ent += len(novas)
    _gravar(d)
    return {"chamados": n_ch, "entradas": n_ent, "pulados": pulados}


def ler_planilha(caminho, aba="CHAMADOS") -> list:
    """Lê a planilha de chamados → registros p/ `importar`. GOTCHA conhecido: o arquivo fica
    aberto/travado no OneDrive e o pandas dá Errno 13 — por isso lê sempre de uma CÓPIA."""
    import shutil
    import tempfile
    import pandas as pd
    tmp = os.path.join(tempfile.gettempdir(), "_chamados_import.xlsx")
    shutil.copy2(caminho, tmp)
    df = pd.read_excel(tmp, aba)
    col = {str(c).strip().lower(): c for c in df.columns}
    c_tk = col.get("ticket/rma")
    c_obs = col.get("observações") or col.get("observacoes")
    c_os = col.get("os de abertura")
    c_up = col.get("data da última atualização") or col.get("data da ultima atualizacao")
    if not c_obs:
        return []
    regs = []
    for _, r in df.iterrows():
        obs = r.get(c_obs)
        if not isinstance(obs, str) or not obs.strip():
            continue
        ano = None
        if c_up is not None:
            try:
                ano = int(str(r.get(c_up))[:4])
            except Exception:
                ano = None
        regs.append({"ticket": r.get(c_tk) if c_tk else "",
                     "folio": r.get(c_os) if c_os else "",
                     "obs": obs, "ano": ano})
    return regs
