# -*- coding: utf-8 -*-
"""Recoleta pela API PV para o Conversor Grid Co. (Levi, 13/11/2026: "deve ter algum campo para fazer uma recoleta pela
API... a pessoa seleciona a usina, seleciona o período... se ela quer recoletar geração, ETM... o que não está batendo
fica em amarelo").

Por que passa por aqui: o Conversor é instalado no PC da Lara e de outros, e a senha da API PV não pode ir dentro do
.exe (config.py do coletor: "a senha estava embutida aqui e viajava dentro de TODO .exe distribuido"). O servidor já
entra na API PV sozinho; o Conversor pede, recebe o dado cru e faz o de-para e a comparação com o BD do lado dele (o
mesmo fluxo da conversão de arquivo: amarelo = valor novo). Nada aqui grava em BD nenhum.

As mesmas chamadas e a mesma conta do coletor (`coletar_pvoperation.py`): `plant_devices` (nomes dos inversores),
`custom_query` energy (Eday por inversor no dia) e `custom_query` meteo (dia fechado, integrado em kWh/m² pela mesma
regra trapezoidal e os mesmos campos de POA/GHI). Só a conta principal (a da coleta do BD_Thopen).

Custo: o `custom_query` gasta a COTA HISTÓRICA da conta (800 por dia, 200 por hora, dividida com a combiner e com o
coletor da noite, que busca a geração do dia pela mesma cota). Cada planta × dia custa 1 (geração) + 1 (ETM). Três
travas: a reserva da plataforma (`_pv_cota_permite`: abaixo de 300 no dia ou 20 na hora não pede, é o que a coleta da
noite precisa), o teto próprio da recoleta (`TETO_DIA`, 150 por dia somando todos os PCs; `RECOLETA_TETO_DIA` muda) e o
tamanho do pedido (`MAX_PLANTAS` plantas × `MAX_DIAS` dias; o Conversor fatia o período e mostra o andamento).

Chave: cabeçalho `X-Recoleta-Chave`. É a `RECOLETA_CHAVE` do ambiente ou, sem ela, um HMAC da senha da API PV com um
rótulo fixo — o servidor e o PC do Levi chegam à mesma chave sem nenhuma configuração nova no servidor, e a chave não
revela a senha. Trocou a senha da API PV, a chave muda: gerar de novo o arquivo que o Conversor lê
(`ferramentas/conversor` → "Conversor Grid Co - recoleta.txt" na pasta de publicação do Performance).
"""
import datetime as dt
import hashlib
import os
import hmac
import json
import threading
from concurrent.futures import ThreadPoolExecutor

ROTULO = b"conversor-grid-co/recoleta-apipv/v1"
MAX_DIAS = 7
MAX_PLANTAS = 8
TETO_DIA = int(os.environ.get("RECOLETA_TETO_DIA") or 150)
TRABALHADORES = 6
_CONTA = {"dia": None, "n": 0}
_LOCK = threading.Lock()

_POA = ["IrPOA", "Ir", "Ir1", "piraPOA1"]               # os mesmos do coletor, na mesma ordem
_GHI = ["piraGHI1", "IrGHI", "piraGHI2", "IrGHITotal"]  # piraGHI1 primeiro: o IrGHI vem zerado/fiado no POA em várias


class Recusa(Exception):
    """Pedido que não passa (status HTTP, texto)."""

    def __init__(self, status, texto):
        super().__init__(texto)
        self.status = status


def chave_esperada(env_chave, pv_password):
    if env_chave:
        return env_chave.strip()
    if not pv_password:
        return ""
    return hmac.new(pv_password.encode("utf-8"), ROTULO, hashlib.sha256).hexdigest()


def confere(recebida, esperada):
    return bool(esperada) and bool(recebida) and hmac.compare_digest(str(recebida).encode(), str(esperada).encode())


def hoje_br(agora_utc=None):
    """O servidor roda em UTC: às 22h de Brasília já é amanhã lá."""
    agora_utc = agora_utc or dt.datetime.now(dt.timezone.utc)
    return (agora_utc - dt.timedelta(hours=3)).date()


def gastar(n, hoje):
    """Reserva `n` chamadas do teto do dia; Recusa(429) se não couber."""
    with _LOCK:
        if _CONTA["dia"] != hoje:
            _CONTA.update(dia=hoje, n=0)
        if _CONTA["n"] + n > TETO_DIA:
            raise Recusa(429, "teto de %d chamadas à API PV por dia atingido (%d usadas hoje); tente amanhã"
                         % (TETO_DIA, _CONTA["n"]))
        _CONTA["n"] += n
        return TETO_DIA - _CONTA["n"]


def _irr(c, campos):
    for f in campos:
        v = c.get(f)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if abs(fv) < 2000:                                # -666 e afins são código de erro
            return max(0.0, fv)
    return None


def integrar(leituras):
    """W/m² instantâneo -> kWh/m² do dia (trapézio), igual ao `integrate_meteo` do coletor. None sem 2 leituras; GHI
    None se veio tudo 0 (estação sem piranômetro horizontal)."""
    pts = []
    for r in leituras or []:
        ts = r.get("tsleitura_new")
        if not ts:
            continue
        try:
            t = dt.datetime.fromisoformat(ts).timestamp()
        except ValueError:
            continue
        c = r.get("conteudojson") or {}
        if isinstance(c, str):
            try:
                c = json.loads(c)
            except ValueError:
                continue
        p, g = _irr(c, _POA), _irr(c, _GHI)
        pts.append((t, p or 0.0, g or 0.0))
    if len(pts) < 2:
        return None, None
    pts.sort()

    def trapz(i):
        return sum((pts[k - 1][i] + pts[k][i]) / 2.0 * (pts[k][0] - pts[k - 1][0]) / 3600.0
                   for k in range(1, len(pts))) / 1000.0
    poa = round(trapz(1), 4)
    ghi = round(trapz(2), 4) if any(x[2] > 0 for x in pts) else None
    return poa, ghi


def _dias(ini, fim):
    out, d = [], ini
    while d <= fim:
        out.append(d)
        d += dt.timedelta(days=1)
    return out


def validar(corpo, plantas_conta, hoje):
    """(ids, dias, geracao, etm) ou Recusa(400)."""
    try:
        ids = [int(x) for x in corpo.get("ids") or []]
        ini = dt.date.fromisoformat(str(corpo.get("ini")))
        fim = dt.date.fromisoformat(str(corpo.get("fim")))
    except (TypeError, ValueError):
        raise Recusa(400, "pedido inválido: ids, ini e fim (AAAA-MM-DD)")
    geracao, etm = bool(corpo.get("geracao")), bool(corpo.get("etm"))
    if not ids or not (geracao or etm):
        raise Recusa(400, "escolha a usina e pelo menos Geração ou ETM")
    if len(set(ids)) > MAX_PLANTAS:
        raise Recusa(400, "no máximo %d plantas por pedido" % MAX_PLANTAS)
    desconhecidas = sorted(set(ids) - set(plantas_conta))
    if desconhecidas:
        raise Recusa(400, "planta(s) fora da conta da API PV: %s" % ", ".join(map(str, desconhecidas)))
    if fim < ini:
        raise Recusa(400, "período ao contrário")
    if fim >= hoje:
        raise Recusa(400, "só dia fechado: o período vai até ontem (%s)" % (hoje - dt.timedelta(days=1)).isoformat())
    dias = _dias(ini, fim)
    if len(dias) > MAX_DIAS:
        raise Recusa(400, "no máximo %d dias por pedido (o Conversor fatia o período)" % MAX_DIAS)
    return list(dict.fromkeys(ids)), dias, geracao, etm


def chamadas(n_plantas, n_dias, geracao, etm):
    return n_plantas * ((1 if geracao else 0) + n_dias * ((1 if geracao else 0) + (1 if etm else 0)))


def recoletar(post, corpo, plantas_conta, hoje, cota_permite=lambda: True):
    """post(caminho, json) -> resposta já em JSON. plantas_conta: {id: nome cru da API}.
    Devolve {"plantas": {id: {"nome", "inversores": {id: nome}, "dias": {iso: {"ger": {nome: kWh}, "ipoa", "ghi",
    "erro"}}}}, "chamadas", "restam"}. Eday nulo NÃO vira 0 (sem dado não se inventa)."""
    ids, dias, geracao, etm = validar(corpo, plantas_conta, hoje)
    if not cota_permite():
        raise Recusa(429, "a cota histórica da API PV está na reserva da coleta da noite; tente mais tarde")
    n = chamadas(len(ids), len(dias), geracao, etm)
    restam = gastar(n, hoje)
    out = {str(i): {"nome": plantas_conta[i], "inversores": {}, "dias": {d.isoformat(): {} for d in dias}} for i in ids}

    def nomes(pid):
        devs = post("/plant_devices", {"id": pid})
        devs = devs[0].get("plant_devices", []) if isinstance(devs, list) and devs else []
        return {str(d.get("device_id")): str(d.get("device_name") or "").strip()
                for d in devs if d.get("device_type") == "INVERTER"}

    def um_dia(pid, d):
        res, per = {}, d.strftime("%Y-%m")
        if not cota_permite():                            # a cota chegou na reserva no meio do pedido
            return pid, d, {"erro": "cota da API PV na reserva"}
        try:
            if geracao:
                ger = {}
                for r in post("/custom_query", {"id": pid, "data_type": "energy", "period": per, "day": d.day}) or []:
                    if str(r.get("dataleitura_new") or "")[:10] not in ("", d.isoformat()):
                        continue
                    try:
                        v = float(r.get("eday"))
                    except (TypeError, ValueError):
                        continue
                    ger[str(r.get("idinversor"))] = round(v, 2)
                res["ger"] = ger
            if etm:
                poa, ghi = integrar(post("/custom_query", {"id": pid, "data_type": "meteo", "period": per, "day": d.day}))
                res["ipoa"], res["ghi"] = poa, ghi
        except Exception as e:                            # um dia que falha não derruba o pedido
            res["erro"] = "%s: %s" % (type(e).__name__, e)
        return pid, d, res

    with ThreadPoolExecutor(max_workers=TRABALHADORES) as ex:
        if geracao:
            for pid, nm in zip(ids, ex.map(lambda p: _seguro(nomes, p), ids)):
                out[str(pid)]["inversores"] = nm
        for pid, d, res in ex.map(lambda a: um_dia(*a), [(p, d) for p in ids for d in dias]):
            inv = out[str(pid)]["inversores"]
            if "ger" in res:                              # id do inversor -> nome do supervisório
                res["ger"] = {inv.get(k, k): v for k, v in res["ger"].items()}
            out[str(pid)]["dias"][d.isoformat()] = res
    return {"plantas": out, "chamadas": n, "restam": restam}


def _seguro(f, *a):
    try:
        return f(*a)
    except Exception:
        return {}
