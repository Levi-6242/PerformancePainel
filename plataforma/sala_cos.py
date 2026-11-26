# -*- coding: utf-8 -*-
"""As strings pelo logger do COS no formato da API PV, na Sala de controle (26/11/2026).

Levi, na Santo Anastácio (a API PV fora, e a aba Strings no quadro cru do logger: os nomes e a numeração dele, sem
esperadas, trancadas nem OS): "está mostrando essa visualização aí completamente fora do padrão criado, sendo que os
dados que a gente puxa do COS tem dado histórico [...] Não é full tempo real"; e, à proposta de fazer do COS a reserva
por dentro da Sala, "sim".

Como: a leitura de agora do logger (a `/cos/inversores` do Nexus, que a tela já pede) vira REGISTROS no formato do
`day_inverter` da API PV, com o id do dispositivo dela, e passa pela MESMA montagem do drill (`_pv_plant_inversores_busca`,
`so_cache`): os nomes, as esperadas, as trancadas e a régua das strings saem iguais aos de sempre. Aqui, só o puro:
- `chave_inv`: "Inversor 1.3" → "1.3" (o mesmo `chaveInv` da tela; do lado do logger a tela manda a chave pronta, o
  `chaveCos`: "SKID 1 - INV03" → "1.3");
- `mapa_dispositivos`: a chave → o dispositivo da API PV (pelo nome de cadastro do dispositivo; chave repetida não liga);
- `registros`: os registros do `day_inverter` a partir do logger, com a corrente de cada entrada na string de MESMO
  número ("Ipv7" = a entrada 7), e o que ficou fora, com o motivo;
- `Conferencias`: o que a tela já viu ao comparar as duas leituras (`confereCos`), guardado por usina e inversor. A
  numeração das strings só é PROVADA com string parada igual nas duas (`zer`); com todas ligadas, só o inversor está
  provado. O inversor em que as duas DISCORDARAM (strings com e sem corrente diferentes) fica fora até nova prova: é o caso
  da Rodrigues 1 de 17/11/2026 (Roger Lélis: a entrada 14 com 0 A e a curva dela com corrente).
"""
import json
import os
import re
import threading

RX_CHAVE = re.compile(r"(\d+)\s*\.\s*(\d+)\s*$")
COMP_MIN = 4          # o mesmo piso do `confereCos` da tela: menos que isso não prova nem desprova nada


def chave_inv(nome) -> str | None:
    """'Inversor 1.3' → '1.3'; '1.10' → '1.10'; sem 'N.M' no fim → None."""
    m = RX_CHAVE.search(str(nome or ""))
    return f"{int(m.group(1))}.{int(m.group(2))}" if m else None


def mapa_dispositivos(dev_names: dict, nome_do) -> dict:
    """{chave: id do dispositivo}. `dev_names` = {id: nome na API PV}; `nome_do(nome na API PV)` = o nome do cadastro
    ("Inversor 1.3"). A chave de dois dispositivos não liga nenhum (ligação errada é pior que faltando)."""
    por = {}
    for dev, api in (dev_names or {}).items():
        ch = chave_inv(nome_do(api))
        if ch:
            por.setdefault(ch, []).append(dev)
    return {ch: ds[0] for ch, ds in por.items() if len(ds) == 1}


def estado(conf_usina: dict, ch) -> str:
    """'numeracao' (string parada igual nas duas leituras), 'inversor' (as duas com tudo ligado: só o inversor provado),
    'contradita' (a última comparação conclusiva discordou) ou '' (nunca comparado)."""
    e = (conf_usina or {}).get(str(ch)) or {}
    ok, zer, falhou = e.get("ok_em") or "", e.get("zer_em") or "", e.get("falhou_em") or ""
    if falhou and falhou > max(ok, zer):
        return "contradita"
    if zer and zer > falhou:          # a prova da numeração de ANTES de uma discordância não vale mais
        return "numeracao"
    if ok:
        return "inversor"
    return ""


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def registros(inversores: list, mapa: dict, conf_usina: dict, agora_txt: str) -> tuple:
    """(registros no formato do `day_inverter`, {id do dispositivo: chave}, [{nome, motivo}] do que ficou fora).
    `inversores` = os do logger como a tela manda: [{ch, nome, kw, ss: [[entrada, corrente A]]}]."""
    recs, usados, fora = [], {}, []
    for x in inversores or []:
        if not isinstance(x, dict):
            continue
        ch, nome = str(x.get("ch") or ""), str(x.get("nome") or x.get("ch") or "?")[:80]
        dev = mapa.get(ch) if ch else None
        if dev is None:
            fora.append({"nome": nome, "motivo": "nenhum inversor da API PV com este nome"})
            continue
        if estado(conf_usina, ch) == "contradita":
            fora.append({"nome": nome, "motivo": "na última comparação as strings com e sem corrente não bateram com as "
                                                 "da API PV (a numeração pode ser outra)"})
            continue
        cj = {}
        for par in x.get("ss") or []:
            if not isinstance(par, (list, tuple)) or len(par) != 2:
                continue
            try:
                n = int(par[0])
            except (TypeError, ValueError):
                continue
            a = _num(par[1])
            if n > 0 and a is not None:
                cj[f"Ipv{n}"] = round(a, 3)
        kw = _num(x.get("kw"))
        if kw is not None:
            cj["Pac"] = kw
        if not cj:
            fora.append({"nome": nome, "motivo": "o logger não trouxe leitura deste inversor agora"})
            continue
        recs.append({"idefinversor": dev, "tsleitura_new": agora_txt, "conteudojson": json.dumps(cj)})
        usados[dev] = ch
    return recs, usados, fora


class Conferencias:
    """{plant_id: {chave: {ok_em, zer_em, falhou_em, motivo}}} num JSON (o estado da Sala, fora do git)."""

    def __init__(self, caminho, substituir):
        self.caminho, self._substituir, self._trava = caminho, substituir, threading.Lock()

    def _tudo(self) -> dict:
        try:
            with open(self.caminho, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def ler(self, pid) -> dict:
        return self._tudo().get(str(pid)) or {}

    def gravar(self, pid, pares: list, agora_iso: str) -> int:
        """Guarda o que é CONCLUSIVO de cada par {ch, ok, zer, comp, motivo}: a prova (ok, e com `zer` a numeração) e a
        discordância (comp >= COMP_MIN e não ok). O resto (pouca string, de noite) não muda nada. Devolve quantos mudou."""
        n = 0
        with self._trava:
            d = self._tudo()
            us = d.setdefault(str(pid), {})
            for p in pares or []:
                if not isinstance(p, dict) or not str(p.get("ch") or "").strip():
                    continue
                ch = str(p.get("ch"))
                e = us.setdefault(ch, {})
                comp = int(p.get("comp") or 0)
                if p.get("ok") is True and comp >= COMP_MIN:
                    e["ok_em"] = agora_iso
                    if int(p.get("zer") or 0) > 0:
                        e["zer_em"] = agora_iso
                    n += 1
                elif p.get("ok") is False and comp >= COMP_MIN:
                    e["falhou_em"], e["motivo"] = agora_iso, str(p.get("motivo") or "")[:160]
                    n += 1
                if not e:
                    us.pop(ch, None)
            if n:
                os.makedirs(os.path.dirname(self.caminho) or ".", exist_ok=True)
                tmp = self.caminho + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False)
                self._substituir(tmp, self.caminho)
        return n
