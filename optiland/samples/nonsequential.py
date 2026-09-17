"""Non-sequential sample scenes.

Small, fully specified :class:`~optiland.nonsequential.scene.NSQScene`
builders that the beam-splitter tests, the gallery and the GUI share. Each
builder returns a fresh scene on every call; nothing is cached, so callers
may freely mutate the result (change the sampling policy, add detectors).

The geometry conventions used throughout:

- The beam splitter is a single ``FinitePlaneGeometry`` rotated by 45 deg
  about the global y axis, so its normal is ``(sin 45, 0, cos 45)``. A beam
  travelling along ``+z`` is reflected towards ``-x``; a beam travelling
  along ``-x`` is reflected towards ``+z``; a beam travelling along ``-z``
  is reflected towards ``+x``.
- Both sides of the splitter are vacuum, so the only interaction is the
  ``SimpleCoating`` split: no refraction, no Fresnel loss, no absorption
  unless ``reflectance + transmittance < 1``.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from optiland.nonsequential.scene import NSQScene

#: Position of the splitter plane along z [mm] in every sample scene.
SPLITTER_Z = 10.0


def beam_splitter_scene(
    reflectance: float = 0.5,
    transmittance: float | None = None,
    total_flux: float = 1.0,
    source_radius: float = 1.0,
    splitter_radius: float = 5.0,
    detector_size: float = 10.0,
    num_pixels: int = 8,
) -> NSQScene:
    """Build the beam-splitter reference scene.

    One collimated beam of ``total_flux`` watts travels along ``+z`` from
    the origin and meets a plate splitter at ``z = SPLITTER_Z`` tilted 45 deg
    about y. The transmitted arm continues to a detector at ``z = 20``; the
    reflected arm travels towards ``-x`` and meets a detector at
    ``x = -10``. With the default 50:50 lossless coating each detector
    receives exactly half of the launched flux in expectation, and every
    ray meets the splitter exactly once.

    Args:
        reflectance: Coating reflectance ``R`` in ``[0, 1]``.
        transmittance: Coating transmittance ``T``. Defaults to ``1 - R``
            (lossless). ``R + T < 1`` models an absorbing coating.
        total_flux: Source power [W].
        source_radius: Radius of the collimated beam [mm].
        splitter_radius: Clear radius of the splitter plate [mm].
        detector_size: Edge length of the two square detectors [mm].
        num_pixels: Pixels per detector edge.

    Returns:
        The scene, with detectors ``"transmitted"`` and ``"reflected"`` and
        the component ``"splitter"``.
    """
    from optiland.coatings import SimpleCoating  # noqa: PLC0415
    from optiland.coordinate_system import CoordinateSystem  # noqa: PLC0415
    from optiland.nonsequential import (  # noqa: PLC0415
        VACUUM,
        CollimatedSourceConfig,
        IrradianceDetectorConfig,
        NSQScene,
        RefractiveComponent,
        Spectrum,
    )
    from optiland.nonsequential.components.geometry.analytic.plane import (  # noqa: PLC0415
        FinitePlaneGeometry,
    )

    if transmittance is None:
        transmittance = 1.0 - reflectance

    scene = NSQScene()
    scene.add_source(
        "source",
        CoordinateSystem(),
        CollimatedSourceConfig(
            spectrum=Spectrum.monochromatic(0.55),
            total_flux=total_flux,
            aperture_radius=source_radius,
        ),
    )
    scene.add_component(
        "splitter",
        RefractiveComponent(
            cs=CoordinateSystem(z=SPLITTER_Z, ry=math.pi / 4),
            geometry=FinitePlaneGeometry(aperture_radius=splitter_radius),
            material_front=VACUUM,
            material_back=VACUUM,
            coating=SimpleCoating(transmittance=transmittance, reflectance=reflectance),
            name="splitter",
        ),
    )
    detector = IrradianceDetectorConfig(
        width=detector_size,
        height=detector_size,
        num_pixels_x=num_pixels,
        num_pixels_y=num_pixels,
    )
    scene.add_detector("transmitted", CoordinateSystem(z=2 * SPLITTER_Z), detector)
    scene.add_detector(
        "reflected",
        CoordinateSystem(x=-SPLITTER_Z, z=SPLITTER_Z, ry=math.pi / 2),
        detector,
    )
    return scene
