"""Engine de texto do COS reestruturado (F2). PURO: sem Qt, sem rede — só monta strings.
Compartilhado pela UI (steps/varias_os) e pela criação (api). Espelha o padrão aprovado pelo time
(reunião 13/07 + fluxograma):

  Tipos de OS: "Religamento da UFV" e "Inspeção e Normalização".
  Categorias da ocorrência:
    A · Proteção atuou      → chips ANSI  → Ação Religamento Remoto/Local
    B · Inversor desligado  → falha do inversor → Ação Religamento Local
    C · Falha de comunicação→ causa da comunicação → Ação Inspeção Local
  Título:      [Usina][Equipamento] - {motivo}          (via api.perf_os_nome)
  Observação:  UFV: {usina} | Proteção: {códigos} | Ação: {ação} | Falha: {falha}
"""

# ── Tipos de OS ──────────────────────────────────────────────────────────────
TIPO_RELIGAMENTO = "Religamento da UFV"
TIPO_INSPECAO    = "Inspeção e Normalização"

# ── Categorias da ocorrência (do fluxograma) ─────────────────────────────────
CAT_A, CAT_B, CAT_C = "A", "B", "C"
CATEGORIAS = {
    CAT_A: "Proteção atuou",
    CAT_B: "Inversor desligado",
    CAT_C: "Falha de comunicação",
}

# Proteções ANSI (A) — 86 é o impedimento de segurança (lockout) que exige equipe em campo.
PROTECOES = ["27", "59", "59N", "47", "67", "81", "32", "50", "51", "86"]
PROTECAO_MOTIVO = {
    "27": "Subtensão", "59": "Sobretensão", "59N": "Sobretensão de neutro",
    "47": "Sequência de fase", "67": "Sobrecorrente direcional", "81": "Frequência",
    "32": "Potência direcional", "50": "Sobrecorrente instantânea",
    "51": "Sobrecorrente temporizada", "86": "Bloqueio (lockout)",
}
PROTECAO_IMPEDIMENTO = "86"          # presença → permissivo bloqueia religamento remoto

# Referência ANSI agrupada (tooltip da "!" na categoria A) — espelha o fluxograma.
ANSI_REF = [
    ("27", "Subtensão"), ("59 · 59N", "Sobretensão / de neutro"), ("47", "Sequência de fase (tensão)"),
    ("67", "Sobrecorrente direcional"), ("81", "Frequência (sobre/sub)"), ("32", "Potência direcional"),
    ("50 · 51", "Sobrecorrente inst. / temp."), ("86", "Bloqueio (lockout) — impedimento"),
]


def ansi_tooltip() -> str:
    linhas = "".join(
        f"<tr><td style='padding:2px 12px 2px 0;color:#A6E22E;font-weight:700'>{c}</td>"
        f"<td style='padding:2px 0'>{m}</td></tr>" for c, m in ANSI_REF)
    return f"<b>Proteção (ANSI) → motivo</b><table style='margin-top:4px'>{linhas}</table>"

# Falhas do inversor (B) e causas de comunicação (C)
FALHAS_B = ["Baixa impedância de isolamento", "Baixa irradiância", "Outro erro"]
CAUSAS_C = ["Falha de comunicação com o supervisório", "Fibra rompida na região",
            "Falta de internet", "Oscilação de internet"]

# Ações
ACAO_REMOTO   = "Religamento Remoto"
ACAO_LOCAL    = "Religamento Local"
ACAO_INSPECAO = "Inspeção Local"
ACAO_DEFAULT_CAT = {CAT_A: ACAO_REMOTO, CAT_B: ACAO_LOCAL, CAT_C: ACAO_INSPECAO}

# Onde atuou (A).
ONDE = ["Disjuntor Geral", "Disjuntor Cabine", "Inversor"]

# Tipos de equipamento que os operadores do COS usam — filtra o dropdown "Tipo de equipamento".
COS_EQUIP = ["Inversor", "Cabine", "Usina", "Tracker", "Disjuntor"]

# ── gênero simples p/ concordância (Cabine/Usina = fem.) ─────────────────────
_FEM = ("cabine", "usina", "estac", "string", "subestac")


def _fem(equip: str) -> bool:
    w = (equip or "").strip().split(" ")[0].lower()
    return any(w.startswith(f) for f in _FEM)


def _desligado(equip: str) -> str:
    return "desligada" if _fem(equip) else "desligado"


def artigo(equip: str) -> str:
    """'do'/'da' p/ o motivo do título."""
    return "da" if _fem(equip) else "do"


# ── montagem ─────────────────────────────────────────────────────────────────
def juntar_codigos(codigos) -> str:
    """['27','59'] → '27 e 59' · ['81'] → '81' · [] → '--/--' (uppercase, sem duplicar)."""
    cs = []
    for c in (codigos or []):
        c = str(c).strip().upper()
        if c and c not in cs:
            cs.append(c)
    if not cs:
        return "--/--"
    if len(cs) == 1:
        return cs[0]
    return ", ".join(cs[:-1]) + " e " + cs[-1]


def falha_texto(categoria, equipamento="", codigos=None, motivo_b="", causa_c="") -> str:
    """Campo 'Falha:' conforme a categoria (espelha os exemplos reais do time)."""
    eq = (equipamento or "Equipamento").strip()
    if categoria == CAT_A:
        return f"{eq} {_desligado(eq)}, relé com proteções {juntar_codigos(codigos)} ativas."
    if categoria == CAT_B:
        m = (motivo_b or "").strip() or "falha não especificada"
        return f'{eq} {_desligado(eq)} devido a falha: "{m}".'
    if categoria == CAT_C:
        c = (causa_c or "").strip()
        base = "Usina ligada, mas em falha de comunicação"
        if not c:
            return base + "."
        low = c.lower()
        if "supervis" in low:
            return base + " com o supervisório."
        # "Fibra rompida na região" → "...devido fibra rompida na região."
        c1 = c[0].lower() + c[1:] if c else c
        return f"{base} devido {c1}."
    return ""


def acao_texto(categoria, remoto=True) -> str:
    """A = Remoto/Local (escolha); B = Religamento Local; C = Inspeção Local."""
    if categoria == CAT_A:
        return ACAO_REMOTO if remoto else ACAO_LOCAL
    return ACAO_DEFAULT_CAT.get(categoria, ACAO_LOCAL)


def motivo_titulo(tipo, equipamento="", acao="") -> str:
    """3º campo do título [Usina][Equip] - MOTIVO. Religamento → 'Religamento {do/da} {equip}';
    Inspeção → 'Inspeção e normalização {do/da} {equip}'."""
    eq = (equipamento or "").strip()
    art = artigo(eq)
    if tipo == TIPO_INSPECAO:
        return f"Inspeção e normalização {art} {eq}".strip() if eq else "Inspeção e normalização"
    base = "Religamento"
    return f"{base} {art} {eq}".strip() if eq else (acao or base)


def observacao(usina, codigos, acao, falha) -> str:
    """Padrão pipe do time: UFV: {usina} | Proteção: {códigos} | Ação: {ação} | Falha: {falha}."""
    return (f"UFV: {(usina or '').strip()} | Proteção: {juntar_codigos(codigos)} "
            f"| Ação: {acao} | Falha: {falha}")


def exige_equipe_campo(codigos) -> bool:
    """Permissivo de segurança: 86 (ou outro impedimento) ativo → religamento remoto NÃO autorizado."""
    return PROTECAO_IMPEDIMENTO in {str(c).strip().upper() for c in (codigos or [])}
