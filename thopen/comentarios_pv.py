# -*- coding: utf-8 -*-
"""Comentários escritos à mão para os dias de outubro/2026 abaixo de 100% que ficaram sem comentário (26/11/2026).

Os 42 dias da OBS 1 da Ana (perda menor que 1 ponto, sem ocorrência na Ronda COS, porque a regra é só cadastrar parada
com perda de 1 ponto ou mais), menos os 7 da Segredo: o inversor 3.5 parava de 1 a 3 h toda tarde, e esses dias foram
cadastrados na Ronda COS em 26/11 (a Ana e o dono: "Cadastra"), como os outros 13 dias de outubro do mesmo inversor. O Fernando (Thopen) pediu, em 25/11: "As inconsistências de 10 minutos, coloca um
comentário sobre isso, só pra não deixar em branco mesmo". Cada texto é o que o histórico de alarmes da PV Operation
mostra no dia ("Potência zerada" e "Queda no envio de dados", lidos em 26/11/2026, todas as páginas). Inversor N.M = sub-usina N
da PV, inversor M (o catálogo da Ronda COS). A planilha com a prova de cada dia está com o COS:
"Saidas abaixo de 1 ponto - outubro - PV Operation (26-11).xlsx".

Mais um dia: Santo Antônio da Platina em 01/10, que a Thopen explicou em 26/11 ("baixa isolação nos inversores até 9:30
mais ou menos").

O texto daqui só entra no dia que está SEM comentário: o relato do COS, a frase das OS e o comentário do BD_Thopen
vencem sempre (`operacao_mes.resposta`). O nome da usina é comparado sem acento e sem caixa ("Santo Anastacio" é o
nome do 5080)."""
import datetime as dt
import unicodedata


def _d(dia):
    return dt.date(2026, 10, dia)


COMENTARIOS = {
    # Santana do Ipanema: a PV numera os 24 inversores de 1 a 24 (o catálogo da Ronda COS vai de 1.1 a 12.2); o texto usa
    # a numeração da PV, que é a que a Thopen vê
    ("Santana do Ipanema", _d(6)): ["Inversor 20 (numeração da PV Operation) parado das 13:31 às 13:41 (10 min)."],
    ("Santana do Ipanema", _d(11)): ["Inversor 3 (numeração da PV Operation) parado das 09:05 às 09:14 (9 min)."],
    ("Santana do Ipanema", _d(18)): ["Inversor 21 (numeração da PV Operation) com potência zerada das 13:22 às 13:32 "
                                     "(10 min); o contador de energia do supervisório mostra que ele gerou nesse intervalo.",
                                     "Inversor 24 desligou às 17:12, 10 min antes dos outros."],
    ("Santana do Ipanema", _d(27)): ["Inversor 2 (numeração da PV Operation) parado das 11:54 às 12:04 (10 min).",
                                     "Os 24 inversores zeraram às 08:30 por menos de 2 min.",
                                     "Estação solarimétrica sem comunicação das 10:05 às 10:42."],
    ("Santana do Ipanema", _d(28)): ["Inversor 16 (numeração da PV Operation) parado das 10:14 às 10:23 (9 min)."],
    ("Santana do Ipanema", _d(29)): ["Inversor 3 (numeração da PV Operation) parado das 09:30 às 09:40 (10 min)."],

    ("Lyon", _d(2)): ["Inversor 4.1 (Sol Maior GD IV) parado das 09:10 às 09:15 (5 min)."],
    ("Lyon", _d(16)): ["Nenhum inversor parou. Estação solarimétrica do GD IV sem comunicação das 09:05 às 10:27 "
                       "(1 h 22)."],
    ("Lyon", _d(21)): ["Inversor 1.5 (Sol Maior GD I) parado das 09:10 às 09:15 (5 min)."],
    ("Lyon", _d(22)): ["Inversor 2.5 (Sol Maior GD II) parado das 09:10 às 09:15 (5 min).",
                       "Estação solarimétrica do GD IV sem comunicação das 16:29 às 17:29."],
    ("Lyon", _d(24)): ["Inversor 4.2 (Sol Maior GD IV) parado das 17:20 às 17:25 (5 min), perto do pôr do sol."],
    ("Lyon", _d(29)): ["Inversor 1.4 (Sol Maior GD I) parado das 09:40 às 09:45 (5 min)."],

    ("Santo Anastácio", _d(3)): ["Inversor 1.1 com quedas repetidas das 10:00 às 15:16 (a maior das 10:00 às 10:23; "
                                 "cerca de 52 min no total).",
                                 "Inversor 1.3 com 5 quedas curtas (cerca de 13 min no total).",
                                 "Inversores sem comunicação até 08:42."],
    ("Santo Anastácio", _d(9)): ["Inversor 1.1 parado das 11:57 às 12:07 (10 min)."],
    ("Santo Anastácio", _d(15)): ["Inversor 1.1 parado das 09:52 às 09:57 e das 10:04 às 10:31 (27 min)."],

    ("Cambé", _d(21)): ["Entre 12:58 e 16:03, 10 inversores pararam um depois do outro, de 4 a 22 min cada: 1.2, 1.1, "
                        "1.3, 1.4, 1.5, 1.12, 1.11, 1.10, 1.16 (duas vezes) e 1.9."],
    ("Cambé", _d(23)): ["Entre 10:15 e 11:24, 6 inversores pararam um depois do outro, de 3 a 21 min cada: 1.15, 1.8, "
                        "1.14, 1.7, 1.13 e 1.6."],

    ("Pharma IV", _d(13)): ["Inversor 1.6 partiu às 08:40 e o 1.2 às 08:14 (os outros às 06:30).",
                            "Cinco dos 6 inversores zeraram das 11:23 às 11:25 e das 11:28 às 11:30."],
    ("Pharma IV", _d(15)): ["Inversor 1.6 partiu às 08:47 (os outros às 06:02)."],

    ("Sítio dos Nogueiras", _d(4)): ["Inversores 2.1 e 2.2 com quedas repetidas das 08:34 às 14:19, de 2 a 27 min cada "
                                     "(cerca de 1 h no 2.1 e 1 h 20 no 2.2).",
                                     "Inversores 2.4 e 3.1 com quedas de 2 a 5 min."],
    ("Sítio dos Nogueiras", _d(24)): ["Inversor 2.2 parado das 12:33 às 12:51, das 13:11 às 13:24 e das 14:06 às 14:14.",
                                      "Inversor 3.1 com 16 quedas de 2 min entre 08:52 e 13:56."],

    ("Pharma II", _d(29)): ["A usina partiu às 07:37 e o inversor 1.3 às 08:42, 1 h 05 depois dos outros."],

    ("Santo Antônio da Platina", _d(1)): ["Baixa isolação nos inversores até cerca de 09:30 (informado pela Thopen)."],
    ("Santo Antônio da Platina", _d(29)): ["Partida tardia: a sub-usina 1 partiu às 08:00 e a 2 às 06:59.",
                                           "Inversor 1.1 partiu às 09:02 e os 1.2 e 1.13 às 08:40; os 2.1 e 2.5, cerca "
                                           "de 20 min depois dos outros."],

    ("Álvares Machado", _d(14)): ["Inversor 1.1 parado das 17:12 às 17:29 (17 min) e de novo a partir das 17:57, antes "
                                  "dos outros (18:16)."],
    ("Itajá", _d(14)): ["Inversor 2.1 parado das 10:34 às 11:19 (45 min)."],

    ("Ouro Branco III", _d(18)): ["Sem parada registrada: os 4 inversores geraram normalmente na PV Operation e no "
                                  "supervisório."],
    ("Ouro Branco V", _d(26)): ["Os 4 inversores zeraram das 11:32 às 11:34 (2 min), no mesmo minuto em que zeraram os "
                                "dos Ouro Branco I e II."],

    ("Ceilândia 1", _d(8)): ["SKID 2 inversor 4 parado das 17:12 às 17:33 (21 min) e SKID 2 inversor 2 das 17:04 às 17:08.",
                             "SKID 5 inversor 8 parado das 17:38 às 17:44 (6 min)."],
    ("Céu Azul", _d(1)): ["Seis inversores partiram tarde: o 3.1 às 08:59, o 1.5, o 2.5 e o 3.8 às 07:37, o 2.7 e o 2.8 "
                          "às 07:25 e o 1.2 às 06:35 (os outros entre 06:15 e 06:25)."],
    ("Guatambu", _d(5)): ["Inversor 2.5 partiu às 09:19 e o 3.1 às 07:58 (os outros às 06:08).",
                          "Inversor 1.3 desligou às 17:58, 19 min antes dos outros."],
    ("Junco", _d(23)): ["Inversor 1.1 parado das 15:20 às 15:34 (14 min)."],
    ("Nova Londrina", _d(27)): ["Nova Londrina 2, inversor 3: a PV Operation mostrou potência zerada entre 09:40 e 16:13, "
                                "com intermitência (cerca de 1 h 30 no total), mas o contador de energia do supervisório "
                                "mostra que ele gerou normalmente no dia (1.471 kWh, contra 1.470 kWh de mediana dos outros "
                                "inversores). A perda vem da leitura da PV: o inversor tem falha de comunicação em tratamento.",
                                "Estação solarimétrica sem comunicação das 10:03 às 10:38."],
    ("Primavera", _d(25)): ["Primavera 2, inversor 3, parado das 14:15 às 14:20 (5 min)."],
    ("Tanabi", _d(5)): ["13 inversores partiram de 40 min a 1 h depois dos outros (por volta de 06:10): 1.1, 1.2, 1.3, "
                        "1.6, 1.7 e 1.17 às 07:00–07:13; 1.11, 1.18, 2.12, 2.13, 2.15, 2.18 e 2.19 às 06:51–06:53.",
                        "Inversores 1.5, 1.7 e 2.3 parados das 17:16 às 17:35 (19 min)."],
    ("São Bento do Una", _d(27)): ["Nenhum inversor parou. Estação solarimétrica sem comunicação das 10:06 às 10:42 "
                                   "(36 min)."],
}


# 26/11/2026, conferência comentário × disponibilidade: dias que já têm comentário (do COS), mas em que ele não explica a
# perda. O texto daqui vai DEPOIS do comentário do dia, sem tirar nada. Nova Londrina: a PV zera o inversor 3 da Nova
# Londrina 2 (NVL200-INVR1.3, falha de comunicação aberta desde março, OS 19685) e a perda da Thopen segue esse zero, mas o
# contador de energia do supervisório (coletor NOLOB, modbus 10) dá ao inversor a mesma energia dos outros, todo dia.
_LEIT = ("Nova Londrina 2, inversor 3: a PV Operation mostrou potência zerada {janela}, mas o contador de energia do "
         "supervisório mostra que ele gerou normalmente no dia ({kwh} kWh, contra {med} kWh de mediana dos outros inversores). "
         "A perda vem da leitura da PV: o inversor tem falha de comunicação em tratamento.")
COMPLEMENTOS = {
    ("Nova Londrina", _d(2)): ["Nova Londrina 2, inversor 3: a PV Operation mostrou potência zerada das 11:32 às 12:05 e das "
                               "12:42 às 12:57. O supervisório não tem leitura neste dia; é o inversor com falha de "
                               "comunicação em tratamento, que nos outros dias do mês gerou normalmente pelo contador de energia."],
    ("Nova Londrina", _d(3)): [_LEIT.format(janela="entre 10:22 e 12:44, com intermitência", kwh="1.367", med="1.369")],
    ("Nova Londrina", _d(7)): [_LEIT.format(janela="das 08:07 às 10:05, das 11:02 às 11:09 e das 16:32 às 17:00", kwh="2.015", med="2.039")],
    ("Nova Londrina", _d(17)): [_LEIT.format(janela="entre 07:40 e 13:23, com intermitência, e das 17:00 às 17:06", kwh="1.978", med="2.018")],
    ("Nova Londrina", _d(18)): [_LEIT.format(janela="entre 07:17 e 17:06, com intermitência", kwh="2.466", med="2.489")],
    ("Nova Londrina", _d(20)): [_LEIT.format(janela="entre 07:23 e 11:47 e das 15:00 às 15:41", kwh="2.404", med="2.430")],
    ("Nova Londrina", _d(21)): [_LEIT.format(janela="das 12:50 às 13:00, das 13:52 às 14:04 e das 15:49 às 16:08", kwh="1.146", med="1.152")],
    ("Nova Londrina", _d(22)): [_LEIT.format(janela="das 08:43 às 09:16", kwh="1.057", med="1.078")],
    ("Nova Londrina", _d(23)): [_LEIT.format(janela="das 11:14 às 11:24", kwh="1.238", med="1.270"),
                                "No fim da tarde, a geração caiu aos poucos com o tempo fechado, de cerca de 850 kW às 15:45 "
                                "até zerar às 17:15, sem desligamento; a PV registrou potência zerada nos inversores da "
                                "Nova Londrina 1 das 17:17 às 18:23."],
    ("Nova Londrina", _d(24)): [_LEIT.format(janela="entre 08:36 e 12:22, com intermitência", kwh="1.962", med="1.979")],
    ("Nova Londrina", _d(25)): [_LEIT.format(janela="das 15:55 às 16:06", kwh="959", med="944")],
    ("Nova Londrina", _d(26)): [_LEIT.format(janela="entre 07:26 e 17:14, com intermitência", kwh="2.493", med="2.570")],
    ("Mandaguaçu", _d(12)): ["Inversor 4.4 só partiu às 09:41, 2 h 25 depois dos outros (07:16), confirmado pelo "
                             "supervisório (09:45)."],
}


def _chave(nome):
    s = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode()
    s = " ".join(s.lower().split())
    return {"santo antonio do platina": "santo antonio da platina"}.get(s, s)   # os dois nomes do 5080


_POR_USINA = {}
for (_u, _dia), _linhas in COMENTARIOS.items():
    _POR_USINA.setdefault(_chave(_u), {})[_dia] = list(_linhas)


_COMPL_POR_USINA = {}
for (_u, _dia), _linhas in COMPLEMENTOS.items():
    _COMPL_POR_USINA.setdefault(_chave(_u), {})[_dia] = list(_linhas)


def por_dia(nome, ano, mes):
    """{dia: [linhas]} da usina no mês; {} sem texto. Cópias (a tela pode mexer na lista)."""
    return {d: list(v) for d, v in (_POR_USINA.get(_chave(nome)) or {}).items() if (d.year, d.month) == (ano, mes)}


def complementos(nome, ano, mes):
    """{dia: [linhas]} que vão DEPOIS do comentário do dia (o do COS fica inteiro); {} sem texto."""
    return {d: list(v) for d, v in (_COMPL_POR_USINA.get(_chave(nome)) or {}).items() if (d.year, d.month) == (ano, mes)}
