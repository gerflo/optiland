"""Surface-by-surface placement of a sequential optic in an NSQ scene.

:func:`optiland.nonsequential.convert.sequential_to_nonsequential` groups
consecutive glass surfaces into ``Lens``/``Doublet`` compounds and needs an
on-axis system that starts at the object and ends at the image. The
functions here place *any* range of a sequential optic's surfaces into a
scene one surface at a time, in an arbitrary frame:

- every refractive surface becomes a ``RefractiveComponent`` with the
  media the sequential chain gives it (catalog glasses and constant-index
  ``IdealMaterial`` media alike, so eye models convert);
- mirrors become ``ReflectiveComponent`` surfaces;
- an air-to-air surface (a stop, a hole, a ring aperture) contributes only
  its aperture;
- every aperture is enforced by an absorbing annulus at the rim (and a
  central disk for an obscuration), because a non-sequential ray that
  misses a surface would otherwise fly on undisturbed;
- ``Plane``, ``StandardGeometry`` and ``EvenAsphere`` geometries are
  supported.

Object-height fields become aimed point sources on the object surface and
the image surface becomes an irradiance detector, so a complete arm of a
folded system (see :mod:`optiland.nonsequential.fold`) can be built from
one sequential file.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

import optiland.backend as be
from optiland.nonsequential.convert import (
    ConversionError,
    _build_spectrum,
    _surface_coating,
    _surface_coefficients,
    _surface_conic,
    _surface_radius,
    _surface_semi_diameter,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from optiland.coordinate_system import CoordinateSystem
    from optiland.nonsequential.detectors.configs import IrradianceDetectorConfig
    from optiland.nonsequential.materials.nsq_material import NSQMaterial
    from optiland.nonsequential.scene import NSQScene
    from optiland.optic import Optic

#: Factor applied to the pupil-subtended half angle of an aimed source.
SOURCE_CONE_MARGIN = 1.15
#: Smallest cone an aimed source emits into [deg].
MIN_SOURCE_CONE_DEG = 1.0


@dataclass
class ArmReport:
    """What :func:`add_optic_surfaces` made of each sequential surface.

    Attributes:
        components: Registry names of the refractive/reflective surfaces.
        baffles: Registry names of the absorbing rim/obscuration surfaces.
        aperture_only: Sequential indices that were air-to-air apertures and
            contribute baffles only.
        lossless: Registry names that received a lossless coating.
        notes: Free-text remarks (estimated apertures, default reflectance).
    """

    components: list[str] = field(default_factory=list)
    baffles: list[str] = field(default_factory=list)
    aperture_only: list[int] = field(default_factory=list)
    lossless: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _scalar(value) -> float:
    """Detached float of a backend scalar."""
    return float(np.ravel(be.to_numpy(value))[0])


def flat_coordinate_system(cs, frame: CoordinateSystem | None = None):
    """Copy a coordinate system's effective pose into ``frame``.

    Args:
        cs: Any :class:`~optiland.coordinate_system.CoordinateSystem`,
            possibly with its own ``reference_cs`` chain.
        frame: The parent frame of the copy (``None`` = global).

    Returns:
        A new coordinate system whose pose relative to ``frame`` equals the
        effective pose of ``cs``.
    """
    from optiland.coordinate_system import CoordinateSystem  # noqa: PLC0415

    if cs.reference_cs is None:
        pose = {
            "x": _scalar(cs.x),
            "y": _scalar(cs.y),
            "z": _scalar(cs.z),
            "rx": _scalar(cs.rx),
            "ry": _scalar(cs.ry),
            "rz": _scalar(cs.rz),
        }
    else:
        translation, _ = cs.get_effective_transform()
        rx, ry, rz = (float(v) for v in cs.get_effective_rotation_euler())
        t = np.asarray(be.to_numpy(translation), dtype=float).ravel()
        pose = {"x": t[0], "y": t[1], "z": t[2], "rx": rx, "ry": ry, "rz": rz}
    return CoordinateSystem(**pose, reference_cs=frame)


def aim_coordinate_system(
    position: tuple[float, float, float],
    target: tuple[float, float, float],
    frame: CoordinateSystem | None = None,
):
    """A coordinate system at ``position`` whose local +z points at ``target``.

    Args:
        position: Origin (x, y, z) in ``frame``.
        target: Point (x, y, z) in ``frame`` the local z axis passes through.
        frame: Parent frame (``None`` = global).

    Returns:
        The aimed coordinate system (rotations ``rx`` then ``ry``).

    Raises:
        ValueError: If ``target`` coincides with ``position``.
    """
    from optiland.coordinate_system import CoordinateSystem  # noqa: PLC0415

    d = np.asarray(target, dtype=float) - np.asarray(position, dtype=float)
    norm = float(np.linalg.norm(d))
    if norm == 0.0:
        raise ValueError("aim_coordinate_system: target equals position.")
    dx, dy, dz = (d / norm).tolist()
    # R = Rz Ry Rx applied to (0, 0, 1) gives (sin ry cos rx, -sin rx, cos ry cos rx).
    rx = -math.asin(max(-1.0, min(1.0, dy)))
    ry = math.atan2(dx, dz)
    return CoordinateSystem(
        x=position[0],
        y=position[1],
        z=position[2],
        rx=rx,
        ry=ry,
        reference_cs=frame,
    )


# ---------------------------------------------------------------------------
# Materials and apertures
# ---------------------------------------------------------------------------


class _MaterialCache:
    """One ``NSQMaterial`` per underlying optiland material object."""

    def __init__(self) -> None:
        self._by_id: dict[int, NSQMaterial] = {}

    def get(self, material) -> NSQMaterial:
        from optiland.materials.ideal import IdealMaterial  # noqa: PLC0415
        from optiland.nonsequential.materials.nsq_material import (  # noqa: PLC0415
            VACUUM,
            NSQMaterial,
        )

        if material is None:
            return VACUUM
        if isinstance(material, IdealMaterial):
            n = _scalar(material.index)
            k = _scalar(material.absorp)
            if n == 1.0 and k == 0.0:
                return VACUUM
        key = id(material)
        if key not in self._by_id:
            self._by_id[key] = NSQMaterial(optiland_material=material)
        return self._by_id[key]


def _same_medium(a, b) -> bool:
    """Whether two sequential materials are physically the same medium."""
    from optiland.materials.ideal import IdealMaterial  # noqa: PLC0415

    if a is b:
        return True
    if isinstance(a, IdealMaterial) and isinstance(b, IdealMaterial):
        return _scalar(a.index) == _scalar(b.index) and _scalar(a.absorp) == _scalar(
            b.absorp
        )
    name_a = getattr(a, "name", None)
    name_b = getattr(b, "name", None)
    return name_a is not None and name_a == name_b


def is_catalog_glass(material) -> bool:
    """Whether a sequential material is a named catalog glass."""
    from optiland.materials.ideal import IdealMaterial  # noqa: PLC0415

    return material is not None and not isinstance(material, IdealMaterial)


def glass_surfaces_lossless(index: int, surface) -> bool:
    """Default lossless policy: coat every surface that touches catalog glass.

    Constant-index media (an eye model, an immersion liquid) keep their
    Fresnel reflection, which is what makes a corneal reflex visible.

    Args:
        index: Sequential surface index (unused).
        surface: The sequential surface.

    Returns:
        True for surfaces bounding a catalog glass.
    """
    return is_catalog_glass(surface.material_pre) or is_catalog_glass(
        surface.material_post
    )


@dataclass
class _Aperture:
    r_max: float | None
    r_min: float
    rectangular: tuple[float, float, float, float] | None
    estimated: bool
    #: Radial zone ``(r_min, r_max)`` a mask stop blocks, if any.
    blocked: tuple[float, float] | None = None
    #: The aperture's shape is enforced as its circumscribed circle.
    approximated: bool = False


def _centred_radial(ap) -> tuple[float, float] | None:
    """``(r_max, r_min)`` of a centred radial aperture, else None."""
    from optiland.physical_apertures.radial import RadialAperture  # noqa: PLC0415

    if not isinstance(ap, RadialAperture):
        return None
    if float(getattr(ap, "offset_x", 0.0)) or float(getattr(ap, "offset_y", 0.0)):
        return None
    return float(ap.r_max), float(ap.r_min)


def _aperture_of(surface, optic, index: int) -> _Aperture:
    from optiland.visualization.system.system import mask_zone  # noqa: PLC0415

    ap = surface.aperture
    if ap is None:
        r, estimated = _surface_semi_diameter(surface, optic, index)
        return _Aperture(float(r), 0.0, None, estimated)
    radial = _centred_radial(ap)
    if radial is not None:
        return _Aperture(*radial, None, False)
    if hasattr(ap, "x_min"):
        rect = (float(ap.x_min), float(ap.x_max), float(ap.y_min), float(ap.y_max))
        r = max(abs(v) for v in rect)
        return _Aperture(r, 0.0, rect, False)
    zone = mask_zone(ap)
    clear = _centred_radial(getattr(ap, "a", None)) if zone is not None else None
    if clear is not None:
        return _Aperture(*clear, None, False, blocked=zone)
    # Any other shape (ellipse, polygon, a decentred or boolean aperture):
    # the circumscribed circle of its extent.
    r = max(abs(float(v)) for v in ap.extent)
    return _Aperture(r, 0.0, None, False, approximated=True)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def _nsq_geometry(surface, r_max: float):
    """Build the NSQ geometry of a sequential surface."""
    from optiland.geometries.even_asphere import EvenAsphere  # noqa: PLC0415
    from optiland.geometries.plane import Plane  # noqa: PLC0415
    from optiland.geometries.standard import StandardGeometry  # noqa: PLC0415
    from optiland.nonsequential.components.geometry.analytic.asphere import (  # noqa: PLC0415
        EvenAsphereGeometry,
    )
    from optiland.nonsequential.components.geometry.analytic.conic import (  # noqa: PLC0415
        ConicGeometry,
    )
    from optiland.nonsequential.components.geometry.analytic.plane import (  # noqa: PLC0415
        FinitePlaneGeometry,
    )

    geometry = surface.geometry
    if isinstance(geometry, EvenAsphere):
        return EvenAsphereGeometry(
            radius=_surface_radius(surface),
            conic=_surface_conic(surface),
            aperture_radius=r_max,
            coefficients=_surface_coefficients(surface),
        )
    if isinstance(geometry, Plane):
        return FinitePlaneGeometry(aperture_radius=r_max)
    if type(geometry) is StandardGeometry:
        radius = _surface_radius(surface)
        if radius == 0.0 or not math.isfinite(radius):
            return FinitePlaneGeometry(aperture_radius=r_max)
        return ConicGeometry(radius, _surface_conic(surface), r_max)
    raise ConversionError(
        f"Surface geometry {type(geometry).__name__} is not supported by the "
        "surface-wise converter (Plane, StandardGeometry, EvenAsphere are)."
    )


def surface_sag(surface, r: float) -> float:
    """Sag of a sequential surface at radial position ``r`` [mm]."""
    try:
        return _scalar(surface.geometry.sag(r, 0.0))
    except Exception:  # noqa: BLE001 -- planes and exotic geometries: no sag
        return 0.0


# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------


def add_optic_surfaces(
    scene: NSQScene,
    optic: Optic,
    *,
    frame: CoordinateSystem | None = None,
    start: int = 1,
    stop: int | None = None,
    prefix: str = "",
    lossless: bool | Callable[[int, object], bool] = False,
    baffles: bool = True,
    baffle_margin: float = 5.0,
    mirror_reflectance: float = 1.0,
) -> ArmReport:
    """Place the surfaces ``optic.surfaces[start:stop]`` into ``scene``.

    Args:
        scene: Target scene.
        optic: The sequential optic.
        frame: Frame the optic's own coordinates are expressed in
            (``None`` = the scene's global frame).
        start: First sequential surface index to place (default 1, the
            first surface after the object).
        stop: One past the last index to place; defaults to the image
            surface index, so the image is never placed as a surface.
        prefix: Prefix of the registry names (``f"{prefix}S{i}"``).
        lossless: ``True`` gives every refractive surface a lossless
            ``SimpleCoating`` (the sequential engine's behaviour); a
            callable ``(index, surface) -> bool`` decides per surface; see
            :func:`glass_surfaces_lossless`. A coating already present on
            the surface always wins.
        baffles: Add absorbing rims (and obscuration disks) that enforce
            every surface aperture.
        baffle_margin: Minimum radial width of a rim baffle [mm]; the rim
            extends to ``max(2 r_max, r_max + baffle_margin)``, wide enough
            that a source cone overshooting a stop is absorbed by its mount
            rather than escaping the scene.
        mirror_reflectance: Reflectance of mirrors without a coating.

    Returns:
        An :class:`ArmReport` naming what was added.

    Raises:
        ConversionError: For an unsupported geometry.
    """
    from optiland.coatings import SimpleCoating  # noqa: PLC0415
    from optiland.nonsequential.components.absorbing import (  # noqa: PLC0415
        AbsorbingComponent,
    )
    from optiland.nonsequential.components.geometry.analytic.annulus import (  # noqa: PLC0415
        AnnularPlaneGeometry,
    )
    from optiland.nonsequential.components.geometry.analytic.plane import (  # noqa: PLC0415
        FinitePlaneGeometry,
    )
    from optiland.nonsequential.components.reflective import (  # noqa: PLC0415
        ReflectiveComponent,
    )
    from optiland.nonsequential.components.refractive import (  # noqa: PLC0415
        RefractiveComponent,
    )

    surfaces = list(optic.surfaces.surfaces)
    if stop is None:
        stop = len(surfaces) - 1
    if not 0 <= start <= stop <= len(surfaces):
        raise ValueError(
            f"add_optic_surfaces: range [{start}, {stop}) is outside the optic's "
            f"{len(surfaces)} surfaces."
        )
    if callable(lossless):
        lossless_fn = lossless
    else:
        lossless_fn = (lambda _i, _s: True) if lossless else (lambda _i, _s: False)

    report = ArmReport()
    materials = _MaterialCache()

    for i in range(start, stop):
        surface = surfaces[i]
        name = f"{prefix}S{i}"
        comment = (getattr(surface, "comment", "") or "").strip()
        label = f"{name} {comment[:40]}".strip()
        aperture = _aperture_of(surface, optic, i)
        if aperture.estimated:
            report.notes.append(f"{name}: aperture estimated ({aperture.r_max:.3g} mm)")
        if aperture.approximated:
            report.notes.append(
                f"{name}: {type(surface.aperture).__name__} enforced as its "
                f"circumscribed circle ({aperture.r_max:.3g} mm)"
            )
        r_max = aperture.r_max
        cs = flat_coordinate_system(surface.geometry.cs, frame)

        model = getattr(surface, "interaction_model", None)
        reflective = bool(getattr(model, "is_reflective", False))
        pre = surface.material_pre
        post = surface.material_post
        coating = _surface_coating(surface)

        if reflective:
            geometry = _nsq_geometry(surface, r_max)
            reflectance = coating if coating is not None else mirror_reflectance
            if coating is None:
                report.notes.append(
                    f"{name}: mirror without coating, reflectance {mirror_reflectance}"
                )
            scene.add_component(
                name,
                ReflectiveComponent(
                    cs=cs,
                    geometry=geometry,
                    reflectance=reflectance,
                    material_front=materials.get(pre),
                    name=label,
                ),
            )
            report.components.append(name)
        elif _same_medium(pre, post) and coating is None:
            report.aperture_only.append(i)
        else:
            geometry = _nsq_geometry(surface, r_max)
            if coating is None and lossless_fn(i, surface):
                coating = SimpleCoating(transmittance=1.0, reflectance=0.0)
                report.lossless.append(name)
            scene.add_component(
                name,
                RefractiveComponent(
                    cs=cs,
                    geometry=geometry,
                    material_front=materials.get(pre),
                    material_back=materials.get(post),
                    coating=coating,
                    name=label,
                ),
            )
            report.components.append(name)

        if not baffles or aperture.rectangular is not None or r_max is None:
            if aperture.rectangular is not None:
                report.notes.append(f"{name}: rectangular aperture, no baffle")
            continue
        outer = max(2.0 * r_max, r_max + baffle_margin)
        rim_name = f"{name}.rim"
        scene.add_component(
            rim_name,
            AbsorbingComponent(
                cs=cs,
                geometry=AnnularPlaneGeometry(
                    inner_radius=r_max,
                    outer_radius=outer,
                    z_offset=surface_sag(surface, r_max),
                ),
                material_front=materials.get(pre),
                name=f"{label} rim",
            ),
        )
        report.baffles.append(rim_name)
        if aperture.r_min > 0.0:
            disk_name = f"{name}.obscuration"
            scene.add_component(
                disk_name,
                AbsorbingComponent(
                    cs=cs,
                    geometry=FinitePlaneGeometry(aperture_radius=aperture.r_min),
                    material_front=materials.get(pre),
                    name=f"{label} obscuration",
                ),
            )
            report.baffles.append(disk_name)
        if aperture.blocked is not None:
            # A mask stop's blocking disk or ring, at the surface like the
            # rim: flat, at the sag of its inner edge.
            inner, outer_blocked = aperture.blocked
            if inner > 0.0:
                mask_geometry = AnnularPlaneGeometry(
                    inner_radius=inner,
                    outer_radius=outer_blocked,
                    z_offset=surface_sag(surface, inner),
                )
            else:
                mask_geometry = FinitePlaneGeometry(aperture_radius=outer_blocked)
            mask_name = f"{name}.mask"
            scene.add_component(
                mask_name,
                AbsorbingComponent(
                    cs=cs,
                    geometry=mask_geometry,
                    material_front=materials.get(pre),
                    name=f"{label} mask",
                ),
            )
            report.baffles.append(mask_name)
    return report


# ---------------------------------------------------------------------------
# Object and image
# ---------------------------------------------------------------------------


def object_field_points(optic: Optic) -> list[tuple[float, float, float]]:
    """Field points on the object surface, ``(x, y, z)`` in the optic frame.

    The z coordinate includes the object surface's sag (a curved retina, a
    domed sample), so each point lies *on* the object surface.

    Args:
        optic: A sequential optic with object-height fields.

    Returns:
        One point per field.

    Raises:
        ConversionError: If the fields are not object heights or the
            object is at infinity.
    """
    from optiland.fields.field_types import ObjectHeightField  # noqa: PLC0415

    if not isinstance(optic.fields.field_definition, ObjectHeightField):
        raise ConversionError(
            "Aimed point sources need object-height fields; this optic uses "
            f"{type(optic.fields.field_definition).__name__}."
        )
    obj = optic.object_surface
    if obj is None or obj.is_infinite:
        raise ConversionError("The object surface is at infinity.")
    x0, y0, z0 = (_scalar(v) for v in obj.geometry.cs.position_in_gcs)
    points = []
    for f in optic.fields.fields:
        fx, fy = float(f.x), float(f.y)
        sag = surface_sag(obj, math.hypot(fx, fy))
        points.append((x0 + fx, y0 + fy, z0 + sag))
    return points


def entrance_pupil(optic: Optic) -> tuple[float, float]:
    """``(z, diameter)`` of the paraxial entrance pupil in the optic frame."""
    z = _scalar(optic.paraxial.entrance_pupil_z())
    diameter = _scalar(optic.paraxial.EPD())
    return z, diameter


def add_field_point_sources(
    scene: NSQScene,
    optic: Optic,
    *,
    frame: CoordinateSystem | None = None,
    prefix: str = "object",
    total_flux: float = 1.0,
    half_angle_deg: float | None = None,
    medium: NSQMaterial | None = None,
) -> list[str]:
    """Add one aimed point source per object-height field of ``optic``.

    Each source sits on the object surface at its field point and emits a
    cone along its chief ray: towards the centre of the paraxial entrance
    pupil, or away from it when the pupil is virtual and lies behind the
    object. The default half angle is the angle the pupil edge subtends
    from the field point, times :data:`SOURCE_CONE_MARGIN`, so the physical
    apertures downstream (not the cone) decide what gets through.

    Args:
        scene: Target scene.
        optic: The sequential optic (object-height fields).
        frame: Frame of the optic's coordinates.
        prefix: Registry names are ``f"{prefix}_{k}"`` with ``k`` the field
            index.
        total_flux: Flux per source [W].
        half_angle_deg: Fixed cone half angle; ``None`` = per field from
            the entrance pupil.
        medium: Medium the object sits in (``None`` = the object surface's
            own material, vacuum if that is air).

    Returns:
        The registry names of the sources, in field order.
    """
    from optiland.nonsequential.sources.configs import (
        PointSourceConfig,  # noqa: PLC0415
    )

    spectrum = _build_spectrum(optic)
    z_pupil, epd = entrance_pupil(optic)
    if medium is None:
        medium = _MaterialCache().get(optic.object_surface.material_post)
    names = []
    for k, (x, y, z) in enumerate(object_field_points(optic)):
        distance = abs(z_pupil - z)
        if half_angle_deg is None:
            angle = math.degrees(math.atan2(abs(epd) / 2.0, distance))
            cone = min(89.0, max(SOURCE_CONE_MARGIN * angle, MIN_SOURCE_CONE_DEG))
        else:
            cone = half_angle_deg
        if z_pupil > z:
            target = (0.0, 0.0, z_pupil)
        else:
            # Virtual pupil behind the object: the chief ray leaves the field
            # point *away* from the pupil centre, still travelling forward.
            target = (2.0 * x, 2.0 * y, 2.0 * z - z_pupil)
        cs = aim_coordinate_system((x, y, z), target, frame)
        name = f"{prefix}_{k}"
        scene.add_source(
            name,
            cs,
            PointSourceConfig(
                spectrum=spectrum,
                total_flux=total_flux,
                half_angle_deg=cone,
                medium=medium if medium.optiland_material is not None else None,
            ),
        )
        names.append(name)
    return names


def add_collimated_field_sources(
    scene: NSQScene,
    optic: Optic,
    *,
    frame: CoordinateSystem | None = None,
    prefix: str = "field",
    total_flux: float = 1.0,
    standoff: float | None = None,
) -> list[str]:
    """Add one collimated beam per angle field, aimed through the entrance pupil.

    Each beam has the diameter of the paraxial entrance pupil and travels
    along the field's chief-ray direction (slopes ``tan`` of the field
    angles, as in the paraxial model). It starts ``standoff`` mm before the
    first surface, or before the pupil when that lies further in front, on
    the line through the pupil centre; the rim baffles downstream decide
    what gets through.

    Args:
        scene: Target scene.
        optic: The sequential optic (angle fields, object at infinity).
        frame: Frame of the optic's coordinates.
        prefix: Registry names are ``f"{prefix}_{k}"`` with ``k`` the field
            index.
        total_flux: Flux per source [W].
        standoff: Distance from the beam start plane to the first surface
            [mm]; defaults to the larger of the pupil diameter and 10 mm.

    Returns:
        The registry names of the sources, in field order.

    Raises:
        ConversionError: If the fields are not angles, the optic has no
            surface after the object, or the pupil diameter is zero.
    """
    from optiland.fields.field_types import AngleField  # noqa: PLC0415
    from optiland.nonsequential.sources.configs import (  # noqa: PLC0415
        CollimatedSourceConfig,
    )

    if not isinstance(optic.fields.field_definition, AngleField):
        raise ConversionError(
            "Collimated sources need angle fields; this optic uses "
            f"{type(optic.fields.field_definition).__name__}."
        )
    surfaces = optic.surfaces.surfaces
    if len(surfaces) < 2:
        raise ConversionError("The optic has no surface after the object.")
    spectrum = _build_spectrum(optic)
    z_pupil, epd = entrance_pupil(optic)
    radius = abs(epd) / 2.0
    if not radius > 0.0:
        raise ConversionError("The entrance pupil diameter is zero.")
    z_first = _scalar(surfaces[1].geometry.cs.position_in_gcs[2])
    if standoff is None:
        standoff = max(abs(epd), 10.0)
    z_start = min(z_first, z_pupil) - standoff
    names = []
    for k, f in enumerate(optic.fields.fields):
        direction = np.array(
            [
                math.tan(math.radians(float(f.x))),
                math.tan(math.radians(float(f.y))),
                1.0,
            ]
        )
        # The beam axis passes through the pupil centre; walk back from
        # there to the start plane.
        distance = (z_pupil - z_start) / direction[2]
        position = tuple((-distance * direction + [0.0, 0.0, z_pupil]).tolist())
        cs = aim_coordinate_system(position, (0.0, 0.0, z_pupil), frame)
        name = f"{prefix}_{k}"
        scene.add_source(
            name,
            cs,
            CollimatedSourceConfig(
                spectrum=spectrum,
                total_flux=total_flux,
                aperture_radius=radius,
            ),
        )
        names.append(name)
    return names


def add_field_sources(
    scene: NSQScene,
    optic: Optic,
    *,
    frame: CoordinateSystem | None = None,
    prefix: str = "field",
    total_flux: float = 1.0,
    half_angle_deg: float | None = None,
) -> list[str]:
    """Add one source per field, whatever the field type.

    Object-height fields become aimed point sources
    (:func:`add_field_point_sources`); angle fields become collimated beams
    through the entrance pupil (:func:`add_collimated_field_sources`).

    Args:
        scene: Target scene.
        optic: The sequential optic.
        frame: Frame of the optic's coordinates.
        prefix: Registry-name prefix (``f"{prefix}_{k}"``).
        total_flux: Flux per source [W].
        half_angle_deg: Fixed cone half angle for point sources (``None`` =
            from the entrance pupil); ignored for collimated beams.

    Returns:
        The registry names of the sources, in field order.

    Raises:
        ConversionError: For field types that have no source model
            (image-height fields).
    """
    from optiland.fields.field_types import (  # noqa: PLC0415
        AngleField,
        ObjectHeightField,
    )

    definition = optic.fields.field_definition
    if isinstance(definition, ObjectHeightField):
        return add_field_point_sources(
            scene,
            optic,
            frame=frame,
            prefix=prefix,
            total_flux=total_flux,
            half_angle_deg=half_angle_deg,
        )
    if isinstance(definition, AngleField):
        return add_collimated_field_sources(
            scene, optic, frame=frame, prefix=prefix, total_flux=total_flux
        )
    raise ConversionError(
        f"Fields of type {type(definition).__name__} have no source model; "
        "use angle or object-height fields."
    )


def image_detector_config(
    optic: Optic,
    *,
    num_pixels: tuple[int, int] = (256, 256),
    default_size: float | None = None,
) -> IrradianceDetectorConfig:
    """Detector config matching the optic's image surface aperture.

    Args:
        optic: The sequential optic.
        num_pixels: ``(nx, ny)``.
        default_size: Edge length [mm] when the image surface has no
            aperture; defaults to twice the paraxial chief-ray height.

    Returns:
        The config (width/height from a rectangular or radial aperture).
    """
    from optiland.nonsequential.detectors.configs import (  # noqa: PLC0415
        IrradianceDetectorConfig,
    )

    image = optic.image_surface
    aperture = _aperture_of(image, optic, len(optic.surfaces.surfaces) - 1)
    if aperture.rectangular is not None:
        x_min, x_max, y_min, y_max = aperture.rectangular
        width, height = x_max - x_min, y_max - y_min
    elif not aperture.estimated and aperture.r_max:
        width = height = 2.0 * aperture.r_max
    elif default_size is not None:
        width = height = default_size
    else:
        try:
            yb, _ = optic.paraxial.chief_ray()
            width = height = max(2.0 * abs(_scalar(yb[-1])), 1.0)
        except Exception:  # noqa: BLE001 -- no paraxial data: nominal size
            width = height = 10.0
    return IrradianceDetectorConfig(
        width=width,
        height=height,
        num_pixels_x=num_pixels[0],
        num_pixels_y=num_pixels[1],
    )


def add_image_detector(
    scene: NSQScene,
    optic: Optic,
    name: str = "image",
    *,
    frame: CoordinateSystem | None = None,
    num_pixels: tuple[int, int] = (256, 256),
) -> IrradianceDetectorConfig:
    """Add an irradiance detector at the optic's image surface.

    Args:
        scene: Target scene.
        optic: The sequential optic.
        name: Registry name.
        frame: Frame of the optic's coordinates.
        num_pixels: ``(nx, ny)``.

    Returns:
        The detector config used.
    """
    config = image_detector_config(optic, num_pixels=num_pixels)
    cs = flat_coordinate_system(optic.image_surface.geometry.cs, frame)
    scene.add_detector(name, cs, config)
    return config
