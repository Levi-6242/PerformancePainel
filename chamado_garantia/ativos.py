"""Tipo do ativo a partir do código do Fracttal — a REGRA, não uma tabela para copiar.

PARTE DO PACOTE `chamado_garantia` — puro, sem PyQt e sem rede. Ver o `__init__.py`.

Por que isto está aqui
──────────────────────
O resto do pacote consome `asset["tipo"]` com os valores "Inversor", "Estrutura Trackers", "NCU",
"RSU", "Estação Meteorológica", "Cabine", "Skid", "PRN", "SDT", "FDL". **Esse campo não existe no
Fracttal.** Procurado em todo o registro do ativo e da OS: `groups_description` e
`items_types_description` vêm ambos como "EQUIPMENTS", e `id_type_item` é 2 para tudo. O tipo é
DERIVADO do código (`APG100-INVR1.1` → Inversor), e a derivação morava no `api.py` do OS Creator.

Deduzir de novo do outro lado criaria a segunda fonte da verdade que este pacote existe para
evitar — e num ponto invisível: dois apps classificando o mesmo ativo de formas diferentes pedem
subtarefas diferentes ao mesmo fabricante, e ninguém percebe até o chamado voltar. Então a
derivação veio para cá, e o OS Creator passou a importar daqui.

Como o código é formado
───────────────────────
`{USINA}-{TIPO}{N}` com 2 ou 3 segmentos:

    APG100-INVR1.1            → INVR → Inversor
    THPN-CGH100-CABN1         → CABN → Cabine        (3 segmentos: vale o ÚLTIMO, não o 2º)
    APG100-ESTM1-PRN1         → PRN  → PRN           (sensor pendurado na estação)

Três detalhes que erram quem deduz de fora, medidos no catálogo real (11.735 ativos):

1. **Vale o ÚLTIMO segmento**, não uma posição fixa — o código tem 2 ou 3 partes.
2. **Sufixo desconhecido NÃO vira "Outro": vira ele mesmo.** É de propósito, e é o que faz NCU,
   RSU, PRN, SDT e FDL funcionarem sem estarem no mapa — são 563 ativos que o chamado aceita.
   Um mapa "completo" copiado à mão perderia exatamente esses.
3. **O item-USINA não se deduz do código.** `2C-APG100` é a usina inteira, e pelo sufixo daria
   "APG" (só as letras). Quem sabe disso é a HIERARQUIA, não o código: item cujo
   `parent_description` tem só o cliente é a usina; com cliente/usina é equipamento. Daí o
   `eh_usina` ser parâmetro — quem chama tem a hierarquia, esta função não.

O item 3 não muda o resultado do chamado (nem "Usina" nem "APG" são aceitos por `aceita()`, e o
botão fica escondido nos dois casos), mas muda o que aparece na tela e nos filtros. Só vira
problema se um dia um código de usina terminar com um sufixo aceito — hoje nenhum dos 402 termina.
"""

# Sufixo do código → nome do tipo. Só os que têm nome próprio; o resto passa direto pelo
# fallback (ver `tipo_do_ativo`). NÃO acrescente NCU/RSU/PRN/SDT/FDL aqui: eles já funcionam
# pelo fallback, e duplicá-los só cria dois lugares para editar.
TIPO_POR_SUFIXO = {
    "INVR": "Inversor", "TRK": "Tracker", "ETKR": "Estrutura Trackers", "SKID": "Skid",
    "CABN": "Cabine", "QGBT": "QGBT", "ESTM": "Estação Meteorológica",
    "TRFR": "Transformador", "TRTP": "Transformador", "TRTC": "Transformador",
    "INFC": "Infraestrutura Civil", "INFE": "Infraestrutura Elétrica", "SOEM": "Sala de O&M",
    "SSEG": "Sistema de Segurança", "SPDA": "SPDA", "SSPV": "Sistema FV", "STRG": "String Box",
}

TIPO_USINA = "Usina"
TIPO_DESCONHECIDO = "Outro"


def tipo_do_ativo(code: str, eh_usina: bool = False) -> str:
    """Nome do tipo do ativo. → "Inversor", "Estrutura Trackers", "NCU", "Usina", "Outro"…

    `eh_usina` = este registro é a USINA inteira, não um equipamento dela. Quem chama decide, pela
    hierarquia: no catálogo do Fracttal, o `parent_description` do equipamento tem cliente E usina
    ("Athon / Capitão Poço 1"), e o da usina tem só o cliente. Sem esse flag, `2C-APG100` viraria
    tipo "APG100".
    """
    if eh_usina:
        return TIPO_USINA
    return tipo_e_sufixo(code)[1]


def tipo_e_sufixo(code: str):
    """→ (sufixo, tipo). O sufixo é o que o OS Creator guarda como `tipo_code` e usa em filtro."""
    partes = str(code or "").split("-")
    if len(partes) >= 2:
        # só as LETRAS do último segmento: CABN4 → CABN, INVR1.1 → INVR
        sufixo = "".join(c for c in partes[-1] if c.isalpha())
        if sufixo:
            return sufixo, TIPO_POR_SUFIXO.get(sufixo, sufixo)   # desconhecido → ele mesmo
    return "", TIPO_DESCONHECIDO
