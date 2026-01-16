"""Qt helpers for building consistent OnePiece panels and menus."""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable, Sequence, Tuple, cast

import structlog

log = structlog.get_logger(__name__)

QtCore: Any | None = None
QtGui: Any | None = None
QtWidgets: Any | None = None

# PySide2 is preferred, but fall back to other Qt bindings when present.
_QT_BINDINGS = (
    ("PySide2", "QtCore", "QtGui", "QtWidgets"),
    ("PySide6", "QtCore", "QtGui", "QtWidgets"),
    ("PyQt6", "QtCore", "QtGui", "QtWidgets"),
    ("PyQt5", "QtCore", "QtGui", "QtWidgets"),
)


@dataclass(frozen=True, slots=True)
class MenuAction:
    """Describe an action rendered as a menu item or button."""

    label: str
    callback: Callable[[], None]
    description: str | None = None
    icon: str | None = None
    shortcut: str | None = None


@dataclass(frozen=True, slots=True)
class _QtBundle:
    core: Any
    gui: Any
    widgets: Any


def _import_qt_modules() -> _QtBundle | None:
    """Return available Qt modules if any supported binding is installed."""

    for package, core_name, gui_name, widgets_name in _QT_BINDINGS:
        if importlib.util.find_spec(package) is None:
            continue
        try:
            core = importlib.import_module(f"{package}.{core_name}")
            gui = importlib.import_module(f"{package}.{gui_name}")
            widgets = importlib.import_module(f"{package}.{widgets_name}")
        except Exception:  # pragma: no cover - depends on host environment
            log.debug("ui_core.qt_import_failed", binding=package, exc_info=True)
            continue
        return _QtBundle(core=core, gui=gui, widgets=widgets)
    return None


if QtCore is None or QtWidgets is None or QtGui is None:
    bundle = _import_qt_modules()
    if bundle:
        QtCore, QtGui, QtWidgets = bundle.core, bundle.gui, bundle.widgets


_WidgetBase: type[Any]

if TYPE_CHECKING:
    from PySide2 import QtWidgets as _QtWidgets

    _WidgetBase = _QtWidgets.QWidget
else:
    if QtWidgets is not None:
        _WidgetBase = cast(type[Any], QtWidgets.QWidget)
    else:

        class _PlaceholderWidget:
            def __init__(self, *_: object, **__: object) -> None:  # pragma: no cover
                pass

        _WidgetBase = _PlaceholderWidget


# We expose this in the public API to allow adapters to fail fast with a good message.
def require_qt_modules() -> Tuple[Any, Any, Any]:
    """Return QtCore, QtGui, QtWidgets or raise a helpful error."""

    if QtCore is None or QtGui is None or QtWidgets is None:
        raise RuntimeError(
            "Qt bindings (PySide2/PySide6/PyQt) are unavailable; UI cannot be created"
        )
    return cast(Any, QtCore), cast(Any, QtGui), cast(Any, QtWidgets)


class BasePanel(_WidgetBase):  # type: ignore[misc]
    """Consistent modern QWidget-based panel with OnePiece styling."""

    ACCENT_COLOR = "#4F8BFF"

    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        *,
        accent: str | None = None,
        parent: object | None = None,
    ) -> None:
        _, qt_gui, qt_widgets = require_qt_modules()
        self._qt_widgets = qt_widgets
        self._qt_gui = qt_gui

        super().__init__(parent)  # type: ignore[misc]

        self._title = title
        self._subtitle = subtitle
        self._accent = accent or self.ACCENT_COLOR

        self._root_layout = self._qt_widgets.QVBoxLayout(self)
        self._root_layout.setContentsMargins(16, 16, 16, 16)
        self._root_layout.setSpacing(12)

        self._header = self._qt_widgets.QLabel(title, self)
        self._header.setProperty("class", "onepiece-header")
        if subtitle:
            self._subtitle_label = self._qt_widgets.QLabel(subtitle, self)
            self._subtitle_label.setWordWrap(True)
            self._subtitle_label.setProperty("class", "onepiece-subtitle")
        else:
            self._subtitle_label = None

        self._actions_layout = self._qt_widgets.QVBoxLayout()
        self._actions_layout.setSpacing(8)

        self._root_layout.addWidget(self._header)
        if self._subtitle_label is not None:
            self._root_layout.addWidget(self._subtitle_label)
        self._root_layout.addLayout(self._actions_layout)
        self._root_layout.addStretch(1)

        self._apply_styles()

    def add_actions(self, actions: Iterable[MenuAction]) -> list[Any]:
        """Render a series of actions as wide, elegant buttons."""

        rendered: list[Any] = []
        for action in actions:
            rendered.append(self.add_action(action))
        return rendered

    def add_action(self, action: MenuAction) -> Any:
        """Render a single action button and connect its callback."""

        button = self._qt_widgets.QPushButton(action.label, self)
        button.setCursor(self._qt_gui.QCursor(self._qt_gui.Qt.PointingHandCursor))
        button.setMinimumHeight(36)
        button.setProperty("class", "onepiece-action")
        if action.description:
            button.setToolTip(action.description)
        if action.icon:
            icon = self._qt_gui.QIcon(action.icon)
            button.setIcon(icon)
        if action.shortcut:
            button.setShortcut(action.shortcut)

        button.clicked.connect(action.callback)  # type: ignore[arg-type]
        self._actions_layout.addWidget(button)
        return button

    def add_section(self, title: str, actions: Sequence[MenuAction]) -> None:
        """Add a titled block of actions."""

        section_title = self._qt_widgets.QLabel(title, self)
        section_title.setProperty("class", "onepiece-section")
        self._actions_layout.addWidget(section_title)
        for action in actions:
            self.add_action(action)

    def _apply_styles(self) -> None:
        """Apply a subtle, modern stylesheet to the panel."""

        palette = f"""
            QWidget#onepiecePanel {{
                background-color: #11141c;
            }}
            QLabel.onepiece-header {{
                font-size: 18px;
                font-weight: 700;
                color: #f7f9fc;
            }}
            QLabel.onepiece-subtitle {{
                font-size: 12px;
                color: #c2c8d0;
            }}
            QLabel.onepiece-section {{
                margin-top: 8px;
                font-size: 12px;
                font-weight: 600;
                color: #9fb7ff;
            }}
            QPushButton.onepiece-action {{
                border-radius: 8px;
                padding: 10px 14px;
                color: #f4f6fb;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {self._accent},
                    stop:1 #2b4c9c
                );
                border: 1px solid rgba(255, 255, 255, 0.06);
                text-align: left;
            }}
            QPushButton.onepiece-action::hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {self._accent},
                    stop:1 #5e9cff
                );
            }}
        """

        self.setObjectName("onepiecePanel")
        self.setStyleSheet(palette)


class BaseMenu:
    """Reusable menu builder that mirrors :class:`BasePanel` actions."""

    def __init__(self, title: str, *, accent: str | None = None) -> None:
        _, _, qt_widgets = require_qt_modules()
        self._qt_widgets = qt_widgets
        self._title = title
        self._accent = accent or BasePanel.ACCENT_COLOR
        self._actions: list[MenuAction] = []

    def add_action(self, action: MenuAction) -> None:
        self._actions.append(action)

    def extend(self, actions: Iterable[MenuAction]) -> None:
        for action in actions:
            self.add_action(action)

    def build_menu(self, parent: object | None = None) -> Any:
        """Create a :class:`QMenu` with OnePiece styling applied."""

        menu = self._qt_widgets.QMenu(self._title, parent)
        menu.setStyleSheet(
            "QMenu { background-color: #0d111a; color: #e6e9ef; } "
            f"QMenu::item:selected {{ background-color: {self._accent}; }}"
        )
        for action in self._actions:
            qt_action = menu.addAction(action.label, action.callback)
            if action.shortcut:
                qt_action.setShortcut(action.shortcut)
            if action.description:
                qt_action.setStatusTip(action.description)
            if action.icon:
                qt_action.setIcon(self._qt_widgets.QIcon(action.icon))
        return menu
