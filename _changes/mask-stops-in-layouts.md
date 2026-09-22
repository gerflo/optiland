# Mask Stops in the 2D and 3D Layout

Branch: `master`

## What this block changed

- `optiland/visualization/system/system.py`: `mask_zone(aperture)` tells a mask stop -- `DifferenceAperture(RadialAperture, RadialAperture)` with a centred blocking disk or ring, as the Lens Editor's *Circular Mask* / *Annular Mask* and the anti-reflex dots define it -- from other apertures and returns the blocked zone `(r_min, r_max)`; colours as module constants (`STOP_COLOR`, `APERTURE_COLOR`, `MASK_COLOR` = `#E8202A`)
- 2D (`_plot_apertures`): a mask's clear-radius marker is red instead of purple; its blocked zone is drawn as a red bar (`MASK_LINE_WIDTH` 3.5 pt) sampled along the surface sag, one bar across the axis for a disk, one on either side for a ring
- 3D (`_plot_apertures_3d`): red ring beyond the clear radius plus the blocked disk or ring (opacity 0.9) laid onto the surface sag and drawn in front of a coincident lens face; theme key `aperture.mask_color` overrides the colour; the disk code is one helper (`_add_aperture_disk`) instead of a closure
- `OpticalSystem.plot(..., show_masks=None)`: masks have their own switch; `None` follows `show_apertures`, so library plots (`Optic.draw`, `OpticViewer`) behave as before apart from the colour. In 3D a mask is no longer one of the "other apertures". A mask on the stop surface keeps the stop's purple edge; only its blocked zone is red
- `optiland_gui/viewer_panel.py`: 2D settings *Show Masks* (default on, `Viewer2D/ShowMasks`), 3D toolbar *Masks* (default on), forwarded to `VTKViewer.render_optic(show_masks=...)`; the mask lines and actors map to their surface, so a click on a mask selects its row in the Lens Data Editor
- `docs/gui_quickstart.rst`: colours and switches of aperture and mask markers

## What it does for the user

- a mask stop is visible in the 2D and 3D layout as the element that blocks light, in red, while the aperture stop stays purple
- masks show by default even when the aperture markers are switched off (the 2D default)
- the System tab (multi-axis system) still shows neither stops nor masks: the conversion into the non-sequential scene does not carry masks yet

## Tests

- `tests/visualization/system/test_mask_stops.py` (NumPy and PyTorch) -- which apertures count as masks; 2D red edge and bar, ring bars in YZ and XZ, bar following a curved lens surface, mask on the stop, switch combinations; 3D red disk and ring, disk on the curved surface, annular disk, switch combinations
- `tests/gui/test_viewer_mask_stops.py` -- masks drawn with the aperture markers off, *Show Masks* hides them and is remembered, a click on the mask bar picks its row, the 3D *Masks* box and `render_optic(show_masks=...)` reach the system plotter
- `tests/gui/test_viewer_panel.py` -- the coupled 3D render now passes `show_masks`
