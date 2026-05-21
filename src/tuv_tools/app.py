"""应用入口"""

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .config import RESOURCES_DIR
from .ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(RESOURCES_DIR / "favicon.ico")))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
