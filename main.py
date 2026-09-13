import sys

from PySide6.QtWidgets import QApplication

from imuviz import theme
from imuviz.main_window import MainWindow


def main():
    theme.apply_pg_defaults()

    app = QApplication(sys.argv)
    app.setStyleSheet(theme.STYLESHEET)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
