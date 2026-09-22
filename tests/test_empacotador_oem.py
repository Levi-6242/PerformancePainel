# -*- coding: utf-8 -*-
"""O filtro do `deploy/_package_oem.py` contra SUFIXO COMPOSTO (21/09/2026).

Terceira aparição da mesma classe de bug nesta semana, e as três vezes o mecanismo foi idêntico:
um filtro que casa a EXTENSÃO EXATA não vê `algo.ext.marcador`.

  28/07  `plat_token.txt.migrado` entrou no zip — `splitext` dá `.migrado`, não `.txt`.
         Remendo da época: acrescentar `.migrado` à lista. Tratou o caso, não a classe.
  20/09  `Monitoramento (novo design).html.bak-acomp` (0,22 MB) e `.bak-alveslima` entraram:
         `splitext` dá `.bak-acomp`, e a lista só tinha `.bak`.
  21/09  `whats_ronda.json.bak_20260916_143840` não era ignorado pelo git — o `.gitignore`
         tinha o nome exato. Esse carregava o token do serviço e os ids dos grupos.

Aqui o filtro passa a olhar CADA segmento pontuado do nome, não só o último. O teste inclui os
casos reais das três vezes, e os negativos que impedem a correção de comer arquivo legítimo
(`backup.py` começa com "bak" e NÃO pode ser barrado)."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "_pkg_oem", Path(__file__).parents[1] / "plataforma" / "deploy" / "_package_oem.py")
pkg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pkg)


def test_sufixo_composto_nao_entra_no_pacote():
    """Os três casos reais, pelo nome que eles tinham no disco."""
    for nome in ("docs/redesign/Monitoramento (novo design).html.bak-acomp",
                 "docs/redesign/Monitoramento (novo design).html.bak-alveslima",
                 "plataforma/plat_token.txt.migrado",
                 "plataforma/whats_ronda.json.bak_20260916_143840",
                 "plataforma/cloudflared_tunnel.log.residual-2607",
                 "plataforma/tunel_guardian.ps1.bak-zumbi",
                 "plataforma/cloudflared_5050.log.morreu-1316",
                 "plataforma/cloudflared_5050.log.antes-011022",
                 "plataforma/cloudflared_5050.log.anterior"):
        assert not pkg.incluir(nome.replace("/", "\\")), f"{nome} não pode entrar no zip"


def test_o_filtro_nao_come_arquivo_legitimo():
    """A correção olha segmento por segmento; sem a regra do separador, `backup.py` cairia junto
    (começa com "bak") e o pacote sairia sem código."""
    for nome in ("plataforma/app.py", "plataforma/qualidade.py", "plataforma/backup.py",
                 "plataforma/BD_Performance.xlsx", "plataforma/trackers_garantia.json",
                 "docs/redesign/Entrada.html",
                 "docs/redesign/Monitoramento (novo design).html",
                 "plataforma/templates/painel_usina_v2.html",
                 "plataforma/static/notif.js", "plataforma/CLAUDE.md"):
        assert pkg.incluir(nome.replace("/", "\\")), f"{nome} PRECISA entrar no zip"
