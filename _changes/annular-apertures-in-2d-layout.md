# Annular Apertures in 2D Layout

Commit: `58acd0bd`

## What this block changed

- removed annular-specific 2D layout resampling that mixed multiple ray sets in one view
- restored `line_y` layout tracing to a single uniformly sampled real ray trace
- relies on the physical annular stop to clip rays instead of synthesizing extra transmitted ring rays

## What it does for the user

- ray density in the 2D layout now reflects the selected distribution and ray count consistently
- central and outer blocked rays remain visible up to the stop and are clipped by the physical aperture
- transmitted rays are only rays that came from the same original sampled fan

## How it is used

- create an annular aperture and inspect the 2D layout
- increase the 2D layout ray count if a narrow annular pass band needs denser visual sampling

## Tests

- `tests/gui/test_viewer_panel.py`
  - verifies 2D viewer behavior for annular aperture display and related rendering paths
  - verifies annular `line_y` layout tracing uses one uniform real trace with exactly the requested ray count
  - verifies the physical stop aperture, not visualization resampling, decides which rays reach the image plane
