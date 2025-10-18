"""Dockable panel for discovering and selecting character rigs in Maya."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Sequence

try:  # pragma: no cover - Maya is not available in CI
    import pymel.core as pymel_core
except ModuleNotFoundError:  # pragma: no cover - replaced by maya.__init__ stub
    pymel_core = None  # type: ignore[assignment]

try:  # pragma: no cover - Maya is not available in CI
    import maya.cmds as maya_cmds
except ModuleNotFoundError:  # pragma: no cover - replaced by maya.__init__ stub
    maya_cmds = None


RigPredicate = Callable[[Any], bool]


def _node_name(node: Any) -> str:
    """Return a best-effort string representation for *node*."""

    if hasattr(node, "name") and callable(node.name):
        try:
            return str(node.name())
        except Exception:  # pragma: no cover - defensive
            pass
    return str(node)


def _default_rig_predicate(node: Any) -> bool:
    """Return ``True`` when *node* looks like a rig root."""

    has_attr = getattr(node, "hasAttr", None)
    get_attr = getattr(node, "getAttr", None)
    if callable(has_attr) and callable(get_attr):
        try:
            if has_attr("isCharacterRig") and bool(get_attr("isCharacterRig")):
                return True
        except Exception:  # pragma: no cover - defensive
            return False

    name = _node_name(node).lower()
    return name.endswith("rig") or name.endswith("_rig")


@dataclass(frozen=True)
class RigDescriptor:
    """Metadata describing a discovered rig."""

    name: str
    node: Any
    namespace: str | None = None

    @classmethod
    def from_node(cls, node: Any) -> "RigDescriptor":
        name = _node_name(node)
        namespace: str | None = None
        if ":" in name:
            namespace = name.split(":", 1)[0]
        return cls(name=name, node=node, namespace=namespace)

    def matches_filter(self, query: str) -> bool:
        """Return ``True`` if *query* matches the rig name or namespace."""

        if not query:
            return True
        lowered = query.lower()
        if lowered in self.name.lower():
            return True
        if self.namespace and lowered in self.namespace.lower():
            return True
        return False

    def selection_target(self) -> str:
        """Return the identifier passed to ``maya.cmds.select``."""

        node = self.node
        if hasattr(node, "name") and callable(node.name):
            try:
                return str(node.name())
            except Exception:  # pragma: no cover - defensive
                pass
        return str(node)

    @property
    def display_label(self) -> str:
        if self.namespace and not self.name.startswith(f"{self.namespace}:"):
            return f"{self.namespace}:{self.name}"
        return self.name


def discover_rigs(
    pm: Any | None = None,
    predicate: RigPredicate | None = None,
) -> List[RigDescriptor]:
    """Return a list of :class:`RigDescriptor` instances in the current scene."""

    pm = pm or pymel_core
    if pm is None:
        raise RuntimeError("PyMEL is not available; cannot discover rigs")

    predicate = predicate or _default_rig_predicate

    assemblies: Iterable[Any] = pm.ls(assemblies=True)
    rigs = [RigDescriptor.from_node(node) for node in assemblies if predicate(node)]
    rigs.sort(key=lambda rig: rig.name.lower())
    return rigs


class CharacterSelectorPanel:
    """Manage the dockable UI that lists discovered rigs."""

    PANEL_NAME = "onepieceCharacterSelector"
    UI_TITLE = "Character Selector"

    def __init__(self, pm: Any | None = None, cmds: Any | None = None):
        self.pm = pm or pymel_core
        self.cmds = cmds or maya_cmds
        if self.pm is None or self.cmds is None:
            raise RuntimeError("Maya commands are unavailable; cannot build panel")

        self._rigs: List[RigDescriptor] = []
        self._filtered_rigs: List[RigDescriptor] = []
        self._filter_query: str = ""

    @property
    def rigs(self) -> Sequence[RigDescriptor]:
        return tuple(self._rigs)

    @property
    def filtered_rigs(self) -> Sequence[RigDescriptor]:
        return tuple(self._filtered_rigs)

    def refresh(self) -> None:
        """Refresh discovered rigs from the current Maya scene."""

        self._rigs = discover_rigs(self.pm)
        self.apply_filter(self._filter_query)

    def apply_filter(self, query: str = "") -> Sequence[RigDescriptor]:
        """Filter the rig list and return the filtered rigs."""

        self._filter_query = query
        lowered = query.strip().lower()
        if not lowered:
            self._filtered_rigs = list(self._rigs)
        else:
            self._filtered_rigs = [
                rig for rig in self._rigs if rig.matches_filter(lowered)
            ]
        return self.filtered_rigs

    def build_selection_actions(self) -> List[Callable[[], None]]:
        """Return callables that select each filtered rig when invoked."""

        return [self._make_selection_callback(rig) for rig in self._filtered_rigs]

    def _make_selection_callback(self, rig: RigDescriptor) -> Callable[[], None]:
        def _callback() -> None:
            self.select_rig(rig)

        return _callback

    def select_rig(self, rig: RigDescriptor) -> None:
        """Select *rig* in Maya."""

        target = rig.selection_target()
        self.cmds.select(target, replace=True)

    def show(self, dock: bool = True) -> Any:
        """Create the Maya UI for the panel and return the control name."""

        self.refresh()

        cmds = self.cmds
        panel_name = self.PANEL_NAME
        title = self.UI_TITLE

        if hasattr(cmds, "workspaceControl") and dock:
            if cmds.workspaceControl(panel_name, exists=True):
                cmds.deleteUI(panel_name)
            control = cmds.workspaceControl(panel_name, label=title, retain=False)
            self._build_control_contents()
            return control

        if cmds.window(panel_name, exists=True):
            cmds.deleteUI(panel_name)
        window = cmds.window(panel_name, title=title)
        cmds.columnLayout(adjustableColumn=True)
        for rig in self._filtered_rigs:
            cmds.button(
                label=rig.display_label,
                command=lambda *_args, _rig=rig: self.select_rig(_rig),
            )
        cmds.showWindow(window)
        return window

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _build_control_contents(self) -> None:
        """Populate the docked workspace control with rig buttons."""

        cmds = self.cmds
        if not hasattr(cmds, "columnLayout"):
            return

        cmds.setParent(self.PANEL_NAME)
        cmds.columnLayout(adjustableColumn=True)
        for rig in self._filtered_rigs:
            cmds.button(
                label=rig.display_label,
                command=lambda *_args, _rig=rig: self.select_rig(_rig),
            )

    @classmethod
    def show_panel(
        cls, dock: bool = True, pm: Any | None = None, cmds: Any | None = None
    ) -> "CharacterSelectorPanel":
        """Convenience factory that creates and shows the panel."""

        panel = cls(pm=pm, cmds=cmds)
        panel.show(dock=dock)
        return panel


__all__ = ["RigDescriptor", "discover_rigs", "CharacterSelectorPanel"]
