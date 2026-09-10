# -*- coding: utf-8 -*-
"""Empacota o DASHBOARD THOPEN (porta 5080, produto do cliente) em deploy/thopen-app.zip.

POR QUE EXISTE, SE O DEPLOY É POR GIT: Railway e Render puxam o repositório (railway.toml e
render.yaml na raiz). Este zip é para quando alguém precisa instalar à mão — T.I., outro
provedor, ou um servidor sem acesso ao GitHub. O conteúdo é o MESMO que a nuvem usaria, e o
layout também: `thopen/` mais os arquivos de raiz, porque o startCommand faz `--chdir thopen`.

O QUE ENTRA — o app são três arquivos (~105 KB), como dizem os comentários do railway.toml:
  thopen/dashboard_thopen.py, thopen/fonte_api.py, thopen/templates/dashboard_thopen.html
mais requirements-thopen.txt (só flask+openpyxl+gunicorn; o requirements.txt da raiz arrasta
pandas/numpy/matplotlib da plataforma) e os dois arquivos de configuração de nuvem.

O QUE NÃO ENTRA, E POR QUÊ:
  • GRIDCO_SQL_TOKEN / tokens.txt — SEGREDO. O railway.toml e o render.yaml dizem, cada um em
    duas linhas, que ele vai nas Variables do painel e nunca no repositório. Um zip circula por
    e-mail e chat; o token não pode circular junto. Sem ele o app SOBE e não lê nada.
  • thopen/data/ (5 MB de planilha) — desde 28/08/2026 o dashboard não abre arquivo nenhum.
    Mandar um BD_Thopen de julho para o servidor só convida alguém a achar que é a fonte.
  • cache_bd_thopen.json.gz — é a última leitura boa DESTA máquina; o servidor faz a dele.
  • .bat/.ps1/logs do túnel — tooling local do Levi, não do servidor.

Uso: python thopen/deploy/_package_thopen.py
"""
import hashlib
import os
import zipfile

DEPLOY = os.path.dirname(os.path.abspath(__file__))          # thopen/deploy
THOPEN = os.path.dirname(DEPLOY)                             # thopen/
ROOT = os.path.dirname(THOPEN)                               # raiz do repositório
OUT = os.path.join(DEPLOY, "thopen-app.zip")

# caminho no repositório -> caminho dentro do zip
ITENS = [
    ("thopen/dashboard_thopen.py",              "thopen/dashboard_thopen.py"),
    ("thopen/fonte_api.py",                     "thopen/fonte_api.py"),
    ("thopen/templates/dashboard_thopen.html",  "thopen/templates/dashboard_thopen.html"),
    ("requirements-thopen.txt",                 "requirements-thopen.txt"),
    ("railway.toml",                            "railway.toml"),
    ("render.yaml",                             "render.yaml"),
]

LEIAME = """# Dashboard Thopen — instalação

O app são três arquivos. Tudo que ele mostra vem da Gridco Performance API (PostgreSQL);
ele NÃO abre planilha nenhuma.

## Subir

    pip install -r requirements-thopen.txt
    gunicorn dashboard_thopen:app --chdir thopen --bind 0.0.0.0:$PORT --workers 1 --timeout 180

No Windows, para testar, `python thopen/dashboard_thopen.py` sobe na 5080 (gunicorn é só Linux).

## Variáveis de ambiente

    GRIDCO_SQL_TOKEN   OBRIGATÓRIA e SECRETA. Não está neste pacote de propósito — preencha no
                       painel do provedor (Railway: Variables; Render: Environment). Sem ela o
                       app sobe e não lê nada.
    GRIDCO_API_BASE    opcional, padrão https://app.gridco.com.br/db_performace
    GRIDCO_API_TTL     opcional, padrão 600 (segundos de cache antes de reler o banco)
    GRIDCO_API_CACHE   opcional. Cache em disco da última leitura boa — o que segura a tela se
                       a API cair. Em disco efêmero ele se perde a cada restart; aponte para um
                       volume persistente se quiser que sobreviva.
    GRIDCO_API_IGNORA  opcional, abas a esconder do seletor, separadas por ";" (as `zz*` já são
                       ignoradas por regra).

## --workers 1

Cada worker carrega o BD_Thopen inteiro em memória (pico medido: 334 MB). Em tier de 512 MB,
dois workers estouram.
"""


def main():
    falta = [o for o, _ in ITENS if not os.path.exists(os.path.join(ROOT, o))]
    if falta:
        raise SystemExit("nao achei no repositorio: %s" % falta)

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for origem, destino in ITENS:
            z.write(os.path.join(ROOT, origem), destino)
        z.writestr("README.md", LEIAME)

    with zipfile.ZipFile(OUT) as z:
        nomes = z.namelist()
        bruto = sum(z.getinfo(n).file_size for n in nomes)
        # trava de seguranca: se um segredo entrar aqui um dia, o build para
        for n in nomes:
            if os.path.basename(n).lower() in ("tokens.txt", ".env", "pg_password.txt",
                                               "se_credentials.txt", "tokens_runtime.json"):
                raise SystemExit("SEGREDO no pacote: %s — abortei" % n)
            if "GRIDCO_SQL_TOKEN=" in z.read(n).decode("utf-8", "ignore"):
                raise SystemExit("token embutido em %s — abortei" % n)

    h = hashlib.sha256(open(OUT, "rb").read()).hexdigest()
    print("thopen-app.zip: %d arquivos | descompactado %.1f KB | zip %.1f KB"
          % (len(nomes), bruto / 1024, os.path.getsize(OUT) / 1024))
    for n in sorted(nomes):
        print("   %-44s %7d" % (n, z.getinfo(n).file_size if n in nomes else 0))
    print("sha256: %s" % h)
    print("[OK] nenhum segredo no pacote — GRIDCO_SQL_TOKEN vai no painel do provedor.")
    print("gerado em: %s" % OUT)


main()
