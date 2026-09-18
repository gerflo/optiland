# Folded Illumination and Imaging Paths

Branch: `feat/fold-optic-paths` (stacked on `feat/beam-splitter-paths`)

## What this block changed

- `optiland/nonsequential/surface_conversion.py`: surface-wise placement of a sequential optic's surfaces in an NSQ scene (`add_optic_surfaces`), aimed point sources on the object surface (`add_field_point_sources`), image-surface detector (`add_image_detector`); constant-index media, aspheres, stops/obscurations as absorbing baffles, arbitrary frame, lossless policy (`glass_surfaces_lossless`)
- `optiland/nonsequential/fold.py`: `fold_paths()` merges an imaging and an illumination file at a perforated 45 deg mirror (`FoldReport`, `compare_tails`, `trace_per_source`)
- `EvenAsphereGeometry` for NSQ (Newton-refined intersection from the base conic), `LensConfig.coefficients1/2`, asphere-aware lens edges and volume checks; the grouped converter carries singlet coefficients and rejects aspheric doublet faces instead of dropping them
- `AnnularPlaneGeometry(inner_radius_y=...)`: elliptical hole (a circular aperture seen along the axis of a tilted mirror)
- `ExtendedSource(inner_radius=..., lambertian_cone=True)`: ring emitters and cosine-weighted emission restricted to a cone
- serialization / IR: `{"type": "ideal", "index", "absorp"}` media, `annulus` and `even_asphere` geometry kinds, the new source fields
- `tools/merge_optic_paths.py`: command line with per-source trace, Markdown report and plots
- `optiland/nonsequential/system.py`: `MultiAxisSystem` (scene + named `OpticalPath`s + `FoldSettings`), `fold_system()`, rebuild after editing a path, rename, click lookup; the `.olsys` file carries `paths` and `fold`
- GUI: the Non-Sequential panel is now the **System view** (sidebar "System"); a *Path* pull-down and clicks on drawn elements activate an optical path in the Lens Data Editor, 2D layout and analyses; edits there rebuild the system (debounced); paths can be renamed; the layout has wheel zoom, drag pan, *Fit* and view memory (`optiland_gui/widgets/plot_navigation.py`)
- `.olsys` is the file extension of a multi-axis (non-sequential) system: the panel's Open/Save dialogs, `tools/merge_optic_paths.py` and *File → Open* use it (`.json` scene files still load)
- GUI: *File → Open* (and the recent-files list) recognises a multi-axis system file and routes it to the System view; the optical-system loader refuses such a file with a hint instead of resetting the workspace; the panel's default max depth is 48
- GUI: the multi-axis system is the document. *File → Save / Save As* write every path and the scene to `.olsys` (title bar and unsaved-changes prompt follow the system); *File → Export → To Optiland JSON* writes one path chosen in a dialog (`optiland_gui/widgets/path_choice_dialog.py`) as a sequential design file; a sequential `.json` opened via *File → Open* becomes path 1 of a new system, or -- when the document has several paths -- fills one of them (first preselected) and rebuilds; opening a `.olsys` activates its first path; a new/sample/imported design starts a fresh single-path document (`OptilandConnector.newDocument`)
- `MultiAxisSystem` without fold settings converts each path in place (`from_optic`, `add_field_sources`: aimed point sources for object-height fields, collimated beams through the entrance pupil for angle fields); `FoldReport.unfolded()`
- `.olsys` files carry `olsys_format_version` (`OLSYS_FORMAT_VERSION = 1`), `application` (`{name, version}` of the saving program) and `optiland_version`; readers refuse newer format versions. Rule: raise the format version only when older Optiland apps can no longer read the file, and raise the GUI version with it
- Optiland GUI version 0.3.0 (`optiland_gui.__version__`, About dialog)
- `tools/gui_screenshot.py` dismisses any modal dialog (and prints its title) so an unattended run never blocks, re-docks a floating target dock and no longer persists the window layout at close
- System view: the layout figure uses constrained layout (the title stayed clipped after the dock got shorter); the sample pull-down shows a placeholder for documents that are not samples

## What it does for the user

- a fundus camera (observation through the Lochspiegel hole, ring illumination reflected by the mirror) becomes one scene: arm powers per source, spot positions on the chip, illumination footprint on the retina, stray light between the arms
- drift between the two design files (a different working distance, a different mirror distance) is listed instead of silently absorbed
- the merged system opens in the GUI's System view; each path can be activated in the Lens Data Editor, edited and folded again

## Tests

- `tests/nonsequential/test_nsq_asphere_geometry.py` -- sag/normal vs the sequential asphere, hits on the surface, conic limit, aperture, lens faces, IR kind, Torch agreement
- `tests/nonsequential/test_nsq_annular_source.py` -- ring sampling, Lambertian cone distribution, JSON round trip
- `tests/nonsequential/test_nsq_surface_conversion.py` -- aimed frames, every surface kind, shared media, lossless policy, rims, ranges/frames, strict IR, sources, detector
- `tests/nonsequential/test_nsq_fold_paths.py` -- tail comparison, mirror/arm placement, hole shapes, tail from either file, arm separation, JSON round trip
- `tests/nonsequential/test_nsq_serialization_media_geometries.py`, `test_nsq_convert_aspheres.py`, updated `test_nsq_scene_ir.py`
- `tests/nonsequential/test_nsq_system.py` -- unfolded single/multi-path conversion, version keys, newer-format refusal; `test_nsq_surface_conversion.py` -- collimated field beams through the pupil
- `tests/gui/test_system_document.py` -- start-up document, `.json` as path 1, fill a path of a folded system (default first), new system, save with versions, pending edits flushed, export of a chosen path, path-choice dialog
