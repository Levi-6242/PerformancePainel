# -*- coding: utf-8 -*-
"""
_trk_analise_dia — traducao da metodologia docs/metodologia-analise-trackers.md
(secoes 3.3 a 3.8) para Python puro. Funcao pura, sem estado, sem IO.

Classifica cada tracker de uma usina num dia em:
    PARADO | DESVIO SEVERO | DESVIO LEVE | NORMAL
detectando OCORRENCIAS de congelamento (freeze) validadas pelo MOVIMENTO da
mediana da frota (passo 3.5, o que separa freeze real de batente compartilhado).
"""

import re
import json

# ---------------------------------------------------------------- 1. Parametros
TOL = 2.0            # graus. Banda de congelamento E limiar de movimento da mediana.
JANELA_INI = 360     # 06:00
JANELA_FIM = 1080    # 18:00
MIN_OCC = 15         # min. Duracao minima p/ virar ocorrencia (piso do leve).
SEVERO_MIN = 30      # min. >=30 -> severo ; 15..29 -> leve
ZERO_EPS = 0.05      # |v| < isto = zero (comunicacao morta)
DEV_MIN = 13.0       # graus. Desvio MAX do tracker vs mediana da frota DURANTE a
                     # janela p/ a ocorrencia ser real (3.5 = frota moveu, este nao).
                     # Calibra freeze-mid-curso/preso-longo (>=13) vs parada leve
                     # no batente / release atrasado (<13).
# --- causa raiz (3.8) ---
CLU_ONSET_TOL = 20   # min. Trackers que congelam no MESMO evento comecam dentro
                     # desta folga (uma parada de controlador/string congela cada
                     # tracker no angulo em que estava -> mesmo INSTANTE, angulos
                     # diferentes; agrupa-se por onset, nao por valor identico).
CLU_ANG_TOL = 12.0   # graus. Guarda p/ nao fundir eventos distintos no mesmo
                     # instante (ex.: batente +54 vs freeze -30).


# ---------------------------------------------------------------- 2. Helpers
def min_do_dia(x):
    """Minuto-do-dia local (0..1439). Aceita ISO ou HH:MM; pega o 1o HH:MM."""
    m = re.search(r"(\d{1,2}):(\d{2})", str(x))
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _serie_dia(pts):
    """TODOS os pontos do dia (madrugada inclusa), (t,y) ordenados por t."""
    out = []
    for p in (pts or []):
        y = p.get("y")
        t = min_do_dia(p.get("x"))
        if isinstance(y, (int, float)) and t is not None:
            out.append((t, float(y)))
    out.sort(key=lambda tv: tv[0])
    return out


def _serie_janela(pts, jini, jfim):
    """Pontos dentro de [jini, jfim], (t,y) ordenados por t."""
    return [(t, y) for (t, y) in _serie_dia(pts) if jini <= t <= jfim]


def _valor_no_tempo(serie, t):
    """Angulo do tracker no instante t, interpolando linearmente.
    serie = lista (t,y) ordenada. Retorna None se t fora do alcance amostrado."""
    if not serie:
        return None
    if t < serie[0][0] or t > serie[-1][0]:
        return None
    # busca amostra exata ou par que cerca t
    prev = None
    for (tt, yy) in serie:
        if tt == t:
            return yy
        if tt > t:
            if prev is None:
                return None
            t0, y0 = prev
            t1, y1 = tt, yy
            if t1 == t0:
                return y0
            return y0 + (y1 - y0) * (t - t0) / (t1 - t0)
        prev = (tt, yy)
    return None


def _mediana(vals):
    v = sorted(vals)
    n = len(v)
    if n == 0:
        return None
    if n % 2:
        return v[n // 2]
    return (v[n // 2 - 1] + v[n // 2]) / 2.0


# ---------------------------------------------------------------- 3.3 Passo A
def _passo_a_trivial(serie_dia):
    """Casos triviais 3.3 (dia inteiro). Retorna dict-resultado se PARADO,
    senao None (segue para B)."""
    ys = [y for (_, y) in serie_dia]
    if not ys:
        return {"classe": "parado", "motivo_parado": "comunicacao_morta",
                "travado_em": None}
    mn, mx = min(ys), max(ys)
    # (a) comunicacao morta: min==max==0
    if abs(mn) < ZERO_EPS and abs(mx) < ZERO_EPS:
        return {"classe": "parado", "motivo_parado": "comunicacao_morta",
                "travado_em": None}
    # (b) travado desde antes da meia-noite: variacao total do dia < TOL
    if (mx - mn) < TOL:
        return {"classe": "parado", "motivo_parado": "travado_antes_meia_noite",
                "travado_em": round(mn, 2)}
    return None


# ---------------------------------------------------------------- 3.4 Passo B
def _passo_b_candidatas(S, tol):
    """Deteccao de congelamento por banda TOL, ancora fixa em S[i].
    S = serie_janela [(t,y)]. Retorna candidatas com j_idx."""
    n = len(S)
    cand = []
    i = 0
    while i < n:
        j = i
        while (j + 1 < n) and (abs(S[j + 1][1] - S[i][1]) <= tol):
            j += 1
        inicio = S[i][0]
        fim = S[j][0]
        dur = fim - inicio
        if dur >= MIN_OCC:
            cand.append({"inicio": inicio, "fim": fim, "valor": S[i][1],
                         "i_idx": i, "j_idx": j})
        i = j + 1
    return cand


def _pausa_de_transicao(S, c):
    """True se a candidata curta e uma PAUSA momentanea na transicao de batente
    (dessincronia de timing benigna), nao um freeze real.

    Assinatura: o tracker chega ao valor congelado por UM lado e sai pelo MESMO
    lado (passa monotonicamente pelo valor) -> so demorou um pouco mais na
    rampa. Um freeze real reverte/estaciona (sai pelo lado oposto, ou nao sai).
    So se aplica a ocorrencias curtas (dur < SEVERO_MIN); freezes longos contam
    sempre.
    """
    i, j = c["i_idx"], c["j_idx"]
    if i - 1 < 0 or j + 1 >= len(S):
        return False                     # sem vizinho -> nao da pra afirmar
    aprox = S[i][1] - S[i - 1][1]        # direcao de chegada
    parte = S[j + 1][1] - S[j][1]        # direcao de saida
    return (aprox > 0 and parte > 0) or (aprox < 0 and parte < 0)


# ---------------------------------------------------------------- 3.8 buckets
def _bucket_valor(v, tol):
    return round(v / tol) * tol


# ---------------------------------------------------------------- funcao pura
def _trk_analise_dia(grafico, jini=JANELA_INI, jfim=JANELA_FIM, tol=TOL):
    # series por tracker
    serie_dia = {tid: _serie_dia(pts) for tid, pts in grafico.items()}
    serie_jan = {tid: _serie_janela(pts, jini, jfim) for tid, pts in grafico.items()}

    resultado = {}

    # ---- Passo A (3.3) para TODOS ----
    parados = {}
    for tid in grafico:
        r = _passo_a_trivial(serie_dia[tid])
        if r is not None:
            parados[tid] = r
            resultado[tid] = {
                "classe": r["classe"],
                "motivo": r["motivo_parado"],
                "ocorrencias": [],
                "travado_em": r["travado_em"],
                "causa_grupo": None,
            }

    # ---- FLEET_ATIVA + mediana da frota (3.5 base) ----
    fleet_ativa = {tid: serie_jan[tid] for tid in grafico if tid not in parados}

    def mediana_frota(t):
        vals = []
        for s in fleet_ativa.values():
            v = _valor_no_tempo(s, t)
            if v is not None:
                vals.append(v)
        if not vals:
            return None
        return _mediana(vals)

    # ---- FIM_DADOS (3.6) = maior minuto observado na usina ----
    fim_dados = 0
    for s in serie_dia.values():
        if s:
            fim_dados = max(fim_dados, s[-1][0])

    # ---- Passos B->C->D->E por tracker nao-parado ----
    ocs_por_tracker = {}
    for tid in grafico:
        if tid in parados:
            continue
        S = serie_jan[tid]
        n = len(S)

        # B: candidatas
        candidatas = _passo_b_candidatas(S, tol)

        # C (3.5): validacao por MOVIMENTO da frota RELATIVO ao tracker.
        #   O tracker esta congelado num valor fixo (c.valor). Se a frota se
        #   afastou dele (mediana passou a divergir >= DEV_MIN em algum instante
        #   da janela) => a frota se moveu e este nao => ocorrencia REAL.
        #   Se a mediana ficou junto do tracker o tempo todo (|dev| < DEV_MIN)
        #   => batente/posicao compartilhada legitima => DESCARTA.
        #   (O endpoint-delta |m2-m1| do PDF nao separa: freezes de tarde tem
        #    m1~=m2 pois a frota volta ao mesmo angulo; usa-se o desvio maximo.)
        reais = []
        for c in candidatas:
            devmax = 0.0
            cobre = False
            t = c["inicio"]
            while t <= c["fim"]:
                mf = mediana_frota(t)
                if mf is not None:
                    cobre = True
                    d = abs(mf - c["valor"])
                    if d > devmax:
                        devmax = d
                t += 5
            if not cobre:
                reais.append(c)            # §4-B: sem referencia -> conservador
                continue
            if devmax >= DEV_MIN:
                reais.append(c)

        # D (3.6): fechamento
        ocorrencias = []
        for c in reais:
            toca_fim = (c["j_idx"] == n - 1)
            if not toca_fim:
                status = "recuperou"
                nota = None
                fim = c["fim"]
            else:
                if fim_dados >= jfim:
                    fim = jfim
                    status = "nao_retomou_18h"
                    nota = "[NAO RETOMOU ATE 18:00]"
                else:
                    fim = fim_dados
                    status = "aberto_dado_insuficiente"
                    nota = "[EM ABERTO - DADO INSUFICIENTE]"
            dur = fim - c["inicio"]
            # descarta pausa de transicao de batente (dessincronia benigna):
            # so afeta ocorrencias curtas; freeze longo (>= SEVERO_MIN) conta sempre.
            if dur < SEVERO_MIN and _pausa_de_transicao(S, c):
                continue
            sev = "severo" if dur >= SEVERO_MIN else "leve"
            ocorrencias.append({
                # chaves do contrato (task): ini/fim/dur_min/valor
                "ini": c["inicio"], "fim": fim,
                "dur_min": dur, "valor": round(c["valor"], 2),
                # campos ricos da SPEC (3.6/3.7), mantidos como bonus
                "severidade": sev, "status": status, "nota": nota,
            })

        # E (3.7): classe
        tem_sev = any(o["severidade"] == "severo" for o in ocorrencias)
        tem_leve = any(o["severidade"] == "leve" for o in ocorrencias)
        if tem_sev:
            classe = "severo"
        elif tem_leve:
            classe = "leve"
        else:
            classe = "normal"

        resultado[tid] = {
            "classe": classe,
            "motivo": None,
            "ocorrencias": ocorrencias,
            "travado_em": None,
            "causa_grupo": None,
        }
        ocs_por_tracker[tid] = ocorrencias

    # ---- Passo F (3.8): agrupamento por causa raiz ----
    ocs_all = []
    for tid, ocs in ocs_por_tracker.items():
        for o in ocs:
            ocs_all.append({"tid": tid, "inicio": o["ini"], "valor": o["valor"]})
    ocs_all.sort(key=lambda o: o["inicio"])

    # Agrupa por ONSET (mesmo instante de falha). Uma parada de controlador/
    # string congela seus trackers no angulo em que cada um estava -> mesmo
    # tempo, angulos diferentes. Por isso a chave e o instante (+/- CLU_ONSET_TOL);
    # o valor entra so como guarda (CLU_ANG_TOL) contra fundir eventos distintos
    # no mesmo minuto. Ancora = 1o membro do grupo (determinismo).
    grupos = []
    for oc in ocs_all:
        colocado = False
        for g in grupos:
            anc = g["membros"][0]
            if abs(oc["inicio"] - anc["inicio"]) <= CLU_ONSET_TOL and \
               abs(oc["valor"] - anc["valor"]) <= CLU_ANG_TOL:
                g["membros"].append(oc)
                colocado = True
                break
        if not colocado:
            grupos.append({"id": "CLUSTER_%d" % (len(grupos) + 1), "membros": [oc]})

    # atribuicao: tracker pode estar em varios; usar grupo com mais membros
    melhor = {}  # tid -> (n_membros, -inicio, grupo_id)
    for g in grupos:
        if len(g["membros"]) < 2:
            continue
        gid = g["id"]
        nm = len(g["membros"])
        ini_g = min(m["inicio"] for m in g["membros"])
        for m in g["membros"]:
            tid = m["tid"]
            chave = (nm, -ini_g)
            if tid not in melhor or chave > melhor[tid][0]:
                melhor[tid] = (chave, gid)
    for tid, (_, gid) in melhor.items():
        resultado[tid]["causa_grupo"] = gid

    # ---- resumo ----
    parado_n = severo_n = leve_n = normal_n = 0
    for r in resultado.values():
        c = r["classe"]
        if c == "parado":
            parado_n += 1
        elif c == "severo":
            severo_n += 1
        elif c == "leve":
            leve_n += 1
        else:
            normal_n += 1

    clusters = []
    for g in grupos:
        if len(g["membros"]) < 2:
            continue
        ini_g = min(m["inicio"] for m in g["membros"])
        val_g = _mediana([m["valor"] for m in g["membros"]])
        clusters.append({
            "id": g["id"],
            "ini": ini_g,
            "valor": round(val_g, 1),
            "trackers": sorted(set(m["tid"] for m in g["membros"])),
        })

    resultado["__resumo__"] = {
        "parado": parado_n, "severo": severo_n, "leve": leve_n,
        "normal": normal_n, "clusters": clusters,
    }
    return resultado


# ---------------------------------------------------------------- main / validacao
def _hhmm(mn):
    return "%02d:%02d" % (int(mn) // 60, int(mn) % 60) if mn is not None else "-"


if __name__ == "__main__":
    RAW = (r"C:/Users/Levi Maia/OneDrive - GRID CO/Área de Trabalho/temp/"
           r"Projeto API PV/tests/fixtures/trackers/sunop__mab200__2026-07-09.raw.json")
    raiz = json.load(open(RAW, encoding="utf-8"))
    grafico = raiz["grafico"]

    res = _trk_analise_dia(grafico)
    resumo = res.pop("__resumo__")

    ESP = {"parado": 10, "severo": 7, "normal": 133}

    print("=== CONTAGENS ===")
    print("            OBTIDO   ESPERADO")
    print("parado      %6d   %6d" % (resumo["parado"], ESP["parado"]))
    print("severo      %6d   %6d" % (resumo["severo"], ESP["severo"]))
    print("leve        %6d   %6s" % (resumo["leve"], "-"))
    print("normal      %6d   %6d" % (resumo["normal"], ESP["normal"]))

    print("\n=== PARADOS (classe/motivo/travado_em) ===")
    for tid in sorted(res, key=lambda t: (int(re.search(r'\d+', t).group()))):
        r = res[tid]
        if r["classe"] == "parado":
            print("  %-8s %-8s %-24s travado_em=%s" %
                  (tid, "morta" if r["motivo"] == "comunicacao_morta" else "mec",
                   r["motivo"], r["travado_em"]))

    print("\n=== SEVERO (freeze que a regua de curso PERDE) ===")
    for tid in sorted(res, key=lambda t: (int(re.search(r'\d+', t).group()))):
        r = res[tid]
        if r["classe"] == "severo":
            pico = max(r["ocorrencias"], key=lambda o: o["dur_min"])
            print("  %-8s freeze %s->%s val=%.1f dur=%d %s cg=%s" %
                  (tid, _hhmm(pico["ini"]), _hhmm(pico["fim"]),
                   pico["valor"], pico["dur_min"], pico["severidade"],
                   r["causa_grupo"]))

    print("\n=== CLUSTERS (causa compartilhada = travam JUNTOS) ===")
    for c in resumo["clusters"]:
        print("  %s @%s val~%.1f : %s" %
              (c["id"], _hhmm(c["ini"]), c["valor"], c["trackers"]))
    print("  (gab correlacao_evento: TRK_3/4/5; TRK_1/2 caem no MESMO evento")
    print("   geometrico - separacao fina 3/4/5 vs 1/2 e por TOPOLOGIA de ID)")

    esp_parado = ["TRK_81", "TRK_87", "TRK_106", "TRK_122",
                  "TRK_9", "TRK_12", "TRK_42", "TRK_91", "TRK_93", "TRK_95"]
    esp_severo = ["TRK_3", "TRK_4", "TRK_5", "TRK_1", "TRK_2", "TRK_35", "TRK_149"]

    got_parado = sorted([t for t in res if res[t]["classe"] == "parado"],
                        key=lambda t: int(re.search(r'\d+', t).group()))
    got_severo = sorted([t for t in res if res[t]["classe"] == "severo"],
                        key=lambda t: int(re.search(r'\d+', t).group()))

    print("\n=== DIFF vs GABARITO ===")
    print("parado faltando :", sorted(set(esp_parado) - set(got_parado)))
    print("parado a mais   :", sorted(set(got_parado) - set(esp_parado)))
    print("severo faltando :", sorted(set(esp_severo) - set(got_severo)))
    print("severo a mais   :", sorted(set(got_severo) - set(esp_severo)))

    # cluster: 3/4/5 (correlacao_evento do gab) devem cair juntos num cluster
    cg = res["TRK_3"]["causa_grupo"]
    cluster_ok = (cg is not None and
                  res["TRK_4"]["causa_grupo"] == cg and
                  res["TRK_5"]["causa_grupo"] == cg)
    print("cluster 3/4/5 juntos :", cluster_ok, "(%s)" % cg)

    bateu = (resumo["parado"] == ESP["parado"] and
             resumo["severo"] == ESP["severo"] and
             resumo["normal"] == ESP["normal"] and
             set(got_parado) == set(esp_parado) and
             set(got_severo) == set(esp_severo) and
             cluster_ok)
    print("\nBATEU GABARITO:", bateu)
