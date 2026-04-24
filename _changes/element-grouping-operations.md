# Element Grouping Operations

Commit: `84e3016e`

## What this block changed

- introduced grouped elements as a first-class Lens Editor workflow
- added element metadata and block operations such as create, rename, duplicate, move, flip, and ungroup
- enabled automatic grouping for inserted catalog parts

## What it does for the user

- multiple surfaces can be treated as one logical optical element
- common operations can be applied to the whole grouped block instead of one surface at a time

## How it is used

- select surfaces and create an element
- use context-menu element operations
- insert catalog parts that are automatically grouped

## Tests

- `tests/gui/test_surface_service.py`
  - verifies group creation, move, duplicate, flip, and guard behavior
- `tests/gui/test_lens_editor.py`
  - verifies GUI interactions for grouped elements
- `tests/gui/test_catalog_pipeline.py`
  - verifies catalog insertions produce the expected grouped behavior
- `tests/test_standard_surface.py`
  - covers serialization support used by grouped element operations

