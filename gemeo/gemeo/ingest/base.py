# gemeo/gemeo/ingest/base.py
"""Ingestor: um laco por fonte, com marca d'agua, disjuntor e o contrato ingest_run. Falha e dado."""
from __future__ import annotations
import datetime as dt
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from gemeo.core import db as _db_mod
from gemeo.core import tempo
from gemeo.core.modelos import UsinaRef


@dataclass
class Busca:
    leituras: list[tuple[int, str, dt.datetime, float]] = field(default_factory=list)
    n_requisicoes: int = 0


# ── O QUE "cobertura" PASSOU A SIGNIFICAR (Levi, 21/09/2026: "arruma o 480 de 480 do PG") ────────
# Ate aqui cada ingestor FABRICAVA um total esperado — `n_series x janela/300s` no PG, formulas
# parecidas nos outros — e o status saia de `n_escrito / esperado`. A conta supoe que toda serie
# reporta a cada 5 min, inclusive de madrugada e inclusive string que nao reporta nunca. Resultado
# medido em 21/09: **480 de 480 execucoes do PG marcadas "parcial"** com a fonte perfeitamente
# saudavel. Um rotulo que diz "parcial" sempre nao distingue nada — ensina a ignorar. E ja tinha
# gambiarra em volta: o `saude()` ignora 'parcial' de proposito ("so 'falha' acusa").
#
# A troca: em vez de adivinhar QUANTO deveria vir, medir QUAO NOVO e o que veio. O atraso da leitura
# mais recente contra o fim da janela e um numero que o gemeo SABE, sem supor nada da fonte.
#
# O corte de 180 min saiu de medicao, nao de gosto (21/09, 18 usinas do PG): as 13 saudaveis estavam
# todas em <= 83 min, e as 5 mudas em 743, 1213, 1213, 2728 e 2728 min — exatamente as que o /painel
# ja marcava SEM COMUNICACAO. Ha um fator 9 entre o pior saudavel e o melhor doente; 180 cai no meio,
# com folga de 2x para um lado e 4x para o outro.
ATRASO_OK_MIN = 180.0


def atraso_da_busca(leituras, fim: dt.datetime) -> float | None:
    """Minutos entre a leitura MAIS NOVA que veio e o fim da janela pedida. None se nada veio.

    Sai das proprias linhas: nenhuma consulta a mais, e mede o que interessa — se a fonte esta
    entregando o presente ou arrastando passado."""
    novos = [t for _, _, t, _ in (leituras or []) if t is not None]
    if not novos:
        return None
    return max(0.0, (fim - max(novos)).total_seconds() / 60.0)


def avaliar(leituras, fim: dt.datetime, tolerancia_min: float = ATRASO_OK_MIN) -> tuple[str, float]:
    """-> (status, cobertura). `cobertura` agora e FRESCOR: 1,0 = dado na borda da janela, 0 = no
    limite da tolerancia ou alem. Um numero so, com um significado so."""
    atraso = atraso_da_busca(leituras, fim)
    if atraso is None:
        return "falha", 0.0
    frescor = max(0.0, min(1.0, 1.0 - atraso / tolerancia_min)) if tolerancia_min > 0 else 1.0
    return ("ok" if atraso <= tolerancia_min else "parcial"), frescor


class Disjuntor:
    """Abre por `pausa_s` segundos. Enquanto aberto, o ciclo nem chama a fonte — insistir na borda da
    SunOp so alimenta o bloqueio (403 CloudFront = rate limit da conta, nao token)."""
    def __init__(self, pausa_s: float = 90.0):
        self.pausa_s, self._ate, self.motivo = pausa_s, 0.0, ""
    def aberto(self) -> bool:
        return time.time() < self._ate
    def abrir(self, motivo: str) -> None:
        self._ate, self.motivo = time.time() + self.pausa_s, motivo


# Sentinela de sensor com defeito: a estacao manda um numero impossivel em vez de "sem leitura". Cada fabricante
# escolheu o seu — -999 no PostgreSQL do Thopen (POA da Santarem 1 e 2, o dia inteiro) e -666 na SunOp (GHI da
# ESTM 1 da MAB100, que a propria plataforma ja pinta como erro). Gravar isso como irradiancia envenena o gate: a
# razao POA/GHI da Santarem saiu -0,46, o dia inteiro foi reprovado e o esperado do gemeo ficou em zero.
# Irradiancia negativa de verdade existe (offset termico do piranometro a noite), mas fica em poucos W/m2.
PISO_IRRADIANCIA = -20.0
MEDIDAS_IRRADIANCIA = ("poa", "ghi")


def valor_valido(medida: str, valor: float | None) -> bool:
    """False quando o valor e codigo de erro do sensor, e nao medida. Quem chama descarta a leitura."""
    if valor is None:
        return False
    return not (medida in MEDIDAS_IRRADIANCIA and valor < PISO_IRRADIANCIA)


class Ingestor(ABC):
    fonte: str = "?"
    tipos: tuple[str, ...] | None = None   # marca d'agua so destes tipos de equipamento (fonte que divide a usina com outra)
    atraso_ok_min: float = ATRASO_OK_MIN   # fonte com cadencia propria sobrescreve (ver o bloco acima)

    def __init__(self, cfg, conn, usinas: list[UsinaRef]):
        self.cfg, self.conn, self.usinas = cfg, conn, usinas
        self.disjuntor = Disjuntor()
        self._db = _db_mod           # trocavel nos testes

    @abstractmethod
    def descobrir(self, usina: UsinaRef) -> None: ...

    @abstractmethod
    def buscar(self, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime) -> Busca: ...

    def ciclo(self, agora: dt.datetime | None = None, reconciliar: bool = False) -> list[int]:
        agora = agora or dt.datetime.now(dt.timezone.utc)
        ids = []
        for u in self.usinas:
            t0 = time.time()
            marca = self._db.marca_dagua(self.conn, u.id, tipos=self.tipos) if self.tipos else self._db.marca_dagua(self.conn, u.id)
            ini, fim = tempo.janela(agora, marca, self.cfg.sobreposicao_min, reconciliar=reconciliar)
            if self.disjuntor.aberto():
                ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim,
                                                         status="falha", cobertura=0.0, erro=f"disjuntor aberto: {self.disjuntor.motivo}"))
                continue
            try:
                b = self.buscar(u, ini, fim)
            except Exception as e:                       # noqa: BLE001 — a fonte falhou; registra e segue
                ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim,
                                                         status="falha", cobertura=0.0, duracao_s=time.time() - t0,
                                                         erro=f"{type(e).__name__}: {e}"[:400]))
                continue
            if not b.leituras:
                ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim,
                                                         status="falha", n_requisicoes=b.n_requisicoes,
                                                         duracao_s=time.time() - t0, cobertura=0.0, erro="fonte devolveu vazio"))
                continue
            n = self._db.upsert_leituras(self.conn, b.leituras)
            # `n` conta o que foi INSERIDO, e a sobreposicao da janela faz boa parte ja existir —
            # mais um motivo para o status nao sair dele. Quem decide e o frescor do que veio.
            status, cob = avaliar(b.leituras, fim, self.atraso_ok_min)
            ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim,
                                                     status=status, n_linhas=n,
                                                     n_requisicoes=b.n_requisicoes, duracao_s=time.time() - t0, cobertura=cob))
        return ids
