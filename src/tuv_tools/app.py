"""应用入口。"""

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .config import RESOURCES_DIR
from .ui.startup_controller import StartupController


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(RESOURCES_DIR / "favicon.ico")))
    controller = StartupController()
    controller.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
