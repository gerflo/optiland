# Refined Physical Aperture Editing

Commit: `916dcfee`

## What this block changed

- refined the aperture editor terminology and interaction model
- made the panel show only the fields relevant for the selected aperture type
- improved layout behavior and readability of the physical-aperture editor

## What it does for the user

- aperture editing is clearer and less error-prone
- irrelevant fields stay out of the way
- the same UI can represent apertures and masks more cleanly

## How it is used

- choose an aperture type in surface properties
- edit only the fields shown for that type

## Tests

- `tests/gui/test_lens_editor.py`
  - verifies relevant-field visibility and editing behavior for aperture types

