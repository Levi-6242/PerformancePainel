# -*- coding: utf-8 -*-
"""Empacota o DASHBOARD THOPEN (porta 5080, produto do cliente) em deploy/thopen-app.zip.

POR QUE EXISTE, SE O DEPLOY É POR GIT: Railway e Render puxam o repositório (railway.toml e
render.yaml na raiz). Este zip é para quando alguém precisa instalar à mão — T.I., outro
provedor, ou um servidor sem acesso ao GitHub. O conteúdo é o MESMO que a nuvem usaria, e o
layout também: `thopen/` mais os arquivos de raiz, porque o startCommand faz `--chdir thopen`.

O QUE ENTRA — o app são treze arquivos (~270 KB), como dizem os comentários do railway.toml:
  thopen/dashboard_thopen.py, thopen/fonte_api.py, thopen/fonte_operacao.py, thopen/operacao_mes.py,
  thopen/rondas_cliente.py, thopen/fotos_ronda.py, thopen/contestacao.py, thopen/contestacao_banco.py,
  thopen/acessos.py, thopen/livro_banco.py, thopen/geracao_possivel.py, thopen/templates/dashboard_thopen.html,
  thopen/templates/entrar.html
(geracao_possivel desde 20/10/2026: a geração possível pelo IPOA da Visão Geral e do Diário)
(acessos + livro_banco + entrar.html desde 14/10/2026: o login por pessoa, com as contas do Nexus)
(rondas_cliente + fotos_ronda + contestacao desde 09/10/2026: a janela das rondas do card e a contestação do cliente;
contestacao_banco desde 13/10/2026: a contestação gravada no banco, cifrada, para o Nexus)
(fonte_operacao + operacao_mes desde 08/10/2026: a Operação no Mês do Diário. O dashboard os importa no topo — o
zip só com os três de antes nem subia; tests/test_thopen_operacao_rota.py confere ITENS contra os imports)
mais requirements-thopen.txt (só flask+openpyxl+gunicorn; o requirements.txt da raiz arrasta
pandas/numpy/matplotlib da plataforma) e os dois arquivos de configuração de nuvem.

O QUE NÃO ENTRA, E POR QUÊ:
  • GRIDCO_SQL_TOKEN / tokens.txt — SEGREDO. O railway.toml e o render.yaml dizem, cada um em
    duas linhas, que ele vai nas Variables do painel e nunca no repositório. Um zip circula por
    e-mail e chat; o token não pode circular junto. Sem ele o app SOBE e não lê nada.
  • thopen/data/ (5 MB de planilha) — desde 28/08/2026 o dashboard não abre arquivo nenhum.
    Mandar um BD_Thopen de julho para o servidor só convida alguém a achar que é a fonte.
  • cache_bd_thopen.json.gz e cache_operacao.json.gz — a última leitura boa DESTA máquina; o
    servidor faz a dele.
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
    ("thopen/fonte_operacao.py",                "thopen/fonte_operacao.py"),
    ("thopen/operacao_mes.py",                  "thopen/operacao_mes.py"),
    ("thopen/rondas_cliente.py",                "thopen/rondas_cliente.py"),
    ("thopen/fotos_ronda.py",                   "thopen/fotos_ronda.py"),
    ("thopen/contestacao.py",                   "thopen/contestacao.py"),
    ("thopen/contestacao_banco.py",             "thopen/contestacao_banco.py"),
    ("thopen/acessos.py",                       "thopen/acessos.py"),
    ("thopen/livro_banco.py",                   "thopen/livro_banco.py"),
    ("thopen/geracao_possivel.py",              "thopen/geracao_possivel.py"),
    ("thopen/templates/entrar.html",            "thopen/templates/entrar.html"),
    ("thopen/templates/dashboard_thopen.html",  "thopen/templates/dashboard_thopen.html"),
    ("requirements-thopen.txt",                 "requirements-thopen.txt"),
    ("railway.toml",                            "railway.toml"),
    ("render.yaml",                             "render.yaml"),
]

LEIAME = """# Dashboard Thopen — instalação

O app são treze arquivos (pasta thopen/). Tudo que ele mostra vem da Gridco Performance API
(PostgreSQL); ele NÃO abre planilha nenhuma.

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

Operação no Mês (card e tabela do Diário, de 10/2026 em diante; lê pela mesma API e o mesmo
GRIDCO_SQL_TOKEN, em segundo plano — a tela nunca espera essa leitura):

    THOPEN_OPERACAO        opcional. "0" desliga o card e a tabela por dia (o Diário volta ao de
                           antes de 10/2026); qualquer outro valor ou vazio = ligado.
    THOPEN_OPERACAO_TTL    opcional, padrão 600 (segundos entre uma releitura e outra)
    THOPEN_OPERACAO_CACHE  opcional. Arquivo da última leitura boa (padrão
                           thopen/cache_operacao.json.gz); a mesma observação do GRIDCO_API_CACHE
                           sobre disco efêmero.

Rondas do mês e dúvida do cliente (o ícone de imagem do card, de 10/2026 em diante). Os três
segredos abaixo NÃO estão no pacote: vão nas variáveis do provedor ou, no Windows, num .env na
raiz do clone (linhas NOME=valor, ao lado da pasta thopen/):

    THOPEN_RONDAS          opcional. "0" desliga a janela das rondas e as fotos.
    FRACTTAL_CLIENT_ID     SECRETA. A credencial da API do Fracttal (a mesma da plataforma): as
    FRACTTAL_CLIENT_SECRET fotos das rondas são os anexos das OS. Sem ela a janela mostra as
                           rondas e avisa que as fotos não estão disponíveis.
    THOPEN_TEAMS_PERFORMANCE  SECRETA. URL do fluxo do Teams do canal O&M > Performance (app
                           Workflows: "Enviar alertas de webhook para um canal"): recebe a contestação
                           de geração, string e tracker.
    THOPEN_TEAMS_COS          SECRETA. URL do fluxo do canal do COS: recebe a de disponibilidade e
                           desligamento (15/10/2026).
    THOPEN_TEAMS_ZELADORIA    SECRETA. URL do fluxo do canal O&M > Zeladoria: recebe a de ronda.
                           Item cujo canal não está configurado não aparece na tela.
    THOPEN_CONTESTACAO_CHAVE_PUBLICA  a chave PÚBLICA (X25519, base64) do Nexus: a contestação vai
                           também ao banco (livro thopen_contestacoes), com nome, contato e mensagem
                           cifrados; só o Nexus abre. Sem ela, não grava no banco (o Teams segue).
    GRIDCO_SQL_TOKEN       SECRETA. O token de escrita do banco (o tokens.txt da raiz serve): sem ele
                           a contestação não vai ao banco.

Login por pessoa (14/10/2026; as contas são criadas no Nexus, em Contratos e clientes → Acessos dos
clientes):

    THOPEN_LOGIN           "1" liga o login. Sem ela o painel segue público, como antes.
    THOPEN_PREFIXO         o caminho em que o painel é servido ("/performance" no servidor da T.I.).
    THOPEN_ACESSOS_CHAVE_PRIVADA  SECRETA. A chave privada do 5080 (X25519, base64): abre o nome e o
                           e-mail das contas e cifra as senhas. A PÚBLICA do par vai no Nexus (Base →
                           Chaves do Nexus). Sem a privada, ninguém entra.
    THOPEN_SESSAO_CHAVE    SECRETA. Assina o cookie da sessão (32+ caracteres aleatórios). Sem ela,
                           quem estava dentro entra de novo a cada reinício.
    THOPEN_COOKIE_SEGURO   "0" só para testar em http local (o padrão é o cookie só em HTTPS).

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


# Só como script (08/10/2026): o teste importa o módulo para conferir ITENS contra o que o dashboard importa, e o
# import não pode gerar o zip na pasta do repositório
if __name__ == "__main__":
    main()
