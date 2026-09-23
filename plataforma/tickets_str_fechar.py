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


def corpo_da_linha(ln: dict, atual: dict, fim_iso: str) -> dict:
    """A LINHA INTEIRA para o PUT, na ordem do cabeçalho da própria aba, com o Fim por cima.

    As colunas nomeadas saem de `atual` (a linha relida com o diário por cima, como no os_web: o que o sync desfez
    volta para a planilha junto). A coluna sem nome da frente sai como está. None vira "" (o `para_valores` do OS
    Creator: None chega em alguns caminhos como o texto 'None')."""
    headers = list(ln.get("headers") or [])
    if FIM not in headers:
        raise Recusa("A aba de tickets não tem a coluna \"%s\". Nada foi gravado." % FIM, 502)
    crus = list(ln.get("values") or [])
    values = []
    for i, h in enumerate(headers):
        if h == FIM:
            v = fim_iso
        elif str(h or "").strip():
            v = atual.get(h)
        else:
            v = crus[i] if i < len(crus) else ""
        values.append("" if v is None else v)
    return {"values": values, "headers": headers}


def retrato(atual: dict, fim_iso: str) -> dict:
    """Todos os CAMPOS como ficam (o `retrato_para_diario` do os_web): datas em ISO, o resto aparado."""
    out = {}
    for c in CAMPOS:
        v = atual.get(c)
        v = "" if v is None else str(v).strip()
        out[c] = para_iso(v) if (c in DATAS and v) else v
    out[FIM] = fim_iso
    return out


def corpo_do_diario(atual: dict, fim_iso: str, quem: str, agora: _dt.datetime) -> dict:
    """O registro do diário, nas COLUNAS do OS Creator. O relay troca o `quem` pelo nome que ele carimba."""
    dados = {"quando": agora.strftime("%Y-%m-%d %H:%M:%S"), "quem": quem, "aba": ABA, "linha": atual.get("_row"),
             "impressao": impressao(atual)}
    dados.update(retrato(atual, fim_iso))
    return {"values": ["" if dados.get(c) is None else dados.get(c) for c in COLUNAS], "headers": list(COLUNAS)}


def _achar(linhas: list, n: int):
    return next((ln for ln in linhas or [] if ln.get("row_number") == n), None)


def finalizar(linha: int, esperado: dict, fim, quem: str, *, ler_aba, gravar, agora: _dt.datetime) -> dict:
    """Grava o Fim da ocorrência do ticket da `linha`. → {ok, linha, fim, confirmado, aviso}. Recusa = nada gravado.

    `ler_aba(sheet_id)` devolve as linhas cruas da API; `gravar(metodo, sheet_id, row, corpo)` devolve
    (status HTTP, texto). `confirmado` só é True com o Fim RELIDO no banco depois de gravar."""
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
    fim_iso = validar_fim(fim, atual, agora)

    status, texto = gravar("PUT", SHEET_STRINGS, linha, corpo_da_linha(ln, atual, fim_iso))
    if not 200 <= int(status) < 300:
        raise Recusa("A base de tickets recusou a gravação (HTTP %s: %s). Nada foi gravado."
                     % (status, str(texto or "")[:200]), 502)
    aviso = ""
    try:
        st, tx = gravar("POST", SHEET_DIARIO, None, corpo_do_diario(atual, fim_iso, quem, agora))
        if not 200 <= int(st) < 300:
            aviso = ("Gravado na planilha, mas o diário recusou o registro (HTTP %s). Se alguém subir o Excel, o "
                     "ticket pode reabrir." % st)
    except Exception as e:                                      # noqa: BLE001 — a planilha já foi gravada
        aviso = ("Gravado na planilha, mas não consegui registrar no diário (%s). Se alguém subir o Excel, o ticket "
                 "pode reabrir." % e)
    try:
        relida = _achar(ler_aba(SHEET_STRINGS), linha)
        lido = para_iso(linha_dict(relida).get(FIM)) if relida else ""
    except Exception:                                           # noqa: BLE001 — sem conferir, não confirma
        lido = ""
    return {"ok": True, "linha": linha, "fim": fim_iso, "confirmado": lido[:16] == fim_iso[:16], "aviso": aviso}
