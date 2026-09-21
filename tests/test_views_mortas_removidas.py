# -*- coding: utf-8 -*-
"""Views mortas removidas em 19/09/2026 (Levi: "queria remover o lixo").

Cada uma foi condenada por evidência, não por impressão: nenhum arquivo do repositório aponta para
ela E existe a versão que a substituiu. O teste existe para elas não voltarem por engano num merge.

**O que NÃO foi removido, e por quê** — vale mais que a lista do que saiu:

- `/ronda/monitor`: zero links e arquivo parado desde 25/07, passaria em qualquer varredura
  automática de código morto. Mas o `Monitor da Ronda.bat` abre essa URL com `--app=` — o "app do
  monitor no PC do Levi" É esta página. Só ela consome `/api/ronda/whats/qr|reiniciar|status`, que
  é como se reconecta o WhatsApp quando a sessão cai.
- `/v2`, `/teste`, `/teste/<nivel>`: redirecionamentos 302 de quatro linhas, mantidos de propósito
  para quem guardou link antigo.
- `/api/tunnel-url`: parece órfã porque o OS Creator saiu deste repositório em 28/08 — ele consome.
"""
import app

REMOVIDAS = ("/teste-layout", "/antigo")


def test_rotas_mortas_nao_voltam():
    regras = {str(r.rule) for r in app.app.url_map.iter_rules()}
    for rota in REMOVIDAS:
        assert rota not in regras, f"{rota} foi removida em 19/09/2026 e não deve voltar"


def test_o_monitor_da_ronda_continua_de_pe():
    """O `.bat` que o Levi usa como aplicativo aponta para cá; derrubar a rota quebra o atalho dele
    e tira os controles de reconexão do WhatsApp."""
    regras = {str(r.rule) for r in app.app.url_map.iter_rules()}
    assert "/ronda/monitor" in regras
    for api in ("/api/ronda/whats/qr", "/api/ronda/whats/status", "/api/ronda/whats/reiniciar"):
        assert api in regras, f"{api} é usada só pelo Monitor da Ronda e não pode sumir junto"


def test_os_atalhos_de_link_antigo_continuam():
    """Redirecionamentos de bookmark custam 4 linhas e quebram favorito de gente se saírem."""
    regras = {str(r.rule) for r in app.app.url_map.iter_rules()}
    for rota in ("/v2", "/teste", "/teste/<nivel>"):
        assert rota in regras


def test_o_front_jinja_antigo_nao_existe_mais():
    """`templates/index.html` era o Monitoramento em Jinja (360 KB), substituído pelo design novo que
    o `/monitoramento` serve como HTML cru. Nenhum arquivo do repositório apontava para `/antigo`.

    Antes de apagar eu conferi a amarra que quase segurou: o `os_creator/MOVIDO.md` dizia que o deep
    link `gridos://` saía do index.html. Ele vive no design novo (3 ocorrências) — a integração com o
    OS Creator não depende deste arquivo. O MOVIDO.md foi corrigido no mesmo commit."""
    from pathlib import Path
    tpl = Path(app.__file__).parent / "templates" / "index.html"
    assert not tpl.exists(), "index.html voltou; ele foi removido em 19/09/2026"


def test_o_deep_link_do_os_creator_continua_no_front_atual():
    """Trava a razão pela qual o index.html pôde sair: quem manda `gridos://` é o design novo."""
    from pathlib import Path
    novo = Path(app.__file__).parents[1] / "docs" / "redesign" / "Monitoramento (novo design).html"
    assert novo.exists() and "gridos://" in novo.read_text(encoding="utf-8", errors="ignore")
