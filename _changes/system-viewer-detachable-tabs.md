# System View in the System Viewer, Detachable Viewer Tabs

Branch: `master`

## What this block changed

- `optiland_gui/widgets/detachable_tabs.py`: `DetachableTabWidget` -- tabs added under a stable key (`add_page`) get a button that moves the page into a `DetachedTabWindow` (owned by the main window); closing the window docks the tab again at its old place; the last docked tab has no button; window geometry is remembered per tab; `save_state` / `restore_state` describe the arrangement as JSON-friendly data; windows restored before the main window is on screen wait for it
- `optiland_gui/viewer_panel.py`: the System Viewer uses it; the System view is its first tab (`ViewerPanel(..., system_panel=...)`, keys `system`, `layout2d`, `layout3d`, `sag`); the shared 2D/3D settings panel sits beside the layout in use, docked or detached; the 3D view renders when its tab is current or its window is shown
- `optiland_gui/panel_manager.py`: no separate System dock any more (the saved dock state simply has no `NSQDock`); `show_system_panel()` brings the System tab (or its window) to the front for the sidebar button, *File → Open* of a `.olsys` and `iface.show_nsq_panel()`; `save_tab_state` / `restore_tab_state` / `attach_all_tabs`; the default layout docks every tab
- `optiland_gui/main_window.py`: the session state (`Layouts/CurrentTabs`) and every saved layout slot (`Layouts/Config<n>Tabs`) store the detached tabs and their window geometry next to the dock state; a slot saved before this change docks every tab; closing the main window hides the detached windows
- `optiland_gui/nsq_panel.py`: *System* and *Path* share one row; *Projection*, *Rays drawn* and *Fit* joined the trace row (`optiland_gui/widgets/flow_layout.py` wraps it onto a second line when the viewer is narrower than about 1150 px); the label above the Layout/Detectors/Summary tabs is gone -- the System pull-down names the system, a file that is not a sample gets its own entry; compact spin boxes and pull-downs (minimum width of the System tab 653 px, the old panel needed 1099 px)
- `tools/gui_screenshot.py`: `--panel system` raises the System tab of the System Viewer; detached tabs of the last session are docked for the grab

## What it does for the user

- the whole optical system and the 2D/3D layouts of the active path are neighbouring tabs of one viewer
- any viewer tab can go to a second screen and come back by closing its window
- Optiland reopens detached tabs where they were, and a layout slot brings back its detached windows too
- the System tab spends two rows on controls instead of four when the viewer is wide enough

## Tests

- `tests/gui/test_detachable_tabs.py` -- buttons per tab, none on the last docked tab, detach/attach order, closing a window docks and selects, remembered positions, state round trip, empty/bad state, windows waiting for a hidden owner, page activation
- `tests/gui/test_system_viewer_tabs.py` -- System view as first tab, detach buttons in the viewer, settings panel following the layout in use, 3D render in a detached window, `show_system_panel`, sidebar button, tab state keyed by widget, default layout docks all
- `tests/gui/test_main_window_layouts.py` -- layout slots and the session store and restore the detached tabs, old slots dock everything, unreadable data, close hides the windows
- `tests/gui/test_nsq_panel.py::TestCompactControls` -- one row for System/Path, no label above the tabs, view controls in the trace row, wrapping on a narrow panel, spin boxes show their values, the layout plot gets the freed height, the pull-down names a system file
