"""Dataclasses compartilhadas pelas tres pecas (ingest, modelar, app)."""
from dataclasses import dataclass, field

@dataclass(frozen=True)
class UsinaRef:
    id: int
    codigo: str          # "MRO100", "Santarem 1"
    fonte: str           # "pg" | "sunop" | "axis"
    fonte_ref: str       # pid no PG ("10") ou nome na SunOp ("MRO100")
    tz: str              # "America/Belem"
    kwp: float = 0.0
    kw_ac: float = 0.0
    lat: float | None = None
    lon: float | None = None

@dataclass(frozen=True)
class EquipRef:
    id: int
    usina_id: int
    tipo: str            # inversor | tracker | string | estacao | cabine
    codigo_fonte: str    # "INV_7", "TRK_17", "INV_7.I_PV3", "ESTM", "765"
    pai_id: int | None = None
    atributos: dict = field(default_factory=dict)   # numero, kwp, kw_ac, n_strings_esperadas...
