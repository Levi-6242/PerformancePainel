# Metodologia de Análise de Strings — gabaritos para a régua

Análogo dos gabaritos de trackers ([metodologia-analise-trackers.md](metodologia-analise-trackers.md)), mas para a **corrente por string**. Fonte: relatórios gerados pelo Levi (Sonnet) a partir da curva crua exportada em CSV (`/api/<fonte>/strings/curva.csv`). São **gabaritos de construção** (evitar whack-a-mole), não relatórios diários.

## Princípios da régua de strings

1. **Referência = mediana das strings-IRMÃS do MESMO inversor** no MESMO instante — cada string é comparada com as outras do seu próprio inversor. (Diferença-chave vs trackers, que usam a mediana/alvo da FROTA da usina.)
2. **Detecção de janela de queda (critério CONCRETO, SMP100):** `corrente < 0,5A` enquanto `mediana das irmãs > 2,0A`, janelas agrupadas com **limiar mínimo de 30 min**.
2b. **Parado × Ocorrência:** se a corrente fica nula por praticamente toda a janela de geração (ex.: SMP100 ST_21/24 = 480min de zero, sem recuperação) → **Parado**; se há queda ≥30min COM recuperação no mesmo dia → **Ocorrência**.
2c. **Sub-classificação do Parado (SMP100 §3.2):** olhar o PADRÃO no amanhecer/entardecer (baixa irradiância). Zero em TODA condição (inclusive baixa luz) → **desconexão total** (cabo rompido/fusível — exige continuidade/troca). Corrente pequena e real só sob baixa irradiância que cai a zero sob carga normal → **mau contato** (resistência elevada — reaperto/troca de conector, reparo mais simples).
2d. **Causa compartilhada (SMP100 §3.3):** 2+ strings do MESMO inversor com janelas de falha coincidentes no tempo → priorizar hipótese de causa física compartilhada (mesmo combinador/disjuntor/dano regional) sobre falhas independentes. (Análogo à causa-raiz dos trackers.)
3. **Critério de RAMPA SAUDÁVEL (exclusão de falso-positivo)** — introduzido no gabarito SMP100 (18/07). Para uma ocorrência breve (única, curta duração, recuperação total): examinar a **rampa de amanhecer ANTES** do evento + a **curva de geração DEPOIS**. Se ambas mostram subida gradual saudável e próxima das strings-irmãs → **causa AMBIENTAL transitória** (sombra de nuvem, ave, sujeira temporária), NÃO falha elétrica → registrar para monitoramento, sem prioridade de manutenção. É a mesma verificação que diferencia desconexão total de mau contato — aqui usada para diferenciar falha elétrica de sombreamento pontual.
4. **Categorias:** `Parado` (corrente zero permanente / falha permanente) · `Ocorrência` (queda com recuperação) · `Normal`.
5. **Não auto-classificar** toda janela de queda como falha de equipamento antes de examinar o contexto ao redor do evento.

## Corpus (casos-gabarito)

| Usina | Fonte | Data | Inv / Strings | Resumo |
|---|---|---|---|---|
| SMP100 | Athon (sunop) | 18/07 | 20 inv / 350 strings | 2 **Parado** reais, mesmo inversor (6.2): **ST_21** = 0,00A o dia todo → **desconexão total**; **ST_24** = pequena no amanhecer (0,33-0,46A) que cai a zero sob carga → **mau contato**. Janelas coincidentes (07:55-08:25 + 08:35-16:05, 480min) → **causa compartilhada**. Trouxe o critério concreto 0,5A/2,0A e a distinção total×mau-contato. Fixture `sunop__smp100__2026-07-18`. |
| Tupi Paulista (TUP) | 2C | 18/07 | 20 inv / 400 strings | Usina MUITO saudável: 399 normais, 0 parado. 1 ocorrência: **Inversor 2.2 / ST_27** — rampa de amanhecer normal (0,00A→0,35A às 07:57), queda a ~0 entre 08:02–08:22, recuperação total (9,7A às 09:30), irmãs 4,6A no período → **ambiental (nuvem)**, não falha. Fixture `owen__tupi-paulista__2026-07-18`. |

**GOTCHA do gabarito TUP:** a seção 1.2 diz "queda entre 08:02 e 08:22 (20 min)" mas a tabela da seção 2 diz "07:52–08:22, 30 min". Inconsistência interna do próprio gabarito na janela exata — a régua não precisa bater o minuto, mas vale lembrar que o gabarito é frouxo aqui.

## Insumo para construir a régua
- A curva crua já sai pronta pelo CSV (`inversor,string,hora,corrente_A`) — formato longo, mediana por inversor é trivial de calcular.
- Ver [[apipv-strings-curva-csv]] (o export) e [[strings-subabas-problema-ocorrencias]] (a régua atual da janela do Levi).


## 4ª categoria: possível falha de TRACKER refletida na string (Sete Lagoas)

O gabarito Sete Lagoas (STL, 2C, 18/07) introduziu uma assinatura distinta das elétricas: **declínio GRADUAL e conjunto** de um subgrupo de strings do mesmo inversor, que NÃO é queda abrupta (elétrica) nem dip isolado que recupera (ambiental). Causa provável: **tracker travado num ângulo fixo** — a corrente cai suave pela lei do cosseno conforme o sol se afasta do ângulo travado (≠ borda abrupta de sombra física).

### Tabela de assinaturas (§3.3 — referência de classificação)

| Assinatura | Padrão | Interpretação | Exemplo |
|---|---|---|---|
| **Falha elétrica permanente** | queda abrupta, patamar zero absoluto, sem recuperação | desconexão total / mau contato | TIM100, SMP100 |
| **Causa ambiental transitória** | queda breve isolada, rampas saudáveis antes/depois, recupera total | nuvem passageira | TUP |
| **Possível falha de tracker** | declínio suave e gradual de um subgrupo, coincide com ângulo se afastando do sol | tracker travado (confirmar c/ ângulo) | Sete Lagoas |
| **Sombreamento estrutural fixo** | transição de sombra mais definida quando o sol cruza um ponto | obstáculo físico (vegetação/estrutura) | hipótese alternativa |

**Confirmação DEFINITIVA (§3.2):** cruzar os horários da queda gradual com o **arquivo de ângulo do tracker** da usina/data. Como já temos a régua de trackers (`trk_regua_v2.py`), o cruzamento string×tracker é o método preferencial e a ponte natural entre as duas réguas.

### Implementação na régua (strings_regua_v2.py)
- Classe `tracker` sub `vespertino`: queda que TOCA o fim da produção do inversor (parada precoce, não volta) sem tocar o início → ângulo travado à tarde. Pega os 5 casos vespertinos de Sete Lagoas (Inv 1.9/1.10), agrupados por inversor.
- O caso `matinal` (partida atrasada no amanhecer, Sete Lagoas ST_11) NÃO é separável de um dip de nuvem só pela string (quebra o TUP) → cai como `ocorrencia/ambiental`; precisa do cruzamento com o tracker p/ confirmar.

| Sete Lagoas (STL) | 2C | 18/07 | 10 inv / 236 strings | 0 elétrica; 5 tracker vespertino (declínio cosseno, Inv 1.9+1.10) + 1 matinal (ST_11) como ambiental. Fixture `owen__sete-lagoas__2026-07-18`. |
