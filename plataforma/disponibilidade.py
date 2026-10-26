# -*- coding: utf-8 -*-
"""Disponibilidade por OS do Fracttal × estrutura do BD_Performance (aba Equipamentos).

Módulo PURO (sem Flask, sem rede, sem arquivo): o app.py injeta as work orders varridas e o
catálogo de equipamentos; os testes injetam fixtures. Réguas fechadas com o Levi em 25-26/08/26
na análise que virou `Disponibilidade Fracttal x BD - agosto 2026.xlsx`:

- Contam OSs com tipo de tarefa Religamento / Religamento Remoto / Corretiva Emergencial;
  canceladas NUNCA contam.
- Início = event_date (ou date_maintenance). Fim = final_date da tarefa. `wo_final_date` é
  carimbo administrativo da WO (uma revisão em massa em 25/08 re-carimbou dezenas p/ o mesmo
  minuto) — só entra como último recurso, com flag.
- SÓ O FRACTTAL (Levi, 15/10/2026: "não quero que cruze dados de geração pois são objetivos
  diferentes"). Até 15/10 a geração do BD desmentia a OS (o "juiz" de 30/08); saiu de vez.
- Evento DEPOIS do fim: a data de criação da OS vira o evento (Levi, 15/10/2026). Se o fim
  fica antes até da criação, a OS conta 0 h e vai para a lista `alinhar`.
- OS ABERTA sem fim CONTA, do evento até o fim do período (no mês corrente, até ontem), em todo
  mês em que seguir aberta (Levi, 15/10/2026: "Será considerado OSs fechadas e abertas"). De
  26/08 a 15/10 ela valia 0 h, com um cenário à parte, e sumia no mês seguinte.
- `alinhar`: o que o próprio Fracttal mostra de estranho (aberta contando, evento depois do fim,
  data final da WO, site agrupado sem a usina, OS sem data) — para corrigir a OS, não a conta.
- Setembro para trás é da Thopen, pelo BD_Thopen (`calcular_pelo_bd`); fora da Thopen, só de
  outubro em diante. Quem escolhe o caminho por mês é o app.py.
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
#
# O juiz da GERAÇÃO (30/08 a 15/10/2026) saiu: ele desmentia a OS em dia em que a usina gerou (OS 8891 dizia Parelhas
# parada de 03/07 a 28/08 com 13.111 kWh/dia). O Levi decidiu (15/10) que a disponibilidade é do Fracttal e só dele —
# a OS errada se corrige no Fracttal, e a lista `alinhar` mostra quais olhar. Não volte a cruzar com a geração.

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


def montar_catalogo(linhas, pot_reserva=None):
    """linhas = dicts com cliente/usina/usina_fracttal/equipamento/parente/pot_kwp/n_inv (a aba
    Equipamentos crua). → {usina: UsinaCat} com potências completadas e cabines derivadas.

    `pot_reserva` = {usina: kWp} do Registro mestre do Nexus, só para a usina SEM potência nenhuma na aba (nem na UFV, nem
    nas UGs, nem nos inversores). Caso que criou (22/10/2026): as Pharma II, III e IV têm as 24 linhas da aba com a
    potência vazia, e toda OS delas saía da conta ("nenhuma usina do site ... tem potência no BD") — a disponibilidade
    delas no Dashboard Thopen era "—". O que estiver na aba vence; a reserva vira lacuna, para alguém preencher a aba."""
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
        if U.pot is None and (pot_reserva or {}).get(U.nome):
            U.pot = float(pot_reserva[U.nome])
            U.fonte_pot = "Registro mestre"
            lacunas.append(f"{U.nome}: sem potência na aba Equipamentos → Registro mestre do Nexus ({U.pot:.0f} kWp)")
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
# Falta de comunicação NÃO é parada (Levi, 19/10/2026: "a falta de comunicação não deve entrar no cálculo de
# disponibilidade"). No Fracttal a OS de "Verificação de comunicação do ..." vem como Religamento (ou Corretiva
# Emergencial), e a conta a tomava por usina parada: em outubro, até 18/10, 113 OS e 27,8% de toda a energia perdida
# (Brodowski a 0% pela OS 12693, aberta desde 02/09; TIM200 a 57% pela 15488). Toda OS cuja descrição (ou o ativo) diz
# "comunicação" sai da conta — vale para o tipo que for — e fica visível na lista "alinhar" como fora da conta, com a usina.
EXCL_COMUNICACAO = "falta de comunicação: não é parada"


def eh_falta_de_comunicacao(*textos):
    """A OS é de falta de comunicação: "comunicação" no texto (descrição, ativo), sem acento e sem caixa."""
    return "COMUNICA" in norm(" ".join(str(t or "") for t in textos))


# A OS de comunicação que foi PARADA volta para a conta (Levi, 26/10/2026: "agora sabemos tudo o que estava sem subtarefa
# porém foi religamento em outubro, bote na conta e a partir de agora veja as últimas OSs criadas sobre comunicação que foi
# confirmado na subtarefa que foi religamento"). A verificação de comunicação do COS tem a subtarefa "Diagnóstico":
# "Desligado" (o técnico achou a usina parada) ou "Só sem comunicação (segue gerando)". Medido em outubro (162 OS de
# comunicação): 48 com "Desligado"; as 18 com "Só sem comunicação" e Ação "Religamento local" eram roteador, smartlogger e
# internet — o religamento ali é do equipamento de comunicação, então o Diagnóstico decide, não a Ação. O formulário do
# religamento ("Foi necessário religamento?" = Sim) também confirma. Em branco ou sem subtarefa: fora, como desde 19/10.
def veredito_subtarefas(subtarefas):
    """'parada' | 'comunicacao' | None (sem resposta) pelas subtarefas da OS ({description, value})."""
    resp = {norm(s.get("description")).strip(" ?:"): norm(s.get("value")) for s in subtarefas or []}
    diag = resp.get("DIAGNOSTICO") or ""
    if diag.startswith("DESLIGAD"):
        return "parada"
    if diag.startswith("SO SEM COMUNICA"):
        return "comunicacao"
    if (resp.get("FOI NECESSARIO RELIGAMENTO") or "").startswith("SIM"):
        return "parada"
    return None


# O retorno do COS sobre outubro de 2026 (planilha "Verificação Thopen 1 - retorno COS", 26/10/2026): vence a subtarefa.
# Só as OS em que ele muda a conta: as de comunicação SEM subtarefa que foram parada, e as que eram só comunicação (uma
# aberta como Religamento, outra com a subtarefa marcada "Desligado" com a usina gerando). As datas seguem as do Fracttal
# (o fim da atividade); data errada se corrige lá.
RETORNO_COS = {
    16640: ("parada", "Salto Pirapora 3: inversor parado de 16/10 a 17/10, normalizou reconectando as strings"),
    15678: ("parada", "Guaratinguetá V: inversor 1.5 parado de 07/10 a 15/10 (fusível queimado)"),
    16515: ("parada", "Brodowski 2: cabines desligadas (trip 47 e 86) até 16/10, religadas no local"),
    16653: ("comunicacao", "Ceilândia 1, 17 a 19/10: só comunicação, a usina gerando"),
    14997: ("comunicacao", "Ceilândia 1, 30/09: só comunicação, sem impacto"),
    15025: ("comunicacao", "Sítio dos Nogueiras, 30/09: oscilação de internet, a usina gerando"),
    15314: ("comunicacao", "Ceilândia 2, 03/10: comunicação entre a sala de O&M e os skids"),
}


# O fim corrigido pelo COS onde a OS do Fracttal não pode mais ser editada (Levi, 26/10/2026: "15192 infelizmente não temos
# mais como editar então faça essa peculiaridade manual"; "o resto vamos tentar calcular antes"). Vale no lugar do fim da
# atividade, na conta e no drill, e fica à vista no "alinhar". Data errada que ainda dá para editar se corrige no Fracttal.
CORRECOES_FIM = {
    15192: (datetime(2026, 10, 2, 10, 40), "São Bento do Una: religada às 10:40 de 02/10 (retorno do COS)"),
}


# A OS aberta no site de duas usinas que o COS diz ser de uma só (Levi, 26/10/2026, OS 16498 "Só na AP2"): o site
# "Aparecida do Taboado 1 e 2" põe a parada nas duas; o retorno do COS diz que a AP1 gerou normal em 16/10 e só a AP2
# parou. {folio: ([usinas que contam], nota)}; vale na conta, na cascata, no relatório e no drill da usina.
ESCOPO_COS = {
    16498: (["Aparecida do Taboado 2"], "o relé da AP2 ficou sem alimentação; a AP1 gerou normal (retorno do COS)"),
}


def escopo_cos_exclui(folio, usina):
    """A OS tem escopo do COS (ESCOPO_COS) e esta usina não é dele?"""
    try:
        f = int(folio)
    except (TypeError, ValueError):
        return False
    return f in ESCOPO_COS and str(usina or "").strip() not in ESCOPO_COS[f][0]


def fim_corrigido(folio, fim):
    """O fim da correção manual (CORRECOES_FIM) para a OS que tem uma; senão o fim que veio."""
    try:
        f = int(folio)
    except (TypeError, ValueError):
        return fim
    return CORRECOES_FIM[f][0] if f in CORRECOES_FIM else fim


def veredito_da_os(folio, vereditos=None):
    """(veredito, fonte): o retorno do COS primeiro, depois o das subtarefas que o worker leu ({folio: veredito})."""
    try:
        f = int(folio)
    except (TypeError, ValueError):
        return None, None
    if f in RETORNO_COS:
        return RETORNO_COS[f][0], "retorno do COS: " + RETORNO_COS[f][1]
    v = (vereditos or {}).get(str(f))
    return (v, "subtarefa") if v else (None, None)


def comunicacao_fora(folio, desc, item, vereditos=None):
    """A OS fica fora da conta por ser só comunicação? A mesma decisão do consolidar_os, para a cascata e o relatório."""
    v, _f = veredito_da_os(folio, vereditos)
    if v == "comunicacao" and (eh_falta_de_comunicacao(desc, item) or (_f or "").startswith("retorno do COS")):
        return True
    if v == "parada":
        return False
    return eh_falta_de_comunicacao(desc, item)


def consolidar_os(folio, tasks, agora, vereditos=None):
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
         "aberta": False, "aberta_sem_fim": False, "ini": None, "fim": None, "alinhar": []}
    sts = {t.get("id_status_work_order") for t in tasks}
    if sts == {4}:
        o["excl"] = "OS cancelada"
        return o
    o["aberta"] = any(s in (0, 1, 5, 6) for s in sts)

    inis = [dt_frac(t.get("event_date") or t.get("date_maintenance")) for t in tasks]
    inis = [d for d in inis if d and agora.year - 1 <= d.year <= agora.year]
    ini = min(inis) if inis else None
    crias = [d for d in (dt_frac(t.get("creation_date")) for t in tasks) if d and d <= agora]
    o["criada"] = min(crias) if crias else None
    # fim no ano de agora OU, na OS cujo evento é do ano anterior, nele também (revisão adversarial de 11/10/2026). Só o
    # ano de agora valia, e o índice do Gerencial é refeito com o relógio de agora: de 01/01 em diante, toda OS
    # concluída em dezembro virava "OS concluída sem data final válida" e o dezembro (no Gerencial e na aba
    # disponibilidade_dia do workbook de falhas) saía 100% em todos os dias. O fim num ano ANTES do evento continua fora
    # — a digitação 2025 da fase RDO — e aí vale o wo_final_date, como antes; no futuro, também fora
    ok_dt = lambda d: d and d <= agora and (d.year == agora.year or (ini is not None and d.year >= ini.year))
    # fim = max(final_date); wo_final_date SÓ sem final_date nenhum (carimbo administrativo)
    fins1 = [d for d in (dt_frac(t.get("final_date")) for t in tasks) if ok_dt(d)]
    fins2 = [d for d in (dt_frac(t.get("wo_final_date")) for t in tasks) if ok_dt(d)]
    fim = max(fins1) if fins1 else (max(fins2) if fins2 else None)
    if not fins1 and fins2:
        o["flags"].append("sem final_date → usei wo_final_date (carimbo da WO; pode ser tardio)")
        o["alinhar"].append("sem data final na tarefa: usei a data final da WO")
    if fim_corrigido(folio, fim) is not fim:
        no_frac = f"{fim:%d/%m %H:%M}" if fim else "sem fim"
        fim = fim_corrigido(folio, fim)
        nota = CORRECOES_FIM[int(folio)][1]
        o["flags"].append(f"fim corrigido pelo COS: {fim:%d/%m %H:%M} (no Fracttal: {no_frac}) — {nota}")
        o["alinhar"].append(f"fim corrigido pelo COS para {fim:%d/%m %H:%M} (no Fracttal: {no_frac}); a OS não pode mais "
                            "ser editada")
    if ini is None:
        o["excl"] = "sem data de evento válida"
        return o
    if fim is not None and fim < ini:
        # evento DEPOIS do fim: a criação vira o evento (Levi, 15/10/2026). Antes: até 1 h = duração 0 ("relâmpago");
        # mais que isso, o fim era descartado e a OS concluída saía do cálculo
        if o["criada"] is not None and o["criada"] <= fim:
            o["flags"].append(f"evento depois do fim → usei a criação da OS ({o['criada']:%d/%m %H:%M}) como evento")
            o["alinhar"].append("evento depois do fim: usei a criação da OS como evento")
            ini = o["criada"]
        else:
            sem_cria = o["criada"] is None
            o["flags"].append("fim antes do evento" + (", sem data de criação" if sem_cria else " e da criação") + " → 0 h")
            o["alinhar"].append("fim antes do evento" + (", sem data de criação" if sem_cria else " e antes da criação")
                                + ": conta 0 h")
            fim = ini
    if fim is None:
        if o["aberta"]:
            # conta do evento até o fim do período (Levi, 15/10/2026); o calcular corta no per_fim
            o["aberta_sem_fim"] = True
            fim = agora
            o["flags"].append("OS ABERTA sem data final → conta até agora")
            o["alinhar"].append(f"OS aberta sem data final: conta enquanto estiver aberta ({(agora - ini).days} dias em aberto)")
            o["dias_aberta"] = (agora - ini).days
        else:
            o["excl"] = "OS concluída sem data final válida"
            o["ini"] = ini
            return o
    o["ini"], o["fim"] = ini, fim
    # falta de comunicação não é parada (19/10/2026, EXCL_COMUNICACAO): fora da conta, com as datas para a lista. Desde
    # 26/10/2026 a de comunicação com a parada confirmada (subtarefa ou retorno do COS) conta, e a que o COS disse ser só
    # comunicação sai, aberta como for
    if comunicacao_fora(folio, o["desc"], o["item"], vereditos):
        o["excl"] = EXCL_COMUNICACAO
        v, fonte = veredito_da_os(folio, vereditos)
        if fonte and fonte.startswith("retorno do COS"):
            o["flags"].append(fonte)
        return o
    if eh_falta_de_comunicacao(o["desc"], o["item"]):
        _v, fonte = veredito_da_os(folio, vereditos)
        o["flags"].append("aberta como comunicação; parada confirmada (%s)"
                          % (fonte if fonte != "subtarefa" else "subtarefa Diagnóstico: Desligado"))
    # Dois sinais só do Fracttal que a prova de 15/10/2026 mostrou pesando no mês — a OS CONTINUA contando, só vai para
    # "alinhar": Religamento cuja descrição é inspeção (até 19/10 também a verificação de comunicação, que saiu da conta)
    # e religamento que dura mais de um dia (Canarana 1, OS 14924, 29/09 a 13/10). Corretiva longa não entra: trocar um
    # inversor leva dias de verdade.
    if origem == "queda":
        texto = norm(f"{o['desc']} {o['item']}")
        if "INSPEC" in texto:
            o["alinhar"].append("Religamento com descrição de inspeção: houve parada?")
        horas = (fim - ini).total_seconds() / 3600
        if horas > 24 and not o["aberta_sem_fim"]:          # a aberta já vai para "alinhar" pelos dias em aberto
            dur = f"{int(horas // 24)} dias" if horas >= 48 else f"{round(horas)} h"
            o["alinhar"].append(f"religamento de {dur}: conferir as datas")
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


# O Fracttal refez as Pharmas depois de 22/09/2026 (Levi, 22/10/2026: "No novo se diferencia por cabine, nos antigo é nome
# mesmo"): os sites "Thopen - Pharmas 2/3/4 - PR" (PHS200/300/400) viraram UM, "Thopen - Pharmas - PR" (THPN-PHS100), com a
# CABN2, CABN3 e CABN4 e os inversores INVR2.x, INVR3.x e INVR4.x. A cabine N é a usina N inteira (cada Pharma tem uma UG
# só no BD) e o inversor N.M do Fracttal é o inversor 1.M da usina N no BD (o código da plataforma já registrava
# THPN-PHS100-INVR2.1 = o 1.1 da Pharma II). O nome antigo segue casando pela "Usina Fractall" da aba, como sempre.
SITES_POR_CABINE = {"THPN-PHS100": {2: "Pharma II", 3: "Pharma III", 4: "Pharma IV"}}


def _escopo_por_cabine(o, usinas):
    """(True, escopo ou None) quando o ativo é de um site de SITES_POR_CABINE; (False, None) quando não é."""
    code = o["code"]
    base = next((b for b in SITES_POR_CABINE if code == b or code.startswith(b + "-")), None)
    if base is None:
        return False, None
    mapa = {n: u for n, u in SITES_POR_CABINE[base].items() if u in usinas}

    def _usina(n, oque):
        u = mapa.get(n)
        if u is None:
            o["excl"] = f"{oque} do site {base} sem usina no cadastro"
            return None
        if not (usinas[u].pot and usinas[u].pot > 0):
            o["excl"] = f"usina '{u}' sem potência no BD"
            return None
        return u

    m = re.search(r"-D?INVR?(\d+)\.(\d+)$", code)
    if m:
        u = _usina(int(m.group(1)), f"inversor {m.group(1)}.{m.group(2)}")
        if u is None:
            return True, None
        U, num = usinas[u], f"1.{m.group(2)}"
        kwp = U.invs.get(num) or U.pot_inv_media()
        o["flags"].append(f"site refeito por cabine: inversor {m.group(1)}.{m.group(2)} do Fracttal = {num} de '{u}'")
        return True, [(u, "inversor", f"inv{num}", min(kwp, U.pot))]
    m = re.search(r"-(" + "|".join(SUF_CABINE) + r")(\d+)$", code)
    if m:
        u = _usina(int(m.group(2)), f"cabine {m.group(2)}")
        if u is None:
            return True, None
        o["flags"].append(f"site refeito por cabine: cabine {m.group(2)} = usina '{u}' inteira")
        return True, [(u, "usina", "ufv", usinas[u].pot)]
    if code == base:
        evs = [(u, "usina", "ufv", usinas[u].pot) for u in mapa.values() if usinas[u].pot and usinas[u].pot > 0]
        if evs:
            o["flags"].append(f"site refeito por cabine: a raiz {base} vale para as usinas dele")
            return True, evs
        o["excl"] = f"nenhuma usina do site '{o['g1']}' tem potência no BD"
        return True, None
    o["excl"] = f"ativo não é de geração ou não mapeável: '{code}' ({o['item'][:40]})"
    return True, None


def escopo_os(o, usinas, idx):
    """→ lista [(usina, nivel, chave, kwp)]; None = exclusão (o motivo fica em o['excl'])."""
    code = o["code"]
    if norm(o["g1"]).startswith("GRID CO") or code == "GRID":
        o["excl"] = "site 'Grid Co.' = usina de terceiros sem contrato (fora do parque)"
        return None
    aplica, esc = _escopo_por_cabine(o, usinas)
    if aplica:
        return esc
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
                o["alinhar"].append(f"site agrupado sem a usina na descrição: contei a cabine na 1ª ({alvo})")
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
                o["alinhar"].append("site agrupado sem a usina na descrição: contei o grupo inteiro")
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


def _varrer(eventos, usinas, per_fim, det_os_usina=None, det_os_dia=None):
    """Linha do tempo por usina → (h_eq, kwh, det_os) por dia. Hierarquia usina > cabine >
    inversor e teto de 100% da usina. Chamada 3×: total, só queda, só equipamento.
    `det_os_usina` (dict, opcional) recebe a MESMA parcela do det_os separada por (folio, usina): a perda de cada OS em
    cada usina, que o drill-down da tela por cliente mostra (Levi, 13/10/2026: "ao clicar na usina aparecerá as OSs").
    Repartir a perda da OS pela potência erra quando o teto de 100% pega uma usina e não a outra (e, até 15/10/2026,
    quando a geração desmentia o dia numa só): em setembro/26 a Rodrigues 1 e 2 trocavam ~47,9 MWh entre si por essa
    conta.
    `det_os_dia` (dict, opcional) recebe a parcela de cada OS em cada DIA, em horas equivalentes, e os trechos (de, até)
    das 06–18 h em que ela foi dona da perda: {(usina, dia, folio): {"h", "trechos"}}. Somadas, as parcelas do dia dão
    o h_eq do dia, porque saem desta MESMA conta (Dashboard Thopen, Levi 14/10/2026: "A partir de outubro quero os
    comentários 100% OS Fracttal. Comentários e disponibilidade!"). Refazer a conta fora daqui errava: a OS de usina
    inteira da Canarana 1 de 08 a 12/10 virava "usina parada o dia todo" ao lado de 87,5% (naquela época a geração
    desmentia esses dias e só o inversor 1.8 contava); e a OS de cabine coberta por uma de usina não tira nada além da
    de usina."""
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
                    parte = kw_af * (e["kwp"] / tot_kw) * h
                    det_os[e["o"]["folio"]] += parte
                    if det_os_usina is not None:
                        det_os_usina[(e["o"]["folio"], u)] += parte
                    if det_os_dia is not None:
                        js = datetime(dia.year, dia.month, dia.day, SOL_INI_H)
                        jf = datetime(dia.year, dia.month, dia.day, SOL_FIM_H)
                        x = det_os_dia.setdefault((u, dia, e["o"]["folio"]), {"h": 0.0, "trechos": []})
                        x["h"] += frac_af * (e["kwp"] / tot_kw) * h
                        x["trechos"].append((max(a, js), min(b, jf)))
    return h_eq, kwh, det_os


def _os_do_dia(det_os_dia):
    """{(usina, dia): [{"folio", "h", "trechos"}]} a partir do det_os_dia do `_varrer`: a parcela (horas equivalentes, 3
    casas) e os trechos das 06–18 h, juntando os que se encostam ("06:00-08:06; 10:55-12:05"). Pela ordem do 1º trecho;
    parcela que não chega a 0,001 h fica fora (não diz nada e não muda o dia)."""
    out = defaultdict(list)
    for (u, dia, folio), x in det_os_dia.items():
        if x["h"] < 0.0005:
            continue
        tr = []
        for de, ate in sorted(x["trechos"]):
            if tr and de <= tr[-1][1]:
                tr[-1][1] = max(tr[-1][1], ate)
            else:
                tr.append([de, ate])
        out[(u, dia)].append({"folio": folio, "h": round(x["h"], 3),
                              "trechos": "; ".join(f"{de:%H:%M}-{ate:%H:%M}" for de, ate in tr), "_ini": tr[0][0]})
    for lst in out.values():
        lst.sort(key=lambda r: (r["_ini"], str(r["folio"])))
        for r in lst:
            r.pop("_ini")
    return dict(out)


def _disp_por_inversor(eventos, usinas, per_fim, tot_h):
    """Disponibilidade POR INVERSOR, com a CASCATA da cabine (pedido do Levi, 14/09/2026): uma OS de
    USINA derruba todos os inversores; uma de CABINE derruba os inversores daquela cabine (mapa
    inversor→UG da coluna 'Equipamento Parente' da aba Equipamentos = `inv_ug`); uma de INVERSOR só
    ele. União das janelas por inversor (duas OS sobrepostas não somam além do período coberto — é a
    mesma varredura por bordas do `_varrer`, mas por inversor). Só usinas com catálogo por inversor.
    → {usina: [ {inversor, disp, h_perdidas}, ... ]} (pior disp primeiro)."""
    por_usina = defaultdict(list)
    for e in eventos:
        por_usina[e["usina"]].append(e)
    out = {}
    for u, U in usinas.items():
        if not U.invs:
            continue
        inv_keys = list(U.invs.keys())
        ev_por_inv = {k: [] for k in inv_keys}
        for e in por_usina.get(u, []):
            nivel, chave = e["nivel"], (e.get("chave") or "")
            if nivel == "usina":
                alvo = inv_keys
            elif nivel == "cabine":
                m = re.match(r"cab(\d+)$", chave)
                ncab = int(m.group(1)) if m else None
                alvo = [k for k in inv_keys if U.inv_ug.get(k) == ncab]
            elif nivel == "inversor":
                num = chave[3:] if chave.startswith("inv") else ""
                alvo = [num] if num in U.invs else []
            else:
                alvo = []
            for k in alvo:
                ev_por_inv[k].append(e)
        linhas = []
        for k in inv_keys:
            evs = ev_por_inv[k]
            h_down = 0.0
            if evs:                                   # bordas → cada fatia conta uma vez (união)
                bordas = sorted({e["ini"] for e in evs} | {e["fim"] for e in evs})
                for i in range(len(bordas) - 1):
                    a, b = bordas[i], bordas[i + 1]
                    if any(e["ini"] <= a and e["fim"] >= b for e in evs):
                        h_down += sum(horas_solares_por_dia(a, b, per_fim).values())
            linhas.append({"inversor": "Inversor " + k, "cabine": U.inv_ug.get(k),
                           "disp": round(100.0 * (1 - h_down / tot_h), 2) if tot_h else None,
                           "h_perdidas": round(h_down, 2)})
        linhas.sort(key=lambda x: (x["disp"] if x["disp"] is not None else 1e9))
        out[u] = linhas
    return out


# ══ cálculo principal ════════════════════════════════════════════════════════
# Exclusão que não é erro de OS: cancelada e site de terceiros. As outras (sem data de evento, concluída sem fim, site
# ou ativo que o cadastro não reconhece) vão para a lista `alinhar`.
_EXCL_QUE_NAO_E_ERRO = ("OS cancelada", "site 'Grid Co.'")


def _para_alinhar(oss, os_escopo, per_ini, per_fim):
    """As OS do período que precisam de um olho humano no Fracttal, com o motivo — só pelo dado do próprio Fracttal
    (Levi, 15/10/2026: "pode até apontar possíveis erros em criação de OS porém não quero que cruze dados de geração").
    A OS fora da conta entra pelo dia do evento (ou da criação, quando nem evento tem)."""
    out = []
    for o in oss:
        if o["excl"]:
            if o["excl"].startswith(_EXCL_QUE_NAO_E_ERRO):
                continue
            # pelo intervalo da OS quando ela tem as duas datas (a 13489, de 12/09 a 06/10, tocava outubro e não aparecia),
            # senão pelo dia do evento ou da criação
            a_, b_ = o.get("ini") or o.get("criada"), o.get("fim") or o.get("ini") or o.get("criada")
            if not a_ or b_ < per_ini or a_ >= per_fim:
                continue
            motivo = f"fora da conta: {o['excl']}"
        elif o.get("alinhar"):
            motivo = "; ".join(dict.fromkeys(o["alinhar"]))
        else:
            continue
        out.append({"folio": o["folio"], "motivo": motivo, "tipos": o["tipos"], "g1": o["g1"], "code": o["code"],
                    "desc": o["desc"][:90], "criado_por": o["criado_por"],
                    "usinas": sorted({u for (u, _n, _c, _k) in os_escopo.get(o["folio"], [])}),
                    "ini": o["ini"].isoformat() if o.get("ini") else None,
                    "fim": None if o.get("aberta_sem_fim") or not o.get("fim") else o["fim"].isoformat(),
                    "criada": o["criada"].isoformat() if o.get("criada") else None,
                    "dias_aberta": o.get("dias_aberta")})
    out.sort(key=lambda a: (a["ini"] or a["criada"] or "", a["folio"]))
    return out


def _parque(usinas):
    """SÓ FULL O&M (decisão do Levi, 30/08): onde a Grid Co. não faz a manutenção completa, a disponibilidade não é
    responsabilidade nossa e as OSs do Fracttal não contam a história toda."""
    return {u: U for u, U in usinas.items()
            if U.fracttal and (U.pot or 0) > 0 and u not in PARQUE_EXCLUI
            and norm(U.full_om).startswith("S")}


def calcular_pelo_bd(dias_por_usina, linhas_equip, per_ini, per_fim):
    """Mês de SETEMBRO PARA TRÁS, só a Thopen, pela "Disponibilidade Usina (%)" diária do BD_Thopen (Levi, 15/10/2026:
    "setembro para trás vamos considerar o que está no BD_Thopen"; fora da Thopen, "só a partir de outubro!").
    dias_por_usina = {usina do cadastro: {dia (data ou 'AAAA-MM-DD'): disponibilidade em fração (0,9139) ou em %}}.
    Mesmo formato do `calcular` (a tela e o Gerencial leem igual), com `fonte` = "BD_Thopen"; o BD não separa queda de
    equipamento nem guarda OS, então esses campos vêm vazios. Dia sem número no BD não entra (nem como 100%)."""
    usinas, lacunas = montar_catalogo(linhas_equip)
    ini_d, fim_d = per_ini.date(), per_fim.date()
    res_usinas, diario = [], {}
    for u, U in sorted(_parque(usinas).items()):
        vals = {}
        for d, v in (dias_por_usina.get(u) or {}).items():
            d = d if hasattr(d, "isoformat") and not isinstance(d, str) else datetime.strptime(str(d)[:10], "%Y-%m-%d")
            d = d.date() if isinstance(d, datetime) else d
            if not (ini_d <= d < fim_d) or not isinstance(v, (int, float)) or v != v:
                continue
            pct = float(v) * 100.0 if float(v) <= 1.5 else float(v)       # a planilha guarda fração; aceita %
            vals[d] = min(100.0, max(0.0, pct))
        if not vals:
            continue
        h_dia = {d: 12.0 * (1 - p / 100.0) for d, p in vals.items()}
        ph = sum(h_dia.values())
        res_usinas.append({"usina": u, "cliente": U.cliente, "fracttal": U.fracttal, "full_om": U.full_om,
                           "pot_kwp": round(U.pot, 1), "fonte_pot": U.fonte_pot, "n_inv": U.n_inv, "n_cab": U.n_cab,
                           "disp": round(100.0 * (1 - ph / (12.0 * len(vals))), 2), "h_perdidas": round(ph, 2),
                           "kwh": round(U.pot * ph),
                           "disp_queda": None, "h_queda": None, "kwh_queda": None,
                           "disp_equip": None, "h_equip": None, "kwh_equip": None,
                           "n_os": 0, "inversores": [], "dias_bd": len(vals)})
        diario[u] = {d.isoformat(): {"h_eq": round(h, 3), "disp": round(vals[d], 1), "kwh": round(U.pot * h),
                                     "h_q": None, "h_e": None}
                     for d, h in sorted(h_dia.items())}
    por_cli = defaultdict(list)
    for r in res_usinas:
        por_cli[r["cliente"] or "—"].append(r)
    clientes = [{"cliente": nome, "kwp": round(sum(r["pot_kwp"] for r in rs)),
                 "disp": round(sum(r["pot_kwp"] * r["disp"] for r in rs) / sum(r["pot_kwp"] for r in rs), 2),
                 "kwh": sum(r["kwh"] for r in rs), "disp_queda": None, "kwh_queda": None,
                 "disp_equip": None, "kwh_equip": None, "n_os": 0, "n_usinas": len(rs),
                 "abaixo99": sum(1 for r in rs if r["disp"] < 99)}
                for nome, rs in sorted(por_cli.items())]
    return {"fonte": "BD_Thopen",
            "periodo": {"ini": per_ini.isoformat(), "fim": per_fim.isoformat(), "dias": (fim_d - ini_d).days},
            "usinas": res_usinas, "clientes": clientes, "diario": diario, "oss": [], "alinhar": [],
            "lacunas": lacunas}


def calcular(wos, linhas_equip, per_ini, per_fim, agora=None, pot_reserva=None, vereditos=None):
    """wos = {folio: [tasks...]} (varredura crua do Fracttal); linhas_equip = aba Equipamentos.
    per_ini/per_fim = janela do mês (fim EXCLUSIVO, já cortado em D-1 pelo chamador). vereditos = {folio: 'parada' |
    'comunicacao'} das subtarefas das OS de comunicação (o worker lê; 26/10/2026).
    → payload completo: usinas, clientes, diário, OSs, `alinhar`, lacunas. Só o Fracttal: a geração não entra."""
    agora = agora or datetime.now()
    usinas, lacunas = montar_catalogo(linhas_equip, pot_reserva)
    idx = indices_g1(usinas)
    n_dias = (per_fim.date() - per_ini.date()).days
    tot_h = 12.0 * n_dias

    oss, eventos, os_escopo = [], [], {}
    for folio, tasks in wos.items():
        o = consolidar_os(folio, tasks, agora, vereditos)
        if o is None:
            continue
        if not o["excl"] or o["excl"] == EXCL_COMUNICACAO:
            if o["fim"] < per_ini or o["ini"] >= per_fim:
                continue                             # não toca o período — fora do universo
        oss.append(o)
        if o["excl"]:
            # a de falta de comunicação fica fora da conta, mas a lista e a tela dizem de qual usina ela é (o escopo numa
            # cópia: ele não mexe na OS, que segue com o motivo dela)
            if o["excl"] == EXCL_COMUNICACAO:
                esc = escopo_os({**o, "excl": None, "flags": [], "alinhar": []}, usinas, idx)
                if esc:
                    os_escopo[o["folio"]] = esc
            continue
        esc = escopo_os(o, usinas, idx)
        if esc is None:
            continue
        if o["folio"] in ESCOPO_COS:                     # o COS diz qual usina do site parou (16498, 26/10/2026)
            esc = [e for e in esc if not escopo_cos_exclui(o["folio"], e[0])]
            o["flags"].append("escopo pelo COS: só %s — %s" % (", ".join(ESCOPO_COS[o["folio"]][0]),
                                                              ESCOPO_COS[o["folio"]][1]))
            if not esc:
                continue
        os_escopo[o["folio"]] = esc
        a, b = max(o["ini"], per_ini), min(o["fim"], per_fim)
        if b <= a:
            continue
        for (u, nivel, chave, kwp) in esc:
            eventos.append({"usina": u, "nivel": nivel, "chave": chave, "kwp": kwp, "ini": a, "fim": b, "o": o})

    det_os_usina, det_os_dia = defaultdict(float), {}
    h_eq, kwh, det_os = _varrer(eventos, usinas, per_fim, det_os_usina, det_os_dia)
    os_do_dia = _os_do_dia(det_os_dia)
    # a OS com evento na usina entra na conta dela mesmo sem hora de sol (é o que o n_os conta): fica com 0 kWh. A
    # aberta sem data final também conta, até o fim do período (15/10/2026)
    for e in eventos:
        det_os_usina[(e["o"]["folio"], e["usina"])] += 0.0
    kwh_os_usina = defaultdict(dict)
    for (folio, u), v in sorted(det_os_usina.items()):
        kwh_os_usina[folio][u] = round(v)
    # decomposição por origem: mesma varredura, só com os eventos de cada família
    h_qd, kwh_qd, _ = _varrer([e for e in eventos if e["o"]["origem"] == "queda"], usinas, per_fim)
    h_eq_ip, kwh_ip, _ = _varrer([e for e in eventos if e["o"]["origem"] == "equipamento"],
                                 usinas, per_fim)
    disp_inv = _disp_por_inversor(eventos, usinas, per_fim, tot_h)   # por inversor, com cascata da cabine (Levi 14/09)

    os_h = {}
    for o in oss:
        if o["excl"]:
            continue
        a, b = max(o["ini"], per_ini), min(o["fim"], per_fim)
        os_h[o["folio"]] = round(sum(horas_solares_por_dia(a, b, per_fim).values()), 2) if b > a else 0.0
    alinhar = _para_alinhar(oss, os_escopo, per_ini, per_fim)

    # SÓ FULL O&M (decisão do Levi, 30/08): onde a Grid Co. não faz a manutenção completa, a
    # disponibilidade não é responsabilidade nossa e as OSs do Fracttal não contam a história
    # toda. Vale para o parque, para o resumo por cliente e para o diário.
    parque = _parque(usinas)
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
                           "n_os": len({e["o"]["folio"] for e in eventos if e["usina"] == u}),
                           "inversores": disp_inv.get(u, [])})

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
        "fonte": "Fracttal",
        "periodo": {"ini": per_ini.isoformat(), "fim": per_fim.isoformat(), "dias": n_dias},
        "usinas": res_usinas,
        "clientes": res_clientes,
        "diario": {u: {d.isoformat(): {"h_eq": round(h, 3),
                                       "disp": round(100 * (1 - h / 12), 1),
                                       "kwh": round(kwh[u].get(d, 0)),
                                       # decomposição do dia (card da célula do mapa)
                                       "h_q": round(h_qd[u].get(d, 0.0), 3),
                                       "h_e": round(h_eq_ip[u].get(d, 0.0), 3),
                                       # as OS que formaram o dia, com a parcela de cada uma (14/10/2026)
                                       "os": os_do_dia.get((u, d), [])}
                       for d, h in sorted(dias.items())} for u, dias in h_eq.items()},
        "oss": [{**{k: o.get(k) for k in ("folio", "tipos", "origem", "code", "item", "g1",
                                          "desc", "flags", "excl", "aberta", "criado_por",
                                          "responsavel", "dias_aberta")},
                 "ini": o["ini"].isoformat() if o.get("ini") else None,
                 "criada": o["criada"].isoformat() if o.get("criada") else None,
                 # a aberta sem data final conta até o fim do período, mas não TERMINOU: sem fim na saída
                 "fim": o["fim"].isoformat() if o.get("fim") and not o.get("aberta_sem_fim") else None,
                 "usinas": sorted({u for (u, _n, _c, _k) in os_escopo.get(o["folio"], [])}),
                 # discriminação do cálculo (card do dia): o que foi afetado e com quantos kWp
                 "escopo": [{"usina": u, "nivel": n, "rotulo": _rotulo_escopo(n, c),
                             "kwp": round(k, 1)}
                            for (u, n, c, k) in os_escopo.get(o["folio"], [])],
                 "h_solar": os_h.get(o["folio"], 0.0),
                 "kwh": round(det_os.get(o["folio"], 0.0)),
                 # a perda desta OS em cada usina da conta dela ({usina: kWh}; soma o `kwh`): o drill-down por usina
                 "kwh_usina": dict(kwh_os_usina.get(o["folio"]) or {})} for o in oss],
        "alinhar": alinhar,
        "lacunas": lacunas,
    }
