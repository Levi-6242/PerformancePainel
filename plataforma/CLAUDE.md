# Plataforma de Performance + ronda de trackers

Flask na porta **5050**, uso interno (3 a 6 analistas). `app.py` tem ~17 mil linhas — **nunca
peça para lê-lo inteiro**; trabalhe por busca ou por trecho. Ver o `CLAUDE.md` da raiz para as
convenções gerais e a regra `_AQUI` × `_RAIZ`.

## Rodar e reiniciar

Python real desta máquina (NÃO use `python` puro — o alias do WindowsApps sobe um segundo
processo e você fica com dois `app.py` disputando a 5050):

```
C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\python.exe   # com log
C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe  # sem janela (normal)
```

Ritual, sempre nesta ordem:

1. `py -m py_compile app.py` — **nunca** reinicie sem compilar antes.
2. Matar **por CommandLine**, não por nome:
   `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*app.py*" }`.
   Confira quantos PIDs voltaram — **é comum aparecerem dois**; mate todos.
3. Esperar ~4 s e subir a partir desta pasta: `Start-Process pythonw app.py -WindowStyle Hidden`.
4. Confirmar com `GET http://127.0.0.1:5050/healthz` em laço (sobe em 4–10 s).

Para diagnosticar, suba com `python.exe -u` e `-RedirectStandardOutput` num `.log`: o prewarm
imprime o tempo de cada etapa, que é a forma mais rápida de achar lentidão.

**Não precisa de restart:** `docs/redesign/Monitoramento (novo design).html` (a página `/`),
`templates/relatorio.html`, `whats_ronda.json` e `plat_token.txt` — todos relidos a cada uso.
Qualquer `.py` ou os demais templates precisam.

**A ronda depende do guardião.** `ronda_guardian.py` roda pela Tarefa Agendada do Windows
"GridCo Ronda Guardian" e sobe o servidor se ele cair, para a ronda das 08:25/13:15 disparar.
A tarefa aponta para o caminho **desta pasta** — se mover o arquivo, atualize a tarefa, senão
a ronda morre em silêncio.

## Armadilhas que já custaram caro

- **Hooks do Flask parecem código morto.** `@app.before_request`, `@app.after_request` e rotas não
  têm chamador visível num scan estático. **Nunca remova** por "não é usado".
- **Ler `.xlsx` sempre de uma cópia.** O Excel/OneDrive tranca o arquivo (`Errno 13`). Use
  `_bd_readable_path()`, que copia uma vez por versão do arquivo. Não volte a copiar por chamada:
  o caminho temporário fixo permitia uma thread truncar o arquivo enquanto outra lia.
- **O schema `dbt` do banco congela.** É um pipeline da Thopen, não nosso. Quando congela, puxe das
  tabelas cruas `public.raw_*` (`raw_inverter`, `raw_tracker`, `raw_weather_station`): mesmo dado em
  `json_data`, hypertable indexada, ordens de grandeza mais rápido. Já foi feito para trackers, ETM,
  geração, PR e potência.
- **Fuso do banco:** `public.raw_*` é `timestamptz` (UTC); as views `dbt.*` são timestamp ingênuo em
  hora local. Converta sempre com `AT TIME ZONE 'America/Sao_Paulo'`. Filtro escrito sem isso pode
  **zerar o resultado silenciosamente** (aconteceu: "últimas 2 horas" caiu no futuro e voltou vazio).
- **Janela de tempo muda comportamento.** Ao filtrar "últimas N horas", lembre que usina muda há dias
  precisa continuar aparecendo para acender o alerta de falha de comunicação — senão ela some da
  tela em vez de alertar.
- **Trabalho pesado no processo web trava todos** (GIL). Um rebuild degrada os outros usuários em até
  1000×. Não coloque `pandas`/`openpyxl`/SQL longo no caminho de uma requisição.

## Arquitetura de cache (importante para desempenho)

Os dados vivem em cache na memória e são servidos em 2–4 ms. Quem reconstrói é o `_prewarm_loop`,
**dentro do mesmo processo** — e é aí que está o gargalo conhecido: um ciclo completo passa dos
5 minutos do TTL, então o servidor vive reconstruindo, e quem chega nessa janela espera.

`_cache_save`/`_cache_load` já persistem 21 caches em `cache_snapshot.json` (na raiz). A correção
estrutural planejada é mover o trabalho pesado para um processo separado, com o web só lendo —
o mecanismo de snapshot já existe para isso.

## Tokens

O token da Plataforma (trackers + combiner box) é **manual**: tem CAPTCHA e MFA, não auto-renova.
Vale **7 dias** (medido no `exp` do próprio JWT — o mesmo token serve trackers e combiner).
Quando vence, o combiner recebe `HTTP 401`; existe um disjuntor que abre no primeiro 401 e para
de tentar, em vez de repetir ~280 chamadas condenadas por ciclo. Status em `/api/tokens`.

**Como renovar:** bookmarklet de 1 clique, ou `POST /api/pv/trackers/token` com `{"token": "..."}`.
O `plat_token.txt` é relido a cada uso, então vale na hora, sem reiniciar. `_plat_token()` escolhe
entre o `PLAT_TOKEN` do ambiente e o arquivo **pela validade maior** — o ambiente é só semente de
boot. Não inverta essa ordem: com "ambiente primeiro", uma semente velha no `tokens.txt` sequestra
a renovação e colar token novo não muda nada (aconteceu em 25/07).

Os demais (SunOp, Axis, SolarEdge, API PV) se renovam sozinhos.
