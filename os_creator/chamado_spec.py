"""Regras dos CHAMADOS de garantia (abertura junto ao fabricante). PURO: sem Qt, sem rede — só
dados e strings. Espelha os 9 processos documentados pela Singrid em
`13. Gestão de Chamados/02. Processos de Abertura e Acompanhamento` e o combinado da reunião de
23/07 (Ana Patrícia + Singrid + Levi):

  - Quem ABRE o chamado é o supervisor, no card da própria OS — não a equipe de chamados. Antes
    ele só colava a etiqueta CHAMADOS e avisava por WhatsApp, e a informação chegava incompleta.
  - A OS de chamado nasce como FILHA da OS onde o problema foi tratado (OS pai), pra manter
    uma linha só do começo ao fim.
  - Os 9 processos têm o MESMO esqueleto (abertura → acompanhamento → garantia/envio) e o
    acompanhamento é um LAÇO: o fabricante volta pedindo testes ou aprova a garantia.
  - O que muda de um pro outro é o pacote de informação exigido na abertura — por isso
    CAMPOS_EXTRA por fabricante, e não um formulário único.
"""

# ── Fabricantes com processo documentado ─────────────────────────────────────
FABRICANTES = ["Axial", "Brametal", "Canadian Solar", "Convert", "Huawei", "Hukseflux",
               "Romiotto", "Soltec", "STI", "Sungrow", "Trina"]

# Aparecem com VOLUME REAL na planilha de chamados mas ainda não têm processo escrito
# (SolarEdge 44 dos 566). Ficam disponíveis com os campos comuns — vale pedir o documento pra
# Singrid, aí saem daqui e ganham CAMPOS_EXTRA.
FABRICANTES_SEM_DOC = ["SolarEdge", "Growatt", "Solplanet", "WEG"]
TODOS_FABRICANTES = FABRICANTES + FABRICANTES_SEM_DOC

# De quem o chamado está esperando. É o vocabulário REAL da planilha e responde "a quem cobrar" —
# eixo diferente do STATUS (que diz em que etapa da garantia está). Nos 317 em aberto:
# Fabricante 151 · Cliente 72 · Supervisor 25 · Pré-Operação 16 — ou seja, 113 estão travados
# do NOSSO lado, não no fabricante. Sem isso a Singrid não sabe atrás de quem correr.
ESPERANDO = ["Fabricante", "Cliente", "Supervisor", "Pré-Operação",
             "Equipe de campo", "Ninguém — ação nossa"]
ESPERANDO_PADRAO = ESPERANDO[0]

# Como o chamado é aberto em cada um (aparece de dica na tela — evita o operador procurar o doc).
CANAL = {
    "Axial":          "E-mail — sdantas@axialstructural.com e mmacedo@axialstructural.com",
    # CLONES (28/07): o PACOTE DE INFORMAÇÃO é o mesmo do fabricante de origem, mas o CANAL não
    # foi documentado — e canal é contato real, não se deduz por semelhança. Fica dito na tela
    # para ninguém abrir chamado da Romiotto no e-mail da Sigma Sensors por engano.
    "Brametal":       "Canal ainda não documentado — confirmar com a Singrid (processo espelhado no da STI)",
    "Romiotto":       "Canal ainda não documentado — confirmar com a Singrid (processo espelhado no da Hukseflux)",
    "Canadian Solar": "E-mail service.latam@csisolar.com + evidências no Google Drive",
    "Convert":        "Formulário de garantia (Valmont) — brazil_services@valmont.com em cópia",
    "Huawei":         "Portal Digital Power — não precisa de login pra abrir",
    "Hukseflux":      "E-mail Sigma Sensors — suporte@ e fabio@sigmasensors.com.br",
    "Soltec":         "Soltec Service Desk — Central de Ajuda",
    "STI":            "Portal STI (login + código no e-mail) — Suporte Técnico › Novo Ticket",
    "Sungrow":        "Portal Sungrow (login) — Novo Ticket",
    "Trina":          "Portal customerservice.trinasolar.com — Mounting Structure › Enquiry",
}

# ── Ciclo de vida do CHAMADO (eixo separado do status da OS) ─────────────────
# Ordem = andamento real do processo nos 9 documentos. Atenção: o chamado NÃO fecha quando a
# garantia é aprovada — fecha quando o defeituoso é coletado (Axial/Huawei/Trina) ou quando o
# equipamento volta a operar (Canadian Solar/Hukseflux).
STATUS = [
    "A abrir",
    "Aberto — aguardando fabricante",
    "Testes adicionais solicitados",
    "Evidências enviadas — em análise",
    "Garantia aprovada",
    "Garantia negada — orçamento",
    "Documentação / NF pendente",
    "Equipamento novo a caminho",
    "Novo recebido na usina",
    "Defeituoso coletado",
    "Concluído",
]
STATUS_INICIAL = STATUS[0]

# Status que ainda exigem ação da equipe de chamados (alimentam a fila do painel).
STATUS_ABERTOS = set(STATUS[:-1])

# ── Campos ───────────────────────────────────────────────────────────────────
# tipo: "texto" (linha), "longo" (parágrafo), "data", "lista", "evid" (checklist de evidências)
def _c(chave, rotulo, tipo="texto", obrig=True, dica="", opcoes=None):
    return {"chave": chave, "rotulo": rotulo, "tipo": tipo, "obrig": obrig,
            "dica": dica, "opcoes": opcoes or []}


# Exigido pelos NOVE — é o pacote mínimo que o supervisor entrega "mastigado" pra equipe de
# chamados (pedido literal da Singrid na reunião: "quando chegasse pra mim, com todas as
# informações que eu precisaria pra abrir").
CAMPOS_COMUNS = [
    _c("serial", "Número de série", dica="do equipamento com falha"),
    _c("data_falha", "Data e hora da falha", "data"),
    _c("problema", "Problema — sintoma e impacto na geração", "longo"),
    _c("acoes", "Ações já realizadas em campo", "longo",
       dica="testes, resets e verificações antes de acionar o fabricante"),
]

# Exigido a MAIS por fabricante (só o que o documento pede além do comum).
CAMPOS_EXTRA = {
    "Huawei": [
        _c("alarme", "ID do alarme", dica="código exibido no supervisório"),
        _c("unidades", "Nº de unidades afetadas"),
        _c("op_desde", "Equipamento em operação desde", "data", obrig=False,
           dica="marca o caso de menos de 7 dias, que a Huawei trata à parte"),
        # calculado pelo app a partir da data do incidente e RECALCULADO toda vez que este diálogo
        # abre — a Singrid abre o chamado dias depois da inspeção e a resposta muda (Levi, 30/07).
        _c("menos_7d", "Menos de 7 dias?", "lista", obrig=False, opcoes=["Sim", "Não"],
           dica="calculado pela data do incidente; confira antes de enviar"),
    ],
    "Canadian Solar": [
        _c("serial_dl", "Nº de série do datalogger"),
        _c("op_desde", "Data de instalação / início de operação", "data"),
        _c("evidencias", "Evidências obrigatórias", "evid", opcoes=[
            "Foto da etiqueta do inversor",
            "Foto da etiqueta do datalogger",
            "Fotos da instalação (módulos, inversores, disjuntores, string box, QGBT, aterramento)",
            "Vídeo da partida com 1 string, sem datalogger",
            "Vídeos das medições CC nos MC4 (PV+/T, PV-/T, PV+/PV-)",
            "Vídeos das medições CA no conector (F-F, F-T, F-N, N-T)",
            "Vídeos do display (Information, Alarm, Version, Running)",
            "Nota fiscal de compra",
            "Datasheet dos equipamentos",
            "Diagrama unifilar",
        ]),
    ],
    "STI": [
        _c("tipo_equip", "Tipo de equipamento", "lista",
           opcoes=["Gateway", "Motor", "NCU", "TCU", "RSU", "Outro"]),
        _c("mac", "Nº de MAC", obrig=False, dica="obrigatório quando for TCU"),
        _c("modbus", "ID Modbus / Tracker", obrig=False, dica="obrigatório quando for TCU"),
        _c("testes", "Testes executados e valores medidos", "longo",
           dica="TCU ligada, tensão do painel PV, corrente do painel PV"),
    ],
    "Hukseflux": [
        _c("posicao", "Posição de instalação na planta", dica=(
            "o sensor TEM de voltar pra mesma posição — a configuração Modbus é por posição")),
        _c("modelo", "Modelo do sensor"),
        _c("acessorios", "Acessórios enviados junto", "longo", obrig=False,
           dica="cabo, escudo solar, estrutura, parafusos, pés de nivelamento"),
    ],
    "Convert": [
        _c("tag", "TAG do equipamento na usina"),
        _c("quantidade", "Quantidade"),
        _c("cnpj", "CNPJ do proprietário da usina"),
        _c("entrega", "Endereço de entrega e responsável pelo recebimento", "longo",
           dica="rua, CEP, cidade, responsável, CPF e telefone"),
    ],
    "Soltec": [
        _c("titulo_ch", "Título do chamado",
           dica="objetivo em uma linha, ex.: 'Gateway não está funcionando'"),
        _c("gw_id", "GW ID", obrig=False),
        _c("tracker_id", "ID dos rastreadores", obrig=False),
    ],
    "Trina": [
        _c("modelo", "Modelo do equipamento"),
    ],
    "Axial": [
        _c("modelo", "Modelo do equipamento"),
        _c("fiscal", "Situação fiscal da usina", "lista", opcoes=[
            "Com Inscrição Estadual — NF CFOP 6915",
            "Sem Inscrição Estadual — Declaração de Não Contribuinte",
        ], dica="define o documento de remessa; a Axial manda o novo ANTES de coletar o defeituoso"),
    ],
    "Sungrow": [
        _c("produto", "Produto", "lista",
           opcoes=["Inversor", "String box", "Datalogger", "Outro"]),
    ],
}

# CLONES de processo (28/07, pedido do Levi). Apontam para a MESMA lista da origem, de propósito:
# se um campo mudar lá, o clone acompanha em vez de divergir em silêncio. O equipamento é do mesmo
# tipo dos dois lados — Romiotto ~ sensor/estação como a Hukseflux; Brametal ~ tracker como a STI.
# Quando a Singrid entregar o processo escrito de cada um, é aqui que a lista própria entra.
CAMPOS_EXTRA["Romiotto"] = CAMPOS_EXTRA["Hukseflux"]
CAMPOS_EXTRA["Brametal"] = CAMPOS_EXTRA["STI"]

# Documento fiscal de remessa (aparece na etapa de garantia; varia por fabricante/UF).
DOCS_FISCAIS = ["NF CFOP 5915/6915 — remessa para conserto", "Declaração de Transporte",
                "Declaração de Não Contribuinte", "Não se aplica"]


# Fabricantes que atendem por E-MAIL: o assunto é como a equipe reencontra a conversa depois
# (na planilha essa coluna tem 160 preenchidos, no formato "[USINA] - assunto").
# Romiotto entra junto da Hukseflux (é clone dela); Brametal NÃO, porque a STI é portal.
FAB_EMAIL = {"Axial", "Canadian Solar", "Hukseflux", "Romiotto", "Convert"}
_C_EMAIL = _c("titulo_email", "Título do e-mail", obrig=False,
              dica="assunto usado no e-mail — é por ele que se acha a conversa depois")


def campos(fabricante) -> list:
    """Campos que a tela deve pedir pra este fabricante = comuns + extras dele."""
    fab = str(fabricante or "").strip()
    out = list(CAMPOS_COMUNS) + list(CAMPOS_EXTRA.get(fab, []))
    if fab in FAB_EMAIL:
        out.append(_C_EMAIL)
    return out


def faltando(fabricante, dados) -> list:
    """Rótulos dos campos OBRIGATÓRIOS ainda vazios — o botão de criar usa isso pra travar.
    É o que impede a informação de chegar incompleta e virar o 'loop de coleta' que a Ana
    quis evitar."""
    d = dados or {}
    out = []
    for c in campos(fabricante):
        if not c["obrig"]:
            continue
        v = d.get(c["chave"])
        v = v.strip() if isinstance(v, str) else v
        if not v:
            out.append(c["rotulo"])
    return out


def motivo_titulo(fabricante, dados=None) -> str:
    """3º campo do título [Usina][Ativo] - MOTIVO. Ex.: 'Chamado Huawei — inversor'."""
    fab = str(fabricante or "").strip()
    d = dados or {}
    alvo = str(d.get("produto") or d.get("tipo_equip") or "").strip()
    base = f"Chamado {fab}" if fab else "Chamado"
    return f"{base} — {alvo.lower()}" if alvo else base


def subtarefas(fabricante, dados=None) -> list:
    """Subtarefas rastreáveis da OS de chamado. São as etapas que existem nos NOVE processos
    (a Ana pediu: 'pensa num padrão, algumas etapas que existem em todas'); o que é específico
    de um fabricante fica no bloco de texto da observação.
    → [{'descricao','tipo','opcoes','valor'}] — a tela converte pro formato do Fracttal."""
    d = dados or {}
    return [
        {"descricao": "Nº do chamado / protocolo", "tipo": "texto", "valor": d.get("ticket", "")},
        {"descricao": "Status do chamado", "tipo": "lista", "opcoes": list(STATUS),
         "valor": d.get("status") or STATUS_INICIAL},
        {"descricao": "Aguardando retorno de", "tipo": "lista", "opcoes": list(ESPERANDO),
         "valor": d.get("esperando") or ESPERANDO_PADRAO},
        {"descricao": "Fabricante", "tipo": "lista", "opcoes": list(TODOS_FABRICANTES),
         "valor": str(fabricante or "")},
        {"descricao": "Número de série", "tipo": "texto", "valor": d.get("serial", "")},
        {"descricao": "Testes adicionais solicitados?", "tipo": "lista",
         "opcoes": ["Não", "Sim — OS de campo aberta"], "valor": ""},
        {"descricao": "Garantia", "tipo": "lista",
         "opcoes": ["Em análise", "Aprovada", "Negada"], "valor": ""},
        {"descricao": "Nº do RMA", "tipo": "texto", "valor": ""},
        {"descricao": "Documento fiscal de remessa", "tipo": "lista",
         "opcoes": list(DOCS_FISCAIS), "valor": ""},
        {"descricao": "Equipamento defeituoso coletado?", "tipo": "lista",
         "opcoes": ["Não", "Sim"], "valor": ""},
    ]


def texto_abertura(fabricante, dados=None) -> str:
    """Corpo que o supervisor entrega pronto — a equipe de chamados copia direto pro portal ou
    e-mail do fabricante. Segue a ordem que os documentos pedem."""
    d = dados or {}
    fab = str(fabricante or "").strip()
    L = [f"Chamado {fab}".strip(), ""]
    if CANAL.get(fab):
        L.append(f"Abertura: {CANAL[fab]}")
        L.append("")
    for c in campos(fab):
        v = d.get(c["chave"])
        if isinstance(v, (list, tuple)):
            v = ", ".join(str(x) for x in v)
        v = str(v or "").strip()
        if v:
            L.append(f"{c['rotulo']}: {v}")
    return "\n".join(L).strip()
