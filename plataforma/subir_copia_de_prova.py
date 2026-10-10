"""Sobe uma CÓPIA DE PROVA da plataforma noutra porta: só o processo web, sem worker, sem ronda, sem fonte paga.

Por quê (porta única com o Nexus, 09/10/2026; Levi: "a partir de segunda quero o Nexus como link principal"): a 5050 do
PC é a ponte do OS Creator e nunca é reiniciada nem derrubada (CLAUDE.md da raiz). Para provar uma mudança, sobe-se o
código da worktree noutra porta, ao lado de uma cópia do Nexus (`ferramentas/subir_copia_de_prova.py` no repositório
do Nexus). O `app.py` fixa a 5050 no `__main__`; este arquivo faz o mesmo boot do modo WEB noutra porta.

O que esta cópia NÃO faz, de propósito:
- nada do `worker.py`: sem prewarm, sem coleta, sem ronda do WhatsApp, sem fechamento, sem backfill, sem `bd_api`
  (é o `_iniciar_loops_de_fundo`, que aqui nunca é chamado). Roda como o web do servidor: `_MODO_WEB = True`, e o `_swr`
  serve o que tem sem reconstruir; só os vigias de arquivo (snapshot, travas, cadastro) ficam ligados;
- nenhum pedido sai para a SunOp (`sunop.net`) ou a API PV (`pvoperation.com`), e nenhum pedido que não seja
  GET/HEAD/OPTIONS sai da máquina (gravação no Fracttal, na API db_performace, no Graph, no WhatsApp): a trava abaixo
  recusa com `ConnectionError`, que o código já trata como fonte fora do ar. Clique de "Atualizar"/drill que dependa
  delas mostra a falha, e é o esperado;
- não grava no estado da plataforma de verdade: `GRIDCO_CACHE_DIR` e `GRIDCO_DADOS_DIR` apontam para `--estado` (padrão:
  uma pasta no TEMP da máquina, por porta). `--copiar-estado-de` copia para lá o snapshot e o estado de outra pasta da
  plataforma (só leitura nela) para a cópia mostrar número; sem isso, as telas abrem vazias ("aquecendo").
As credenciais vêm do `.env` e do `tokens.txt` da raiz da worktree e do `plataforma/tokens_runtime.json` (copiados à
mão, gitignorados). A senha é a mesma `DASH_PASSWORD`: nunca imprima.

Cookie: o navegador separa cookie por HOST, não por porta. A cópia em 127.0.0.1:5150 e a 5050 em 127.0.0.1 dividem o
cookie `session` (a chave de assinatura sai da mesma senha); o Nexus em 127.0.0.1 também, até o passo 0 da porta única.
Use um perfil de navegador só da prova.

Uso, da raiz do repositório:
    python plataforma/subir_copia_de_prova.py --porta 5150
    python plataforma/subir_copia_de_prova.py --porta 5150 --copiar-estado-de "<pasta plataforma/ de outra cópia>"
    python plataforma/subir_copia_de_prova.py --porta 5150 --copiar-estado-de "<...>" --acompanhar   (número ao vivo)
"""
import argparse
import os
import shutil
import sys
import tempfile
import threading
from urllib.parse import urlsplit

AQUI = os.path.dirname(os.path.abspath(__file__))
FONTES_PAGAS = ("sunop.net", "pvoperation.com")
LOCAIS = ("127.0.0.1", "localhost", "::1")
METODOS_DE_LEITURA = ("GET", "HEAD", "OPTIONS")
# Estado que o app lê de _CACHE_DIR/_DADOS_DIR (`_p_cache`/`_p_dado`). Credencial nunca entra (tokens_runtime.json,
# *.txt): ela fica no lugar dela, na worktree.
ESTADO_EXTENSOES = (".json", ".jsonl", ".local.xlsx")
# O whats_ronda leva o token do serviço e os grupos; o log e os enviados da ronda, telefones e mensagens. A cópia não
# roda a ronda e não precisa de nenhum deles.
NUNCA_COPIAR_PREFIXOS = ("tokens_runtime", "whats_")


def motivo_da_recusa(metodo: str, url: str) -> str | None:
    """None = pode sair. Fonte paga sai nunca; para fora da máquina, só leitura."""
    host = (urlsplit(url).hostname or "").lower()
    if any(p in host for p in FONTES_PAGAS):
        return "fonte paga"
    if host and host not in LOCAIS and (metodo or "GET").upper() not in METODOS_DE_LEITURA:
        return "gravação fora da máquina"
    return None


def instalar_trava() -> None:
    """Antes de importar o app: tudo o que usa `requests` passa pelo HTTPAdapter.send, e o `bd_api` pelo urlopen."""
    import urllib.error
    import urllib.request

    import requests
    import requests.adapters

    enviar = requests.adapters.HTTPAdapter.send

    def send(self, pedido, *a, **k):
        motivo = motivo_da_recusa(pedido.method, pedido.url)
        if motivo:
            print(f"[cópia de prova] recusado ({motivo}): {pedido.method} {urlsplit(pedido.url).hostname}", flush=True)
            raise requests.exceptions.ConnectionError(f"cópia de prova: {motivo} recusada")
        return enviar(self, pedido, *a, **k)

    requests.adapters.HTTPAdapter.send = send
    abrir = urllib.request.urlopen

    def urlopen(pedido, *a, **k):
        url = pedido if isinstance(pedido, str) else pedido.full_url
        metodo = "GET" if isinstance(pedido, str) else pedido.get_method()
        motivo = motivo_da_recusa(metodo, url)
        if motivo:
            print(f"[cópia de prova] recusado ({motivo}): {metodo} {urlsplit(url).hostname}", flush=True)
            raise urllib.error.URLError(f"cópia de prova: {motivo} recusada")
        return abrir(pedido, *a, **k)

    urllib.request.urlopen = urlopen


def copiar_estado(origem: str, destino: str) -> int:
    n = 0
    for nome in sorted(os.listdir(origem)):
        caminho = os.path.join(origem, nome)
        if (os.path.isfile(caminho) and nome.endswith(ESTADO_EXTENSOES) and not nome.startswith(NUNCA_COPIAR_PREFIXOS)
                and "token" not in nome.lower()):
            shutil.copy2(caminho, os.path.join(destino, nome))
            n += 1
    return n


def acompanhar_snapshot(origem: str, destino: str, intervalo: int = 30) -> None:
    """Recopia o snapshot quando o worker da origem publica outro: o vigia do web (`_snapshot_watch_loop`) relê sozinho.
    É o que deixa comparar a cópia com a plataforma direta no mesmo minuto (prova da porta única, spec seção 9)."""
    import time
    fonte, alvo, marca = os.path.join(origem, "cache_snapshot.json"), os.path.join(destino, "cache_snapshot.json"), None
    while True:
        try:
            st = os.stat(fonte)
            if (st.st_mtime, st.st_size) != marca:
                shutil.copy2(fonte, alvo + ".tmp")
                os.replace(alvo + ".tmp", alvo)
                marca = (st.st_mtime, st.st_size)
        except OSError as e:
            print(f"[cópia de prova] snapshot não recopiado: {e}", flush=True)
        time.sleep(intervalo)


def main() -> None:
    p = argparse.ArgumentParser(description="Cópia de prova da plataforma noutra porta (só web, sem fonte paga).")
    p.add_argument("--porta", type=int, default=5150)
    p.add_argument("--estado", help="pasta do estado desta cópia (padrão: TEMP/plataforma-copia-de-prova-<porta>)")
    p.add_argument("--copiar-estado-de", help="pasta plataforma/ de onde copiar snapshot e estado (só leitura nela)")
    p.add_argument("--acompanhar", action="store_true",
                   help="com --copiar-estado-de: recopia o snapshot a cada 30 s quando a origem publicar outro")
    args = p.parse_args()
    if args.porta == 5050:
        sys.exit("A 5050 é a ponte do OS Creator e nunca reinicia: use outra porta.")

    estado = os.path.abspath(args.estado or os.path.join(tempfile.gettempdir(), f"plataforma-copia-de-prova-{args.porta}"))
    os.makedirs(estado, exist_ok=True)
    if args.copiar_estado_de:
        print(f"[cópia de prova] {copiar_estado(args.copiar_estado_de, estado)} arquivos de estado copiados", flush=True)
    os.environ["GRIDCO_CACHE_DIR"] = estado
    os.environ["GRIDCO_DADOS_DIR"] = estado
    instalar_trava()

    sys.path.insert(0, AQUI)
    import app as plataforma            # noqa: E402  (as cargas do cadastro rodam no import, como no servidor)

    plataforma._carregar_estado_do_disco()
    plataforma._MODO_WEB = True         # o mesmo do __main__ no modo normal: quem reconstrói é o worker, que aqui não há
    for alvo in (plataforma._snapshot_watch_loop, plataforma._tranc_watch_loop, plataforma._cadastro_watch_loop):
        threading.Thread(target=alvo, daemon=True).start()
    if args.copiar_estado_de and args.acompanhar:
        threading.Thread(target=acompanhar_snapshot, args=(args.copiar_estado_de, estado), daemon=True).start()
    from waitress import serve
    print(f"Plataforma (cópia de prova) em http://127.0.0.1:{args.porta}  estado: {estado}", flush=True)
    serve(plataforma.app, listen=f"127.0.0.1:{args.porta}", threads=16)


if __name__ == "__main__":
    main()
