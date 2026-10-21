# -*- coding: utf-8 -*-
"""O vínculo ocorrência ↔ OS da aba Strings e trackers (Levi, 20/10/2026, Nexus > Performance > Strings e trackers:
"1.5 Opção de vincular OS, eu clico no botão e buscas as OSs de recomposição de string desse inversor (...) 1.7 A OS só
carrega se eu clicar em vincular, caso eu não clique não deve carregar nem fazer requisição alguma do fractal (...) 1.8
faça algo parecido com os trackers!"). A regra pura; a leitura e a gravação no banco são as da `cobertura.Decisoes`,
como no de-para de equipamentos (`depara.py`).

Por que gravar: a OS existe no Fracttal, mas nada ligava a ocorrência que a aba mede à OS que a resolve, e o Fracttal
sozinho não diz qual é. Guatambu 1.2, parada de 01 a 20/10, tem a OS 16561 em andamento (evento 01/10); a Mandaguaçu 4.4
(01 a 15/10) só tem a 9915, de 23/07, ANTERIOR à parada — não é a que resolve esta; a Sete Lagoas Tracker 1.49 (01 a
17/10) tem a 15481, que é de dois trackers. Quem decide é o analista, na tela. O que aparece sem clique vem daqui (do
banco do Nexus), nunca do Fracttal: é o 1.7.

O dado (governança do Nexus, `nexus/dados/CLAUDE.md`): livro `nexus_falhas`, aba `fato_decisao_vinculo_os`, registrado no
catálogo do Nexus antes da 1ª gravação (regra 10). Grão: 1 linha = 1 decisão de ligar (ou desligar) 1 OS do Fracttal a 1
ocorrência de string (o inversor) ou a 1 parada de tracker. Tipo: sem medida. Só acrescenta: o vigente é a última decisão
de cada (tipo, fonte, plant_id, equipamento, dia_inicio, os). Sem pessoa nem texto livre (regra 8: a API do banco é de
leitura aberta): quem vinculou vai só ao log da máquina (`logs/falhas_vinculos.log`); a descrição da OS não vai — o
número basta.

A ocorrência entra pela chave de negócio: fonte + plant_id + equipamento (o inversor nas strings, o tracker nos trackers,
como a tela os nomeia) + o DIA do início. O dia, não a hora: o backfill refaz o dia e a hora do início anda alguns
minutos — a mesma razão da chave do "Tirar da conta" (`falhas_job.chave_str`). A tela cola o vínculo na ocorrência do
mesmo equipamento cujo intervalo de dias contém o `dia_inicio`, para ele não desgrudar quando o início anda.

No livro, o dia do início é a 2ª data do fato e vai como PAPEL, em inteiro AAAAMMDD (`data_id_inicio`, regra 7 do Nexus,
como o `data_id` da decisão); a API da tela segue com `dia_inicio` "AAAA-MM-DD" — a conversão mora aqui, na gravação
(`linha`) e na leitura (`vigentes`).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

LIVRO = "nexus_falhas"
NOME_LIVRO = "Nexus · Falhas de strings e trackers (vínculo com OS)"
ABA = "fato_decisao_vinculo_os"
CAB = ["decidida_em", "data_id", "tipo", "fonte", "plant_id", "equipamento", "data_id_inicio", "os", "decisao", "origem"]
TIPOS = ("strings", "trackers")
DECISOES = ("vincular", "desvincular")
ORIGENS = ("tela",)
# As fontes do pacote da aba (falhas_job): as das strings e as dos trackers — a mesma lista do rótulo do workbook
# (falhas_publicar.FONTE_ROT), conferida no teste. Fonte fora dela é linha que nenhuma ocorrência da tela tem.
FONTES = ("pv", "pvsb", "pg", "sunop", "axis", "owen", "solaredge", "greenyellow", "salenergia")
TEXTO_MAX = 120

_BRT = timezone(timedelta(hours=-3))
_RX_DIA = re.compile(r"\d{4}-\d{2}-\d{2}")
_RX_PID = re.compile(r"[A-Za-z0-9_.:-]{1,40}")
_RX_EQ = re.compile(r"[\w .,#/()+-]{1,40}")
OS_MAX = 10 ** 9                                         # a OS do Fracttal está na casa dos 17 mil (outubro de 2026)


def agora_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dia_brasilia(quando: str) -> int:
    """`data_id` = o dia de Brasília da decisão (regra 7 do Nexus), como no de-para."""
    d = datetime.strptime(quando, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(_BRT)
    return int(d.strftime("%Y%m%d"))


def _txt(v) -> str:
    """Texto da chave. O número que o banco devolve como 297378.0 volta a ser "297378": o plant_id é sempre texto
    (falhas_publicar._pid — "297378" e 297378 seriam duas ocorrências)."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return "" if v is None else str(v).strip()


def _dia(v) -> str:
    """AAAA-MM-DD que existe no calendário; o resto é erro."""
    s = _txt(v)[:10]
    if not _RX_DIA.fullmatch(s):
        raise ValueError(f"dia_inicio inválido: {v!r} (AAAA-MM-DD)")
    datetime.strptime(s, "%Y-%m-%d")                     # 2026-02-30 levanta ValueError
    return s


def data_id(dia_iso) -> int:
    """"2026-10-01" → 20261001: o papel da data no livro (regra 7 do Nexus)."""
    return int(_dia(dia_iso).replace("-", ""))


def dia_de_data_id(v) -> str:
    """20261001 (ou 20261001.0, ou "20261001", como o banco devolver) → "2026-10-01"; fora disso, ValueError."""
    s = _txt(v)
    if not re.fullmatch(r"\d{8}", s):
        raise ValueError(f"data_id_inicio inválido: {v!r} (AAAAMMDD)")
    return _dia(f"{s[:4]}-{s[4:6]}-{s[6:]}")


def _os(v) -> int:
    """Nº da OS: inteiro positivo, em número ou em texto só de dígitos ("16561"). Booleano não é número."""
    if isinstance(v, bool):
        raise ValueError(f"os inválida: {v!r}")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int):
        n = v
    elif isinstance(v, str) and v.strip().isdigit():
        n = int(v.strip())
    else:
        raise ValueError(f"os inválida: {v!r} (o número da OS)")
    if n <= 0 or n > OS_MAX:                             # sem teto, 99999999999999999999 voltava do banco como 1e+20
        raise ValueError(f"os inválida: {v!r} (o número da OS)")
    return n


def linha(tipo: str, fonte: str, plant_id, equipamento, dia_inicio, os, decisao: str, origem: str = "tela",
          quando: str | None = None) -> list:
    """Uma decisão, na ordem do CAB. Confere tudo antes: o que chega aqui vai para um banco de leitura aberta.
    `dia_inicio` chega "AAAA-MM-DD" (a API da tela) e vai ao livro como `data_id_inicio` AAAAMMDD."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo inválido: {tipo!r} (strings ou trackers)")
    if decisao not in DECISOES:
        raise ValueError(f"decisão inválida: {decisao!r} (vincular ou desvincular)")
    if origem not in ORIGENS:
        raise ValueError(f"origem inválida: {origem!r}")
    f = _txt(fonte)
    if f not in FONTES:
        raise ValueError(f"fonte desconhecida: {fonte!r}")
    pid, eq = _txt(plant_id), _txt(equipamento)
    # Só a FORMA de um id e de um nome de equipamento (revisão de 20/10/2026: o livro é de leitura aberta e nunca se
    # apaga, e aceitava "Fulano da Silva" no plant_id e telefone com quebra de linha no equipamento — regra 8 do Nexus,
    # nada de texto livre). Medido nos pacotes de setembro e outubro: todo plant_id é [A-Za-z0-9_.:-] (o id da API PV,
    # do banco, o código da SunOp) e todo equipamento tem um número ("Inversor 1.2", "INV-402513", "TRK67", "Tracker
    # 95"), com no máximo 13 caracteres.
    if not _RX_PID.fullmatch(pid):
        raise ValueError(f"plant_id inválido: {plant_id!r} (o id da usina na fonte)")
    if not _RX_EQ.fullmatch(eq) or not re.search(r"\d", eq):
        raise ValueError(f"equipamento inválido: {equipamento!r} (o nome do inversor ou do tracker)")
    dia, n = data_id(dia_inicio), _os(os)
    quando = quando or agora_utc()
    return [quando, _dia_brasilia(quando), tipo, f, pid, eq, dia, n, decisao, origem]


def _como_dict(lin) -> dict:
    return dict(zip(CAB, lin)) if isinstance(lin, (list, tuple)) else dict(lin)


def vigentes(linhas) -> list:
    """Os vínculos que valem: a última decisão de cada (tipo, fonte, plant_id, equipamento, data_id_inicio, os) — a mais
    recente; no empate, a que veio depois — quando ela é `vincular`. Linha que não se lê (tipo, fonte, data ou OS fora
    do formato) não conta. → [{tipo, fonte, plant_id, equipamento, dia_inicio "AAAA-MM-DD", os, decidida_em}], em ordem
    de chave (o dia volta ao formato da API da tela)."""
    marcadas = []
    for i, lin in enumerate(linhas or []):
        d = _como_dict(lin)
        try:
            tipo, f, dec = _txt(d.get("tipo")), _txt(d.get("fonte")), _txt(d.get("decisao"))
            pid, eq = _txt(d.get("plant_id")), _txt(d.get("equipamento"))
            if tipo not in TIPOS or f not in FONTES or dec not in DECISOES or not pid or not eq:
                continue
            if _txt(d.get("origem")) not in ORIGENS:
                continue
            chave = (tipo, f, pid, eq, dia_de_data_id(d.get("data_id_inicio")), _os(d.get("os")))
        except ValueError:
            continue
        marcadas.append((_txt(d.get("decidida_em")), i, chave, dec))
    estado = {}
    for quando, _i, chave, dec in sorted(marcadas):
        estado[chave] = (dec, quando)
    return [{"tipo": k[0], "fonte": k[1], "plant_id": k[2], "equipamento": k[3], "dia_inicio": k[4], "os": k[5],
             "decidida_em": quando}
            for k, (dec, quando) in sorted(estado.items()) if dec == "vincular"]
