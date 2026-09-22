# Mask Stops in the 2D and 3D Layout

Branch: `master`

## What this block changed

- `optiland/visualization/system/system.py`: `mask_zone(aperture)` tells a mask stop -- `DifferenceAperture(RadialAperture, RadialAperture)` with a centred blocking disk or ring, as the Lens Editor's *Circular Mask* / *Annular Mask* and the anti-reflex dots define it -- from other apertures and returns the blocked zone `(r_min, r_max)`; colours as module constants (`STOP_COLOR`, `APERTURE_COLOR`, `MASK_COLOR` = `#E8202A`)
- 2D (`_plot_apertures`): a mask's clear-radius marker is red instead of purple; its blocked zone is drawn as a red bar (`MASK_LINE_WIDTH` 3.5 pt) sampled along the surface sag, one bar across the axis for a disk, one on either side for a ring
- 3D (`_plot_apertures_3d`): red ring beyond the clear radius plus the blocked disk or ring (opacity 0.9) laid onto the surface sag and drawn in front of a coincident lens face; theme key `aperture.mask_color` overrides the colour; the disk code is one helper (`_add_aperture_disk`) instead of a closure
- `OpticalSystem.plot(..., show_masks=None)`: masks have their own switch; `None` follows `show_apertures`, so library plots (`Optic.draw`, `OpticViewer`) behave as before apart from the colour. In 3D a mask is no longer one of the "other apertures". A mask on the stop surface keeps the stop's purple edge; only its blocked zone is red
- `optiland_gui/viewer_panel.py`: 2D settings *Show Masks* (default on, `Viewer2D/ShowMasks`), 3D toolbar *Masks* (default on), forwarded to `VTKViewer.render_optic(show_masks=...)`; the mask lines and actors map to their surface, so a click on a mask selects its row in the Lens Data Editor
- `docs/gui_quickstart.rst`: colours and switches of aperture and mask markers
- ring apertures (`RadialAperture` with `r_min > 0`, the Lens Editor's *Annular Aperture*; follow-up of the same day): the central disk they block is drawn like a mask's blocking disk (`_blocked_zone`), red in 2D and 3D and under the mask switch, instead of a purple inner edge in 2D and a translucent light-purple (pink-looking) disk in 3D; their clear edge stays an aperture marker. `mask_zone` still returns None for them

## What it does for the user

- a mask stop is visible in the 2D and 3D layout as the element that blocks light, in red, while the aperture stop stays purple
- masks show by default even when the aperture markers are switched off (the 2D default)
- the blocked centre of a ring aperture is red like a mask's blocking disk, no longer pink
- the System tab (multi-axis system): since the O1 fix the conversion into the non-sequential scene builds a mask's blocking disk or ring as an absorber (`S<i>.mask`), so the NSQ trace is dimmed correctly; since the O4 fix these absorbers and a ring aperture's centre disk (`S<i>.obscuration`) are drawn red in the System tab too (2D and 3D renderers, recognised by `is_blocking_absorber` from the registry name), and the active-path highlight thickens them but keeps the red

## Tests

- `tests/visualization/system/test_mask_stops.py` (NumPy and PyTorch) -- which apertures count as masks; 2D red edge and bar, ring bars in YZ and XZ, bar following a curved lens surface, mask on the stop, switch combinations; 3D red disk and ring, disk on the curved surface, annular disk, switch combinations; ring apertures: 2D red bar over the blocked centre with the purple clear edge, mask switch, 3D red disk on the curved surface beside the edge ring
- `tests/gui/test_viewer_mask_stops.py` -- masks drawn with the aperture markers off, *Show Masks* hides them and is remembered, a click on the mask bar picks its row, the 3D *Masks* box and `render_optic(show_masks=...)` reach the system plotter
- `tests/gui/test_viewer_panel.py` -- the coupled 3D render now passes `show_masks`
- `tests/nonsequential/test_nsq_surface_rendering.py` (2D, 3D) and `tests/gui/test_nsq_panel.py` -- System tab: mask and ring-centre absorbers red, rims not, red kept in the active path (O4)
