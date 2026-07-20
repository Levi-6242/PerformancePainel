# Plataforma de Performance — pacote p/ redesign (Grid Co.)

Artefatos REAIS extraidos de `templates/index.html`. Nada reconstruido de memoria.

## Arquivos aqui
- **plataforma.css** — a folha de estilo COMPLETA (todas as telas usam a mesma). CSS puro,
  **sem framework** (nao e Tailwind/Bootstrap): variaveis CSS (`:root` / `body.dark`), fonte **Inter**,
  graficos via **Plotly** (CDN). Tema claro e escuro (navy `#090d18`) no mesmo arquivo.
- **ETM (painel real).html** — a tela ETM (prioridade), painel real `#panel-pv-etm`, ja linkando o CSS.
  Abra no navegador: mostra o esqueleto real (4 cards + tabela). O `<tbody>` vem vazio porque e
  preenchido por JS em runtime (veja abaixo).

## IMPORTANTE — por que "so o template" nao mostra a tela cheia
As telas sao **renderizadas por JavaScript**. O template (`<div id="panel-...">`) e o esqueleto;
a tabela, os cards de tracker, os chips Ipv e o grafico Plotly (ex.: o drill do Brodowski) sao
montados em runtime. Para o **HTML renderizado FIEL** de uma tela (com o conteudo), o caminho e:

  1. Abrir a tela no navegador (logado).
  2. Botao direito -> Inspecionar -> aba Elements.
  3. Botao direito no `<html>` (ou no `<div id="panel-...">` da tela) -> Copy -> **Copy outerHTML**.
  4. Colar num arquivo `.html`.

Isso da o DOM real, ja preenchido. (Se preferir, me manda o outerHTML colado que eu limpo e
troco qualquer dado real por exemplo.)

## Mapa: tela -> painel -> linha em templates/index.html
| Tela                | id do painel                              | Linha |
|---------------------|-------------------------------------------|-------|
| Geral (consolidado) | panel-geral                               | 982   |
| Strings             | panel-pv-strings (+ str-prob / str-ev)    | 1061 / 1018 / 1039 |
| ETM (meteo)         | panel-pv-etm / panel-pg-etm / sunop-etm   | 1117 / 1372 / 1544 |
| Trackers            | panel-sunop-trackers                      | 1450  |
| PR Inversores       | panel-pv-pr                               | 1591  |
| Curva das strings   | drill (Ipv + Plotly, montado por JS)      | via JS |

## Stack (resumo p/ o designer)
- HTML servido por Flask + Jinja2 (server-side) e populado por JS vanilla (sem framework de front).
- CSS: hand-written, variaveis CSS, Inter, ~825 linhas (plataforma.css). Radios 12/8px.
- Marca: verde #A3D900. Tema escuro navy: #090D18 / #161D30 / #1C2640. Texto #E9EEF6.
- Graficos: Plotly 2.35.
