# -*- coding: utf-8 -*-
"""Falhas de strings e trackers — monta o pacote da aba "Falhas" do Diagnóstico de performance (24/09/2026).

É o código do estudo de 24/09 ("Falhas de strings e trackers, com a perda em kWh"), trazido para a plataforma para
o estudo e a aba usarem a MESMA conta. O worker chama `montar()` e grava o pacote; a tela só lê.

Entradas (o chamador entrega; aqui nada vai à rede):
- quedas de string gravadas (`perdas_strings.json`) e, onde houver, a régua nova sobre a curva (`falhas_strings.json`,
  de 24/09 em diante) — por usina-dia, a régua nova vence;
- curva do 2C (2C_historico, em disco) com a régua nova para todos os dias;
- episódios de tracker (`trk_eventos.json`) e o book de paradas (crônicos);
- cadastro: Equipamentos e Info Geral (kWp, strings ativas, cliente), BD_Trackers (tracker → inversor);
- travas de string (ufv_state), o de-para de inversor da API PV e a geração diária do mês (o juiz do kWh/kWp).

Réguas (pedidos do Levi, 24/09):
- strings: 06–18h, 2 h SEGUIDAS sem corrente (ver falhas.py); trancada não entra; episódio que atravessa o dia
  continua se a string amanhece zerada; sem notícia depois, segue EM ABERTO — "teremos mais informação no outro dia";
- trackers: a régua de parado da plataforma; parado que vira severo/médio/leve sai da visão; "parado" no alvo o
  episódio todo (desvio < 2°) não é falha;
- perda: kWp do equipamento × kWh/kWp real do dia × fração da energia do dia no episódio (strings, pela altura do
  sol) ou das horas solares (trackers, × 1 − cos do desvio de pico).
"""
import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import falhas as _regua

YIELD_PADRAO = 4.5            # kWh/kWp de usina plena (o piso da disponibilidade.py) — só quando falta a geração
FATOR_TRK_PADRAO = 0.25       # perda de tracker sem ângulo conhecido
JAN_INI, JAN_FIM = 6 * 60, 18 * 60
STR_MIN_MIN = 120             # "mais que 2 horas" seguidas (a curva já vem assim da régua nova; nas quedas gravadas é aqui)
DESPERTAR = 7 * 60 + 30       # caiu até 07:30 = amanheceu zerada (a régua do "zerada desde" da plataforma)
FONTE_VARRE_TUDO = {"sunop", "axis", "owen"}
FONTE_ROT = {"pv": "API PV", "pg": "Banco", "sunop": "Athon", "axis": "Axis", "owen": "2C"}
_CACHE_2C = {}                # dia fechado → (marca das travas, [(cod, usina, strings sem corrente)])


def _hm(s):
    try:
        h, m = str(s).split(":")[:2]
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _fmt(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _prox(dia, n=1):
    return (datetime.strptime(dia, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


def _dias_entre(a, z):
    while a <= z:
        yield a
        a = _prox(a)


def montar(app, sol, ini, fim, *, geracao, pv_dev=None, mortas_curva=None, str_store=None, trk_store=None,
           book=None, hist_2c=None, agora=None, log=print):
    """Pacote {periodo, gerado_em, strings, trackers, regua} de [ini, fim] (AAAA-MM-DD, fim incluso).
    hist_2c(dia) → {"strings": {cod: {inv: {string: serie}}}} (padrão: app._hist_build, o 2C_historico em disco)."""
    import pandas as pd

    t0 = time.time()
    # episódio aberto de HOJE termina em "agora", não às 18:00: às 10:21 de 25/09 os 405 trackers parados desde a manhã
    # contavam até as 18:00 (~11 h cada, em vez de ~3 h) — 45 MWh a mais só no dia corrente
    agora = agora or datetime.now()
    hoje, agora_min = agora.strftime("%Y-%m-%d"), agora.hour * 60 + agora.minute

    def fim_janela(dia):
        return min(JAN_FIM, agora_min) if dia == hoje else JAN_FIM

    pv_dev = pv_dev or {}
    mortas_curva = mortas_curva or {}
    if str_store is None:
        with open(app._PERDAS_STR_PATH, encoding="utf-8") as f:
            str_store = json.load(f)
    if trk_store is None:
        with open(os.path.join(os.path.dirname(app._PERDAS_STR_PATH), "trk_eventos.json"), encoding="utf-8") as f:
            trk_store = json.load(f)
    if book is None:
        try:
            with open(os.path.join(os.path.dirname(app._PERDAS_STR_PATH), "paradas_book.json"), encoding="utf-8") as f:
                book = json.load(f)
        except Exception:
            book = {}
    nrm = app._nrm
    SOL_MIN = sol.SOL_BAIXO_GRAUS

    # ── cadastro por NOME DE EXIBIÇÃO (é o que os stores guardam) ─────────────────────────────
    df = pd.read_excel(app._bd_readable(), sheet_name="Equipamentos", header=2)
    CAD_INV, CAD_UFV, CLIENTE_DE, CAD_INV_DISP = {}, {}, {}, {}
    for _, r in df.iterrows():
        us, eq = r.get("Usina"), r.get("Equipamento")
        if pd.isna(us) or pd.isna(eq):
            continue
        usn, eqs = nrm(us), str(eq).strip()
        pot = r.get("Potência (kWp)")
        pot = float(pot) if pd.notna(pot) else None
        if pd.notna(r.get("Cliente")):
            CLIENTE_DE.setdefault(usn, str(r["Cliente"]).strip())
        if eqs.upper() == "UFV":
            CAD_UFV[usn] = {"kwp": pot, "n_inv": int(r["N de Inversores"]) if pd.notna(r.get("N de Inversores")) else None}
        elif eqs.lower().startswith("inversor"):
            sa = r.get("Strings Ativas")
            CAD_INV[(usn, nrm(eqs))] = {"kwp": pot, "strings": int(round(float(sa))) if pd.notna(sa) else None,
                                        "sup": str(r.get("Equipamento Supervisório") or "").strip()}
            CAD_INV_DISP[(usn, eqs)] = CAD_INV[(usn, nrm(eqs))]
    # Info Geral: kWp e nº de trackers — fallback de quem não está no BD_Trackers nem tem linha UFV com kWp
    IG_TRK, IG_KWP, IG_NINV = {}, {}, {}
    try:
        ig = pd.read_excel(app._bd_readable(), sheet_name="Info Geral", header=None)
        hdr = next(i for i in range(6) if any("usina" in str(v).lower() for v in ig.iloc[i].values))
        ig.columns = [str(c).strip() for c in ig.iloc[hdr].values]
        ig = ig.iloc[hdr + 1:]
        c_us = next(c for c in ig.columns if c.lower().startswith("usina"))
        c_tr = next((c for c in ig.columns if "tracker" in c.lower()), None)
        c_kw = next((c for c in ig.columns if "kwp" in c.lower()), None)
        c_ni = next((c for c in ig.columns if "inversor" in c.lower()), None)
        for _, r in ig.iterrows():
            u = nrm(r[c_us]) if pd.notna(r[c_us]) else ""
            if not u:
                continue
            for c, dst in ((c_tr, IG_TRK), (c_kw, IG_KWP), (c_ni, IG_NINV)):
                if c is not None and pd.notna(r[c]):
                    try:
                        dst[u] = float(r[c])
                    except (TypeError, ValueError):
                        pass
    except Exception as e:
        log(f"[falhas] Info Geral não lida: {e}")

    def canon(usina):
        return app._macro_usina_nome(str(usina or "")) or str(usina or "")

    def cliente(usina):
        c = canon(usina)
        ig_ = app.INFO_GERAL.get(nrm(c)) or {}
        return ig_.get("cliente") or CLIENTE_DE.get(nrm(c)) or CLIENTE_DE.get(nrm(usina)) or ""

    def inv_nome(s):
        s = str(s or "").strip()
        return f"Inversor {s}" if re.fullmatch(r"\d+\.\d+", s) else s

    def cad_inv(usina, inversor):
        """(kWp do inversor, strings esperadas, origem) — pelo nome de exibição; fallback = UFV ÷ N inversores."""
        for u in (usina, canon(usina)):
            c = CAD_INV.get((nrm(u), nrm(inversor)))
            if c:
                return c["kwp"], c["strings"], "inversor"
        for u in (usina, canon(usina)):
            ufv = CAD_UFV.get(nrm(u))
            if ufv and ufv.get("kwp") and ufv.get("n_inv"):
                return ufv["kwp"] / ufv["n_inv"], None, "ufv/n"
            k = nrm(u)
            if IG_KWP.get(k) and IG_NINV.get(k):
                return IG_KWP[k] / IG_NINV[k], None, "ufv/n"
        return None, None, "sem_kwp"

    # ── sol por estado ────────────────────────────────────────────────────────────────────────
    _jan_cache, _perfil_cache = {}, {}

    def janela_sol(usina, dia):
        est = app._estado_da_usina(usina) or app._estado_da_usina(canon(usina))
        key = (est, dia)
        if key in _jan_cache:
            return _jan_cache[key]
        if not est or sol.coordenadas(est) is None:
            _jan_cache[key] = (None, None, est)
            return _jan_cache[key]
        d0 = datetime.strptime(dia, "%Y-%m-%d")
        a = b = None
        for m in range(4 * 60, 20 * 60, 2):
            e = sol.elevacao_estado(est, d0 + timedelta(minutes=m))
            if e is not None and e >= SOL_MIN:
                a = m if a is None else a
                b = m
        _jan_cache[key] = (a, b, est)
        return _jan_cache[key]

    def intersec(a, b, usina, dia):
        """[a,b) em minutos ∩ 06–18h ∩ sol ≥ 8° no estado. → (ini, fim, minutos, sem_estado)."""
        si, sf, est = janela_sol(usina, dia)
        lo, hi = JAN_INI, JAN_FIM
        if si is not None:
            lo, hi = max(lo, si), min(hi, sf)
        x, y = max(a, lo), min(b, hi)
        return x, y, max(0, y - x), est is None

    def h_sol_dia(usina, dia):
        return intersec(0, 24 * 60, usina, dia)[2] / 60.0

    def perfil_sol(usina, dia):
        """Peso da energia minuto a minuto = sin(elevação), o proxy de céu limpo: a perda de um episódio é a FRAÇÃO
        DA ENERGIA DO DIA que cabe nele — uma string zerada das 09:00 às 16:30 perde ~80% do dia, não 100%."""
        est = app._estado_da_usina(usina) or app._estado_da_usina(canon(usina))
        key = (est, dia)
        if key in _perfil_cache:
            return _perfil_cache[key]
        if not est or sol.coordenadas(est) is None:
            _perfil_cache[key] = None
            return None
        d0 = datetime.strptime(dia, "%Y-%m-%d")
        acc, s = [0.0], 0.0
        for m in range(0, 24 * 60, 2):
            e = sol.elevacao_estado(est, d0 + timedelta(minutes=m))
            s += max(0.0, math.sin(math.radians(e))) if e is not None else 0.0
            acc.append(s)
        _perfil_cache[key] = acc
        return acc

    def share_energia(usina, dia, x, y):
        if y <= x:
            return 0.0
        acc = perfil_sol(usina, dia)
        if not acc or acc[-1] <= 0:
            return (y - x) / (12 * 60.0)
        i, j = min(len(acc) - 1, x // 2), min(len(acc) - 1, y // 2)
        return (acc[j] - acc[i]) / acc[-1]

    # ── geração diária por usina (juiz do kWh/kWp) ────────────────────────────────────────────
    GER_N = {nrm(u): v for u, v in (geracao or {}).items()}

    def yield_dia(usina, dia):
        for u in (canon(usina), usina, re.sub(r"\s+\d+$", "", canon(usina))):
            g = GER_N.get(nrm(u))
            if g and g.get("kwp") and dia in g["dias"] and g["dias"][dia] > 0:
                return g["dias"][dia] / g["kwp"]
        return None

    # ══ STRINGS ══════════════════════════════════════════════════════════════════════════════
    dias = [x for x in sorted(str_store) if ini <= x <= fim]
    # "em aberto" conta pelo último dia COM dado, não pela data de hoje: logo depois da meia-noite o período já vai
    # até um dia vazio, e tudo que estava aberto ontem fechava (25/09, 00:33 no servidor: 0 trackers em aberto)
    ult_str = max((x for x in dias if any((str_store[x] or {}).values())), default=fim)
    str_q = Counter()
    parcial, massa = set(), {}
    registro = defaultdict(set)          # (fonte, pid) → dias com a usina no store (varrida e com queda)
    dias_fonte = defaultdict(set)        # fonte → dias em que ela gravou
    wake_depois = set()                  # (chave da string, dia > fim) em que ela ainda amanheceu zerada
    for dia in [x for x in sorted(str_store) if x >= ini]:
        for fonte, usinas in str_store[dia].items():
            if fonte == "owen":
                continue                 # 2C vem da curva (abaixo)
            dias_fonte[fonte].add(dia)
            for pid, ent in usinas.items():
                registro[(fonte, pid)].add(dia)
                if dia > fim:
                    for e in ent.get("eventos") or []:
                        a = _hm(e.get("caiu"))
                        if a is not None and a <= DESPERTAR:
                            wake_depois.add(((fonte, pid, canon(ent.get("usina") or pid), inv_nome(e.get("inversor")),
                                              str(e.get("string"))), dia))
    for dia, fontes in mortas_curva.items():             # usina varrida pela régua nova conta como registrada
        for fonte, usinas in fontes.items():
            if dia >= ini:
                dias_fonte[fonte].add(dia)
                for pid in usinas:
                    registro[(fonte, pid)].add(dia)
    for dia in dias:
        for fonte, usinas in str_store[dia].items():
            ult, n, volt = 0, 0, Counter()
            for pid, ent in usinas.items():
                for e in ent.get("eventos") or []:
                    n += 1
                    for k in ("caiu", "voltou"):
                        v = _hm(e.get(k)) if e.get(k) else None
                        if v:
                            ult = max(ult, v)
                    if e.get("voltou"):
                        volt[str(e["voltou"])] += 1
            # retorno em massa: 100+ strings "voltando" no mesmo minuto = a telemetria voltou, não a string
            if volt and max(volt.values()) >= 100:
                massa[(dia, fonte)] = max(volt.items(), key=lambda kv: kv[1])[0]
                str_q["dia-fonte com retorno em massa (buraco de telemetria)"] += 1
            # captura parcial: o dia fechou no store com o último instante visto antes das 16:00 → foto pela metade
            if n >= 20 and ult < 16 * 60:
                parcial.add((dia, fonte))
                str_q["dia-fonte com captura parcial"] += 1

    def perda_seg(usina, inv, dia, x, y, flags):
        """(kWp da string, kWh/kWp do dia, perda, perda nominal) do trecho [x, y) do dia."""
        mins = max(0, y - x)
        kwp_inv, n_str, orig = cad_inv(usina, inv)
        if kwp_inv is None:
            flags.add("sem kWp")
            if mins > 0:
                str_q["evento sem kWp"] += 1
            return None, None, 0.0, 0.0
        if mins <= 0:
            return None, None, 0.0, 0.0
        if not n_str:
            flags.add("strings esperadas ausentes (20)")
        if orig == "ufv/n":
            flags.add("kWp da UFV ÷ N inversores")
        kwp_str = kwp_inv / (n_str or 20)
        y_ = yield_dia(usina, dia)
        if y_ is None:
            y_ = YIELD_PADRAO
            flags.add("sem geração no dia (4,5 kWh/kWp)")
        return kwp_str, y_, kwp_str * y_ * share_energia(usina, dia, x, y), kwp_str * (mins / 60.0)

    # travas: marcada à mão = MPPT sem string. O detector já as tira na hora, mas o store guarda dias de antes da
    # trava; aqui a trava de HOJE vale para o mês inteiro. Chaves do ufv_state por fonte: pv plant|idefinversor|IpvN;
    # sunop/axis plant|INV_n|I_PVn; owen cod|inv|n.
    TRANC = app._trancadas
    str_q["strings trancadas no estado (ufv_state.json)"] = len(TRANC)
    # nome de inversor comparado NORMALIZADO (sem espaço, minúsculo — o _nrm da plataforma): em 25/09 o plant_devices
    # chamava o 378276 de Indaiatuba de "INVERSOR 1.10" e a queda gravada dizia "Inversor 1.10"; pelo nome exato a
    # trava 21480|378276|Ipv18 não era conferida e 16 episódios da string trancada apareciam na aba
    SUNOP_INV_KEY = {}
    TEM_TRAVA = {k.split("|")[0] for k in TRANC}
    for k in TRANC:
        p = k.split("|")
        if len(p) == 3 and "I_PV" in p[2]:
            SUNOP_INV_KEY[(p[0], nrm(app._sunop_inv_display(p[0], p[1])))] = p[1]
    PV_INV_ID, PV_INV_NOME = {}, {}
    for pid, ent in pv_dev.items():
        nome_api = ent.get("nome_api")
        usn = nrm(ent.get("usina") or "")
        for inv_id, dev_name in (ent.get("names") or {}).items():
            disp = app.EQUIP_NAMES.get(nome_api, {}).get(dev_name) if nome_api else None
            if disp is None:
                disp = next((eq for (u, eq), c in CAD_INV_DISP.items() if u == usn and nrm(c["sup"]) == nrm(dev_name)), dev_name)
            for nome in (disp, dev_name):
                PV_INV_ID.setdefault((str(pid), nrm(nome)), str(inv_id))
            PV_INV_NOME[(str(pid), str(inv_id))] = disp

    def trancada(fonte, pid, inv_raw, string):
        """True = trancada; False = livre; None = sem de-para (não dá para conferir)."""
        if fonte == "pv":
            m = re.fullmatch(r"(?:INV-)?(\d{4,})", str(inv_raw))       # o próprio id no lugar do nome
            inv_id = m.group(1) if m else PV_INV_ID.get((str(pid), nrm(inv_raw)))
            if inv_id is None:          # sem de-para: só é dúvida se a usina tem alguma trava
                return None if str(pid) in TEM_TRAVA else False
            return app._str_trancada(str(pid), inv_id, str(string))
        if fonte in ("sunop", "axis"):
            key = SUNOP_INV_KEY.get((str(pid), nrm(inv_raw)))
            m = re.search(r"\d+", str(string))
            if key is None or not m:
                # o nome da trava sai da mesma função que nomeia a queda: inversor fora do mapa não tem trava (MAB100
                # Inv 3.9, 25/09: a usina tem UMA trava, no 2.3, e toda queda dela ficava "trava não conferida")
                return False if key is None else None
            return app._str_key(pid, key, f"I_PV{int(m.group())}") in TRANC
        if fonte == "owen":
            return app._str_key(pid, inv_raw, string) in TRANC
        return False

    # 1) SEGMENTOS de dia por string — da régua nova (curva) quando a usina-dia tem, senão das quedas gravadas
    segs = defaultdict(list)          # (fonte, pid, usina, inversor, string) → [segmento]

    def add_seg(fonte, pid, usina, dia, inv_raw, string, a, voltou, metodo):
        b = voltou if voltou is not None else fim_janela(dia)
        x, y, mins, sem_estado = intersec(a, b, usina, dia)
        if sem_estado:
            str_q["usina sem estado (janela fixa)"] += 1
        m_id = re.fullmatch(r"(?:INV-)?(\d{4,})", str(inv_raw)) if fonte == "pv" else None
        inv_disp = str(inv_raw)
        if m_id:              # o detector gravou o idefinversor no lugar do nome (plant_devices falhou na hora)
            inv_disp = PV_INV_NOME.get((str(pid), m_id.group(1)), inv_disp)
            str_q["inversor gravado pelo id → nome pelo de-para" if inv_disp != str(inv_raw) else
                  "inversor gravado pelo id sem nome no de-para"] += 1
        tv = trancada(fonte, pid, inv_raw, string)
        if tv:
            str_q["trancada: fora"] += 1
            return
        inv = inv_nome(inv_disp)
        flags = set()
        if tv is None:                # a usina tem trava e o de-para não diz qual inversor é: fica, mas avisada
            str_q["trava não conferida (sem de-para)"] += 1
            flags.add("trava não conferida (sem de-para)")
        if metodo == "store" and (dia, fonte) in parcial and voltou is None:
            flags.add("captura parcial")          # a queda "aberta" pode ser só a foto que parou
        if metodo == "store" and voltou is not None and massa.get((dia, fonte)) == _fmt(voltou):
            flags.add("retorno em massa (buraco de telemetria)")
        kwp_str, y_, perda, perda_nom = perda_seg(usina, inv, dia, x, y, flags)
        segs[(fonte, str(pid), canon(usina), inv, str(string))].append(
            {"dia": dia, "a": a, "voltou": voltou, "x": x, "y": y, "mins": mins, "kwp_str": kwp_str, "yield": y_,
             "perda": perda, "perda_nom": perda_nom, "flags": flags, "metodo": metodo})

    for dia in dias:
        for fonte, usinas in str_store[dia].items():
            if fonte == "owen":
                continue
            curva_dia = (mortas_curva.get(dia) or {}).get(fonte) or {}
            for pid, ent in usinas.items():
                if pid in curva_dia:
                    continue              # esta usina-dia tem a régua nova sobre a curva
                usina = ent.get("usina") or pid
                for e in ent.get("eventos") or []:
                    str_q["quedas gravadas lidas"] += 1
                    a = _hm(e.get("caiu"))
                    if a is None:
                        continue
                    add_seg(fonte, pid, usina, dia, e.get("inversor"), e.get("string"), a,
                            _hm(e.get("voltou")) if e.get("voltou") else None, "store")
    for dia, fontes in mortas_curva.items():
        if not (ini <= dia <= fim):
            continue
        for fonte, usinas in fontes.items():
            for pid, ent in usinas.items():
                for r in ent.get("mortas") or []:
                    for sa, sv in r.get("trechos") or []:
                        str_q["trechos da régua nova (curva)"] += 1
                        add_seg(fonte, pid, ent.get("usina") or pid, dia, r["inversor"], r["string"], _hm(sa),
                                _hm(sv) if sv else None, "curva")
    # 2C: a curva mora em disco (2C_historico) — régua nova em todos os dias. Dia fechado não muda: guarda o achado
    # (com a marca das travas, que podem mudar) e o ciclo seguinte do worker não relê 24 dias de arquivo.
    marca = hash(frozenset(TRANC))
    for dia in _dias_entre(ini, fim):
        ach = _CACHE_2C.get(dia)
        if ach is None or ach[0] != marca or dia >= hoje:
            try:
                data = (hist_2c or app._hist_build)(dia).get("strings", {})
            except Exception as e:
                log(f"[falhas] 2C {dia}: {e}")
                continue
            lst = []
            for u, invs in data.items():
                usina = app._macro_usina_nome(app._owen_nome(u)) or app._owen_nome(u)
                curvas = {inv: {sid: s for sid, s in strs.items() if app._str_key(u, inv, sid) not in TRANC}
                          for inv, strs in invs.items()}
                if any(curvas.values()):
                    lst.append((u, usina, _regua.strings_sem_corrente(curvas, zero=app.STRING_SEM_CORRENTE_A,
                                                                      piso_inv=app.STR_EV_INV_MIN_MED)))
            ach = (marca, lst)
            if dia < hoje:
                _CACHE_2C[dia] = ach
        for u, usina, mortas in ach[1]:
            dias_fonte["owen"].add(dia)
            registro[("owen", u)].add(dia)
            for r in mortas:
                for sa, sv in r["trechos"]:
                    str_q["trechos da régua nova (curva)"] += 1
                    add_seg("owen", u, usina, dia, r["inversor"], r["string"], _hm(sa), _hm(sv) if sv else None, "curva")

    # 2) EPISÓDIOS por string: aberto no fim do dia continua na próxima varredura da usina se a string amanhece
    #    zerada (caiu até 07:30). Na varredura seguinte sem ela zerada ao amanhecer = voltou de madrugada; com a usina
    #    dias fora do store = voltou entre as varreduras. Sem nenhuma notícia depois = EM ABERTO (pedido de 24/09: o dia
    #    acabou com a string nula, então continua aberta até vir informação). Dias sem varredura com a string zerada
    #    dos dois lados entram como zerados, estimados e avisados.
    def prox_registro(fonte, pid, d_ant):
        return min((x for x in registro[(fonte, pid)] if x > d_ant), default=None)

    def seg_inferido(key, g):
        fonte, pid, usina, inv, string = key
        x, y, mins, _ = intersec(JAN_INI, fim_janela(g), usina, g)
        flags = {"dias sem varredura estimados"}
        kwp_str, y_, perda, perda_nom = perda_seg(usina, inv, g, x, y, flags)
        return {"dia": g, "a": x, "voltou": None, "x": x, "y": y, "mins": mins, "kwp_str": kwp_str, "yield": y_,
                "perda": perda, "perda_nom": perda_nom, "flags": flags, "inferido": True, "metodo": "inferido"}

    str_ep, aceitos = [], []

    def fecha_str(ep, fim_txt, motivo, extra=None):
        fonte, pid, usina, inv, string = ep["key"]
        mins = sum(s_["mins"] for s_ in ep["segs"])
        if mins <= 0:
            str_q["descartado: fora do período solar"] += 1
            return
        if mins < STR_MIN_MIN:
            str_q["descartado: menos de 2 h seguidas sem corrente"] += 1
            return
        str_q["episódio: " + motivo] += 1
        flags = set().union(*(s_["flags"] for s_ in ep["segs"]))
        if extra:
            flags.add(extra)
        s0 = ep["segs"][0]
        inf = [s_ for s_ in ep["segs"] if s_.get("inferido")]
        metodos = {s_["metodo"] for s_ in ep["segs"] if s_["metodo"] != "inferido"}
        str_ep.append({"fonte": fonte, "plant_id": pid, "cliente": cliente(usina), "usina": usina, "inversor": inv, "string": string,
                       "inicio": f"{s0['dia']} {_fmt(s0['a'])}", "fim": fim_txt, "fim_motivo": motivo,
                       "d0": s0["dia"], "d1": ep["segs"][-1]["dia"], "dias": len(ep["segs"]), "dias_inferidos": len(inf),
                       "h_sol": round(mins / 60, 2),
                       "perda_kwh": round(sum(s_["perda"] for s_ in ep["segs"]), 1),
                       "perda_inferida_kwh": round(sum(s_["perda"] for s_ in inf), 1),
                       "perda_nominal_kwh": round(sum(s_["perda_nom"] for s_ in ep["segs"]), 1),
                       "kwp_string": round(next((s_["kwp_str"] for s_ in ep["segs"] if s_["kwp_str"]), 0) or 0, 2),
                       "metodo": "curva" if metodos == {"curva"} else ("quedas gravadas" if metodos == {"store"} else "misto"),
                       "flags": sorted(flags)})
        aceitos.append(ep)

    def encerra_str(ep):
        """Como termina um episódio aberto que não continuou no segmento seguinte (ou não tem segmento seguinte)."""
        fonte, pid, usina, inv, string = ep["key"]
        d_ant = ep["segs"][-1]["dia"]
        prox = _prox(d_ant)
        pr = prox_registro(fonte, pid, d_ant)            # pode ser dia depois do período: só diz se voltou
        if pr is None:
            fecha_str(ep, None, "em aberto", None if d_ant >= ult_str else f"sem registro desde {d_ant[8:10]}/{d_ant[5:7]}")
            return
        if pr > fim and (ep["key"], pr) in wake_depois:
            fecha_str(ep, None, "em aberto")             # seguia zerada na varredura seguinte, já fora do período
            return

        def nascer(dia):
            si, _sf, _est = janela_sol(usina, dia)
            return f"{dia} {_fmt(max(JAN_INI, si or JAN_INI))}"

        if pr == prox:
            fecha_str(ep, nascer(prox), "voltou de madrugada")
        elif fonte in FONTE_VARRE_TUDO and prox in dias_fonte[fonte]:
            fecha_str(ep, nascer(prox), "voltou de madrugada", "retorno inferido (usina sem queda no dia seguinte)")
        else:
            fecha_str(ep, nascer(pr), "voltou entre varreduras",
                      f"usina fora do store de {prox[8:10]}/{prox[5:7]} a {_prox(pr, -1)[8:10]}/{_prox(pr, -1)[5:7]}: "
                      "voltou em algum momento nesse meio")

    for key, lst in segs.items():
        fonte, pid = key[0], key[1]
        lst.sort(key=lambda s_: (s_["dia"], s_["a"]))
        aberto = None
        for s_ in lst:
            dia = s_["dia"]
            if aberto is not None:
                d_ant = aberto["segs"][-1]["dia"]
                pr = prox_registro(fonte, pid, d_ant)
                if dia == d_ant or (dia == pr and s_["a"] <= DESPERTAR):
                    if dia != d_ant and dia != _prox(d_ant):
                        for g in _dias_entre(_prox(d_ant), _prox(dia, -1)):   # dias sem varredura no meio
                            aberto["segs"].append(seg_inferido(key, g))
                    aberto["segs"].append(s_)                  # amanheceu zerada: mesmo episódio
                    if s_["voltou"] is not None:
                        fecha_str(aberto, f"{dia} {_fmt(s_['voltou'])}", "voltou")
                        aberto = None
                    continue
                encerra_str(aberto)                            # o anterior terminou antes deste segmento
                aberto = None
            ep = {"key": key, "segs": [s_]}
            if s_["voltou"] is not None:
                fecha_str(ep, f"{dia} {_fmt(s_['voltou'])}", "voltou")
            else:
                aberto = ep
        if aberto is not None:
            encerra_str(aberto)

    # 3) visão por INVERSOR × DIA (quantidade + strings em texto) — dos mesmos episódios: as duas somam o mesmo kWh
    por_inv = defaultdict(lambda: {"strings": set(), "min": 0, "perda": 0.0, "perda_nom": 0.0, "flags": set(),
                                   "kwp_str": None, "yield": None})
    for ep in aceitos:
        fonte, pid, usina, inv, string = ep["key"]
        for s_ in ep["segs"]:
            if s_["mins"] <= 0:
                continue
            r = por_inv[(s_["dia"], fonte, usina, inv)]
            r["strings"].add(string)
            r["min"] += s_["mins"]
            r["perda"] += s_["perda"]
            r["perda_nom"] += s_["perda_nom"]
            r["flags"] |= s_["flags"]
            r["kwp_str"] = r["kwp_str"] or s_["kwp_str"]
            r["yield"] = r["yield"] or s_["yield"]

    def _ord(s_):
        m = re.search(r"\d+", s_)
        return (int(m.group()) if m else 0, s_)

    str_rows = []
    for (dia, fonte, usina, inv), r in por_inv.items():
        strs = sorted(r["strings"], key=_ord)
        str_rows.append({"dia": dia, "fonte": fonte, "cliente": cliente(usina), "usina": usina, "inversor": inv,
                         "qtd": len(strs), "strings": ", ".join(strs), "h_sol": round(r["min"] / 60, 2),
                         "perda_kwh": round(r["perda"], 1), "perda_nominal_kwh": round(r["perda_nom"], 1),
                         "kwp_string": round(r.get("kwp_str") or 0, 2), "yield": round(r.get("yield") or 0, 2),
                         "flags": sorted(r["flags"])})
    log(f"[falhas] strings: {len(str_ep)} episódios, {len(str_rows)} linhas inversor-dia ({time.time()-t0:.0f}s)")

    # ══ TRACKERS ═════════════════════════════════════════════════════════════════════════════
    dias_t = [x for x in sorted(trk_store) if ini <= x <= fim]
    ult_trk = max((x for x in dias_t if any((e or {}).get("cobertura") for e in (trk_store[x] or {}).values())), default=fim)
    trk_q = Counter()
    serie, nomes = defaultdict(dict), {}
    for dia in dias_t:
        for pid, ent in trk_store[dia].items():
            nomes[pid] = ent.get("nome") or pid
            cls = ent.get("classes") or {}
            evs = defaultdict(list)
            for ev in ent.get("eventos") or []:
                evs[str(ev["tracker"])].append(ev)
            for trk in set(cls) | set(evs):
                serie[(pid, trk)][dia] = {"cls": (cls.get(trk) or {}).get("status"), "evs": evs.get(trk, []),
                                         "cob": ent.get("cobertura", 0)}
    # frota vista pela plataforma no store inteiro — só para saber se a usina tem trackers (o nº dela NÃO serve de
    # divisor: o store só lista tracker com anomalia; ver o kWp típico abaixo)
    frota_store = defaultdict(set)
    for _dia, _ents in trk_store.items():
        for _pid, _e in _ents.items():
            frota_store[_pid].update((_e.get("classes") or {}).keys())
            frota_store[_pid].update(str(x["tracker"]) for x in (_e.get("eventos") or []))

    def fonte_de(pid):
        if pid.isdigit():
            return "pv" if len(pid) > 5 else "pg"
        return "owen" if len(pid) <= 3 else "sunop"

    def inversor_de(pid, trk):
        return app._bd_trk_lookup(nomes.get(pid, ""), app._trk_id_num(trk))

    def kwp_cadastro(pid, trk, inversor):
        usina = nomes.get(pid, "")
        usn = app._nome_base(usina)
        kwp_inv, _, _orig = cad_inv(canon(usina), inversor or "")
        n = len((app.INV_TRK.get(usn) or {}).get(nrm(inversor or ""), []) or [])
        if kwp_inv and inversor and n:
            return kwp_inv / n, "inversor ÷ trackers do inversor"
        uc = nrm(canon(usina))
        tot = len(app.BD_TRK_INV.get(usn) or {}) or IG_TRK.get(uc) or IG_TRK.get(nrm(usina)) or 0
        origem = "UFV ÷ trackers da usina"
        if not tot and len(frota_store.get(pid) or ()) >= 5:
            tot, origem = len(frota_store[pid]), "UFV ÷ frota vista no store"
        ufv = CAD_UFV.get(uc) or {}
        kwp_u = ufv.get("kwp") or IG_KWP.get(uc) or IG_KWP.get(nrm(usina))
        if kwp_u and tot:
            return kwp_u / tot, origem
        return None, "sem kWp"

    # kWp típico de um tracker MEDIDO no cadastro (kWp do inversor ÷ trackers do inversor). Achado de 24/09: dividir a
    # UFV pelos trackers "vistos no store" inflava ~10× (Guatambu TRK1: 678 kWp e 27 MWh num episódio). Sem contagem
    # de frota no cadastro vale o típico, e kWp acima do teto (P95 medido, no mínimo 2× o típico) também.
    med = sorted(k for k, o in (kwp_cadastro(p_, t_, inversor_de(p_, t_)) for (p_, t_) in serie)
                 if k and o == "inversor ÷ trackers do inversor")
    KWP_TIPICO = med[len(med) // 2] if med else 50.0
    KWP_TETO = max(2 * KWP_TIPICO, med[int(len(med) * 0.95)] if med else 0)

    def kwp_tracker(pid, trk, inversor):
        k, o = kwp_cadastro(pid, trk, inversor)
        if k is None:
            return None, o
        if o == "UFV ÷ frota vista no store":
            trk_q["kWp: frota vista no store → tracker típico"] += 1
            return KWP_TIPICO, f"tracker típico da carteira ({KWP_TIPICO:.0f} kWp)"
        if k > KWP_TETO:
            trk_q["kWp acima do teto → tracker típico"] += 1
            return KWP_TIPICO, f"kWp implausível ({k:.0f}) → típico ({KWP_TIPICO:.0f} kWp)"
        return k, o

    # crônico = o book da plataforma diz que o tracker já estava parado ANTES do período
    antes = set()
    for _f, _ent in (book or {}).items():
        for r in _ent.get("rows") or []:
            if str(r.get("inicio") or "") < ini and (r.get("aberta") or str(r.get("fim") or "") >= ini):
                antes.add((r.get("usina"), str(r.get("tracker"))))

    trk_rows = []
    for (pid, trk), por_dia in serie.items():
        usina = nomes.get(pid, "")
        usina_c = canon(usina)
        fonte = fonte_de(pid)
        aberto = None

        def fecha(ep, fim_dia, fim_min, motivo, fim_txt=None, extra=None, pid=pid, trk=trk, usina_c=usina_c, fonte=fonte):
            """fim_txt = só a DATA da volta, quando o registro não guarda a hora (voltou num dia que a régua não viu)."""
            inversor = inversor_de(pid, trk)
            kwp_t, orig = kwp_tracker(pid, trk, inversor)
            desv = max([v for v in ep["desvios"] if v is not None], default=None)
            if desv is not None and desv < 2.0:
                # "parado" na posição certa o episódio todo: não é falha e não perde energia (Santa Bárbara I,
                # 24/09 16:50: 52 trackers com desvio 0,0° — a régua marca parado porque não se moveram no fim da tarde)
                trk_q["descartado: no alvo o episódio todo (desvio < 2°)"] += 1
                return
            fator = (1 - math.cos(math.radians(min(desv, 90)))) if desv is not None else FATOR_TRK_PADRAO
            perda, hs = 0.0, 0.0
            flags = {motivo} if motivo else set()
            if extra:
                flags.add(extra)
            if kwp_t is None:
                flags.add("sem kWp")
            elif orig != "inversor ÷ trackers do inversor":
                flags.add("kWp: " + orig)
            if desv is None:
                flags.add("sem ângulo (fator 25%)")
            if not inversor:
                flags.add("sem inversor no BD_Trackers")
            for dd, x, y in ep["dias"]:
                mins = max(0, y - x)
                hs += mins / 60
                if kwp_t:
                    y_ = yield_dia(usina_c, dd)
                    if y_ is None:
                        y_ = YIELD_PADRAO
                        flags.add("sem geração no dia (4,5 kWh/kWp)")
                    perda += kwp_t * y_ * (mins / 60) / (h_sol_dia(usina_c, dd) or 12.0) * fator
            if hs * 60 < 30:
                trk_q["descartado: < 30 min na janela solar"] += 1
                return
            trk_rows.append({"fonte": fonte, "plant_id": pid, "cliente": cliente(usina_c), "usina": usina_c, "tracker": trk,
                             "inversor": inversor or "", "inicio": f"{ep['ini_dia']} {_fmt(ep['ini_min'])}",
                             "fim": fim_txt or (f"{fim_dia} {_fmt(fim_min)}" if fim_min is not None else None),
                             "h_sol": round(hs, 2), "desvio_pico": desv, "fator": round(fator, 3),
                             "kwp_tracker": round(kwp_t or 0, 2), "perda_kwh": round(perda, 1),
                             "cronico": (usina_c, trk) in antes and ep["ini_dia"] <= ini,
                             "flags": sorted(flags)})

        def ddmm(d):
            return f"{d[8:10]}/{d[5:7]}"

        for dia in dias_t:
            info = por_dia.get(dia)
            if info is None:
                # a usina tem leitura no dia e o tracker não entrou em classe nenhuma: a régua não o viu parado — ele
                # voltou nesse dia, numa hora que o registro não guarda (MAB200 Tracker 103, 25/09: parado de 05 a
                # 08/09, a tela dizia "voltou 08/09 17:38"; na curva ele voltou em 09/09, entre 16:45 e 17:00)
                u = (trk_store.get(dia) or {}).get(pid) or {}
                if aberto is not None and (u.get("cobertura") or 0) > 0:
                    trk_q["fechado: voltou num dia sem parada (hora não registrada)"] += 1
                    fecha(aberto, None, None, f"voltou em {ddmm(dia)} (hora não registrada)", fim_txt=dia)
                    aberto = None
                continue
            if info["cob"] == 0:
                continue                                  # a usina não leu nada no dia: atravessa (regra da base)
            parado = info["cls"] == "parado"
            evs = sorted(info["evs"], key=lambda e: _hm(e.get("parada")) or 0)
            if aberto is not None and not parado:
                # A RÉGUA DO LEVI: começou parado e no dia seguinte a plataforma o classifica como severo/médio/leve
                # (ou normal) → saiu da visão de parados, nesse dia, em hora que o registro não guarda
                trk_q["fechado: virou " + str(info["cls"] or "normal")] += 1
                fecha(aberto, None, None, "saiu: " + str(info["cls"] or "normal"), fim_txt=dia)
                aberto = None
            if not parado:
                continue
            if not evs:
                # classe "parado" sem evento no dia (amplitude baixa, sem onset achado): o dia inteiro conta parado
                evs = [{"parada": _fmt(JAN_INI), "retorno": None, "desvio": None}]
            for ev in evs:
                a = _hm(ev.get("parada"))
                b = _hm(ev.get("retorno")) if ev.get("retorno") else None
                if a is None:
                    continue
                if aberto is not None:
                    # episódio vindo de trás: a parada da manhã (≤ 09:00) é continuação; se voltou hoje, fecha no retorno
                    if a <= 9 * 60 and b is None:
                        x, y, _m, _ = intersec(a, fim_janela(dia), usina_c, dia)
                        aberto["dias"].append((dia, x, y))
                        aberto["desvios"].append(ev.get("desvio"))
                        continue
                    if a <= 9 * 60 and b is not None:
                        x, y, _m, _ = intersec(a, b, usina_c, dia)
                        aberto["dias"].append((dia, x, y))
                        aberto["desvios"].append(ev.get("desvio"))
                        trk_q["fechado: voltou a girar"] += 1
                        fecha(aberto, dia, y, None)
                        aberto = None
                        continue
                    # parada nova depois das 09:00: ele se mexeu de manhã (hora não registrada) e parou de novo
                    trk_q["fechado: voltou e parou de novo no mesmo dia"] += 1
                    fecha(aberto, None, None, f"voltou em {ddmm(dia)} e parou de novo às {_fmt(a)}", fim_txt=dia)
                    aberto = None
                x, y, _m, _ = intersec(a, b if b is not None else fim_janela(dia), usina_c, dia)
                ep = {"ini_dia": dia, "ini_min": x, "dias": [(dia, x, y)], "desvios": [ev.get("desvio")]}
                if b is None:
                    aberto = ep
                else:
                    trk_q["fechado: voltou a girar"] += 1
                    fecha(ep, dia, y, None)
        if aberto is not None:
            if aberto["dias"][-1][0] >= ult_trk:
                trk_q["em aberto no fim do período"] += 1
                fecha(aberto, None, None, "em aberto")
            else:
                # a usina não leu mais nada depois do último dia parado: sem notícia, segue em aberto (a regra das strings)
                trk_q["em aberto: sem dado da usina depois"] += 1
                fecha(aberto, None, None, "em aberto", extra=f"sem dado da usina desde {ddmm(aberto['dias'][-1][0])}")
    log(f"[falhas] trackers: {len(trk_rows)} episódios ({time.time()-t0:.0f}s)")

    def resumo(rows, chave):
        agg = defaultdict(lambda: {"n": 0, "kwh": 0.0, "h": 0.0})
        for r in rows:
            a = agg[r[chave] or "—"]
            a["n"] += 1
            a["kwh"] += r["perda_kwh"]
            a["h"] += r["h_sol"]
        return sorted(({"k": k, **v} for k, v in agg.items()), key=lambda x: -x["kwh"])

    return {"periodo": [ini, fim], "gerado_em": agora.strftime("%Y-%m-%d %H:%M"),
            "strings": {"rows": str_rows, "episodios": str_ep, "qualidade": dict(str_q),
                        "por_cliente": resumo(str_rows, "cliente")[:12], "por_usina": resumo(str_rows, "usina")[:25],
                        "parcial": sorted(list(x) for x in parcial), "massa": {f"{d_}|{f_}": v for (d_, f_), v in massa.items()}},
            "trackers": {"rows": trk_rows, "qualidade": dict(trk_q), "por_cliente": resumo(trk_rows, "cliente")[:12],
                         "por_usina": resumo(trk_rows, "usina")[:25]},
            "regua": {"sol_min_graus": SOL_MIN, "janela": "06–18h ∩ sol ≥ 8° no estado",
                      "janela_strings": "06–18h, 2 h seguidas sem corrente com o inversor gerando (≥ 12% do pico); "
                                        "perda ponderada pela altura do sol",
                      "min_minutos": STR_MIN_MIN, "kwp_trk_tipico": round(KWP_TIPICO, 1), "yield_padrao": YIELD_PADRAO,
                      "fator_tracker": "1 − cos(desvio de pico ao alvo); 25% sem ângulo"}}
