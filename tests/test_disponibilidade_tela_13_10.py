# -*- coding: utf-8 -*-
"""Tela Disponibilidade (/gerencial/disponibilidade) — os pedidos do Levi em 13/10/2026:

3. "Em Disponibilidade tire esse aviso de "24 OS(s) de religamento ainda abertas sem data final" deixe como um
   informação de atenção em um ícone de exclamação acima do filtro do mês, ao clicar no ícone aparece a mensagem!"
4. "Em disponibilidade nos KPIS tire a informação de disponibilidade por queda e por equipamento, deixe só o valor
   principal"
5. "Em disponibilidade visão "o que derruba o mês" estou achando muita informação. (...) Tem que deixar mais enxuto.
   "Usina - Equipamento (Inversor 1.1, Usina, Cabine 1, Skid 1 etc)" Abaixo ficaria: "OS X Tipo de tarefa Data do
   evento e data fim da atividade - hora solar. E mantém a perda ao lado!"
6. "Em disponibilidade mude a disponibilidade por usina e deixe disponibilidade por cliente! Ao clicar na linha vai
   expandir as usinas daquele cliente! ao clicar na usina aparecerá as OSs em formato de dril down!!!"

Só a apresentação muda. Os números da tela (o total do mês e o de cada usina) são os de antes, e o cliente pondera as
usinas dele pela MESMA conta do total, então fecha com ele. A página roda inteira no node, com um DOM de mentira (o
padrão dos testes de tela do repositório), sobre o payload que a rota de verdade serve. A entrada é a do gabarito
`tests/fixtures/disp_antes_13_10.json` (OS, aba Equipamentos e geração), cujas contas foram feitas à mão:
Alfa 14,5 h em 1.000 kWp, Beta 1 12 h e Beta 2 27 h em 500, Gama 7,75 h em 800 e Delta 1,5 h em 300, julho/2026 (31
dias × 12 h = 372 h).
"""
import json
import pathlib
import re
import shutil
import subprocess
from datetime import datetime
from html.parser import HTMLParser

import pytest

import app
from disponibilidade import calcular

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
TPL = RAIZ / "plataforma" / "templates" / "disponibilidade.html"
GAB = json.loads((RAIZ / "tests" / "fixtures" / "disp_antes_13_10.json").read_text(encoding="utf-8"))
NODE = shutil.which("node")
MES = "2026-07"


# ── HTML em árvore (o que o navegador montaria a partir do texto) ────────────────────────────────────────────────────
class _No:
    def __init__(self, tag, attrs, pai=None):
        self.tag, self.attrs, self.pai, self.filhos = tag, dict(attrs), pai, []

    def texto(self):
        return "".join(f if isinstance(f, str) else f.texto() for f in self.filhos)

    def todos(self, pred=lambda n: True):
        for f in self.filhos:
            if isinstance(f, _No):
                if pred(f):
                    yield f
                yield from f.todos(pred)

    def um(self, pred):
        return next(self.todos(pred), None)

    def elementos(self):
        return [f for f in self.filhos if isinstance(f, _No)]

    def classes(self):
        return (self.attrs.get("class") or "").split()

    def dentro_de(self, pred):
        n = self.pai
        while n is not None:
            if pred(n):
                return True
            n = n.pai
        return False


_VAZIAS = {"br", "img", "input", "meta", "link", "hr", "source", "wbr"}


class _Arvore(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = self.atual = _No("raiz", [])

    def handle_starttag(self, tag, attrs):
        n = _No(tag, attrs, self.atual)
        self.atual.filhos.append(n)
        if tag not in _VAZIAS:
            self.atual = n

    def handle_startendtag(self, tag, attrs):
        self.atual.filhos.append(_No(tag, attrs, self.atual))

    def handle_endtag(self, tag):
        n = self.atual
        while n is not self.raiz and n.tag != tag:
            n = n.pai
        if n is not self.raiz:
            self.atual = n.pai

    def handle_data(self, d):
        self.atual.filhos.append(d)


def arvore(html):
    p = _Arvore()
    p.feed(html)
    p.close()
    return p.raiz


def _id(i):
    return lambda n: n.attrs.get("id") == i


def _classe(c):
    return lambda n: c in n.classes()


def _limpo(s):
    return re.sub(r"\s+", " ", s).strip()


# ── a página no node ─────────────────────────────────────────────────────────────────────────────────────────────────
_DOM = r"""
const ELEMENTOS = {}, OUVIDOS_DOC = {};
function elemento(id) {
  if (ELEMENTOS[id]) return ELEMENTOS[id];
  return ELEMENTOS[id] = { id, innerHTML: '', textContent: '', hidden: false, value: '', options: [], dataset: {},
    disabled: false, attrs: {}, ouv: {}, style: {}, focos: 0,
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    addEventListener(t, f) { (this.ouv[t] = this.ouv[t] || []).push(f); },
    focus() { this.focos++; document.activeElement = this; },
    closest() { return null; }, querySelector() { return null; },
    insertAdjacentHTML(p, h) { this.innerHTML += h; },
    getBoundingClientRect() { return {left: 880, right: 1260, top: 90, bottom: 300, width: 380, height: 210}; },
    classList: {add() {}, remove() {}, toggle() {}, contains() { return false; }} };
}
globalThis.window = globalThis;
globalThis.innerWidth = 1280;
globalThis.document = { getElementById: elemento, activeElement: null, body: elemento('body'),
  addEventListener(t, f) { (OUVIDOS_DOC[t] = OUVIDOS_DOC[t] || []).push(f); } };
globalThis.fetch = () => new Promise(() => {});        // a carga sozinha fica esperando: o teste chama o render()
globalThis.setInterval = () => 0;
function saida(o) { process.stdout.write("\n" + JSON.stringify(o)); }
// o clique como o navegador entrega: o ouvinte do elemento e o do documento, com o alvo e o caminho dele (closest)
function clicar(onde, alvo) {
  const ev = {target: {closest: sel => (alvo && alvo.casa(sel)) ? alvo : null}, preventDefault() {}};
  ((onde && onde.ouv.click) || []).forEach(f => f(ev));
  (OUVIDOS_DOC.click || []).forEach(f => f(ev));
}
function tecla(key) { (OUVIDOS_DOC.keydown || []).forEach(f => f({key, target: {tagName: 'BODY'}, preventDefault() {}})); }
// o <button> que o navegador montaria a partir do HTML desenhado: os atributos são os do próprio HTML
function botaoDoHtml(html, nome) {
  const k = encodeURIComponent(nome);
  const tag = (html.match(/<button\b[^>]*>/g) || []).find(t => t.includes('data-k="' + k + '"'));
  if (!tag) throw new Error('sem botão para ' + nome);
  const at = {}; tag.replace(/([\w-]+)="([^"]*)"/g, (_, n, v) => { at[n] = v; });
  return { tag, attrs: at, dataset: {k: at['data-k'], tipo: at['data-tipo']},
    casa: sel => /button/.test(sel),
    getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; },
    setAttribute(n, v) { this.attrs[n] = String(v); }, focus() { document.activeElement = this; } };
}
"""

# A régua de ANTES (template até 13/10/2026, commit 6ad711e), copiada sem mudança: o total ponderado do KPI e o número
# de cada usina nas barras. A página nova tem de mostrar exatamente isto.
_ANTES = r"""
function antes(j) {
  const fmtp = n => n == null ? '—' : n.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const us = j.usinas.slice().sort((a, b) => (a.disp ?? 101) - (b.disp ?? 101));
  const totKwp = us.reduce((s, u) => s + (u.pot_kwp || 0), 0);
  const totH = 12 * j.periodo.dias;
  const _pond = campo => totKwp
    ? 100 * (1 - us.reduce((s, u) => s + u.pot_kwp * u[campo], 0) / (totKwp * totH)) : null;
  const pond = _pond('h_perdidas');
  return {us, pond, kDisp: fmtp(pond) + '<small>%</small>',
          barras: Object.fromEntries(us.map(u => [u.usina, fmtp(u.disp) + '%']))};
}
"""


def _script():
    scripts = re.findall(r"<script>(.*?)</script>", TPL.read_text(encoding="utf-8"), re.S)
    assert len(scripts) == 1, "a página tem um <script> só (o aviso de sessão o app injeta)"
    return scripts[0]


def _estaticos():
    """Cada elemento com id do HTML estático nasce no DOM de mentira como o navegador o monta: `hidden` e os aria-*."""
    return {n.attrs["id"]: {"hidden": "hidden" in n.attrs,
                            "attrs": {k: v for k, v in n.attrs.items() if k.startswith("aria-")}}
            for n in arvore(TPL.read_text(encoding="utf-8")).todos(lambda n: "id" in n.attrs)}


def _pagina(payload, roteiro, tmp_path):
    if not NODE:
        pytest.skip("node não instalado")
    semente = ("for (const [id, s] of Object.entries(" + json.dumps(_estaticos(), ensure_ascii=False) + ")) {"
               " const e = elemento(id); e.hidden = s.hidden; Object.assign(e.attrs, s.attrs); }\n")
    js = (_DOM + _ANTES + semente + _script() + "\n;const P = " + json.dumps(payload, ensure_ascii=False) + ";\n"
          + "(async () => {\n" + roteiro + "\n})().catch(e => { process.stderr.write(String(e && e.stack || e)); "
          "process.exit(1); });\n")
    arq = tmp_path / "pagina.js"
    arq.write_text(js, encoding="utf-8")
    p = subprocess.run([NODE, str(arq)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr[-3000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


def _calcula(entrada=None):
    e = entrada or GAB["entrada"]
    return calcular(e["wos"], e["equip"], datetime.fromisoformat(e["per_ini"]), datetime.fromisoformat(e["per_fim"]),
                    agora=datetime.fromisoformat(e["agora"]), geracao=e["geracao"])


@pytest.fixture
def servir(tmp_path, monkeypatch):
    """A rota de verdade servindo um índice gravado numa pasta temporária (o web só lê o arquivo do worker)."""
    monkeypatch.setattr(app, "_FRAC_DISP_FILE", str(tmp_path / "frac_disp_index.json"))
    monkeypatch.setattr(app, "_FRAC_DISP_STATUS", str(tmp_path / "frac_disp_status.json"))
    monkeypatch.setattr(app, "_frac_disp_mem", {"mtime": 0.0, "dados": {}})
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    web = app.app.test_client()

    def _servir(mes_calc, cliente=""):
        (tmp_path / "frac_disp_index.json").write_text(
            json.dumps({"ts": 1784000000.0, "meses": {MES: mes_calc}}, ensure_ascii=False), encoding="utf-8")
        app._frac_disp_mem.update(mtime=0.0, dados={})
        r = web.get(f"/api/gerencial/disponibilidade?mes={MES}" + (f"&cliente={cliente}" if cliente else ""))
        assert r.status_code == 200
        return r.get_json()
    return _servir


def _linhas_cliente(html):
    """[(cliente, valor, [(usina, valor), ...])] na ordem da tela."""
    raiz, out = arvore(html), []
    for b in raiz.todos(lambda n: n.tag == "button" and n.attrs.get("data-tipo") == "cli"):
        nome = _limpo(b.um(_classe("u")).filhos[0])
        reg = raiz.um(_id(b.attrs["aria-controls"]))
        us = [(_limpo(u.um(_classe("u")).texto()), _limpo(u.um(_classe("v")).texto()))
              for u in reg.todos(lambda n: n.tag == "button" and n.attrs.get("data-tipo") == "usi")]
        out.append((nome, _limpo(b.um(_classe("v")).texto()), us))
    return out


def _itens_os(html):
    """[(título, linha de baixo, perda)] de uma lista de OS (O que derrubou o mês ou o drill-down de uma usina)."""
    return [(_limpo(ev.um(_classe("t")).texto()), _limpo(ev.um(_classe("m")).texto()),
             _limpo(ev.um(_classe("kwh")).texto()))
            for ev in arvore(html).todos(_classe("ev"))]


# ── 0. a conta é a mesma de antes ────────────────────────────────────────────────────────────────────────────────────
def test_o_modulo_devolve_a_mesma_saida_de_antes_da_mudanca():
    """O disponibilidade.py de agora, sobre a entrada gravada, devolve exatamente a saída do de antes (6ad711e): usina por
    usina, cliente por cliente, dia por dia e OS por OS. O que entrou de novo é a perda de cada OS em cada usina
    (`kwh_usina`, para o drill-down), que reparte a perda da OS e soma a da usina, e a parcela de cada OS em cada dia
    (`os` no diário, 14/10/2026, para o comentário do Dashboard Thopen), que soma o h_eq do dia."""
    novo = json.loads(json.dumps(_calcula(), ensure_ascii=False))
    partes = {o["folio"]: o.pop("kwh_usina") for o in novo["oss"]}
    do_dia = {(u, d): v.pop("os") for u, dias in novo["diario"].items() for d, v in dias.items()}
    assert novo == GAB["saida"]
    for (u, d), lst in do_dia.items():
        assert lst and abs(sum(x["h"] for x in lst) - novo["diario"][u][d]["h_eq"]) <= 0.002 * len(lst), (u, d)
    for o in novo["oss"]:
        assert sum(partes[o["folio"]].values()) == o["kwh"], o["folio"]
    for u in novo["usinas"]:
        assert sum(p.get(u["usina"], 0) for p in partes.values()) == u["kwh"], u["usina"]
        assert sum(1 for p in partes.values() if u["usina"] in p) == u["n_os"], u["usina"]


def test_total_do_mes_e_cada_usina_sao_os_mesmos_de_antes(servir, tmp_path):
    r = _pagina(servir(_calcula()), """
      DADOS = P; render(P, '');
      const a = antes(P);
      saida({kDisp: elemento('kDisp').innerHTML, antesKDisp: a.kDisp, antesBarras: a.barras,
             mesmaConta: dispPonderada(a.us, P.periodo.dias) === a.pond, html: elemento('porCliente').innerHTML});""",
                tmp_path)
    assert r["kDisp"] == r["antesKDisp"] == "96,48<small>%</small>"      # 1 − 40.650 ÷ (3.100 kWp × 372 h)
    assert r["mesmaConta"] is True, "o total tem de ser a mesma conta de antes, bit a bit"
    usinas = {u: v for _c, _v, us in _linhas_cliente(r["html"]) for u, v in us}
    assert usinas == r["antesBarras"] == {"Alfa": "96,10%", "Beta 1": "96,77%", "Beta 2": "92,74%",
                                          "Gama": "97,92%", "Delta": "99,60%"}


# ── 6. disponibilidade por cliente ───────────────────────────────────────────────────────────────────────────────────
def test_um_cliente_por_linha_pior_primeiro_com_as_usinas_dele(servir, tmp_path):
    r = _pagina(servir(_calcula()), "DADOS = P; render(P, ''); saida({html: elemento('porCliente').innerHTML});",
                tmp_path)
    # TesteCo: 1 − (14,5×1.000 + 12×500 + 27×500) ÷ (2.000 × 372) = 95,43%; OutraCo: 1 − (7,75×800 + 1,5×300) ÷
    # (1.100 × 372) = 98,37%. A Terceirizada (não é Full O&M) não entra.
    assert _linhas_cliente(r["html"]) == [
        ("TesteCo", "95,43%", [("Beta 2", "92,74%"), ("Alfa", "96,10%"), ("Beta 1", "96,77%")]),
        ("OutraCo", "98,37%", [("Gama", "97,92%"), ("Delta", "99,60%")])]


def test_o_cliente_pondera_pela_conta_do_total_e_fecha_com_ele(servir, tmp_path):
    p = servir(_calcula())
    r = _pagina(p, """
      const us = P.usinas.slice().sort((a, b) => (a.disp ?? 101) - (b.disp ?? 101));
      const g = gruposPorCliente(us, P.periodo.dias), tot = dispPonderada(us, P.periodo.dias);
      const kwp = c => c.usinas.reduce((s, u) => s + u.pot_kwp, 0);
      const fecha = 100 - g.reduce((s, c) => s + kwp(c) * (100 - c.disp), 0) / g.reduce((s, c) => s + kwp(c), 0);
      saida({g: g.map(c => [c.cliente, c.disp]), tot, fecha});""", tmp_path)
    assert r["fecha"] == pytest.approx(r["tot"], abs=1e-9)
    modulo = {c["cliente"]: c["disp"] for c in p["clientes"]}          # o mesmo número que o módulo já publicava
    assert {c: round(v, 2) for c, v in r["g"]} == modulo == {"TesteCo": 95.43, "OutraCo": 98.37}


def test_com_o_filtro_de_cliente_a_linha_dele_e_o_total(servir, tmp_path):
    r = _pagina(servir(_calcula(), cliente="OutraCo"), """
      DADOS = P; render(P, 'OutraCo');
      saida({kDisp: elemento('kDisp').innerHTML, html: elemento('porCliente').innerHTML});""", tmp_path)
    assert r["kDisp"] == "98,37<small>%</small>"
    assert _linhas_cliente(r["html"]) == [("OutraCo", "98,37%", [("Gama", "97,92%"), ("Delta", "99,60%")])]


def test_linhas_sao_botoes_que_abrem_e_fecham_com_aria_expanded(servir, tmp_path):
    r = _pagina(servir(_calcula()), """
      DADOS = P; render(P, '');
      const html = elemento('porCliente').innerHTML, b = botaoDoHtml(html, 'OutraCo');
      const regiao = b.getAttribute('aria-controls');
      elemento(regiao).hidden = true;                          // como o HTML desenhado: fechado
      clicar(elemento('porCliente'), b); const aberto = [b.getAttribute('aria-expanded'), elemento(regiao).hidden];
      clicar(elemento('porCliente'), b); const fechado = [b.getAttribute('aria-expanded'), elemento(regiao).hidden];
      saida({html, aberto, fechado});""", tmp_path)
    raiz = arvore(r["html"])
    botoes = list(raiz.todos(lambda n: n.attrs.get("data-tipo") in ("cli", "usi")))
    assert botoes and all(b.tag == "button" and b.attrs.get("type") == "button" for b in botoes), \
        "linha clicável é <button type=button>: Enter e Espaço funcionam sem código"
    for b in botoes:                                            # cada botão diz o que abre, e a região começa fechada
        assert b.attrs["aria-expanded"] == "false"
        reg = raiz.um(_id(b.attrs["aria-controls"]))
        assert reg is not None and "hidden" in reg.attrs
    assert r["aberto"] == ["true", False] and r["fechado"] == ["false", True]


def test_usina_aberta_mostra_as_os_da_conta_dela(servir, tmp_path):
    r = _pagina(servir(_calcula()), """
      DADOS = P; render(P, '');
      const html = elemento('porCliente').innerHTML, b = botaoDoHtml(html, 'Gama');
      clicar(elemento('porCliente'), b); const reg = elemento(b.getAttribute('aria-controls'));
      saida({drill: reg.innerHTML, hidden: reg.hidden});""", tmp_path)
    assert r["hidden"] is False
    # a mesma régua da conta: só OS com evento na usina (a 35, relâmpago de 0 h, e a 34, cancelada, ficam fora);
    # a maior perda primeiro, empate pela data do evento
    assert _itens_os(r["drill"]) == [
        ("Skid 1", "OS 30 · Religamento Remoto · 10/07 09:00 → 10/07 14:00 · 5 h solares", "2.000kWh"),
        ("Usina", "OS 33 · Corretiva Emergencial + Religamento · 14/07 07:00 → 14/07 09:00 · 2 h solares", "1.600kWh"),
        ("QGBT 2", "OS 31 · Religamento · 11/07 10:00 → 11/07 12:00 · 2 h solares", "800kWh"),
        ("Disjuntor do Inversor 2.2", "OS 32 · Corretiva Emergencial · 12/07 08:00 → 12/07 12:00 · 4 h solares",
         "800kWh"),
        ("Disjuntor do Transformador 2", "OS 37 · Religamento · 19/07 09:00 → 19/07 10:30 · 1,5 h solares", "600kWh"),
        ("Ponto de Entrega 1", "OS 36 · Religamento · 18/07 09:00 → 18/07 10:00 · 1 h solares", "400kWh")]


def test_os_de_duas_usinas_mostra_a_perda_de_cada_uma(servir, tmp_path):
    # OS 20, site Beta 1 e 2 sem pista: 18.000 kWh. A geração da Beta 1 desmente o dia 11, então a Beta 1 perde 12 h ×
    # 500 = 6.000 e a Beta 2, 24 h × 500 = 12.000 — não 9.000 e 9.000 pela potência
    r = _pagina(servir(_calcula()), """
      DADOS = P; render(P, ''); const html = elemento('porCliente').innerHTML, d = {};
      for (const u of ['Beta 1', 'Beta 2']) { const b = botaoDoHtml(html, u); clicar(elemento('porCliente'), b);
        d[u] = elemento(b.getAttribute('aria-controls')).innerHTML; }
      saida(d);""", tmp_path)
    assert _itens_os(r["Beta 1"]) == [
        ("Usina", "OS 20 · Religamento · 10/07 06:00 → 11/07 18:00 · 24 h solares · 1 dia desmentido pela geração",
         "6.000kWh")]
    assert _itens_os(r["Beta 2"]) == [
        ("Usina", "OS 20 · Religamento · 10/07 06:00 → 11/07 18:00 · 24 h solares", "12.000kWh"),
        ("Cabine 2", "OS 21 · Religamento · 20/07 09:00 → 20/07 12:00 · 3 h solares", "1.500kWh")]


def test_drill_diz_em_aberto_e_o_que_passa_da_borda_do_mes(servir, tmp_path):
    r = _pagina(servir(_calcula()), """
      DADOS = P; render(P, ''); const html = elemento('porCliente').innerHTML, d = {};
      for (const u of ['Delta', 'Alfa']) { const b = botaoDoHtml(html, u); clicar(elemento('porCliente'), b);
        d[u] = elemento(b.getAttribute('aria-controls')).innerHTML; }
      saida(d);""", tmp_path)
    # Delta: a 42 segue aberta (uma tarefa em andamento) com o fim da atividade; a 41 é noturna (conta, com 0 h); a 40,
    # aberta SEM data final, entra com 0 h e não tem evento — fica no aviso, não no drill
    assert _itens_os(r["Delta"]) == [
        ("Inversor 1.1", "OS 42 · Religamento · 22/07 08:00 → 22/07 11:00 · 3 h solares · em aberto", "450kWh"),
        ("Inversor 1.2", "OS 41 · Religamento · 20/07 20:00 → 20/07 22:00 · 0 h solares", "0kWh")]
    alfa = _itens_os(r["Alfa"])
    assert [t[1].split(" · ")[0] for t in alfa] == ["OS 10", "OS 11", "OS 13", "OS 70", "OS 12", "OS 50", "OS 14"]
    assert ("Inversor 2.1", "OS 50 · Religamento · 30/06 15:00 → 01/07 09:00 · 3 h solares no mês", "600kWh") in alfa


def test_o_que_esta_aberto_continua_aberto_na_releitura_de_5_min(servir, tmp_path):
    r = _pagina(servir(_calcula()), """
      DADOS = P; render(P, ''); let html = elemento('porCliente').innerHTML;
      clicar(elemento('porCliente'), botaoDoHtml(html, 'TesteCo'));
      clicar(elemento('porCliente'), botaoDoHtml(html, 'Alfa'));
      render(P, '');                                   // o carregar() de 5 em 5 min redesenha tudo
      saida({html: elemento('porCliente').innerHTML});""", tmp_path)
    raiz = arvore(r["html"])
    abertos = {_limpo(b.um(_classe("u")).filhos[0]): b
               for b in raiz.todos(lambda n: n.attrs.get("aria-expanded") == "true")}
    assert set(abertos) == {"TesteCo", "Alfa"}
    for b in abertos.values():
        assert "hidden" not in raiz.um(_id(b.attrs["aria-controls"])).attrs
    drill = raiz.um(_id(abertos["Alfa"].attrs["aria-controls"]))
    assert len(list(drill.todos(_classe("ev")))) == 7


def test_indice_de_antes_do_deploy_sem_a_perda_por_usina(servir, tmp_path):
    """Até o worker refazer o índice (até 30 min depois do deploy) o web serve o de antes, sem `kwh_usina`: a OS de duas
    usinas mostra a perda das duas, dizendo isso, e a de 0 h (aberta sem fim, relâmpago) não entra."""
    r = _pagina(servir(GAB["saida"]), """
      DADOS = P; render(P, ''); const html = elemento('porCliente').innerHTML, d = {};
      for (const u of ['Beta 1', 'Delta', 'Gama']) { const b = botaoDoHtml(html, u); clicar(elemento('porCliente'), b);
        d[u] = elemento(b.getAttribute('aria-controls')).innerHTML; }
      saida(d);""", tmp_path)
    assert _itens_os(r["Beta 1"]) == [
        ("Usina · perda somada das 2 usinas do site",
         "OS 20 · Religamento · 10/07 06:00 → 11/07 18:00 · 24 h solares · 1 dia desmentido pela geração", "18.000kWh")]
    assert [t[1].split(" · ")[0] for t in _itens_os(r["Delta"])] == ["OS 42", "OS 41"]
    assert "OS 35" not in r["Gama"] and len(_itens_os(r["Gama"])) == 6


# ── 5. o que derrubou o mês ──────────────────────────────────────────────────────────────────────────────────────────
def test_o_que_derrubou_o_mes_em_duas_linhas_com_a_perda_ao_lado(servir, tmp_path):
    r = _pagina(servir(_calcula()), "DADOS = P; render(P, ''); saida({html: elemento('eventos').innerHTML});", tmp_path)
    assert _itens_os(r["html"]) == [
        ("Beta 1, Beta 2 – Usina",
         "OS 20 · Religamento · 10/07 06:00 → 11/07 18:00 · 24 h solares · 1 dia desmentido pela geração", "18.000kWh"),
        ("Alfa – Usina", "OS 10 · Religamento · 10/07 09:00 → 10/07 15:00 · 6 h solares", "6.000kWh"),
        ("Alfa – Cabine 2", "OS 11 · Corretiva Emergencial · 12/07 09:00 → 12/07 15:00 · 6 h solares", "2.400kWh"),
        ("Alfa – Usina", "OS 13 · Religamento · 15/07 09:00 → 15/07 11:00 · 2 h solares", "2.000kWh"),
        ("Alfa – Usina", "OS 70 · Religamento · 20/07 09:00 → 20/07 11:00 · 2 h solares", "2.000kWh"),
        ("Gama – Skid 1", "OS 30 · Religamento Remoto · 10/07 09:00 → 10/07 14:00 · 5 h solares", "2.000kWh")]
    assert not list(arvore(r["html"]).todos(_classe("tag-org"))), "a divisão queda × equipamento saiu desta visão"


@pytest.mark.parametrize("codigo, nome", [
    ("THPN-SRD100", "Usina"),                         # raiz do site: a usina inteira
    ("GY-CDP100-CABN2", "Cabine 2"),
    ("THPN-APR200-SKID1", "Skid 1"),
    ("THPN-ORB100-QGBT4", "QGBT 4"),
    ("THPN-XYZ100-PECN3", "Ponto de Entrega 3"),
    ("TPP100-DTRF2", "Disjuntor do Transformador 2"),
    ("CAZ100-INVR1.3", "Inversor 1.3"),
    ("MRO100-DINV1.12", "Disjuntor do Inversor 1.12"),
])
def test_equipamento_com_o_nome_do_cadastro(codigo, nome, tmp_path):
    # os nomes do cadastro do Fracttal para cada sufixo do código do ativo (items_log_description de 39 mil tarefas)
    r = _pagina({}, "saida({nome: equipamento({code: %s})});" % json.dumps(codigo), tmp_path)
    assert r["nome"] == nome


# ── 4. KPIs ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_kpi_de_disponibilidade_so_com_o_valor_principal(servir, tmp_path):
    raiz = arvore(TPL.read_text(encoding="utf-8"))
    kpi = raiz.um(lambda n: "kpi" in n.classes() and n.um(_id("kDisp")) is not None)
    assert [(e.tag, e.classes(), e.attrs.get("id")) for e in kpi.elementos()] == [
        ("div", ["lbl"], None), ("div", ["val"], "kDisp"), ("div", ["note"], "kDispNote")]
    assert _limpo(kpi.um(_classe("lbl")).texto()) == "Disponibilidade"
    r = _pagina(servir(_calcula()), """DADOS = P; render(P, '');
      saida({kDisp: elemento('kDisp').innerHTML, nota: elemento('kDispNote').textContent});""", tmp_path)
    assert r == {"kDisp": "96,48<small>%</small>", "nota": "5 usinas · 3.100 kWp · 31 dias"}


# ── 3. o aviso das OS abertas virou um ícone acima do filtro do mês ──────────────────────────────────────────────────
_AVISO = ("1 OS(s) de religamento ainda abertas sem data final entraram com 0 h no cálculo (OSs esquecidas abertas "
          "distorceriam o mês). Se forem parada real, somariam até 24.300 kWh: OS 40 (Delta)")


def test_icone_de_atencao_fica_acima_do_filtro_do_mes_fora_do_corpo():
    raiz = arvore(TPL.read_text(encoding="utf-8"))
    wrap, mes = raiz.um(_id("avisoWrap")), raiz.um(_id("selMes"))
    irmaos = wrap.pai.elementos()
    assert wrap.pai is mes.pai and irmaos.index(wrap) < irmaos.index(mes), "o ícone fica em cima do seletor do mês"
    assert not wrap.dentro_de(_id("conteudo")), "a mensagem saiu do corpo da tela"
    assert "hidden" in wrap.attrs, "sem nada a avisar, nada aparece"
    btn = wrap.um(_id("avisoBtn"))
    assert btn.tag == "button" and btn.attrs.get("type") == "button"
    assert btn.attrs.get("aria-expanded") == "false" and btn.attrs.get("aria-controls") == "avisoBalao"
    assert btn.um(lambda n: n.tag == "svg") is not None, "ícone desenhado (Phosphor warning-circle), não emoji"
    emoji = "[%s-%s%s-%s]" % (chr(0x1F300), chr(0x1FAFF), chr(0x2600), chr(0x27BF))
    assert not re.search(emoji, btn.texto() + btn.attrs.get("aria-label", ""))
    balao = wrap.um(_id("avisoBalao"))
    assert balao is not None and "hidden" in balao.attrs


def test_icone_aparece_com_o_aviso_e_o_clique_mostra_a_mensagem(servir, tmp_path):
    r = _pagina(servir(_calcula()), """
      DADOS = P; render(P, '');
      const b = elemento('avisoBtn'), bal = elemento('avisoBalao'), wrap = elemento('avisoWrap');
      const fechado = {wrap: wrap.hidden, balao: bal.hidden, exp: b.getAttribute('aria-expanded')};
      clicar(b, {casa: sel => sel === '#avisoWrap'});
      const aberto = {balao: bal.hidden, exp: b.getAttribute('aria-expanded')};
      document.activeElement = null; tecla('Escape');
      const esc = {balao: bal.hidden, exp: b.getAttribute('aria-expanded'), foco: document.activeElement === b};
      clicar(b, {casa: sel => sel === '#avisoWrap'});
      clicar(null, {casa: () => false});                  // clique em qualquer outro lugar da tela
      const fora = {balao: bal.hidden, exp: b.getAttribute('aria-expanded')};
      saida({fechado, aberto, esc, fora, texto: elemento('avisoTxt').innerHTML, rotulo: b.getAttribute('aria-label')});""",
                tmp_path)
    assert r["fechado"] == {"wrap": False, "balao": True, "exp": "false"}
    assert r["aberto"] == {"balao": False, "exp": "true"}
    assert r["esc"] == {"balao": True, "exp": "false", "foco": True}, "Esc fecha e devolve o foco ao ícone"
    assert r["fora"] == {"balao": True, "exp": "false"}, "clique fora fecha"
    assert _limpo(arvore(r["texto"]).texto()) == _AVISO, "o texto da mensagem é o de antes, inteiro"
    assert "1 OS" in r["rotulo"]


def test_quando_a_os_aberta_ganha_fim_o_icone_some(servir, tmp_path):
    # a OS 40 ganhou data final no Fracttal: a releitura seguinte não tem mais o que avisar — o ícone some e o balão
    # aberto fecha junto
    sem = _calcula({**GAB["entrada"], "wos": {k: v for k, v in GAB["entrada"]["wos"].items() if k != "40"}})
    leituras = {"com": servir(_calcula()), "sem": servir(sem)}
    r = _pagina(leituras, """
      DADOS = P.com; render(P.com, '');
      const b = elemento('avisoBtn'); clicar(b, {casa: sel => sel === '#avisoWrap'});
      const aberto = b.getAttribute('aria-expanded');
      DADOS = P.sem; render(P.sem, '');
      saida({aberto, wrap: elemento('avisoWrap').hidden, balao: elemento('avisoBalao').hidden,
             exp: b.getAttribute('aria-expanded')});""", tmp_path)
    assert r == {"aberto": "true", "wrap": True, "balao": True, "exp": "false"}


def test_mes_sem_indice_nao_deixa_o_aviso_de_outro_mes(servir, tmp_path):
    # a leitura que volta "quente: false" (o mês saiu do índice) esconde os números — e o ícone, que era daquele mês
    r = _pagina(servir(_calcula()), """
      DADOS = P; render(P, ''); const antes = elemento('avisoWrap').hidden;
      globalThis.fetch = async () => ({ok: true, status: 200, json: async () => ({quente: false, meses: []})});
      await carregar();
      saida({antes, depois: elemento('avisoWrap').hidden, conteudo: elemento('conteudo').hidden});""", tmp_path)
    assert r == {"antes": False, "depois": True, "conteudo": True}
