# -*- coding: utf-8 -*-
"""Recoleta pela API PV, conta principal (as usinas do BD_Thopen), no formato do contrato da Coletas (comum.py).

A busca é a do recoleta_apipv (a mesma régua do coletor da noite: plant_devices, custom_query energy e meteo, ETM pelo
trapézio, chuva pelo acumulado chuTotal) e o teto do dia é UM só com o Conversor 1.0.14. Aqui só se traduz o cru da API
pela aba Equipamentos: (planta do supervisório, equipamento) -> (aba do BD, coluna). ETM e chuva da aba com várias
plantas (Ceilândia 2 são 4): a 1ª planta que mediu, na ordem dos ids.
"""
import types

import recoleta_apipv as rc

FONTE = "apipv"
PAGA = True
MAX_PLANTAS = rc.MAX_PLANTAS
TETO = rc.TETO_DIA


def contexto(app):
    return types.SimpleNamespace(mapa=app._recoleta_mapa(), plantas_conta=app._recoleta_plantas, post=app._recoleta_post,
                                 cota_permite=app._pv_cota_permite, disjuntor=app._pv_disj_aberto, _pc=None)


def _pc(ctx):
    if ctx._pc is None:
        ctx._pc = ctx.plantas_conta()            # {id: (nome cru da API, nome do cadastro)}; a lista tem cache de 5 min
    return ctx._pc


def plantas(ctx):
    from recoleta_fontes import comum
    out = []
    for pid, (nome, cad) in sorted(_pc(ctx).items()):
        u = ctx.mapa.usina_de(nome) or ctx.mapa.usina_de(cad)
        for aba in (comum.abas_de(u, ctx.mapa) if u else ()):   # fora da aba Equipamentos: a coleta também não grava
            out.append({"id": str(pid), "usina": aba, "destino": "BD_Thopen", "planta": nome})
    return out


def custo(ids, dias, geracao, etm, chuva):
    meteo = 1 if (etm or chuva) else 0
    g = 1 if geracao else 0
    return len(ids) * (g + len(dias) * (g + meteo))


def permite(ctx, n):
    if ctx.disjuntor():
        return "a API PV está fora do ar agora (disjuntor aberto); tente em alguns minutos"
    if not ctx.cota_permite():
        return "a cota histórica da API PV está na reserva da coleta da noite; tente mais tarde"
    return None


def traduzir(cru, mapa, etm=True, chuva=True):
    """O cru do recoleta_apipv.buscar_cru -> {"geracao", "escalares", "avisos"} do contrato, com a aba do BD_Thopen pelo
    rotear do coletor (RENOMES e o split da Ouro Branco)."""
    from recoleta_fontes import comum
    geracao, avisos, sem = [], [], set()
    esc = {}                                     # (aba, dia, coluna) -> valor da 1ª planta que mediu
    for sid in sorted(cru, key=lambda x: int(x)):
        pl = cru[sid]
        nome = pl["nome"]
        u = mapa.usina_de(nome)
        abas = comum.abas_de(u, mapa) if u else []
        for dia, d in sorted(pl["dias"].items()):
            if d.get("erro"):
                avisos.append("%s %s: a API PV não respondeu (%s)" % (nome, dia, d["erro"]))
                continue
            for eq, kwh in sorted((d.get("ger") or {}).items()):
                alvo = mapa.inversor_de(nome, eq)
                alvo = comum.rotear(*alvo) if alvo else None
                if alvo is None:
                    sem.add("%s · %s" % (nome, eq))
                elif isinstance(kwh, (int, float)):
                    geracao.append({"usina": alvo[0], "inversor": alvo[1], "data": dia, "kwh": kwh})
            for aba in abas:
                for k, col in (("ipoa", "IPOA"), ("ghi", "GHI")) if etm else ():
                    if isinstance(d.get(k), (int, float)):
                        esc.setdefault((aba, dia, col), d[k])
                if chuva and isinstance(d.get("chuva"), (int, float)):
                    if (aba, dia, "Chuva") not in esc:
                        esc[(aba, dia, "Chuva")] = d["chuva"]
                        if d.get("chuva_conf") is False:
                            avisos.append("%s %s: chuva não confiável (sensor com viés); no BD vai em LARANJA"
                                          % (aba, dia))
                elif chuva and d.get("chuva_conf") is False:
                    avisos.append("%s %s: chuva com o acumulador fora de 0-150 mm; sem valor" % (aba, dia))
    if sem:
        avisos.append("%d equipamento(s) da API sem de-para na aba Equipamentos (a coleta também não os grava): %s"
                      % (len(sem), ", ".join(sorted(sem)[:12]) + (" ..." if len(sem) > 12 else "")))
    escalares = [{"usina": a, "data": d, "coluna": c, "valor": v} for (a, d, c), v in sorted(esc.items())]
    return {"geracao": geracao, "escalares": escalares, "avisos": avisos}


def buscar(ctx, ids, dias, geracao, etm, chuva):
    pc = {int(i): _pc(ctx)[int(i)][0] for i in ids}
    cru = rc.buscar_cru(ctx.post, [int(i) for i in ids], dias, geracao, etm, pc, ctx.cota_permite, chuva=chuva)
    return traduzir(cru, ctx.mapa, etm=etm, chuva=chuva)
