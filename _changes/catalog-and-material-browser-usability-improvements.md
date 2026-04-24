# Catalog and Material Browser Usability Improvements

Commit: `this commit`

## What this block changed

- made `Selection Details` collapsible in both the stock catalog browser and the material browser
- moved the catalog insert buttons into the `Catalog Tools` area above the search row
- required explicit confirmation before `Delete Marked` removes cached catalog entries or imported materials

## What it does for the user

- frees vertical space when the details section is not needed
- keeps the primary catalog insertion actions closer to the search and filtering tools
- reduces accidental deletion of marked entries

## How it is used

- click the `Selection Details` header to collapse or expand it
- use `Insert Before Selected Surface` and `Insert After Selected Surface` from the `Catalog Tools` section
- confirm the `Delete Marked` dialog before deletion proceeds

## Tests

- `tests/gui/test_catalog_browser_panel.py`
  - verifies the insert buttons live outside the details section
  - verifies stock-browser selection details can be collapsed and expanded
  - verifies the delete-marked flow still works with explicit confirmation
- `tests/gui/test_material_browser_panel.py`
  - verifies material-browser selection details can be collapsed and expanded
  - verifies the delete-marked flow still works with explicit confirmation
