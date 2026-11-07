"""Configure Shiboken before PyInstaller's Qt runtime hook imports PySide6."""
import os

os.environ['PYSIDE6_OPTION_LAZY'] = '0'
