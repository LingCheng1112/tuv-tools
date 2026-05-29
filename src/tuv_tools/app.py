"""应用入口。"""

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from tuv_tools import APP_NAME
from .config import RESOURCES_DIR
from .ui.startup_controller import StartupController


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(RESOURCES_DIR / "favicon.ico")))

    from .config.database import DatabaseManager
    from .ui.theme import ThemeManager

    ThemeManager.init(DatabaseManager())
    ThemeManager.instance().start_system_watch()

    controller = StartupController()
    controller.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
