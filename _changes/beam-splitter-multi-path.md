# Beam Splitters and Multi-Path Illumination

Commits: `9764572c` .. `HEAD` on `feat/beam-splitter-paths`

## What this block changed

- scaled the non-sequential self-intersection guard with the float precision and the coordinate magnitude, so a Torch float32 trace no longer re-hits the surface it just left (the 45° splitter received 0.404 / 0.596 W instead of 0.5 / 0.5 W while the total still summed to 1 W)
- passive coating validation on non-sequential interfaces (`R`, `T` finite, non-negative, `R + T <= 1`) and attached (differentiable) tensor coefficients
- branch provenance in the event log: bounded-splitting children start with a `"split"` event and a `parent_id`; children are recorded with their root ray under `record_paths=int`; zero-flux children (total internal reflection) are not spawned
- sequences bind `FresnelCoating`/`ThinFilmCoating` of a reflected view to the physical interface (`SurfaceView.interface_materials`) instead of the collapsed same-medium pair, which reflected nothing
- sequences follow their surfaces through base-optic edits: stale raw indices are renumbered by surface identity on the next trace or save (`SequencedOptic.refresh`, `Optic.refresh_sequences`), and a removed route surface raises `SequenceStaleError`
- reference scenes in `optiland.samples.nonsequential`: `beam_splitter_scene()` and `side_illumination_transmission_scene()` (side illumination folded onto a sample plane, imaging in transmission through the splitter onto a camera)
- raw surfaces (`NSQScene.add_component`) and per-surface `SurfaceConfig` overrides round-trip through NSQ JSON; the 2D/3D viewers draw raw surfaces and sources
- a transmit between identical media no longer counts as a medium-stack underflow
- GUI: `NSQService` document service and the `NSQPanel` dock (sample scenes, open/save JSON, worker-thread traces, layout with paths, detector maps, energy balance), sidebar entry "Non-Seq"
- GUI: `focus_dock_widget` raises tabified docks; typing "Mirror" in the Lens Data Editor now sets the interaction model's reflective flag

## What it does for the user

- a 50:50 splitter delivers 0.5 / 0.5 W on every backend and precision; the arm powers are exact with `SamplingPolicy(split_depth=1)`
- side illumination and a transmission imaging path can share one splitter, and the event log proves the arms stay apart
- ghost sequences through coated surfaces carry the right Fresnel reflectance
- inserting or removing surfaces in a design keeps its named sequences pointing at the same surfaces
- non-sequential scenes can be built, traced, saved and inspected from the GUI

## How it is used

- `from optiland.samples.nonsequential import beam_splitter_scene, side_illumination_transmission_scene`
- `scene.sampling_policy = SamplingPolicy(split_depth=1)` for deterministic arm powers (NumPy engine)
- GUI: sidebar "Non-Seq", pick a scene, set rays / seed / split depth, "Trace"
- `python tools/gui_screenshot.py --panel nonsequential --trace --all-tabs out/nsq.png` for automated screenshots

## Tests

- `tests/nonsequential/test_nsq_beam_splitter.py` — self-intersection guard, arm powers on NumPy/Torch × float64/float32, exact splitting, edge and lossy coatings
- `tests/nonsequential/test_nsq_passive_coating.py` — coating validation, `d(flux)/dR` under Torch
- `tests/nonsequential/test_nsq_split_provenance.py` — split events, parent ids, subset recording, total internal reflection
- `tests/nonsequential/test_nsq_side_illumination.py` — two-arm scene powers, imaging, arm separation, Torch roulette
- `tests/nonsequential/test_nsq_surface_serialization.py`, `tests/nonsequential/test_nsq_surface_rendering.py` — JSON round trips and viewer output for raw surfaces and sources
- `tests/sequences/test_view_media.py`, `tests/sequences/test_sequence_lifecycle.py` — media per visit, Fresnel reflection intensity, renumbering and staleness
- `tests/gui/test_nsq_panel.py`, `tests/gui/test_focus_dock_widget.py`, `tests/gui/test_surface_service_edits.py` — panel and service, dock focus, mirror edit
