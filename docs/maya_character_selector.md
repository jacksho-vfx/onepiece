# Maya Character Selector Panel

> **Documentation refresh (November 2025):** Animators requested faster signposts to usage snippets, rig discovery heuristics, and UI extension hooks. The outline below gathers those sections for quick reference during show-specific customisation.

## At a glance

- [Usage](#usage) — Import the panel and expose it inside Maya.
- [Rig discovery heuristics](#rig-discovery-heuristics) — Understand how rigs are detected and filtered.
- [Extending the UI](#extending-the-ui) — Hook in custom buttons, filters, or metadata displays.

The character selector panel provides a lightweight dockable UI for animators to
discover and select character rigs that exist in the current Maya scene. The
tool relies on PyMEL / `maya.cmds` for its UI but keeps the discovery logic
pure-Python so it can be unit tested without Maya. 【F:src/libraries/creative/dcc/maya/character_selector.py†L1-L120】

## Usage

```python
from libraries.creative.dcc.maya import CharacterSelectorPanel

# Launch the dockable panel. When running inside Maya this will create a
# workspace control if available, otherwise a floating window is displayed.
CharacterSelectorPanel.show_panel()
```

The panel lists the rigs discovered via :func:`discover_rigs`. Buttons are
generated for each rig and selecting one will call ``maya.cmds.select`` on the
rig root. 【F:src/libraries/creative/dcc/maya/character_selector.py†L122-L210】

## Rig discovery heuristics

Rig roots are detected using two inexpensive heuristics:

* Nodes exposing the boolean attribute ``isCharacterRig`` set to ``True`` are
  automatically included.
* Nodes whose names end with ``Rig`` or ``_Rig`` are assumed to be character
  rig roots. 【F:src/libraries/creative/dcc/maya/character_selector.py†L26-L63】

These heuristics cover most internal rigs but the discovery call can be
customised downstream by providing a predicate function when calling
``discover_rigs(pm=my_pymel, predicate=my_predicate)``.

## Extending the UI

`CharacterSelectorPanel` exposes helper methods that make it straightforward to
extend the UI:

* :meth:`CharacterSelectorPanel.apply_filter` filters the discovered rigs.
* :meth:`CharacterSelectorPanel.build_selection_actions` returns callables that
  select the filtered rigs. These actions can be wired to custom UI controls if
  the default buttons are not sufficient.

Because the module lazily imports PyMEL/Maya, it can be imported safely in
headless environments and unit tests.

