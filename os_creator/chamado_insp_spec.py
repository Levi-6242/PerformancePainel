"""Ponte para o pacote `chamado_garantia` — o conteúdo REAL mora lá.

A lógica de abertura de chamado foi extraída em 30/07/2026 para o app de campo (celular) usar a
mesma regra pelo botão "Necessário abrir chamado". Este arquivo virou um repasse para não quebrar
os imports existentes (`import chamado_insp_spec as ci` está espalhado pelas telas).

**Não escreva regra aqui.** Toda alteração de subtarefa, marca ou tipo de ativo vai em
`chamado_garantia/spec.py`. Duas cópias divergindo significa a OS do supervisor e a do técnico
pedindo coisas diferentes ao mesmo fabricante — o problema que este projeto veio resolver.
"""
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:                       # o pacote mora na RAIZ do repositório, não aqui
    # APPEND, nunca insert(0): a raiz tem um `app.py` (o da plataforma) que sombrearia o
    # `os_creator/app.py`. Ver a nota longa no api.py.
    sys.path.append(_RAIZ)

from chamado_garantia.regras import (CLASSIF_1, CLASSIF_2, ETIQUETA,  # noqa: F401
                                     ETIQUETA_ACOMPANHAMENTO, TIPO_TAREFA,
                                     TIPO_TAREFA_ACOMPANHAMENTO, descobrir_marca,
                                     marca_pelos_irmaos, montar, pode_abrir, titulo)
from chamado_garantia.spec import *          # noqa: F401,F403  (repasse deliberado)
from chamado_garantia.spec import (ALIAS_TIPO, BASE, DIAS_DOA, MARCAS_CONHECIDAS,  # noqa: F401
                                   POR_FABRICANTE, POR_TIPO, TIPO_ID, TIPOS_DA_MARCA, aceita,
                                   derivados, grupo_de, marca_do_ativo, marcas_para, resumo,
                                   subtarefas)
