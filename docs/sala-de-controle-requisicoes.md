# Sala de controle: como a tela pede os dados, e o que o Monitoramento do COS ensina

Pedido do Levi (16/11/2026, 23h30): "Faça uma análise geral de como fazemos as requisições e como melhoraria, compare como
o COS faz as requisições". Os tempos são medidos em produção, com o servidor quieto, em 16/11 entre 22h e 0h.

## Como o Monitoramento do COS faz

1. **Grava antes, lê depois.** A Ronda COS coleta os loggers e grava no banco dela (a potência de minuto a minuto, as
   entradas de cada inversor de 5 em 5 min, 45 dias). A tela nunca pergunta ao portal do fabricante na hora.
2. **Uma leitura para todas as usinas.** O cartão de todas as usinas vem num pedido só; os inversores de todas, em outro.
3. **Cópia no servidor, curta, e um pedido no ar.** O Nexus guarda cada resposta (2 s o ao vivo, 20 s a lista, 60 s a
   curva de hoje, 1 h o dia que passou). Dez pessoas com a tela aberta são uma leitura.
4. **A tela pede só o que abriu.** O histórico é por inversor e por dia; o ao vivo relê só o pedaço leve.

## Como a Sala pede hoje (medido)

| Leitura | De onde | 1ª vez | Repetida | Segue o padrão do COS? |
|---|---|---|---|---|
| Entrada (todas as usinas) | resumo em memória, refeito pelo servidor | 0,2 a 0,4 s | igual | sim (um pedido, tudo) |
| Usina (inversores e strings de agora) | cópia do Tempo real | 0,2 s | igual | sim |
| Pacote de falhas do mês | arquivo do servidor | 0,5 s | igual | sim (gravado antes) |
| Geração e PR do mês (banco) | BDs em memória | 0,4 s | 0,3 s | sim |
| Geração e PR do mês (GreenYellow) | BDs em memória | 7,6 s | 0,3 s | sim; a 1ª depois da subida é lenta |
| Potência do dia (banco) | banco da Thopen | 3,5 s | 0,3 s | sim (cópia e um pedido no ar) |
| Potência do dia (GreenYellow) | scadaGridco, um inversor por pedido | 23 s | 0,9 s | em parte: a fonte não tem a rota por usina |
| Curva de strings (banco) | banco da Thopen, a usina inteira | 7 a 18 s | 0,5 s | passou a ter cópia em 16/11 |
| Curva de strings (API PV) | portal, na hora | 13 s | 0,3 s (5 min) | não: pergunta ao portal |
| Curva dos trackers (banco) | banco da Thopen | 6 a 10 s | cópia de 5 min | sim |
| Lista e inversores do COS | Nexus (cópia de 20 a 30 s) | menos de 1 s | igual | é o próprio COS |

## O que já foi aplicado (16/11)

- cópia no servidor na curva de strings do banco (5 min hoje, 1 h o dia que passou, um pedido no ar);
- a curva das usinas da API PV com logger vem do histórico gravado no COS;
- um pedido no ar por endereço também na tela (abrir vários inversores não repete a leitura da usina);
- a Potência pede um dia por vez (cada dia tem a sua cópia no servidor);
- a Geração do mês é lida quando a usina abre (sai dos BDs em memória, não é fonte paga): o PR do mês no cabeçalho e a
  aba já chegam prontos;
- a conferência das fontes usa a lista do COS inteira (um pedido) em vez de um pedido por usina.

## Onde ainda perdemos tempo, e o que proponho

1. **A subida esfria tudo.** Cada deploy reinicia a plataforma e a coleta: a Entrada fica "aquecendo" de 2,5 a 7 min e a
   1ª Geração do mês de uma usina já levou 212 s. Em 16/11 foram dez subidas. Proposta: subir em lote (já é regra) e
   guardar em disco as cópias que custam (o resumo da Entrada, os BDs), para a largada começar morna.
2. **A 1ª leitura do banco da Thopen.** A curva de strings faz 32 extrações de JSON por linha da `raw_inverter`; a
   Potência e os trackers leem a mesma tabela. Proposta: medir a consulta (EXPLAIN) e, se confirmar, gravar o que a tela
   usa (corrente por string e potência, de 5 em 5 min) numa tabela nossa, como o COS grava a `scada_entradas`.
3. **O scadaGridco responde um inversor por pedido.** A Potência da GreenYellow são 16 pedidos em série (23 s). Proposta:
   pedir à Automação uma rota por usina e dia, ou gravar a potência no nosso banco pela coleta.
4. **A API PV é perguntada na hora** (13 s por usina). Onde há logger, a curva já vem do COS; onde não há, só gravando
   pela coleta (o dia que passou já fica guardado para sempre).
5. **O estado inteiro para ler uma chave.** O acompanhamento e os comentários de UMA usina vêm do `/api/state` inteiro.
   Proposta: rota por chave.

Nada do item 1 ao 5 foi feito nesta leva: são propostas, cada uma com a sua medição.
