# gemeo/gemeo/ingest/plat.py
"""Fonte `plat`: angulo dos trackers das tres usinas da 2C (Araputanga, Sete Lagoas, Tupi Paulista).

POR QUE MUDOU DE CAMINHO EM 21/09/2026
Ate aqui esta fonte batia direto na apiplataforma.pvoperation.com com um token colado a mao no
gemeo.env (`PV_PLAT_TOKEN_OEM`, 7 dias). Ela parou em 19/09 e o diagnostico obvio — "o token
venceu" — estava ERRADO: o token no gemeo.env era literalmente o MESMO da Plataforma de
Performance, valido ate 23/09. O que a API respondia era HTTP **200** com
`{"message": "Usuario nao possui permissao para acessar o recurso"}`: e o token da conta **gridco**,
e estas tres usinas sao da conta **oem@**. Pior, o 200 escondia o problema — o codigo so tratava
401/403, entao isso nao abria o disjuntor, virava excecao de parsing e o ciclo morria calado.

O caminho certo ja existia na casa. A Plataforma de Performance recebe o acervo da 2C por E-MAIL e
o serve pronto (ARA 59, STL 59, TUP 100 trackers, angulo a cada 5 min) — sem token, sem conta, sem
vencimento. Esta fonte agora le de la, por `/api/gemeo/trackers/<ref>/chart`, autenticando com o
MESMO segredo compartilhado que a plataforma usa para falar com o gemeo (`X-Gemeo-Senha`). Deixou
de existir um segundo token para alguem esquecer de renovar.

O QUE O ACERVO DA PLATAFORMA DA, e o que nao da:
- da: por tracker, `x` (carimbos) e `y` (angulo), ~5 min; e UMA serie `alvo` comum a frota.
- NAO da: o de-para tracker -> inversor (isso so vinha do `/v2/usinas/trackers` da apiplataforma).
  Por isso esta fonte NAO CRIA equipamento: os 218 trackers ja estao cadastrados com o inversor-pai
  certo, e criar aqui produziria tracker orfao, sem pai, duplicando o que existe. Nome que nao casa
  e contado em `nao_mapeados` para aparecer, em vez de sumir.

CARIMBO: vem com sufixo `Z`, que e FALSO — a hora e de BRASILIA, igual ao que a apiplataforma fazia.
Medido em 21/09 pelo meio-dia solar: a mediana da frota da Araputanga chega a 0 grau por volta de
12:55 no carimbo como veio, e o meio-dia solar da lon -58,3 e 12:50 de Brasilia. Ler como UTC
deslocaria a serie inteira em 3 h.

DE-PARA DOS NOMES: o acervo chama `Tracker <grupo>.<n>`, o cadastro do gemeo chama `TRK<numero>`.
Na Araputanga e na Sete Lagoas nao ha ambiguidade (um grupo so, 1..59). Na Tupi o acervo divide os
100 em 1.1-1.30, 2.1-2.30 e 3.1-3.40 enquanto o cadastro tem `numero` 1..100 corrido, e a ORDEM
entre os grupos e uma SUPOSICAO (decisao do Levi, 21/09): grupo 1 -> 1..30, grupo 2 -> 31..60,
grupo 3 -> 61..100. Tentei provar cruzando as curvas de 18/09 e nao da: tracker saudavel segue o
mesmo sol, o melhor casamento erra por 0,2 grau, e naquele dia nao havia tracker parado para servir
de impressao digital. `conferir_de_para()` existe para fechar essa conta sozinha no dia em que um
tracker ficar parado — ai a assinatura e unica."""
from __future__ import annotations
import datetime as dt
import re

import requests

from gemeo.core.modelos import UsinaRef
from gemeo.ingest.apipv import FUSO_API
from gemeo.ingest.base import Busca, Ingestor

BLOCO_MIN = 15
_FORMATOS = ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")
_NOME = re.compile(r"^\s*Tracker\s+(\d+)\.(\d+)\s*$", re.I)


def ts_utc(texto) -> dt.datetime:
    """'2026-09-21T06:04:46Z' -> UTC. O `Z` e sufixo falso: a hora e de Brasilia (ver o cabecalho)."""
    s = str(texto or "").strip()
    for f in _FORMATOS:
        try:
            naive = dt.datetime.strptime(s, f)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"carimbo do acervo da 2C fora do formato: {s!r}")
    return naive.replace(tzinfo=FUSO_API).astimezone(dt.timezone.utc)


def ordem_dos_nomes(nomes) -> list[str]:
    """`Tracker g.n` ordenados por (grupo, n) — a ordem que o de-para assume. Nome fora do padrao fica de fora."""
    pares = []
    for n in nomes or ():
        m = _NOME.match(str(n))
        if m:
            pares.append((int(m.group(1)), int(m.group(2)), str(n)))
    return [n for _, _, n in sorted(pares)]


def de_para_nomes(nomes) -> dict[str, str]:
    """{'Tracker 1.1': 'TRK1', ...} pela ordem (grupo, n). Na Tupi isto e a SUPOSICAO do cabecalho."""
    return {nome: f"TRK{i}" for i, nome in enumerate(ordem_dos_nomes(nomes), start=1)}


def _bloco(ts: dt.datetime, minutos: int) -> dt.datetime:
    return ts.replace(minute=ts.minute - ts.minute % minutos, second=0, microsecond=0)


def _serie(t: dict) -> list[tuple[dt.datetime, float]]:
    out = []
    for x, y in zip(t.get("x") or [], t.get("y") or []):
        if not isinstance(y, (int, float)) or isinstance(y, bool):
            continue
        try:
            out.append((ts_utc(x), float(y)))
        except ValueError:
            continue
    return sorted(out)


def leituras_da_curva(payload, mapa_trk: dict[str, int], ini: dt.datetime, fim: dt.datetime) -> tuple[list[tuple], int]:
    """Um angulo por tracker por bloco de 15 min, em (ini, fim]. -> (leituras, nomes nao mapeados).

    Guardar 1 ponto/5 min x 218 trackers seriam ~150 mil linhas/dia; o modelo trabalha em blocos de
    15 min, que e a grade do `p_ac` da fonte apipv — a comparacao tracker x inversor precisa da mesma."""
    trks = (payload or {}).get("trackers") if isinstance(payload, dict) else None
    if not isinstance(trks, list):
        return [], 0
    nomes = [str((t or {}).get("id") or "") for t in trks]
    depara = de_para_nomes(nomes)
    out: list[tuple] = []
    nao = 0
    for t in trks:
        if not isinstance(t, dict):
            continue
        eid = mapa_trk.get(depara.get(str(t.get("id") or ""), ""))
        if eid is None:
            nao += 1
            continue
        vistos: set = set()
        for ts, v in _serie(t):
            if not (ini < ts <= fim):
                continue
            b = _bloco(ts, BLOCO_MIN)
            if b in vistos:
                continue
            vistos.add(b)
            out.append((eid, "angulo", ts, v))
    return out, nao


def leituras_do_alvo(payload, mapa_trk: dict[str, int], ini: dt.datetime, fim: dt.datetime) -> list[tuple]:
    """`angulo_alvo` no ultimo instante da janela, um por tracker.

    O acervo traz a curva inteira do alvo, mas ele e UM so para a frota: grava-lo em todo bloco
    multiplicaria por 218 um valor identico. Fica so o instante — exatamente o que a fonte antiga
    gravava (o alvo so existia no estado), para esta troca mudar a ORIGEM do dado e nao a regua."""
    alvo = (payload or {}).get("alvo") if isinstance(payload, dict) else None
    if not isinstance(alvo, dict) or not mapa_trk:
        return []
    serie = [(ts, v) for ts, v in _serie(alvo) if ini < ts <= fim]
    if not serie:
        return []
    ts, v = serie[-1]
    return [(eid, "angulo_alvo", ts, v) for eid in sorted(mapa_trk.values())]


def conferir_de_para(payload, curvas_do_gemeo: dict[str, list[float]], parado_ate: float = 20.0) -> dict:
    """Confere a suposicao de ordem da Tupi QUANDO houver tracker parado (amplitude pequena no dia).

    Nao serve em dia normal: com todos seguindo o sol as curvas sao indistinguiveis (medido em
    18/09/2026 — o 'melhor casamento' erra por 0,2 grau). Com um parado, a assinatura e unica.
    -> {"conclusivo": bool, "confere": bool, "pares": [(nome, TRKn)]}"""
    trks = (payload or {}).get("trackers") if isinstance(payload, dict) else None
    if not isinstance(trks, list):
        return {"conclusivo": False, "confere": False, "pares": []}
    depara = de_para_nomes([str((t or {}).get("id") or "") for t in trks])

    def amp(vals):
        return (max(vals) - min(vals)) if len(vals or []) > 2 else None

    # `or` aqui seria bug: amplitude 0.0 — o tracker PERFEITAMENTE travado, o caso que esta funcao
    # existe para achar — e falsy, e sumiria da lista. Comparacao explicita com None.
    def parado(vals):
        a = amp(vals)
        return a is not None and a < parado_ate

    parados_acervo = [str(t.get("id")) for t in trks
                      if isinstance(t, dict) and parado([v for _, v in _serie(t)])]
    parados_gemeo = [k for k, v in (curvas_do_gemeo or {}).items() if parado(v)]
    if len(parados_acervo) != 1 or len(parados_gemeo) != 1:
        return {"conclusivo": False, "confere": False, "pares": []}   # zero ou varios: nao identifica
    par = (parados_acervo[0], parados_gemeo[0])
    return {"conclusivo": True, "confere": depara.get(par[0]) == par[1], "pares": [par]}


def dias_da_janela(ini: dt.datetime, fim: dt.datetime) -> list[dt.date]:
    """Dias de Brasilia que a janela toca — o acervo da 2C e por dia."""
    d, ultimo = ini.astimezone(FUSO_API).date(), fim.astimezone(FUSO_API).date()
    out = []
    while d <= ultimo:
        out.append(d)
        d += dt.timedelta(days=1)
    return out


class IngestorPlatTrackers(Ingestor):
    fonte = "plat"
    tipos = ("tracker",)          # marca d'agua so dos trackers: a usina e a mesma da fonte apipv

    def __init__(self, cfg, conn, usinas: list[UsinaRef], http=None):
        super().__init__(cfg, conn, usinas)
        self.http = http or requests.Session()

    def _get(self, usina: UsinaRef, ini_d: dt.date, fim_d: dt.date, timeout: int = 180) -> dict:
        senha = (getattr(self.cfg, "senha_app", "") or "").strip()
        base = (getattr(self.cfg, "plataforma_url", "") or "").rstrip("/")
        if not (senha and base):
            raise RuntimeError("falta GEMEO_SENHA ou PLATAFORMA_URL para ler os trackers da 2C na plataforma")
        r = self.http.get(f"{base}/api/gemeo/trackers/{usina.fonte_ref}/chart",
                          headers={"X-Gemeo-Senha": senha, "accept": "application/json"},
                          params={"ini": ini_d.isoformat(), "fim": fim_d.isoformat()}, timeout=timeout)
        if r.status_code in (401, 403):
            self.disjuntor.abrir(f"HTTP {r.status_code}: a plataforma recusou o X-Gemeo-Senha")
            raise RuntimeError("a Plataforma de Performance recusou o segredo compartilhado: conferir GEMEO_SENHA "
                               "nos dois lados (gemeo.env e tokens.txt)")
        if r.status_code == 404:
            raise RuntimeError(f"usina {usina.fonte_ref} fora do acervo da 2C na plataforma")
        if r.status_code == 429 or r.status_code >= 500:
            self.disjuntor.abrir(f"HTTP {r.status_code} ao ler os trackers da 2C")
            raise RuntimeError(f"plataforma HTTP {r.status_code} em /api/gemeo/trackers")
        j = r.json()
        # A fonte antiga so olhava 401/403 e um 200 com "sem permissao" passava batido, matando o ciclo
        # calado por dois dias (19-21/09). Aqui todo corpo que nao traz `trackers` vira erro explicito.
        if not isinstance(j, dict) or "trackers" not in j:
            corpo = str(j)[:160] if not isinstance(j, dict) else str(j.get("error") or j)[:160]
            raise RuntimeError(f"resposta sem trackers da plataforma (HTTP {r.status_code}): {corpo}")
        return j

    def _mapa(self, usina: UsinaRef) -> dict[str, int]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT codigo_fonte, id FROM equipamento WHERE usina_id=%s AND tipo='tracker' AND ativo", (usina.id,))
            return dict(cur.fetchall())

    def descobrir(self, usina: UsinaRef) -> None:
        """Nao cria equipamento: este acervo nao sabe a que inversor cada tracker pertence, e tracker
        sem pai nao serve para a cascata. Os 218 ja estao cadastrados (vieram da apiplataforma quando
        ela ainda respondia); tracker novo tem de entrar pelo cadastro, nao por aqui."""
        return None

    def buscar(self, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime) -> Busca:
        mapa = self._mapa(usina)
        dias = dias_da_janela(ini, fim)
        payload = self._get(usina, dias[0], dias[-1])
        leituras, nao = leituras_da_curva(payload, mapa, ini, fim)
        leituras += leituras_do_alvo(payload, mapa, ini, fim)
        if nao:
            print(f"[plat] {usina.codigo}: {nao} tracker(es) do acervo sem par no cadastro do gemeo", flush=True)
        return Busca(leituras=leituras, n_requisicoes=1)
