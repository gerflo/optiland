# GUI Toolbar and Window Polish

Commit: `this commit`

## What this block changed

- aligned Analysis panel icon-only controls and embedded Matplotlib toolbar buttons across light and dark themes
- retinted embedded Analysis toolbar icons from the live active theme
- reset Viewer panel framing only when a new optic is loaded, while preserving view state for normal optic updates
- coupled 3D layout ray count to the 2D layout and maps 2D line-section distributions to a full-pupil 3D trace
- deferred 3D viewer creation and rendering until the 3D tab is opened so startup does not block on VTK
- preserves ray-count semantics when mapping 2D line sections to 3D hexapolar sampling, avoiding excessive VTK ray actors
- hardened the frameless-window event filter against failures from deleted Qt wrappers and delegated event-filter paths
- slightly reduced grouped Lens Editor row background intensity for calmer contrast

## What it does for the user

- left-side Analysis plot toolbar buttons now look and react like the right-side Analysis controls
- Analysis toolbar icons remain readable after live theme changes
- loading a new system reframes the viewers, while routine changes no longer force a full reset
- 3D layout ray density follows the 2D setting without collapsing line-section choices into a flat 3D fan
- application startup no longer creates or renders the VTK 3D view before it is needed
- opening the 3D tab remains responsive for high 2D line-section ray counts
- shutdown and widget teardown paths are less likely to surface Qt wrapper errors
- grouped Lens Editor rows read less heavily in the table

## How it is used

- use the Analysis panel plot toolbar and right-side controls in either theme
- change `Num Rays` or `Distribution` in the 2D viewer settings and press `Apply` to update both 2D and 3D layouts; 2D `line_x`/`line_y` remain section views, while 3D uses full-pupil sampling
- open the `3D Layout` tab to create and render the VTK scene on demand
- for 2D line-section distributions, 3D converts the requested line count to a comparable hexapolar ring count before tracing
- load a new optic to reset viewer framing, then edit the optic without losing the current view framing
- close or refresh GUI windows during normal interaction without event-filter teardown noise

## Tests

- `tests/gui/test_analysis_panel.py`
  - verifies Analysis controls use icon-only tool buttons, embedded toolbar geometry, live-theme icon tinting, and visible-toolbar QSS targeting
- `tests/gui/test_viewer_panel.py`
  - verifies optic load resets original views while optic changes preserve the current viewer framing
  - verifies 3D rendering receives coupled 2D sampling, uses comparable full-pupil sampling for 2D line sections, refreshes when 2D settings are applied, and is deferred until the 3D tab is opened
- `tests/gui/test_frameless_window.py`
  - verifies frameless-window event filtering tolerates deleted-wrapper and delegated super-path failures
