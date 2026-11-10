# -*- coding: utf-8 -*-
"""scadaGridco — o supervisório da Automação Grid Co. como fonte de strings (06/10/2026).

Levi: "OS para tempo real e histórico das UFVs da Green Yellow", com as usinas "separe green yellow e sal energia",
"igual às outras fontes" e histórico "só até 45 dias" (é o que a API guarda). Documento da Automação: "API do
scadaGridco — como puxar os dados". Só GET, cabeçalho `X-API-Key`, JSON; sem token ou com token errado ela responde
302 para o login.

Duas famílias de leitura (MQTT e Modbus), uma fonte por cliente:
- **GreenYellow** chega por gateway MQTT: `/api/mqtt/<usina>` (último pacote de cada inversor) e `/api/telemetria`
  (histórico, ~1 registro por minuto por inversor). Ponto de string no gateway antigo `string_current_NN`, no novo
  `string_N_current`.
- **Sal Energia** é Modbus: `/api/inversores/<usina>` (leitura atual) e `/api/dados/string` (histórico de 5 min, uma
  linha por string). Em 06/10/2026 as cinco estavam com `read_error: TimeoutError` desde pelo menos 17/09 — o
  supervisório não lê os inversores, e a usina aparece sem comunicação, que é o que ela está para ele. O nome dos campos
  Modbus foi conferido na Boa Esperança do Sul, Modbus e lendo (`string_NN_i`, `active_power_w`, `daily_energy_kwh`).
- **Apolo** (29/10/2026) chega pelo mesmo gateway MQTT da GreenYellow: a Rio do Peixe I e II, na lista abaixo com o
  de-para (o supervisório manda um inversor a mais, cópia de outro); usina nova do cliente entra pela descoberta.
- **Trackers** (03/11/2026): `/api/trackers/<usina>` (o agora) e `/api/trackers/<usina>/historico` (a curva do dia), por
  usina — ver a seção "Trackers" abaixo.

Regras da Automação que este módulo segura: uma chamada por vez (o mesmo servidor opera as usinas, lendo relés e
inversores em tempo real — `_LOCK`), busca incremental (`apos_ts`), `communication_fault` 192 = leitura boa, nulo não é
zero e lacuna é sem comunicação. `data_hora` é a hora local das usinas (UTC−3, o Nordeste não tem horário de verão) e
`ts` é epoch. O token mora no tokens.txt (`SCADAGRIDCO_URL`, `SCADAGRIDCO_TOKEN`), nunca no código.

Puro onde dá (leitura dos pacotes, curva, de-para): a rede entra só por `get()`.
"""
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

TZ = timezone(timedelta(hours=-3))
COM_OK = 192                     # communication_fault da leitura boa (28 = ruim)
TIMEOUT_S = 60
LIMITE = 5000                    # registros por página (a doc pede 5.000 a 20.000)

# ── Usinas e de-para dos inversores ─────────────────────────────────────────────────────────────────────────────────
# id = a chave da usina no scadaGridco; usina = o nome do cadastro (aba Equipamentos/Info Geral do BD_Performance).
# `inversores` = {equipamento do scadaGridco: inversor do cadastro}. Na GreenYellow ele foi fechado POR VALOR, a energia do
# dia de cada equipamento contra o kWh diário da aba de 27 a 30/09/2026: na Irecê 2 a ordem NÃO é a do cadastro (o 4 é
# o Inversor 1.8, o 7 é o 1.4); o 7 bateu em 3 dos 4 dias ao centésimo, e no 29/09 o contador dele amanheceu com o
# valor da véspera. A Demerval Lobão tem só a UG 01 no scadaGridco (12 de 20 inversores, 3.246 de 5.410 kWp): o 1 a 12
# batem com o Inversor 1.1 a 1.12, e a UG 02 fica fora da conta da usina (como a União na 2C).
# Sal Energia: `None` = pela ORDEM do cadastro (slave 1 = o 1º inversor). PROVISÓRIO: sem uma leitura sequer não há
# como fechar por valor — confirmar quando o supervisório voltar a ler os inversores.
FONTES = {
    "greenyellow": {
        "rotulo": "GreenYellow",
        "via": "mqtt",
        "usinas": [
            {"id": "dermeval_lobao", "usina": "Demerval Lobao",
             "inversores": {str(i): f"Inversor 1.{i}" for i in range(1, 13)}},
            # Irecê 2: ORDEM NATURAL desde 01/10/2026 (10/10 por valor em 01, 05 e 09/10, contra o que a equipe digitou).
            # O de-para de 27-30/09 (4 = 1.8, 7 = 1.4...) só batia em setembro: em outubro a aba segue a ordem natural, e
            # é ela que o coletor da GreenYellow grava desde 13/10 (coleta API PV/src/coletar_greenyellow.py).
            {"id": "irece_2", "usina": "Irece 2",
             "inversores": {str(i): f"Inversor 1.{i}" for i in range(1, 11)}},
            # Macaíba (10/11/2026, Levi: "Em greenyellow também temos macaíba"). A descoberta não a achava: o supervisório
            # a chama "Macaíba" e o cadastro "Macaiba 1". 15 equipamentos inversor ("1" a "15", 24 entradas string_N_current,
            # 14 com corrente cada) contra 15 no cadastro (1.1 a 1.8 na UG 01, 2.1 a 2.7 na UG 02, 14 strings todos).
            # PROVISÓRIO, pela ORDEM: todos com as mesmas 14 strings, o padrão não separa; fechar pelo valor (a energia do
            # dia de cada equipamento contra o kWh da aba) quando houver dia em comum.
            {"id": "macaiba", "usina": "Macaiba 1",
             "inversores": {**{str(i): f"Inversor 1.{i}" for i in range(1, 9)},
                            **{str(e): f"Inversor 2.{n}" for n, e in enumerate(range(9, 16), start=1)}},
             "provisorio": "Macaíba: de-para pela ordem (1 a 8 = UG 01, 9 a 15 = UG 02); todos com 14 strings, o padrão "
                           "não separa; fechar pelo valor"},
        ],
    },
    "salenergia": {
        "rotulo": "Sal Energia",
        "via": "modbus",
        "usinas": [
            {"id": "salvales", "usina": "Aquiraz 1 (Salvales)", "inversores": None},
            {"id": "carosa", "usina": "Aquiraz 2 (Carosa)", "inversores": None},
            {"id": "sunpower", "usina": "Cascavel (Sunpower)", "inversores": None},
            {"id": "hortina", "usina": "Quixadá 1 (Hortina)", "inversores": None},
            {"id": "vitesse", "usina": "Quixadá 2 (Vitesse)", "inversores": None},
        ],
    },
    # Apolo (29/10/2026, Levi: "As API que tem as mesmas UFVs da GreenYellow também soltou Rio do Peixe 1 e 2 que é da
    # Apolo, traga para o tempo real"). Gateway MQTT como a GreenYellow; usina nova do cliente "Apolo" na Info Geral entra
    # pela descoberta. A Rio do Peixe I e II (rio_do_peixe_1_2) manda 21 equipamentos inversor ("1" a "21", 28 entradas
    # string_N_current cada), 3 relés e (desde 03/11/2026) 96 trackers, sem estação; o cadastro tem 20 inversores (1.1 a 1.10 na UG 01,
    # 2.1 a 2.10 na UG 02, 20/18/20 strings) e ela fica AQUI, com o de-para, porque a ordem do cadastro erra: o
    # equipamento 15 é CÓPIA do 14 (em 28/10/2026, 315 dos 316 minutos com sol iguais em potência e em cada string; o 14
    # contra o 16, 0), e pela ordem o 15 virava o 2.5, o 18 (18 strings) o 2.8 (20 esperadas, −2 falso) e o 21 ficava sem
    # inversor. PROVISÓRIO, pelo PADRÃO DAS STRINGS (o nº de entradas com corrente às 13h de 28/10 bate 20/18/20 nas duas
    # UGs com o 15 fora): o histórico do supervisório começa em 28/10 11:52 e o BD vai até 21/10, sem dia em comum para
    # fechar pelo valor. Dentro de cada grupo de esperadas iguais vale a ordem dos números. O 15 fica de fora.
    "apolo": {
        "rotulo": "Apolo",
        "via": "mqtt",
        "usinas": [
            {"id": "rio_do_peixe_1_2", "usina": "Rio do Peixe I e II",
             "inversores": {**{str(i): f"Inversor 1.{i}" for i in range(1, 11)},
                            **{str(e): f"Inversor 2.{n}" for n, e in enumerate((11, 12, 13, 14, 16, 17, 18, 19, 20, 21),
                                                                               start=1)}},
             "provisorio": "Rio do Peixe I e II: de-para pelo padrão das strings (20/18/20 por UG), sem dia em comum com "
                           "o BD para fechar pelo valor; o equipamento 15 do supervisório é cópia do 14 e fica de fora"},
            # Gravatá II e Iramaia II (10/11/2026, Levi: "Usinas da Apolo no tempo real, na nossa API já temos Iramaia e
            # Gravata, por gentileza inserir"). A descoberta não as achava pelo nome: o supervisório escreve "Gravata II
            # Apolo" e "Iramaia II apolo". 10 equipamentos inversor cada ("1" a "10", 28 entradas string_N_current), sem
            # estação. Equipamento N = Inversor 1.N: é a numeração do SmartLogger (InverterNN = 1.N, conferida contra o BD
            # em 21 de 21 dias de outubro) e o padrão das strings com corrente bate com o cadastro (Gravatá 20/20/18/18/18/
            # 18/20/20/20/20; Iramaia 18 em todos).
            {"id": "gravata_ii_apolo", "usina": "Gravatá II",
             "inversores": {str(i): f"Inversor 1.{i}" for i in range(1, 11)}},
            {"id": "iramaia_ii_apolo", "usina": "Iramaia II",
             "inversores": {str(i): f"Inversor 1.{i}" for i in range(1, 11)}},
        ],
    },
}


# Usinas DESCOBERTAS na API (11/10/2026, Levi: "Na API que está puxando as UFVs da GreenYellow não está aparecendo todas
# as UFVs"): a lista acima era fixa, e o supervisório já tinha a Castelo do Piauí (16 inversores) e a "Cedro 1 e 2" (20)
# lendo. O app classifica cada usina de `/api/usinas` pelo CLIENTE do cadastro (Info Geral) e pendura aqui as que não estão
# acima ({fonte: [cfg]}); `ATUALIZAR` (o app) relê a lista do disco quando o worker a troca. Numa usina do cadastro que o
# supervisório junta com outra (a Cedro 1 e a Cedro 2 são a "cedro"), a chave da usina é própria ("cedro_1") e o id do
# supervisório vai em "scada".
EXTRAS = {}
ATUALIZAR = None


def usinas(fonte):
    """As usinas da fonte: a lista fixa acima e as descobertas na API."""
    if ATUALIZAR:
        try:
            ATUALIZAR()
        except Exception:                                    # noqa: BLE001 — sem a lista nova, vale a que já está
            pass
    return list(FONTES[fonte]["usinas"]) + list(EXTRAS.get(fonte) or [])


def usina_cfg(fonte, pid):
    return next((u for u in usinas(fonte) if u["id"] == str(pid)), None)


def scada_id(fonte, pid):
    """O id da usina NO SUPERVISÓRIO (o da URL): o da chave, menos na usina do cadastro que ele junta com outra."""
    cfg = usina_cfg(fonte, pid) or {}
    return cfg.get("scada") or str(pid)


def via(fonte, pid):
    cfg = usina_cfg(fonte, pid) or {}
    return cfg.get("via") or FONTES[fonte]["via"]


_RX_EQUIP = re.compile(r"^\D*?(\d+)(?:\D+(\d+))?\s*$")


def grupo_e_numero(equip):
    """'inversor-03' → (1, 3); 'inversor-03-12' → (2, 3): o supervisório põe o 2º grupo de inversores (a 2ª UG, ou a
    2ª usina que ele junta) com o sufixo do endereço ('-12'). Número puro ('4') → (1, 4). Sem número → None."""
    m = _RX_EQUIP.match(str(equip or ""))
    if not m:
        return None
    return (2 if m.group(2) else 1), int(m.group(1))


def mapa_pelo_nome(equips, cadastro, grupo=None, alvo_grupo=None):
    """{equipamento: inversor do cadastro} PELO NOME do equipamento (provisório: sem dia em comum com o BD para fechar
    pelo valor). `grupo` = só os equipamentos desse grupo (a Cedro 1 é o 1º, a Cedro 2 o 2º); `alvo_grupo` = o grupo do
    nome no cadastro (as duas Cedro chamam os inversores de "Inversor 1.x"). Equipamento sem par no cadastro fica de
    fora; se sobrar algum, devolve {} (vale a ordem do cadastro, com o aviso de sempre)."""
    nomes = {(ordem_par(n)): n for n in cadastro}
    out = {}
    for e in equips:
        gn = grupo_e_numero(e)
        if gn is None or (grupo and gn[0] != grupo):
            continue
        alvo = nomes.get(((alvo_grupo or gn[0]), gn[1]))
        if not alvo:
            return {}
        out[str(e)] = alvo
    return out if len(set(out.values())) == len(out) else {}


def descobrir(getter=None):
    """[{id, nome, via, inv_total, equipamentos}] de todas as usinas do supervisório: `/api/usinas` (todas, com o total
    de inversores) e `/api/mqtt` (as do gateway MQTT, com o nome e os equipamentos). 2 chamadas."""
    getter = getter or get
    todas = getter("/api/usinas") or {}
    mq = {u.get("usina"): u for u in ((getter("/api/mqtt") or {}).get("usinas") or []) if u.get("usina")}
    out = []
    for uid, st in sorted(todas.items()):
        u = mq.get(uid) or {}
        eqs = [str(e.get("equipamento") or e.get("indice")) for e in (u.get("equipamentos") or []) if e.get("tipo") == "inverter"]
        out.append({"id": uid, "nome": u.get("nome") or uid.replace("_", " "), "via": "mqtt" if uid in mq else "modbus",
                    "inv_total": (st or {}).get("inv_total"), "equipamentos": eqs})
    return out


def ordem_par(nome):
    """"Inversor 1.10" → (1, 10), depois do 1.9; "INV 03" → (3, 0)."""
    m = re.search(r"(\d+)\.(\d+)", str(nome or ""))
    if m:
        return (int(m.group(1)), int(m.group(2)))
    n = re.search(r"(\d+)", str(nome or ""))
    return (int(n.group(1)), 0) if n else (9999, 0)


# De-para decidido na tela (De-para de equipamentos da plataforma, 11/10/2026): o app pendura aqui quem devolve
# {nº do equipamento: inversor} da usina; o decidido vence o mapa abaixo e a ordem do cadastro (vazio = vale o daqui).
SOBREPOR = None


def nome_inversor(cfg, equip, cadastro_ordem=()):
    """O inversor do cadastro para o equipamento do scadaGridco. Sem de-para fechado (Sal Energia), o N-ésimo do
    cadastro em ordem natural; sem cadastro, o rótulo da fonte. O decidido na tela (SOBREPOR) vem antes de tudo."""
    sob = SOBREPOR(cfg) if SOBREPOR else None
    if sob and sob.get(str(equip)):
        return sob[str(equip)]
    mapa = cfg.get("inversores")
    if mapa:
        return mapa.get(str(equip))
    if cfg.get("scada"):
        return None                                          # usina que o supervisório junta: só o de-para dela é dela
    try:
        n = int(re.search(r"(\d+)", str(equip)).group(1))
    except (AttributeError, ValueError):
        return None
    ordem = sorted(cadastro_ordem, key=ordem_par)
    return ordem[n - 1] if 0 < n <= len(ordem) else None


# ── Cliente ─────────────────────────────────────────────────────────────────────────────────────────────────────────
class SemAcesso(RuntimeError):
    """Sem token, token recusado (302 para o login) ou endereço não configurado."""


_LOCK = threading.Lock()         # uma chamada por vez, a regra da Automação (o servidor também opera as usinas)
_SESSAO = requests.Session()


def configurado() -> bool:
    return bool(os.environ.get("SCADAGRIDCO_URL", "").strip() and os.environ.get("SCADAGRIDCO_TOKEN", "").strip())


def get(rota, params=None, timeout=TIMEOUT_S):
    """GET na API, em série com as outras chamadas do processo. 302 = token recusado (a API manda para o login)."""
    base = os.environ.get("SCADAGRIDCO_URL", "").strip().rstrip("/")
    token = os.environ.get("SCADAGRIDCO_TOKEN", "").strip()
    if not base or not token:
        raise SemAcesso("scadaGridco sem SCADAGRIDCO_URL/SCADAGRIDCO_TOKEN no tokens.txt")
    with _LOCK:
        r = _SESSAO.get(base + rota, headers={"X-API-Key": token}, params=params or {}, timeout=timeout,
                        allow_redirects=False)
    if r.status_code in (301, 302, 303, 401, 403):
        raise SemAcesso(f"scadaGridco recusou o token (HTTP {r.status_code})")
    r.raise_for_status()
    return r.json()


# ── Leitura atual ───────────────────────────────────────────────────────────────────────────────────────────────────
_RX_STRING = (re.compile(r"^string_current_(\d+)$"), re.compile(r"^string_(\d+)_current$"),
              re.compile(r"^string_(\d+)_i$"))


def strings_de(pontos) -> dict:
    """{nº da string: corrente (A) ou None} dos pontos de um inversor, nos três jeitos de escrever."""
    out = {}
    for k, v in (pontos or {}).items():
        for rx in _RX_STRING:
            m = rx.match(str(k))
            if m:
                out[int(m.group(1))] = float(v) if isinstance(v, (int, float)) else None
                break
    return out


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def leitura_mqtt(eq) -> dict:
    """Um equipamento de `/api/mqtt/<usina>` → leitura normalizada. Leitura ruim (communication_fault ≠ 192, `stale`
    ou `falha_comunicacao`) não traz valor: lacuna é sem comunicação, não zero."""
    m = eq.get("measurements") or {}
    ok = eq.get("communication_fault") == COM_OK and not eq.get("stale") and not eq.get("falha_comunicacao")
    eday = _num(m.get("total_daily_energy"))
    if eday is None:
        eday = _num(m.get("daily_active_energy"))
    return {"equip": str(eq.get("equipamento") or eq.get("indice")), "ts": _num(eq.get("ts")), "ok": ok,
            "pot_kw": _num(m.get("active_power")) if ok else None,
            "eday": eday if ok else None,
            # a Rio do Peixe (Apolo, 29/10/2026) escreve a temperatura do inversor como `temperature_internal`
            "temp": _num(m.get("temperature_current", m.get("temperature_internal"))) if ok else None,
            "serial": m.get("serial_number"),
            "strings": strings_de(m) if ok else {}}


def leitura_modbus(unit) -> dict:
    """Um inversor de `/api/inversores/<usina>` → leitura normalizada (potência em W na fonte, kW aqui)."""
    m = unit.get("measurements") or {}
    ok = not unit.get("read_error") and not unit.get("stale") and bool(m)
    pw = _num(m.get("active_power_w"))
    ts = _num(unit.get("updated_at"))
    return {"equip": str(unit.get("slave_id")), "ts": ts if ts else None, "ok": ok,
            "pot_kw": pw / 1000.0 if ok and pw is not None else None,
            "eday": _num(m.get("daily_energy_kwh")) if ok else None,
            "temp": _num(m.get("internal_temperature_c")) if ok else None,
            "serial": m.get("serial_number"),
            "strings": strings_de(m) if ok else {}}


def leituras(fonte, pid) -> list:
    """A leitura atual de todos os inversores da usina (1 chamada)."""
    sid = scada_id(fonte, pid)
    if via(fonte, pid) == "mqtt":
        d = get(f"/api/mqtt/{sid}")
        return [leitura_mqtt(e) for e in (d.get("equipamentos") or []) if e.get("tipo") == "inverter"]
    d = get(f"/api/inversores/{sid}")
    return [leitura_modbus(u) for u in (d.get("units") or [])]


def ts_local(ts) -> str:
    """epoch → 'AAAA-MM-DD HH:MM:SS' na hora das usinas (a da `ultima_leitura` das outras fontes)."""
    return datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d %H:%M:%S") if ts else None


def hoje() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


# ── Trackers (03/11/2026) ───────────────────────────────────────────────────────────────────────────────────────────
# Levi, 03/11/2026, com a doc nova da Automação para os rastreadores: "já adapta para a plataforma". Os rastreadores
# chegam por MQTT, um equipamento por tracker (tipo `tracker`; o supervisório também aceita `tracker_ncu`, `tcu` e
# `rsu`), e a API dá duas leituras prontas, por usina:
# - `/api/trackers/<usina>`: o AGORA de cada um (posicao_atual, posicao_alvo, sem_comunicacao, stale, alarmes, ts). Usina
#   sem tracker responde `total` 0 (Demerval Lobão, Irecê 2, as cinco da Sal Energia): 0,01 a 0,2 s.
# - `/api/trackers/<usina>/historico?dia=&passo=`: o dia reamostrado, `instantes` (epoch), `alvo` (UM vetor da usina) e
#   `posicao` de cada tracker, nulo onde não houve leitura. Uma chamada por usina e dia (medido em 03/11/2026, passo 15:
#   Cedro 68 trackers 2,6 a 17 s, Ipixuna do Pará 122 em 11 s, Rio do Peixe 96 em 14 s, Castelo do Piauí 128 em 26 s; o
#   passo 5 custa o mesmo: 20, 17 e 26 s).
# PASSO DE 5 MIN, e não os 15 da curva da SunOp (TRK_CURVA_PERIODO do app.py): medido em 03/11/2026 às 09:50, a mesma régua
# sobre o `/historico` de passo 1, 5 e 15 deu os MESMOS parados com 1 e 5 nas três usinas (Castelo 84, Cedro 0, Rio do
# Peixe 1) e 96 na Castelo com 15 — o balde de 15 min guarda só a última leitura (não a média, como a SunOp), e 12
# trackers que mexem pouco viravam "zero o dia todo" (o sensor morto da régua). O histórico de hoje é pedido de novo a
# cada 15 min (`HistoricoTrackers.TTL_HOJE`); o que chega no meio vem pelo agora. O valor de cada instante é a ÚLTIMA
# leitura do balde [instante, instante + passo): na Araputanga de 02/11/2026 (passo 15), contra a curva da API PV dos
# mesmos 59 trackers (mesma ordem), a diferença média por tracker foi 3,56° com o rótulo da API e 0,57° com o ponto no
# FIM do balde — é onde ele fica aqui (`curvas_historico`).
# A NCU agregada da Rio do Peixe (29/10/2026: 1 `tracker_ncu` com o ângulo da central) não existe mais: o supervisório
# manda os 96 trackers do campo, e o equipamento "1" agora é o tracker 1.
TIPOS_TRACKER = ("tracker", "tracker_ncu", "tcu", "rsu")
TRK_PASSO_MIN = 5


def _dt_local(ts):
    """epoch → datetime local SEM fuso (o formato das curvas de tracker das outras fontes)."""
    return datetime.fromtimestamp(ts, TZ).replace(tzinfo=None)


def trackers_agora(fonte, pid, getter=None) -> list:
    """O agora de cada tracker da usina (1 chamada): [{equip, atual, alvo, sem_comunicacao, alarmes, ts}]. O
    `sem_comunicacao` junta o da API e o `stale` (leitura velha): os dois são "não sei onde ele está agora"."""
    getter = getter or get
    d = getter(f"/api/trackers/{scada_id(fonte, pid)}") or {}
    out = []
    for t in d.get("trackers") or []:
        out.append({"equip": str(t.get("equipamento") or t.get("indice")),
                    "atual": _num(t.get("posicao_atual")), "alvo": _num(t.get("posicao_alvo")),
                    "sem_comunicacao": bool(t.get("sem_comunicacao") or t.get("stale")),
                    "alarmes": [str(a) for a in (t.get("alarmes") or [])], "ts": _num(t.get("ts"))})
    return out


def curvas_historico(d, passo=TRK_PASSO_MIN, ate=None) -> dict:
    """A resposta do `/historico` → {equip: {"atual": [(datetime, °)], "alvo": [(datetime, °)]}}. O ponto vai no FIM do
    balde (instante + passo), que é quando a leitura foi feita; o balde em curso não passa de `ate` (epoch, o agora), e o
    último do dia fica em 23:59 do MESMO dia (no 00:00 do dia seguinte, o gráfico de vários dias, que classifica o último
    dia, veria um dia novo de um ponto só). Nulo fica fora (nulo não é zero). O alvo é o da usina, o mesmo em todos."""
    inst = list((d or {}).get("instantes") or [])
    passo_s = 60 * int((d or {}).get("passo_min") or passo)

    def quando(ts):
        ini, fim = _dt_local(ts), _dt_local(min(ts + passo_s, ate) if ate is not None else ts + passo_s)
        return fim if fim.date() == ini.date() else ini.replace(hour=23, minute=59, second=0, microsecond=0)
    tempos = [quando(ts) if isinstance(ts, (int, float)) else None for ts in inst]
    alvo = [(t, _num(v)) for t, v in zip(tempos, (d or {}).get("alvo") or []) if t is not None and _num(v) is not None]
    out = {}
    for x in (d or {}).get("trackers") or []:
        eq = str(x.get("equipamento") or x.get("indice"))
        atual = [(t, _num(v)) for t, v in zip(tempos, x.get("posicao") or []) if t is not None and _num(v) is not None]
        out[eq] = {"atual": atual, "alvo": alvo}
    return out


def trackers_historico(fonte, pid, dia, getter=None, ate=None) -> dict:
    """As curvas do dia (≤ 45 dias atrás) de todos os trackers da usina: 1 chamada."""
    getter = getter or get
    d = getter(f"/api/trackers/{scada_id(fonte, pid)}/historico", {"dia": dia, "passo": TRK_PASSO_MIN})
    return curvas_historico(d, ate=ate)


class HistoricoTrackers:
    """O `/historico` de cada usina e dia guardado: o de hoje por 15 min (a Castelo leva 26 s na fila de uma chamada por
    vez do supervisório; entre um e outro, o ponto novo vem pelo agora), o de dia passado por 6 h. Pela chave do
    SUPERVISÓRIO: a Cedro 1 e a Cedro 2 são a mesma usina para ele, uma chamada só."""
    TTL_HOJE = 15 * 60
    TTL_PASSADO = 6 * 3600

    def __init__(self):
        self._d = {}
        self._lock = threading.Lock()

    def curvas(self, fonte, pid, dia, getter=None, agora=None):
        agora = time.time() if agora is None else agora
        k = (fonte, scada_id(fonte, pid), dia)
        e_hoje = dia >= hoje()
        with self._lock:
            ent = self._d.get(k)
        if ent and agora - ent["ts"] < (self.TTL_HOJE if e_hoje else self.TTL_PASSADO):
            return ent["curvas"]
        cur = trackers_historico(fonte, pid, dia, getter=getter, ate=agora if e_hoje else None)
        with self._lock:
            self._d[k] = {"ts": agora, "curvas": cur}
            for kk in [kk for kk, v in self._d.items() if kk[2] != hoje() and agora - v["ts"] > self.TTL_PASSADO]:
                self._d.pop(kk, None)
        return cur


def junta_agora(curvas, agora_lst) -> dict:
    """As curvas do histórico + o ponto do agora de cada tracker que lê (o balde em curso do histórico só chega no passo
    seguinte). O ponto entra no instante da leitura, e só se for depois do último do histórico; o tracker sem
    comunicação não ganha ponto (o ângulo dele é velho). Tracker que o agora lista e o histórico não entra sem curva (a
    análise o marca sem comunicação). Não muda `curvas`."""
    out = {eq: {"atual": list(c.get("atual") or []), "alvo": list(c.get("alvo") or [])} for eq, c in (curvas or {}).items()}
    for t in agora_lst or []:
        c = out.setdefault(t["equip"], {"atual": [], "alvo": []})
        if t.get("sem_comunicacao") or t.get("ts") is None or t.get("atual") is None:
            continue
        quando = _dt_local(t["ts"]).replace(second=0, microsecond=0)
        if not c["atual"] or quando > c["atual"][-1][0]:
            c["atual"].append((quando, t["atual"]))
            if t.get("alvo") is not None and (not c["alvo"] or quando > c["alvo"][-1][0]):
                c["alvo"] = c["alvo"] + [(quando, t["alvo"])]
    return out


# ── Curva do dia ────────────────────────────────────────────────────────────────────────────────────────────────────
def curva_mqtt(registros) -> dict:
    """Registros de `/api/telemetria` de UM inversor → {"strings": {n: [(HH:MM, A)]}, "pot": [(HH:MM, kW)],
    "ultimo_ts": ts}. Só leitura boa (192); ponto nulo fica fora (nulo não é zero)."""
    strings, pot, ultimo = {}, [], None
    for x in registros or []:
        ts = _num(x.get("ts"))
        if ts is not None:
            ultimo = ts if ultimo is None else max(ultimo, ts)
        if x.get("communication_fault") != COM_OK:
            continue
        hhmm = str(x.get("data_hora") or "")[11:16]
        if not hhmm:
            continue
        p = x.get("pontos") or {}
        for n, v in strings_de(p).items():
            if v is not None:
                strings.setdefault(n, []).append((hhmm, v))
        pk = _num(p.get("active_power"))
        if pk is not None:
            pot.append((hhmm, pk))
    return {"strings": strings, "pot": pot, "ultimo_ts": ultimo}


def curva_modbus(registros) -> dict:
    """Registros de `/api/dados/string` de UM inversor (uma linha por string a cada 5 min) → o formato da curva_mqtt."""
    strings, ultimo = {}, None
    for x in registros or []:
        ts = _num(x.get("ts"))
        if ts is not None:
            ultimo = ts if ultimo is None else max(ultimo, ts)
        v = _num(x.get("current_a"))
        hhmm = str(x.get("data_hora") or "")[11:16]
        if v is None or not hhmm or x.get("string_num") is None:
            continue
        strings.setdefault(int(x["string_num"]), []).append((hhmm, v))
    return {"strings": strings, "pot": [], "ultimo_ts": ultimo}


def junta(antes, novo) -> dict:
    """Curva guardada + o pedaço incremental (apos_ts): só acrescenta, o pedaço é todo depois do último ponto."""
    if not antes:
        return novo
    s = {n: list(v) for n, v in (antes.get("strings") or {}).items()}
    for n, v in (novo.get("strings") or {}).items():
        s.setdefault(n, []).extend(v)
    ult = [t for t in (antes.get("ultimo_ts"), novo.get("ultimo_ts")) if t is not None]
    return {"strings": s, "pot": list(antes.get("pot") or []) + list(novo.get("pot") or []),
            "ultimo_ts": max(ult) if ult else None}


def _paginas(rota, params, getter):
    regs, apos = [], params.get("apos_ts")
    base = {k: v for k, v in params.items() if k != "apos_ts"}
    for _ in range(50):                                      # teto: 50 × 5.000 = um mês de um inversor, nunca chega
        p = dict(base, limit=LIMITE)
        if apos is not None:
            p["apos_ts"] = apos
        d = getter(rota, p)
        regs.extend(d.get("registros") or [])
        apos = d.get("proximo_apos_ts")
        if not apos:
            break
    return regs


def curva_inversor(fonte, pid, equip, dia, apos_ts=None, getter=None) -> dict:
    """A curva de UM inversor num dia (≤ 45 dias atrás: é o que a API guarda). Um inversor por pedido: a usina inteira
    de uma vez são 19 MB e 22 s (Irecê 2, 06/10/2026); um inversor, 2,5 MB e 0,5 s."""
    getter = getter or get
    sid = scada_id(fonte, pid)
    if via(fonte, pid) == "mqtt":
        # pelo NOME do equipamento: o `indice` só filtra quem tem nome numérico ("1"); na Cedro, "inversor-01" com
        # indice=1 voltava vazio (11/10/2026). Na Demerval e na Irecê os dois dão o mesmo (1.433 e 1.430 registros)
        regs = _paginas("/api/telemetria", {"usina": sid, "desde": dia, "ate": dia, "tipo": "inverter",
                                            "equipamento": str(equip), "apos_ts": apos_ts}, getter)
        return curva_mqtt([r for r in regs if str(r.get("equipamento")) == str(equip)])
    regs = _paginas(f"/api/dados/string", {"usina": sid, "desde": dia, "ate": dia, "slave_id": int(equip),
                                           "apos_ts": apos_ts}, getter)
    return curva_modbus([r for r in regs if str(r.get("slave_id")) == str(equip)])


class CurvasDoDia:
    """A curva de hoje de cada inversor, buscada aos pedaços (`apos_ts`): a 1ª busca traz o dia até agora, as
    seguintes só o que chegou depois. Dia passado é fixo: guardado inteiro por `TTL_PASSADO`."""
    TTL_HOJE = 300
    TTL_PASSADO = 6 * 3600

    def __init__(self):
        self._d = {}                                         # (fonte, pid, equip, dia) → {"ts", "curva"}
        self._lock = threading.Lock()

    def curva(self, fonte, pid, equip, dia, getter=None, agora=None):
        agora = time.time() if agora is None else agora
        k = (fonte, str(pid), str(equip), dia)
        with self._lock:
            ent = self._d.get(k)
        e_hoje = dia >= hoje()
        if ent and agora - ent["ts"] < (self.TTL_HOJE if e_hoje else self.TTL_PASSADO):
            return ent["curva"]
        apos = ent["curva"].get("ultimo_ts") if (ent and e_hoje) else None
        novo = curva_inversor(fonte, pid, equip, dia, apos_ts=apos, getter=getter)
        cur = junta(ent["curva"], novo) if apos is not None else novo
        with self._lock:
            self._d[k] = {"ts": agora, "curva": cur}
            for kk in [kk for kk, v in self._d.items() if kk[3] != hoje() and agora - v["ts"] > self.TTL_PASSADO]:
                self._d.pop(kk, None)
        return cur
