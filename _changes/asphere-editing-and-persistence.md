# Asphere Editing and Persistence

Commit: `768c25d3`

## What this block changed

- improved the Even Asphere surface-properties editor
- fixed coefficient handling so asphere data serializes cleanly
- fixed save/load persistence so even-asphere surfaces remain even-asphere after reopening

## What it does for the user

- asphere coefficients can be edited more directly
- saved systems no longer silently fall back to standard surfaces
- broken JSON output caused by coefficient serialization was corrected

## How it is used

- set a surface type to `Even_Asphere`
- edit coefficients in the surface-properties editor
- save and reload the system

## Tests

- `tests/test_standard_surface.py`
  - verifies round-trip persistence of surface type metadata
- `tests/gui/test_surface_service.py`
  - verifies coefficient serialization stays JSON-safe
- `tests/gui/test_lens_editor.py`
  - verifies the Even Asphere editor and related GUI behavior
