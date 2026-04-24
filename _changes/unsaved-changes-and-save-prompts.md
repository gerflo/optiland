# Unsaved Changes and Save Prompt Handling

Commit: `75c3ec45`

## What this block changed

- replaced the simple modified-flag approach with a clean-state snapshot comparison in the connector
- added `Save / Discard / Cancel` prompts for destructive actions
- made prompts appear only when the actual optic state differs from the last clean baseline

## What it does for the user

- prevents unnecessary save prompts when changes were fully undone back to the clean state
- still warns correctly when opening, importing, creating a new system, loading a sample, or closing the app would discard real work
- treats imported or sample-loaded systems as unsaved until explicitly saved

## How it is used

- create a new system, edit it, and then open/import/close
- revert changes back to the clean baseline and observe that no save prompt appears

## Tests

- `tests/gui/test_unsaved_changes.py`
  - verifies a reverted new-system edit returns to clean state
  - verifies imported/sample-like states still require saving
  - verifies `Save / Discard / Cancel` decision paths
- `tests/gui/test_main_window_layouts.py`
  - included in regression runs to ensure main-window helper changes do not break existing layout behavior
- `tests/gui/test_lens_editor.py`
  - included in regression runs because Lens Editor editing is a primary source of modified-state transitions
