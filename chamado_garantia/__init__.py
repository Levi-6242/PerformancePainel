"""chamado_garantia — a lógica de abertura de chamado de garantia, sem interface e sem HTTP.

Extraído do OS Creator em 30/07/2026 para o app de campo poder usar a MESMA regra. Foi extraído,
não copiado: o OS Creator importa daqui. Se as duas cópias divergirem, a OS do supervisor e a do
técnico passam a pedir coisas diferentes ao mesmo fabricante — que é exatamente o problema que este
projeto veio resolver.

O fluxo em três OS (ver o diagrama do processo):
    1. OS DE CAMPO           · Corretiva      · sem etiqueta
    2. OS DE CHAMADOS        · Inspeção       · Aguardando Garantia   ← é esta que este pacote monta
    3. OS DE ACOMPANHAMENTO  · Administrativa · CHAMADOS

Uso no app de campo, dentro da OS que o técnico está preenchendo:

    import chamado_garantia as cg

    if cg.pode_abrir(ativo):                      # mostra o botão "Necessário abrir chamado"
        ...
    dados = cg.montar(ativo, fabricante="", catalogo=todos_os_ativos)
    # dados['subtarefas'] já vem no formato do RPC do Fracttal
    # ativo, data do incidente, responsável e OS pai vêm da OS que ele já tem aberta

Quem for criar a OS de fato precisa de um cliente Fracttal. O `payload.py` monta os parâmetros do
RPC sem falar com a rede, então serve tanto ao desktop quanto a um backend do app de campo.
"""
from .ativos import TIPO_POR_SUFIXO, tipo_do_ativo, tipo_e_sufixo
from .regras import (CLASSIF_1, CLASSIF_2, ETIQUETA, ETIQUETA_ACOMPANHAMENTO, TIPO_TAREFA,
                     TIPO_TAREFA_ACOMPANHAMENTO, TIPOS_ORIGEM, derivados, descobrir_marca,
                     marca_do_ativo, marca_pelos_irmaos, montar, pode_abrir, titulo)
from .spec import (ALIAS_TIPO, BASE, MARCAS_CONHECIDAS, POR_FABRICANTE, POR_TIPO, TIPO_ID,
                   TIPOS_DA_MARCA, aceita, grupo_de, marcas_para, resumo, subtarefas)

__all__ = [
    # o tipo do ativo NÃO vem do Fracttal: é derivado do código. Use `tipo_do_ativo` — não
    # reimplemente, senão os dois apps classificam o mesmo ativo de formas diferentes.
    "tipo_do_ativo", "tipo_e_sufixo", "TIPO_POR_SUFIXO",
    "montar", "pode_abrir", "descobrir_marca", "marca_do_ativo", "marca_pelos_irmaos",
    "derivados", "titulo", "subtarefas", "marcas_para", "resumo", "aceita", "grupo_de",
    "TIPO_TAREFA", "CLASSIF_1", "CLASSIF_2", "ETIQUETA", "TIPOS_ORIGEM",
    "TIPO_TAREFA_ACOMPANHAMENTO", "ETIQUETA_ACOMPANHAMENTO",
    "BASE", "POR_TIPO", "POR_FABRICANTE", "ALIAS_TIPO", "TIPOS_DA_MARCA", "MARCAS_CONHECIDAS",
    "TIPO_ID",
]
__version__ = "1.1.0"     # 1.1.0: ativos.py (tipo do ativo pelo código)
