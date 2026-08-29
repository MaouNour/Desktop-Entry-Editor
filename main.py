#!/usr/bin/env python3
"""Entry point for the Desktop Entry Editor.

Usage:
    main.py                      Open a blank new entry
    main.py FILE.desktop         Open an existing .desktop/.directory file
    (double-click a .desktop file after installing — see install.sh)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from desktop_entry_editor.app import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
