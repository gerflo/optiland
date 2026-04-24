# Theme Propagation and Lens Editor Refresh

Commit: `460baa24`

## What this block changed

- propagated theme changes through menu bars, catalog panels, viewer panel, analysis panel, and Lens Editor
- re-themed existing Matplotlib figures instead of only future plots
- hardened Lens Editor grouped-row refresh against deleted Qt items
- made collapsed grouped elements behave like single visible rows for `Tab`, cursor keys, and `Enter`

## What it does for the user

- switching themes updates more of the already-open GUI correctly
- grouped Lens Editor rows remain stable during theme refresh
- collapsed elements feel like one row in keyboard navigation

## How it is used

- switch between light and dark themes while panels are already visible
- navigate collapsed grouped elements with keyboard controls

## Tests

- `tests/gui/test_lens_editor.py`
  - verifies grouped-row re-theming, collapsed-row type guards, deleted-item rebuilds, and collapsed-row navigation
- `tests/gui/test_catalog_browser_panel.py`
  - verifies theme-refresh icon updates in the catalog browser
- `tests/gui/test_material_browser_panel.py`
  - verifies theme-refresh icon updates in the material browser
- `tests/gui/test_catalogs_panel.py`
  - verifies theme forwarding through the catalogs container
- `tests/gui/test_panel_manager.py`
  - verifies panel manager theme propagation across theme-aware panels
- `tests/gui/test_viewer_panel.py`
  - verifies existing viewer figures and sag plots re-theme correctly
- `tests/gui/test_analysis_panel.py`
  - verifies embedded analysis figures re-theme correctly
