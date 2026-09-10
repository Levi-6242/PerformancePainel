# -*- coding: utf-8 -*-
"""Régua do PADRÃO DE PROPORCIONALIDADE por inversor — para usina SEM visão por string.

Por que existe: Ceilândia 1, Céu Azul e Ouro Branco são String Box com a combiner não exposta na
API PV (0 strings por desenho) e Barretos não tem esperado no cadastro. Nessas, a régua de strings
não enxerga nada e a usina fica "ok" para sempre. O Levi pediu (10/09/2026) outra abordagem: "se
por padrão aquele inversor opera a 94 % do maior, ou 98 % em relação aos demais, e cai 10 p.p.
ou mais, alerte".

O estudo dos 30 dias anteriores (13 plantas, 132 inversores, `custom_query energy` da API PV)
mostrou que a razão inversor ÷ mediana da usina no dia é MUITO estável: desvio-padrão p50 = 1,2
pp, p90 = 4,9 pp. Logo 10 pp é 2 a 8 desvios acima do ruído. Referência = MEDIANA da usina, não
o máximo: em Barretos 2 o INVERSOR19 gera 120 % da mediana e puxaria o "máximo" sozinho.

Tudo aqui é função pura sobre {dia: {id_inversor: kWh}} — sem HTTP, sem Flask, sem estado global
— para caber em teste (tests/test_inv_padrao.py). O app.py cuida de buscar, guardar e mostrar.
"""
import json
import os
import statistics
import threading
from datetime import date, timedelta

INV_PADRAO_JANELA = 30            # dias VÁLIDOS que ensinam o baseline
INV_PADRAO_MIN_DIAS = 7           # abaixo disso não há padrão para comparar (não inventa com 3 pontos)
INV_PADRAO_RETEM_DIAS = 45        # o store guarda mais que a janela: dias de chuva não contam como válidos
INV_PADRAO_DIA_VALIDO_FRAC = 0.25 # mediana da usina < 25 % do típico = chuva forte/sem dado → razão é ruído
INV_PADRAO_QUEDA_ATENCAO = 10.0   # pp abaixo do baseline (o pedido do Levi)
INV_PADRAO_QUEDA_CRITICO = 20.0   # pp — ou 3 dias seguidos em atenção
INV_PADRAO_DIAS_SEGUIDOS = 3
INV_PADRAO_SIGMA_MULT = 2.0       # inversor instável (Barretos 2 INV 12–20, σ 8–18 pp): limiar = max(10, 2σ)
INV_PADRAO_CRONICO = 85.0         # baseline abaixo disto = etiqueta "cronicamente abaixo" (Barretos INV 03/04)
INV_PADRAO_PREVIA_HORA = 14       # Eday parcial de HOJE só vale como prévia da tarde em diante


def _med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.median(xs) if xs else None


def _mediana_dia(dia: dict):
    """Mediana dos inversores que GERARAM (> 0). Zero e None ficam de fora: inversor parado não é
    referência de "quanto o sol deu", e o id fantasma (nunca reporta) não pode puxar a usina para baixo."""
    return _med([v for v in (dia or {}).values() if isinstance(v, (int, float)) and v > 0])


def tipico_kwh(E: dict):
    """Mediana das medianas diárias — o "dia normal" da usina, para separar chuva forte de dia útil."""
    return _med([_mediana_dia(d) for d in E.values()])


def dias_validos(E: dict, tipico=None) -> set:
    tip = tipico if tipico is not None else tipico_kwh(E)
    if not tip:
        return set()
    return {d for d, m in E.items() if (_mediana_dia(m) or 0) >= INV_PADRAO_DIA_VALIDO_FRAC * tip}


def baseline(E: dict, janela: int = INV_PADRAO_JANELA) -> dict:
    """{id: {"base": % da mediana da usina (mediana dos dias), "sigma": desvio-padrão em pp, "n": dias}}.
    Só os últimos `janela` dias válidos; id que nunca gerou nada não aparece."""
    validos = sorted(dias_validos(E))[-janela:]
    razoes = {}
    for d in validos:
        m = _mediana_dia(E[d])
        if not m:
            continue
        for i, v in E[d].items():
            if isinstance(v, (int, float)) and v > 0:
                razoes.setdefault(i, []).append(v / m * 100.0)
    out = {}
    for i, rs in razoes.items():
        if len(rs) < INV_PADRAO_MIN_DIAS:
            out[i] = {"base": None, "sigma": None, "n": len(rs)}
        else:
            out[i] = {"base": round(statistics.median(rs), 1),
                      "sigma": round(statistics.pstdev(rs), 1) if len(rs) > 1 else 0.0, "n": len(rs)}
    return out


def _limiar(b: dict) -> float:
    return round(max(INV_PADRAO_QUEDA_ATENCAO, INV_PADRAO_SIGMA_MULT * (b.get("sigma") or 0.0)), 1)


def classificar_dia(dia: dict, base: dict, tipico_kwh=None) -> dict:
    """Um dia contra o baseline. {id: {razao, base, sigma, delta, limiar, status, cronico}}.
    status: ok / atencao / critico / sem_base / sem_julgamento (dia de chuva forte ou sem leitura)."""
    m = _mediana_dia(dia)
    chuva = (tipico_kwh is not None) and ((m or 0) < INV_PADRAO_DIA_VALIDO_FRAC * tipico_kwh)
    out = {}
    for i in set(base) | {k for k, v in (dia or {}).items() if isinstance(v, (int, float))}:
        b = base.get(i) or {}
        v = (dia or {}).get(i)
        r = {"razao": None, "base": b.get("base"), "sigma": b.get("sigma"), "delta": None,
             "limiar": _limiar(b) if b.get("base") is not None else None,
             "status": "ok", "cronico": bool(b.get("base") is not None and b["base"] < INV_PADRAO_CRONICO)}
        if isinstance(v, (int, float)) and m:
            r["razao"] = round(v / m * 100.0, 1)
        if b.get("base") is None:
            r["status"] = "sem_base"
        elif chuva or r["razao"] is None:
            r["status"] = "sem_julgamento"
        else:
            r["delta"] = round(r["razao"] - b["base"], 1)
            lim = r["limiar"]
            if r["delta"] <= -(lim + (INV_PADRAO_QUEDA_CRITICO - INV_PADRAO_QUEDA_ATENCAO)):
                r["status"] = "critico"
            elif r["delta"] <= -lim:
                r["status"] = "atencao"
        out[i] = r
    return out


_ORDEM = {"critico": 0, "atencao": 1, "ok": 2, "sem_julgamento": 3, "sem_base": 4}


def avaliar_dia(E: dict, dia: str) -> dict:
    """Julga `dia` com o baseline dos dias ANTERIORES a ele. O dia julgado não ensina o próprio baseline —
    senão uma queda sustentada vira "o novo normal" aos poucos e nunca alerta.
    Atenção por INV_PADRAO_DIAS_SEGUIDOS dias seguidos (contra o mesmo baseline) sobe para crítico."""
    hist = {d: v for d, v in E.items() if d < dia}
    tip = tipico_kwh(hist)
    base = baseline(hist)
    n_base = len(sorted(dias_validos(hist, tip))[-INV_PADRAO_JANELA:])
    invs = classificar_dia(E.get(dia) or {}, base, tip) if dia in E else {}
    for i, r in invs.items():
        r["dias_seguidos"] = 0
        if r["status"] not in ("atencao", "critico"):
            continue
        # conta para trás os dias (válidos) em que este inversor já estava abaixo do limiar
        seguidos = 1
        for d in sorted(dias_validos(hist, tip), reverse=True):
            rd = classificar_dia(hist[d], base, tip).get(i) or {}
            if rd.get("status") in ("atencao", "critico"):
                seguidos += 1
            else:
                break
        r["dias_seguidos"] = seguidos
        if r["status"] == "atencao" and seguidos >= INV_PADRAO_DIAS_SEGUIDOS:
            r["status"] = "critico"
    alertas = sorted([{"inv": i, "status": r["status"], "razao": r["razao"], "base": r["base"], "delta": r["delta"]}
                      for i, r in invs.items() if r["status"] in ("atencao", "critico")],
                     key=lambda a: (_ORDEM[a["status"]], a["delta"]))
    status = min((r["status"] for r in invs.values()), key=lambda s: _ORDEM[s], default="sem_base")
    return {"dia": dia, "status": status, "alertas": alertas, "inversores": invs, "n_dias_base": n_base,
            "tipico_kwh": round(tip, 1) if tip else None}


def previa_hoje(eday: dict, base: dict, hora: int):
    """Eday parcial de HOJE contra o mesmo baseline — só da tarde em diante (antes é geração de meia manhã,
    e a razão entre inversores ainda oscila com sombra e rampa). None = ainda não é hora."""
    if hora < INV_PADRAO_PREVIA_HORA:
        return None
    out = classificar_dia(eday, base)
    for r in out.values():
        r["previa"] = True
    return out


def coletar_dia(post, plant_id, dia: str):
    """{id_inversor: kWh|None} do `POST /custom_query {id, data_type:"energy", period, day}` da API PV, ou
    None quando a API não devolveu a lista (ela reporta erro como DICT — e um erro não pode virar "dia sem
    geração" no store). `post(payload) -> json` é injetado: quem chama escolhe sessão, token e timeout."""
    d = date.fromisoformat(dia)
    recs = post({"id": plant_id, "data_type": "energy", "period": d.strftime("%Y-%m"), "day": d.day})
    if not isinstance(recs, list) or not all(isinstance(r, dict) for r in recs):
        return None
    out = {}
    for r in recs:
        i = r.get("idinversor")
        if i is None:
            continue
        try:
            out[str(i)] = float(r["eday"]) if r.get("eday") is not None else None
        except (TypeError, ValueError):
            out[str(i)] = None
    return out


class Store:
    """{plant_id: {"nome", "devs": {id: nome}, "dias": {dia: {id: kWh}}}} em JSON, gravação atômica.
    `path=None` = só memória (testes)."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.data = {}
        self.recarregar()

    def recarregar(self):
        """Relê o arquivo. São dois processos: o worker grava, o web lê — e o web pode ter nascido antes do worker
        gravar os devices (senão os inversores saem pelo id numérico da API até um restart)."""
        if not (self.path and os.path.exists(self.path)):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                novo = json.load(f) or {}
        except (OSError, ValueError) as e:
            print(f"[inv_padrao] store ilegível ({e}); mantenho o que tenho")
            return
        with self._lock:
            self.data = novo

    def _p(self, pid):
        return self.data.setdefault(str(pid), {"nome": None, "devs": {}, "dias": {}})

    def gravar_dia(self, pid, dia: str, mapa: dict):
        with self._lock:
            self._p(pid)["dias"][dia] = dict(mapa)

    def gravar_devs(self, pid, devs: dict, nome: str = None):
        with self._lock:
            p = self._p(pid)
            p["devs"] = dict(devs)
            if nome:
                p["nome"] = nome

    def dias(self, pid) -> dict:
        return dict((self.data.get(str(pid)) or {}).get("dias") or {})

    def devs(self, pid) -> dict:
        return dict((self.data.get(str(pid)) or {}).get("devs") or {})

    def dias_faltando(self, pid, ate: str, janela: int = INV_PADRAO_JANELA) -> list:
        fim = date.fromisoformat(ate)
        tem = self.dias(pid)
        return [d for d in ((fim - timedelta(days=k)).isoformat() for k in range(janela - 1, -1, -1)) if d not in tem]

    def salvar(self):
        if not self.path:
            return
        with self._lock:
            for p in self.data.values():
                ds = p.get("dias") or {}
                for d in sorted(ds)[:-INV_PADRAO_RETEM_DIAS]:
                    del ds[d]
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
