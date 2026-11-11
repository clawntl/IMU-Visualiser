import sys


def self_check():
    """Imports everything the app needs and exits, without opening a window.
    Used by CI to confirm a packaged build isn't missing any modules."""
    import importlib

    for name in (
        "PySide6.QtWidgets",
        "PySide6.QtOpenGLWidgets",
        "pyqtgraph.opengl",
        "OpenGL.GL",
        "serial.tools.list_ports",
        "stl.mesh",
        "imuviz.main_window",
    ):
        importlib.import_module(name)
    print("self-check OK")


def main():
    if "--check" in sys.argv:
        self_check()
        return

    from PySide6.QtWidgets import QApplication

    from imuviz import theme
    from imuviz.main_window import MainWindow

    theme.apply_pg_defaults()

    app = QApplication(sys.argv)
    app.setStyleSheet(theme.STYLESHEET)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
