# 2D Viewer Aspect-Preserving Zoom and Pan

Commit: `1740c870`

## What this block changed

- enforced aspect-preserving behavior during rectangle zoom when `Preserve X/Y Ratio` is enabled
- corrected pan/right-mouse zoom interactions so ratio preservation can happen during drag, not only afterward
- aligned the 2D viewer interaction path with Matplotlib's own pan/zoom handling

## What it does for the user

- zooming into a rectangle no longer distorts the plot when ratio preservation is active
- right-mouse zoom in pan mode keeps the intended ratio behavior while dragging

## How it is used

- enable `Preserve X/Y Ratio` in the 2D viewer
- use rectangle zoom or pan-mode right-mouse zoom

## Tests

- `tests/gui/test_viewer_panel.py`
  - verifies aspect-ratio preservation during rectangle zoom
  - verifies live ratio preservation during pan-mode zoom interactions

