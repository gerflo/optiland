# Collapsible Element Rows

Commit: `b49bdee2`

## What this block changed

- added collapsed summary rows for grouped elements in the Lens Editor table
- made grouped elements directly recognizable in the table instead of only through context-menu metadata

## What it does for the user

- grouped surfaces can be compacted into a single summary row by default
- the Lens Editor stays readable even with many grouped multi-surface elements

## How it is used

- create or insert grouped elements
- expand or collapse them directly in the table

## Tests

- `tests/gui/test_lens_editor.py`
  - verifies collapsed default presentation and grouped-row behavior
- `tests/gui/test_catalog_pipeline.py`
  - verifies grouped catalog insertions cooperate with the table presentation
