from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Sequence, cast

import importlib
import importlib.util
import runpy

import structlog


log = structlog.get_logger(__name__)

QtCore: Any | None = None
QtWidgets: Any | None = None


def _optional_qt_modules() -> tuple[object | None, object | None]:
    """Return PySide2 Qt modules if available without raising."""

    if importlib.util.find_spec("PySide2") is None:
        return None, None

    from PySide2 import QtCore as qt_core  # type: ignore
    from PySide2 import QtWidgets as qt_widgets  # type: ignore

    return qt_core, qt_widgets


QtCore, QtWidgets = _optional_qt_modules()

if TYPE_CHECKING:
    from PySide2 import QtWidgets as _QtWidgets

    _WidgetBase = _QtWidgets.QWidget
else:
    _WidgetBase: type[Any] = object
    if QtWidgets is not None:
        _WidgetBase = cast(type[Any], QtWidgets.QWidget)

ScriptAction = Callable[[], None]


@dataclass(frozen=True)
class ScriptDefinition:
    """Describe a runnable script entry in the launcher."""

    label: str
    action: ScriptAction
    description: str | None = None

    def run(self) -> None:
        """Execute the configured action."""

        self.action()

    @classmethod
    def from_path(
        cls, path: Path, *, description: str | None = None
    ) -> "ScriptDefinition":
        """Build a script definition that executes a Python file on selection."""

        normalized = path.expanduser().resolve()

        def _execute_path() -> None:
            log.info("nuke_script_launcher_running_script", path=str(normalized))
            runpy.run_path(str(normalized), run_name="__main__")

        label = normalized.stem.replace("_", " ").title()
        return cls(label=label, action=_execute_path, description=description)


_DEFAULT_SCRIPTS: list[ScriptDefinition] = []
_DEFAULT_SCRIPT_DIRECTORY: Path | None = None


def configure_script_launcher_defaults(
    scripts: Sequence[ScriptDefinition] | None = None,
    script_directory: Path | None = None,
) -> None:
    """Set module-level defaults for the launcher plugin."""

    global _DEFAULT_SCRIPTS, _DEFAULT_SCRIPT_DIRECTORY
    _DEFAULT_SCRIPTS = list(scripts or [])
    _DEFAULT_SCRIPT_DIRECTORY = script_directory


def discover_script_definitions(directory: Path) -> list[ScriptDefinition]:
    """Return launcher definitions for each Python file in *directory*.

    Files are sorted alphabetically to ensure a predictable dropdown order and
    ``material_harmonizer.py`` is ignored.
    """

    if not directory.exists() or not directory.is_dir():
        return []

    definitions: list[ScriptDefinition] = []
    for path in sorted(directory.glob("*.py")):
        if path.name == "material_harmonizer.py":
            continue
        definitions.append(ScriptDefinition.from_path(path))
    return definitions


class ScriptLauncherWidget(_WidgetBase):  # type: ignore[misc, valid-type]
    """Nuke panel that presents a dropdown of runnable scripts."""

    PANEL_ID = "com.onepiece.nuke.script_launcher"
    PANEL_NAME = "Script Launcher"

    def __init__(
        self,
        scripts: Sequence[ScriptDefinition] | None = None,
        script_directory: Path | None = None,
        parent: object | None = None,
    ) -> None:
        if QtWidgets is None or QtCore is None:
            raise RuntimeError(
                "PySide2 Qt bindings are unavailable; cannot build Script Launcher panel"
            )

        super().__init__(parent)  # type: ignore[misc]

        directory = script_directory or _DEFAULT_SCRIPT_DIRECTORY
        provided = list(scripts or _DEFAULT_SCRIPTS)
        discovered = discover_script_definitions(directory) if directory else []
        self._scripts: list[ScriptDefinition] = provided + discovered

        self._script_combo = QtWidgets.QComboBox(self)
        self._description_label = QtWidgets.QLabel(self)
        self._status_label = QtWidgets.QLabel(self)
        self._run_button = QtWidgets.QPushButton("Run Script", self)
        self._refresh_button = QtWidgets.QPushButton("Refresh", self)

        self._build_ui()
        self._populate_scripts()

    def _build_ui(self) -> None:
        assert QtWidgets is not None and QtCore is not None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        header = QtWidgets.QLabel("OnePiece Script Launcher", self)
        header.setProperty("class", "header")
        subtitle = QtWidgets.QLabel(
            "Choose a utility script to run inside Nuke."
            " Keep your favorite tools within reach.",
            self,
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("class", "subtitle")

        self._script_combo.setPlaceholderText("Select a script to run…")
        self._script_combo.currentIndexChanged.connect(self._update_description)

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self._script_combo, stretch=1)
        controls.addWidget(self._refresh_button)
        controls.addWidget(self._run_button)

        self._run_button.clicked.connect(self.execute_selected_script)
        self._refresh_button.clicked.connect(self._populate_scripts)

        self._description_label.setWordWrap(True)
        self._description_label.setProperty("class", "description")

        self._status_label.setWordWrap(True)
        self._status_label.setProperty("class", "status")

        layout.addWidget(header)
        layout.addWidget(subtitle)
        layout.addLayout(controls)
        layout.addWidget(self._description_label)
        layout.addWidget(self._status_label)
        layout.addStretch(1)

        self._apply_styles()

    def _populate_scripts(self) -> None:
        assert QtWidgets is not None

        self._script_combo.blockSignals(True)
        self._script_combo.clear()
        for definition in self._scripts:
            self._script_combo.addItem(definition.label)
        self._script_combo.blockSignals(False)
        self._update_description(self._script_combo.currentIndex())
        self._set_status("Select a script to run.")

    def _update_description(self, index: int) -> None:
        if index < 0 or index >= len(self._scripts):
            self._description_label.setText("")
            return

        definition = self._scripts[index]
        self._description_label.setText(
            definition.description or "Ready to execute this script."
        )

    def _apply_styles(self) -> None:
        palette = (
            "QWidget {"
            "    background-color: #18181b;"
            "    color: #e5e7eb;"
            "    font-size: 12px;"
            "    font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;"
            "}"
            "QLabel[class='header'] {"
            "    font-size: 16px;"
            "    font-weight: 600;"
            "    color: #f8fafc;"
            "}"
            "QLabel[class='subtitle'] {"
            "    color: #cbd5e1;"
            "}"
            "QComboBox {"
            "    padding: 8px 10px;"
            "    border-radius: 8px;"
            "    border: 1px solid #27272a;"
            "    background-color: #1f2937;"
            "}"
            "QComboBox::drop-down {"
            "    border: none;"
            "}"
            "QPushButton {"
            "    padding: 8px 12px;"
            "    border-radius: 8px;"
            "    background-color: #2563eb;"
            "    color: #f8fafc;"
            "    border: 0;"
            "    font-weight: 600;"
            "}"
            "QPushButton:hover {"
            "    background-color: #1d4ed8;"
            "}"
            "QPushButton:pressed {"
            "    background-color: #1e3a8a;"
            "}"
            "QLabel[class='description'] {"
            "    padding: 8px;"
            "    background-color: #111827;"
            "    border-radius: 8px;"
            "    border: 1px solid #27272a;"
            "}"
            "QLabel[class='status'] {"
            "    color: #a5b4fc;"
            "}"
        )
        self.setStyleSheet(palette)

    def execute_selected_script(self) -> None:
        if not self._scripts:
            self._set_status("No scripts available to run.", is_error=True)
            return

        index = self._script_combo.currentIndex()
        if index < 0 or index >= len(self._scripts):
            self._set_status("Please choose a script before running.", is_error=True)
            return

        definition = self._scripts[index]
        try:
            definition.run()
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            log.error(
                "nuke_script_launcher_failed", script=definition.label, error=str(exc)
            )
            self._set_status(
                f"Failed to run '{definition.label}'. Check script output.",
                is_error=True,
            )
            raise

        log.info("nuke_script_launcher_completed", script=definition.label)
        self._set_status(f"Ran '{definition.label}' successfully.")

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        color = "#fca5a5" if is_error else "#a5b4fc"
        self._status_label.setText(f"<span style='color:{color}'>{message}</span>")


def register_script_launcher_panel(
    scripts: Sequence[ScriptDefinition] | None = None,
    script_directory: Path | None = None,
    *,
    panel_id: str | None = None,
    tab_name: str | None = None,
) -> str:
    """Register the script launcher as a Nuke panel plugin."""

    configure_script_launcher_defaults(scripts, script_directory)

    if importlib.util.find_spec("nukescripts") is None:
        raise RuntimeError("nukescripts module is unavailable; cannot register panel")

    nukescripts = importlib.import_module("nukescripts")
    panels = getattr(nukescripts, "panels", nukescripts)
    register = getattr(panels, "registerWidgetAsPanel")

    panel_identifier = panel_id or ScriptLauncherWidget.PANEL_ID
    tab_label = tab_name or ScriptLauncherWidget.PANEL_NAME

    return str(
        register(
            f"{__name__}.ScriptLauncherWidget",
            tab_label,
            panel_identifier,
        )
    )
