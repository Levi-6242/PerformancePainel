# -*- coding: utf-8 -*-
"""Operação no Mês (Dashboard Thopen, 08/10/2026): strings com saída, trackers parados e a zeladoria da usina.

Pedido do Levi: "quantas strings tiveram saída naquele mês para aquela usina e quantos trackers pararam (trackers
distintos)" + "o nível de zeladoria" das rondas do Nexus. Mockup aprovado em 08/10: card no Diário, só de 10/2026 em
diante, com a frase de cada nível da régua. Tudo aqui é puro (sem rede, sem Flask): a leitura mora em `fonte_operacao`
e a rota em `dashboard_thopen`.
"""
import datetime as dt
import re
import unicodedata
from collections import defaultdict

DESDE = (2026, 10)          # Levi, 08/10: "somente a partir de outubro"
FUSO_H = -3                 # Brasília (sem horário de verão desde 2019); as rondas chegam em UTC
CLIENTE = "Thopen"          # as 4 carteiras do 5080 são do cliente Thopen nas falhas; a Ipixuna do Pará é da 2C

# A régua das rondas: 5 níveis e a frase de cada um (cartão "A régua: cinco níveis", Levi, 08/10/2026).
# As frases moram SÓ aqui: a rota manda para a tela, que não as repete (duas cópias divergem).
REGUA = {
    "sujidade": {1: "Vidro limpo, escuro e com reflexo",
                 2: "Sujeira leve ou pontual: manchas, escorrido, dejeto",
                 3: "Película visível, mas o módulo ainda aparece escuro",
                 4: "Camada densa e uniforme, módulo fosco e acinzentado",
                 5: "Camada grossa de poeira/terra, cor da célula some"},
    "vegetacao": {1: "Área roçada, grama rente, corredor limpo",
                  2: "Vegetação baixa, com poucos pontos mais altos",
                  3: "Mato médio e uniforme, ainda abaixo da borda dos módulos",
                  4: "Mato alto e denso, encostando na borda inferior dos módulos",
                  5: "Mato na altura ou acima dos módulos, sombreando e fechando o corredor"},
}

# Nome nas falhas (o canônico da plataforma) → nome do 5080 (a coluna Usina do BD_Thopen). Medido em 08/10 contra o
# workbook falhas_performance: só estes não casavam pelo nome sem acento (o "Corrego do Sapucaia" casa pela chave sem
# acento). A Ouro Branco (um nome nas falhas, I a V no 5080) fica de fora até haver de-para por plant_id.
ALIAS_FALHAS = {"Marajoara I": "Marajoara 1", "Piracicaba I": "Piracicaba 1",
                "Nova Londrina 1": "Nova Londrina", "Nova Londrina 2": "Nova Londrina",
                "Primavera 1": "Primavera", "Primavera 2": "Primavera",
                "Santo Antonio do Platina": "Santo Antonio da Platina"}

# O que a rota devolve — e NADA além disto (o 5080 é público, sem senha). Rodada 2 (08/10, tarde): `por_dia` (a
# tabela do Diário, uma linha por dia) e `avisos` (textos curtos para a nota do card) — nunca número de OS nem texto
# da OS: o número da OS só serve, na memória do servidor, para não contar a mesma OS duas vezes.
CHAVES = ("disponivel", "motivo", "usina", "ano", "mes", "strings", "trackers", "zeladoria", "regua",
          "parcial_ate", "atualizado_em", "por_dia", "avisos",
          # rodada 4 (09/10/2026): a disponibilidade do mês pela régua do Gerencial e para onde a contestação vai
          "disponibilidade", "contestar",
          # 23/10/2026: o trip das OS ainda chegando do Fracttal (trip_os): a tela relê em alguns segundos
          "trip_pendente",
          # 30/10/2026: de onde vêm a disponibilidade e o comentário do dia ("os" ou "bd_comentarios": as usinas que a
          # Ronda COS não cobre, pelos comentários do BD_Thopen, disp_comentarios.py)
          "fonte_disp")

# Outubro de 2026 (Levi, 08/10: "adapte todas desse mês, do nosso lado, sem tocar no Fracttal"): OS de string sem
# quantidade nem citação foi completada pela plataforma com as strings que a régua viu sem corrente naquele inversor no
# dia do evento (`origem = estimado`). O cliente fica sabendo que parte do número é estimativa nossa.
AVISO_ESTIMADO = "parte das strings estimada pela Grid (OS sem quantidade)"
# `comunicou` da aba trackers_dia: "sim" = a usina comunicou no dia; "sem prova" = o dia corrente sem a geração fechada
# (conta: não é falha de comunicação comprovada — decisão do orquestrador, 08/10). Vazio conta, como o dias_comunicou
# vazio dos episódios; qualquer outro valor (um "não" que escape da plataforma) fica fora.
COMUNICOU_CONTA = ("sim", "sem prova", "")

# Zeladoria de usina sem ligação no de-para do cadastro do Nexus. Não é "sem leitura no mês" (revisão de 08/10: 13
# usinas do 5080 vêm sem usina_id no de-para — Ouro Branco I a V, AP. do Taboado, Lyon... — e a Ouro Branco 1 teve 3
# rondas em 09/2026): a tela mostra "—", o estado de "não sabemos", e não um "não houve ronda" falso.
SEM_CADASTRO = {"sem_cadastro": True}

_ROT = (("sujidade dos modulos", "sujidade"), ("altura da vegetacao", "vegetacao"))
_INTEIRO_TXT = re.compile(r"\d+(?:\.0+)?")


def chave(nome):
    """Nome para comparar: sem acento, minúsculo, espaços simples ('Córrego' = 'Corrego')."""
    s = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError, OverflowError):
        return None


def _data(v):
    """'AAAA-MM-DD' (ou com hora depois) → date; o resto → None (sem data não dá para pôr a OS num dia)."""
    try:
        return dt.date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _qtd(v):
    """Quantidade de strings de uma OS: inteiro ≥ 0, ou None (vazio, quebrado ou negativo — nunca vira 0)."""
    if v is None or isinstance(v, bool) or str(v).strip() == "":
        return None
    try:
        f = float(str(v).strip().replace(",", "."))
    except ValueError:
        return None
    return int(f) if f.is_integer() and f >= 0 else None


def _lista(v):
    """'Ipv3, Ipv7' → ['ipv3', 'ipv7']: sem espaço e minúsculo, porque a mesma string vem 'IPV 3' numa OS e 'Ipv3'
    noutra (o texto é digitado no campo). Vírgula ou ponto e vírgula separam."""
    return [x for x in (re.sub(r"\s+", "", chave(p)) for p in re.split(r"[,;]", str(v or ""))) if x]


def nivel(v):
    """1 a 5, ou None ("Não se aplica", vazio, quebrado ou fora da escala nunca vira 0 nem vira outro nível).

    Só aceita número inteiro: "1.05" não pode virar 1 nem "2,5" virar 2 — o nível vai para o cliente com a frase."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        s = str(v).strip()
        if not _INTEIRO_TXT.fullmatch(s):
            return None
        f = float(s)
    if not f.is_integer() or not 1 <= f <= 5:
        return None
    return int(f)


def ler_respostas(texto):
    """{sujidade, vegetacao} do texto de respostas da ronda com OS, como o App escreve: "Sujidade dos módulos: 4;
    Altura da vegetação: 2; ...". O resto do texto (vala, sensores, portaria) não interessa ao card."""
    out = {"sujidade": None, "vegetacao": None}
    for parte in str(texto or "").split(";"):
        rot, sep, val = parte.rpartition(":")
        if not sep:
            continue
        k = next((k for p, k in _ROT if chave(rot).startswith(p)), None)
        if k:
            out[k] = nivel(val.strip())
    return out


def _brt(utc):
    return utc + dt.timedelta(hours=FUSO_H)


def rondas_com_os(linhas):
    """As rondas já lidas (livro do App, rondas_cliente.da_app; até 09/10 era o campo_nexus · rondas) → [{usina_id,
    quando (Brasília), sujidade, vegetacao}]. Uma por usina + dia + início + fim (no campo_nexus a mesma ronda vinha em
    2–3 OS). dia e hora_inicio são UTC (o Início do App é ISO em UTC; conferido em 08/10: +180 min em 594 de 594)."""
    vistas, out = set(), []
    for r in linhas or []:
        uid, dia, hi = _int(r.get("usina_id")), str(r.get("dia") or "")[:10], str(r.get("hora_inicio") or "")[:5]
        k = (uid, dia, hi, str(r.get("hora_fim") or "")[:5])
        if uid is None or k in vistas:
            continue
        vistas.add(k)
        try:
            utc = dt.datetime.strptime(f"{dia} {hi}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue                          # sem hora não dá para saber o dia em Brasília: não chuta
        out.append({"usina_id": uid, "quando": _brt(utc), "sujidade": nivel(r.get("sujidade")),
                    "vegetacao": nivel(r.get("vegetacao"))})
    return out


def rondas_sem_os(linhas):
    """nexus_rondas_checklist · fato_checklist_ronda → o mesmo formato. `inicio` é ISO em UTC ("...Z")."""
    out = []
    for r in linhas or []:
        uid = _int(r.get("usina_id"))
        try:
            utc = dt.datetime.strptime(str(r.get("inicio") or "").replace(" ", "T")[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
        if uid is not None:
            out.append({"usina_id": uid, "quando": _brt(utc), "sujidade": nivel(r.get("sujidade")),
                        "vegetacao": nivel(r.get("vegetacao"))})
    return out


def _nomes(nome):
    """O nome do 5080 e os nomes que viram ele (os aliases), todos como chave."""
    alvo = chave(nome)
    return {alvo} | {chave(a) for a, b in ALIAS_FALHAS.items() if chave(b) == alvo}


def ids_da_usina(de_para, nome):
    """usina_id(s) do nome do 5080 pelo de-para do cadastro do Nexus (sistema "BD_Thopen · Dados Gerais Usinas").
    N:N: Primavera e Nova Londrina têm dois ids; Coração 1 e 2 dividem um. Sem ligação = vazio (nunca chutar ID)."""
    nomes = _nomes(nome)
    return {u for u, ext in ((_int(r.get("usina_id")), r.get("chave_externa")) for r in de_para or [])
            if u is not None and chave(ext) in nomes}


def zeladoria(rondas, ids, ano, mes):
    """A última ronda do mês com nível lido nas usinas dos ids (a mesma régua do Relatório Semanal e do Nexus)."""
    melhor = None
    for r in rondas:
        q = r["quando"]
        if r["usina_id"] not in ids or (q.year, q.month) != (ano, mes):
            continue
        if r["sujidade"] is None and r["vegetacao"] is None:
            continue
        if melhor is None or q > melhor["quando"]:
            melhor = r
    if melhor is None:
        return None

    def item(k):
        n = melhor[k]
        return {"nivel": n, "frase": REGUA[k][n]} if n else None
    return {"data": melhor["quando"].strftime("%d/%m"), "sujidade": item("sujidade"), "vegetacao": item("vegetacao")}


def _e_da_usina(nome):
    """A linha é desta usina do 5080 (pelo nome, com os aliases) e do cliente Thopen? Sem olhar o mês."""
    nomes = _nomes(nome)

    def f(r):
        u = str(r.get("usina") or "").strip()
        return str(r.get("cliente") or "") == CLIENTE and chave(ALIAS_FALHAS.get(u, u)) in nomes
    return f


def _da_usina(nome, m):
    e_da = _e_da_usina(nome)
    return lambda r: str(r.get("mes")) == m and e_da(r)


def _atualizacao(dados, m):
    return next((x for x in dados["atualizacao"] if str(x.get("mes")) == m), None)


def _publicada(a, aba):
    """A plataforma publicou a aba no mês? A contagem na `atualizacao` (mesmo 0) diz que sim; coluna vazia (o mês
    publicado antes de a aba existir) diz que não — e aí o número é "—", nunca um 0 que é "sem dado"."""
    return a is not None and _int(a.get(aba)) is not None


def _no_mes(v, ano, mes):
    d = _data(v)
    return d if d and (d.year, d.month) == (ano, mes) else None


def os_do_mes(dados, nome, ano, mes):
    """[(dia do evento, linha)] das OS de string da usina com o EVENTO no mês — a data do evento da OS no Fracttal é o
    dia da string (Levi, 08/10), e não o mês em que a linha foi publicada. Cancelada fica fora (a mesma regra do
    histórico de OS da plataforma, Levi 26/08: pelo texto do status). A mesma OS lida duas vezes (o mesmo número, a
    mesma usina e o mesmo inversor) é uma só: "soma a quantidade uma vez por OS"."""
    e_da, vistas, out = _e_da_usina(nome), set(), []
    for r in dados.get("strings_os") or []:
        dia = _no_mes(r.get("data_evento"), ano, mes)
        if not dia or not e_da(r) or "cancelad" in chave(r.get("status")):
            continue
        num = str(r.get("os") or "").strip()
        if num:
            k = (num, chave(r.get("usina")), chave(r.get("inversor")))
            if k in vistas:
                continue
            vistas.add(k)
        out.append((dia, r))
    return out


def _conta_strings(oss):
    """Strings de um conjunto de OS: as citadas por nome são DISTINTAS por (usina das falhas, inversor, string) — a
    mesma string em duas OS conta uma vez; a usina entra na chave porque Primavera 1 e 2 (uma Primavera no 5080) têm
    cada uma o seu "Inversor 1.1". OS sem lista soma a quantidade dela. Nenhuma OS com lista ou quantidade → None:
    houve OS e não se sabe quantas strings (um 0 ali seria o zero falso)."""
    distintas, soma, alguma = set(), 0, False
    for _dia, o in oss:
        lst = _lista(o.get("strings"))
        if lst:
            distintas |= {(chave(o.get("usina")), chave(o.get("inversor")), x) for x in lst}
            alguma = True
        elif _qtd(o.get("qtd")) is not None:
            soma += _qtd(o.get("qtd"))
            alguma = True
    return len(distintas) + soma if alguma else None


def disp_por_dia(dados, nome, ano, mes):
    """{dia: disponibilidade %} da usina no mês (rodada 4, Levi 09/10/2026: "calculada pelo Fracttal, da mesma forma
    que calculamos pelo gerencial da plataforma") — a aba disponibilidade_dia que a plataforma publica, um valor por dia
    fechado (o 100 do dia sem OS vem escrito). Liga pelos usina_ids que a leitura achou pelo nome do Fracttal no de-para
    do Nexus; a linha sem ligação casa pelo nome (com os aliases), nunca por parecido. Usina do 5080 com mais de um
    cadastro no Gerencial (Primavera 1 e 2): média do dia ponderada pela potência.

    O NOME vence o site: Aparecida do Taboado 1 e 2, Santarém 1 e 2 e Rodrigues 1 e 2 dividem um site no Fracttal, e
    pelo id as duas recebiam a média das duas (Taboado: 87,53% cada, com o Gerencial dizendo 100% e 78,84%). O valor do
    dia vem das horas perdidas (3 casas), não do % arredondado em 1 casa: a média de dias arredondados errava o mês do
    Gerencial em 0,01–0,02 p.p. Devolve sem arredondar — quem mostra arredonda."""
    ids, nomes = ids_da_usina(dados.get("de_para"), nome), _nomes(nome)
    linhas = [(r, _no_mes(r.get("dia"), ano, mes)) for r in dados.get("disponibilidade_dia") or []]
    linhas = [(r, d) for r, d in linhas if d]
    por_nome = _gerencial_por_nome(dados, nome, ano, mes)
    escolha = [x for x in linhas if _e_da_usina_gerencial(x[0], por_nome, ids, nomes)]
    soma = defaultdict(lambda: [0.0, 0.0])
    for r, dia in escolha:
        try:
            pot = float(r.get("pot_kwp") or 1.0)
            h = r.get("h_perdidas")
            v = 100.0 * (1 - float(h) / 12.0) if h not in (None, "") else float(r.get("disp"))
        except (TypeError, ValueError):
            continue
        soma[dia][0] += v * pot
        soma[dia][1] += pot
    return {d: a / b for d, (a, b) in soma.items() if b > 0}


def _gerencial_por_nome(dados, nome, ano, mes):
    """A usina do 5080 tem linha com o MESMO nome na disponibilidade do Gerencial no mês? Então liga só pelo nome (a
    disponibilidade e as OS); senão, pelos usina_ids que a leitura achou pelo nome do Fracttal."""
    nomes = _nomes(nome)
    return any(chave(r.get("usina")) in nomes for r in dados.get("disponibilidade_dia") or []
               if _no_mes(r.get("dia"), ano, mes))


def _e_da_usina_gerencial(r, por_nome, ids, nomes):
    if por_nome:
        return chave(r.get("usina")) in nomes
    return bool({_int(u) for u in r.get("usina_ids") or []} & ids)


def _quando(v):
    try:
        return dt.datetime.fromisoformat(str(v)[:19])
    except (TypeError, ValueError):
        return None


def _pct(v):
    """20 → "20%"; 1,5 → "1,5%"; abaixo de 1 → "menos de 1%"."""
    if v >= 10:
        return "%d%%" % round(v)
    if v >= 1:
        return ("%.1f%%" % v).replace(".", ",")
    return "menos de 1%"


_TRECHO = re.compile(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*")


def _trechos(txt, dia):
    """"06:00-08:06; 10:55-12:05" (a coluna `trechos` da disponibilidade_os_dia: onde a OS foi dona da perda nas 06–18 h
    daquele dia, na conta do Gerencial) → [(de, até)]. Pedaço que não lê fica fora."""
    out = []
    for p in str(txt or "").split(";"):
        m = _TRECHO.fullmatch(p)
        if not m:
            continue
        a = dt.datetime(dia.year, dia.month, dia.day, int(m[1]), int(m[2]))
        b = dt.datetime(dia.year, dia.month, dia.day, int(m[3]), int(m[4]))
        if b > a:
            out.append((a, b))
    return out


def _dentro(t1, t2):
    """Todo trecho de t1 cabe num trecho de t2?"""
    return bool(t1) and all(any(x <= a and b <= y for x, y in t2) for a, b in t1)


def _usina_inteira(o):
    esc = [e.strip() for e in str(o.get("escopo") or "").split(";") if e.strip()]
    return not esc or esc == ["Usina inteira"]


def _frase_cos(o, alvo, quando):
    """A OS do COS (29/10/2026): o que a Ronda COS registrou, com as proteções que atuaram (Levi: "Nos comentários tem
    que vir as proteções atuadas"; a frase do Trip é a de 23/10/2026). Ex.: "Desligamento Usina Trip 27ABC/86 de 10/10
    às 09:00h a 10/10 às 15:00h; OS 17001" e "Falha de comunicação com a geração parada, Usina de ... ; OS 17002"."""
    prot = "/".join(p.strip() for p in str(o.get("protecoes") or "").split(";") if p.strip())
    alvo += (" Trip %s" % prot) if prot else ""
    n = str(o.get("os") or "").strip()
    if "comunica" in str(o.get("tipo") or "").lower():
        return "Falha de comunicação com a geração parada, %s%s; %s" % (alvo, quando, "OS " + n if n else "sem OS")
    return "Desligamento %s%s; %s" % (alvo, quando, "OS " + n if n else "sem OS")


def _frase_os(o, dia, pot_usina, trip=None):
    """O que a OS tirou NAQUELE dia, na conta do Gerencial (Levi, 14/10/2026: "Como assim continua? preciso de um motivo
    que faça sentido esse valor de 80%"; e, à noite: "A partir de outubro quero os comentários 100% OS Fracttal"). Desde
    15/10/2026 à tarde o texto é curto e leva o nº da OS (o Levi pediu), nunca o texto da OS. Ex.: "Desligamento Cabine 2
    de 09/10 às 16:29h a 13/10 às 18:21h; religamento, OS 15123". A linha só sai no dia em que a OS tirou hora na conta
    (os trechos da disponibilidade_os_dia, onde ela foi dona da perda): o dia em que não tirou (fora da conta, ou coberta
    por outra OS de usina inteira) não tem linha. Nada aqui lê geração: desde 15/10/2026 a disponibilidade é "full
    Fracttal, isolada da geração" (Levi). None = a linha não tem trecho que se leia."""
    # 15/10/2026, tarde (Levi: "Nos comentários podemos diminuir esse texto (...) pode ficar só como: Desligamento
    # Cabine 2 de 09/10 às 16:29h a 13/10 às 18:21h; religamento, OS do Fracttal / invés de OS do fracttal quero o número
    # desse OS"): o que parou, o desligamento inteiro da OS, o tipo e o nº da OS. A linha do dia segue saindo só onde a
    # OS tirou hora na conta (os trechos); o trecho do dia e a parte da potência saíram do texto
    if not _trechos(o.get("trechos"), dia):
        return None
    ini, fim, aberta = _quando(o.get("inicio")), _quando(o.get("fim")), chave(o.get("aberta")) == "sim"
    esc = [e.strip() for e in str(o.get("escopo") or "").split(";") if e.strip()]
    partes = ["Usina"] if not esc or esc == ["Usina inteira"] else esc
    alvo = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]
    tipo = ", ".join(x.strip().lower() for x in str(o.get("tipo") or "").split(";") if x.strip())
    hm = lambda d: d.strftime("%d/%m às %H:%Mh")                      # noqa: E731
    if aberta and ini:
        quando = " desde %s, em aberto" % hm(ini)
    elif ini and fim:
        quando = " de %s a %s" % (hm(ini), hm(fim))
    else:
        quando = ""
    if chave(o.get("fonte")) == "cos":
        return _frase_cos(o, alvo, quando)
    n = str(o.get("os") or "").strip()
    # 23/10/2026 (Levi: "Desligamento Usina Trip X de 13/10 às 17:02h a 14/10 às 07:29h; religamento, OS 16249"): a
    # proteção que atuou, lida da OS no Fracttal (trip_os), logo depois do que parou. Sem proteção, a frase de sempre
    alvo += (" Trip %s" % trip) if trip else ""
    return "Desligamento %s%s; %sOS %s" % (alvo, quando, tipo + ", " if tipo else "", n or "do Fracttal")


def _os_da_usina(dados, nome, ano, mes):
    """({dia: [linha da disponibilidade_os_dia]}, potência da usina) das OS da usina no mês, ou None antes de a aba
    ser publicada no mês. A mesma ligação da disponibilidade (o nome vence o site compartilhado)."""
    m = f"{ano}-{mes:02d}"
    a = next((x for x in dados.get("atualizacao") or [] if str(x.get("mes")) == m), None)
    if not a or _int(a.get("disponibilidade_os_dia")) is None:
        return None
    ids, nomes = ids_da_usina(dados.get("de_para"), nome), _nomes(nome)
    por_nome = _gerencial_por_nome(dados, nome, ano, mes)
    pot = {}
    for r in dados.get("disponibilidade_dia") or []:
        if _no_mes(r.get("dia"), ano, mes) and _e_da_usina_gerencial(r, por_nome, ids, nomes):
            try:
                pot[r.get("usina")] = float(r.get("pot_kwp"))
            except (TypeError, ValueError):
                pass
    dias = defaultdict(list)
    for o in dados.get("disponibilidade_os_dia") or []:
        d = _data(o.get("dia"))
        if str(o.get("mes")) == m and d and (d.year, d.month) == (ano, mes) and _e_da_usina_gerencial(o, por_nome, ids,
                                                                                                         nomes):
            dias[d].append(o)
    return dias, sum(pot.values()) or None


def os_desligamento_do_mes(dados, nome, ano, mes):
    """Os números das OS que explicam os dias da usina no mês (as que o trip_os vai buscar), sem repetir. A OS do COS
    (29/10/2026) já traz as proteções: não vai ao Fracttal."""
    ok = _os_da_usina(dados, nome, ano, mes) if dados else None
    out = []
    for lst in (ok[0].values() if ok else []):
        for o in lst:
            if chave(o.get("fonte")) == "cos":
                continue
            n = str(o.get("os") or "").strip()
            if n and n not in out:
                out.append(n)
    return out


def os_por_dia(dados, nome, ano, mes, trips=None):
    """{dia: [frase da OS]} — o comentário de cada dia, só das OS do Fracttal que formaram a disponibilidade dele (Levi,
    14/10/2026: "A partir de outubro quero os comentários 100% OS Fracttal. Comentários e disponibilidade!"). Vem da
    aba disponibilidade_os_dia, a parcela de cada OS no dia na MESMA conta da disponibilidade_dia: o texto e o número
    contam a mesma história por construção. Em 14/10, no índice real: 1.203 dias-usina com perda (setembro e outubro),
    a soma das parcelas igual à perda do dia em todos, nenhum dia com perda sem OS. A mesma ligação da disponibilidade
    (o nome vence o site compartilhado); a parte da potência é o kWp da OS sobre a das usinas do Gerencial que a usina
    do 5080 junta (Primavera 1 e 2 somam). None = a aba ainda não foi publicada no mês (a tela diz isso; nunca um dia
    "sem OS" que só não chegou). `trips`: {nº da OS: "27/86"} do trip_os (23/10/2026)."""
    ok = _os_da_usina(dados, nome, ano, mes)
    if ok is None:
        return None
    dias, pot_usina = ok
    out, trips = defaultdict(list), trips or {}
    for d in sorted(dias):
        lst = sorted(dias[d], key=lambda o: (str(o.get("trechos") or ""), str(o.get("inicio") or "")))
        tr = [_trechos(o.get("trechos"), d) for o in lst]
        # duas OS de usina inteira para a mesma parada dividem a parcela (Mandaguaçu 11/10/2026: OS abertas uma por cima
        # da outra) e diriam a mesma coisa: a que cabe nos trechos de outra de usina inteira não vira outra linha.
        # Empate: fica a 1ª
        for i, o in enumerate(lst):
            if _usina_inteira(o) and any(j != i and _usina_inteira(y) and _dentro(tr[i], tr[j]) and (j < i or tr[i] != tr[j])
                                         for j, y in enumerate(lst)):
                continue
            frase = _frase_os(o, d, pot_usina, trips.get(str(o.get("os") or "").strip()))
            if frase and frase not in out[d]:
                out[d].append(frase)
    return dict(out)


def ronda_por_dia(rondas, ids, ano, mes):
    """{dia: {sujidade, vegetacao}} — a última ronda de cada dia (Brasília) com algum nível lido, para o comentário do
    dia ("Ronda realizada: vegetação nível 3 e sujidade nível 4", Levi 09/10/2026)."""
    out = {}
    for r in sorted(rondas, key=lambda x: x["quando"]):
        q = r["quando"]
        if r["usina_id"] in ids and (q.year, q.month) == (ano, mes) and (r["sujidade"] or r["vegetacao"]):
            out[q.date()] = {"sujidade": r["sujidade"], "vegetacao": r["vegetacao"]}
    return out


def _junta_dias(por_dia, dsp, rnd, strings, trackers, osd=None):
    """O por_dia das OS e dos trackers + os dias com disponibilidade ou ronda. Dia novo vem com 0 de string/tracker
    quando o mês tem número (None quando não tem — nunca um zero de "sem medição"). `os`: o comentário do dia que ficou
    abaixo de 100% — as OS do Fracttal que o formaram; None = a parcela das OS ainda não publicada no mês (`osd` None)."""
    out = {p["dia"]: dict(p, disp=None, ronda=None, os=[]) for p in por_dia}
    for d in set(dsp) | set(rnd):
        k = d.strftime("%d/%m")
        p = out.setdefault(k, {"dia": k, "strings": 0 if strings is not None else None,
                               "trackers": 0 if trackers is not None else None, "disp": None, "ronda": None,
                               "os": []})
        p["disp"], p["ronda"] = dsp.get(d), rnd.get(d)
        if p["disp"] is not None and p["disp"] < 100:
            p["os"] = None if osd is None else list(osd.get(d) or [])
        else:
            p["os"] = []
    return sorted(out.values(), key=lambda p: (p["dia"][3:5], p["dia"][:2]))


def _trackers_por_dia(dados, nome, ano, mes):
    """{dia: trackers distintos parados no dia} da aba trackers_dia (a plataforma só publica o dia em que a usina
    comunicou). Chave (fonte, plant_id, tracker), como nos episódios: Brodowski são dois cadastros com TRK1..52 cada."""
    e_da, nomes, soma = _e_da_usina(nome), defaultdict(set), defaultdict(int)
    for r in dados.get("trackers_dia") or []:
        dia = _no_mes(r.get("dia"), ano, mes)
        if not dia or not e_da(r) or chave(r.get("comunicou")) not in COMUNICOU_CONTA:
            continue
        lst = [x.strip() for x in re.split(r"[,;]", str(r.get("trackers") or "")) if x.strip()]
        if lst:
            nomes[dia] |= {(r.get("fonte"), str(r.get("plant_id")), x) for x in lst}
        elif _qtd(r.get("qtd")):
            soma[dia] += _qtd(r.get("qtd"))
    return {d: len(nomes[d]) + soma[d] for d in set(nomes) | set(soma) if len(nomes[d]) + soma[d] > 0}


def _conta_tracker(r):
    """Episódio que conta: a usina comunicou em algum dia dele, ou o dia ainda não tem prova (o dia corrente sem a
    geração fechada — decisão do orquestrador, 08/10). dias_comunicou vazio (coluna ainda não publicada) conta."""
    dc = _int(r.get("dias_comunicou"))
    return dc is None or dc > 0 or (_int(r.get("dias_sem_prova")) or 0) > 0


def contar(dados, nome, ano, mes):
    """O card e a tabela do Diário: strings, trackers, por_dia e avisos da usina no mês.

    - Strings (rodada 2, Levi 08/10: "Strings é OS"): das OS de recomposição de string do Fracttal com o evento no mês.
      Sem OS: 0 se a plataforma mede as strings da usina (cobertura) e publicou as OS do mês; senão None ("—").
    - Trackers: DISTINTOS (fonte, plant_id, tracker) dos episódios com a usina comunicando — nunca menos que o de um
      dia da tabela. None sem medição ou sem o detalhe por dia publicado (a tabela diria "0" no dia de uma parada).
    - por_dia: um item por dia com OS (data do evento) ou tracker parado; dia sem ocorrência daquela coisa é 0 quando
      o mês tem número, e None quando não tem."""
    m = f"{ano}-{mes:02d}"
    da, a = _da_usina(nome, m), _atualizacao(dados, m)
    cob = [c for c in dados["cobertura"] if da(c)]

    oss = os_do_mes(dados, nome, ano, mes)
    if oss:
        strings = _conta_strings(oss)
    elif _publicada(a, "strings_os") and any((_int(c.get("dias_strings")) or 0) > 0 for c in cob):
        strings = 0
    else:
        strings = None

    t = {(r.get("fonte"), str(r.get("plant_id")), str(r.get("tracker")).strip())
         for r in dados["trackers_episodios"] if da(r) and _conta_tracker(r)}
    t_dia = _trackers_por_dia(dados, nome, ano, mes)
    med_t = bool(t) or bool(t_dia) or any((_int(c.get("dias_trackers")) or 0) > 0 for c in cob)
    trackers = max(len(t), max(t_dia.values(), default=0)) if med_t and _publicada(a, "trackers_dia") else None

    s_dia = defaultdict(list)
    for dia, o in oss:
        s_dia[dia].append((dia, o))
    por_dia = [{"dia": d.strftime("%d/%m"),
                "strings": _conta_strings(s_dia[d]) if d in s_dia else (0 if strings is not None else None),
                "trackers": (t_dia.get(d, 0) if trackers is not None else None)}
               for d in sorted(set(s_dia) | set(t_dia))]

    avisos = []
    if any(chave(o.get("origem")) == "estimado" for _d, o in oss):
        avisos.append(AVISO_ESTIMADO)
    sem_q = [d for d, o in oss if not _lista(o.get("strings")) and _qtd(o.get("qtd")) is None]
    if sem_q:
        avisos.append("%d OS de string sem quantidade (%s), fora da soma"
                      % (len(sem_q), ", ".join(d.strftime("%d/%m") for d in sorted(set(sem_q)))))
    return {"strings": strings, "trackers": trackers, "por_dia": por_dia, "avisos": avisos}


# Abas conferidas contra a contagem da `atualizacao` (a coluna da contagem tem o nome da aba).
ABAS_CONFERIDAS = ("strings_episodios", "trackers_episodios", "cobertura", "strings_os", "trackers_dia",
                   "disponibilidade_dia", "disponibilidade_os_dia")


def conferir(dados):
    """A leitura bate com a aba `atualizacao`? O sync troca linhas no lugar: lida no meio dele, um episódio pode vir
    duas vezes ou faltar. Diferença = ler de novo — nunca deduplicar (duas linhas iguais podem ser dois trackers de
    cadastros diferentes: Assis, out/2026).

    Mês com linha nas abas e sem linha na `atualizacao` também reprova (revisão de 08/10): aba renomeada, ainda não
    sincronizada ou lida vazia no meio do sync deixava a conferência passar por vacuidade, e a leitura parcial ia para
    o disco como boa. Rodada 2: as OS de string e os trackers por dia entram na mesma conferência (coluna vazia na
    `atualizacao` = aba ainda não publicada naquele mês, nada a conferir)."""
    publicados = {str(a.get("mes")) for a in dados["atualizacao"]}
    for aba in ABAS_CONFERIDAS:
        if any(str(r.get("mes")) not in publicados for r in dados.get(aba) or []):
            return False
    for a in dados["atualizacao"]:
        m = str(a.get("mes"))
        for aba in ABAS_CONFERIDAS:
            esperado = _int(a.get(aba))
            if esperado is None:
                continue                      # coluna que ainda não existia quando o mês foi publicado
            if sum(1 for r in dados.get(aba) or [] if str(r.get("mes")) == m) != esperado:
                return False
    return True


def _mes_info(dados, ano, mes, hoje):
    """(parcial_ate, atualizado_em). O aviso de mês parcial sai do FIM do período publicado, não do relógio: no dia 1º,
    com o fechamento do mês anterior ainda por sair, o mês não pode aparecer como fechado (revisão de 08/10).
    `hoje` fica na assinatura porque a rota o passa; a conta não depende mais dele."""
    a = next((x for x in dados["atualizacao"] if str(x.get("mes")) == f"{ano}-{mes:02d}"), None)
    if not a:
        return None, None
    try:
        fim = dt.date.fromisoformat(str(a.get("periodo_fim") or "")[:10])
    except ValueError:
        fim = None
    ultimo = dt.date(ano + mes // 12, mes % 12 + 1, 1) - dt.timedelta(days=1)
    parcial = fim.strftime("%d/%m") if fim and (fim.year, fim.month) == (ano, mes) and fim < ultimo else None
    return parcial, a.get("atualizado_em")


def resposta(dados, nome, ano, mes, hoje, trips=None, bd=None):
    """A resposta da rota /api/t/operacao — sempre com as chaves de CHAVES, nem uma a mais. `bd` = ({dia: disp %},
    {dia: [linhas]}) dos comentários do BD_Thopen (disp_comentarios.por_dia), no lugar das OS (30/10/2026)."""
    r = dict.fromkeys(CHAVES)
    r.update(usina=nome, ano=ano, mes=mes, disponivel=False, por_dia=[], avisos=[], trip_pendente=False,
             regua={k: {str(n): f for n, f in v.items()} for k, v in REGUA.items()})
    if (ano, mes) < DESDE:
        r["motivo"] = "antes de 10/2026"
        return r
    if dados is None:
        r["motivo"] = "carregando"
        return r
    # Antes de a plataforma publicar o plant_id, contar tracker "distinto" juntaria os dois cadastros da Brodowski (52
    # em vez de 103): melhor nenhum número do que um número pela metade na tela do cliente. Só as linhas DESTA usina
    # contam (revisão de 08/10: uma linha da Athon, da Renogrid ou da 2C sem plant_id travava todas as usinas da
    # Thopen). Rodada 2: vale para os trackers (episódios e por dia); as strings vêm das OS, contadas por usina +
    # inversor + string, e os episódios da régua de 2 h não dão mais número ao card.
    da, e_da = _da_usina(nome, f"{ano}-{mes:02d}"), _e_da_usina(nome)
    sem_pid = (any(x.get("plant_id") in (None, "") for x in dados["trackers_episodios"] if da(x))
               or any(x.get("plant_id") in (None, "") for x in dados.get("trackers_dia") or []
                      if e_da(x) and _no_mes(x.get("dia"), ano, mes)))
    if sem_pid:
        r["motivo"] = "aguardando a plataforma publicar o plant_id"
        return r
    r.update(contar(dados, nome, ano, mes))
    ids = ids_da_usina(dados["de_para"], nome)
    rnd = {}
    if ids:
        # desde 09/10 as rondas sem OS vêm no mesmo livro do App (rondas_com_os, os=None); a chave antiga só existe
        # em dado de teste
        rondas = rondas_com_os(dados["rondas_com_os"]) + rondas_sem_os(dados.get("rondas_sem_os") or [])
        r["zeladoria"] = zeladoria(rondas, ids, ano, mes)
        rnd = ronda_por_dia(rondas, ids, ano, mes)
    else:
        r["zeladoria"] = dict(SEM_CADASTRO)
    # rodada 4: Disp (%) e a ronda do dia na tabela; a disponibilidade do mês é a média dos dias — a mesma conta do
    # Gerencial (12 h por dia: 100·(1 − Σh/12n) é a média dos dias)
    dsp = disp_por_dia(dados, nome, ano, mes) if bd is None else bd[0]
    r["por_dia"] = _junta_dias(r["por_dia"], {d: round(v, 1) for d, v in dsp.items()}, rnd, r["strings"],
                               r["trackers"], os_por_dia(dados, nome, ano, mes, trips) if bd is None else bd[1])
    r["fonte_disp"] = "os" if bd is None else "bd_comentarios"
    if bd is not None:
        # o comentário da equipe vai também no dia que ficou em 100% (a falha de comunicação, que não conta)
        com = {d.strftime("%d/%m"): v for d, v in bd[1].items()}
        for p in r["por_dia"]:
            if com.get(p["dia"]):
                p["os"] = list(com[p["dia"]])
    r["disponibilidade"] = round(sum(dsp.values()) / len(dsp), 2) if dsp else None
    r["parcial_ate"], r["atualizado_em"] = _mes_info(dados, ano, mes, hoje)
    r["disponivel"] = True
    return r
