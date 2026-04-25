import os
import sys

# CRITICAL: Import torch before PyQt6 to avoid [WinError 1114] DLL initialization failure.
# This ensures Intel OpenMP and torch-core libraries are loaded before Qt's own runtime.
try:
    import torch
    # Safeguard for multiple OpenMP runtimes
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
except ImportError:
    pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from main_window import MainWindow


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Engineering Drawing Annotation Tool")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
