# -*- coding: utf-8 -*-
"""Quem entra no tempo real, fonte por fonte (Levi, 11/10/2026): "Antes o controle do que entra e o que não entra em tempo
real estava sendo do Claude, eu passava as instruções e o claude inseria ao meu gosto. Precisamos de um espaço para
administração do que entra no tempo real onde eu possa através da fonte permitir qual usina entra e qual não entra."

Até aqui a lista de cada fonte morava em quatro lugares: constantes no código (`PV_FONTES`, `scadagridco.FONTES`), a coluna
"Full O&M" do BD_Performance (só para a API PV principal), "tudo que a conta devolve" (SunOp, SolarEdge, o banco da Thopen)
e uma regra calada (o card cai fora se o cliente não casa na Info Geral). Mudar exigia o Claude, um commit e um deploy.

As regras que o Levi deu (11/10/2026):
- usina NOVA numa fonte espera ele liberar, com notificação de "usina nova" (o sino das telas);
- a escolha vale no Tempo real, no Monitoramento, no Painel NOC e na ronda do WhatsApp;
- usina tirada PARA DE SER COLETADA (economiza cota; os dias fora ficam sem dado).
Por isso o filtro mora na LISTA de usinas de cada fonte, antes da coleta: tudo o que vem depois (cards, tabelas, rollup do
NOC, ronda) só vê o que entrou.

O dado (governança do Nexus, `nexus/dados/CLAUDE.md`): livro `nexus_tempo_real`, aba `fato_decisao_cobertura`, registrado
no catálogo do Nexus. Grão: 1 linha = 1 decisão de incluir ou excluir 1 usina (chave nativa da fonte) de 1 fonte. Tipo:
sem medida. Só acrescenta (o estado vigente é a última decisão de cada fonte × chave); o histórico de quem entrou e saiu fica
no próprio dado. Nada de pessoa nem texto livre (a API do banco é de leitura aberta). PC e servidor leem o MESMO livro.

Segurança contra sumiço em massa (confiabilidade é a prioridade 1):
- uma fonte só passa a ser governada quando tem as linhas de MIGRAÇÃO (a foto do que aparecia no dia da troca); sem elas,
  a fonte segue como antes;
- se o livro não puder ser lido, vale a última leitura boa (memória e disco); sem nenhuma, nada é filtrado (como antes) e a
  tela de administração diz que as decisões estão indisponíveis.
Este módulo é a regra (sem Flask); a leitura e a gravação no banco moram em `Decisoes`.
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

LIVRO = "nexus_tempo_real"
NOME_LIVRO = "Nexus · Tempo real (cobertura por fonte)"
ABA = "fato_decisao_cobertura"
CAB = ["decidida_em", "data_id", "fonte", "chave", "decisao", "origem"]
DECISOES = ("incluir", "excluir")
ORIGENS = ("migracao", "tela")

# As fontes como o Monitoramento as chama (a chave da aba), com o rótulo das telas.
FONTES = {
    "pv": "Thopen · API PV",
    "pg": "Thopen · Banco de dados",
    "sunop": "Athon",
    "axis": "Axis",
    "solaredge": "RenoGrid",
    "semp": "SEMP",
    "alveslima": "Alves Lima",
    "2capi": "2C",
    "greenyellow": "GreenYellow",
    "salenergia": "Sal Energia",
}

_BRT = timezone(timedelta(hours=-3))


def agora_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def linha(fonte: str, chave, decisao: str, origem: str, quando: str | None = None) -> list:
    """Uma decisão, na ordem do CAB. `data_id` = o dia de Brasília da decisão (regra 7 do Nexus)."""
    if fonte not in FONTES:
        raise ValueError(f"fonte desconhecida: {fonte!r}")
    if decisao not in DECISOES:
        raise ValueError(f"decisão inválida: {decisao!r}")
    if origem not in ORIGENS:
        raise ValueError(f"origem inválida: {origem!r}")
    chave = str(chave).strip()
    if not chave:
        raise ValueError("chave vazia")
    quando = quando or agora_utc()
    dia = datetime.strptime(quando, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(_BRT)
    return [quando, int(dia.strftime("%Y%m%d")), fonte, chave, decisao, origem]


def _como_dict(lin) -> dict:
    return dict(zip(CAB, lin)) if isinstance(lin, (list, tuple)) else dict(lin)


def vigente(linhas) -> dict:
    """{(fonte, chave): decisão} pela última decisão de cada par (a mais recente; no empate, a que veio depois)."""
    marcadas = []
    for i, lin in enumerate(linhas or []):
        d = _como_dict(lin)
        f, c, dec = str(d.get("fonte") or ""), str(d.get("chave") or "").strip(), d.get("decisao")
        if f in FONTES and c and dec in DECISOES:
            marcadas.append((str(d.get("decidida_em") or ""), i, f, c, dec))
    estado = {}
    for _q, _i, f, c, dec in sorted(marcadas):
        estado[(f, c)] = dec
    return estado


def governadas(linhas) -> set:
    """As fontes que já passaram pela migração: só elas são filtradas."""
    return {str(_como_dict(lin).get("fonte")) for lin in (linhas or [])
            if _como_dict(lin).get("origem") == "migracao" and _como_dict(lin).get("fonte") in FONTES}


def filtrar(fonte: str, itens, chave_de, linhas):
    """(os que entram, os novos sem decisão). Fonte não governada (ou decisões indisponíveis, `linhas` None): todos
    entram e não há novos — como era antes da tela."""
    itens = list(itens or [])
    if linhas is None or fonte not in governadas(linhas):
        return itens, []
    estado = vigente(linhas)
    entram, novos = [], []
    for it in itens:
        dec = estado.get((fonte, str(chave_de(it)).strip()))
        if dec == "incluir":
            entram.append(it)
        elif dec is None:
            novos.append(it)
    return entram, novos


def semente(fonte: str, inventario, visiveis, quando: str | None = None) -> list:
    """As linhas de migração de uma fonte: `incluir` para cada chave que aparecia no tempo real no dia da troca, `excluir`
    para o resto do que a fonte devolve. Assim a troca não muda nada na tela; dali em diante, quem manda é a tela."""
    quando = quando or agora_utc()
    vis = {str(c).strip() for c in visiveis}
    return [linha(fonte, c, "incluir" if str(c).strip() in vis else "excluir", "migracao", quando)
            for c in sorted({str(c).strip() for c in inventario} | vis)]


# ── o inventário: o que cada fonte devolveu, para a tela listar e para o sino das usinas novas ───────────────────────
class Inventario:
    """O que cada fonte devolveu da última vez ({fonte: {chave: {"nome", "visto_em"}}}), em disco (o worker coleta; a
    tela, no processo web, lê) e as usinas novas já avisadas (para o sino avisar uma vez só)."""

    def __init__(self, caminho: str):
        self.caminho = caminho
        self._lock = threading.Lock()

    def ler(self) -> dict:
        try:
            with open(self.caminho, encoding="utf-8") as f:
                d = json.load(f) or {}
        except Exception:
            d = {}
        d.setdefault("fontes", {})
        d.setdefault("avisadas", [])
        return d

    def _gravar(self, d: dict):
        tmp = self.caminho + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, self.caminho)

    def registrar(self, fonte: str, itens) -> None:
        """`itens` = [(chave, nome)]: a lista inteira que a fonte devolveu agora. Troca a da fonte (usina que saiu da
        conta sai daqui também); o `visto_em` diz quando."""
        if fonte not in FONTES:
            return
        quando = agora_utc()
        novo = {str(c).strip(): {"nome": str(n or "").strip(), "visto_em": quando} for c, n in itens if str(c).strip()}
        with self._lock:
            d = self.ler()
            atual = d["fontes"].get(fonte) or {}
            # a mesma lista lida há menos de 10 min não regrava o arquivo (a lista de uma fonte é pedida várias vezes
            # por ciclo: strings, ETM, trackers)
            if {c: v.get("nome") for c, v in atual.items()} == {c: v["nome"] for c, v in novo.items()}:
                try:
                    lida = datetime.strptime(d.get("lido_em", {}).get(fonte, ""), "%Y-%m-%dT%H:%M:%SZ")
                    if (datetime.now(timezone.utc) - lida.replace(tzinfo=timezone.utc)).total_seconds() < 600:
                        return
                except ValueError:
                    pass
            d["fontes"][fonte] = novo
            d.setdefault("lido_em", {})[fonte] = quando
            try:
                self._gravar(d)
            except Exception as e:
                print(f"[cobertura] inventário não gravado: {e}")

    def a_avisar(self, fonte: str, novos_chaves) -> list:
        """Das usinas novas, as que ainda não foram avisadas (e marca como avisadas)."""
        with self._lock:
            d = self.ler()
            ja = set(d["avisadas"])
            fazer = [c for c in (str(x).strip() for x in novos_chaves) if c and f"{fonte}|{c}" not in ja]
            if fazer:
                d["avisadas"] = sorted(ja | {f"{fonte}|{c}" for c in fazer})
                try:
                    self._gravar(d)
                except Exception as e:
                    print(f"[cobertura] avisadas não gravadas: {e}")
            return fazer


# ── as decisões no banco ─────────────────────────────────────────────────────────────────────────────────────────────
class GravacaoErro(RuntimeError):
    pass


class Decisoes:
    """Lê (com cache de `ttl` s e a última leitura boa em disco) e acrescenta decisões no livro do banco. O livro, a aba e
    o cabeçalho são os da cobertura por padrão; o De-para de equipamentos (depara.py) usa a mesma classe com os dele."""

    def __init__(self, base: str, token, cache_path: str, ttl: int = 60, sessao=None, livro: str = LIVRO,
                 aba: str = ABA, cab=None, nome_livro: str = NOME_LIVRO):
        self.livro, self.aba, self.cab, self.nome_livro = livro, aba, list(cab or CAB), nome_livro
        self.base = base.rstrip("/")
        self._token = token if callable(token) else (lambda: token)
        self.cache_path = cache_path
        self.ttl = ttl
        self._sessao = sessao
        self._lock = threading.Lock()
        self._linhas = None
        self._lido = 0.0
        self.erro = None
        self.lido_em = None

    @property
    def sessao(self):
        if self._sessao is None:
            import requests
            self._sessao = requests.Session()
        return self._sessao

    def _aba_id(self):
        r = self.sessao.get(f"{self.base}/api/sheets", timeout=30)
        r.raise_for_status()
        dados = r.json()
        dados = dados.get("items", dados) if isinstance(dados, dict) else dados
        for x in dados:
            if x.get("workbook_key") == self.livro and x.get("sheet_name") == self.aba:
                return x["id"]
        return None

    def _ler_banco(self) -> list:
        sid = self._aba_id()
        if sid is None:
            return []                                  # o livro ainda não existe: nenhuma fonte governada
        out, off = [], 0
        while True:
            r = self.sessao.get(f"{self.base}/api/sheets/{sid}/rows", params={"limit": 1000, "offset": off}, timeout=60)
            r.raise_for_status()
            rows = r.json()
            rows = rows.get("rows", rows) if isinstance(rows, dict) else rows
            for x in rows:
                d = dict(zip(x.get("headers") or self.cab, x.get("values") or []))
                out.append([d.get(c) for c in self.cab])
            if len(rows) < 1000:
                return out
            off += 1000

    def _disco(self):
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                d = json.load(f)
            return d.get("linhas"), d.get("lido_em")
        except Exception:
            return None, None

    def linhas(self, forcar: bool = False):
        """As decisões, ou None se nunca foi possível ler (nem banco, nem memória, nem disco)."""
        with self._lock:
            if not forcar and self._linhas is not None and time.time() - self._lido < self.ttl:
                return self._linhas
            try:
                novas = self._ler_banco()
                self._linhas, self._lido, self.erro, self.lido_em = novas, time.time(), None, agora_utc()
                try:
                    tmp = self.cache_path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump({"lido_em": self.lido_em, "linhas": novas}, f, ensure_ascii=False)
                    os.replace(tmp, self.cache_path)
                except Exception as e:
                    print(f"[cobertura] cópia das decisões não gravada: {e}")
            except Exception as e:                       # banco fora: a última leitura boa segue valendo
                self.erro = f"{type(e).__name__}"
                self._lido = time.time()                 # não martela o banco a cada pedido
                if self._linhas is None:
                    self._linhas, self.lido_em = self._disco()
            return self._linhas

    def acrescentar(self, novas: list) -> int:
        """Relê o livro do banco (sem cache), acrescenta `novas`, grava inteiro e confere a contagem. → o total."""
        token = (self._token() or "").strip()
        if not token:
            raise GravacaoErro("sem GRIDCO_SQL_TOKEN nesta máquina: a decisão não foi gravada")
        with self._lock:
            atuais = self._ler_banco()
            todas = atuais + [list(x) for x in novas]
            h = {"Authorization": f"Bearer {token}"}
            r = self.sessao.get(f"{self.base}/api/workbooks", headers=h, timeout=60)
            r.raise_for_status()
            lista = r.json()
            lista = lista.get("items", lista) if isinstance(lista, dict) else lista
            if self.livro not in {w.get("key") for w in lista}:
                self.sessao.post(f"{self.base}/api/workbooks", headers=h,
                                 json={"key": self.livro, "display_name": self.nome_livro}, timeout=60).raise_for_status()
            r = self.sessao.post(f"{self.base}/api/workbooks/{self.livro}/sync-xlsx", headers=h, params={"replace": "true"},
                                 files={"file": (f"{self.livro}.xlsx", xlsx_bytes(todas, self.aba, self.cab),
                                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                                 timeout=300)
            r.raise_for_status()
            gravadas = self._ler_banco()
            if len(gravadas) != len(todas):
                raise GravacaoErro(f"{self.livro}.{self.aba}: enviei {len(todas)} linhas e o banco tem {len(gravadas)}")
            self._linhas, self._lido, self.erro, self.lido_em = gravadas, time.time(), None, agora_utc()
            return len(gravadas)


def xlsx_bytes(linhas, aba: str = ABA, cab=None) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = aba
    ws.append(list(cab or CAB))
    for lin in linhas:
        ws.append(list(lin))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
