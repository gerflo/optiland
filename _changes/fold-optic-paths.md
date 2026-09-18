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
