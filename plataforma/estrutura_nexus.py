"""A estrutura das usinas do Nexus no lugar da aba Equipamentos (fase 2, 13/10/2026).

Levi, 13/10/2026: "Temos que substituir a aba equipamentos aproveitando o que tem lá e usando o Nexus como ponto de
partida" e, com a tela pronta no Nexus (Base > Equipamentos das usinas), "pode fazer todas as fases! vamos pra cima!".

Como: o Nexus publica no banco, no livro `nexus_estrutura_usina`, a aba `aba_equipamentos`: a estrutura das chaves que
o Levi marcou "no lugar da aba", no MESMO formato da aba Equipamentos do BD_Performance (as mesmas colunas, com os IDs do
Nexus no fim). Aqui, cada leitura da aba troca as linhas dessas chaves pelas da visão (`sobrepor_df`): tira da aba as
linhas de UFV, UG e inversor das chaves que a visão traz e põe as da visão. O resto do leitor (o `load_equipamentos`, o
mapa do "Usina Fractall" e a disponibilidade) não muda: é a mesma linha, vinda de outro lugar.

- A chave de cada linha é a da plataforma: "Usina Supervisório" e, sem ela, "Usina" (`chave_efetiva`, o `us` do
  `load_equipamentos`). Chave fora da visão segue da aba, como sempre.
- Livro que não existe, vazio ou ilegível sem cópia boa = nada troca (a aba inteira, como antes). `ESTRUTURA_NEXUS=0`
  desliga numa máquina.
- A mesma regra está no Nexus (`nexus/cadastro/estrutura_usina.py`, `sobrepor`), no gêmeo e no coletor: mudou lá, muda aqui.
"""
import hashlib
import json

LIVRO, ABA, NOME_LIVRO = "nexus_estrutura_usina", "aba_equipamentos", "Nexus · estrutura das usinas"
CAB = ("Cliente", "Usina", "Usina Supervisório", "Usina Fractall", "Equipamento", "Equipamento Supervisório",
       "Equipamento Parente", "Chave", "Chave 2", "Potência (kWp)", "N de Inversores", "String Box", "Full O&M",
       "Strings Ativas", "usina_id", "supervisorio_id", "cabine_id", "inversor_id")


def texto(v) -> str:
    """Texto limpo; vazio para None e para o NaN do pandas."""
    if v is None or (isinstance(v, float) and v != v):
        return ""
    return " ".join(str(v).split())


def chave_efetiva(linha) -> str:
    """A chave da linha, como a plataforma a lê: "Usina Supervisório" e, sem ela, "Usina"."""
    return texto(linha.get("Usina Supervisório")) or texto(linha.get("Usina"))


def tipo(equipamento) -> str:
    """"ufv", "ug", "inversor" ou "" (o que não é nenhum dos três fica sempre da aba)."""
    e = texto(equipamento)
    if e.upper() == "UFV":
        return "ufv"
    if e.upper().startswith("UG"):
        return "ug"
    if e.lower().startswith("inversor"):
        return "inversor"
    return ""


def linhas(lidas) -> list[dict]:
    """As linhas lidas do livro (listas na ordem de `CAB`, como o `cobertura.Decisoes` devolve) como dicionários, sem as
    que não têm chave."""
    out = []
    for x in lidas or ():
        d = dict(zip(CAB, x)) if isinstance(x, (list, tuple)) else dict(x)
        if chave_efetiva(d):
            out.append(d)
    return out


def marca(visao) -> str:
    """A impressão da visão: mudou, o cadastro relê (a leitura do livro devolve uma lista nova a cada minuto, mesmo igual)."""
    corpo = json.dumps([[texto(x.get(c)) for c in CAB] for x in visao or ()], ensure_ascii=False)
    return hashlib.sha1(corpo.encode("utf-8")).hexdigest()[:16]


def sobrepor(linhas_aba, visao) -> tuple[list, int]:
    """(as linhas da aba com as chaves da visão trocadas, quantas linhas da aba saíram). Lista de dicionários."""
    visao = list(visao or ())
    chaves = {chave_efetiva(x) for x in visao}
    if not chaves:
        return list(linhas_aba or ()), 0
    fica = [x for x in linhas_aba or () if chave_efetiva(x) not in chaves or not tipo(x.get("Equipamento"))]
    return fica + visao, len(list(linhas_aba or ())) - len(fica)


def sobrepor_df(df, visao):
    """O mesmo `sobrepor` para o DataFrame da aba (o `pd.read_excel` da plataforma): (DataFrame, linhas que saíram)."""
    import pandas as pd
    visao = list(visao or ())
    chaves = {chave_efetiva(x) for x in visao}
    if not chaves:
        return df, 0
    fica = [not (chave_efetiva(r) in chaves and tipo(r.get("Equipamento"))) for r in df.to_dict("records")]
    novo = pd.DataFrame(visao, columns=list(CAB))
    out = pd.concat([df[fica], novo], ignore_index=True, sort=False)
    return out, len(fica) - sum(fica)


def resumo(visao) -> dict:
    """{chave: {"inversores", "strings", "usina_id"}} da visão, para o diagnóstico."""
    out = {}
    for x in visao or ():
        k = chave_efetiva(x)
        r = out.setdefault(k, {"inversores": 0, "strings": 0, "usina_id": x.get("usina_id"), "linhas": 0})
        r["linhas"] += 1
        if tipo(x.get("Equipamento")) == "inversor":
            r["inversores"] += 1
            try:
                r["strings"] += int(float(x.get("Strings Ativas")))
            except (TypeError, ValueError):
                pass
    return out
