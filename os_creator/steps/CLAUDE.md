# steps/ — como se escreve uma tela aqui

Uma tela por fluxo. Quem for adicionar um card ao app trabalha aqui dentro.
Leia antes o `CLAUDE.md` da pasta acima (armadilhas da API e a régua de verificação).

## O contrato de uma tela

- Um `QWidget` com o próprio layout. Quem monta a navegação é o `app.py`.
- Se a tela tiver o próprio botão de Voltar, marque `_selfnav = True` — o `app.py` deixa de pôr
  a barra dele e você não fica com dois Voltar na mesma tela.
- Cores, fontes e componentes saem do `steps/ui.py` (`BG`, `CARD`, `INPUT`, `BORDER`, `GREEN`,
  `GREEN_INK`, `TEXT`, `MUTED`). **Não invente hex novo** — o tema é navy + verde Grid, e
  divergência aparece na hora.
- Toda chamada de API vai para uma thread. Nunca direto no clique.

## Chamada de API: o padrão, e por que não tem outro

```python
self._w = ApiWorker(api.minha_funcao, arg1, arg2)
self._w.ok.connect(self._quando_der_certo)
self._w.erro.connect(self._quando_der_errado)
self._w.start()
```

Guarde o worker em `self.` — uma `QThread` sem referência viva é coletada pelo garbage collector
e **mata o processo inteiro**, sem traceback. Os slots levam `@slot_seguro`, que engole a exceção
para não derrubar o app e grava em `%TEMP%\criaros_erros.log`. É lá que o erro aparece quando a
tela simplesmente "não fez nada".

## Armadilhas do PyQt6 que já custaram tempo

**Ícones — leia isto antes de usar um.** Existem **dois dicionários diferentes**:

| Dicionário | Onde | Para quê |
|---|---|---|
| `app.py::_ICO` | `os_creator/app.py` | ícones dos cards do launcher |
| `steps/ui.py::_LUCIDE` | `os_creator/steps/ui.py` | ícones dentro das telas |

Ler um nome de um e usar no outro levanta `KeyError` **dentro do `MainWindow.__init__`** — ou
seja, o app não abre. Foi exatamente isso na v135. Ao adicionar um ícone, adicione **nos dois**
se ele for usado nos dois lugares.

**`QLabel` herda de `QFrame`.** Uma regra `QFrame{border:1px solid X;}` no card pai vaza para
todo `QLabel` filho. Um ponto de status de 6px virou um círculo inteiro pintado por causa disso.
Ponha `border:none` no filho.

**`deleteLater()` não tira da tela.** Ele agenda a destruição, mas o widget continua desenhado e
sobrepondo o que veio depois. Chame `setParent(None)` também.

**`takeAt()` devolve espaçador.** Um `addStretch()` vira item de layout sem widget — testar
`item.widget()` antes de usar, senão dá `AttributeError` ao limpar um layout.

**`QScrollArea` pinta a cor de janela.** O `QWidget` interno tem fundo próprio e aparece como um
retângulo mais claro dentro do card. O seletor que resolve:

```
QScrollArea{background:transparent;border:none;}
QScrollArea > QWidget > QWidget{background:transparent;}
```

**`QLabel` reporta a largura do texto inteiro como mínimo** e empurra os irmãos para fora da
janela. Use `QSizePolicy.Minimum` na horizontal e encurte o texto — as duas coisas.

**`clicked` ≠ `toggled`.** `clicked` só dispara em clique humano; `toggled` dispara também quando
o código marca a caixa. Para distinguir "o usuário escolheu" de "o app sugeriu", conecte
`clicked`.

**Foco desenha retângulo branco** e espreme o texto de tabelas. Mate com `outline:0` e
`item:focus{border:none}`.

## Antes de abrir o PR

1. Rodou a tela e ela abre.
2. **Rodou o app inteiro** — `python main.py` — e a janela principal abre. Tela isolada
   funcionando não prova nada; foi assim que a v135 passou.
3. Criou uma OS de teste na usina `TESTE - PA` e conferiu campo a campo no Fracttal.
4. Cancelou a OS de teste.
5. Escreveu as linhas de nota de versão do que mudou, na linguagem de quem usa o app —
   não "refatorado o handler", e sim "Performance: a data do evento não aceita mais data futura".

## Convenções

- **pt-BR em tudo**, inclusive comentário de código.
- **Sem emoji na interface.** Severidade se comunica por cor.
- Comentário explica **por quê**, de preferência citando o caso real que motivou a regra.
  É o padrão dos arquivos daqui; mantenha.
