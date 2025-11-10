"""Utilities for building custom Cinema 4D command panels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol, Sequence, cast

try:  # pragma: no cover - Cinema 4D is not available in CI
    import c4d  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - replaced by tests stubs
    c4d = None  # type: ignore


CommandCallback = Callable[[], None]


class CommandDialogProtocol(Protocol):
    """Interface implemented by the dynamically generated dialog."""

    def Open(
        self,
        dlgtype: int,
        *,
        pluginid: int = ...,
        defaultw: int = ...,
        defaulth: int = ...,
    ) -> bool: ...

    def add_command(
        self, command: "CommandDefinition"
    ) -> None:  # pragma: no cover - protocol
        ...


@dataclass(frozen=True)
class CommandDefinition:
    """Describe a command displayed on the panel."""

    label: str
    callback: CommandCallback
    description: str | None = None


class CommandPanel:
    """Build and display a Cinema 4D panel with custom actions."""

    PANEL_ID = 1059991

    def __init__(self, title: str = "OnePiece Commands", module: object | None = None):
        self._title = title
        self._module = module or c4d
        if self._module is None:
            raise RuntimeError(
                "Cinema 4D Python API is unavailable; cannot build panel"
            )

        self._gui = getattr(self._module, "gui", None)
        if self._gui is None:
            raise RuntimeError(
                "Cinema 4D GUI module is unavailable; cannot build panel"
            )

        dialog_type = getattr(self._gui, "GeDialog", None)
        if not isinstance(dialog_type, type):
            raise RuntimeError("Cinema 4D GUI module does not expose GeDialog")

        self._dialog_class: type[Any] = self._create_dialog_class(dialog_type)
        self._commands: list[CommandDefinition] = []
        self._dialog: CommandDialogProtocol | None = None

    @property
    def commands(self) -> Sequence[CommandDefinition]:
        """Return the registered command definitions."""

        return tuple(self._commands)

    @property
    def dialog(self) -> CommandDialogProtocol | None:
        """Return the currently constructed dialog instance, if any."""

        return self._dialog

    def register_command(
        self, label: str, callback: CommandCallback, description: str | None = None
    ) -> CommandDefinition:
        """Register a command button for the panel and return its definition."""

        definition = CommandDefinition(
            label=label, callback=callback, description=description
        )
        self._add_definition(definition)
        return definition

    def extend(self, commands: Iterable[CommandDefinition]) -> None:
        """Register multiple commands at once."""

        for command in commands:
            self._add_definition(command)

    def show(
        self, async_open: bool = True, width: int = 400, height: int = 0
    ) -> CommandDialogProtocol:
        """Display the panel in Cinema 4D."""

        if self._dialog is None:
            dialog_class = self._dialog_class
            self._dialog = cast(
                CommandDialogProtocol,
                dialog_class(title=self._title, commands=list(self._commands)),
            )

        dialog_type = getattr(self._module, "DLG_TYPE_ASYNC", 0 if async_open else 1)
        if not async_open:
            dialog_type = getattr(self._module, "DLG_TYPE_MODAL", dialog_type)

        self._dialog.Open(
            dialog_type, pluginid=self.PANEL_ID, defaultw=width, defaulth=height
        )
        return self._dialog

    def _add_definition(self, definition: CommandDefinition) -> None:
        self._commands.append(definition)
        if self._dialog is not None:
            self._dialog.add_command(definition)

    def _create_dialog_class(self, base_dialog: type) -> type[Any]:
        panel = self

        class PanelDialog(base_dialog):  # type: ignore[misc]
            def __init__(self, title: str, commands: list[CommandDefinition]):
                super().__init__()
                self._title = title
                self._commands = list(commands)
                self._id_to_command: dict[int, CommandDefinition] = {}
                self._next_id = 1000

            # Cinema 4D expects CreateLayout to return True on success.
            def CreateLayout(
                self,
            ) -> bool:  # pragma: no cover - executed in CI via tests
                parent_create = getattr(super(), "CreateLayout", None)
                if callable(parent_create):
                    parent_create()
                self.SetTitle(self._title)
                for command in self._commands:
                    self._create_button(command)
                return True

            def add_command(self, command: CommandDefinition) -> None:
                self._commands.append(command)
                if hasattr(self, "AddButton"):
                    self._create_button(command)

            def _create_button(self, command: CommandDefinition) -> None:
                button_id = self._next_id
                self._next_id += 1
                self._id_to_command[button_id] = command
                flags = getattr(panel._module, "BFH_SCALEFIT", 0)
                self.AddButton(button_id, flags, 0, 0, command.label)
                if command.description:
                    set_tooltip = getattr(self, "SetTooltip", None)
                    if callable(set_tooltip):
                        set_tooltip(button_id, command.description)

            def Command(self, button_id: int, msg: object | None) -> bool:
                command = self._id_to_command.get(button_id)
                if command is None:
                    return False
                command.callback()
                return True

        return PanelDialog


__all__ = ["CommandDefinition", "CommandPanel"]
