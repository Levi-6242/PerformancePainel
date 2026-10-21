"""A estrutura das usinas do Nexus no lugar da aba Equipamentos (fase 2, 13/10/2026).

Levi, 13/10/2026: "Temos que substituir a aba equipamentos aproveitando o que tem lá e usando o Nexus como ponto de
partida" e, com a tela pronta no Nexus (Base > Equipamentos das usinas), "pode fazer todas as fases! vamos pra cima!".

Como: o Nexus publica no banco, no livro `nexus_estrutura_usina`, a aba `aba_equipamentos`: a estrutura das chaves que
o Levi marcou "no lugar da aba", no MESMO formato da aba Equipamentos do BD_Performance (as mesmas colunas, com os IDs do
Nexus no fim). Aqui, cada leitura da aba troca as linhas dessas chaves pelas da visão (`sobrepor_df`): tira da aba as
linhas de UFV, UG e inversor das chaves que a visão traz e põe as da visão. O resto do leitor (o `load_equipamentos`, o
mapa do "Usina Fractall" e a disponibilidade) não muda: é a mesma linha, vinda de outro lugar.

- A chave de cada linha é a da plataforma: "Usina Supervisório" e, sem ela, "Usina" (`chave_efetiva`, o `us` do
  `load_equipamentos`). Chave fora da visão segue da aba, como sempre. A comparação é pelo texto() (espaços juntados), e
  a linha da visão HERDA a grafia da aba (`herda_grafia`, 20/10/2026: a "Assis Chateaubriand  Skid 1 (79)" de espaço
  duplo perdia o cadastro inteiro no tempo real depois de marcada).
- Livro que não existe, vazio ou ilegível sem cópia boa = nada troca (a aba inteira, como antes). `ESTRUTURA_NEXUS=0`
  desliga numa máquina.
- A mesma regra está no Nexus (`nexus/cadastro/estrutura_usina.py`, `sobrepor`), no gêmeo e no coletor: mudou lá, muda aqui.
- "Código Fracttal" (Modo de-para, 20/10/2026): o código do ativo no Fracttal que o Nexus grava (`dim_inversor` e
  `dim_cabine.codigo_fracttal`), na linha do inversor e na da UG, no FIM da visão. A aba Equipamentos não tem a coluna: as
  linhas dela chegam vazias, e o `load_equipamentos` monta os mapas do código (FRAC_COD_INV, FRAC_COD_CAB) só com o que veio
  do Nexus. A leitura do livro é por NOME de coluna (`cobertura.Decisoes`): coluna que não está aqui não chega.
"""
import hashlib
import json

LIVRO, ABA, NOME_LIVRO = "nexus_estrutura_usina", "aba_equipamentos", "Nexus · estrutura das usinas"
CAB = ("Cliente", "Usina", "Usina Supervisório", "Usina Fractall", "Equipamento", "Equipamento Supervisório",
       "Equipamento Parente", "Chave", "Chave 2", "Potência (kWp)", "N de Inversores", "String Box", "Full O&M",
       "Strings Ativas", "usina_id", "supervisorio_id", "cabine_id", "inversor_id", "Código Fracttal")


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


# As colunas que dão a chave da linha (`chave_efetiva`): a grafia delas é a que o leitor guarda e a fonte procura.
COLS_DA_CHAVE = ("Usina Supervisório", "Usina")


def grafias_da_aba(linhas_aba) -> dict:
    """{texto(nome): o nome como a aba o escreve} das colunas da chave, só onde a grafia da aba não é o próprio texto()
    (espaço duplo, tabulação). A "Usina Supervisório" vence a "Usina" quando as duas escrevem o mesmo nome."""
    out = {}
    for col in COLS_DA_CHAVE:
        for x in linhas_aba or ():
            v = x.get(col)
            if not isinstance(v, str):
                continue
            t, crua = texto(v), v.strip()
            if t and crua != t:
                out.setdefault(t, crua)
    return out


def herda_grafia(visao, grafias, fracttal=None) -> list[dict]:
    """As linhas da visão com a "Usina Supervisório" e a "Usina" escritas COMO NA ABA quando o texto() bate (20/10/2026).

    O caso: a aba e a API PV escrevem "Assis Chateaubriand  Skid 1 (79)" (espaço duplo) e o Nexus grava a chave com
    texto() ("... Chateaubriand Skid 1 ..."). O `sobrepor` já tirava as linhas da aba pelo texto(), mas a visão entrava com
    a grafia do Nexus, o `load_equipamentos` guardava a chave de espaço único e o `build_summary` (que procura o
    ESPERADO_INV pela grafia exata da API) deixava a usina sem esperadas, kWp, nome de exibição e Full O&M, sem aviso
    nenhum. Herdando a grafia da aba, a chave marcada no lugar da aba segue igual à aba para todo leitor. Chave que a aba
    não tem fica como o Nexus escreve.

    O "Usina Fractall" também herda (`fracttal`, de `grafias_fracttal`; 2ª revisão final, 21/10/2026), pela MESMA chave
    e quando o texto() bate: o `_frac_usina_ent` procura a usina no índice do Fracttal pela description exata, e a "Thopen -
    Belo Jardim  1 - PE" (espaço duplo na aba e no Fracttal) escrita com os espaços juntados deixava a Belo Jardim marcada
    "fora do Fracttal": sem o badge de OS abertas, sem as OS no Diagnóstico e com a cascata de queda (h_rede/h_equip) em 0.
    Nome de outra letra (acento) não herda: o Nexus compara e a chave não vale no lugar da aba."""
    if not grafias and not fracttal:
        return [dict(x) for x in visao or ()]
    out = []
    for x in visao or ():
        y, k = dict(x), chave_efetiva(x)
        for col in COLS_DA_CHAVE:
            g = (grafias or {}).get(texto(y.get(col)))
            if g is not None:
                y[col] = g
        fr = (fracttal or {}).get((k, texto(y.get("Usina Fractall"))))
        if fr is not None:
            y["Usina Fractall"] = fr
        out.append(y)
    return out


def grafias_fracttal(linhas_aba) -> dict:
    """{(chave, texto(nome)): o "Usina Fractall" como a aba o escreve, só sem as pontas}, da 1ª linha de cada chave."""
    out = {}
    for x in linhas_aba or ():
        v = x.get("Usina Fractall")
        if isinstance(v, str) and v.strip():
            out.setdefault((chave_efetiva(x), texto(v)), v.strip())
    return out


def sobrepor(linhas_aba, visao) -> tuple[list, int]:
    """(as linhas da aba com as chaves da visão trocadas, quantas linhas da aba saíram). Lista de dicionários. A visão
    entra com a grafia da aba nas chaves que as duas têm (`herda_grafia`)."""
    visao = list(visao or ())
    chaves = {chave_efetiva(x) for x in visao}
    if not chaves:
        return list(linhas_aba or ()), 0
    fica = [x for x in linhas_aba or () if chave_efetiva(x) not in chaves or not tipo(x.get("Equipamento"))]
    return (fica + herda_grafia(visao, grafias_da_aba(linhas_aba), grafias_fracttal(linhas_aba)),
            len(list(linhas_aba or ())) - len(fica))


def sobrepor_df(df, visao):
    """O mesmo `sobrepor` para o DataFrame da aba (o `pd.read_excel` da plataforma): (DataFrame, linhas que saíram)."""
    import pandas as pd
    visao = list(visao or ())
    chaves = {chave_efetiva(x) for x in visao}
    if not chaves:
        return df, 0
    registros = df.to_dict("records")
    fica = [not (chave_efetiva(r) in chaves and tipo(r.get("Equipamento"))) for r in registros]
    novo = pd.DataFrame(herda_grafia(visao, grafias_da_aba(registros), grafias_fracttal(registros)), columns=list(CAB))
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
