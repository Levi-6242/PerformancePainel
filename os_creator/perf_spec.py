"""Regras do kanban de carga da Performance — prioridade, estado e o marcador na observação.

DE ONDE VEM CADA COISA (medido na API em 26/07, 378 OS de Performance em 90 dias):

| informação        | fonte                                    | custo |
|-------------------|------------------------------------------|-------|
| quem está com ela | `atribuido_a` da listagem                | zero  |
| estado            | `status_id` da listagem                  | zero  |
| fazendo agora     | etiqueta "Atividade em execução" (3377)  | zero  |
| PRIORIDADE        | bloco [PERFORMANCE] na observação        | zero  |

Tudo sai de UMA consulta. A prioridade ficou na **observação** e não numa etiqueta nova por
decisão do Levi (27/07): a etiqueta "Pedido do cliente" não existe no Fracttal, e anexo custaria
uma chamada por OS — 378 chamadas só para descobrir quem é pedido de cliente.

CUIDADO: a API do Fracttal **não edita OS já criada**. O bloco entra na CRIAÇÃO. Reclassificar
uma OS antiga só editando a observação no Fracttal web.

POR QUE PRIORIDADE É O CORAÇÃO DISTO (reunião de 16/07): o Roger Lélis vetou o kanban sem régua
clara — "prioridades tem que ficar muito claro, senão vira bola de neve; o Levi abriu algumas para
mim, até hoje nunca peguei, todas foram canceladas". Não era hipótese: **102 das 378 OS de
Performance dos últimos 90 dias estão CANCELADAS (27%)**. A régua abaixo é a da Ana Patrícia:
"80% atrelada ao impacto de PR".
"""

# ── prioridades ──────────────────────────────────────────────────────────────
# (chave, rótulo, explicação curta que aparece na legenda da tela)
MAXIMA  = "Máxima"
CLIENTE = "Cliente"
ROTINA  = "Rotina"

PRIORIDADES = [
    (MAXIMA,  "PRIORIDADE MÁXIMA", "Usina com PR muito impactado — as vermelhas do painel."),
    (CLIENTE, "PEDIDO DE CLIENTE", "Análise pedida direto pelo cliente, com prazo de retorno."),
    (ROTINA,  "ROTINA",            "Ronda, verificação e o que a pessoa abriu para si mesma."),
]
PRIORIDADE_PADRAO = ROTINA

# ordem de quem sobe na fila. É a régua da Ana: impacto de PR primeiro, pedido de cliente logo
# atrás, rotina por último.
ORDEM = {MAXIMA: 0, CLIENTE: 1, ROTINA: 2}

# ── etiquetas do Fracttal usadas aqui (ids conferidos na API em 26/07) ───────
LABEL_PERFORMANCE  = "PERFORMANCE"          # 4660 — marca o setor
LABEL_EM_EXECUCAO  = "Atividade em execução"  # 3377 — o "fazendo agora" que o analista marca
LABEL_PRIORIDADE   = "Dar prioridade"       # 2603 — reforço visual DENTRO do Fracttal

# ── o bloco na observação ────────────────────────────────────────────────────
MARCADOR = "[PERFORMANCE]"
_CAMPOS = [("Prioridade", "prioridade"), ("Motivo", "motivo"), ("Pedido por", "pedido_por")]


def bloco(dados: dict) -> str:
    """dict → texto do bloco, para concatenar na observação da OS na CRIAÇÃO.
    Só emite campo preenchido: bloco enxuto é bloco que a pessoa lê no Fracttal."""
    linhas = [MARCADOR]
    for rot, k in _CAMPOS:
        v = str((dados or {}).get(k) or "").strip()
        if v:
            linhas.append(f"{rot}: {v}")
    return "\n".join(linhas) if len(linhas) > 1 else ""


def parse(texto) -> dict:
    """INVERSO: lê o bloco de uma observação → {'prioridade','motivo','pedido_por'}.
    {} quando não tem bloco. Tolera acento e caixa no rótulo, como o bloco do chamado."""
    t = str(texto or "")
    if MARCADOR.lower() not in t.lower():
        return {}
    import unicodedata

    def _norm(s):
        s = unicodedata.normalize("NFKD", str(s).lower())
        return "".join(c for c in s if not unicodedata.combining(c)).strip()

    rot2k = {_norm(r): k for r, k in _CAMPOS}
    out = {}
    for linha in t.splitlines():
        if ":" not in linha:
            continue
        rot, val = linha.split(":", 1)
        k = rot2k.get(_norm(rot))
        if k:
            v = val.strip()
            out[k] = "" if v in ("", "—") else v
    return out


def prioridade_de(d: dict) -> str:
    """Prioridade de uma OS da listagem. Precedência: bloco na observação > etiqueta
    'Dar prioridade' > padrão. A etiqueta sozinha não distingue PR de pedido de cliente —
    é justamente por isso que o bloco existe."""
    p = (parse(d.get("note")).get("prioridade") or "").strip()
    for chave, _, _ in PRIORIDADES:
        if p.lower() == chave.lower():
            return chave
    if tem_etiqueta(d, LABEL_PRIORIDADE):
        return MAXIMA
    return PRIORIDADE_PADRAO


def tem_etiqueta(d: dict, nome: str) -> bool:
    alvo = (nome or "").strip().lower()
    return any((e.get("nome") or "").strip().lower() == alvo
               for e in (d.get("etiquetas") or []) if isinstance(e, dict))


def em_execucao(d: dict) -> bool:
    """O analista marcou 'Atividade em execução' — é o card azul do board."""
    return tem_etiqueta(d, LABEL_EM_EXECUCAO)


# ── estado (as três colunas da visão do analista) ────────────────────────────
# "Não iniciada" e não "Pendente" (troca pedida pelo Levi em 27/07): pendente descrevia a OS do
# ponto de vista de quem cobra; "não iniciada" descreve o FATO — ninguém apertou o play ainda.
PENDENTE, EM_PROCESSO, CONCLUIDA = "Não iniciada", "Em processo", "Concluída"
ESTADOS = [PENDENTE, EM_PROCESSO, CONCLUIDA]


def estado_de(d: dict) -> str:
    """Estado do trabalho, não o status cru do Fracttal.

    'Em Verificação' (2) conta como CONCLUÍDA para o analista: ele já fez a parte dele e a OS
    está aguardando conferência — deixá-la em 'pendente' faria a fila mentir para cima.
    'Cancelada' (4) fica fora do board: são 27% das OS e poluiriam a coluna de concluídas com
    trabalho que nunca aconteceu — quem quiser ver cancelamento usa o Histórico."""
    st = d.get("status_id")
    if st == 3 or st == 2:
        return CONCLUIDA
    if em_execucao(d):
        return EM_PROCESSO
    return PENDENTE


def visivel(d: dict) -> bool:
    """Cancelada não entra no board (ver estado_de)."""
    return d.get("status_id") != 4


# ── tempo: a régua da cobrança ───────────────────────────────────────────────
def _dt(s):
    import datetime as _d
    s = str(s or "")[:19]
    if len(s) < 10:
        return None
    try:
        return _d.datetime.fromisoformat(s)
    except ValueError:
        return None


def dias_parado(d: dict, agora=None):
    """Dias desde a criação, para OS que ainda NÃO concluiu. None quando concluída.

    É o número que o Roger pediu para não deixar virar bola de neve — e não é hipótese: 42 das 44
    OS que já foram atribuídas a analistas terminaram CANCELADAS (95%), quase todas por ficarem
    paradas. Conta em dias corridos porque a cobrança é de calendário, não de hora útil."""
    if estado_de(d) == CONCLUIDA:
        return None
    ini = _dt(d.get("data"))
    if not ini:
        return None
    import datetime as _d
    return max(0, ((agora or _d.datetime.now()) - ini).days)


def tempo_conclusao(d: dict):
    """Quanto levou, em HORAS, da criação até o fim. None se não dá para saber.
    O Levi pediu explicitamente 'concluída com tempo de conclusão'."""
    if estado_de(d) != CONCLUIDA:
        return None
    ini, fim = _dt(d.get("data")), _dt(d.get("data_fim"))
    if not ini or not fim or fim < ini:
        return None
    return (fim - ini).total_seconds() / 3600.0


def fmt_duracao(h):
    """Horas → '4 h' / '2,4 d'. Abaixo de 1h vira minuto, senão some tudo em '0 h'."""
    if h is None:
        return ""
    if h < 1:
        return "%d min" % max(1, int(round(h * 60)))
    if h < 48:
        return "%d h" % int(round(h))
    return ("%.1f d" % (h / 24.0)).replace(".", ",")


def urgencia(dias):
    """Faixa da cobrança → 'ok' | 'atencao' | 'critico'. 7 dias é o corte porque a Ana pede
    ronda no fim do dia e o Roger revisa as próprias OS toda sexta: passar de uma semana
    significa que as duas rotinas deixaram passar."""
    if dias is None:
        return "ok"
    if dias > 15:
        return "critico"
    if dias > 7:
        return "atencao"
    return "ok"
