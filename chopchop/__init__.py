"""Chop Chop Inc. save converter: carry a demo save over to the full game."""

import os
import sys

__version__ = "1.1.3"


def data_dir():
    """Folder holding the catalogs and the base save, from source or inside the .exe."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "data")  # PyInstaller bundle
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
