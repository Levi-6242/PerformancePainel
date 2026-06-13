# BD_Performance via SharePoint (Microsoft Graph + Sites.Selected)

O dashboard lê o `BD_Performance.xlsx` direto do SharePoint pela Microsoft Graph API,
sem depender do OneDrive sincronizado da máquina (que desidrata o arquivo e quebra o
cadastro). A permissão usada é **`Sites.Selected`**: o app só enxerga o site que o TI
liberar explicitamente — não tem acesso a mais nada do tenant. É o modelo de menor
privilégio que existe no Graph para SharePoint, e por isso o mais fácil de aprovar.

Enquanto as variáveis `AZ_*`/`GRAPH_*` não estiverem no `.env`, nada muda: o app
continua usando o OneDrive/cópia local. O Graph é aditivo e tem fallback automático
(se o sync falhar por mais de 1 h, volta pro OneDrive sozinho).

## Como funciona no app

- `_graph_loop()` (thread de fundo) checa o **eTag** do arquivo a cada 5 min — se não
  mudou, não baixa nada; se mudou, baixa para `BD_Performance_sharepoint.xlsx`.
- O download muda o mtime do arquivo → a recarga automática de cadastro/metas
  (`maybe_reload_equipamentos`) já existente faz o resto.
- `_bd_perf_path()` prioriza: (1) cópia do SharePoint com sync saudável,
  (2) OneDrive sincronizado, (3) cópia local.

## Passo 1 — Registrar o app no Azure AD (quem tiver acesso ao portal)

1. [portal.azure.com](https://portal.azure.com) → **Microsoft Entra ID** →
   **Registros de aplicativo** → **Novo registro**.
2. Nome: `Dashboard OM - BD Performance` (qualquer nome). Tipo de conta:
   *Somente este diretório organizacional*. Sem redirect URI. → **Registrar**.
3. Anote o **ID do aplicativo (cliente)** → `AZ_CLIENT_ID` e o
   **ID do diretório (locatário)** → `AZ_TENANT_ID`.
4. **Certificados e segredos** → **Novo segredo do cliente** (validade 24 meses).
   Copie o **Valor** na hora (só aparece uma vez) → `AZ_CLIENT_SECRET`.
5. **Permissões de API** → **Adicionar permissão** → **Microsoft Graph** →
   **Permissões de aplicativo** → marcar **`Sites.Selected`** → Adicionar.
6. Ainda em Permissões de API: **Conceder consentimento de administrador** —
   este clique exige um admin do tenant (é parte do pedido pro TI abaixo).

## Passo 2 — Pedido pro TI (copiar e colar)

> **Assunto:** Consentimento Sites.Selected + acesso de leitura a 1 site do SharePoint
>
> Registrei o aplicativo **Dashboard OM - BD Performance**
> (client ID: `<COLAR AZ_CLIENT_ID>`) no Azure AD para o dashboard de O&M ler a
> planilha BD_Performance.xlsx direto do SharePoint, em vez do OneDrive sincronizado.
>
> O app usa a permissão **`Sites.Selected`** do Microsoft Graph — ou seja, **não tem
> acesso a nada do tenant** até que um site específico seja liberado, e a liberação é
> só de **leitura** de **um único site**. Preciso de duas coisas:
>
> 1. **Conceder consentimento de administrador** à permissão `Sites.Selected` do app
>    (Entra ID → Registros de aplicativo → Dashboard OM - BD Performance →
>    Permissões de API → "Conceder consentimento de administrador").
>
> 2. **Liberar leitura do site do O&M para o app**, via Graph (Graph Explorer ou
>    PowerShell, por um admin do SharePoint):
>
>    ```
>    POST https://graph.microsoft.com/v1.0/sites/{SITE-ID}/permissions
>    Content-Type: application/json
>
>    {
>      "roles": ["read"],
>      "grantedToIdentities": [{
>        "application": {
>          "id": "<COLAR AZ_CLIENT_ID>",
>          "displayName": "Dashboard OM - BD Performance"
>        }
>      }]
>    }
>    ```
>
>    O `{SITE-ID}` é obtido com:
>    `GET https://graph.microsoft.com/v1.0/sites/gridco.sharepoint.com:/sites/<NOME-DO-SITE>`
>
>    Equivalente em PowerShell (módulo PnP): 
>    `Grant-PnPAzureADAppSitePermission -AppId <AZ_CLIENT_ID> -DisplayName "Dashboard OM - BD Performance" -Site <URL do site> -Permissions Read`

## Passo 3 — Descobrir host/site/caminho do arquivo

Abra o BD_Performance no SharePoint pelo navegador e olhe a URL:

```
https://gridco.sharepoint.com/sites/OeM/Documentos%20Compartilhados/6.Gerencial/...
        └── GRAPH_SITE_HOST ┘└ GRAPH_SITE_PATH ┘└──────── GRAPH_FILE_PATH ────────┘
```

- `GRAPH_SITE_HOST` = `gridco.sharepoint.com`
- `GRAPH_SITE_PATH` = `/sites/OeM` (o que vier entre o host e a biblioteca)
- `GRAPH_FILE_PATH` = caminho do arquivo **dentro** da biblioteca de documentos
  (sem o nome da biblioteca), ex.:
  `6.Gerencial/4. Gestão à vista/1. Banco de Dados/BD_Performance.xlsx`

Se a pasta da equipe for sincronizada de um site de Teams, o nome do site costuma
aparecer no Explorer como o primeiro nível depois de "GRID CO" — ex.:
`Grid Co_ - 4. O&M` → site provavelmente `/sites/GridCo-4OM` ou similar; confirme
pela URL no navegador.

## Passo 4 — Preencher o `.env` e validar

```ini
AZ_TENANT_ID=...
AZ_CLIENT_ID=...
AZ_CLIENT_SECRET=...
GRAPH_SITE_HOST=gridco.sharepoint.com
GRAPH_SITE_PATH=/sites/OeM
GRAPH_FILE_PATH=6.Gerencial/4. Gestão à vista/1. Banco de Dados/BD_Performance.xlsx
```

Reinicie o servidor e confira o console:

- `` [graph] sync do BD_Performance via SharePoint ativado `` → credenciais lidas
- `` [graph] BD_Performance baixado do SharePoint (XXXX KB) `` → fim a fim OK
- `` [graph] sync falhou (...) `` → ver tabela de erros abaixo

| Erro no log | Causa provável |
|---|---|
| `401`/`invalid_client` no login.microsoftonline.com | `AZ_CLIENT_SECRET` errado/expirado (usar o **Valor**, não o ID do segredo) |
| `403` ao resolver o site ou baixar | Consentimento não dado **ou** o site ainda não foi liberado pro app (Passo 2.2) |
| `404` ao resolver o site | `GRAPH_SITE_PATH` errado — confirmar pela URL do navegador |
| `404` ao baixar o arquivo | `GRAPH_FILE_PATH` errado — lembrar que NÃO inclui o nome da biblioteca |
