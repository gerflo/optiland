"""Launch the Optiland GUI off-line, drive a panel, and save screenshots.

A small automation harness for visual checks without a person at the
keyboard: it starts the real ``MainWindow``, optionally focuses a dock,
runs a non-sequential trace, and grabs the window (or a single dock) to PNG
files. Nothing is mocked, so the screenshots show what a user would see.

Examples::

    # Whole window with the Non-Sequential dock raised, after a trace
    python tools/gui_screenshot.py --panel nonsequential --trace out/nsq.png

    # Only the NSQ dock, both sample scenes, light theme
    python tools/gui_screenshot.py --panel nonsequential --dock-only \\
        --scene side_illumination --trace --theme light out/side.png

    # Every tab of the NSQ panel (suffixes _layout/_detectors/_summary)
    python tools/gui_screenshot.py --panel nonsequential --trace --all-tabs out/nsq.png
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("output", help="PNG file to write (suffixes added per tab).")
    parser.add_argument(
        "--panel",
        default=None,
        help="Sidebar panel to raise: design, analysis, nonsequential, "
        "optimization, catalogs, scripts.",
    )
    parser.add_argument(
        "--scene",
        default=None,
        help="Non-sequential sample scene key (beam_splitter, side_illumination) "
        "or a path to a scene file (.olsys or NSQ JSON).",
    )
    parser.add_argument(
        "--trace", action="store_true", help="Run a non-sequential trace first."
    )
    parser.add_argument("--rays", type=int, default=20_000, help="Rays to trace.")
    parser.add_argument("--split-depth", type=int, default=0, help="Split depth.")
    parser.add_argument(
        "--projection", default="XZ", help="Layout projection: XZ, YZ or XY."
    )
    parser.add_argument(
        "--dock-only",
        action="store_true",
        help="Grab only the raised dock instead of the whole window.",
    )
    parser.add_argument(
        "--all-tabs",
        action="store_true",
        help="Grab every tab of the non-sequential panel.",
    )
    parser.add_argument(
        "--theme", default=None, help="Theme id to apply (e.g. dark, light)."
    )
    parser.add_argument(
        "--size",
        default="1600x950",
        help="Window size WIDTHxHEIGHT in pixels (default 1600x950).",
    )
    parser.add_argument(
        "--settle-ms",
        type=int,
        default=1200,
        help="Event-loop settle time before each grab [ms].",
    )
    return parser.parse_args()


def _settle(app, ms: int) -> None:
    from PySide6.QtCore import QDeadlineTimer, QEventLoop

    deadline = QDeadlineTimer(ms)
    while not deadline.hasExpired():
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)


def _grab(widget, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not widget.grab().save(str(path)):
        raise RuntimeError(f"Could not write {path}")
    print(f"wrote {path}")


def _raise_dock(app, window, dock, settle_ms: int) -> None:
    """Bring *dock* to the front again.

    Background jobs that finish after start-up (the catalog import) raise
    their own dock, so the target is re-focused right before every grab.
    """
    if dock is None:
        return
    window.focus_dock_widget(dock)
    _settle(app, settle_ms)


def main() -> int:
    """Start the GUI, drive it as requested and write the screenshots."""
    args = _parse_args()
    sys.path.insert(0, str(_project_root()))
    os.environ.setdefault("OPTILAND_GUI_NO_SPLASH", "1")

    from PySide6.QtWidgets import QApplication

    from optiland_gui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    width, height = (int(v) for v in args.size.lower().split("x"))
    window.resize(width, height)
    window.show()
    _settle(app, args.settle_ms)

    if args.theme:
        window.switch_theme(args.theme)
        _settle(app, args.settle_ms)

    manager = window.panel_manager
    target = None
    if args.panel:
        manager.on_sidebar_menu_selected(args.panel)
        docks = {
            "design": manager.lens_editor_dock,
            "analysis": manager.analysis_dock,
            "nonsequential": manager.nsq_dock,
            "optimization": manager.optimization_dock,
            "catalogs": manager.catalog_browser_dock,
            "scripts": manager.terminal_dock,
        }
        target = docks.get(args.panel)
        _settle(app, args.settle_ms)

    nsq_panel = manager.nsq_panel
    if args.scene:
        if os.path.isfile(args.scene):
            nsq_panel.service.load_file(args.scene)
        else:
            index = nsq_panel.scene_combo.findData(args.scene)
            if index < 0:
                raise SystemExit(f"Unknown sample scene {args.scene!r}")
            nsq_panel.scene_combo.setCurrentIndex(index)
            nsq_panel.service.load_sample(args.scene)
    nsq_panel.projection_combo.setCurrentText(args.projection.upper())
    if args.trace:
        nsq_panel.rays_spin.setValue(args.rays)
        nsq_panel.split_spin.setValue(args.split_depth)
        nsq_panel.run_trace_sync()
    _settle(app, args.settle_ms)

    output = Path(args.output)
    subject = target if (args.dock_only and target is not None) else window
    if args.all_tabs:
        for index in range(nsq_panel.tabs.count()):
            nsq_panel.tabs.setCurrentIndex(index)
            _raise_dock(app, window, target, args.settle_ms)
            name = nsq_panel.tabs.tabText(index).lower()
            _grab(subject, output.with_name(f"{output.stem}_{name}{output.suffix}"))
    else:
        _raise_dock(app, window, target, args.settle_ms)
        _grab(subject, output)

    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
