# -*- coding: utf-8 -*-
"""De-para de equipamentos, fatia 1 (11/10/2026): o diagnóstico, só leitura. Levi: "quero que o de-para da equipamentos
seja feito na plataforma de forma intuitiva". Antes de editar, ver: para cada usina de cada fonte, como ela se liga ao
cadastro (a aba Equipamentos do BD_Performance), se tem strings esperadas, se o número de inversores bate e de onde vem o
nome de cada inversor. As quatro quebras achadas no mesmo dia (a API renomeou a Ipixuna e a Morada Nova, que ficaram sem
esperadas; a União com 6 de 12 inversores e o grupo 2 rotulado como 1) apareceriam aqui no primeiro dia.

Regra pura (sem Flask, sem rede): recebe as linhas das tabelas de strings que já estão em cache e o que o código sabe do
de-para; o app.py junta. Nada grava.
"""
from __future__ import annotations

from cobertura import FONTES as ROTULOS   # as mesmas fontes (e nomes) das Fontes do tempo real

API_PV = ("pv", "semp", "alveslima", "2capi")
SEVERIDADE = {"critico": 0, "atencao": 1, "info": 2}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def linha(fonte: str, r: dict, ctx: dict) -> dict:
    """O diagnóstico de uma usina. `r` é a linha da tabela de strings (a da API PV traz `str_esp_cadastro` e, com a ponte,
    `nome_api`). `ctx`: nome_api {plant_id: nome que a API escreveu, quando a ponte trocou; reserva da linha},
    ponte_ids (PV_NOME_POR_ID), apelidos (PV_NOME_API_ALIAS), inv_nomes (PV_INV_NOMES), provisorios {plant_id: texto},
    oem (PV_OEM_PLANTS), sg_por_ordem {(fonte, id): True} (scadaGridco sem de-para de inversor)."""
    pid = r.get("plant_id")
    usina = r.get("usina") or str(pid)
    # As esperadas são as do CADASTRO: a linha da API PV traz `str_esp_cadastro` porque o `str_esp` dela já vem com os
    # descontos da leitura (a String Box à noite fica com 0: na 1ª prova, 20 usinas "sem esperadas" que tinham cadastro).
    tem_cad = "str_esp_cadastro" in r
    str_esp = _num(r.get("str_esp_cadastro") if tem_cad else r.get("str_esp"))
    inv_esp, inv_fonte = _num(r.get("inv_esp")), _num(r.get("qtd_inversores"))
    alertas = []
    # ── como a usina se liga ao cadastro ──
    if fonte in API_PV and pid in ctx.get("ponte_ids", {}):
        api = r.get("nome_api") or ctx.get("nome_api", {}).get(pid)
        liga = f"pelo id (ponte): a API escreve “{api}”" if api else "pelo id (ponte)"
    elif fonte in API_PV and any(_mesmo(usina, a) for a in ctx.get("apelidos", {}).values()):
        liga = "por apelido no código"
    else:
        liga = "pelo nome"
    if not str_esp:
        if not tem_cad and (r.get("sem_visao") or r.get("rampa") or r.get("sem_dados")):
            # sem o total do cadastro, o zero desta leitura não prova nada (inversor sem visão, rampa, sem dados)
            alertas.append(("info", "sem leitura das strings agora: as esperadas não dão para conferir por esta linha"))
        elif r.get("inv_padrao"):
            alertas.append(("atencao", "sem strings esperadas no cadastro: vigiada só pela régua por inversor (padrão 30 dias)"))
        else:
            alertas.append(("critico", "sem strings esperadas no cadastro: string morta não acusa"))
    if inv_fonte and inv_esp and inv_fonte != inv_esp:
        alertas.append(("atencao", f"{inv_fonte:g} inversor(es) na fonte, {inv_esp:g} no cadastro"))
    # ── de onde vem o nome de cada inversor ──
    if fonte in API_PV and pid in ctx.get("inv_nomes", {}):
        nomes = "de-para no código"
    elif fonte in API_PV and pid in ctx.get("oem", set()):
        nomes = "pela ordem do cadastro"
        alertas.append(("atencao", "nomes dos inversores pela ORDEM dos ids: pode trocar um inversor pelo outro"))
    elif fonte in ("greenyellow", "salenergia") and ctx.get("sg_por_ordem", {}).get((fonte, pid)):
        nomes = "pela ordem do cadastro"
        alertas.append(("atencao", "nomes dos inversores pela ORDEM (provisório, sem leitura para fechar por valor)"))
    else:
        nomes = "o nome que a fonte manda"
    prov = ctx.get("provisorios", {}).get(pid)
    if prov:
        alertas.append(("info", prov))
    alertas.sort(key=lambda a: SEVERIDADE[a[0]])
    return {"fonte": fonte, "plant_id": pid, "usina": usina, "liga": liga, "str_esp": str_esp, "inv_esp": inv_esp,
            "inv_fonte": inv_fonte, "nomes_inversor": nomes,
            "alertas": [{"nivel": n, "texto": t} for n, t in alertas],
            "pior": alertas[0][0] if alertas else "ok"}


def _mesmo(a, b) -> bool:
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def diagnostico(tabelas: dict, ctx: dict) -> dict:
    """{fontes: [...], precisa: [linhas com alerta crítico ou de atenção, das piores para as melhores], contagem}.
    `tabelas` = {fonte: [linhas da tabela de strings em cache]} — fonte sem tabela (não lida nesta máquina) fica de fora,
    e a tela diz isso."""
    fontes, precisa = [], []
    for fid, rotulo in ROTULOS.items():
        rows = tabelas.get(fid)
        if rows is None:
            fontes.append({"id": fid, "nome": rotulo, "lida": False, "usinas": []})
            continue
        us = sorted((linha(fid, r, ctx) for r in rows if r.get("plant_id") is not None),
                    key=lambda u: (SEVERIDADE.get(u["pior"], 3), str(u["usina"]).lower()))
        fontes.append({"id": fid, "nome": rotulo, "lida": True, "usinas": us})
        precisa += [u for u in us if u["pior"] in ("critico", "atencao")]
    precisa.sort(key=lambda u: (SEVERIDADE[u["pior"]], u["fonte"], str(u["usina"]).lower()))
    cont = {"usinas": sum(len(f["usinas"]) for f in fontes),
            "criticos": sum(1 for u in precisa if u["pior"] == "critico"),
            "atencao": sum(1 for u in precisa if u["pior"] == "atencao")}
    return {"fontes": fontes, "precisa": precisa, "contagem": cont}
