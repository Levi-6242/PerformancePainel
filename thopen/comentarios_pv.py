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
    ("Santana do Ipanema", _d(6)): ["Inversor 1.20 parado das 13:31 às 13:41 (10 min)."],
    ("Santana do Ipanema", _d(11)): ["Inversor 1.3 parado das 09:05 às 09:14 (9 min)."],
    ("Santana do Ipanema", _d(18)): ["Inversor 1.21 parado das 13:22 às 13:32 (10 min).",
                                     "Inversor 1.24 desligou às 17:12, 10 min antes dos outros."],
    ("Santana do Ipanema", _d(27)): ["Inversor 1.2 parado das 11:54 às 12:04 (10 min).",
                                     "Os 24 inversores zeraram às 08:30 por menos de 2 min.",
                                     "Estação solarimétrica sem comunicação das 10:05 às 10:42."],
    ("Santana do Ipanema", _d(28)): ["Inversor 1.16 parado das 10:14 às 10:23 (9 min)."],
    ("Santana do Ipanema", _d(29)): ["Inversor 1.3 parado das 09:30 às 09:40 (10 min)."],

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
    ("Nova Londrina", _d(27)): ["Nova Londrina 2, inversor 3, com potência zerada das 09:40 às 10:26, das 11:48 às 12:05, "
                                "das 12:28 às 12:40, das 12:48 às 13:00 e das 16:10 às 16:13 (cerca de 1 h 30 no total).",
                                "Estação solarimétrica sem comunicação das 10:03 às 10:38."],
    ("Primavera", _d(25)): ["Primavera 2, inversor 3, parado das 14:15 às 14:20 (5 min)."],
    ("Tanabi", _d(5)): ["13 inversores partiram de 40 min a 1 h depois dos outros (por volta de 06:10): 1.1, 1.2, 1.3, "
                        "1.6, 1.7 e 1.17 às 07:00–07:13; 1.11, 1.18, 2.12, 2.13, 2.15, 2.18 e 2.19 às 06:51–06:53.",
                        "Inversores 1.5, 1.7 e 2.3 parados das 17:16 às 17:35 (19 min)."],
    ("São Bento do Una", _d(27)): ["Nenhum inversor parou. Estação solarimétrica sem comunicação das 10:06 às 10:42 "
                                   "(36 min)."],
}


def _chave(nome):
    s = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode()
    s = " ".join(s.lower().split())
    return {"santo antonio do platina": "santo antonio da platina"}.get(s, s)   # os dois nomes do 5080


_POR_USINA = {}
for (_u, _dia), _linhas in COMENTARIOS.items():
    _POR_USINA.setdefault(_chave(_u), {})[_dia] = list(_linhas)


def por_dia(nome, ano, mes):
    """{dia: [linhas]} da usina no mês; {} sem texto. Cópias (a tela pode mexer na lista)."""
    return {d: list(v) for d, v in (_POR_USINA.get(_chave(nome)) or {}).items() if (d.year, d.month) == (ano, mes)}
