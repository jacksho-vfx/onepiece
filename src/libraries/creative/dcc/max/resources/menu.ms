-- OnePiece 3ds Max bootstrap menu.
-- Run this script inside 3ds Max to expose the Python-driven OnePiece panel and menu.

if python != undefined do
(
    python.execute "from libraries.creative.dcc.max.adapter import build_menu, build_panel\n" +
        "menu = build_menu()\n" +
        "panel = build_panel()\n" +
        "menu.popup()\n" +
        "panel.show()"
)
