#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Qt environment bootstrap for PySide6.

This module MUST be imported before any PySide6 imports. It resolves two issues on Windows for certain users:

1. **DLL load failed** – PySide6 DLLs are not on the system ``PATH``,
   so Windows cannot locate them when importing the Qt bindings.
2. **No Qt platform plugin** – The ``platforms/qwindows.dll`` plugin
   cannot be found because ``QT_PLUGIN_PATH`` is not set.

Both problems are especially common in embedded-Python / portable builds
where PySide6 lives inside a bundled ``site-packages`` directory.

Usage (at the very top of ``Main.py``, before any other imports)::

    from utils.qt_environment import configure_qt_environment
    configure_qt_environment()

    # Now PySide6 imports will work
    from PySide6.QtWidgets import QApplication
"""

from __future__ import annotations

import os
import sys
import importlib.util
from pathlib import Path


def _find_pyside6_dir() -> Path | None:
    """Locate the PySide6 package directory without importing it.

    Returns:
        The resolved ``Path`` to the PySide6 package directory,
        or ``None`` if it cannot be found.
    """
    spec = importlib.util.find_spec("PySide6")
    if spec is not None and spec.origin is not None:
        return Path(spec.origin).resolve().parent

    # Fallback: walk ``sys.path`` looking for PySide6 manually
    for entry in sys.path:
        candidate = Path(entry) / "PySide6"
        if candidate.is_dir() and (candidate / "__init__.py").exists():
            return candidate.resolve()

    return None


def configure_qt_environment() -> None:
    """Prepare environment variables and DLL search paths for PySide6.

    This function is safe to call multiple times; it short-circuits if
    the environment has already been configured.

    The function performs three actions when the PySide6 package
    directory can be located:

    1. Sets ``QT_PLUGIN_PATH`` so Qt finds the *platforms* plugin.
    2. Prepends the PySide6 directory to ``PATH`` so Windows can find
       Qt DLLs (e.g. ``Qt6Core.dll``) at import time.
    3. On Python 3.8+ calls :func:`os.add_dll_directory` which is the
       modern mechanism for registering additional DLL search directories
       on Windows.
    """
    if os.environ.get("TA_TOOLBOX_ENV_CONFIGURED"):
        print("[Qt Environment] Already configured, skipping.")
        return

    print("[Qt Environment] Configuring Qt environment...")

    pyside6_dir = _find_pyside6_dir()
    if pyside6_dir is None:
        print("[Qt Environment] PySide6 not found — skipping configuration.")
        return

    pyside6_str = str(pyside6_dir)
    print(f"[Qt Environment] PySide6 found at: {pyside6_str}")

    plugins_dir = pyside6_dir / "plugins"
    if plugins_dir.is_dir():
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugins_dir))
        print(f"[Qt Environment] QT_PLUGIN_PATH set to: {plugins_dir}")
    else:
        print(f"[Qt Environment] WARNING: plugins directory not found at {plugins_dir}")

    current_path = os.environ.get("PATH", "")
    if pyside6_str not in current_path:
        os.environ["PATH"] = pyside6_str + os.pathsep + current_path
        print("[Qt Environment] Added PySide6 directory to PATH.")

    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(pyside6_str)
            print("[Qt Environment] Registered DLL directory (PySide6).")
        except OSError:
            print("[Qt Environment] Could not register PySide6 DLL directory.")
        if plugins_dir.is_dir():
            try:
                os.add_dll_directory(str(plugins_dir))
                print("[Qt Environment] Registered DLL directory (plugins).")
            except OSError:
                print("[Qt Environment] Could not register plugins DLL directory.")

    os.environ["TA_TOOLBOX_ENV_CONFIGURED"] = "1"
    print("[Qt Environment] Configuration complete.")
