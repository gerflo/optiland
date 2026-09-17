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

import numpy as np

import optiland.backend as be

if TYPE_CHECKING:
    from optiland.nonsequential.scene import NSQScene

#: Position of the splitter plane along z [mm] in every sample scene.
SPLITTER_Z = 10.0

#: Names of the registered scene builders, for menus and tests.
SAMPLE_SCENES: dict[str, str] = {
    "beam_splitter": "Beam splitter: one beam, two arms",
    "side_illumination": "Side illumination and imaging in transmission",
}


def build_sample_scene(name: str) -> NSQScene:
    """Build a sample scene by registry name.

    Args:
        name: A key of :data:`SAMPLE_SCENES`.

    Returns:
        The freshly built scene.

    Raises:
        KeyError: If ``name`` is not a registered sample.
    """
    builders = {
        "beam_splitter": beam_splitter_scene,
        "side_illumination": side_illumination_transmission_scene,
    }
    if name not in builders:
        raise KeyError(
            f"Unknown sample scene {name!r}; expected one of {list(builders)}"
        )
    return builders[name]()


def _splitter(reflectance: float, transmittance: float, radius: float):
    """The 45 deg plate splitter shared by every sample scene."""
    from optiland.coatings import SimpleCoating  # noqa: PLC0415
    from optiland.coordinate_system import CoordinateSystem  # noqa: PLC0415
    from optiland.nonsequential import VACUUM, RefractiveComponent  # noqa: PLC0415
    from optiland.nonsequential.components.geometry.analytic.plane import (  # noqa: PLC0415
        FinitePlaneGeometry,
    )

    return RefractiveComponent(
        cs=CoordinateSystem(z=SPLITTER_Z, ry=math.pi / 4),
        geometry=FinitePlaneGeometry(aperture_radius=radius),
        material_front=VACUUM,
        material_back=VACUUM,
        coating=SimpleCoating(transmittance=transmittance, reflectance=reflectance),
        name="splitter",
    )


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
    from optiland.coordinate_system import CoordinateSystem  # noqa: PLC0415
    from optiland.nonsequential import (  # noqa: PLC0415
        CollimatedSourceConfig,
        IrradianceDetectorConfig,
        NSQScene,
        Spectrum,
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
        "splitter", _splitter(reflectance, transmittance, splitter_radius)
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


def thick_lens_image_distance(
    object_distance: float,
    r1: float,
    r2: float,
    thickness: float,
    n: float,
) -> float:
    """Paraxial image distance behind a thick lens in air.

    Args:
        object_distance: Distance from the object to the front vertex [mm],
            positive for an object in front of the lens.
        r1: Front radius of curvature [mm] (positive: centre behind the
            vertex).
        r2: Back radius of curvature [mm].
        thickness: Centre thickness [mm].
        n: Refractive index of the lens.

    Returns:
        Distance from the back vertex to the paraxial image [mm].
    """
    power = (n - 1.0) * (1.0 / r1 - 1.0 / r2 + (n - 1.0) * thickness / (n * r1 * r2))
    focal_length = 1.0 / power
    # Principal planes measured from the vertices (positive: inside).
    front_shift = -focal_length * (n - 1.0) * thickness / (n * r2)
    back_shift = -focal_length * (n - 1.0) * thickness / (n * r1)
    s = object_distance + front_shift
    s_prime = 1.0 / (1.0 / focal_length - 1.0 / s)
    return s_prime + back_shift


def side_illumination_transmission_scene(
    illumination_flux: float = 1.0,
    object_flux: float = 1.0,
    reflectance: float = 0.5,
    illumination_radius: float = 1.5,
    object_half_angle_deg: float = 5.0,
    sample_z: float = 25.0,
    lens_front_z: float = -10.0,
    lens_radius: float = 20.0,
    lens_thickness: float = 4.0,
    lens_aperture_radius: float = 6.0,
    lens_material: str = "N-BK7",
    num_pixels: int = 64,
) -> NSQScene:
    """Build the side-illumination / transmission-imaging reference scene.

    Two independent sources share one 45 deg splitter at ``z = SPLITTER_Z``:

    - ``"illumination"``: a collimated beam entering from the side
      (``x = +20``, travelling ``-x``). Its reflected half goes up to the
      sample plane at ``z = sample_z`` where the ``"sample"`` detector
      records the illumination; the transmitted half is caught by
      ``"illumination_dump"`` at ``x = -10``.
    - ``"object"``: a point source at the sample plane emitting towards
      ``-z``, standing in for the light the sample transmits. Its
      transmitted half passes the splitter, is imaged by a biconvex lens
      (front vertex at ``lens_front_z``, facing the splitter) onto the
      ``"camera"`` detector at the paraxial image distance; its reflected
      half goes back out towards ``+x`` and lands on the ``"return"``
      detector behind the illumination source.

    The lens faces carry a lossless ``SimpleCoating`` so the arm powers are
    exact: sample = R * illumination, dump = (1 - R) * illumination,
    camera = (1 - R) * object, return = R * object, for any ray that clears
    the apertures.

    Args:
        illumination_flux: Illumination source power [W].
        object_flux: Object (sample) source power [W].
        reflectance: Splitter reflectance; transmittance is ``1 - R``.
        illumination_radius: Radius of the collimated illumination [mm].
        object_half_angle_deg: Half-angle of the object source cone [deg].
        sample_z: Sample plane position [mm].
        lens_front_z: Position of the lens front vertex [mm]; the lens body
            extends towards ``-z``.
        lens_radius: Absolute radius of curvature of both lens faces [mm].
        lens_thickness: Lens centre thickness [mm].
        lens_aperture_radius: Lens semi-diameter [mm].
        lens_material: Lens glass catalog name.
        num_pixels: Pixels per edge of the sample and camera detectors.

    Returns:
        The scene, with detectors ``"sample"``, ``"illumination_dump"``,
        ``"camera"`` and ``"return"``.
    """
    from optiland.coatings import SimpleCoating  # noqa: PLC0415
    from optiland.coordinate_system import CoordinateSystem  # noqa: PLC0415
    from optiland.nonsequential import (  # noqa: PLC0415
        CollimatedSourceConfig,
        IrradianceDetectorConfig,
        LensConfig,
        NSQMaterial,
        NSQScene,
        PointSourceConfig,
        Spectrum,
        SurfaceConfig,
    )

    wavelength = 0.55
    spectrum = Spectrum.monochromatic(wavelength)
    transmittance = 1.0 - reflectance
    illumination_x = 20.0
    dump_x = -10.0
    return_x = illumination_x + 5.0

    scene = NSQScene()

    # Illumination from the side: local +z rotated to global -x.
    scene.add_source(
        "illumination",
        CoordinateSystem(x=illumination_x, z=SPLITTER_Z, ry=-math.pi / 2),
        CollimatedSourceConfig(
            spectrum=spectrum,
            total_flux=illumination_flux,
            aperture_radius=illumination_radius,
        ),
    )
    # The sample re-emits (transmits) towards -z: local +z rotated to -z.
    scene.add_source(
        "object",
        CoordinateSystem(z=sample_z, ry=math.pi),
        PointSourceConfig(
            spectrum=spectrum,
            total_flux=object_flux,
            half_angle_deg=object_half_angle_deg,
        ),
    )

    scene.add_component("splitter", _splitter(reflectance, transmittance, 6.0))

    lossless = SurfaceConfig(coating=SimpleCoating(transmittance=1.0, reflectance=0.0))
    scene.add_lens(
        "imaging_lens",
        # Front vertex faces the splitter; the body extends towards -z.
        CoordinateSystem(z=lens_front_z, ry=math.pi),
        LensConfig(
            r1=lens_radius,
            r2=-lens_radius,
            thickness=lens_thickness,
            material=lens_material,
            front_aperture_radius=lens_aperture_radius,
            front=lossless,
            back=lossless,
        ),
    )

    n_lens = float(
        np.ravel(be.to_numpy(NSQMaterial.from_glass(lens_material).n(wavelength)))[0]
    )
    image_distance = thick_lens_image_distance(
        object_distance=sample_z - lens_front_z,
        r1=lens_radius,
        r2=-lens_radius,
        thickness=lens_thickness,
        n=n_lens,
    )
    camera_z = lens_front_z - lens_thickness - image_distance

    square = IrradianceDetectorConfig(
        width=10.0, height=10.0, num_pixels_x=num_pixels, num_pixels_y=num_pixels
    )
    coarse = IrradianceDetectorConfig(
        width=10.0, height=10.0, num_pixels_x=8, num_pixels_y=8
    )
    scene.add_detector("sample", CoordinateSystem(z=sample_z), square)
    scene.add_detector("camera", CoordinateSystem(z=camera_z), square)
    scene.add_detector(
        "illumination_dump",
        CoordinateSystem(x=dump_x, z=SPLITTER_Z, ry=math.pi / 2),
        coarse,
    )
    scene.add_detector(
        "return",
        CoordinateSystem(x=return_x, z=SPLITTER_Z, ry=math.pi / 2),
        coarse,
    )
    return scene
