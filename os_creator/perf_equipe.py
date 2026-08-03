"""Quem são os analistas de Performance — as colunas do board.

NÃO fica cravado no código de propósito: o Levi pediu "quero que haja a possibilidade de
adicionar mais pessoas". A lista mora num JSON ao lado do resto do estado do app e pode ser
editada pela tela, sem release.

O casamento com o Fracttal é **pelo NOME**, porque é o que a listagem de OS devolve
(`atribuido_a`, vindo de `user_assigned`). O `id_personnel` é guardado junto quando conhecido,
para a criação de OS — mas o board não depende dele.

CUIDADO com nomes parecidos: o pessoal do Fracttal tem **"Gabriela Dias"** e **"Gabriel
Oliveira"** — casar por prefixo juntaria os dois. Por isso a comparação é por nome inteiro
normalizado, nunca por "começa com".
"""
import json
import os
import unicodedata

import api

# COR DA COLUNA de cada analista — um degradê levíssimo atrás da fila, só para o olho achar a
# própria coluna sem ler o nome. NÃO usa o vermelho nem o âmbar do semáforo: nesta tela eles já
# significam "prioridade máxima" e "pedido de cliente", e a mesma cor não pode dizer duas coisas.
# Sem lilás — convenção da casa (tema navy + verde Grid).
# COR DA PESSOA — no 1B ela pinta APENAS o círculo da inicial no cabeçalho da coluna (20px).
# O véu atrás da fila SAIU: com 4 pessoas ele já competia com o semáforo e, com 6, matiz deixa de
# identificar quem é quem — seis tons distinguíveis entre si e fora do vermelho/âmbar não existem.
# Continua fora do semáforo, e sem lilás (convenção da casa).
VERDE_GRID = "#A8C842"          # o verde da casa com o neon a menos
CORES = [VERDE_GRID, "#3FB89C", "#5AA9D0", "#8AB84A", "#4FC0B0", "#6F9FD0"]
COR_PADRAO = VERDE_GRID


def cor_de(d) -> str:
    """Cor da coluna de um analista, com queda para o cinza neutro."""
    c = str((d or {}).get("cor") or "").strip()
    return c if c.startswith("#") and len(c) in (4, 7) else COR_PADRAO


# Os quatro que o Levi indicou em 27/07. Servem de semente; a lista real vive no JSON.
PADRAO = [
    {"nome": "Ana Barros",     "id_personnel": None, "cor": CORES[0]},
    {"nome": "Roger Lélis",    "id_personnel": None, "cor": CORES[1]},
    {"nome": "Gabriela Dias",  "id_personnel": None, "cor": CORES[2]},
    {"nome": "Levi Maia",      "id_personnel": None, "cor": CORES[3]},
]


def _caminho():
    try:
        return os.path.join(api._data_dir(), "perf_equipe.json")
    except Exception:
        return None


def _norm(s):
    """Sem acento, sem caixa, sem espaço duplicado. O Fracttal devolve nomes com espaço
    dobrado ('Luiz  Silva') — sem colapsar, o casamento falha."""
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def carregar() -> list:
    """→ [{'nome','id_personnel'}] na ordem em que aparecem no board."""
    p = _caminho()
    if p and os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                dados = json.load(f)
            if isinstance(dados, list) and dados:
                lista = [d for d in dados if isinstance(d, dict) and d.get("nome")]
                # instalação antiga não tem `cor` gravada: distribui a paleta pela ORDEM, em vez
                # de deixar todo mundo cinza (era o que acontecia — as quatro colunas saíam com
                # o mesmo véu). Só na leitura; grava quando a pessoa escolher.
                for i, d in enumerate(lista):
                    if not str(d.get("cor") or "").startswith("#"):
                        d["cor"] = CORES[i % len(CORES)]
                return lista
        except Exception:
            pass
    return [dict(d) for d in PADRAO]


def salvar(lista) -> bool:
    p = _caminho()
    if not p:
        return False
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump([{"nome": d.get("nome"), "id_personnel": d.get("id_personnel"),
                        "cor": cor_de(d)}
                       for d in (lista or []) if d.get("nome")], f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def adicionar(nome, id_personnel=None, cor=None) -> bool:
    nome = (nome or "").strip()
    if not nome:
        return False
    atual = carregar()
    if any(_norm(d["nome"]) == _norm(nome) for d in atual):
        return False                      # já está no board
    # sem cor escolhida, pega a próxima da paleta que ninguém está usando
    if not cor:
        usadas = {cor_de(d) for d in atual}
        cor = next((c for c in CORES if c not in usadas), COR_PADRAO)
    atual.append({"nome": nome, "id_personnel": id_personnel, "cor": cor})
    return salvar(atual)


def set_cor(nome, cor) -> bool:
    atual = carregar()
    for d in atual:
        if _norm(d["nome"]) == _norm(nome):
            d["cor"] = cor
            return salvar(atual)
    return False


def remover(nome) -> bool:
    atual = carregar()
    novo = [d for d in atual if _norm(d["nome"]) != _norm(nome)]
    return salvar(novo) if len(novo) != len(atual) else False


def distribuir(oss) -> dict:
    """OSs da `api.list_performance` → {nome do analista: [OSs]}, na ordem do board.

    A chave 'OUTROS' junta o que está com quem não é analista — hoje a maioria: das 378 OS de
    Performance dos últimos 90 dias, **328 estão com técnicos de campo** (Luiz Silva, Gilson
    Souza…) e só 50 com os analistas. É esperado: hoje a Performance ABRE e manda para o campo;
    a prática de OS entre analistas é o que esta tela vem criar. 'OUTROS' não vira coluna, mas
    fica acessível para não sumir com trabalho.
    """
    equipe = carregar()
    por = {d["nome"]: [] for d in equipe}
    idx = {_norm(d["nome"]): d["nome"] for d in equipe}
    fora = []
    for d in (oss or []):
        nome = idx.get(_norm(d.get("atribuido_a")))
        (por[nome] if nome else fora).append(d)
    por["OUTROS"] = fora
    return por


def sincronizar_ids(pessoas=None) -> int:
    """Preenche o id_personnel de quem ainda está sem, casando pelo nome com o pessoal do
    Fracttal. → quantos casaram. Silencioso se a API falhar (o board não depende disto)."""
    atual = carregar()
    if all(d.get("id_personnel") for d in atual):
        return 0
    try:
        pessoas = pessoas if pessoas is not None else api.get_responsaveis()
    except Exception:
        return 0
    mapa = {_norm(p.get("name")): p.get("id_personnel") for p in (pessoas or [])}
    n = 0
    for d in atual:
        if not d.get("id_personnel"):
            pid = mapa.get(_norm(d["nome"]))
            if pid:
                d["id_personnel"] = pid
                n += 1
    if n:
        salvar(atual)
    return n
