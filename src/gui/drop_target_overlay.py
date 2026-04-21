#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Reusable drag-and-drop visual overlay for tab widgets.

Provides ``DropTargetOverlay``, a translucent ``QFrame`` shown on top of
its parent during a drag operation. The overlay displays a centered hint
label (e.g. "Drop files here") so users get a clear visual cue that the
target accepts dropped files before they release the mouse button.

The overlay is sized to match its parent in ``resizeEvent`` and is
hidden by default. Enable/disable visibility via ``show_overlay()`` and
``hide_overlay()`` from the parent's drag handlers.

Usage:
    from gui.drop_target_overlay import DropTargetOverlay

    self._drop_overlay = DropTargetOverlay(self, hint_text="Drop files here")
    self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self._drop_overlay.show_overlay()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._drop_overlay.hide_overlay()

    def dropEvent(self, event):
        self._drop_overlay.hide_overlay()
        ...
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class DropTargetOverlay(QFrame):
    """Translucent overlay shown on top of a drop-target widget.

    Attributes:
        hint_label: Centered ``QLabel`` displaying the drop hint text.
    """

    def __init__(self, parent: QWidget, hint_text: str) -> None:
        """Create an overlay covering ``parent`` with a centered hint label.

        Args:
            parent: Widget to overlay; the overlay is reparented onto it
                and resizes with it via ``parent.installEventFilter``.
            hint_text: Localized text shown in the centered label.
        """
        super().__init__(parent)
        self.setObjectName("dropTargetOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(
            """
            QFrame#dropTargetOverlay {
                background-color: rgba(0, 120, 215, 60);
                border: 3px dashed rgba(0, 120, 215, 220);
                border-radius: 8px;
            }
            QLabel#dropTargetHint {
                color: white;
                font-size: 18px;
                font-weight: bold;
                background-color: rgba(0, 0, 0, 120);
                padding: 12px 24px;
                border-radius: 6px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.hint_label = QLabel(hint_text, self)
        self.hint_label.setObjectName("dropTargetHint")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hint_label)

        self.hide()
        parent.installEventFilter(self)
        self._sync_geometry()
        self.raise_()

    def set_hint_text(self, text: str) -> None:
        """Update the overlay hint label text."""
        self.hint_label.setText(text)

    def show_overlay(self) -> None:
        """Reveal the overlay and bring it to the top of the parent stack."""
        self._sync_geometry()
        self.raise_()
        self.show()

    def hide_overlay(self) -> None:
        """Hide the overlay."""
        self.hide()

    def eventFilter(self, watched, event) -> bool:
        """Resize overlay whenever its parent is resized."""
        from PySide6.QtCore import QEvent

        if watched is self.parent() and event.type() == QEvent.Type.Resize:
            self._sync_geometry()
        return super().eventFilter(watched, event)

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(0, 0, parent.width(), parent.height())
