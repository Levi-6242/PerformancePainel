# push_bases.py — empurra as planilhas para o servidor da plataforma.
#
# POR QUE EXISTE
# O PC dedicado roda 24h com uma porta aberta que a T.I. definiu. Sincronizar OneDrive numa
# máquina exposta é o que queremos evitar: se ela for comprometida, o invasor alcança as bases
# da empresa e o ransomware sobe para a nuvem junto. Então o servidor NÃO monta OneDrive — ele
# recebe as três planilhas por HTTPS, atrás da mesma senha do dashboard.
#
# ONDE RODA
# Na máquina que TEM o OneDrive (a do analista), pelo Agendador do Windows, de tempos em tempos.
# Envia só o que mudou (compara tamanho + data de modificação com o último envio), então rodar
# de 10 em 10 minutos é barato.
#
#   python push_bases.py --url https://<endereco-do-servidor>
#   python push_bases.py --url http://127.0.0.1:5050 --forcar     (testar tudo agora)
#
# A senha sai do DASH_PASSWORD do .env — a mesma do dashboard, nenhuma credencial nova.
import argparse
import json
import os
import sys

import requests

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_AQUI)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_RAIZ, ".env"))
except ImportError:
    pass

ESTADO = os.path.join(_AQUI, "push_bases_estado.json")

# (rótulo no endpoint, nome do arquivo, caminhos onde procurar no OneDrive)
_OD = os.path.join(os.path.expanduser("~"), "OneDrive - GRID CO")
_REL_PERF = os.path.join("Grid Co_ - 4. O&M", "6.Gerencial", "4. Gestão à vista",
                         "1. Banco de Dados", "BD_Performance.xlsx")
_REL_TICK = os.path.join("Grid Co_ - 4. O&M", "9.Pós Operação", "3. Análises de Performance",
                         "Tickets de Performance (atualizada).xlsx")
BASES = [
    ("bd_performance", [os.environ.get("BD_PERF_PATH"),
                        os.path.join(_OD, _REL_PERF),
                        os.path.join(_OD, "Área de Trabalho", _REL_PERF)]),
    ("bd_thopen",      [os.environ.get("BD_THOPEN_PATH"),
                        os.path.join(_OD, "Grid Co_ - 17. Acesso Externo Thopen",
                                     "1. Registro usinas Thopen", "BD_Thopen.xlsx"),
                        os.path.join(_OD, "BD_Thopen.xlsx")]),
    ("tickets",        [os.environ.get("TICKETS_PATH"),
                        os.path.join(_OD, _REL_TICK),
                        os.path.join(_OD, "Área de Trabalho", _REL_TICK)]),
]


def acha(cands):
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None


def carrega_estado():
    try:
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser(description="Envia as planilhas para o servidor da plataforma.")
    ap.add_argument("--url", required=True, help="ex.: https://painel.gridco.com.br")
    ap.add_argument("--forcar", action="store_true", help="envia mesmo se não mudou")
    args = ap.parse_args()
    raiz = args.url.rstrip("/")

    senha = os.environ.get("DASH_PASSWORD", "")
    s = requests.Session()
    if senha:
        r = s.post(raiz + "/login", data={"senha": senha}, timeout=60, allow_redirects=False)
        if r.status_code not in (200, 302):
            print(f"[push] login recusado (HTTP {r.status_code}) — confira DASH_PASSWORD")
            return 1

    estado, mudou, erros = carrega_estado(), 0, 0
    for nome, cands in BASES:
        origem = acha(cands)
        if not origem:
            print(f"[push] {nome}: não achei o arquivo nesta máquina — pulando")
            continue
        st = os.stat(origem)
        assinatura = f"{st.st_size}:{int(st.st_mtime)}"
        if not args.forcar and estado.get(nome) == assinatura:
            print(f"[push] {nome}: sem mudança")
            continue
        try:
            # lê tudo na memória: a planilha maior tem ~4 MB, e ler de uma vez evita
            # mandar um arquivo pela metade se o OneDrive estiver sincronizando no meio.
            with open(origem, "rb") as f:
                dados = f.read()
            r = s.post(f"{raiz}/api/admin/base/{nome}", data=dados, timeout=300,
                       headers={"Content-Type": "application/octet-stream"})
            if r.status_code == 200:
                j = r.json()
                print(f"[push] {nome}: enviada ({j.get('bytes', 0)/1024/1024:.1f} MB, "
                      f"{j.get('abas')} abas)")
                estado[nome] = assinatura
                mudou += 1
            else:
                print(f"[push] {nome}: RECUSADA (HTTP {r.status_code}) {r.text[:160]}")
                erros += 1
        except Exception as e:
            print(f"[push] {nome}: falhou — {type(e).__name__}: {str(e)[:120]}")
            erros += 1

    if mudou:
        try:
            with open(ESTADO, "w", encoding="utf-8") as f:
                json.dump(estado, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"[push] não consegui gravar o estado: {e}")
    print(f"[push] enviadas: {mudou} | erros: {erros}")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
