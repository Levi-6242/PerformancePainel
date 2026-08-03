"""Regras do chamado de garantia que NÃO dependem de tela nem de cliente HTTP.

Aqui mora tudo que decide *o que* a OS de inspeção leva: tipo de tarefa, classificação, etiqueta,
como a marca é descoberta e o que o app preenche no lugar do técnico. Nada aqui importa PyQt nem
`requests` — é de propósito, para o app de campo poder usar o mesmo código sem arrastar a interface
do OS Creator junto.

Quem consome:
  - `os_creator/` (desktop, supervisor abre a inspeção)
  - o app de campo (celular): botão "Necessário abrir chamado" dentro da OS que o técnico preenche
"""
import re
import unicodedata

from . import spec

# ── como a OS de inspeção nasce no Fracttal ───────────────────────────────────────────────────
TIPO_TAREFA = "Inspeção"          # id_task_type_main 43889 na conta 4987
CLASSIF_1 = "Programada"          # Classificação 1
CLASSIF_2 = "Elétrica"            # Classificação 2
ETIQUETA = "Aguardando Garantia"  # id 2036 — já existia no Fracttal

# A OS de acompanhamento (a 3ª do fluxo, aberta pela equipe de chamados) é outra coisa:
TIPO_TAREFA_ACOMPANHAMENTO = "Administrativa"
ETIQUETA_ACOMPANHAMENTO = "CHAMADOS"

# De QUAIS OS pode nascer uma inspeção de chamado. Quando o Levi diz "corretiva" ele quer dizer os
# quatro (30/07) — religamento é corretiva de outro nome, e o técnico que foi religar e não
# conseguiu é exatamente quem descobre que precisa de garantia. É a mesma lista que a visão COS do
# histórico usa, e por isso mora aqui: as duas telas leem daqui.
TIPOS_ORIGEM = ("Corretiva", "Corretiva Emergencial", "Religamento", "Religamento Remoto")


def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s)


def marca_do_ativo(asset: dict) -> str:
    """Marca lida da DESCRIÇÃO do ativo ('' se não reconhecer).

    Medido no catálogo inteiro (29/07): a descrição carrega a marca em 94% dos inversores
    ('Inversor 1.1 Huawei SUN2000-250KTL-H1') e 85% das estruturas de tracker ('Tracker 1.100 STI
    STI-H250'). Na Estação Meteorológica é inútil — 1 de 106 — porque ali a descrição é o endereço.
    É PRÉ-SELEÇÃO: quem abre confirma."""
    txt = _n("%s %s" % (asset.get("description") or "", asset.get("label") or ""))
    for m in spec.MARCAS_CONHECIDAS:
        if _n(m) in txt:
            return m
    return ""


def marca_pelos_irmaos(asset: dict, catalogo, marcas_validas=None) -> str:
    """Marca inferida dos ativos IRMÃOS da mesma usina, quando o próprio não a diz.

    NCU, RSU e os sensores da estação se chamam só 'NCU 1', 'Piranômetro 1'. Mas os trackers da
    mesma planta dizem a marca, e a NCU de uma planta de trackers STI é STI. Só sugere quando os
    irmãos apontam para UMA marca válida — duas marcas na usina devolvem '', que é o honesto."""
    usi = asset.get("usina")
    if not usi:
        return ""
    validas = set(marcas_validas or spec.marcas_para(asset.get("tipo")))
    if not validas:
        return ""
    achadas = set()
    for x in catalogo or []:
        if x.get("usina") != usi or x is asset:
            continue
        m = marca_do_ativo(x)
        if m in validas:
            achadas.add(m)
            if len(achadas) > 1:
                return ""
    return next(iter(achadas), "")


def descobrir_marca(asset: dict, catalogo=None) -> str:
    """Marca do ativo: primeiro o texto dele, depois os irmãos da usina. '' = precisa perguntar."""
    return marca_do_ativo(asset) or (marca_pelos_irmaos(asset, catalogo) if catalogo else "")


def titulo(asset: dict, fabricante: str) -> str:
    """'[Ativo] - Inspeção para chamado <marca>' — o padrão de título das OS do OS Creator."""
    ativo = (str(asset.get("description") or "").split("{")[0]).strip()[:60] or asset.get("code")
    return "[%s] - Inspeção para chamado %s" % (ativo, str(fabricante or "").strip())


def montar(asset: dict, fabricante: str, catalogo=None) -> dict:
    """Tudo o que a OS de inspeção precisa, num dicionário só. É ESTE o contrato que o app de campo
    consome ao clicar em "Necessário abrir chamado".

    → {'tipo_tarefa','classif_1','classif_2','etiqueta','titulo','fabricante','subtarefas','resumo'}

    O que NÃO vem daqui, porque é do contexto de quem chama: ativo, data do incidente, responsável
    e OS pai. No app de campo os quatro saem da OS que o técnico já está preenchendo."""
    fab = str(fabricante or "").strip() or descobrir_marca(asset, catalogo)
    subs = spec.subtarefas(asset.get("tipo"), fab)
    return {
        "tipo_tarefa": TIPO_TAREFA,
        "classif_1": CLASSIF_1,
        "classif_2": CLASSIF_2,
        "etiqueta": ETIQUETA,
        "titulo": titulo(asset, fab),
        "fabricante": fab,
        "subtarefas": subs,
        "resumo": spec.resumo(asset.get("tipo"), fab),
    }


def derivados(asset: dict, event_date, hoje=None) -> dict:
    """Campos do chamado que o APP sabe — não viram pergunta para o técnico. Ver `spec.derivados`."""
    return spec.derivados(asset.get("tipo"), event_date, hoje=hoje)


def pode_abrir(asset: dict, tipo_tarefa_os: str = None) -> bool:
    """O botão "Necessário abrir chamado" deve aparecer nesta OS?

    Duas condições, e as duas importam:
      1. o ATIVO tem modelo de subtarefa (`spec.aceita`) — não adianta oferecer o botão num
         transformador, para o qual não existe processo de chamado escrito;
      2. a OS é de origem válida (`TIPOS_ORIGEM`) — corretiva, corretiva emergencial, religamento
         ou religamento remoto. `tipo_tarefa_os=None` pula esta checagem, para quem chama de uma
         tela que já filtrou (é o caso do card "Inspeção de chamados" do OS Creator, onde a pessoa
         escolhe o ativo do zero e não parte de uma OS)."""
    if not spec.aceita(asset.get("tipo")):
        return False
    if tipo_tarefa_os is None:
        return True
    return str(tipo_tarefa_os).strip() in TIPOS_ORIGEM
