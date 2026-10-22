# -*- coding: utf-8 -*-
"""O que o Modo de-para do Tempo real e a Base · De-para de equipamentos LEEM (20/10/2026): a árvore do Fracttal (usina →
cabine → inversor) e o Registro mestre (o kWp da usina). Só leitura; a regra pura e os leitores em fundo. Quem vai à rede
é o app: ele entrega o leitor do banco (`cobertura.Decisoes`) e o pedido ao Fracttal (`_frac_get`).

Levi, 20/10/2026, com o protótipo aprovado ("Boa, é isso mesmo. Implementa no tempo real e adapta na base o de-para para
ficar nesse padrão de tabela"): a tela liga cada inversor da fonte ao ativo dele no Fracttal e à cabine, com as strings
corretas e o kWp pela regra do Registro mestre. Quem GRAVA é o Nexus (a estrutura das usinas, `nexus_estrutura_usina`); a
plataforma só lê o que a tela precisa para sugerir.

De onde vem cada coisa:
- a árvore: a dimensão de equipamento do Nexus (`nexus_equipamentos · dim_equipamento`, aba 477 do banco), que é a FOTO
  dos ativos do Fracttal de 22/09 (carga única do Levi). O inversor cai na cabine SUBINDO pelo `pai_id` (na Itajá:
  ITA100-INVR1.1 → QGBT1 → SKID1 → CABN1); sem pai até uma cabine, pelo número do código (INVR2.1 → CABN2). O nome sai
  SEMPRE do código ("Inversor 2.1", "Cabine 2"), nunca da descrição: 2.380 das 2.477 descrições trazem marca e modelo
  ("Inversor 1.3 Huawei SUN2000-250KTL-H1"), e o número tirado delas acertaria 39 de 1.743 inversores (o "1" do "H1";
  levantamento de cobertura de 20/10/2026).
- usina fora da foto: a Pharmas foi refeita no Fracttal depois de 22/09 (PHS200/300/400 viraram a THPN-PHS100, com CABN2,
  CABN3 e CABN4); na dimensão ela só tem os códigos que o PCM gravou, sem pai, sem descrição e sem a raiz. Para essas a
  plataforma lê a árvore no próprio Fracttal (`BuscaFracttal`), em fundo, 1 pedido por segundo (a cota de 200/min é da
  EMPRESA inteira), e guarda 7 dias em disco. A resposta não espera: sai a árvore da foto com `pendente: true`.
- o kWp: o Registro mestre (`cadastro_nexus · usinas`, aba 450), potência real em MWp × 1.000; sem a real, a CONTRATUAL
  (decisão do Levi, 20/10/2026: "Nesse caso, onde não tem potência real, vai usar potência contratual" — as 68 usinas sem a
  real têm a contratual, na mesma unidade); sem as duas, vazio. A Rodrigues II tem "0,,643" digitado na real: ilegível
  conta como sem a real e cai na contratual (2.570 kWp).
Só as colunas que não são sensíveis entram na memória e no disco (o Registro tem `sensivel_cifrado`; a plataforma não tem a
chave, de propósito).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone

# ── os livros do banco (por nome, nunca pelo id da aba) ───────────────────────────────────────────────────────────────
LIVRO_EQUIP, ABA_EQUIP = "nexus_equipamentos", "dim_equipamento"
CAB_EQUIP = ("equipamento_id", "codigo", "descricao", "usina_id", "familia", "pai_id", "na_foto", "foto_em")
LIVRO_CADASTRO = "cadastro_nexus"
ABA_USINAS = "usinas"
CAB_USINAS = ("usina_id", "codigo", "nome", "status", "cliente_id", "potencia_real", "potencia_contratual", "excluido")
ABA_CLIENTES = "clientes"
CAB_CLIENTES = ("cliente_id", "nome", "excluido")


def _txt(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    return " ".join(str(v).split())


def _int(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f == f and f.is_integer() else None


def canon(codigo) -> str:
    """O código do ativo como a dimensão do Nexus o guarda: maiúsculo e sem espaço (`nexus/dados/equipamento.py`)."""
    return re.sub(r"\s+", "", str(codigo or "")).upper()


def natural(codigo):
    """INVR1.2 antes de INVR1.10; CABN2 antes de CABN10."""
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.split(r"(\d+)", str(codigo or "")) if p]


def _numero(codigo, familia):
    m = re.search(rf"-{familia}(\d+(?:\.\d+)*)", canon(codigo))
    return ".".join(str(int(p)) for p in m.group(1).split(".")) if m else None


def nome_inversor(codigo):
    """"Inversor 2.1" pelo CÓDIGO (THPN-PHS100-INVR2.1), ou None quando o código não é de inversor."""
    n = _numero(codigo, "INVR")
    return f"Inversor {n}" if n else None


def nome_cabine(codigo):
    """"Cabine 2" pelo CÓDIGO (THPN-PHS100-CABN2), ou None."""
    n = _numero(codigo, "CABN")
    return f"Cabine {n}" if n else None


def numero_cabine(codigo):
    n = _numero(codigo, "CABN")
    return int(n.split(".")[0]) if n else None


def bloco_do_inversor(codigo):
    """O N do INVR N.M: a cabine pelo número, quando o inversor não tem pai até uma (o protótipo e o _frac_inv_code)."""
    n = _numero(codigo, "INVR")
    return int(n.split(".")[0]) if n else None


def cabine_da_ug(ug):
    """"UG 02" (o "Equipamento Parente" do cadastro) → "Cabine 2". A cabine do Nexus é a CABN do Fracttal com o nome
    "UG NN" (decisão do Levi, 20/10/2026: "foque em cabine"); o que não começa com UG não é cabine para ninguém."""
    m = re.match(r"\s*UG\s*0*(\d+)\b", str(ug or ""), re.I)
    return f"Cabine {int(m.group(1))}" if m else None


def site(codigo):
    """O código da usina que o código do ativo carrega: "THPN-PHS100" de THPN-PHS100-INVR2.1, "ITA100" de ITA100-CABN1."""
    m = re.match(r"^((?:[A-Z0-9]+-)?[A-Z]{3}\d{3})-", canon(codigo))
    return m.group(1) if m else None


def codigo_base(codigo):
    """"ITA100" de THOPEN-ITA100: o pedaço que a usina, os ativos sem prefixo e o Registro mestre têm em comum."""
    achados = re.findall(r"[A-Z]{3}\d{3}", canon(codigo))
    return achados[-1] if achados else None


def nome_curto(descricao):
    """"Thopen - Itajá 1 e 2 - RN" da descrição da foto, que vem com o endereço colado ("... - RN Fazenda Pricila ...")."""
    d = _txt(descricao)
    m = re.match(r"^(.*? - [A-Z]{2})(?=\s|$)", d)
    return m.group(1) if m else (d[:80] or None)


def cliente_do_nome(nome):
    """"Thopen" de "Thopen - Itajá 1 e 2 - RN" (o Fracttal nomeia a usina "Cliente - Usina - UF")."""
    n = _txt(nome)
    return (n.split(" - ")[0].strip() or None) if " - " in n else None


# ── o kWp do Registro mestre ──────────────────────────────────────────────────────────────────────────────────────────
def mwp(v):
    """A potência em MWp como número, ou None (vazia, zero, ou ilegível: o "0,,643" da Rodrigues II)."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        s = re.sub(r"\s+", "", str(v))
        if not re.fullmatch(r"\d+(?:[.,]\d+)?", s):
            return None
        x = float(s.replace(",", "."))
    return x if x == x and x > 0 else None


def kwp_do_registro(real, contratual):
    """(kWp, "real" | "contratual" | None): a real × 1.000; sem ela (vazia ou ilegível), a contratual × 1.000 (decisão do
    Levi, 20/10/2026); sem as duas, (None, None). Na Itajá: 2,596 MWp → 2.596 kWp, "real"."""
    for v, de in ((real, "real"), (contratual, "contratual")):
        x = mwp(v)
        if x is not None:
            return round(x * 1000, 3), de
    return None, None


def _como_dict(x, cab):
    return dict(zip(cab, x)) if isinstance(x, (list, tuple)) else dict(x or {})


CAB_DE_PARA = ("usina_id", "sistema", "chave_externa", "casou_por")
ABA_DE_PARA = "de_para"


def _nome_chave(s) -> str:
    """Nome para casar: sem acento, sem caixa, espaços únicos ("Pharma  II" ≡ "pharma ii")."""
    import unicodedata
    t = unicodedata.normalize("NFKD", _txt(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().upper()


def kwp_por_nome(usinas, de_para, nomes) -> dict:
    """{nome: kWp do Registro mestre} para os `nomes` (as usinas da aba Equipamentos do BD_Performance) que casam com UMA
    usina do Registro pelo de-para do Nexus (qualquer sistema) ou pelo nome do próprio Registro. A reserva da potência da
    disponibilidade (22/10/2026: as Pharma II, III e IV sem potência na aba saíam da conta). Nome que casa com duas
    usinas, ou usina sem kWp no Registro, fica de fora: nunca chutar."""
    kwp = {}
    for x in usinas or ():
        d = _como_dict(x, CAB_USINAS)
        uid = _int(d.get("usina_id"))
        if uid is None or _txt(d.get("excluido")).lower() == "sim":
            continue
        k, _ = kwp_do_registro(d.get("potencia_real"), d.get("potencia_contratual"))
        if k:
            kwp[uid] = (k, _nome_chave(d.get("nome")))
    ids_por_nome = {}
    for uid, (_, nome) in kwp.items():
        ids_por_nome.setdefault(nome, set()).add(uid)
    for x in de_para or ():
        d = _como_dict(x, CAB_DE_PARA)
        uid = _int(d.get("usina_id"))
        if uid in kwp and _txt(d.get("chave_externa")):
            ids_por_nome.setdefault(_nome_chave(d.get("chave_externa")), set()).add(uid)
    out = {}
    for n in nomes or ():
        ids = ids_por_nome.get(_nome_chave(n)) or set()
        if len(ids) == 1:
            out[n] = kwp[next(iter(ids))][0]
    return out


def registro(usinas, clientes=()) -> list:
    """As usinas do Registro mestre para a tela: {usina_id, codigo, nome, status, kwp, kwp_de, cliente}. Sem as excluídas."""
    nomes = {}
    for x in clientes or ():
        d = _como_dict(x, CAB_CLIENTES)
        if _int(d.get("cliente_id")) is not None and _txt(d.get("excluido")).lower() != "sim":
            nomes[_int(d["cliente_id"])] = _txt(d.get("nome")) or None
    out = []
    for x in usinas or ():
        d = _como_dict(x, CAB_USINAS)
        uid = _int(d.get("usina_id"))
        if uid is None or _txt(d.get("excluido")).lower() == "sim":
            continue
        kwp, de = kwp_do_registro(d.get("potencia_real"), d.get("potencia_contratual"))
        out.append({"usina_id": uid, "codigo": _txt(d.get("codigo")) or None, "nome": _txt(d.get("nome")),
                    "status": _txt(d.get("status")) or None, "kwp": kwp, "kwp_de": de,
                    "cliente": nomes.get(_int(d.get("cliente_id")))})
    out.sort(key=lambda u: (u["nome"].lower(), u["usina_id"]))
    return out


# ── a árvore ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _montar(cabines, inversores, cabine_pelo_pai):
    """A árvore no formato da rota. `cabines` = {chave: {codigo, ...}}; `inversores` = [{codigo, descricao, ...}];
    `cabine_pelo_pai(inv)` = a chave da cabine subindo pelos pais, ou None. Sem cabine acima, o número do código (INVR2.x →
    a CABN2 desta usina, se houver UMA); sem as duas, `sem_cabine`."""
    por_numero = {}
    for k, c in cabines.items():
        por_numero.setdefault(numero_cabine(c["codigo"]), []).append(k)
    filhos = {k: [] for k in cabines}
    sem = []
    for inv in inversores:
        item = {"codigo": inv["codigo"], "nome": nome_inversor(inv["codigo"]) or inv["codigo"],
                "descricao": inv.get("descricao") or None}
        k, por = cabine_pelo_pai(inv), "pai"
        if k not in filhos:
            ks = por_numero.get(bloco_do_inversor(inv["codigo"])) or []
            k, por = (ks[0], "codigo") if len(ks) == 1 else (None, None)
        if k is None:
            sem.append(item)
        else:
            filhos[k].append(dict(item, cabine_por=por))
    saida = []
    for k, c in sorted(cabines.items(), key=lambda kv: natural(kv[1]["codigo"])):
        saida.append({"codigo": c["codigo"], "nome": nome_cabine(c["codigo"]) or c["codigo"],
                      "inversores": sorted(filhos[k], key=lambda i: natural(i["codigo"]))})
    return saida, sorted(sem, key=lambda i: natural(i["codigo"]))


class Foto:
    """A dimensão de equipamento indexada UMA vez por leitura do banco (22,5 mil membros; montar a árvore a cada pedido
    seria trabalho pesado no processo web, que trava todos)."""

    def __init__(self, linhas):
        self.membros, self.por_codigo, self.filhos = {}, {}, {}
        for x in linhas or ():
            d = _como_dict(x, CAB_EQUIP)
            eid, cod = _int(d.get("equipamento_id")), canon(d.get("codigo"))
            if eid is None or not cod:
                continue
            self.membros[eid] = {"id": eid, "codigo": cod, "descricao": _txt(d.get("descricao")) or None,
                                 "usina_id": _int(d.get("usina_id")), "familia": _txt(d.get("familia")).upper(),
                                 "pai_id": _int(d.get("pai_id")), "na_foto": _int(d.get("na_foto")) == 1,
                                 "foto_em": _txt(d.get("foto_em")) or None}
            self.por_codigo[cod] = eid
        for m in self.membros.values():
            if m["pai_id"] in self.membros and m["pai_id"] != m["id"]:
                self.filhos.setdefault(m["pai_id"], []).append(m["id"])
        self.raizes = {m["codigo"]: m["id"] for m in self.membros.values() if m["familia"] == "USINA"}
        self.foto_em = max((m["foto_em"] for m in self.membros.values() if m["foto_em"] and m["na_foto"]), default=None)
        # cada membro na usina dele: primeiro descendo pelos filhos de cada raiz...
        self.usina_de = {}
        for cod, rid in self.raizes.items():
            fila = [rid]
            while fila:
                eid = fila.pop()
                if eid in self.usina_de:
                    continue
                self.usina_de[eid] = cod
                fila.extend(self.filhos.get(eid, ()))
        # ...e o que não desce de raiz nenhuma (fora da foto: a THPN-PHS100, que o PCM gravou sem pai) pelo código: a
        # usina que o código carrega, ou a ÚNICA raiz com o mesmo código-base (CGU100-INVR1.1 → THOPEN-CGU100). Com duas
        # (IPX100 é da 2C e da Thopen) não liga: vira uma usina à parte, pelo próprio código, como a PHS100.
        por_base = {}
        for cod in self.raizes:
            por_base.setdefault(codigo_base(cod), []).append(cod)
        self.virtuais = set()
        for m in self.membros.values():
            if m["id"] in self.usina_de or m["familia"] not in ("CABN", "INVR"):
                continue
            s = site(m["codigo"])
            if not s:
                continue
            if s in self.raizes:
                dono = s
            elif len(por_base.get(codigo_base(s), ())) == 1:
                dono = por_base[codigo_base(s)][0]
            else:
                dono = s
                self.virtuais.add(s)
            self.usina_de[m["id"]] = dono
        self.por_usina = {}
        for eid, cod in self.usina_de.items():
            self.por_usina.setdefault(cod, []).append(eid)
        # o cliente das usinas fora da foto, pelo prefixo do código (THPN → Thopen), como as raízes da foto dizem
        votos = {}
        for cod, rid in self.raizes.items():
            cli = cliente_do_nome(nome_curto(self.membros[rid]["descricao"]))
            pre = cod.split("-")[0] if "-" in cod else None
            if cli and pre:
                votos.setdefault(pre, {}).setdefault(cli, 0)
                votos[pre][cli] += 1
        self._cliente_do_prefixo = {p: max(v, key=v.get) for p, v in votos.items()}

    def achar(self, codigo):
        """O código da usina na foto: o exato e, sem ele, a ÚNICA usina com o mesmo código-base (ITA100 → THOPEN-ITA100;
        a Athon chama a usina pelo código, "MAB100"). Ambíguo ou ausente: None."""
        c = canon(codigo)
        if c in self.raizes or c in self.virtuais:
            return c
        base = codigo_base(c)
        achadas = [u for u in set(self.raizes) | self.virtuais if base and codigo_base(u) == base]
        return achadas[0] if len(achadas) == 1 else None

    def _nome(self, cod):
        rid = self.raizes.get(cod)
        return (nome_curto(self.membros[rid]["descricao"]) if rid is not None else None) or cod

    def _cliente(self, cod):
        nome = self._nome(cod)
        return cliente_do_nome(nome) or self._cliente_do_prefixo.get(cod.split("-")[0] if "-" in cod else "")

    def _da_familia(self, cod, familia):
        return [self.membros[e] for e in self.por_usina.get(cod, ()) if self.membros[e]["familia"] == familia]

    def fora_da_foto(self, cod) -> bool:
        """A usina não está inteira na foto: a raiz não está (a PHS100), ou alguma cabine ou inversor dela entrou na
        dimensão só pelo código (sem foto, sem pai, sem descrição)."""
        rid = self.raizes.get(cod)
        if rid is None or not self.membros[rid]["na_foto"]:
            return True
        return any(not m["na_foto"] for f in ("CABN", "INVR") for m in self._da_familia(cod, f))

    def usinas(self) -> list:
        """As usinas da foto com as cabines (montadas uma vez: a lista é a mesma até a próxima leitura do banco)."""
        if getattr(self, "_usinas", None) is not None:
            return self._usinas
        out = []
        for cod in sorted(set(self.raizes) | self.virtuais, key=natural):
            rid = self.raizes.get(cod)
            cabs = sorted(self._da_familia(cod, "CABN"), key=lambda m: natural(m["codigo"]))
            out.append({"codigo": cod, "nome": self._nome(cod), "cliente": self._cliente(cod),
                        "usina_id": self.membros[rid]["usina_id"] if rid is not None else None,
                        "cabines": [{"codigo": m["codigo"], "nome": nome_cabine(m["codigo"]) or m["codigo"]} for m in cabs],
                        "fonte": "foto"})
        self._usinas = out
        return out

    def arvore(self, cod):
        """A árvore da usina pela foto, ou None se o código não é usina da foto."""
        if cod not in self.raizes and cod not in self.virtuais:
            return None
        cabines = {m["id"]: m for m in self._da_familia(cod, "CABN")}

        def subir(inv):
            eid, passos = inv["pai_id"], 0
            while eid in self.membros and passos < 20:
                if eid in cabines:
                    return eid
                eid, passos = self.membros[eid]["pai_id"], passos + 1
            return None
        cabs, sem = _montar(cabines, self._da_familia(cod, "INVR"), subir)
        rid = self.raizes.get(cod)
        datas = [self.membros[e]["foto_em"] for e in self.por_usina.get(cod, ()) if self.membros[e]["foto_em"]]
        return {"codigo": cod, "nome": self._nome(cod), "cliente": self._cliente(cod),
                "usina_id": self.membros[rid]["usina_id"] if rid is not None else None,
                "cabines": cabs, "sem_cabine": sem, "fonte": "foto", "foto_em": max(datas) if datas else None,
                "fora_da_foto": self.fora_da_foto(cod)}


def arvore_do_fracttal(cod, ent) -> dict:
    """A árvore lida no Fracttal (`BuscaFracttal`), no mesmo formato da foto."""
    nos = {n["codigo"]: n for n in ent.get("nos") or ()}
    cabines = {c: n for c, n in nos.items() if "-CABN" in c}

    def subir(inv):
        c, passos = inv.get("pai"), 0
        while c in nos and passos < 20:
            if c in cabines:
                return c
            c, passos = nos[c].get("pai"), passos + 1
        return None
    invs = [n for c, n in nos.items() if "-INVR" in c]
    cabs, sem = _montar(cabines, invs, subir)
    raiz = ent.get("raiz") or {}
    return {"codigo": cod, "nome": raiz.get("nome") or cod, "cliente": raiz.get("cliente"), "usina_id": None,
            "cabines": cabs, "sem_cabine": sem, "fonte": "fracttal", "lido_em": ent.get("lido_em")}


def usinas_fracttal(foto, lidas) -> list:
    """As usinas da foto com as que o Fracttal já devolveu por cima (a PHS100 ganha o nome e as cabines de hoje)."""
    por = {u["codigo"]: u for u in (foto.usinas() if foto else [])}
    for cod, ent in (lidas or {}).items():
        if not ent.get("existe"):
            continue
        a = arvore_do_fracttal(cod, ent)
        antes = por.get(cod) or {}
        por[cod] = {"codigo": cod, "nome": a["nome"], "cliente": a["cliente"] or antes.get("cliente"),
                    "usina_id": antes.get("usina_id"),
                    "cabines": [{"codigo": c["codigo"], "nome": c["nome"]} for c in a["cabines"]],
                    "fonte": "fracttal", "lido_em": ent.get("lido_em")}
    return sorted(por.values(), key=lambda u: ((u["cliente"] or "~").lower(), (u["nome"] or "").lower(), u["codigo"]))


# ── leitores em fundo ─────────────────────────────────────────────────────────────────────────────────────────────────
class LivroEmFundo:
    """Um livro do banco servido sem prender o pedido: a cópia que já existe (memória, senão a última boa em disco) e a
    leitura nova numa thread quando ela vence. Só a 1ª leitura da máquina, sem cópia nenhuma, espera um pouco
    (`espera_s`): a dimensão de equipamento são 23 páginas de 1.000 linhas no banco."""

    def __init__(self, leitor, espera_s: float = 20.0, falha_s: float = 60.0):
        self.leitor, self.espera_s, self.falha_s = leitor, espera_s, falha_s
        self._t = None
        self._tentou = 0.0
        self._lock = threading.Lock()

    def _ler(self):
        try:
            self.leitor.linhas()
        except Exception as e:                                  # noqa: BLE001 — a leitura em fundo nunca derruba nada
            print(f"[de-para] leitura de {self.leitor.livro} · {self.leitor.aba}: {type(e).__name__}: {e}")

    def _disparar(self):
        with self._lock:
            if self._t is None or not self._t.is_alive():
                self._t = threading.Thread(target=self._ler, daemon=True, name=f"livro-{self.leitor.aba}")
                self._t.start()
            return self._t

    def carregando(self) -> bool:
        return bool(self._t is not None and self._t.is_alive())

    def linhas(self):
        """(linhas ou None, carregando, lido_em)."""
        linhas, lido = self.leitor.sem_rede()
        if self.leitor.vencida():
            sem_nada = linhas is None
            # sem cópia nenhuma e a última tentativa acabou de falhar (o banco fora): não prende o pedido de novo
            if not (sem_nada and time.time() - self._tentou < self.falha_s):
                self._tentou = time.time()
                t = self._disparar()
                if sem_nada:
                    t.join(self.espera_s)
                    linhas, lido = self.leitor.sem_rede()
        return linhas, self.carregando(), lido


def _dados(d):
    if not d:
        return []
    x = d.get("data") if isinstance(d, dict) else d
    if isinstance(x, dict):
        return [x]
    return x if isinstance(x, list) else []


def _desc_fracttal(it):
    """A descrição sem o "{ CÓDIGO }" que o Fracttal cola no fim."""
    return _txt(str(it.get("description") or "").split("{")[0]) or None


def _nome_fracttal(it):
    """O nome curto do ativo (o `field_1`: "Cabine 2", "Thopen - Pharmas 2, 3 e 4 - PR"), senão a descrição."""
    return _txt(it.get("field_1")) or _desc_fracttal(it)


def _cliente_fracttal(it):
    """O cliente pelo caminho ("// Thopen/ Thopen - Pharmas.../ "), senão pelo nome."""
    partes = [p.strip() for p in str(it.get("parent_description") or "").strip().strip("/").split("/") if p.strip()]
    return partes[0] if partes else cliente_do_nome(_nome_fracttal(it))


def agora_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class BuscaFracttal:
    """A árvore de uma usina lida no próprio Fracttal, para as que a foto de 22/09 não tem (a THPN-PHS100, a Apolo, a Faro).

    Como o Fracttal guarda o parque (sondado ao vivo em 20/10/2026 para o protótipo): `items/{código}` dá o ativo, e
    `items/?location_code=<código do pai>` dá os filhos DIRETOS (o `location_code` de cada ativo é o código do pai). Filtro
    que o Fracttal não conhece devolve o catálogo inteiro sem erro (23.018 ativos): todo pedido confere o `total`. Desce só
    pelos LOCAIS (`id_type_item` 1: usina, cabine, SKID, QGBT); o inversor (equipamento) aparece como filho do QGBT.

    Um pedido por segundo (`espaco_s`), uma usina de cada vez, numa thread só; o resultado fica 7 dias em disco
    (`caminho`). O pedido da tela nunca espera: quem pede recebe a foto com `pendente` e a árvore nova no pedido seguinte.
    Falhou (cota, rede, árvore grande demais): não tenta de novo por `falha_s`, e a tela diz o motivo."""

    VALE_S = 7 * 86400
    CATALOGO_MIN = 20000            # o catálogo sem filtro tinha 23.018 ativos (20/10/2026)
    MAX_PEDIDOS = 150               # a Pharmas leva ~20; árvore maior que isto não é uma usina

    def __init__(self, caminho, pedir, ligado=lambda: True, espaco_s: float = 1.05, falha_s: float = 120.0,
                 relogio=time.time, dormir=time.sleep):
        self.caminho, self.pedir, self.ligado = caminho, pedir, ligado
        self.espaco_s, self.falha_s, self.relogio, self.dormir = espaco_s, falha_s, relogio, dormir
        self._lock = threading.Lock()
        self._fila, self._na_fila, self._falhas = [], set(), {}
        self._dados = None
        self._t = None
        self._ultimo = 0.0

    # o disco
    def _carregar(self):
        if self._dados is None:
            try:
                with open(self.caminho, encoding="utf-8") as f:
                    self._dados = (json.load(f) or {}).get("arvores") or {}
            except Exception:                                   # noqa: BLE001 — sem arquivo = nada lido ainda
                self._dados = {}
        return self._dados

    def _gravar(self):
        tmp = self.caminho + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"versao": 1, "arvores": self._dados}, f, ensure_ascii=False)
        os.replace(tmp, self.caminho)

    def entrada(self, cod):
        """A árvore lida há menos de 7 dias, ou None."""
        with self._lock:
            ent = self._carregar().get(canon(cod))
        return ent if ent and self.relogio() - float(ent.get("ts") or 0) < self.VALE_S else None

    def todas(self) -> dict:
        with self._lock:
            dados = dict(self._carregar())
        agora = self.relogio()
        return {c: e for c, e in dados.items() if agora - float(e.get("ts") or 0) < self.VALE_S}

    def falha(self, cod):
        f = self._falhas.get(canon(cod))
        return f[1] if f and self.relogio() - f[0] < self.falha_s else None

    def pendente(self, cod) -> bool:
        return canon(cod) in self._na_fila

    def pedir_arvore(self, cod) -> bool:
        """Põe a usina na fila (se precisa e se pode). True = a leitura está a caminho."""
        cod = canon(cod)
        if not cod or self.entrada(cod) is not None or self.falha(cod) or not self.ligado():
            return cod in self._na_fila
        with self._lock:
            if cod not in self._na_fila:
                self._na_fila.add(cod)
                self._fila.append(cod)
            if self._t is None or not self._t.is_alive():
                self._t = threading.Thread(target=self._rodar, daemon=True, name="depara-fracttal")
                self._t.start()
        return True

    def _rodar(self):
        while True:
            with self._lock:
                if not self._fila:
                    return
                cod = self._fila.pop(0)
            try:
                self.ler_agora(cod)
            except Exception as e:                              # noqa: BLE001 — a falha vira motivo, não queda
                self._falhas[cod] = (self.relogio(), f"{type(e).__name__}: {str(e)[:200]}")
                print(f"[de-para] árvore de {cod} no Fracttal: {type(e).__name__}: {e}")
            finally:
                with self._lock:
                    self._na_fila.discard(cod)

    def _get(self, ep, **params):
        falta = self.espaco_s - (self.relogio() - self._ultimo)
        if falta > 0:
            self.dormir(falta)
        self._ultimo = self.relogio()
        return self.pedir(ep, **params)

    def ler_agora(self, cod) -> dict:
        """Lê a árvore no Fracttal e grava no disco (a thread da fila chama; o teste chama direto)."""
        cod = canon(cod)
        pedidos = 1
        raiz = next(iter(_dados(self._get(f"items/{cod}"))), None)
        if not raiz or canon(raiz.get("code")) != cod:
            ent = {"existe": False, "ts": self.relogio(), "lido_em": agora_utc(), "pedidos": pedidos}
        else:
            nos, fila, vistos = [], [cod], {cod}
            while fila:
                pai, start = fila.pop(0), 0
                while True:
                    if pedidos >= self.MAX_PEDIDOS:
                        raise RuntimeError(f"árvore grande demais ({pedidos} pedidos ao Fracttal)")
                    d = self._get("items/", location_code=pai, limit=100, start=start)
                    pedidos += 1
                    pg = _dados(d)
                    total = d.get("total") if isinstance(d, dict) else None
                    if isinstance(total, (int, float)) and total >= self.CATALOGO_MIN:
                        raise RuntimeError(f"o Fracttal ignorou o filtro location_code (total {total} = o catálogo)")
                    for it in pg:
                        c = canon(it.get("code"))
                        if not c or c in vistos or canon(it.get("location_code")) != pai:
                            continue
                        vistos.add(c)
                        nos.append({"codigo": c, "nome": _nome_fracttal(it), "descricao": _desc_fracttal(it), "pai": pai,
                                    "tipo": it.get("id_type_item"), "ativo": it.get("active")})
                        if it.get("id_type_item") == 1:
                            fila.append(c)
                    start += len(pg)
                    if not pg or len(pg) < 100 or (isinstance(total, (int, float)) and start >= total):
                        break
            ent = {"existe": True, "ts": self.relogio(), "lido_em": agora_utc(), "pedidos": pedidos,
                   "raiz": {"codigo": cod, "nome": _nome_fracttal(raiz), "cliente": _cliente_fracttal(raiz)}, "nos": nos}
        with self._lock:
            self._carregar()[cod] = ent
            try:
                self._gravar()
            except Exception as e:                              # noqa: BLE001 — sem disco, fica na memória
                print(f"[de-para] cópia das árvores do Fracttal não gravada: {e}")
        self._falhas.pop(cod, None)
        return ent
