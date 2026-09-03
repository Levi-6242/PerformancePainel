# gemeo/gemeo/core/config.py
"""Configuração = config.toml (não-segredo, versionado) + SECRETS_DIR/gemeo.env (segredo, fora de
pasta sincronizada). Dois arquivos, dois donos — a mesma separação que a plataforma adotou depois de
o tokens.txt e o tokens_runtime.json se pisarem."""
from __future__ import annotations
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

SEGREDOS = ("SUNOP_API_TOKEN", "GRIDCO_SQL_TOKEN", "GEMEO_SENHA")
OPCIONAIS = ("POWERPLANTS_DSN", "GEMEO_DB_CAMINHO")   # POWERPLANTS so para usinas de fonte pg; caminho do SQLite tem padrao


class SegredoAusente(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    db_caminho: Path
    powerplants_dsn: str
    sunop_token: str
    bd_api_token: str
    senha_app: str
    usinas_piloto: tuple[str, ...]
    ritmo_min: dict[str, int]
    teto_sunop_dia: int
    lote_pathnames: int
    janela_solar: tuple[str, str]
    sobreposicao_min: int
    grade_min: int
    porta_app: int
    cache_dir: Path
    sunop_base: str = "https://gridco-api.sunop.net"
    bd_api_base: str = "https://app.gridco.com.br/db_performace"
    publicar_ativo: bool = True                 # ao fim do `gemeo modelar`, sincroniza o workbook da API da Performance
    publicar_workbook: str = "gemeo_digital"
    publicar_dias: int = 90                     # cascata_dia, perda_dia e evento: so os ultimos N dias vao para o workbook


def _ler_env(caminho: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not caminho.exists():
        return out
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        k, v = linha.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def carregar(caminho_config: Path | None = None, secrets_dir: Path | None = None) -> Config:
    caminho_config = Path(caminho_config or os.environ.get("GEMEO_CONFIG", "config.toml"))
    secrets_dir = Path(secrets_dir or os.environ.get("SECRETS_DIR", caminho_config.parent))
    t = tomllib.loads(caminho_config.read_text(encoding="utf-8"))
    env = {**_ler_env(secrets_dir / "gemeo.env"), **{k: v for k, v in os.environ.items() if k in SEGREDOS + OPCIONAIS}}
    faltam = [k for k in SEGREDOS if not env.get(k)]
    if faltam:
        raise SegredoAusente(f"faltam em {secrets_dir / 'gemeo.env'}: {', '.join(faltam)}")
    cache = Path(t.get("caminhos", {}).get("cache_dir", "cache"))
    if not cache.is_absolute():
        cache = (caminho_config.parent / cache)
    # banco: SQLite embutido (03/09/2026). Caminho: ambiente > gemeo.env > [db] caminho > %LOCALAPPDATA%/GridCo/gemeo — sempre
    # FORA de pasta sincronizada (OneDrive + SQLite = lock preso e arquivo subido pela metade)
    bruto = env.get("GEMEO_DB_CAMINHO") or t.get("db", {}).get("caminho") or ""
    if bruto:
        caminho_db = Path(os.path.expandvars(os.path.expanduser(bruto)))
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        caminho_db = Path(base) / "GridCo" / "gemeo" / "gemeo.sqlite"
    return Config(
        db_caminho=caminho_db, powerplants_dsn=env.get("POWERPLANTS_DSN", ""),
        sunop_token=env["SUNOP_API_TOKEN"], bd_api_token=env["GRIDCO_SQL_TOKEN"], senha_app=env["GEMEO_SENHA"],
        usinas_piloto=tuple(t["usinas"]["piloto"]), ritmo_min=dict(t["ritmo_min"]),
        teto_sunop_dia=int(t["sunop"]["teto_dia"]), lote_pathnames=int(t["sunop"]["lote"]),
        janela_solar=tuple(t["sunop"]["janela"]), sobreposicao_min=int(t["ingest"]["sobreposicao_min"]),
        grade_min=int(t["modelar"]["grade_min"]), porta_app=int(t["app"]["porta"]), cache_dir=cache.resolve(),
        publicar_ativo=bool(t.get("publicar", {}).get("ativo", True)),
        publicar_workbook=str(t.get("publicar", {}).get("workbook", "gemeo_digital")),
        publicar_dias=int(t.get("publicar", {}).get("dias", 90)),
    )
