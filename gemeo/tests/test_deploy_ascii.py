# gemeo/tests/test_deploy_ascii.py
"""Os .ps1 do deploy sao ASCII puro: o PowerShell 5.1 le .ps1 sem BOM como ANSI e um acento num comentario
ja derruba o parse (aconteceu no deploy da plataforma). O teste trava a regra."""
from pathlib import Path


def test_ps1_do_deploy_sao_ascii():
    arquivos = list((Path(__file__).parents[1] / "deploy").glob("*.ps1"))
    assert {a.name for a in arquivos} >= {"instalar_tarefas.ps1", "backup.ps1"}
    for arq in arquivos:
        ruins = [i for i, b in enumerate(arq.read_bytes()) if b >= 128]
        assert not ruins, f"{arq.name}: byte nao-ASCII na posicao {ruins[0]}"
