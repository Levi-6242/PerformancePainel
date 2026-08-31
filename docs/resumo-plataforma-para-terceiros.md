# Plataforma de Performance — resumo de arquitetura

Dashboard interno de O&M solar. Lê 7 fontes diferentes (APIs de supervisório, um PostgreSQL e
e-mail), normaliza tudo num formato só e serve telas de strings, trackers, irradiância, geração,
PR e uma visão gerencial. Uso interno, 3 a 6 analistas.

Este documento é o **mapa das decisões que importam** — o que copiar e o que evitar. Não é manual
de instalação.

---

## Stack

Flask + waitress (produção, não o servidor de dev), Python 3.14. Frontend em HTML/CSS/JS puro,
sem build e sem framework. Sem banco próprio: o estado vive em JSON no disco, o cadastro mestre
em planilhas Excel, e um PostgreSQL externo é uma das *fontes*, não o nosso armazenamento.

O backend é um monolito de ~19 mil linhas num arquivo. **Não é recomendação** — é o que cresceu.
Se você está começando, quebre em módulos por fonte desde o início.

---

## 1. A decisão que mais importa: dois processos

O erro original foi reconstruir os caches dentro do processo web. Medido: com um rebuild em curso,
endpoints que respondiam em 2–7 ms passavam de 2.900 ms — **até 1000× mais lentos**. Pandas e
openpyxl são Python puro e seguram o GIL quase o tempo todo.

Pior: um ciclo completo de reconstrução leva ~8 minutos e o TTL do cache é 5, então o servidor
vivia reconstruindo e quase todo usuário caía na janela ruim.

A separação:

```
worker.py   reconstrói tudo e PUBLICA num snapshot em disco
app.py      só lê o snapshot e serve. Nenhum trabalho pesado no caminho de uma requisição.
```

Um guardião (Tarefa Agendada) mantém os dois vivos.

**Detalhe que não é óbvio:** rodar as fontes em paralelo dentro do worker **não** encurtou o ciclo
(501 s contra ~500 s em série) e ainda piorou cada item, porque o trabalho é CPU sob o GIL, não
espera de rede. O que resolveu foi **prioridade**: a aba mais usada reconstrói primeiro e sozinha;
as telas de consulta ocasional só a cada N ciclos.

---

## 2. Camada de fontes: N fontes, um formato

Cada fonte tem um `build_*` que devolve **a mesma forma de linha** (usina, inversores, strings
ativas, esperadas, última leitura, status). As telas não sabem de qual fonte vieram.

O que isso paga: régua de classificação escrita **uma vez**. Quando corrigimos a detecção de
tracker parado, valeu para as 7 fontes no mesmo commit.

O que isso cobra: normalização de nomes é um problema real e permanente. A mesma usina aparece
como `TIM100` no supervisório, `Thopen - Ibaté 1 - SP` no ERP de manutenção e `Ibaté 1` na
planilha. Existe um cadastro mestre (planilha) que é a fonte da verdade do de-para. **Se você tem
mais de uma fonte, resolva isso no dia 1** — depois fica caro.

---

## 3. Padrões que valem copiar

### Vazio nunca sobrescreve dado bom
A regra mais valiosa do projeto. Fonte sob throttle devolve lista vazia, e um `[]` gravado por
cima do último dado bom apaga a tela por 5 minutos. Em todo cache: só grava se veio conteúdo; se
veio vazio, mantém o anterior e tenta de novo. Cache vazio, quando inevitável, entra com validade
**curta** (30 s), não com o TTL cheio.

### Disjuntor por fonte
Uma das APIs fica atrás de CDN com rate limit: uma rajada derruba a conta inteira por ~30 s e
**tudo** responde 403 em 0,0 s (bloqueio de borda, o servidor nem é consultado). O agravante é que
o ciclo seguinte continua batendo e mantém o contador quente — o que devia durar 30 s virava
permanente.

Solução: no primeiro 403 de borda, **pausa todas as chamadas àquela fonte por 90 s**. Quem chega
no meio recebe vazio na hora (e a regra acima segura o último dado bom). Sem espera, sem fila.

Isso vale para qualquer integração com CDN na frente. O sintoma engana: parece token vencido.

### Erro ≠ ausência de dado
`catch → []` transforma falha nossa em "a fonte não reportou", e a tela acusa o fornecedor por um
bug interno. Marque o erro e diga na tela qual dos dois foi.

### Token: arquivo vence ambiente
Dois arquivos, dois donos. Um é **semente** (editado por humano, carregado no boot); o outro é
**estado** (o app escreve quando renova). Ao escolher qual usar, vale o de **maior validade** —
nunca "ambiente primeiro". Com a ordem invertida, uma semente velha sequestra a renovação e colar
token novo não muda nada. Custou um dia para descobrir.

Cuidado gêmeo: token vive **em memória** no processo. Colar token novo no arquivo não ajuda se o
processo já subiu com o velho — ou o código relê o arquivo quando a memória expira, ou é restart.

### Estado fora do versionamento
Caches, histórico, notas dos analistas, tokens renovados: nada disso vai para o git. São megabytes
que mudam a cada minuto e alguns carregam segredo. Regra de ignore explícita desde o começo — não
"não está rastreado por sorte".

---

## 4. Armadilhas específicas (custaram tempo real)

**Contador diário que não zera à meia-noite.** A leitura das 00:00 ainda carrega o total de ontem;
o reset chega minutos depois. Um `MAX()` sobre o dia inteiro pega esse resto e repete o valor do
dia anterior sempre que hoje rendeu menos — dias consecutivos com geração idêntica. Estava
inflando o total em **12%**. A régua certa é contar só a partir do reset (a primeira queda do
contador), **não** um corte por hora fixa: parte dos equipamentos zera ao acordar, não à
meia-noite.

**Fuso do banco.** Tabelas cruas em `timestamptz` (UTC), views em timestamp ingênuo local.
Converter sempre e explicitamente. Um filtro escrito sem isso pode **zerar o resultado em
silêncio** — "últimas 2 horas" caiu no futuro e voltou vazio.

**Pipeline de terceiro congela.** As views agregadas de um fornecedor pararam de atualizar sem
avisar. A saída foi reconstruir a partir das tabelas cruas: mesmo dado, mais rápido, e sob nosso
controle. Se você depende de transformação de terceiro, tenha o caminho cru mapeado.

**Ler planilha aberta.** Excel/OneDrive travam o arquivo. Ler sempre de uma cópia, feita uma vez
por versão do arquivo — não por chamada, senão duas threads corrompem a cópia.

**Escrever planilha compartilhada.** Round-trip de biblioteca em pasta de trabalho complexa
descarta coisas silenciosamente (validação de dados, no nosso caso). Para editar poucas células,
cirurgia no XML dentro do `.xlsx` preserva o resto byte a byte.

**Janela de tempo esconde falha.** Ao filtrar "últimas N horas", equipamento mudo há dias **some**
da tela em vez de acender alarme. O filtro tem de manter o que está velho, marcado como velho.

---

## 5. O que eu faria diferente

1. **Modularizar por fonte desde o início.** O monolito só piora.
2. **De-para de nomes no dia 1**, com uma fonte única da verdade.
3. **Testes das funções puras de classificação.** As réguas (parado, sem corrente, PR) são
   funções puras sobre séries — trivial de testar e é onde nasceram os piores bugs.
4. **Publicação com hostname fixo.** Túnel efêmero funciona para demonstrar e atrapalha para
   operar: o endereço muda a cada queda, e isso trava integração e SSO.
5. **Um número visível de cobertura.** Quase todo bug sério apareceu como "esse número está
   estranho" de um analista, não como exceção no log. Mostrar quantos dias/equipamentos entraram
   em cada agregado pega isso mais cedo.

---

## 6. Se for reaproveitar código

O núcleo transferível é pequeno: o par worker/servidor com snapshot, o disjuntor por fonte, e as
funções de classificação de série temporal (detectar equipamento parado, sensor travado, valor
congelado). O resto é acoplado às nossas fontes e ao nosso cadastro.
