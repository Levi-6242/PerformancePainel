"""Bloco reutilizável 'Esta tarefa já foi realizada?'. Marcado → a OS é criada já CONCLUÍDA
(Finalizados) ou em Verificação, com Data inicial/final e as RESPOSTAS das subtarefas (caixa de
texto por subtarefa). Usado no wizard (ResponsavelDialog) e no Várias OSs.

`com_datas=True` mostra Data inicial (= data do evento) + Data final aqui dentro (wizard).
`com_datas=False` deixa as datas por conta do host (Várias OSs usa as datas por linha)."""
from PyQt6.QtCore import Qt, QDateTime, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QRadioButton,
                             QButtonGroup, QDateTimeEdit, QLineEdit, QFrame)


class FinalizarPanel(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, subtarefas=None, com_datas=True):
        super().__init__()
        self._com_datas = com_datas
        self._resp_boxes = []
        # texto sem caixa escura; os indicadores (verde Grid + borda branca) vêm do DARK_QSS global
        self.setStyleSheet("QRadioButton, QCheckBox, QLabel { background: transparent; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.chk = QCheckBox("Esta tarefa já foi realizada?")
        self.chk.toggled.connect(self._on_toggle)
        lay.addWidget(self.chk)

        self.panel = QFrame()
        self.panel.setObjectName("finpanel")
        self.panel.setStyleSheet("QFrame#finpanel{background:#1d2130;border:1px solid #2c3142;"
                                 "border-radius:6px;}")
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(10, 8, 10, 8)
        pl.setSpacing(6)

        rrow = QHBoxLayout()
        rrow.addWidget(QLabel("Enviar para OS:"))
        self.rb_verif = QRadioButton("Verificação")
        self.rb_final = QRadioButton("Finalizados")
        self.rb_final.setChecked(True)                    # default Finalizados
        self._grp = QButtonGroup(self)
        self._grp.addButton(self.rb_verif)
        self._grp.addButton(self.rb_final)
        rrow.addWidget(self.rb_verif)
        rrow.addWidget(self.rb_final)
        rrow.addStretch(1)
        pl.addLayout(rrow)

        if com_datas:
            drow = QHBoxLayout()
            ci = QVBoxLayout()
            ci.addWidget(QLabel("Data inicial <span style='color:#8a90a2'>(= evento)</span>"))
            self.dt_ini = QDateTimeEdit(QDateTime.currentDateTime())
            self.dt_ini.setDisplayFormat("dd/MM/yyyy HH:mm")
            self.dt_ini.setCalendarPopup(True)
            ci.addWidget(self.dt_ini)
            drow.addLayout(ci)
            cf = QVBoxLayout()
            cf.addWidget(QLabel("Data final"))
            self.dt_fim = QDateTimeEdit(QDateTime.currentDateTime())
            self.dt_fim.setDisplayFormat("dd/MM/yyyy HH:mm")
            self.dt_fim.setCalendarPopup(True)
            cf.addWidget(self.dt_fim)
            drow.addLayout(cf)
            pl.addLayout(drow)

        self._subs = [str(s).strip() for s in (subtarefas or []) if str(s).strip()] or ["Procedimento"]
        pl.addWidget(QLabel("<b>Respostas das subtarefas</b> "
                            "<span style='color:#8a90a2'>(opcional)</span>"))
        for s in self._subs:
            pl.addWidget(QLabel(s))
            box = QLineEdit()
            box.setPlaceholderText("Resposta…")
            self._resp_boxes.append(box)
            pl.addWidget(box)

        self.panel.setVisible(False)
        lay.addWidget(self.panel)

    def _on_toggle(self, on):
        self.panel.setVisible(on)
        self.toggled.emit(on)   # o host decide se ajusta o tamanho (ResponsavelDialog faz adjustSize;
                                # Várias OSs usa scroll geral, não mexe na janela)

    # ── getters ──
    def is_finalizar(self):
        return self.chk.isChecked()

    def to_in_review(self):
        return self.rb_verif.isChecked()

    def data_inicial(self):
        return self.dt_ini.dateTime().toPyDateTime() if self._com_datas else None

    def data_final(self):
        return self.dt_fim.dateTime().toPyDateTime() if self._com_datas else None

    def respostas(self):
        return [b.text().strip() for b in self._resp_boxes]
