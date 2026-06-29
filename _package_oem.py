# -*- coding: utf-8 -*-
"""Empacota o dashboard em oem-app.zip para entrega ao TI.
Exclui: ambientes/cache, .git, logs, SEGREDOS (.env, credenciais e token caches),
o app desktop separado (os_creator), e o próprio zip/este script.
Uso: python _package_oem.py"""
import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "oem-app.zip")

# diretórios ignorados em qualquer nível
SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", ".pytest_cache", ".mypy_cache",
             ".claude", "os_creator", "build", "dist", "node_modules",
             "tests"}                     # testes não são runtime
# arquivos exatos ignorados (segredos + lixo + o que o app.py NÃO usa)
SKIP_FILES = {
    ".env", "oem-app.zip", "_package_oem.py",
    # segredos
    "se_credentials.txt", "pg_password.txt",
    "sunop_token.txt", "axis_token.txt", "plat_token.txt", "se_cookie.txt",
    # estado transitório (o app reconstrói sozinho)
    "owen_accum.json", "cache_snapshot.json", "spv_stringbox.json",
    # apps Flask SEPARADOS + seus templates (não são o app.py)
    "dashboard_thopen.py", "dashboard_geracao.py",
    "dashboard_thopen.html", "dashboard_geracao.html",
    # scripts de coleta standalone (NÃO importados pelo app.py)
    "collect_energy.py", "coletar_geracao_hoje.py",
    # xlsx auxiliares não lidos pelo app.py/tracker_watch
    "axis_inversores_sunop.xlsx", "trackers_inversores_pv.xlsx",
    # infra de teste / deploy Linux-Railway (não usado no Windows)
    "conftest.py", "pytest.ini", "run_tests.bat", "requirements-dev.txt",
    "Procfile", "railway.toml", ".gitignore",
    # .bat extras (mantém só "Iniciar Dashboard.bat")
    "Iniciar Dashboards.bat", "Compartilhar Dashboard.bat",
}
# extensões ignoradas
SKIP_EXT = {".log", ".out", ".tmp", ".pyc"}


def incluir(rel):
    base = os.path.basename(rel)
    if base in SKIP_FILES:
        return False
    _, ext = os.path.splitext(base)
    if ext.lower() in SKIP_EXT:
        return False
    if base.endswith(".log.out"):
        return False
    return True


def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    incluidos, total = [], 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
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
        top[head] = top.get(head, [0, 0]); top[head][0] += 1; top[head][1] += sz
    for head in sorted(top):
        n, sz = top[head]
        print(f"  {head:<34} {n:>4} arq  {sz/1e6:>7.2f} MB")


if __name__ == "__main__":
    main()
