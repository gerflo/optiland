# Embedded Analysis Plot Stabilization

Commit: `f2c8f5c9`

## What this block changed

- filtered `view()` arguments against the actual analysis signature before calling analysis views
- fixed embedded colorbar creation so colorbars attach to the correct figure and axes

## What it does for the user

- analyses such as Grid Distortion no longer crash because of foreign plot arguments
- embedded OPD and Zernike plots avoid mismatched colorbar warnings

## How it is used

- run analyses in the embedded Analysis panel
- switch analyses and pages without the earlier `view()`-argument crash

## Tests

- `tests/gui/test_analysis_panel.py`
  - verifies unknown view arguments are filtered before dispatch
- `tests/test_analysis.py`
  - verifies the broader analysis stack stays healthy with the embedded plotting changes
