# -*- coding: utf-8 -*-
"""Finalizar ticket de STRINGS pela plataforma (Levi, 23/09/2026).

O PEDIDO: "ao clicar no inversor ver as informações do ticket e conseguir finalizar ele pela plataforma (...) de forma
que o que mudar na plataforma também muda na base de dados de tickets". A base é a aba "Strings indisp" (sheet 128) do
workbook `tickets_performance`, a mesma que o OS Creator lê e grava.

QUEM GRAVA: a própria plataforma, pelo relay que já grava os tickets do OS Creator de mesa
(`tickets_relay.encaminhar`: token só nesta máquina, lista de abas liberadas, log de quem gravou). Até 23/09 o botão
passava pelo OS Creator web, que não está instalado no servidor: respondia 503 e nada gravava. O Levi escolheu a
gravação direta.

AS REGRAS SÃO AS DO SALVAR DO OS CREATOR WEB (repo oem, os_web/rotas_tickets.py::api_salvar), e têm de continuar
iguais, porque agora são dois gravadores do mesmo dado:
  1. relê a linha NA HORA, na API (não no espelho de 30 min), com o diário por cima;
  2. confere que a linha ainda é ESTE ticket (usina, inversor e início) e que o Fim está vazio. Linha apagada no Excel
     desce todas as de baixo, e gravar pela posição sem conferir fecharia o ticket do vizinho;
  3. manda a LINHA INTEIRA no PUT. A API troca a linha toda: mandar só o Fim apagaria as outras colunas, e ela responde
     200 do mesmo jeito (achado de 22/09 no próprio os_web);
  4. registra no DIÁRIO ("Edicoes do app v3", sheet 399) o RETRATO de todos os campos, não só o Fim. Dos registros de
     uma linha só o mais novo vale, e um registro sem a OS faria o vínculo com a OS sumir da tela, porque a OS não tem
     coluna na planilha e mora só no diário. É o diário que impede o sync do Excel (replace=true) de reabrir o ticket;
  5. relê de novo, e só dá o ticket por fechado com o Fim lido no banco.

O contrato do diário (colunas, nome da aba, impressão, "vazio no registro não apaga") é o do `tickets_diario.py` do oem.
`tests/test_tickets_str_fechar.py::test_contrato_do_diario_bate_com_o_oem` compara os dois onde o clone do oem existe.

Tudo aqui é puro: a rede entra por `ler_aba` e `gravar`, que a rota passa (bd_api e relay) e o teste troca.
"""
import datetime as _dt

SHEET_STRINGS = 128
SHEET_DIARIO = 399
NOME_DIARIO = "Edicoes do app v3"      # quando o OS Creator criar a v4, as duas pontas mudam juntas
ABA = "Strings"                         # o nome que o OS Creator usa para esta aba no diário
FIM = "Fim da ocorrência"
INICIO = "Início da ocorrência"
CAMPOS = ["Causa raiz", "Responsabilidade da Grid Co.?", "Início da ocorrência",
          "Início do chamado pela Grid Co.", "Fim da ocorrência", "Comentários gerais", "OS",
          "Ativo", "Status do ticket"]
COLUNAS = ["quando", "quem", "aba", "linha", "impressao"] + CAMPOS
DATAS = ("Início da ocorrência", "Início do chamado pela Grid Co.", "Fim da ocorrência")
CAUSA = "Causa raiz"
STATUS_T = "Status do ticket"                # só existe no diário: a planilha não tem coluna para ele
# O que o card deixa escolher (Levi, 23/09/2026: "Causas raiz possíveis de responder: Falha no equipamento, Furto,
# Garantia" e "OS Programada (quando já tem OS aberta para esse ativo de recomposição de string), Aguardando material,
# Aguardando garantia, Aguardando cliente"). "Aguardando Cliente" e "OS Programada" com a grafia da lista do OS Creator
# (os_web/tickets_web.py::STATUS), que compara o texto; "Aguardando Material" e "Aguardando Garantia" ainda não estão lá.
CAUSAS = ("Falha no equipamento", "Furto", "Garantia")
STATUS = ("OS Programada", "Aguardando Material", "Aguardando Garantia", "Aguardando Cliente")
# Ticket finalizado vai com o status final da lista do OS Creator, para não ficar "OS Programada" depois de fechado.
STATUS_FIM = "Concluído"
# Quantidade de strings afetadas, editável no card (Levi, 23/09/2026: "quero um contador de quantidade de strings
# afetadas para eu poder editar também" — o ticket da ADT100, linha 292, dizia 1 string com 2 sem corrente). O nome é o
# REAL da coluna na API, com o "no" que sobrou (conferido em 23/09). Não tem campo no diário do OS Creator: vai só para a
# planilha. Mínimo 1, como o card de quantidade do OS Creator ("zero não pode ir para a planilha"); acima de 999 é erro
# de digitação (a maior da aba em 23/09 era 209, o furto de cabos de Brodowski).
QTD = "Quantidade de strings no afetadas"
QTD_MAX = 999
_ROTULO = {QTD: "quantidade de strings afetadas"}
# Fim até 10 min à frente do relógio do servidor passa: o relógio do navegador de quem clica pode estar adiantado.
TOLERANCIA_FUTURO = _dt.timedelta(minutes=10)
# O Brasil não tem horário de verão desde 2019, e o servidor Linux roda em UTC (22/09/2026).
_BRASILIA = _dt.timezone(_dt.timedelta(hours=-3))
_FORMATOS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y")


class Recusa(Exception):
    """Nada foi gravado. `status` é o HTTP que a rota devolve."""

    def __init__(self, msg: str, status: int = 409):
        super().__init__(msg)
        self.status = status


def agora_brasilia() -> _dt.datetime:
    """Hora de parede de Brasília, ingênua, como a planilha e o diário guardam."""
    return _dt.datetime.now(_BRASILIA).replace(tzinfo=None)


def _norm(v) -> str:
    return " ".join(str(v or "").split()).strip().lower()


def _qtd(v):
    """A quantidade como número, do jeito que a aba guarda: 1 (vinda do Excel) ou "1" (criada pelo app). None se vazia
    ou ilegível. É para COMPARAR; o que a pessoa digitou passa pelo `_qtd_valida`, que é estrito. Não usa o `_norm`: ele
    trata o 0 numérico como vazio, e o "0" em texto não."""
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(float(str(v).strip().replace(",", ".")))
    except (TypeError, ValueError, OverflowError):
        return None


def _qtd_valida(v) -> int:
    """A quantidade escolhida no card → int de 1 a QTD_MAX. Recusa (400) o resto, sem arredondar: "2,5" não vira 2."""
    n = None
    if isinstance(v, bool):
        n = None                                              # True é int no Python e não é quantidade
    elif isinstance(v, int):
        n = v
    elif isinstance(v, float) and v.is_integer():
        n = int(v)
    elif isinstance(v, str) and v.strip().isdigit():
        n = int(v.strip())
    if n is None or not 1 <= n <= QTD_MAX:
        raise Recusa("Quantidade de strings afetadas inválida (%r): tem de ser um número inteiro de 1 a %d. Nada foi "
                     "gravado." % (v, QTD_MAX), 400)
    return n


def _igual(campo, a, b) -> bool:
    """O valor do banco e o da tela são o mesmo? Quantidade compara o número (1 e "1"); o resto, o texto."""
    return _qtd(a) == _qtd(b) if campo == QTD else _norm(a) == _norm(b)


def para_dt(v):
    """Mesma régua do `tickets_calc._para_dt` do OS Creator: hora local ingênua; o que não for data vira None."""
    if v in (None, "", " "):
        return None
    if isinstance(v, _dt.datetime):
        return v
    s = str(v).strip().replace("T", " ")[:19]
    for fmt in _FORMATOS:
        try:
            return _dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def para_iso(v) -> str:
    """'23/09/2026 13:20' ou '2026-09-23T13:20' → '2026-09-23 13:20:00', o formato que a coluna já guarda."""
    d = para_dt(v)
    return d.strftime("%Y-%m-%d %H:%M:%S") if d is not None else str(v or "").strip()


def impressao(oc: dict) -> str:
    """Usina + inversor, como o `tickets_diario.impressao` para a aba Strings. Sem data de propósito: o Início é
    editável, e a impressão tem de continuar casando com o registro que a gravou."""
    return "%s|%s" % (_norm(oc.get("Usina")), _norm(oc.get("Inversor")))


def linha_dict(ln: dict) -> dict:
    """Linha crua da API ({row_number, headers, values}) → {coluna: valor} com `_row`. Coluna sem nome fica de fora."""
    oc = {str(h): v for h, v in zip(ln.get("headers") or [], ln.get("values") or []) if str(h or "").strip()}
    oc["_row"] = ln.get("row_number")
    return oc


def registros(linhas_do_diario: list) -> list:
    """As linhas cruas do diário → uma lista de dicts {coluna: valor}."""
    return [linha_dict(ln) for ln in linhas_do_diario or []]


def registro_vigente(oc: dict, regs: list):
    """O registro MAIS NOVO do diário para (Strings, linha desta ocorrência), só se a impressão bater. Empate de
    `quando` fica com o que a API devolveu por último, como no `_mais_recentes` do OS Creator."""
    try:
        linha = int(oc.get("_row"))
    except (TypeError, ValueError):
        return None
    melhor = None
    for r in regs or []:
        if str(r.get("aba") or "") != ABA:
            continue
        try:
            n = int(float(r.get("linha")))
        except (TypeError, ValueError):
            continue
        if n != linha:
            continue
        if melhor is None or str(r.get("quando") or "") >= str(melhor.get("quando") or ""):
            melhor = r
    if melhor is None or _norm(melhor.get("impressao")) != _norm(impressao(oc)):
        return None                           # órfão: a linha virou outra ocorrência
    return melhor


def aplicar_diario(oc: dict, regs: list) -> dict:
    """A ocorrência como o OS Creator a vê: o registro vigente por cima. Campo VAZIO no registro não apaga o que a
    linha tem (22/09: registros parciais apagavam Início, comentário e até o Fim na tela do OS Creator)."""
    out = dict(oc)
    reg = registro_vigente(oc, regs)
    if reg:
        for c in CAMPOS:
            v = reg.get(c)
            if _norm(v):
                out[c] = v
    return out


def conferir(atual: dict, esperado: dict) -> None:
    """A linha relida ainda é o ticket que a tela mostrou? Senão, Recusa e nada é gravado."""
    n = atual.get("_row")
    if _norm(atual.get("Usina")) != _norm(esperado.get("usina_planilha")):
        raise Recusa("A linha %s agora é de \"%s\", não de \"%s\". Nada foi gravado. Atualize a tela."
                     % (n, atual.get("Usina"), esperado.get("usina_planilha")))
    if _norm(atual.get("Inversor")) != _norm(esperado.get("inversor")):
        raise Recusa("A linha %s agora é do \"%s\", não do \"%s\". Nada foi gravado. Atualize a tela."
                     % (n, atual.get("Inversor"), esperado.get("inversor")))
    ini_tela, ini = para_dt(esperado.get("desde")), para_dt(atual.get(INICIO))
    if ini_tela is not None and (ini is None or ini.date() != ini_tela.date()):
        raise Recusa("O início da linha %s (%s) não é o deste ticket (%s). Nada foi gravado. Atualize a tela."
                     % (n, atual.get(INICIO) or "vazio", esperado.get("desde")))
    fim = str(atual.get(FIM) or "").strip()
    if fim not in ("", "-"):
        raise Recusa("Este ticket já tem Fim da ocorrência (%s): alguém finalizou antes. Nada foi gravado." % fim)


def validar_fim(fim, atual: dict, agora: _dt.datetime) -> str:
    """O Fim digitado → ISO. Recusa (400) o que não é data, o que é anterior ao início e o que está no futuro."""
    d = para_dt(fim)
    if d is None:
        raise Recusa("Fim da ocorrência inválido (%r). Nada foi gravado." % (fim,), 400)
    ini = para_dt(atual.get(INICIO))
    if ini is not None and d < ini:
        raise Recusa("O Fim (%s) é antes do início do ticket (%s). Nada foi gravado."
                     % (d.strftime("%d/%m/%Y %H:%M"), ini.strftime("%d/%m/%Y %H:%M")), 400)
    if d > agora + TOLERANCIA_FUTURO:
        raise Recusa("O Fim (%s) está no futuro. Nada foi gravado." % d.strftime("%d/%m/%Y %H:%M"), 400)
    return d.strftime("%Y-%m-%d %H:%M:%S")


def corpo_da_linha(ln: dict, atual: dict, mudou: dict) -> dict:
    """A LINHA INTEIRA para o PUT, na ordem do cabeçalho da própria aba, com o que mudou por cima.

    As colunas nomeadas saem de `atual` (a linha relida com o diário por cima, como no os_web: o que o sync desfez
    volta para a planilha junto). A coluna sem nome da frente sai como está. None vira "" (o `para_valores` do OS
    Creator: None chega em alguns caminhos como o texto 'None'). Campo que só existe no diário não entra."""
    headers = list(ln.get("headers") or [])
    if FIM in mudou and FIM not in headers:
        raise Recusa("A aba de tickets não tem a coluna \"%s\". Nada foi gravado." % FIM, 502)
    crus = list(ln.get("values") or [])
    values = []
    for i, h in enumerate(headers):
        if h in mudou:
            v = mudou[h]
        elif str(h or "").strip():
            v = atual.get(h)
        else:
            v = crus[i] if i < len(crus) else ""
        values.append("" if v is None else v)
    return {"values": values, "headers": headers}


def retrato(atual: dict, mudou: dict) -> dict:
    """Todos os CAMPOS como ficam (o `retrato_para_diario` do os_web): datas em ISO, o resto aparado."""
    out = {}
    for c in CAMPOS:
        v = atual.get(c)
        v = "" if v is None else str(v).strip()
        out[c] = para_iso(v) if (c in DATAS and v) else v
    out.update(mudou)
    return out


def corpo_do_diario(atual: dict, mudou: dict, quem: str, agora: _dt.datetime) -> dict:
    """O registro do diário, nas COLUNAS do OS Creator. O relay troca o `quem` pelo nome que ele carimba."""
    dados = {"quando": agora.strftime("%Y-%m-%d %H:%M:%S"), "quem": quem, "aba": ABA, "linha": atual.get("_row"),
             "impressao": impressao(atual)}
    dados.update(retrato(atual, mudou))
    return {"values": ["" if dados.get(c) is None else dados.get(c) for c in COLUNAS], "headers": list(COLUNAS)}


def validar_valores(valores: dict, atual: dict) -> dict:
    """O que a pessoa escolheu no card → só o que MUDOU, validado. Causa e status só da lista do Levi — exceto o valor
    que a linha JÁ tem: causa antiga escrita à mão ("Problema no MPPT") continua valendo enquanto ninguém trocar. A
    quantidade, inteira de 1 a QTD_MAX, e igual ao que a linha tem ("1" ou 1) não é mudança."""
    listas = {CAUSA: CAUSAS, STATUS_T: STATUS}
    mudou = {}
    for c, v in (valores or {}).items():
        if c == QTD:
            n = _qtd_valida(v)
            if n != _qtd(atual.get(QTD)):
                mudou[QTD] = n
            continue
        if c not in listas:
            raise Recusa("Campo que esta tela não edita: %s. Nada foi gravado." % c, 400)
        v = " ".join(str(v or "").split())
        if _norm(v) == _norm(atual.get(c)):
            continue
        if v not in listas[c]:
            raise Recusa("\"%s\" não é uma opção de %s (%s). Nada foi gravado."
                         % (v or "vazio", c.lower(), ", ".join(listas[c])), 400)
        mudou[c] = v
    return mudou


def _achar(linhas: list, n: int):
    return next((ln for ln in linhas or [] if ln.get("row_number") == n), None)


def salvar(linha: int, esperado: dict, valores: dict, quem: str, *, ler_aba, gravar, agora: _dt.datetime,
           originais: dict = None, fim=None) -> dict:
    """Grava o que o card mudou no ticket da `linha`: Causa raiz, Status do ticket e quantidade de strings afetadas
    (`valores`) e, com `fim`, também o Fim da ocorrência — é o Finalizar. → {ok, linha, campos, valores, fim,
    confirmado, aviso}. Recusa = nada gravado.

    `ler_aba(sheet_id)` devolve as linhas cruas da API; `gravar(metodo, sheet_id, row, corpo)` devolve (status, texto).
    `originais` = o que o card MOSTRAVA dos campos editados: se o banco tem outro valor agora, outra pessoa mexeu
    nesse meio-tempo e nada é gravado (409), como no os_web. `confirmado` só é True com o que mudou RELIDO no banco."""
    quem = " ".join(str(quem or "").split())
    if not quem:
        raise Recusa("Diga quem está fechando: o diário guarda o autor de cada edição. Nada foi gravado.", 400)
    try:
        ln = _achar(ler_aba(SHEET_STRINGS), linha)
    except Exception as e:                                      # noqa: BLE001 — sem reler, não grava
        raise Recusa("Não consegui reler a linha %s na base de tickets (%s). Nada foi gravado." % (linha, e), 502)
    if ln is None:
        raise Recusa("A linha %s não existe mais na base de tickets. Nada foi gravado. Atualize a tela." % linha, 404)
    try:
        regs = registros(ler_aba(SHEET_DIARIO))
    except Exception as e:                                      # noqa: BLE001
        raise Recusa("Não consegui ler o diário do OS Creator (%s). Sem ele, o registro novo apagaria da tela a OS "
                     "vinculada. Nada foi gravado." % e, 502)
    atual = aplicar_diario(linha_dict(ln), regs)
    conferir(atual, esperado)
    mudou = validar_valores(valores, atual)
    brigam = [c for c in mudou if originais and c in originais and not _igual(c, atual.get(c), originais.get(c))]
    if brigam:
        raise Recusa("Outra pessoa alterou %s neste ticket depois que o card abriu (agora: %s). Nada foi gravado. "
                     "Atualize a tela." % (", ".join(_ROTULO.get(c, c.lower()) for c in brigam),
                                           "; ".join(str(atual.get(c) or "vazio") for c in brigam)))
    fim_iso = ""
    if fim is not None:
        fim_iso = validar_fim(fim, atual, agora)
        if not _norm(mudou.get(CAUSA, atual.get(CAUSA))):
            raise Recusa("Escolha a causa raiz antes de finalizar: a plataforma não finaliza ticket sem causa. "
                         "Nada foi gravado.", 400)
        mudou[FIM] = fim_iso
        mudou[STATUS_T] = STATUS_FIM
    if not mudou:
        raise Recusa("Nada mudou neste ticket.", 400)

    headers = set(ln.get("headers") or [])
    # Fim e quantidade só existem na planilha: sem a coluna (renomeada no Excel), iriam só ao diário — que não tem a
    # quantidade — e o card diria "salvo" sem nada ter mudado.
    sem_coluna = [c for c in (FIM, QTD) if c in mudou and c not in headers]
    if sem_coluna:
        raise Recusa("A aba de tickets não tem a coluna \"%s\". Nada foi gravado." % sem_coluna[0], 502)
    na_planilha = [c for c in mudou if c in headers]            # Status do ticket não é coluna: vai só ao diário
    if na_planilha:
        status, texto = gravar("PUT", SHEET_STRINGS, linha, corpo_da_linha(ln, atual, mudou))
        if not 200 <= int(status) < 300:
            raise Recusa("A base de tickets recusou a gravação (HTTP %s: %s). Nada foi gravado."
                         % (status, str(texto or "")[:200]), 502)
    aviso, diario_ok = "", False
    try:
        st, tx = gravar("POST", SHEET_DIARIO, None, corpo_do_diario(atual, mudou, quem, agora))
        diario_ok = 200 <= int(st) < 300
        if not diario_ok:
            aviso = "o diário recusou o registro (HTTP %s)" % st
    except Exception as e:                                      # noqa: BLE001 — a planilha já pode ter sido gravada
        aviso = "não consegui registrar no diário (%s)" % e
    if aviso:
        if not na_planilha:                                     # só o diário ia mudar: não gravou nada
            raise Recusa("O status não foi gravado: %s. Nada foi gravado." % aviso, 502)
        aviso = "Gravado na planilha, mas %s. Se alguém subir o Excel, a edição pode voltar atrás." % aviso
    if na_planilha:
        try:
            relida = linha_dict(_achar(ler_aba(SHEET_STRINGS), linha) or {})
        except Exception:                                       # noqa: BLE001 — sem conferir, não confirma
            relida = {}
        confirmado = all((para_iso(relida.get(c))[:16] == mudou[c][:16]) if c == FIM
                         else _igual(c, relida.get(c), mudou[c]) for c in na_planilha)
    else:
        confirmado = diario_ok
    return {"ok": True, "linha": linha, "campos": sorted(mudou), "valores": {c: mudou[c] for c in mudou},
            "fim": fim_iso, "confirmado": confirmado, "aviso": aviso}


def finalizar(linha: int, esperado: dict, fim, quem: str, *, ler_aba, gravar, agora: _dt.datetime,
              valores: dict = None, originais: dict = None) -> dict:
    """O Finalizar: `salvar` com o Fim. A causa raiz tem de existir (na linha ou escolhida agora)."""
    return salvar(linha, esperado, valores or {}, quem, ler_aba=ler_aba, gravar=gravar, agora=agora,
                  originais=originais, fim=fim)
