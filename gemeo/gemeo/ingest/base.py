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
    esperadas: int = 0


class Disjuntor:
    """Abre por `pausa_s` segundos. Enquanto aberto, o ciclo nem chama a fonte — insistir na borda da
    SunOp so alimenta o bloqueio (403 CloudFront = rate limit da conta, nao token)."""
    def __init__(self, pausa_s: float = 90.0):
        self.pausa_s, self._ate, self.motivo = pausa_s, 0.0, ""
    def aberto(self) -> bool:
        return time.time() < self._ate
    def abrir(self, motivo: str) -> None:
        self._ate, self.motivo = time.time() + self.pausa_s, motivo


class Ingestor(ABC):
    fonte: str = "?"

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
            marca = self._db.marca_dagua(self.conn, u.id)
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
            cob = min(1.0, n / b.esperadas) if b.esperadas else 1.0
            ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim,
                                                     status="ok" if cob >= 0.9 else "parcial", n_linhas=n,
                                                     n_requisicoes=b.n_requisicoes, duracao_s=time.time() - t0, cobertura=cob))
        return ids
