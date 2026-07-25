# OS Creator

App de **desktop** (PyQt6) que cria e acompanha Ordens de Serviço no **Fracttal**. É o único
projeto do repositório que não é web e que já era autocontido: tem `app.py`, `main.py` e
`requirements.txt` próprios. Ver o `CLAUDE.md` da raiz para as convenções gerais.

**Atenção ao nome:** o `app.py` desta pasta é o do OS Creator, **não** o da plataforma
(que fica em `plataforma/app.py`). O `from app import MainWindow` em `main.py` aponta para cá.

| Arquivo | Papel |
|---|---|
| `main.py` | Ponto de entrada (login + janela principal) |
| `app.py` | `MainWindow`, tema escuro (`DARK_QSS`), `LoginDialog` |
| `api.py` | Cliente do Fracttal (REST + RPC) |
| `cos_spec.py` | Regras do COS: tipos de OS e categorias |
| `steps/` | Uma tela por fluxo (performance, chamados, OS pai, detalhe, histórico) |
| `workers.py` | Threads de API — ver o cuidado abaixo |

## Cuidados

- **PyQt6 + threads derruba o app se feito errado.** Uma `QThread` sem referência viva é coletada
  pelo garbage collector e mata o processo. Use o padrão que já existe (`ApiWorker` + slot seguro);
  não crie thread solta.
- **Login é multiusuário**: cada pessoa entra com a própria conta (RPC `rpc/login_new`, senha em
  MD5). O REST e o RPC do Fracttal são autenticados de formas diferentes — não misture.
- `fracttal_login.txt` é credencial: não commite nem imprima.
- **Buildar fora do OneDrive** (o sync corrompe o PyInstaller). Use uma pasta local como
  `C:\GridcoBuild`, e distribua pelo instalador, não pelo `.exe` solto.
- Paginação da API do Fracttal corta em ~100 itens — sempre pagine.

## Deep link

A plataforma abre este app já preenchido via `gridos://` (ativo, OS pai e responsável). Se mudar
o formato do link, o lado da plataforma (`plataforma/app.py`) precisa acompanhar.
