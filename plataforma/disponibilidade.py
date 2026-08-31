# -*- coding: utf-8 -*-
"""Disponibilidade por OS do Fracttal × estrutura do BD_Performance (aba Equipamentos).

Módulo PURO (sem Flask, sem rede, sem arquivo): o app.py injeta as work orders varridas e o
catálogo de equipamentos; os testes injetam fixtures. Réguas fechadas com o Levi em 25-26/08/26
na análise que virou `Disponibilidade Fracttal x BD - agosto 2026.xlsx`:

- Contam OSs com tipo de tarefa Religamento / Religamento Remoto / Corretiva Emergencial;
  canceladas NUNCA contam.
- Início = event_date (ou date_maintenance). Fim = final_date da tarefa. `wo_final_date` é
  carimbo administrativo da WO (uma revisão em massa em 25/08 re-carimbou dezenas p/ o mesmo
  minuto) — só entra como último recurso, com flag. Religamento-relâmpago com final_date
  minutos ANTES do event_date = carimbo → duração 0.
- OS ABERTA sem fim = 0h no cálculo + cenário à parte (Mandaguaçu/Céu Azul provaram: usina
  gerando com OS "parada" esquecida aberta).
- Escopo pelo ATIVO da OS (code): raiz do site → usina inteira; CABN/SKID/QGBT/PECN/DTRF N →
  cabine (UG) N; INVR/DINV N[.M] → inversor. Sites que agrupam 2+ usinas tentam pista na
  descrição; sem pista, valem para o grupo (flag).
- Janela solar 06–18h, dia a dia, em horas e minutos; sobreposições não passam de 100% da
  usina (hierarquia usina > cabine > inversor). Perda = kWp afetado × horas (potência nominal).
"""
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta

# DUAS FAMÍLIAS por ORIGEM da falha (metodologia da Ana Patrícia, reunião 29/08). A conta é a
# mesma nas duas — potência do equipamento × tempo de indisponibilidade —, o que muda é a
# classificação: QUEDA tem origem externa (rede/concessionária) e EQUIPAMENTO é falha física
# nossa ("tem disponibilidade elétrica mas não tem disponibilidade física"). O total continua
# sendo o número oficial; as famílias são a DECOMPOSIÇÃO dele e NÃO somam exatamente, porque
# um evento de cada tipo no mesmo horário é capado em 100% no total e contado nos dois recortes.
# ── Parada-fantasma por fechamento tardio de OS ──────────────────────────────
# Caso real (30/08): OSs velhas fechadas EM LOTE em 27-28/08 ganharam final_date de "agora" e
# viraram paradas de semanas. A OS 8891 dizia Parelhas parada de 03/07 a 28/08 enquanto a usina
# gerava 13.111 kWh/dia, todos os dias. O Fracttal não ajuda a separar (`stop_assets` é False em
# TODAS as 2.596 tarefas-alvo; `real_stop_assets_sec` só repete evento→fim), então o juiz é a
# GERAÇÃO: dia em que a usina produziu de verdade não foi dia de usina parada.
# Só vale para OS LONGA e de escopo USINA INTEIRA — OS curta é confiável e evento de cabine ou
# inversor não deve zerar por a usina ter gerado com o resto dos equipamentos.
# A conferência compara o que a OS AFIRMA com o que a usina PRODUZIU. Se a OS diz que uma
# fração `f` da usina estava parada, a geração esperada é (1-f) do normal. Gerou muito acima
# disso? Então havia mais capacidade rodando do que a OS afirma, e o dia não foi de parada.
# Assim a régua vale para qualquer nível: pegou Parelhas (f=1, gerando pleno) e Junco (f=0,5,
# gerando pleno) sem exonerar um inversor real parado (f=0,05 → a usina gera 95%, coerente).
# A conferência é POR DIA, pela fatia do dia que a OS afirma perdida — não pela duração da OS.
# Amarrar à duração deixava passar o caso Marialva: religamentos abertos num dia e fechados no
# mesmo horário do seguinte comiam o dia solar inteiro, com a usina gerando 4,97 kWh/kWp (perto
# do máximo dela), e como duravam "só" 1 dia nem eram conferidos.
GER_TOLERANCIA = 0.15        # folga sobre o esperado (clima, sujeira, medição)
# O piso ABSOLUTO se aplica ao PATAMAR da usina no período (o P75), não ao dia. Aplicá-lo dia a
# dia punia dia nublado, que não prova nem desmente nada — Parelhas, com dias entre 3,5 e 6,
# perdia metade da exoneração por causa de nuvem. Já o patamar precisa dele: sem esse piso, uma
# usina com metade parada o mês inteiro faria o próprio nível reduzido virar o "normal" e toda
# parada real seria exonerada. 4,5 kWh/kWp é usina praticamente plena (o típico vai de 3,5 a 5,5).
GER_PLENO_KWH_KWP = 4.5
# Abaixo desta fatia do DIA afirmada perdida, a geração NÃO tem resolução para desmentir a OS:
# um inversor de 20 fora muda ~5% da produção, e meia hora de parada muda 4% — ambos se perdem
# no ruído do clima. Não se tenta.
GER_FRAC_MIN = 0.30

TIPOS_QUEDA = {"religamento", "religamento remoto"}
# 'Corretiva' simples ficou DE FORA (decisão do Levi, 29/08: "esquece por enquanto, vamos pensar
# em algo melhor"). Medido antes de decidir: entrariam 1.933 tarefas e o bucket cairia de 99,5%
# para 93,7% — grosso demais, porque boa parte é trabalho programado SEM equipamento parado. O
# critério melhor provavelmente não é o TIPO da tarefa, e sim se houve parada de fato.
TIPOS_EQUIP = {"corretiva emergencial"}
TIPOS_ALVO = TIPOS_QUEDA | TIPOS_EQUIP
SOL_INI_H, SOL_FIM_H = 6, 18
SUF_CABINE = ("CABN", "SKID", "QGBT", "PECN", "DTRF")
# linha agregada que convive com as filhas numeradas no BD — no parque ela duplicaria o kWp
PARQUE_EXCLUI = {"AP. do Taboado"}

_ROM = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6", "VII": "7",
        "VIII": "8", "IX": "9", "X": "10", "XI": "11", "XII": "12",
        "IA": "1A", "IB": "1B", "IIA": "2A", "IIB": "2B"}


def _txt(v):
    """Texto de célula de planilha, à prova de NaN. O pandas devolve `float('nan')` para célula
    vazia, e **NaN é TRUTHY em Python** — então `str(v or "")` virava a string "nan". Foi assim
    que 7 usinas SEM 'Usina Fractall' passaram no filtro do parque (fracttal="nan") e ficavam
    com 100% eterno, sem nenhuma OS podendo alcançá-las. Vazio tem de continuar vazio."""
    if v is None:
        return ""
    if isinstance(v, float) and v != v:                    # NaN
        return ""
    return str(v).strip()


def norm(s):
    s = unicodedata.normalize("NFD", _txt(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().upper()


def norm2(s):
    """norm + romanos→arábicos por token ('Ouro Branco II' ≡ 'Ouro Branco 2')."""
    return " ".join(_ROM.get(p, p) for p in norm(s).split(" "))


def dt_frac(s):
    """ISO do Fracttal (na prática UTC com offset) → datetime local (America/Sao_Paulo, -3)."""
    if not s:
        return None
    t = str(s).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})", t)
    if not m:
        return None
    d = datetime(*[int(x) for x in m.groups()])
    off = re.search(r"([+-])(\d{2}):?(\d{2})$", t)
    if off:
        mins = (int(off.group(2)) * 60 + int(off.group(3))) * (1 if off.group(1) == "+" else -1)
        d -= timedelta(minutes=mins)
        d += timedelta(hours=-3)
    return d


# ══ catálogo (aba Equipamentos) ══════════════════════════════════════════════
class UsinaCat:
    __slots__ = ("nome", "cliente", "fracttal", "full_om", "pot", "fonte_pot",
                 "n_inv", "ugs", "ugs_derivadas", "invs", "inv_ug")

    def __init__(self, nome):
        self.nome = nome
        self.cliente = ""
        self.fracttal = ""
        self.full_om = ""
        self.pot = None
        self.fonte_pot = ""
        self.n_inv = None
        self.ugs = {}                # nº → kWp (linhas UG, ou derivadas — ver montar_catalogo)
        self.ugs_derivadas = False
        self.invs = {}               # "N.M"/"N" → kWp
        self.inv_ug = {}             # "N.M"/"N" → nº da UG, da coluna "Equipamento Parente"

    @property
    def n_cab(self):
        return len(self.ugs) or None

    def pot_ug_media(self):
        if self.ugs:
            vs = [v for v in self.ugs.values() if v]
            if vs:
                return sum(vs) / len(vs)
            if self.pot:
                return self.pot / len(self.ugs)
        return None

    def pot_inv_media(self):
        vs = [v for v in self.invs.values() if v]
        if vs:
            return sum(vs) / len(vs)
        if self.pot and self.n_inv:
            return self.pot / self.n_inv
        return None


def montar_catalogo(linhas):
    """linhas = dicts com cliente/usina/usina_fracttal/equipamento/parente/pot_kwp/n_inv (a aba
    Equipamentos crua). → {usina: UsinaCat} com potências completadas e cabines derivadas."""
    usinas = {}
    lacunas = []
    for e in linhas:
        u = _txt(e.get("usina"))
        if not u:
            continue
        U = usinas.setdefault(u, UsinaCat(u))
        eq = _txt(e.get("equipamento"))
        equ = eq.upper()
        pot = e.get("pot_kwp")
        pot = pot if isinstance(pot, (int, float)) and pot == pot else None    # descarta NaN
        fr = _txt(e.get("usina_fracttal"))
        if equ == "UFV":
            U.cliente = _txt(e.get("cliente"))
            # NÃO sobrescreve com vazio: há usina cuja linha UFV vem depois das filhas e sem
            # o vínculo preenchido (era o caso da 2ª linha UFV de Ribeirão Cascalheiras).
            U.fracttal = fr or U.fracttal
            U.full_om = _txt(e.get("full_om"))
            U.pot = pot
            U.fonte_pot = "UFV"
            try:
                U.n_inv = int(e["n_inv"]) if e.get("n_inv") is not None else None
            except (TypeError, ValueError):
                U.n_inv = None
        elif equ.startswith("UG"):
            m = re.search(r"(\d+)", eq)
            if m:
                U.ugs[int(m.group(1))] = pot
            U.fracttal = U.fracttal or fr
            U.cliente = U.cliente or _txt(e.get("cliente"))
            U.full_om = U.full_om or _txt(e.get("full_om"))
        elif equ.startswith("INVERSOR"):
            m = re.search(r"(\d+(?:\.\d+)?)\s*$", eq)
            if m:
                U.invs[m.group(1)] = pot
                # "Equipamento Parente" é a hierarquia OFICIAL do BD (100% preenchida, aponta
                # "UG NN") e é a fonte que a Performance usa. O padrão de nome "Inversor N.M"
                # é só o fallback: em Ibirapuã I/II, Inhapi e Tucano 2 o N do nome NÃO é a UG.
                par = _txt(e.get("parente")).upper()
                mp = re.search(r"(\d+)", par)
                if par.startswith("UG") and mp:
                    U.inv_ug[m.group(1)] = int(mp.group(1))
            U.fracttal = U.fracttal or fr
            U.cliente = U.cliente or _txt(e.get("cliente"))
            U.full_om = U.full_om or _txt(e.get("full_om"))
    for U in usinas.values():
        if not U.ugs and U.invs:                     # sem linhas UG → deriva as cabines
            der = defaultdict(float)
            for k, v in U.invs.items():
                ug = U.inv_ug.get(k)                 # 1ª opção: Equipamento Parente
                if ug is None:                       # 2ª: padrão de nome "Inversor N.M"
                    m = re.match(r"(\d+)\.(\d+)$", k)
                    ug = int(m.group(1)) if m else None
                if ug is not None:
                    der[ug] += (v or 0.0)
            if der:
                U.ugs = dict(der)
                U.ugs_derivadas = True
        if U.fonte_pot != "UFV" and (U.ugs or U.invs):
            lacunas.append(f"{U.nome}: sem linha UFV na aba Equipamentos")
        if U.pot is None:
            if U.ugs and any(U.ugs.values()):
                U.pot = sum(v for v in U.ugs.values() if v)
                U.fonte_pot = "soma UGs"
            elif U.invs and any(U.invs.values()):
                U.pot = sum(v for v in U.invs.values() if v)
                U.fonte_pot = "soma inversores"
            if U.pot:
                lacunas.append(f"{U.nome}: potência da UFV vazia → {U.fonte_pot} ({U.pot:.0f} kWp)")
        # Lacuna só interessa em usina Full O&M — fora delas o cadastro incompleto não é
        # problema nosso e só faria barulho na lista.
        if norm(U.full_om).startswith("S") and not U.fracttal and (U.pot or 0) > 0:
            lacunas.append(f"{U.nome}: sem 'Usina Fractall' — fora do cálculo "
                           f"({U.pot:.0f} kWp não avaliados)")
    return usinas, lacunas


# ══ site do Fracttal (groups_1) → usina(s) do catálogo ══════════════════════
def miolo_g1(g1):
    """'Thopen - Itajá 1 e 2 - RN' → 'ITAJA 1 E 2' (tira cliente e UF)."""
    t = norm(g1)
    t = re.sub(r"^[A-Z0-9 .]+? - ", "", t, count=1)
    t = re.sub(r"\s*-\s*[A-Z]{2}\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip()


def indices_g1(usinas):
    exato, mio = {}, {}
    for u, U in usinas.items():
        if not U.fracttal:
            continue
        exato.setdefault(norm(U.fracttal), []).append(u)
        mi = miolo_g1(U.fracttal)
        mio.setdefault(mi, []).append(u)
        m2 = re.sub(r"\s+\d+ E \d+$", "", mi)
        if m2 != mi:
            mio.setdefault(m2, []).append(u)
    return exato, mio


def resolve_g1(g1, usinas, idx):
    exato, mio = idx
    if not g1 or norm(g1).startswith("GRID CO"):
        return []
    out = []
    if norm(g1) in exato:
        out = exato[norm(g1)]
    else:
        mi = miolo_g1(g1)
        if mi in mio:
            out = mio[mi]
        else:
            mi2 = norm2(mi)
            for k, v in mio.items():
                if norm2(k) == mi2:
                    out = v
                    break
            else:
                for u in usinas:
                    n = norm2(u)
                    if len(n) >= 5 and (mi2 == n or mi2.startswith(n + " ")):
                        out = [u]
                        break
    out = list(dict.fromkeys(out))
    if len(out) > 1:
        out = [u for u in out if u not in PARQUE_EXCLUI]
    return out


# ══ consolidação de uma OS (lista de tasks) ══════════════════════════════════
def consolidar_os(folio, tasks, agora):
    """→ dict da OS com datas locais validadas, tipos, status, flags — ou com 'excl' preenchido."""
    tipos_all = {str(t.get("tasks_log_task_type_main") or "").strip() for t in tasks}
    tipos_alvo = sorted(t for t in tipos_all if t.lower() in TIPOS_ALVO)
    if not tipos_alvo:
        return None                                  # nem listar: fora do universo
    # origem da falha: QUEDA manda quando a OS tem os dois (a usina caiu; a corretiva veio junto)
    origem = "queda" if any(t.lower() in TIPOS_QUEDA for t in tipos_alvo) else "equipamento"
    o = {"folio": int(folio), "tipos": tipos_alvo, "origem": origem, "flags": [], "excl": None,
         "code": str(tasks[0].get("code") or "").strip(),
         "item": str(tasks[0].get("items_log_description") or "").split("{")[0].strip(),
         "g1": str(tasks[0].get("groups_1_description") or "").strip(),
         "desc": str(tasks[0].get("description") or "").strip(),
         "criado_por": str(tasks[0].get("created_by") or "").strip(),
         "responsavel": str(tasks[0].get("personnel_description")
                            or tasks[0].get("user_assigned") or "").strip(),
         "aberta": False, "aberta_sem_fim": False, "ini": None, "fim": None}
    sts = {t.get("id_status_work_order") for t in tasks}
    if sts == {4}:
        o["excl"] = "OS cancelada"
        return o
    o["aberta"] = any(s in (0, 1, 5, 6) for s in sts)

    ok_dt = lambda d: d and d.year == agora.year and d <= agora
    inis = [dt_frac(t.get("event_date") or t.get("date_maintenance")) for t in tasks]
    inis = [d for d in inis if d and agora.year - 1 <= d.year <= agora.year]
    # fim = max(final_date); wo_final_date SÓ sem final_date nenhum (carimbo administrativo)
    fins1 = [d for d in (dt_frac(t.get("final_date")) for t in tasks) if ok_dt(d)]
    fins2 = [d for d in (dt_frac(t.get("wo_final_date")) for t in tasks) if ok_dt(d)]
    ini = min(inis) if inis else None
    fim = max(fins1) if fins1 else (max(fins2) if fins2 else None)
    if not fins1 and fins2:
        o["flags"].append("sem final_date → usei wo_final_date (carimbo da WO; pode ser tardio)")
    if ini is None:
        o["excl"] = "sem data de evento válida"
        return o
    if fim is not None and fim < ini:
        if (ini - fim).total_seconds() <= 3600:      # relâmpago: carimbo minutos antes do evento
            o["flags"].append("fim registrado minutos antes do evento → duração 0")
            fim = ini
        else:
            o["flags"].append("fim muito antes do início → descartado")
            fim = None
    if fim is None:
        if o["aberta"]:
            o["aberta_sem_fim"] = True               # 0h no cálculo; cenário à parte
            fim = ini
            o["flags"].append("OS ABERTA sem data final → 0h no cálculo (ver cenário)")
        else:
            o["excl"] = "OS concluída sem data final válida"
            o["ini"] = ini
            return o
    o["ini"], o["fim"] = ini, fim
    return o


# ══ escopo pelo ativo ════════════════════════════════════════════════════════
def _pista_no_texto(o, grupo):
    # SÓ a description: o items_log/g1 carregam o nome AGRUPADO do site ("Beta 1 e 2"), que
    # contém "Beta 1" e viraria falso positivo. O lookahead descarta a própria forma "N e M".
    d = norm2(o["desc"])
    achou = set()
    for u in grupo:
        nu = norm2(u)
        m = re.match(r"^(.*?)\s+(\d+)$", nu)
        if m and re.search(re.escape(m.group(1)) + r"\s*0?" + m.group(2) + r"(?!\d)(?!\s+E\s+\d)", d):
            achou.add(u)
    if len(grupo) == 2:
        if re.search(r"\b1A\b", d):
            achou.add(sorted(grupo)[0])
        if re.search(r"\b1B\b", d):
            achou.add(sorted(grupo)[1])
    return sorted(achou)


def escopo_os(o, usinas, idx):
    """→ lista [(usina, nivel, chave, kwp)]; None = exclusão (o motivo fica em o['excl'])."""
    code = o["code"]
    if norm(o["g1"]).startswith("GRID CO") or code == "GRID":
        o["excl"] = "site 'Grid Co.' = usina de terceiros sem contrato (fora do parque)"
        return None
    grupo = resolve_g1(o["g1"], usinas, idx)
    if not grupo:
        o["excl"] = f"site do Fracttal sem correspondência no BD: '{o['g1'] or code}'"
        return None

    m = re.search(r"-D?INVR?(\d+(?:\.\d+)?)$", code)
    if m and ("INVR" in code or "DINV" in code):
        num = m.group(1)
        for u in grupo:
            U = usinas[u]
            if U.invs.get(num):
                return [(u, "inversor", f"inv{num}", min(U.invs[num], U.pot or U.invs[num]))]
        U = usinas[grupo[0]]
        pm = U.pot_inv_media()
        if pm:
            o["flags"].append(f"inversor {num} sem match exato no BD → potência média")
            return [(grupo[0], "inversor", f"inv{num}", pm)]
        o["excl"] = f"inversor {num} sem potência derivável no BD ({grupo[0]})"
        return None

    m = re.search(r"-(" + "|".join(SUF_CABINE) + r")(\d+)$", code)
    if m:
        ncab = int(m.group(2))
        if len(grupo) == 1:
            alvo = grupo[0]
        else:
            # Régua do Levi (27/08, caso OS 11461): site agrupado onde CADA usina tem no
            # máximo 1 cabine própria → o Nº da cabine IDENTIFICA a usina ('Cabine 2' do
            # site 'Aparecida do Taboado 1 e 2' = usina Taboado 2, INTEIRA). Se alguma
            # usina do grupo tem 2+ cabines (Ipixuna 1), o número pode ser cabine interna
            # e o mapeamento seria chute — aí vale o fluxo antigo (pista → 1ª + flag).
            if all((usinas[u].n_cab or 1) <= 1 for u in grupo):
                for u in grupo:
                    m2 = re.search(r"(\d+)$", norm2(u))
                    if m2 and int(m2.group(1)) == ncab:
                        U = usinas[u]
                        if not (U.pot and U.pot > 0):
                            o["excl"] = f"usina '{u}' sem potência no BD"
                            return None
                        o["flags"].append(f"cabine {ncab} do site agrupado = usina '{u}' "
                                          "(configuração de 1 cabine por usina)")
                        return [(u, "usina", "ufv", U.pot)]
            pista = _pista_no_texto(o, grupo)
            if len(pista) == 1:
                alvo = pista[0]
                o["flags"].append(f"site agrupado → usina '{alvo}' pela descrição")
            else:
                alvo = grupo[0]
                o["flags"].append(f"site agrupado {grupo} sem pista → atribuí à 1ª ({alvo}); conferir")
        U = usinas[alvo]
        if not (U.pot and U.pot > 0):
            o["excl"] = f"usina '{alvo}' sem potência no BD"
            return None
        p = U.ugs.get(ncab)
        if p:
            return [(alvo, "cabine", f"cab{ncab}", min(p, U.pot))]
        pm = U.pot_ug_media()
        if pm:
            o["flags"].append(f"cabine {ncab} sem UG própria no BD ({alvo}) → potência média de cabine")
            return [(alvo, "cabine", f"cab{ncab}", min(pm, U.pot))]
        o["flags"].append(f"usina {alvo} sem cabines no BD → considerei a usina inteira")
        return [(alvo, "usina", "ufv", U.pot)]

    if re.search(r"[A-Z]{3}\d{3}$", code) or code == "" or norm(o["item"]).startswith(norm(o["g1"])[:8]):
        alvos = grupo
        if len(grupo) > 1:
            pista = _pista_no_texto(o, grupo)
            if pista:
                alvos = pista
                o["flags"].append(f"site agrupado → {pista} pela descrição")
            else:
                o["flags"].append(f"site agrupado {grupo} sem pista na descrição → grupo inteiro")
        evs = [(u, "usina", "ufv", usinas[u].pot) for u in alvos
               if usinas[u].pot and usinas[u].pot > 0]
        if evs:
            return evs
        o["excl"] = f"nenhuma usina do site '{o['g1']}' tem potência no BD"
        return None

    o["excl"] = f"ativo não é de geração ou não mapeável: '{code}' ({o['item'][:40]})"
    return None


def _rotulo_escopo(nivel, chave):
    """chave interna → rótulo legível do card ('cab6' → 'Cabine 6', 'inv1.1' → 'Inversor 1.1')."""
    if nivel == "usina":
        return "Usina inteira"
    if nivel == "cabine":
        return "Cabine " + str(chave).replace("cab", "")
    if nivel == "inversor":
        return "Inversor " + str(chave).replace("inv", "")
    return str(chave)


# ══ janela solar ═════════════════════════════════════════════════════════════
def horas_solares_por_dia(a, b, teto):
    """{date: horas} da interseção [a,b) com a janela 06–18h, dias < teto.date()."""
    out = {}
    d = a.date()
    while d <= b.date() and d < teto.date():
        js = datetime(d.year, d.month, d.day, SOL_INI_H)
        jf = datetime(d.year, d.month, d.day, SOL_FIM_H)
        x, y = max(a, js), min(b, jf)
        if y > x:
            out[d] = (y - x).total_seconds() / 3600.0
        d += timedelta(days=1)
    return out


def _varrer(eventos, usinas, per_fim):
    """Linha do tempo por usina → (h_eq, kwh, det_os) por dia. Hierarquia usina > cabine >
    inversor e teto de 100% da usina. Chamada 3×: total, só queda, só equipamento."""
    h_eq = defaultdict(lambda: defaultdict(float))
    kwh = defaultdict(lambda: defaultdict(float))
    det_os = defaultdict(float)
    for u in sorted({e["usina"] for e in eventos}):
        evs = [e for e in eventos if e["usina"] == u]
        pot_u = usinas[u].pot or 0.0
        bordas = sorted({e["ini"] for e in evs} | {e["fim"] for e in evs})
        for i in range(len(bordas) - 1):
            a, b = bordas[i], bordas[i + 1]
            ativos = [e for e in evs if e["ini"] <= a and e["fim"] >= b]
            if not ativos:
                continue
            if any(e["nivel"] == "usina" for e in ativos):
                kw_af, donos = pot_u, [e for e in ativos if e["nivel"] == "usina"]
            else:
                kw_af = min(pot_u, sum(e["kwp"] for e in ativos))
                donos = ativos
            frac_af = (kw_af / pot_u) if pot_u > 0 else 0.0
            hs = horas_solares_por_dia(a, b, per_fim)
            tot_kw = sum(e["kwp"] for e in donos) or 1.0
            for dia, h in hs.items():
                h_eq[u][dia] += frac_af * h
                kwh[u][dia] += kw_af * h
                for e in donos:
                    det_os[e["o"]["folio"]] += kw_af * (e["kwp"] / tot_kw) * h
    return h_eq, kwh, det_os


# ══ cálculo principal ════════════════════════════════════════════════════════
def _normal_kwh_kwp(dias_ger, pot_kwp):
    """Produção 'normal' da usina no período, em kWh/kWp: P75 dos dias com dado. O P75 (e não a
    média) porque dias nublados e dias de parada real puxariam a referência para baixo — o que
    se quer é o patamar de regime pleno. None se não dá para afirmar nada."""
    vs = sorted(v / pot_kwp for v in dias_ger.values() if isinstance(v, (int, float)))
    if len(vs) < 5:
        return None
    p75 = vs[min(int(len(vs) * 0.75), len(vs) - 1)]
    # patamar abaixo de usina plena → não dá para usar como referência (ver comentário lá em cima)
    return p75 if p75 >= GER_PLENO_KWH_KWP else None


def _dias_desmentidos(usina, a, b, geracao, pot_kwp, kwp_afetado):
    """Dias de [a,b] em que a GERAÇÃO DESMENTE a parada afirmada pela OS.

    A OS diz que `kwp_afetado` de `pot_kwp` estava parado → a usina deveria produzir no máximo
    (1 - f) do normal. Produziu bem mais que isso? Então rodava mais capacidade do que a OS
    afirma, e esse dia não conta. Dia sem dado nunca entra: ausência de prova não é prova."""
    if not geracao or not pot_kwp or pot_kwp <= 0:
        return set()
    ent = geracao.get(usina) or {}
    # Duas formas aceitas: {dia: kWh} (a geração é só desta usina) ou
    # {"dias": {...}, "kwp": N} — a medição cobre um COMPLEXO e N é o kWp somado dele. É o caso
    # de Nova Londrina, que o BD_Thopen mede junto: a fração parada e o rendimento passam a ser
    # calculados sobre o complexo, sem precisar separar a planilha.
    if isinstance(ent.get("dias"), dict):
        dias_ger, base = ent["dias"], (ent.get("kwp") or pot_kwp)
    else:
        dias_ger, base = ent, pot_kwp
    if not base or base <= 0:
        return set()
    normal = _normal_kwh_kwp(dias_ger, base)
    if not normal:
        return set()
    frac_pot = min(1.0, max(0.0, (kwp_afetado or 0) / base))
    out = set()
    # a fatia perdida do DIA é a fração de potência vezes a fatia do dia solar coberta
    for d, horas in horas_solares_por_dia(a, b, b + timedelta(days=1)).items():
        f_dia = frac_pot * min(1.0, horas / 12.0)
        if f_dia < GER_FRAC_MIN:               # fatia pequena demais p/ a geração julgar
            continue
        kwh = dias_ger.get(d.isoformat())
        if not isinstance(kwh, (int, float)):
            continue
        teto = (1.0 - f_dia) + GER_TOLERANCIA  # fração do normal compatível com a parada
        if (kwh / base) / normal > teto:        # produziu mais do que a parada permitiria
            out.add(d)
    return out


def calcular(wos, linhas_equip, per_ini, per_fim, agora=None, geracao=None):
    """wos = {folio: [tasks...]} (varredura crua do Fracttal); linhas_equip = aba Equipamentos.
    per_ini/per_fim = janela do mês (fim EXCLUSIVO, já cortado em D-1 pelo chamador).
    → payload completo: usinas, clientes, diário, OSs, cenário das abertas, lacunas."""
    agora = agora or datetime.now()
    usinas, lacunas = montar_catalogo(linhas_equip)
    idx = indices_g1(usinas)
    n_dias = (per_fim.date() - per_ini.date()).days
    tot_h = 12.0 * n_dias

    oss, eventos, os_escopo = [], [], {}
    for folio, tasks in wos.items():
        o = consolidar_os(folio, tasks, agora)
        if o is None:
            continue
        if not o["excl"]:
            if o["fim"] < per_ini or o["ini"] >= per_fim:
                continue                             # não toca o período — fora do universo
        oss.append(o)
        if o["excl"]:
            continue
        esc = escopo_os(o, usinas, idx)
        if esc is None:
            continue
        os_escopo[o["folio"]] = esc
        a, b = max(o["ini"], per_ini), min(o["fim"], per_fim)
        if b <= a:
            continue
        for (u, nivel, chave, kwp) in esc:
            exon = _dias_desmentidos(u, a, b, geracao, usinas[u].pot, kwp)
            if not exon:
                eventos.append({"usina": u, "nivel": nivel, "kwp": kwp, "ini": a, "fim": b, "o": o})
                continue
            # a geração desmente a parada nesses dias: parte o evento e pula
            o["flags"].append(f"{u}: {len(exon)} dia(s) exonerados — a geração desmente a parada "
                              f"(OS longa fechada com atraso não é parada real)")
            o.setdefault("dias_exonerados", {})[u] = sorted(x.isoformat() for x in exon)
            d = a.date()
            while d <= b.date():
                if d not in exon:
                    ini_d = max(a, datetime(d.year, d.month, d.day))
                    fim_d = min(b, datetime(d.year, d.month, d.day) + timedelta(days=1))
                    if fim_d > ini_d:
                        eventos.append({"usina": u, "nivel": nivel, "kwp": kwp,
                                        "ini": ini_d, "fim": fim_d, "o": o})
                d += timedelta(days=1)

    h_eq, kwh, det_os = _varrer(eventos, usinas, per_fim)
    # decomposição por origem: mesma varredura, só com os eventos de cada família
    h_qd, kwh_qd, _ = _varrer([e for e in eventos if e["o"]["origem"] == "queda"], usinas, per_fim)
    h_eq_ip, kwh_ip, _ = _varrer([e for e in eventos if e["o"]["origem"] == "equipamento"],
                                 usinas, per_fim)

    os_h = {}
    cenario = []
    for o in oss:
        if o["excl"]:
            continue
        a, b = max(o["ini"], per_ini), min(o["fim"], per_fim)
        os_h[o["folio"]] = round(sum(horas_solares_por_dia(a, b, per_fim).values()), 2) if b > a else 0.0
        if o["aberta_sem_fim"]:
            h_cen = sum(horas_solares_por_dia(max(o["ini"], per_ini), per_fim, per_fim).values())
            kwh_cen = sum(kwp * h_cen for (_u, _n, _c, kwp) in os_escopo.get(o["folio"], []))
            cenario.append({"folio": o["folio"], "g1": o["g1"], "desc": o["desc"][:90],
                            "code": o["code"], "ini": o["ini"].isoformat(),
                            "usinas": sorted({u for (u, _n, _c, _k) in os_escopo.get(o["folio"], [])}),
                            "h_cenario": round(h_cen, 1), "kwh_cenario": round(kwh_cen)})

    # SÓ FULL O&M (decisão do Levi, 30/08): onde a Grid Co. não faz a manutenção completa, a
    # disponibilidade não é responsabilidade nossa e as OSs do Fracttal não contam a história
    # toda. Vale para o parque, para o resumo por cliente e para o diário.
    parque = {u: U for u, U in usinas.items()
              if U.fracttal and (U.pot or 0) > 0 and u not in PARQUE_EXCLUI
              and norm(U.full_om).startswith("S")}
    res_usinas = []
    for u, U in sorted(parque.items()):
        ph = sum(h_eq[u].values())
        phq = sum(h_qd[u].values())
        phe = sum(h_eq_ip[u].values())
        res_usinas.append({"usina": u, "cliente": U.cliente, "fracttal": U.fracttal,
                           "full_om": U.full_om, "pot_kwp": round(U.pot, 1),
                           "fonte_pot": U.fonte_pot, "n_inv": U.n_inv, "n_cab": U.n_cab,
                           "disp": round(100.0 * (1 - ph / tot_h), 2) if tot_h else None,
                           "h_perdidas": round(ph, 2),
                           "kwh": round(sum(kwh[u].values())),
                           # decomposição por origem (queda × equipamento)
                           "disp_queda": round(100.0 * (1 - phq / tot_h), 2) if tot_h else None,
                           "h_queda": round(phq, 2), "kwh_queda": round(sum(kwh_qd[u].values())),
                           "disp_equip": round(100.0 * (1 - phe / tot_h), 2) if tot_h else None,
                           "h_equip": round(phe, 2), "kwh_equip": round(sum(kwh_ip[u].values())),
                           "n_os": len({e["o"]["folio"] for e in eventos if e["usina"] == u})})

    por_cli = defaultdict(lambda: {"kwp": 0.0, "ph_pond": 0.0, "phq_pond": 0.0, "phe_pond": 0.0,
                                   "kwh": 0.0, "kwh_q": 0.0, "kwh_e": 0.0, "n_os": 0,
                                   "n_usinas": 0, "abaixo99": 0})
    for r in res_usinas:
        c = por_cli[r["cliente"] or "—"]
        c["kwp"] += r["pot_kwp"]
        c["ph_pond"] += r["pot_kwp"] * r["h_perdidas"]
        c["phq_pond"] += r["pot_kwp"] * r["h_queda"]
        c["phe_pond"] += r["pot_kwp"] * r["h_equip"]
        c["kwh"] += r["kwh"]
        c["kwh_q"] += r["kwh_queda"]
        c["kwh_e"] += r["kwh_equip"]
        c["n_os"] += r["n_os"]
        c["n_usinas"] += 1
        if r["disp"] is not None and r["disp"] < 99:
            c["abaixo99"] += 1

    def _pond(num, c):
        return round(100.0 * (1 - num / (c["kwp"] * tot_h)), 2) if (tot_h and c["kwp"]) else None

    res_clientes = [{"cliente": nome, "kwp": round(c["kwp"]),
                     "disp": _pond(c["ph_pond"], c), "kwh": round(c["kwh"]),
                     "disp_queda": _pond(c["phq_pond"], c), "kwh_queda": round(c["kwh_q"]),
                     "disp_equip": _pond(c["phe_pond"], c), "kwh_equip": round(c["kwh_e"]),
                     "n_os": c["n_os"], "n_usinas": c["n_usinas"], "abaixo99": c["abaixo99"]}
                    for nome, c in sorted(por_cli.items())]

    return {
        "periodo": {"ini": per_ini.isoformat(), "fim": per_fim.isoformat(), "dias": n_dias},
        "usinas": res_usinas,
        "clientes": res_clientes,
        "diario": {u: {d.isoformat(): {"h_eq": round(h, 3),
                                       "disp": round(100 * (1 - h / 12), 1),
                                       "kwh": round(kwh[u].get(d, 0)),
                                       # decomposição do dia (card da célula do mapa)
                                       "h_q": round(h_qd[u].get(d, 0.0), 3),
                                       "h_e": round(h_eq_ip[u].get(d, 0.0), 3)}
                       for d, h in sorted(dias.items())} for u, dias in h_eq.items()},
        "oss": [{**{k: o.get(k) for k in ("folio", "tipos", "origem", "code", "item", "g1",
                                          "desc", "flags", "excl", "aberta", "criado_por",
                                          "responsavel", "dias_exonerados")},
                 "ini": o["ini"].isoformat() if o.get("ini") else None,
                 "fim": o["fim"].isoformat() if o.get("fim") else None,
                 "usinas": sorted({u for (u, _n, _c, _k) in os_escopo.get(o["folio"], [])}),
                 # discriminação do cálculo (card do dia): o que foi afetado e com quantos kWp
                 "escopo": [{"usina": u, "nivel": n, "rotulo": _rotulo_escopo(n, c),
                             "kwp": round(k, 1)}
                            for (u, n, c, k) in os_escopo.get(o["folio"], [])],
                 "h_solar": os_h.get(o["folio"], 0.0),
                 "kwh": round(det_os.get(o["folio"], 0.0))} for o in oss],
        "cenario_abertas": cenario,
        "lacunas": lacunas,
    }
