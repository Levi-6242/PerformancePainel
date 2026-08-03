# Da OS corretiva à OS de inspeção

Especificação de implementação do botão **"Necessário abrir chamado"** e de tudo que ele cria.
Escrito para quem for construir isso no app de campo, sem precisar ler o código do OS Creator.

A lógica mora no pacote **`chamado_garantia/`**, na raiz do repositório, e não tem PyQt nem
`requests` dentro — dá para importar de qualquer app Python. O OS Creator importa daqui; se o app
de campo copiar em vez de importar, as duas OS passam a pedir coisas diferentes ao mesmo fabricante.

---

## 1. Onde isto se encaixa

Um chamado de garantia são três OS encadeadas por OS pai, no mesmo ativo:

| # | OS | Tipo de tarefa | Etiqueta | Quem executa |
|---|---|---|---|---|
| 1 | De campo | Corretiva¹ | — | técnico, em campo |
| 2 | **De chamados** | **Inspeção** | **Aguardando Garantia** | técnico, em campo |
| 3 | De acompanhamento | Administrativa | CHAMADOS | equipe de chamados |

¹ "Corretiva" aqui são **quatro** tipos: `Corretiva`, `Corretiva Emergencial`, `Religamento` e
`Religamento Remoto`. Religamento é corretiva de outro nome, e o técnico que foi religar e não
conseguiu é justamente quem descobre que vai precisar de garantia.

**Este documento cobre só a passagem da 1 para a 2.**

---

## 2. Quando o botão aparece

```python
import chamado_garantia as cg

if cg.pode_abrir(ativo, tipo_tarefa_os):
    mostrar_botao("Necessário abrir chamado")
```

Duas condições, e as duas precisam ser verdadeiras:

**a) O tipo da OS está em `cg.TIPOS_ORIGEM`** — os quatro acima. Numa preventiva ou numa
administrativa o botão não aparece.

**b) O ativo tem modelo de subtarefa.** Não adianta oferecer o botão num transformador ou num
disjuntor: não existe processo de chamado escrito para eles. Os tipos atendidos hoje:

`Inversor` · `Estrutura Trackers` · `NCU` · `RSU` · `Estação Meteorológica` · `Cabine` · `Skid`

mais três tipos que usam o modelo da estação por alias: **PRN** (piranômetro), **SDT** (sensor de
temperatura) e **FDL** (fieldlogger). `cg.grupo_de("PRN")` devolve `"Estação Meteorológica"`.

---

## 3. O que a OS de inspeção herda da OS corretiva

O app **não pergunta** nada disto — está tudo na OS que o técnico já tem aberta:

| Campo | De onde vem |
|---|---|
| **Ativo** | o mesmo da OS corretiva |
| **Data do incidente** | o `event_date` da OS corretiva, com a hora |
| **Responsável** | o mesmo da OS corretiva |
| **OS pai** | a própria OS corretiva |

> A **data programada** *não* é herdada: nasce no **dia seguinte ao incidente, às 8h**. Clonar a
> data do incidente agendava a ida a campo para a hora em que a falha foi vista.

---

## 4. O que o app resolve sozinho

```python
d = cg.montar(ativo, fabricante="", catalogo=todos_os_ativos)
```

| Chave | Valor | Origem |
|---|---|---|
| `tipo_tarefa` | `Inspeção` | fixo |
| `classif_1` | `Programada` | fixo |
| `classif_2` | `Elétrica` | fixo |
| `etiqueta` | `Aguardando Garantia` | fixo — id 2036, já existia no Fracttal |
| `titulo` | `[Ativo] - Inspeção para chamado <marca>` | montado |
| `fabricante` | descoberto (ver §5) | — |
| `subtarefas` | lista pronta para o RPC | ver §6 |
| `resumo` | `"8 subtarefas · 6 obrigatórias · 2 com anexo obrigatório"` | para mostrar antes de criar |

No Fracttal, os ids: tipo de tarefa `Inspeção` = 43889; classificações resolvidas **pelo nome**
(`Programada` = 56098, `Elétrica` = 66713) — pelo nome e não fixas, porque a lista é editável lá.

---

## 5. Descoberta da marca

`cg.descobrir_marca(ativo, catalogo)` tenta em duas etapas e **nunca chuta**:

**1. O texto do ativo.** `Inversor 1.1 Huawei SUN2000-250KTL-H1` → `Huawei`. Medido no catálogo
inteiro: acerta **94% dos inversores** (1.764 de 1.877) e **85% das estruturas de tracker**
(5.386 de 6.306).

**2. Os ativos irmãos da usina.** NCU, RSU e os sensores da estação se chamam só `NCU 1`,
`Piranômetro 1` — não há marca no nome. Mas os trackers da mesma planta dizem, e a NCU de uma planta
de trackers STI é STI. **Só sugere se os irmãos apontarem para uma única marca**; duas marcas na
mesma usina devolvem vazio.

Vazio significa **a tela tem de perguntar**. Na Estação Meteorológica isso é a regra, não a exceção:
só 1 de 106 estações traz a marca no texto, porque ali a descrição é o endereço da planta.

Marcas válidas por tipo de ativo saem de `cg.marcas_para(tipo)`.

---

## 6. Como as subtarefas são montadas

Três blocos somados, nesta ordem:

```
BASE  +  POR_TIPO[grupo do ativo]  +  POR_FABRICANTE[marca]
```

E três regras de limpeza, todas com motivo:

**Deduplicação por texto da pergunta.** A marca pode reforçar algo que o tipo já pede; duas linhas
iguais na mão do técnico é convite para ele responder qualquer coisa em uma delas.

**`so_para`** — pergunta de marca que só vale para certos ativos. A STI faz tracker, NCU e RSU; as
perguntas de componente, MAC e painel PV só fazem sentido no tracker. Sem esse filtro, uma OS de NCU
nascia com **16 subtarefas e duas perguntas de número de série**.

**Só se pergunta o que o técnico consegue responder no ativo.** Impacto na geração, data da falha,
número de unidades e "menos de 7 dias" saíram da lista — o app entrega (§7).

### Tipos de campo do Fracttal

Sondados ao vivo na conta 4987. **A documentação REST está errada para esta conta:**

| id | é de verdade | a doc dizia |
|---|---|---|
| 1 | Texto | Texto |
| 2 | Sim / Não | Número |
| 3 | **Número** | **Data** |
| 4 | Verificação (Aprovado / Alerta / Falhou) | Checkbox |
| 7 | **Lista** (com `dropdown_options`) | **Foto** |

**Não existe tipo Data.** Data e hora vão como texto, com o formato dentro da pergunta.

`is_required` e `attachments_required` funcionam por subtarefa — é o que permite exigir o número de
série **digitado e** a foto da etiqueta, que é a dor de origem deste projeto.

---

## 7. Campos que o app preenche no lugar do técnico

```python
cg.derivados(ativo, data_do_incidente)
```

| Campo | Regra |
|---|---|
| `data_falha` | a data do incidente da própria OS |
| `unidades` | `1` quando o ativo é inversor |
| `quantidade` | `1` para tracker, NCU e RSU — a OS é de um ativo |
| `menos_7d` | calculado da data do incidente, **recalculado a cada chamada** |

O `menos_7d` é função e não valor gravado de propósito: a equipe de chamados abre o ticket dias
depois da inspeção, e a resposta muda.

> ⚠️ **Ressalva registrada.** No formulário da Huawei esse campo é sobre a **idade do equipamento**
> (instalação recente, tratada como DOA), não sobre a idade da falha. Está calculado pela data do
> incidente porque foi o pedido; um inversor de três anos que falhou anteontem responde "Sim". Se a
> leitura mudar, é uma conta só, em `spec.derivados`.

---

## 8. As respostas viajam para a terceira OS

Cada subtarefa carrega uma `chave`, que é o campo do formulário do fabricante que ela alimenta
(`serial`, `problema`, `acoes`, `alarme`, `mac`, `testes`, `modelo`, `tag`…). Quando a inspeção é
concluída, a OS de acompanhamento nasce com esses campos escritos.

Medido num inversor Huawei: **5 dos 7 campos** do formulário vêm preenchidos.

Três campos do chamado **nunca** têm fonte no campo, e está certo: `cnpj`, `entrega` e `fiscal` são
trabalho de escritório da equipe de chamados.

---

## 9. Cobertura atual

11 marcas, extraídas dos nove processos de abertura em
`4. O&M/11.Pré-Operação/2. Controle/13. Gestão de Chamados/02. Processos de Abertura e Acompanhamento`.

**Sem processo escrito:** Sparkin (195 trackers, Ibirapuã 1 e 2) e MTR (149 trackers, Petrolina 3 e
Nova Londrina). SolarEdge (200 inversores) também não tem.

---

## 10. Tabelas — geradas do código

> As tabelas abaixo foram **geradas a partir do `chamado_garantia`**, não escritas à mão. Ao alterar
> o pacote, regere-as; descrever numa coisa e implementar outra é como o modelo se perde.

### Combinações e tamanho de cada modelo

| Tipo de ativo | Marca | Subtarefas | Obrigatórias | Com anexo |
|---|---|---:|---:|---:|
| Inversor | Canadian Solar | 15 | 9 | 8 |
| Inversor | Huawei | 8 | 6 | 2 |
| Inversor | Sungrow | 9 | 7 | 2 |
| Estrutura Trackers | Axial | 7 | 6 | 2 |
| Estrutura Trackers | Brametal | 14 | 9 | 3 |
| Estrutura Trackers | Convert | 8 | 7 | 2 |
| Estrutura Trackers | STI | 14 | 9 | 3 |
| Estrutura Trackers | Soltec | 12 | 8 | 2 |
| Estrutura Trackers | Trina | 7 | 6 | 2 |
| NCU | Brametal | 10 | 7 | 3 |
| NCU | STI | 10 | 7 | 3 |
| NCU | Soltec | 11 | 8 | 3 |
| RSU | Brametal | 9 | 7 | 3 |
| RSU | STI | 9 | 7 | 3 |
| RSU | Soltec | 10 | 8 | 3 |
| Estação Meteorológica | Hukseflux | 10 | 6 | 3 |
| Estação Meteorológica | Romiotto | 10 | 6 | 3 |
| PRN | Hukseflux | 10 | 6 | 3 |
| PRN | Romiotto | 10 | 6 | 3 |
| SDT | Hukseflux | 10 | 6 | 3 |
| SDT | Romiotto | 10 | 6 | 3 |
| FDL | Hukseflux | 10 | 6 | 3 |
| FDL | Romiotto | 10 | 6 | 3 |
| Cabine | Convert | 8 | 6 | 2 |
| Skid | Convert | 8 | 6 | 2 |

### Perguntas da BASE — valem para todo ativo e toda marca

| # | Pergunta | Tipo | Obrigatória | Anexo | Alimenta |
|---:|---|---|:---:|:---:|---|
| 1 | Descrição do problema: sintoma observado em campo | longo | sim | — | `problema` |
| 2 | Causa da falha | lista | sim | — | `—` |
| 3 | Ações já realizadas em campo (testes, resets, verificações) | longo | sim | — | `acoes` |
| 4 | Foto do alarme no equipamento, se estiver exibindo algum | texto | — | sim | `—` |

### Perguntas por TIPO DE ATIVO

**Inversor**

| Pergunta | Tipo | Obrigatória | Anexo | Alimenta |
|---|---|:---:|:---:|---|
| Nº de série do inversor (foto da etiqueta com modelo e série legíveis) | texto | sim | sim | `serial` |
| Modelo do inversor | texto | sim | — | `modelo` |
| ID do alarme exibido | texto | sim | — | `alarme` |
| Quantas strings o inversor possui | num | — | — | `—` |

**Estrutura Trackers**

| Pergunta | Tipo | Obrigatória | Anexo | Alimenta |
|---|---|:---:|:---:|---|
| Modelo / referência da peça (foto da etiqueta ou da peça) | texto | sim | sim | `modelo` |
| TAG do equipamento na usina (nome e número) | texto | sim | — | `tag` |
| Localização na planta: fileira, posição e nº dos trackers afetados | texto | sim | — | `—` |

**NCU**

| Pergunta | Tipo | Obrigatória | Anexo | Alimenta |
|---|---|:---:|:---:|---|
| Nº de série da NCU (foto da etiqueta) | texto | sim | sim | `serial` |
| Onde a NCU está instalada na planta | texto | sim | sim | `—` |
| Quantos trackers dependem desta NCU | num | — | — | `—` |
| Trackers afetados: fileira, posição e números | texto | sim | — | `—` |
| A NCU energiza / acende LED? | simnao | — | — | `—` |
| Testes executados em campo e valores medidos | longo | sim | — | `testes` |

**RSU**

| Pergunta | Tipo | Obrigatória | Anexo | Alimenta |
|---|---|:---:|:---:|---|
| Nº de série da RSU (foto da etiqueta) | texto | sim | sim | `serial` |
| Onde a RSU está instalada na planta | texto | sim | sim | `—` |
| Trackers afetados: fileira, posição e números | texto | sim | — | `—` |
| A RSU energiza / acende LED? | simnao | — | — | `—` |
| Testes executados em campo e valores medidos | longo | sim | — | `testes` |

**Estação Meteorológica**

| Pergunta | Tipo | Obrigatória | Anexo | Alimenta |
|---|---|:---:|:---:|---|
| Nº de série gravado no sensor (foto da etiqueta) | texto | sim | sim | `serial` |
| Modelo do sensor | texto | sim | — | `modelo` |
| Foto da posição exata do sensor na planta — ele volta para o MESMO lugar, a configuração Modbus é por posição | texto | sim | sim | `posicao` |
| Configuração Modbus (endereço ID, baud rate, paridade) | texto | — | — | `—` |
| Acessórios instalados junto (cabo, escudo solar, estrutura, pés) | longo | — | — | `acessorios` |
| Leitura atual do sensor no supervisório | texto | — | — | `—` |

**Cabine**

| Pergunta | Tipo | Obrigatória | Anexo | Alimenta |
|---|---|:---:|:---:|---|
| Equipamento da cabine com falha (foto) | texto | sim | sim | `—` |
| Nº de série do equipamento, se houver | texto | — | — | `serial` |
| TAG do equipamento na usina (nome e número) | texto | sim | — | `tag` |

**Skid**

| Pergunta | Tipo | Obrigatória | Anexo | Alimenta |
|---|---|:---:|:---:|---|
| Equipamento do skid com falha (foto) | texto | sim | sim | `—` |
| Nº de série do equipamento, se houver | texto | — | — | `serial` |
| TAG do equipamento na usina (nome e número) | texto | sim | — | `tag` |

### Perguntas por MARCA — só o que a base e o tipo já não cobrem

**Axial** — nada a acrescentar: o formulário dele pede só o que já está sendo coletado.

**Brametal**

| Pergunta | Tipo | Obrigatória | Anexo | Só para | Alimenta |
|---|---|:---:|:---:|---|---|
| Componente com falha | lista | sim | — | Estrutura Trackers | `tipo_equip` |
| Nº de série do componente com falha (foto da etiqueta) | texto | sim | sim | Estrutura Trackers | `serial` |
| Nº de MAC (obrigatório quando for TCU) | texto | — | — | Estrutura Trackers | `mac` |
| TCU liga / energiza? | simnao | — | — | Estrutura Trackers | `—` |
| Tensão medida no painel PV (V) | num | — | — | Estrutura Trackers | `—` |
| Corrente medida no painel PV (A) | num | — | — | Estrutura Trackers | `—` |
| Testes executados em campo e valores medidos | longo | sim | — | todos | `testes` |

**Canadian Solar**

| Pergunta | Tipo | Obrigatória | Anexo | Só para | Alimenta |
|---|---|:---:|:---:|---|---|
| Nº de série do datalogger (foto da etiqueta) | texto | sim | sim | todos | `serial_dl` |
| Data de instalação / início de operação (dd/mm/aaaa) | texto | sim | — | todos | `op_desde` |
| Fotos da instalação: módulos, inversores, disjuntores, string box, QGBT e aterramento | texto | sim | sim | todos | `evidencias` |
| Vídeo da partida com 1 string, sem datalogger | texto | — | sim | todos | `—` |
| Vídeos das medições CC nos MC4 (PV+/T, PV-/T, PV+/PV-) | texto | — | sim | todos | `—` |
| Vídeos das medições CA no conector (F-F, F-T, F-N, N-T) | texto | — | sim | todos | `—` |
| Vídeos do display (Information, Alarm, Version, Running) | texto | — | sim | todos | `—` |

**Convert**

| Pergunta | Tipo | Obrigatória | Anexo | Só para | Alimenta |
|---|---|:---:|:---:|---|---|
| Item / descrição do equipamento em garantia | texto | sim | — | todos | `—` |

**Huawei** — nada a acrescentar: o formulário dele pede só o que já está sendo coletado.

**Hukseflux** — nada a acrescentar: o formulário dele pede só o que já está sendo coletado.

**Romiotto** — nada a acrescentar: o formulário dele pede só o que já está sendo coletado.

**STI**

| Pergunta | Tipo | Obrigatória | Anexo | Só para | Alimenta |
|---|---|:---:|:---:|---|---|
| Componente com falha | lista | sim | — | Estrutura Trackers | `tipo_equip` |
| Nº de série do componente com falha (foto da etiqueta) | texto | sim | sim | Estrutura Trackers | `serial` |
| Nº de MAC (obrigatório quando for TCU) | texto | — | — | Estrutura Trackers | `mac` |
| TCU liga / energiza? | simnao | — | — | Estrutura Trackers | `—` |
| Tensão medida no painel PV (V) | num | — | — | Estrutura Trackers | `—` |
| Corrente medida no painel PV (A) | num | — | — | Estrutura Trackers | `—` |
| Testes executados em campo e valores medidos | longo | sim | — | todos | `testes` |

**Soltec**

| Pergunta | Tipo | Obrigatória | Anexo | Só para | Alimenta |
|---|---|:---:|:---:|---|---|
| Objetivo do chamado em uma linha (ex.: 'Gateway não está funcionando') | texto | sim | — | todos | `titulo_ch` |
| Componente com falha | lista | sim | — | Estrutura Trackers | `tipo_equip` |
| ID do Gateway (GW) | texto | — | — | Estrutura Trackers | `gw_id` |
| IDs dos rastreadores afetados | texto | — | — | Estrutura Trackers | `tracker_id` |
| Testes executados em campo e valores medidos | longo | — | — | todos | `testes` |

**Sungrow**

| Pergunta | Tipo | Obrigatória | Anexo | Só para | Alimenta |
|---|---|:---:|:---:|---|---|
| Produto com problema (conforme catálogo Sungrow) | texto | sim | — | todos | `produto` |

**Trina** — nada a acrescentar: o formulário dele pede só o que já está sendo coletado.
