# -*- coding: utf-8 -*-
"""Empacota a PLATAFORMA DE PERFORMANCE (app.py, porta 5050) em deploy/oem-app.zip p/ a T.I
INSTALAR DO ZERO (ou atualizar) o servidor. Regras:
  - ENTRA: código (app.py, dashboard_thopen.py — IMPORTADO pelo app p/ gerencial/carteiras,
    tracker_watch.py, ronda_guardian.py), templates/, static/, docs/ (o /v2 lê docs/redesign),
    data/ (BD_Thopen + planilhas Copel/Matrix/Polaris), BD_Performance.xlsx (fallback local),
    trackers_garantia.json (referência curada), requirements.txt, .env.example, o README.md de
    instalação (deploy/README.md → raiz do zip) E o tokens.txt (credenciais consolidadas, p/ o
    app subir já autenticado — é o ÚNICO segredo no pacote; entregar por canal seguro).
  - FICA DE FORA: os segredos ANTIGOS espalhados (.env, sunop_token.txt/axis_token.txt/plat_token.txt,
    se_credentials.txt, pg_password.txt, whats_ronda.json — todos superados pelo tokens.txt),
    ESTADO de runtime do servidor (caches, ufv_state, tracker_issues, trk_eventos, whats_log… —
    o update NÃO pode sobrescrever o estado de lá), tooling local (bats/ps1 da máquina do Levi,
    MonitorRonda.exe, coletores), testes e pastas de suporte.
Uso: python deploy/_package_oem.py   (gera deploy/oem-app.zip — CONTÉM tokens.txt, tratar como sigiloso)"""
import os
import zipfile

DEPLOY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(DEPLOY)                      # raiz do projeto (o script vive em deploy/)
OUT = os.path.join(DEPLOY, "oem-app.zip")
README_DEPLOY = os.path.join(DEPLOY, "README.md")   # vira README.md na RAIZ do zip

# diretórios ignorados em qualquer nível
SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", ".pytest_cache", ".mypy_cache",
             ".claude", "os_creator", "build", "dist", "node_modules",
             "tests", "backups", "logs", "deploy", "referencia"}
# arquivos exatos ignorados
SKIP_FILES = {
    # segredos — NUNCA entram
    ".env", "se_credentials.txt", "pg_password.txt",
    "sunop_token.txt", "axis_token.txt", "plat_token.txt", "se_cookie.txt",
    "whats_ronda.json",                       # token do serviço + ids de grupo + telefone
    # ESTADO de runtime (o servidor mantém o dele; o app reconstrói o que faltar)
    "cache_snapshot.json", "owen_accum.json", "spv_stringbox.json",
    "ufv_state.json", "tracker_issues.json", "trk_eventos.json",
    "whats_log.json", "whats_enviados.json", "tunnel_url.txt",
    "string_notas.json", "fracttal_index.json", "frac_osperf_index.json",
    # tooling LOCAL da máquina do Levi (não é do servidor)
    "MonitorRonda.exe", "Monitor da Ronda.bat", "Rodar Ronda Agora.bat", "rodar_ronda.ps1",
    "Compartilhar Dashboard.bat", "subir_tunel.ps1",
    "Atualizar Nuvem.bat", "atualizar_nuvem.ps1", "Iniciar Dashboards.bat",
    # coletores rodam na máquina local (alimentam os BDs), não no servidor
    "collect_energy.py", "coletar_geracao_hoje.py",
    # infra de teste / meta
    "conftest.py", "pytest.ini", "run_tests.bat", "requirements-dev.txt", ".gitignore",
    "README.md",                              # o do repo — substituído pelo README de atualização
    "oem-app.zip", "_package_oem.py",
}
SKIP_EXT = {".log", ".out", ".tmp", ".pyc", ".zip", ".exe"}


def incluir(rel):
    base = os.path.basename(rel)
    if base in SKIP_FILES:
        return False
    _, ext = os.path.splitext(base)
    if ext.lower() in SKIP_EXT:
        return False
    return True


def main():
    if not os.path.exists(README_DEPLOY):
        raise SystemExit("deploy/README.md não existe — escreva o guia de atualização antes de empacotar.")
    if os.path.exists(OUT):
        os.remove(OUT)
    incluidos, total = [], 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(README_DEPLOY, "README.md")           # guia da T.I na raiz do zip
        incluidos.append(("README.md", os.path.getsize(README_DEPLOY)))
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT)
                if not incluir(rel):
                    continue
                z.write(full, rel)
                sz = os.path.getsize(full)
                incluidos.append((rel, sz)); total += sz
    print(f"oem-app.zip: {len(incluidos)} arquivos | descompactado {total/1e6:.1f} MB | "
          f"zip {os.path.getsize(OUT)/1e6:.1f} MB")
    print("\n--- conteúdo (top-level + tamanhos) ---")
    top = {}
    for rel, sz in incluidos:
        head = rel.split(os.sep)[0]
        top.setdefault(head, [0, 0]); top[head][0] += 1; top[head][1] += sz
    for head in sorted(top):
        n, sz = top[head]
        print(f"  {head:<34} {n:>4} arq  {sz/1e6:>7.2f} MB")
    # tokens.txt é o ÚNICO segredo que PODE entrar (é o objetivo do pacote de instalação).
    tem_tokens = any(os.path.basename(r) == "tokens.txt" for r, _ in incluidos)
    print("\n[SEGREDO INTENCIONAL] tokens.txt " +
          ("INCLUÍDO — o app sobe já autenticado; ENTREGAR POR CANAL SEGURO." if tem_tokens
           else "AUSENTE — rode build_tokens ou o app subirá sem credenciais (fontes 'indisponíveis')."))
    # trava de segurança: nenhum OUTRO nome suspeito de segredo pode ter entrado
    suspeitos = [r for r, _ in incluidos if any(s in r.lower() for s in
                 (".env", "token", "senha", "password", "credential", "cookie", "whats_ronda"))
                 and not r.endswith(".env.example") and "autocapture" not in r
                 and os.path.basename(r) != "tokens.txt"     # o segredo intencional (acima)
                 and not r.startswith("docs" + os.sep)]      # docs citam "token" no NOME (instruções, sem segredo)
    if suspeitos:
        print("[ALERTA] OUTROS possíveis segredos no zip (revisar!):", suspeitos)
    else:
        print("[OK] fora o tokens.txt, nenhum outro segredo entrou (.env.example é o único 'env').")


if __name__ == "__main__":
    main()
