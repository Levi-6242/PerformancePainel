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
porta = 5075
[caminhos]
cache_dir = "cache"
"""
ENV = "POWERPLANTS_DSN=postgresql://l:l@h/powerplants\nSUNOP_API_TOKEN=abc\nGRIDCO_SQL_TOKEN=def\nGEMEO_SENHA=s\n"


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
    assert cfg.db_caminho.name == "gemeo.sqlite" and cfg.powerplants_dsn.startswith("postgresql://l:l")
    assert cfg.sunop_token == "abc" and cfg.senha_app == "s"
    assert cfg.cache_dir == (d / "cache").resolve()


def test_segredo_ausente_nomeia_a_chave(tmp_path):
    d = _monta(tmp_path, env="SUNOP_API_TOKEN=x\n")
    with pytest.raises(SegredoAusente) as e:
        carregar(d / "config.toml", secrets_dir=d)
    assert "GRIDCO_SQL_TOKEN" in str(e.value) and "GEMEO_SENHA" in str(e.value)


def test_caminho_do_banco_vem_do_toml_do_env_ou_do_padrao(tmp_path, monkeypatch):
    d = _monta(tmp_path)
    monkeypatch.delenv("GEMEO_DB_CAMINHO", raising=False)
    assert carregar(d / "config.toml", secrets_dir=d).db_caminho.parts[-3:] == ("GridCo", "gemeo", "gemeo.sqlite")
    (d / "config.toml").write_text(TOML + '[db]\ncaminho = "%s"\n' % str(d / "x.sqlite").replace("\\", "/"), encoding="utf-8")
    assert carregar(d / "config.toml", secrets_dir=d).db_caminho == d / "x.sqlite"
    (d / "gemeo.env").write_text(ENV + "GEMEO_DB_CAMINHO=%s\n" % str(d / "y.sqlite").replace("\\", "/"), encoding="utf-8")
    assert carregar(d / "config.toml", secrets_dir=d).db_caminho == d / "y.sqlite"
    monkeypatch.setenv("GEMEO_DB_CAMINHO", str(d / "z.sqlite"))
    assert carregar(d / "config.toml", secrets_dir=d).db_caminho == d / "z.sqlite"


def test_publicar_tem_padrao_e_le_do_toml(tmp_path):
    d = _monta(tmp_path)
    cfg = carregar(d / "config.toml", secrets_dir=d)
    assert cfg.publicar_ativo is True and cfg.publicar_workbook == "gemeo_digital" and cfg.publicar_dias == 90
    (d / "config.toml").write_text(TOML + '[publicar]\nativo = false\nworkbook = "gemeo_homolog"\ndias = 30\n', encoding="utf-8")
    cfg = carregar(d / "config.toml", secrets_dir=d)
    assert cfg.publicar_ativo is False and cfg.publicar_workbook == "gemeo_homolog" and cfg.publicar_dias == 30


def test_config_e_imutavel(tmp_path):
    d = _monta(tmp_path)
    cfg = carregar(d / "config.toml", secrets_dir=d)
    with pytest.raises(Exception):
        cfg.teto_sunop_dia = 1  # type: ignore[misc]
