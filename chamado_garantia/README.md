# chamado_garantia

A lógica de abertura de **chamado de garantia**, sem interface e sem rede. Feita para ser usada por
mais de um app: o **OS Creator** (desktop, o supervisor abre a inspeção) e o **app de campo**
(celular, o técnico clica em "Necessário abrir chamado" dentro da OS que está preenchendo).

O `os_creator/chamado_insp_spec.py` é só uma ponte para cá. **Regra nova entra aqui**, nunca lá —
duas cópias divergindo significam a OS do supervisor e a do técnico pedindo coisas diferentes ao
mesmo fabricante, que é o problema que este projeto veio resolver.

## O fluxo, em três OS

| # | OS | Tipo de tarefa | Etiqueta | Quem |
|---|---|---|---|---|
| 1 | De campo | Corretiva | — | técnico, em campo |
| 2 | **De chamados** | **Inspeção** | **Aguardando Garantia** | técnico, em campo |
| 3 | De acompanhamento | Administrativa | CHAMADOS | equipe de chamados |

Este pacote monta a **2**.

## Uso no app de campo

```python
import chamado_garantia as cg

# o botão "Necessário abrir chamado" só aparece para ativo que tem modelo
if cg.pode_abrir(ativo):
    ...

# ao clicar: monta tudo o que a OS de inspeção precisa
d = cg.montar(ativo, fabricante="", catalogo=todos_os_ativos)

d["tipo_tarefa"]   # "Inspeção"
d["classif_1"]     # "Programada"
d["classif_2"]     # "Elétrica"
d["etiqueta"]      # "Aguardando Garantia"
d["fabricante"]    # descoberto sozinho quando o cadastro permite
d["titulo"]        # "[Ativo] - Inspeção para chamado <marca>"
d["subtarefas"]    # já no formato do RPC do Fracttal
d["resumo"]        # "8 subtarefas · 6 obrigatórias · 2 com anexo obrigatório"
```

**O que o app de campo fornece**, porque já está na OS aberta na mão do técnico:

- o **ativo** (clonado da OS atual);
- a **data do incidente** (clonada da OS atual);
- o **responsável** (o próprio técnico, ou quem a OS atual indicar);
- a **OS pai** (a OS atual).

**O que este pacote resolve sozinho**: marca, tipo de tarefa, classificação, etiqueta, título e as
subtarefas do fabricante.

## Descoberta da marca

`cg.descobrir_marca(ativo, catalogo)` tenta em duas etapas:

1. **texto do ativo** — acerta 94% dos inversores e 85% das estruturas de tracker (medido no
   catálogo inteiro em 29/07);
2. **ativos irmãos da usina** — para NCU, RSU e sensores da estação, que se chamam só "NCU 1" ou
   "Piranômetro 1". A NCU de uma planta de trackers STI é STI.

Devolve `""` quando não dá para saber — e aí a tela **tem** de perguntar. Nunca chuta.

## Campos que o app preenche no lugar do técnico

`cg.derivados(ativo, data_do_incidente)` devolve o que não faz sentido perguntar em campo:

- `data_falha` — a data do incidente da própria OS;
- `unidades` / `quantidade` — 1, porque a OS é de um ativo;
- `menos_7d` — calculado da data do incidente, **recalculado a cada chamada** (a equipe de chamados
  abre o ticket dias depois, e a resposta muda).

> ⚠️ No formulário da Huawei, "menos de 7 dias" é sobre a **idade do equipamento**, não a da falha.
> Está calculado pela data do incidente porque foi o pedido; se a leitura mudar, é uma conta só.

## Cobertura

11 marcas, 26 combinações de tipo de ativo × marca, extraídas dos nove processos de abertura em
`4. O&M/11.Pré-Operação/2. Controle/13. Gestão de Chamados/02. Processos de Abertura e
Acompanhamento`.

Tipos de ativo atendidos: **Inversor · Estrutura Trackers · NCU · RSU · Estação Meteorológica ·
Cabine · Skid**, mais os sensores da estação por alias (**PRN** piranômetro, **SDT** sensor de
temperatura, **FDL** fieldlogger).

Sem processo escrito ainda: **Sparkin** (195 trackers) e **MTR** (149 trackers).

## Tipos de subtarefa do Fracttal

Sondados ao vivo na conta 4987 — a documentação REST **está errada** para esta conta:

| id | é | doc REST dizia |
|---|---|---|
| 1 | Texto | Texto |
| 2 | Sim / Não | Número |
| 3 | **Número** | **Data** |
| 4 | Verificação (Aprovado/Alerta/Falhou) | Checkbox |
| 7 | **Lista** (traz `dropdown_options`) | **Foto** |

**Não existe tipo Data.** Data e hora vão como texto, com o formato na própria pergunta.

`is_required` e `attachments_required` funcionam por subtarefa — é o que permite exigir o número de
série digitado **e** a foto da etiqueta.
