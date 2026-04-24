# GUI Toolbar and Window Polish

Commit: `this commit`

## What this block changed

- aligned Analysis panel icon-only controls and embedded Matplotlib toolbar buttons across light and dark themes
- retinted embedded Analysis toolbar icons from the live active theme
- reset Viewer panel framing only when a new optic is loaded, while preserving view state for normal optic updates
- hardened the frameless-window event filter against failures from deleted Qt wrappers and delegated event-filter paths
- slightly reduced grouped Lens Editor row background intensity for calmer contrast

## What it does for the user

- left-side Analysis plot toolbar buttons now look and react like the right-side Analysis controls
- Analysis toolbar icons remain readable after live theme changes
- loading a new system reframes the viewers, while routine changes no longer force a full reset
- shutdown and widget teardown paths are less likely to surface Qt wrapper errors
- grouped Lens Editor rows read less heavily in the table

## How it is used

- use the Analysis panel plot toolbar and right-side controls in either theme
- load a new optic to reset viewer framing, then edit the optic without losing the current view framing
- close or refresh GUI windows during normal interaction without event-filter teardown noise

## Tests

- `tests/gui/test_analysis_panel.py`
  - verifies Analysis controls use icon-only tool buttons, embedded toolbar geometry, live-theme icon tinting, and visible-toolbar QSS targeting
- `tests/gui/test_viewer_panel.py`
  - verifies optic load resets original views while optic changes preserve the current viewer framing
- `tests/gui/test_frameless_window.py`
  - verifies frameless-window event filtering tolerates deleted-wrapper and delegated super-path failures
