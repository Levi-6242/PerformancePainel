"""Observação escrita ao CONCLUIR uma OS de análise.

POR QUE É UM ARQUIVO LOCAL E NÃO VAI PARA O FRACTTAL: a API não tem método de edição de OS já
criada — só criar, cancelar, mudar status, sincronizar etiqueta e anexar arquivo (o mesmo motivo
que fez o histórico de chamados nascer fora do Fracttal; ver `chamado_log`). A rota do ANEXO foi
testada ao vivo na OS 10152 em 27/07 com os DOIS ids de tarefa que existem (55875684 do fluxo de
execução e 20878948 do fluxo de anexos): o upload responde `ok`, mas o arquivo não volta em
`get_os_anexos` nem em `get_os_subtarefa_anexos`. Enquanto isso não for resolvido, a observação
não sai da máquina de quem escreveu — e é melhor guardar do que perder.

LIMITAÇÃO QUE PRECISA ESTAR CLARA PARA QUEM USA: cada analista tem a própria instalação, então
esta observação NÃO é vista pelos colegas. É registro pessoal, não comunicação de equipe.
"""
import json
import os
from datetime import datetime

_ARQ = "perf_notas_conclusao.json"
_CACHE = {"path": None, "dados": None, "mtime": 0}


def _caminho():
    try:
        import api
        return os.path.join(api._data_dir(), _ARQ)
    except Exception:
        return os.path.join(os.path.expanduser("~"), _ARQ)


def _ler():
    p = _caminho()
    try:
        m = os.path.getmtime(p)
    except OSError:
        return {}
    if _CACHE["path"] == p and _CACHE["mtime"] == m:
        return _CACHE["dados"]
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        d = d if isinstance(d, dict) else {}
    except Exception:
        d = {}
    _CACHE.update({"path": p, "dados": d, "mtime": m})
    return d


def adicionar(folio, texto, autor="") -> bool:
    """Guarda a observação da conclusão de UMA OS. Devolve False se não houver texto."""
    texto = (texto or "").strip()
    if not texto or not folio:
        return False
    d = dict(_ler())
    d.setdefault(str(folio), []).append({
        "quando": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "autor": (autor or "").strip(), "texto": texto})
    p = _caminho()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        return False
    _CACHE["mtime"] = 0                     # força reler na próxima
    return True


def entradas(folio) -> list:
    return list(_ler().get(str(folio or ""), []))


def resumo(folio) -> str:
    """Texto pronto p/ tooltip: uma linha por observação, mais recente por último."""
    return "\n".join("%s — %s" % (e.get("quando", ""), e.get("texto", ""))
                     for e in entradas(folio))
