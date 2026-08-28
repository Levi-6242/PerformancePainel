# steps/engenharia/ — a área de Engenharia

Esta pasta é da **Engenharia**. Tudo que a área precisa mudar mora aqui dentro.

Leia primeiro `steps/CLAUDE.md` (como se escreve uma tela) e `os_creator/CLAUDE.md`
(armadilhas da API do Fracttal e a régua de verificação). Este arquivo só diz a fronteira.

> Modelo para outras áreas: copie esta pasta trocando o nome, e ajuste as duas listas abaixo.

## O que é seu

- Qualquer arquivo dentro de `steps/engenharia/`.
- A entrada do seu card na lista de cards do `app.py` — **uma linha**, a sua.

## O que não é seu

Se a tarefa parece exigir mexer em algo desta lista, **pare e abra a conversa** em vez de editar.
Não é burocracia: são arquivos que todas as áreas usam ao mesmo tempo, e uma mudança aqui altera
telas que você não testou.

| Arquivo | Por que não |
|---|---|
| `api.py` | 5.000+ linhas, é o que **todas** as telas usam para falar com o Fracttal. Mudar uma função aqui muda o comportamento de Performance, COS, PCM e Chamados junto. |
| `steps/ui.py` | Tema e componentes compartilhados. Um ajuste de cor ou de espaçamento aparece em todas as telas. |
| `app.py` (fora da sua linha) | Navegação e janela principal. Erro aqui impede o app de **abrir** — e a v135 provou que app que não abre também não atualiza. |
| `cos_spec.py`, `chamado_garantia/` | Regras de negócio de outras áreas. |
| `.spec`, `release.py`, workflows | Empacotamento e publicação. |

**Precisa de uma função nova no `api.py`?** É pedido legítimo e acontece. Abra a conversa
descrevendo o que precisa receber e devolver — quem cuida do `api.py` escreve, e você chama.
O que não pode é a função nascer no meio de uma tarefa de tela, sem ninguém olhar.

## Aviso para agente de código

Se você é um agente trabalhando nesta pasta: a tabela acima **não** é uma sugestão de estilo.
Editar aqueles arquivos para "resolver logo" é o modo de falha específico que este documento
existe para impedir. Quando o caminho mais curto passar por eles, **diga isso e pare** —
não siga em frente.

E o mais importante: **o erro grave aqui não é o que quebra.** É o que funciona, cria a OS e
grava errado no sistema do cliente. Compilar, abrir e a tela responder não é evidência de nada.
A evidência é a OS aberta no Fracttal, conferida campo a campo. Se você não conseguiu fazer isso,
diga que não conseguiu.

## Como publicar

1. Trabalhe em um branch seu, nunca direto no `main`.
2. Teste segundo a lista de `steps/CLAUDE.md` — incluindo abrir o app inteiro e criar uma OS de
   teste na usina `TESTE - PA`.
3. Abra o PR. O `CODEOWNERS` chama o revisor certo automaticamente.
4. O build confere se o app abre antes de publicar. Se ele reprovar, o problema é seu para
   consertar — não é para forçar o merge.
5. Aprovado, a publicação é automática. Não existe passo manual de compilar.

## Convenções

- **pt-BR em tudo**, inclusive comentário de código.
- **Sem emoji na interface.**
- Tema navy (`#090d18` / `#161d30`) + verde Grid. Nunca lilás. As cores saem do `steps/ui.py`.
- Comentário explica **por quê**, citando o caso real que motivou a regra.
