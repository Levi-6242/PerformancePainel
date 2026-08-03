"""Engine de texto do COS reestruturado (F2). PURO: sem Qt, sem rede — só monta strings.
Compartilhado pela UI (steps/varias_os) e pela criação (api). Espelha o padrão aprovado pelo time
(reunião 13/07 + fluxograma):

  Tipos de OS: "Religamento da UFV" e "Inspeção e Normalização".
  Categorias da ocorrência:
    A · Proteção atuou      → chips ANSI  → Ação Religamento Remoto/Local
    B · Inversor desligado  → falha do inversor → Ação Religamento Local
    C · Falha de comunicação→ causa da comunicação → Ação Inspeção Local
  Título:      [Equipamento] - {motivo}                 (via api.perf_os_nome)
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
PROTECOES = ["27", "32", "46", "47", "50", "51", "59", "67", "78", "81", "86",
             "50N", "51N", "59N", "67N"]                    # lista oficial do COS (23/07)
PROTECAO_MOTIVO = {
    "27": "Relé de Subtensão",
    "32": "Relé Direcional de Potência",
    "46": "Relé de Desbalanceamento de Corrente",
    "47": "Relé de Desbalanceamento de Tensão",
    "50": "Relé de Sobrecorrente Instantâneo",
    "51": "Relé de Sobrecorrente Temporizado",
    "59": "Relé de Sobretensão",
    "67": "Relé Direcional de Sobrecorrente",
    "78": "Salto Vetorial",
    "81": "Relé de Frequência",
    "86": "Relé Auxiliar de Bloqueio",
    "50N": "Sobrecorrente Instantâneo de Neutro",
    "51N": "Relé de Sobrecorrente Temporizado de Neutro",
    "59N": "Relé de Sobretensão Residual ou Sobretensão de Neutro",
    "67N": "Relé de Sobrecorrente Direcional de Neutro",
}
PROTECAO_IMPEDIMENTO = "86"          # presença → permissivo bloqueia religamento remoto

# Referência ANSI (tooltip da "!" na categoria A) — mesma lista/descrição do COS.
ANSI_REF = [(c, PROTECAO_MOTIVO[c]) for c in PROTECOES]


def ansi_tooltip() -> str:
    linhas = "".join(
        f"<tr><td style='padding:2px 12px 2px 0;color:#A6E22E;font-weight:700'>{c}</td>"
        f"<td style='padding:2px 0'>{m}</td></tr>" for c, m in ANSI_REF)
    return f"<b>Proteção (ANSI) → motivo</b><table style='margin-top:4px'>{linhas}</table>"

# Falhas do inversor (B) e causas de comunicação (C)
# "Outro erro" fica SEMPRE no fim: é o escape da lista, e item novo entra antes dele.
FALHAS_B = ["Baixa impedância de isolamento", "Baixa irradiância",
            "Perda da rede elétrica",              # Levi, 03/08
            "Outro erro"]
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
    import unicodedata
    w = (equip or "").strip().split(" ")[0].lower()
    # sem acento: 'estação' precisa casar com 'estac' (senão sai "Religamento DO Estação")
    w = "".join(c for c in unicodedata.normalize("NFD", w) if unicodedata.category(c) != "Mn")
    return any(w.startswith(f) for f in _FEM)


def _desligado(equip: str) -> str:
    return "desligada" if _fem(equip) else "desligado"


def artigo(equip: str) -> str:
    """'do'/'da' p/ o motivo do título."""
    return "da" if _fem(equip) else "do"


# ── montagem ─────────────────────────────────────────────────────────────────
SEM_TRIP = "Sem proteção/trip ativo"   # cat A: desligou SEM atuação de proteção (exclusivo com os códigos)


def _eh_sem_trip(codigos) -> bool:
    """Aceita o rótulo novo e o antigo ('Sem trip') — OSs já criadas continuam sendo lidas."""
    for c in (codigos or []):
        s = str(c).strip().lower()
        if s.startswith("sem trip") or s.startswith("sem prote"):
            return True
    return False


def juntar_codigos(codigos) -> str:
    """['27','59'] → '27 e 59' · ['81'] → '81' · ['Sem trip'] → 'Sem trip' · [] → '--/--'."""
    cs = []
    for c in (codigos or []):
        c = str(c).strip()
        c = c if _eh_sem_trip([c]) else c.upper()   # preserva o rótulo 'Sem …'; códigos em maiúscula
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
        if _eh_sem_trip(codigos):
            return f"{eq} {_desligado(eq)}, sem atuação de proteção (sem trip)."
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
    """Ação ESCOLHIDA pelo operador em qualquer categoria (o default por categoria está em
    ACAO_DEFAULT_CAT). Remoto = Religamento Remoto; Local = Religamento Local (A/B) ou
    Inspeção Local (C — falha de comunicação não tem religamento, o técnico inspeciona)."""
    if remoto:
        return ACAO_REMOTO
    return ACAO_INSPECAO if categoria == CAT_C else ACAO_LOCAL


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


def parse_observacao(texto) -> dict:
    """INVERSO de observacao(): lê o pipe do COS de volta → {'usina','codigos','acao','falha'}.
    Usa a 1ª linha que tem 'UFV:' e '|' (a observação livre do operador vem depois). Campos que
    faltam voltam vazios. É o que permite o CLONADOR do COS remontar o formulário de uma OS."""
    out = {"usina": "", "codigos": [], "acao": "", "falha": ""}
    linha = ""
    for l in str(texto or "").splitlines():
        if "|" in l and "ufv:" in l.lower():
            linha = l.strip()
            break
    if not linha:
        return out
    for parte in linha.split("|"):
        p = parte.strip()
        low = p.lower()
        if ":" not in p:
            continue
        val = p.split(":", 1)[1].strip()
        if low.startswith("ufv"):
            out["usina"] = val
        elif low.startswith(("proteção", "protecao")):
            if val and val != "--/--":
                out["codigos"] = [(c.strip() if _eh_sem_trip([c]) else c.strip().upper())
                                  for c in val.replace(" e ", ",").split(",") if c.strip()]
        elif low.startswith(("ação", "acao")):
            out["acao"] = val
        elif low.startswith("falha"):
            out["falha"] = val
    return out


def categoria_de(codigos, falha) -> str:
    """Deduz a categoria de uma OS do COS já criada (p/ o clonador): tem proteção → A;
    falha citando comunicação/supervisório/fibra/internet → C; senão → B (inversor)."""
    if codigos:
        return CAT_A
    f = str(falha or "").lower()
    if any(t in f for t in ("comunica", "supervis", "fibra", "internet")):
        return CAT_C
    return CAT_B


def exige_equipe_campo(codigos) -> bool:
    """Permissivo de segurança: 86 (ou outro impedimento) ativo → religamento remoto NÃO autorizado."""
    return PROTECAO_IMPEDIMENTO in {str(c).strip().upper() for c in (codigos or [])}
