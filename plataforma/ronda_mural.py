# -*- coding: utf-8 -*-
"""O mural da ronda de trackers do App de Campo (18/11/2026). Levi: "Refaça a página Ronda de trackers da performance como
um mural de acompanhamento da ronda de trackers do app de campo".

Junta duas coisas que já existiam, sem consulta nova a fonte nenhuma:
- o livro `rondas_app_campo` (o App regrava de hora em hora): de cada ronda, a usina (pelo nome do Fracttal), o técnico,
  o início e o fim, a nota e QUANTOS trackers foram apontados e quantos tiveram resposta;
- o pacote de falhas do mês: as paradas de tracker em aberto de cada usina, e o de-para usina → nome no Fracttal
  (`disponibilidade.usinas`), que é como o livro chama a usina.

O que o técnico respondeu em CADA tracker (normalizado ou não, motivo, ação) fica só na tabela `rondas` do App: não vem
no livro, e por isso o mural mostra a ronda, não o tracker. Puro: quem lê o livro e o pacote é o app.py."""
import re
import unicodedata
from datetime import datetime

ROTULO_FONTE = {"pv": "API PV", "pvsb": "API PV", "pg": "Banco de dados", "owen": "2C", "sunop": "SunOp"}
TRK_POR_USINA = 40                # trackers parados listados por usina (o total vai inteiro)


def _norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def _int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _minutos(ini, fim):
    """A duração da ronda em minutos, do início e do fim que o App grava; None sem os dois ou fora de (0, 24 h)."""
    try:
        a, b = (datetime.strptime(str(x)[:19], "%Y-%m-%dT%H:%M:%S") for x in (ini, fim))
    except (TypeError, ValueError):
        return None
    d = (b - a).total_seconds() / 60
    return round(d) if 0 < d < 24 * 60 else None


_RX_NUMS = re.compile(r"^(.*?)\s+((?:\d+|[ivx]+)(?:\s+e\s+(?:\d+|[ivx]+))*)$")
_ROMANO = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}


def _base_e_numeros(nome):
    """"Coração 1 e 2" → ("coracao", {1, 2}); "Coração 2" → ("coracao", {2}); "Rio do Peixe I e II" → ("rio do peixe",
    {1, 2}); sem número no fim → (nome, set())."""
    n = _norm(nome)
    m = _RX_NUMS.match(n)
    if not m:
        return n, set()
    nums = {int(x) if x.isdigit() else _ROMANO.get(x) for x in m.group(2).split(" e ")}
    return (m.group(1), nums) if None not in nums else (n, set())


def _miolo(fracttal):
    """"Thopen - Coração 1 e 2 - SC" → ("thopen", "Coração 1 e 2"); fora do formato → ("", nome)."""
    p = [x.strip() for x in str(fracttal or "").split(" - ")]
    return (_norm(p[0]), " - ".join(p[1:-1])) if len(p) >= 3 else ("", str(fracttal or ""))


def nome_no_livro(usina, fracttal, cliente, nomes_do_livro) -> str:
    """Como o LIVRO de rondas chama a usina. O cadastro manda quando o nome dele está no livro. Senão, a usina que o
    Fracttal junta com a vizinha (Levi, 18/11/2026: "se existir Coração no Fracttal com duas cabines pode contar como
    Coração 2"): o livro tem "Thopen - Coração 1 e 2 - SC", o cadastro tem a Coração 1 como "Thopen - Coração 1 - SC" e a
    Coração 2 sem nome. Vale o nome do livro do MESMO cliente e da mesma usina-base cujos números incluem o desta; com
    mais de um candidato não adivinha. Sem achar, fica o nome do cadastro (ou "" se ele não tem)."""
    fracttal = str(fracttal or "").strip()
    if fracttal and fracttal in nomes_do_livro:
        return fracttal
    cli = _miolo(fracttal)[0] if fracttal else _norm(cliente)
    base, nums = _base_e_numeros(_miolo(fracttal)[1] if fracttal else usina)
    if not cli or not nums:
        return fracttal
    cand = []
    for n in nomes_do_livro:
        c2, miolo = _miolo(n)
        b2, n2 = _base_e_numeros(miolo)
        if c2 == cli and b2 == base and len(n2) > 1 and nums <= n2:
            cand.append(n)
    return cand[0] if len(cand) == 1 else fracttal


def meses_do_livro(livro) -> list:
    return sorted({str(l.get("Data") or "")[:7] for l in livro or [] if re.match(r"^\d{4}-\d{2}", str(l.get("Data") or ""))})


def montar(livro, pacote, mes, hoje) -> dict:
    """livro = as linhas do `rondas_app_campo` (dicts pelo cabeçalho); pacote = o pacote de falhas de `mes` (ou None);
    hoje = AAAA-MM-DD. → o que a tela mostra."""
    pacote = pacote or {}
    nomes = {l.get("Usina") for l in livro or [] if l.get("Usina")}          # o livro inteiro (90 dias), não só o mês
    frac = {}
    for u in (pacote.get("disponibilidade") or {}).get("usinas") or []:
        f = nome_no_livro(u.get("usina"), u.get("fracttal"), u.get("cliente"), nomes)
        if f:
            frac[_norm(u.get("usina"))] = f
    parados, sem_par = {}, {}
    for r in (pacote.get("trackers") or {}).get("rows") or []:
        if r.get("fim"):
            continue                                         # só o que segue parado
        f = frac.get(_norm(r.get("usina")))
        if not f:
            sem_par[r.get("usina")] = sem_par.get(r.get("usina"), 0) + 1
            continue
        p = parados.setdefault(f, {"n": 0, "fonte": "", "trk": []})
        p["n"] += 1
        p["fonte"] = " · ".join(x for x in (r.get("cliente") or "", ROTULO_FONTE.get(r.get("fonte"), r.get("fonte") or "")) if x)
        p["trk"].append([str(r.get("tracker")), str(r.get("inicio") or "")[:10], bool(r.get("cronico"))])
    rondas, tecnicos = [], set()
    for l in livro or []:
        if str(l.get("Data") or "")[:7] != mes:
            continue
        tecnicos.add(l.get("Técnico (HMAC)") or l.get("Técnico") or "")
        rondas.append({"d": str(l["Data"])[:10], "u": l.get("Usina") or "", "reg": l.get("Região") or "", "tec": l.get("Técnico") or "", "tipo": l.get("Tipo") or "",
                       "ap": _int(l.get("Trackers apontados")), "rs": _int(l.get("Trackers respondidos")), "nota": l.get("Nota da ronda"), "falhas": l.get("Falhas") or "",
                       "ini": str(l.get("Início") or "")[:16], "min": _minutos(l.get("Início"), l.get("Fim"))})
    usinas = []
    for f in sorted(set(parados) | {r["u"] for r in rondas if r["u"]}):
        rs = sorted((r for r in rondas if r["u"] == f), key=lambda r: (r["d"], r["ini"]))
        ct = [r for r in rs if r["ap"]]
        p = parados.get(f) or {"n": 0, "fonte": "", "trk": []}
        usinas.append({"u": f, "fonte": p["fonte"], "par": p["n"], "trk": sorted(p["trk"], key=lambda z: z[1])[:TRK_POR_USINA], "n": len(rs), "nT": len(ct),
                       "ult": rs[-1]["d"] if rs else None, "ultT": ct[-1] if ct else None, "ap": sum(r["ap"] for r in ct), "rs": sum(r["rs"] for r in ct)})
    com = sorted((r for r in rondas if r["ap"]), key=lambda r: (r["d"], r["ini"]), reverse=True)
    return {"mes": mes, "hoje": hoje, "pacote": pacote.get("gerado_em") or "", "usinas": usinas, "rondas": com, "nRondas": len(rondas),
            "nTec": len(tecnicos - {""}), "semPar": [u for u, _n in sorted(sem_par.items(), key=lambda z: -z[1])]}
