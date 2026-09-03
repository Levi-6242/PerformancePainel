# gemeo/tests/test_core_config.py
"""config.toml + SECRETS_DIR/gemeo.env viram um Config congelado. Segredo faltando falha NOMEANDO
a chave — a plataforma perdeu horas em 25/07 com um token velho 'sequestrando' a renovação em
silêncio; aqui, ausência é erro em voz alta."""
from pathlib import Path
import pytest
from gemeo.core.config import carregar, SegredoAusente

TOML = """
[usinas]
piloto = ["MRO100", "Santarem 1"]
[ritmo_min]
pg = 15
sunop_fino = 15
sunop_lento = 60
cadastro = 30
modelar = 15
[sunop]
teto_dia = 600
lote = 600
janela = ["05:40", "18:20"]
[ingest]
sobreposicao_min = 30
[modelar]
grade_min = 15
[app]
porta = 5070
[caminhos]
cache_dir = "cache"
"""
ENV = "GEMEO_DB_DSN=postgresql://g:g@localhost/gemeo\nPOWERPLANTS_DSN=postgresql://l:l@h/powerplants\nSUNOP_API_TOKEN=abc\nGRIDCO_SQL_TOKEN=def\nGEMEO_SENHA=s\n"


def _monta(tmp_path, env=ENV):
    (tmp_path / "config.toml").write_text(TOML, encoding="utf-8")
    (tmp_path / "gemeo.env").write_text(env, encoding="utf-8")
    return tmp_path


def test_carrega_config_e_segredos(tmp_path):
    d = _monta(tmp_path)
    cfg = carregar(d / "config.toml", secrets_dir=d)
    assert cfg.usinas_piloto == ("MRO100", "Santarem 1")
    assert cfg.ritmo_min["sunop_lento"] == 60
    assert cfg.teto_sunop_dia == 600 and cfg.lote_pathnames == 600
    assert cfg.janela_solar == ("05:40", "18:20")
    assert cfg.db_dsn.startswith("postgresql://g:g")
    assert cfg.sunop_token == "abc" and cfg.senha_app == "s"
    assert cfg.cache_dir == (d / "cache").resolve()


def test_segredo_ausente_nomeia_a_chave(tmp_path):
    d = _monta(tmp_path, env="GEMEO_DB_DSN=x\n")
    with pytest.raises(SegredoAusente) as e:
        carregar(d / "config.toml", secrets_dir=d)
    assert "POWERPLANTS_DSN" in str(e.value)


def test_schema_vem_do_toml_do_env_ou_do_ambiente(tmp_path, monkeypatch):
    d = _monta(tmp_path)
    assert carregar(d / "config.toml", secrets_dir=d).db_schema == "gemeo"
    (d / "config.toml").write_text(TOML + '[db]\nschema = "digital_twins"\n', encoding="utf-8")
    assert carregar(d / "config.toml", secrets_dir=d).db_schema == "digital_twins"
    (d / "gemeo.env").write_text(ENV + "GEMEO_DB_SCHEMA=dt_homolog\n", encoding="utf-8")
    assert carregar(d / "config.toml", secrets_dir=d).db_schema == "dt_homolog"
    monkeypatch.setenv("GEMEO_DB_SCHEMA", "dt_env")
    assert carregar(d / "config.toml", secrets_dir=d).db_schema == "dt_env"


def test_schema_com_espaco_e_erro_em_voz_alta(tmp_path, monkeypatch):
    d = _monta(tmp_path)
    monkeypatch.setenv("GEMEO_DB_SCHEMA", "digital twins")
    with pytest.raises(ValueError):
        carregar(d / "config.toml", secrets_dir=d)


def test_config_e_imutavel(tmp_path):
    d = _monta(tmp_path)
    cfg = carregar(d / "config.toml", secrets_dir=d)
    with pytest.raises(Exception):
        cfg.teto_sunop_dia = 1  # type: ignore[misc]
