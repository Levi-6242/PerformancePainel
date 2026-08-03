"""Modelos de SUBTAREFA da OS de inspeção que alimenta um chamado de garantia.

PARTE DO PACOTE `chamado_garantia` — puro, sem PyQt e sem rede, para o app de campo usar o mesmo
conteúdo do OS Creator. Ver o `__init__.py` do pacote.

Para que serve
──────────────
Hoje o chamado nasce torto: o técnico anexa uma foto (às vezes borrada) da plaqueta e mais nada, e
a Singrid tem de garimpar número de série e sintomas na OS para conseguir abrir o ticket no
fabricante. A regra que a Ana fixou na reunião de 29/07 é que **todo chamado nasce de uma OS de
teste** — é teste que se apresenta ao fabricante. Então o jeito de consertar é qualificar a OS de
teste: o supervisor/COS diz ativo e marca, e as subtarefas já descem pedindo exatamente o que
aquele fabricante exige no formulário dele.

Fonte de cada campo
───────────────────
Os 9 documentos de processo da Singrid, em
`4. O&M/11.Pré-Operação/2. Controle/13. Gestão de Chamados/02. Processos de Abertura e
Acompanhamento` (Axial, Canadian Solar, Convert, Huawei, Hukseflux, STI, Soltec, Sungrow, Trina).
Só entra aqui o que o CAMPO tem de coletar. O que é trabalho de escritório — NF com CFOP 5915/6915,
declaração de não contribuinte, planilha SPA da Huawei, formulário RM.R05 da Sigma, endereço de
remessa — fica de fora de propósito: é da Singrid, não do técnico, e poluiria a OS dele.

Complementa o `chamado_spec.py`, que descreve o outro lado (os campos do diálogo de abertura do
chamado). Um mesmo dado pode aparecer nos dois: aqui é o técnico QUE COLETA, lá é quem ABRE.

Tipos de subtarefa
──────────────────
Sondados ao vivo na conta 4987 (1=Texto, 2=Sim/Não, 3=Número, 4=Verificação, 7=Lista). NÃO existe tipo Data nesta conta (o id 3 é
Número), então data/hora vai como texto com o formato na própria pergunta.
"""

# apelido → id_task_form_item_type do Fracttal
TIPO_ID = {
    "texto":  1,    # resposta livre curta
    "longo":  1,    # idem (a conta não tem tipo de texto longo separado)
    "num":    3,    # numérico
    "simnao": 2,    # Sim / Não / N/A
    "verif":  4,    # Aprovado / Alerta / Falhou
    "lista":  7,    # menu de opções (precisa de `opcoes`)
}


def _s(desc, tipo="texto", obrig=True, anexo=False, opcoes=None, chave="", so_para=None):
    """Uma subtarefa. `anexo=True` EXIGE arquivo — é o que impede o velho 'só mandei a foto'
    de virar 'só mandei a foto e nada digitado'.

    `chave` é o campo do `chamado_spec` que esta resposta alimenta. É o que fecha o ciclo: quando
    a inspeção terminar, o diálogo "Abrir chamado" lê as respostas do técnico por essa chave e já
    nasce preenchido — que é exatamente o trabalho manual que a Singrid faz hoje no Claude.

    `so_para` limita a pergunta a certos blocos de ativo. Existe porque a mesma MARCA atende ativos
    diferentes: a STI faz tracker, NCU e RSU, e as perguntas de componente/TCU/painel PV só fazem
    sentido no tracker. Sem isso, uma OS de NCU nascia com 16 subtarefas e DUAS perguntas de número
    de série — a da NCU e a "do componente" (medido em 30/07)."""
    return {"desc": desc, "tipo": tipo, "obrig": obrig, "anexo": anexo, "opcoes": opcoes,
            "chave": chave, "so_para": set(so_para) if so_para else None}


# ── 1. base: vale para qualquer ativo e qualquer marca ────────────────────────────────────────
# A 1ª pergunta é a validação que a Ana pede em toda OS de teste: o ativo está REALMENTE em falha?
# Se voltou sozinho, não há chamado — e a OS morre aqui, o que já é uma resposta útil.
#
# O NÚMERO DE SÉRIE NÃO ENTRA AQUI de propósito. Ele é do bloco do tipo de ativo, porque a
# pergunta muda: no tracker é "de qual componente — NCU, TCU, motor?"; na ETM é o gravado no
# sensor; no inversor é o da etiqueta. Quando a base também pedia, a OS saía com TRÊS perguntas
# de serial (medido ao renderizar o modelo Tracker/STI) — e três linhas parecidas na mão do
# técnico é convite para ele responder qualquer coisa em duas delas.
# Revisão do Levi em 30/07, olhando a lista do inversor na tela. O critério que ele aplicou, e que
# vale para revisar qualquer bloco daqui: **só pergunte ao técnico o que o técnico consegue
# responder em campo**. Saíram:
#   - "O equipamento continua em falha?" — se chegou a virar inspeção para chamado, já houve
#     religamento e não voltou. A resposta seria sempre sim;
#   - "Impacto na geração" e "Equipamento em operação desde" — o técnico não tem essa informação;
#   - "Print do supervisório" — ele está em campo, não no supervisório. Virou foto do alarme NO
#     equipamento, que é o que ele consegue fazer;
#   - "Data e hora da falha" e "Nº de unidades afetadas" — o app já sabe (data do incidente da OS
#     e 1, no caso de inversor). Ver `derivados()`, que entrega isso ao chamado sem gastar uma
#     pergunta.
BASE = [
    _s("Descrição do problema: sintoma observado em campo", "longo", chave="problema"),
    # "Causa da falha" nasceu como "Natureza do problema" dentro do bloco da STI. O Levi pediu o
    # nome novo e a posição COLADA na descrição (30/07) — daí ter subido para a base, o que a faz
    # valer também para inversor e ETM, onde a pergunta faz o mesmo sentido.
    _s("Causa da falha", "lista",
       opcoes=["Elétrica", "Mecânica", "Comunicação", "Desgaste natural", "Causa externa", "Outra"]),
    _s("Ações já realizadas em campo (testes, resets, verificações)", "longo", chave="acoes"),
    _s("Foto do alarme no equipamento, se estiver exibindo algum", "texto", obrig=False,
       anexo=True),
]

# ── 2. por TIPO DE ATIVO — aqui mora a identificação do equipamento ───────────────────────────
# O tipo é o do catálogo do Fracttal (campo `tipo` do ativo), por isso os nomes batem com
# `api.CARTEIRA_EQUIP`.
POR_TIPO = {
    "Inversor": [
        _s("Nº de série do inversor (foto da etiqueta com modelo e série legíveis)",
           "texto", anexo=True, chave="serial"),
        _s("Modelo do inversor", "texto", chave="modelo"),
        _s("ID do alarme exibido", "texto", chave="alarme"),
        _s("Quantas strings o inversor possui", "num", obrig=False),
    ],
    # NÃO existe tipo "Tracker" no catálogo — medido: 0 ativos. O tracker individual
    # ("Tracker 1.100 STI STI-H250", código APG100-ETKR1.100) é do tipo **Estrutura Trackers**,
    # que tem 6.306 ativos: 6.216 trackers individuais e 90 estruturas de planta. Eu havia criado
    # um bloco "Tracker" separado que nunca seria alcançado, e o tracker de verdade cairia no bloco
    # mecânico, sem NCU/TCU/MAC/Modbus. As perguntas eletrônicas foram para os fabricantes de
    # tracker (STI/Brametal/Soltec), porque Axial/Trina/Convert são peça mecânica no mesmo tipo.
    "Estrutura Trackers": [
        _s("Modelo / referência da peça (foto da etiqueta ou da peça)", "texto", anexo=True, chave="modelo"),
        _s("TAG do equipamento na usina (nome e número)", "texto", chave="tag"),
        # "Quantidade de peças afetadas" saiu: a OS é de UM ativo, então é sempre 1 (Levi, 30/07).
        # Vai pelo `derivados()`, igual ao nº de unidades do inversor.
        # ONDE está o problema (Levi, 30/07): o ativo diz QUAL tracker, mas o fabricante precisa da
        # posição em campo — e quando a OS é da estrutura DA PLANTA (e não de um tracker
        # individual, que é o caso de 90 dos 6.306 ativos) essa é a única pista de localização.
        _s("Localização na planta: fileira, posição e nº dos trackers afetados", "texto"),
    ],
    # NCU e RSU são ativos PRÓPRIOS pendurados na Estrutura Trackers DA PLANTA, não de um tracker
    # individual (medido: APG100-NCU1 é filho de APG100-ETKR1; 96 NCU e 105 RSU no catálogo). Daí
    # bloco separado: o que importa é quantos trackers pararam por causa dela, não a peça mecânica.
    "NCU": [
        _s("Nº de série da NCU (foto da etiqueta)", "texto", anexo=True, chave="serial"),
        _s("Onde a NCU está instalada na planta", "texto", anexo=True),
        _s("Quantos trackers dependem desta NCU", "num", obrig=False),
        _s("Trackers afetados: fileira, posição e números", "texto"),
        _s("A NCU energiza / acende LED?", "simnao", obrig=False),
        _s("Testes executados em campo e valores medidos", "longo", chave="testes"),
    ],
    "RSU": [
        _s("Nº de série da RSU (foto da etiqueta)", "texto", anexo=True, chave="serial"),
        _s("Onde a RSU está instalada na planta", "texto", anexo=True),
        _s("Trackers afetados: fileira, posição e números", "texto"),
        _s("A RSU energiza / acende LED?", "simnao", obrig=False),
        _s("Testes executados em campo e valores medidos", "longo", chave="testes"),
    ],
    "Estação Meteorológica": [
        _s("Nº de série gravado no sensor (foto da etiqueta)", "texto", anexo=True, chave="serial"),
        _s("Modelo do sensor", "texto", chave="modelo"),
        _s("Foto da posição exata do sensor na planta — ele volta para o MESMO lugar, "
           "a configuração Modbus é por posição", "texto", anexo=True, chave="posicao"),
        _s("Configuração Modbus (endereço ID, baud rate, paridade)", "texto", obrig=False),
        _s("Acessórios instalados junto (cabo, escudo solar, estrutura, pés)", "longo", obrig=False, chave="acessorios"),
        _s("Leitura atual do sensor no supervisório", "texto", obrig=False),
    ],
    "Cabine": [
        _s("Equipamento da cabine com falha (foto)", "texto", anexo=True),
        _s("Nº de série do equipamento, se houver", "texto", obrig=False, chave="serial"),
        _s("TAG do equipamento na usina (nome e número)", "texto", chave="tag"),
    ],
    "Skid": [
        _s("Equipamento do skid com falha (foto)", "texto", anexo=True),
        _s("Nº de série do equipamento, se houver", "texto", obrig=False, chave="serial"),
        _s("TAG do equipamento na usina (nome e número)", "texto", chave="tag"),
    ],
}

# ── 3. por FABRICANTE: SÓ o que a base e o tipo de ativo ainda não cobrem ─────────────────────
# Lista vazia é resposta legítima: significa que o formulário daquele fabricante não pede nada
# além do que já está sendo coletado (Axial e Trina pedem modelo, série, horário e ações — todos
# já acima). Repetir aqui só produziria pergunta duplicada.
POR_FABRICANTE = {
    # digitalpower.huawei.com — o formulário tem uma caixa própria para "menos de 7 dias",
    # que a Huawei trata à parte
    # "menos de 7 dias" saiu da mão do técnico: o app calcula (ver `derivados`) e o chamado
    # recalcula no dia em que a Singrid abrir. Sobra nada específico da Huawei aqui.
    "Huawei": [],
    # plataforma STI: stepper Projeto → Equipamento → Ações → Evidências. A etapa "Equipamento"
    # pede o COMPONENTE (Gateway/Motor/NCU/TCU/RSU) e, se for TCU, MAC + ID Modbus; a etapa "Ações"
    # exige o VALOR medido em cada teste, não só o "fiz o teste".
    "STI": [
        _s("Componente com falha", "lista", opcoes=["Gateway", "Motor", "NCU", "TCU", "RSU", "Outro"], chave="tipo_equip", so_para={"Estrutura Trackers"}),
        _s("Nº de série do componente com falha (foto da etiqueta)", "texto", anexo=True, chave="serial", so_para={"Estrutura Trackers"}),
        _s("Nº de MAC (obrigatório quando for TCU)", "texto", obrig=False, chave="mac", so_para={"Estrutura Trackers"}),
        # "ID Modbus / nº do tracker" e "Natureza do problema" saíram daqui (Levi, 30/07): o
        # primeiro por não fazer falta ao técnico, o segundo virou "Causa da falha" na base.
        _s("TCU liga / energiza?", "simnao", obrig=False, so_para={"Estrutura Trackers"}),
        _s("Tensão medida no painel PV (V)", "num", obrig=False, so_para={"Estrutura Trackers"}),
        _s("Corrente medida no painel PV (A)", "num", obrig=False, so_para={"Estrutura Trackers"}),
        _s("Testes executados em campo e valores medidos", "longo", chave="testes"),
    ],
    # service.latam@csisolar.com + pastas no Drive: a lista de evidências é fechada, e o
    # datalogger tem série própria
    "Canadian Solar": [
        _s("Nº de série do datalogger (foto da etiqueta)", "texto", anexo=True, chave="serial_dl"),
        _s("Data de instalação / início de operação (dd/mm/aaaa)", "texto", chave="op_desde"),
        _s("Fotos da instalação: módulos, inversores, disjuntores, string box, QGBT e aterramento",
           "texto", anexo=True, chave="evidencias"),
        _s("Vídeo da partida com 1 string, sem datalogger", "texto", anexo=True, obrig=False),
        _s("Vídeos das medições CC nos MC4 (PV+/T, PV-/T, PV+/PV-)", "texto", anexo=True, obrig=False),
        _s("Vídeos das medições CA no conector (F-F, F-T, F-N, N-T)", "texto", anexo=True, obrig=False),
        _s("Vídeos do display (Information, Alarm, Version, Running)", "texto", anexo=True, obrig=False),
    ],
    # suporte@sigmasensors.com.br — série, modelo, posição e acessórios já vêm do tipo ETM
    "Hukseflux": [],
    # forms.office.com da Valmont — item é a descrição da peça; TAG e quantidade já vêm do tipo
    "Convert": [
        _s("Item / descrição do equipamento em garantia", "texto"),
    ],
    # Soltec Service Desk: o campo "O que você precisa?" é o título do chamado, em uma linha.
    # Também é tracker eletrônico (gateway + rastreadores), então cobra o componente.
    "Soltec": [
        _s("Objetivo do chamado em uma linha (ex.: 'Gateway não está funcionando')",
           "texto", chave="titulo_ch"),
        _s("Componente com falha", "lista",
           opcoes=["Gateway", "Motor", "Controlador", "Outro"], chave="tipo_equip", so_para={"Estrutura Trackers"}),
        _s("ID do Gateway (GW)", "texto", obrig=False, chave="gw_id", so_para={"Estrutura Trackers"}),
        _s("IDs dos rastreadores afetados", "texto", obrig=False, chave="tracker_id", so_para={"Estrutura Trackers"}),
        _s("Testes executados em campo e valores medidos", "longo", obrig=False, chave="testes"),
    ],
    # customerservice.trinasolar.com — pede UFV, série, descrição e ações: tudo já coberto
    "Trina": [],
    # plataforma Sungrow: o campo Serviço exige escolher o produto no catálogo deles
    "Sungrow": [
        _s("Produto com problema (conforme catálogo Sungrow)", "texto", chave="produto"),
    ],
    # sdantas@/mmacedo@axialstructural.com — e-mail simples: modelo, série, horário e ações
    "Axial": [],
}
# clones já assumidos no chamado_spec: mesma engenharia, representante diferente
POR_FABRICANTE["Brametal"] = POR_FABRICANTE["STI"]
POR_FABRICANTE["Romiotto"] = POR_FABRICANTE["Hukseflux"]

# Marca × tipo de ativo que faz sentido — alimenta o combo de marca depois de escolher o ativo,
# para não oferecer Hukseflux num inversor. Marca fora deste mapa aparece para qualquer tipo.
# Tipo de ativo do Fracttal → bloco de perguntas que ele usa. Serve para ativos que NÃO têm bloco
# próprio mas pertencem a um grupo que tem.
#
# Os sensores da estação são ativos separados no cadastro, filhos da ESTM (medido: APG100-ESTM1-PRN1
# é filho de APG100-ESTM1). Sem este mapa não dava para abrir chamado de um piranômetro específico —
# só da estação inteira, e aí o fabricante não sabe qual sensor voltar para qual posição.
# Levi pediu piranômetro, sensor de temperatura e fieldlogger (30/07); os outros sensores da mesma
# estação estão listados abaixo, comentados, esperando a palavra dele.
ALIAS_TIPO = {
    "PRN": "Estação Meteorológica",     # Piranômetro     — 135 ativos
    "SDT": "Estação Meteorológica",     # Sensor de Temp. — 119
    "FDL": "Estação Meteorológica",     # Fieldlogger     —  96
    # "ALB": "Estação Meteorológica",   # Albedômetro     — 106
    # "ANM": "Estação Meteorológica",   # Anemômetro      —  60
    # "PLV": "Estação Meteorológica",   # Pluviômetro     —  96
    # "SDP": "Estação Meteorológica",   # Sensor de Pás   — 106
    # "CPF": "Estação Meteorológica",   # Captor Franklin — 107
}


def grupo_de(tipo_ativo: str) -> str:
    """Bloco de perguntas que aquele tipo de ativo usa. Devolve '' se o tipo não é atendido."""
    t = (tipo_ativo or "").strip()
    if t in POR_TIPO:
        return t
    return ALIAS_TIPO.get(t, "")


def aceita(tipo_ativo: str) -> bool:
    """O ativo daquele tipo pode virar inspeção de chamado?"""
    return bool(grupo_de(tipo_ativo))


TIPOS_DA_MARCA = {
    "Huawei": {"Inversor"},
    "Sungrow": {"Inversor"},
    "Canadian Solar": {"Inversor"},
    "STI": {"Estrutura Trackers", "NCU", "RSU"},
    "Brametal": {"Estrutura Trackers", "NCU", "RSU"},
    "Soltec": {"Estrutura Trackers", "NCU", "RSU"},
    "Axial": {"Estrutura Trackers"},
    "Trina": {"Estrutura Trackers"},
    "Convert": {"Estrutura Trackers", "Cabine", "Skid"},
    "Hukseflux": {"Estação Meteorológica"},
    "Romiotto": {"Estação Meteorológica"},
}

# Marcas que o app sabe reconhecer no texto do ativo, para já vir marcada no combo. Inclui as que
# NÃO têm processo de chamado escrito (SolarEdge, Growatt…) — reconhecer serve para avisar que
# aquela marca não tem processo, em vez de deixar o campo vazio sem explicação.
MARCAS_CONHECIDAS = sorted(set(TIPOS_DA_MARCA) | {"SolarEdge", "Growatt", "Solplanet", "WEG"})


def marca_do_ativo(asset: dict) -> str:
    """Marca lida da DESCRIÇÃO do ativo no Fracttal ('' se não reconhecer).

    Medido no catálogo inteiro (29/07): a descrição carrega a marca em **94% dos inversores**
    (1.764 de 1.877 — 'Inversor 1.1 Huawei SUN2000-250KTL-H1') e **85% das estruturas de tracker**
    (5.386 de 6.306 — 'Tracker 1.100 STI STI-H250'). Na Estação Meteorológica é inútil: só 1 de 106,
    porque ali a descrição é o endereço da planta. Então isto é PRÉ-SELEÇÃO, nunca substitui o
    campo — quem confirma é quem abre a OS."""
    import re
    import unicodedata

    def _n(s):
        s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
        return re.sub(r"[^a-z0-9]+", " ", s)

    txt = _n("%s %s" % (asset.get("description") or "", asset.get("label") or ""))
    for m in MARCAS_CONHECIDAS:
        if _n(m) in txt:
            return m
    return ""


def marcas_para(tipo_ativo: str) -> list:
    """Marcas que fazem sentido para aquele tipo de ativo (ordem alfabética).

    Resolve o ALIAS antes: piranômetro e fieldlogger são tipos próprios no Fracttal, mas as marcas
    deles são as da estação (Hukseflux/Romiotto)."""
    t = grupo_de(tipo_ativo) or (tipo_ativo or "").strip()
    return sorted(m for m, tipos in TIPOS_DA_MARCA.items() if not t or t in tipos)


def subtarefas(tipo_ativo: str, fabricante: str) -> list:
    """Subtarefas da OS de inspeção → lista pronta para `api._rpc_subtasks`.

    Ordem: base (validação e sintomas) → específico do tipo de ativo → específico da marca. É a
    ordem em que o técnico trabalha: primeiro confirma a falha, depois identifica o equipamento,
    depois junta o que aquele fabricante cobra.

    Subtarefa repetida (mesma pergunta na base e no bloco da marca) entra uma vez só: a marca pode
    reforçar um dado que a base já pede, e duas linhas iguais na OS só confundem o técnico."""
    blocos = (BASE
              + POR_TIPO.get(grupo_de(tipo_ativo), [])
              + POR_FABRICANTE.get((fabricante or "").strip(), []))
    grupo = grupo_de(tipo_ativo)
    out, vistos = [], set()
    for s in blocos:
        if s.get("so_para") and grupo not in s["so_para"]:
            continue                       # pergunta de tracker numa OS de NCU/RSU, por exemplo
        chave = s["desc"].strip().lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        item = {"description": s["desc"],
                "id_task_form_item_type": TIPO_ID.get(s["tipo"], 1),
                "is_required": bool(s["obrig"]),
                "attachments_required": bool(s["anexo"])}
        if s["opcoes"]:
            item["dropdown_options"] = [{"description": o} for o in s["opcoes"]]
        out.append(item)
    return out


DIAS_DOA = 7          # a Huawei trata à parte o equipamento com pouco tempo de operação


def derivados(tipo_ativo: str, event_date, hoje=None) -> dict:
    """Campos do chamado que o APP sabe — não viram pergunta para o técnico.

    Decisão do Levi (30/07) ao revisar a lista do inversor: perguntar em campo o que já está na OS
    só gasta o tempo dele e abre espaço para divergência. Então:
      - `data_falha`  = a data do incidente da própria OS;
      - `unidades`    = 1 quando o ativo é um inversor (é sempre um);
      - `menos_7d`    = calculado da data do incidente. **Recalcula toda vez que é chamado** — por
        isso é função e não valor gravado: a Singrid abre o chamado dias depois, e a resposta muda.

    ⚠️ Ressalva registrada: no formulário da Huawei esse campo é sobre a IDADE DO EQUIPAMENTO
    (instalação recente, tratada como DOA), não sobre há quanto tempo a falha ocorreu. Calculando
    pela data do incidente, inversor antigo que falhou anteontem responde "Sim". Está assim porque
    foi o pedido; se a leitura mudar, é só trocar a conta aqui."""
    import datetime as _dt
    out = {}
    tipo_ativo = str(tipo_ativo or "").strip()
    if tipo_ativo == "Inversor":
        out["unidades"] = "1"
    if grupo_de(tipo_ativo) in ("Estrutura Trackers", "NCU", "RSU"):
        out["quantidade"] = "1"          # a OS é de UM ativo; perguntar seria pergunta de resposta única
    dt = event_date
    if isinstance(dt, str):
        try:
            dt = _dt.datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            dt = None
    if dt is not None:
        out["data_falha"] = dt.strftime("%d/%m/%Y %H:%M")
        ref = hoje or _dt.datetime.now(dt.tzinfo) if dt.tzinfo else (hoje or _dt.datetime.now())
        try:
            dias = (ref - dt).days
            out["menos_7d"] = "Sim" if dias < DIAS_DOA else "Não"
            out["dias_desde_incidente"] = str(max(dias, 0))
        except TypeError:
            pass                      # datas com/sem fuso misturadas: não inventa a resposta
    return out


def resumo(tipo_ativo: str, fabricante: str) -> str:
    """'12 subtarefas · 5 com anexo obrigatório' — para o rodapé do card antes de criar."""
    subs = subtarefas(tipo_ativo, fabricante)
    an = sum(1 for s in subs if s.get("attachments_required"))
    ob = sum(1 for s in subs if s.get("is_required"))
    return "%d subtarefas · %d obrigatórias · %d com anexo obrigatório" % (len(subs), ob, an)
