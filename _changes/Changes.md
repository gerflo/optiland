# Optiland Change Blocks

This folder documents the change blocks that were implemented in this development cycle. Each block links to a detail page with the technical changes, the commit, and the covered tests.

## 1. Lens Editor Navigation and Catalog Controls
File: [lens-editor-navigation-and-catalog-controls.md](./lens-editor-navigation-and-catalog-controls.md)  
Commit: `26444a01`

Effect:
- fixed several Lens Editor keyboard navigation issues
- restored proper button behavior in the catalog browser
- improved copy/paste behavior in table-based editors

How to use it:
- use `Ctrl+Insert`, `Shift+Insert`, `Tab`, cursor keys, and normal table editing in the Lens Editor and related tables
- use the catalog browser action buttons as standard buttons again

## 2. 2D Viewer Aspect-Preserving Zoom and Pan
File: [viewer-aspect-preserving-zoom-and-pan.md](./viewer-aspect-preserving-zoom-and-pan.md)  
Commit: `3384bb05`

Effect:
- preserved the `X/Y` ratio during rectangle zoom and right-mouse zoom/pan workflows in the 2D viewer

How to use it:
- enable `Preserve X/Y Ratio` and zoom or pan in the 2D layout

## 3. Catalog Filters and Viewer Robustness
File: [catalog-filters-and-viewer-robustness.md](./catalog-filters-and-viewer-robustness.md)  
Commit: `d0794a63`

Effect:
- added the insertable-only catalog filter
- improved viewer behavior when the system has no stop surface

How to use it:
- use the catalog browser filter toggle to show only insertable records
- open systems without a stop and still inspect geometry in 2D/3D

## 4. Physical Aperture Controls in the Lens Editor
File: [physical-aperture-controls.md](./physical-aperture-controls.md)  
Commit: `9df83813`

Effect:
- introduced physical aperture editing in Lens Editor surface properties

How to use it:
- open surface properties and edit circular, annular, and mask-like aperture definitions

## 5. Refined Physical Aperture Editing
File: [refined-physical-aperture-controls.md](./refined-physical-aperture-controls.md)  
Commit: `d0c26a2e`

Effect:
- improved aperture terminology, field relevance, and editor layout behavior

How to use it:
- edit only the relevant aperture fields for the selected aperture type

## 6. Annular Apertures in 2D Layout
File: [annular-apertures-in-2d-layout.md](./annular-apertures-in-2d-layout.md)  
Commit: `58acd0bd`

Effect:
- made annular apertures render correctly in the 2D layout ray display

How to use it:
- define an annular aperture and inspect the resulting ray bundle in the 2D layout

## 7. Asphere Editing and Persistence
File: [asphere-editing-and-persistence.md](./asphere-editing-and-persistence.md)  
Commit: `768c25d3`

Effect:
- improved even-asphere editing
- fixed save/load persistence for asphere geometry and coefficients

How to use it:
- edit even-asphere coefficients in the Lens Editor
- save and reopen systems without losing the asphere type

## 8. Element Grouping Operations
File: [element-grouping-operations.md](./element-grouping-operations.md)  
Commit: `ef0ba75e`

Effect:
- introduced grouped optical elements in the Lens Editor

How to use it:
- create, rename, duplicate, move, flip, and ungroup grouped surface blocks

## 9. Collapsible Element Rows
File: [collapsible-element-rows.md](./collapsible-element-rows.md)  
Commit: `b49bdee2`

Effect:
- showed grouped elements as collapsible rows directly in the Lens Editor table

How to use it:
- collapse and expand grouped elements in-place in the table

## 10. Element Workflows and Table Persistence
File: [element-workflows-and-table-persistence.md](./element-workflows-and-table-persistence.md)  
Commit: `7308cabd`

Effect:
- refined grouped-element behavior, selection, context menus, and table state persistence

How to use it:
- work with grouped elements via selection, delete behavior, summary rows, and saved column widths

## 11. Embedded Analysis Plot Stabilization
File: [analysis-panel-embedded-figures.md](./analysis-panel-embedded-figures.md)  
Commit: `f2c8f5c9`

Effect:
- stabilized embedded analysis plotting
- fixed figure/colorbar binding issues

How to use it:
- switch between analyses in the Analysis panel without plot crashes from incompatible `view()` arguments

## 12. Theme Propagation and Lens Editor Refresh
File: [theme-propagation-and-lens-editor-refresh.md](./theme-propagation-and-lens-editor-refresh.md)  
Commit: `460baa24`

Effect:
- propagated theme changes through GUI panels and existing plots
- hardened Lens Editor grouped-row refresh and navigation under theme changes

How to use it:
- switch between light and dark themes while keeping viewer, analysis, catalog, and Lens Editor widgets synchronized

## 13. Unsaved Changes and Save Prompt Handling
File: [unsaved-changes-and-save-prompts.md](./unsaved-changes-and-save-prompts.md)  
Commit: `75c3ec45`

Effect:
- added real state-based unsaved-change detection
- prompts before data-loss actions only when the actual optic state differs from the clean baseline

How to use it:
- trigger `New`, `Open`, `Import`, `Load Sample`, or app close and confirm save/discard/cancel only when there is real unsaved work

## 14. Catalog and Material Browser Usability Improvements
File: [catalog-and-material-browser-usability-improvements.md](./catalog-and-material-browser-usability-improvements.md)  
Commit: `this commit`

Effect:
- made selection details collapsible in the stock and material browsers
- moved catalog insert actions into the tools area above the search row
- required explicit confirmation before deleting marked entries in both browsers

How to use it:
- collapse or expand `Selection Details` when you need more space
- use the insert buttons from `Catalog Tools`
- confirm `Delete Marked` before cached records or imported materials are removed

## 15. GUI Toolbar and Window Polish
File: [gui-toolbar-and-window-polish.md](./gui-toolbar-and-window-polish.md)  
Commit: `this commit`

Effect:
- aligned Analysis toolbar/control button styling and behavior across themes
- reset viewer framing only on optic load, not on every optic change
- hardened frameless-window event filtering during teardown paths
- softened grouped Lens Editor row contrast

How to use it:
- use the Analysis plot toolbar and right-side Analysis controls with matching hover/press/checked states
- load a new optic to reframe viewers, then continue editing without losing the current view framing
- close or refresh GUI windows without deleted-wrapper event-filter errors surfacing
