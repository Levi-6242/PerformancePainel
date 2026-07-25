# worker.py — o processo que faz o trabalho pesado da plataforma.
#
# POR QUE ELE EXISTE
# Até 25/07/2026 o reaquecimento dos caches (APIs, PostgreSQL, planilhas) rodava dentro do
# mesmo processo do servidor web. Como pandas e openpyxl são Python puro, eles seguram o GIL
# quase o tempo todo: enquanto um ciclo rodava, as 16 threads do waitress ficavam famintas.
# Medido: com um rebuild em curso, endpoints que respondem em 2–7 ms passavam de 2.900 ms —
# até 1085x mais lentos. E o ciclo completo (>4 min) é MAIS LONGO que o TTL de 5 min do cache,
# então o servidor vivia reconstruindo: quase todo usuário caía na janela ruim.
#
# A divisão: este processo reconstrói e PUBLICA o resultado no cache_snapshot.json; o app.py
# apenas lê esse arquivo e serve. Nenhum trabalho pesado no caminho de uma requisição.
#
# COMO RODAR (os dois precisam estar de pé)
#   pythonw worker.py     ← este, o que reconstrói
#   pythonw app.py        ← o servidor, porta 5050
# O guardião (ronda_guardian.py) mantém ambos vivos.
#
# ATENÇÃO: a RONDA do WhatsApp roda AQUI, e só pode existir em um processo. Nunca suba dois
# workers, e nunca rode o app.py com GRIDCO_SOLO=1 ao mesmo tempo que um worker — seriam dois
# laços de ronda, e o grupo recebe a mensagem duplicada.
import os
import sys
import time

import app


def main():
    print("[worker] carregando estado do disco...")
    app._carregar_estado_do_disco()

    print("[worker] iniciando os laços de fundo (prewarm, ronda, persistência, backfills)")
    app._iniciar_loops_de_fundo()

    print("[worker] no ar. Publica em:", app._PERSIST_PATH)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    if os.environ.get("GRIDCO_SOLO", "") == "1":
        print("[worker] GRIDCO_SOLO=1 está ligado: o app.py já faz tudo sozinho. "
              "Subir este worker junto duplicaria a ronda. Saindo.")
        sys.exit(1)
    main()
