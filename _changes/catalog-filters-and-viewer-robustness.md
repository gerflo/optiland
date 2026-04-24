# Catalog Filters and Viewer Robustness

Commit: `d0794a63`

## What this block changed

- added a default-on catalog filter that only shows entries with usable surface data
- improved viewer robustness for systems without a stop surface
- reduced warning noise in intermediate invalid states while editing optics

## What it does for the user

- the catalog list can default to insertable items only
- systems without a stop can still display geometry, while rays are intentionally suppressed with a warning
- transient invalid systems create less distracting warning spam

## How it is used

- use the insertable-only filter in the catalog browser
- open or build systems without a stop and inspect them in the viewer

## Tests

- `tests/gui/test_catalog_browser_panel.py`
  - verifies insertable-only filtering and reset behavior
- `tests/gui/test_viewer_panel.py`
  - verifies graceful handling of systems without a stop
- `tests/test_backend_functions.py`
  - verifies backend robustness paths related to suppressed warning cases
- `tests/test_optic.py`
  - verifies optic update behavior around invalid/intermediate states
