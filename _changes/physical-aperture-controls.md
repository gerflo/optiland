# Physical Aperture Controls in the Lens Editor

Commit: `9df83813`

## What this block changed

- introduced physical aperture editing directly in Lens Editor surface properties
- added support for circular, annular, and offset aperture definitions in the GUI
- connected the UI to the actual physical aperture model instead of only using semi-diameter shortcuts

## What it does for the user

- surfaces can now carry explicit aperture definitions from the GUI
- annular and offset apertures can be entered without dropping to Python code

## How it is used

- open surface properties from the Lens Editor
- edit the `Physical Aperture` section for the selected surface

## Tests

- `tests/gui/test_lens_editor.py`
  - verifies aperture editing interactions in the surface properties panel
- `tests/gui/test_surface_service.py`
  - verifies aperture configuration is translated correctly to surface data
