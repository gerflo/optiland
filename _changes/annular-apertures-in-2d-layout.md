# Annular Apertures in 2D Layout

Commit: `58acd0bd`

## What this block changed

- changed 2D layout ray sampling so annular apertures produce the correct visible central obscuration in meridional display
- removed the earlier workaround that used a less appropriate sampling mode for this view

## What it does for the user

- the 2D layout now better matches the actual annular stop behavior already seen in spot diagrams

## How it is used

- create an annular aperture and inspect the 2D layout

## Tests

- `tests/gui/test_viewer_panel.py`
  - verifies 2D viewer behavior for annular aperture display and related rendering paths
