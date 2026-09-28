"""Fold two sequential paths into one non-sequential scene.

A fundus camera, a reflected-light microscope or any coaxial illuminator
consists of two sequential designs that share a tail: an *imaging* path
traced from the sample outwards to a camera, and an *illumination* path
traced from a light source through a relay onto the same sample. Both are
laid out unfolded and meet at a perforated fold mirror: the imaging path
passes through its hole, the illumination reflects off its ring.

:func:`fold_paths` builds the folded system as one
:class:`~optiland.nonsequential.scene.NSQScene`:

- the imaging optic's frame is the global frame (sample near the origin,
  camera along +z);
- the fold mirror is an annular ``ReflectiveComponent`` at the imaging
  optic's fold surface, tilted about y; its hole is the imaging fold
  aperture, its rim the illumination fold aperture;
- the illumination optic's surfaces before its fold surface lie along the
  -x axis, travelling +x into the mirror, so the reflected beam continues
  towards -z into the shared tail;
- the shared tail (the surfaces between the sample and the fold) is taken
  from one of the two files, and the other file's copy is compared with
  it surface by surface so that any drift between the two designs is
  reported, never silently absorbed;
- the imaging fields become aimed point sources on the sample, the
  illumination object becomes the emitter of the illumination path's LED
  ring (:attr:`~optiland.optic.Optic.light_source`: discrete chips or an
  annulus, with its radiation pattern, spectrum and flux) or, without one,
  an annular (or disk) Lambertian emitter spanning the illumination field
  radii, and detectors sit at the camera, the sample, behind the hole and
  behind the illumination source.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from optiland.nonsequential.convert import (
    ConversionError,
    _build_spectrum,
    _surface_coefficients,
    _surface_conic,
    _surface_radius,
)
from optiland.nonsequential.surface_conversion import (
    ArmReport,
    _aperture_of,
    _scalar,
    add_field_point_sources,
    add_image_detector,
    add_optic_surfaces,
    entrance_pupil,
    flat_coordinate_system,
    glass_surfaces_lossless,
    object_field_points,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from optiland.illumination import LEDRing
    from optiland.nonsequential.scene import NSQScene
    from optiland.nonsequential.sources.configs import (
        ExtendedSourceConfig,
        LEDRingSourceConfig,
    )
    from optiland.optic import Optic

HoleShape = Literal["projected", "physical"]
TailSource = Literal["imaging", "illumination"]

#: Registry names used by :func:`fold_paths`.
MIRROR = "fold_mirror"
CAMERA = "camera"
SAMPLE = "sample"
DUMP = "illumination_dump"
RETURN = "return"
ILLUMINATION = "illumination"
OBJECT_PREFIX = "object"


@dataclass
class FoldReport:
    """Everything :func:`fold_paths` decided or found.

    Attributes:
        fold_z: Global z of the fold mirror centre [mm].
        angle_deg: Mirror tilt about y [deg].
        hole_semi_axes: ``(along x, along y)`` of the hole in the mirror
            plane [mm].
        rim_radius: Outer radius of the mirror [mm].
        tail_from: Which optic supplied the shared tail.
        tail_differences: Human-readable mismatches between the two copies
            of the shared tail (empty when they agree).
        imaging_arm: What the imaging surfaces behind the fold became.
        illumination_arm: What the illumination surfaces before the fold
            became.
        tail: What the shared tail became.
        sources: Registry names of the sources.
        detectors: Registry names of the detectors.
        notes: Free-text remarks.
        arms: Per-path conversions of an *unfolded* system (see
            :meth:`~optiland.nonsequential.system.MultiAxisSystem.rebuild`),
            keyed by path name; empty for a fold.
    """

    fold_z: float
    angle_deg: float
    hole_semi_axes: tuple[float, float]
    rim_radius: float
    tail_from: str
    tail_differences: list[str] = field(default_factory=list)
    imaging_arm: ArmReport = field(default_factory=ArmReport)
    illumination_arm: ArmReport = field(default_factory=ArmReport)
    tail: ArmReport = field(default_factory=ArmReport)
    sources: list[str] = field(default_factory=list)
    detectors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    arms: dict[str, ArmReport] = field(default_factory=dict)

    @classmethod
    def unfolded(cls) -> FoldReport:
        """A report for a system that was converted path by path, not folded."""
        return cls(
            fold_z=math.nan,
            angle_deg=0.0,
            hole_semi_axes=(0.0, 0.0),
            rim_radius=0.0,
            tail_from="",
        )

    @property
    def is_fold(self) -> bool:
        """Whether the report describes a fold (as opposed to path conversions)."""
        return not math.isnan(self.fold_z)

    def summary(self) -> str:
        """Multi-line summary for logs and reports."""
        if self.is_fold:
            lines = [
                f"fold mirror at z = {self.fold_z:.4f} mm, tilt {self.angle_deg:g} "
                f"deg, hole {2 * self.hole_semi_axes[0]:.3f} x "
                f"{2 * self.hole_semi_axes[1]:.3f} mm, rim diameter "
                f"{2 * self.rim_radius:.3f} mm",
                f"shared tail from the {self.tail_from} file",
            ]
            if self.tail_differences:
                lines.append("tail differences between the two files:")
                lines.extend(f"  - {d}" for d in self.tail_differences)
            else:
                lines.append("both files agree on the shared tail")
            arms = [
                ("tail", self.tail),
                ("imaging arm", self.imaging_arm),
                ("illumination arm", self.illumination_arm),
            ]
        else:
            lines = [f"unfolded system: {len(self.arms)} path(s) converted in place"]
            arms = list(self.arms.items())
        for label, arm in arms:
            lines.append(
                f"{label}: {len(arm.components)} surfaces, {len(arm.baffles)} "
                f"baffles, {len(arm.aperture_only)} aperture-only, "
                f"{len(arm.lossless)} lossless"
            )
            lines.extend(f"  - {n}" for n in arm.notes)
        lines.append(f"sources: {', '.join(self.sources)}")
        lines.append(f"detectors: {', '.join(self.detectors)}")
        lines.extend(f"note: {n}" for n in self.notes)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tail comparison
# ---------------------------------------------------------------------------


def _index_at(material, wavelength: float) -> float:
    if material is None:
        return 1.0
    return _scalar(material.n(wavelength))


def _medium_label(material) -> str:
    """A short name of a sequential medium for messages (``N-BK7``, ``n=1``)."""
    name = getattr(material, "name", None)
    if name:
        return str(name)
    index = getattr(material, "index", None)
    return "unknown medium" if index is None else f"n={_scalar(index):g}"


def _surface_z(surface) -> float:
    return _scalar(surface.geometry.cs.position_in_gcs[2])


def _led_ring_emitter(
    ring: LEDRing, cone_deg: float, normalised_flux: float
) -> tuple[ExtendedSourceConfig | LEDRingSourceConfig, str]:
    """Source config and report note of an illumination path's LED ring.

    Args:
        ring: The LED ring of the illumination optic.
        cone_deg: Half angle of the emission cone [deg].
        normalised_flux: Flux inside the cone [W] when the LED flux is not
            known.

    Returns:
        ``(config, note)``: discrete chips (``LEDRingSourceConfig``) or a
        homogeneous annulus (``ExtendedSourceConfig``), with the ring's
        radiation pattern and LED spectrum. A known LED flux is emitted as
        ``count x flux x`` (share of the pattern inside the cone).
    """
    from optiland.nonsequential.sources.base import Spectrum  # noqa: PLC0415
    from optiland.nonsequential.sources.configs import (  # noqa: PLC0415
        ExtendedSourceConfig,
        LEDRingSourceConfig,
    )
    from optiland.nonsequential.units import lumens_to_watts  # noqa: PLC0415

    led = ring.led
    spectrum = Spectrum(*led.spectrum.density())
    pattern = led.radiation
    radiation = None if pattern.kind == "lambertian" else pattern
    if led.flux is None:
        flux = normalised_flux
        flux_text = f"{flux:g} W inside the cone (LED flux unknown, normalised)"
    else:
        per_led = (
            led.flux if led.flux_unit == "W" else lumens_to_watts(led.flux, spectrum)
        )
        share = pattern.flux_fraction(cone_deg)
        flux = ring.count * per_led * share
        flux_text = (
            f"{ring.count} x {led.flux:g} {led.flux_unit}, {share:.1%} inside the "
            f"cone: {flux:g} W"
        )
    if ring.emitter_model == "discrete":
        config = LEDRingSourceConfig(
            spectrum=spectrum,
            total_flux=flux,
            count=ring.count,
            pitch_radius=ring.pitch_radius,
            chip_width=led.chip_width,
            chip_height=led.chip_height,
            first_angle_deg=ring.first_angle_deg,
            half_angle_deg=cone_deg,
            radiation=radiation,
        )
        shape = (
            f"{ring.count} chips {led.chip_width:g} x {led.chip_height:g} mm on "
            f"pitch diameter {ring.pitch_diameter:g} mm"
        )
    else:
        config = ExtendedSourceConfig(
            spectrum=spectrum,
            total_flux=flux,
            aperture_radius=ring.outer_radius,
            inner_radius=ring.inner_radius,
            half_angle_deg=cone_deg,
            lambertian_cone=True,
            radiation=radiation,
        )
        shape = (
            f"annulus {ring.inner_radius:g}..{ring.outer_radius:g} mm "
            f"({ring.count} LEDs smeared)"
        )
    if pattern.kind == "lambertian":
        pattern_text = "Lambertian"
    elif pattern.kind == "half_angle":
        pattern_text = (
            f"cos^{pattern.cos_power:.2f} (half angle {pattern.half_angle_deg:g} deg)"
        )
    else:
        pattern_text = f"tabulated pattern ({len(pattern.angles_deg)} angles)"
    spec = led.spectrum
    if spec.kind == "line":
        spectrum_text = f"{spec.center_um * 1000:g} nm"
    elif spec.kind == "gaussian":
        spectrum_text = f"{spec.center_um * 1000:g} nm, FWHM {spec.fwhm_um * 1000:g} nm"
    else:
        spectrum_text = f"tabulated spectrum, peak {spec.peak_um * 1000:g} nm"
    label = f" {led.name}" if led.name else ""
    note = (
        f"illumination emitter from the LED ring{label}: {shape}, {pattern_text}, "
        f"{spectrum_text}, cone {cone_deg:.1f} deg, {flux_text}"
    )
    return config, note


def compare_tails(
    imaging: Optic,
    illumination: Optic,
    fold_imaging: int,
    fold_illumination: int,
    *,
    tol: float = 1e-6,
) -> list[str]:
    """Compare the two copies of the shared tail surface by surface.

    The imaging tail is ``imaging.surfaces[1:fold_imaging]`` read backwards
    (from the fold towards the sample); the illumination tail is
    ``illumination.surfaces[fold_illumination + 1 : -1]`` read forwards.
    Matching surfaces must have opposite radii and coefficients, equal
    conics and apertures, equal gaps and the same media (compared by index
    at the imaging primary wavelength).

    Args:
        imaging: Imaging optic (sample -> camera).
        illumination: Illumination optic (source -> sample).
        fold_imaging: Index of the fold (hole) surface in ``imaging``.
        fold_illumination: Index of the fold (ring) surface in
            ``illumination``.
        tol: Absolute tolerance for lengths [mm] and indices.

    Returns:
        One line per mismatch; empty when the tails agree.
    """
    s_img = list(imaging.surfaces.surfaces)
    s_ill = list(illumination.surfaces.surfaces)
    tail_img = s_img[1:fold_imaging][::-1]
    tail_ill = s_ill[fold_illumination + 1 : len(s_ill) - 1]
    wavelength = float(imaging.wavelengths.primary_wavelength.value)
    diffs: list[str] = []

    if len(tail_img) != len(tail_ill):
        diffs.append(
            f"tail length: imaging has {len(tail_img)} surfaces before the fold, "
            f"illumination has {len(tail_ill)} after it"
        )

    gap_img = _surface_z(s_img[fold_imaging]) - _surface_z(s_img[fold_imaging - 1])
    gap_ill = _surface_z(s_ill[fold_illumination + 1]) - _surface_z(
        s_ill[fold_illumination]
    )
    if abs(gap_img - gap_ill) > tol:
        diffs.append(
            f"fold -> first tail surface: imaging {gap_img:.4f} mm, "
            f"illumination {gap_ill:.4f} mm"
        )

    for k, (a, b) in enumerate(zip(tail_img, tail_ill, strict=False)):
        ia = fold_imaging - 1 - k
        ib = fold_illumination + 1 + k
        tag = f"imaging[{ia}] vs illumination[{ib}]"
        ra, rb = _surface_radius(a), _surface_radius(b)
        both_flat = not (math.isfinite(ra) or math.isfinite(rb))
        both_curved = math.isfinite(ra) and math.isfinite(rb)
        if not both_flat and (not both_curved or abs(ra + rb) > tol):
            diffs.append(f"{tag}: radius {ra:g} vs {rb:g} (expected opposite)")
        if abs(_surface_conic(a) - _surface_conic(b)) > tol:
            diffs.append(f"{tag}: conic {_surface_conic(a):g} vs {_surface_conic(b):g}")
        ca, cb = _surface_coefficients(a), _surface_coefficients(b)
        if len(ca) != len(cb) or any(
            abs(x + y) > tol for x, y in zip(ca, cb, strict=False)
        ):
            diffs.append(f"{tag}: asphere coefficients differ (expected opposite)")
        ap_a, ap_b = _aperture_of(a, imaging, ia), _aperture_of(b, illumination, ib)
        if (ap_a.r_max or 0.0) - (ap_b.r_max or 0.0) > tol or (ap_b.r_max or 0.0) - (
            ap_a.r_max or 0.0
        ) > tol:
            diffs.append(f"{tag}: aperture radius {ap_a.r_max:g} vs {ap_b.r_max:g}")
        n_pre_a = _index_at(a.material_pre, wavelength)
        n_post_a = _index_at(a.material_post, wavelength)
        n_pre_b = _index_at(b.material_pre, wavelength)
        n_post_b = _index_at(b.material_post, wavelength)
        if abs(n_pre_a - n_post_b) > 1e-3 or abs(n_post_a - n_pre_b) > 1e-3:
            diffs.append(
                f"{tag}: media n = {n_pre_a:.4f}|{n_post_a:.4f} vs "
                f"{n_post_b:.4f}|{n_pre_b:.4f} (reversed)"
            )
        if k + 1 < min(len(tail_img), len(tail_ill)):
            g_a = _surface_z(a) - _surface_z(tail_img[k + 1])
            g_b = _surface_z(tail_ill[k + 1]) - _surface_z(b)
            if abs(g_a - g_b) > tol:
                diffs.append(f"{tag}: gap to next {g_a:.4f} mm vs {g_b:.4f} mm")

    if tail_img and tail_ill:
        obj_gap = _surface_z(s_img[1]) - _surface_z(s_img[0])
        img_gap = _surface_z(s_ill[-1]) - _surface_z(s_ill[-2])
        if abs(obj_gap - img_gap) > tol:
            diffs.append(
                f"sample distance: imaging object {obj_gap:.4f} mm, "
                f"illumination image {img_gap:.4f} mm"
            )
    return diffs


# ---------------------------------------------------------------------------
# The fold
# ---------------------------------------------------------------------------


def fold_paths(
    imaging: Optic,
    illumination: Optic,
    fold_imaging: int,
    fold_illumination: int,
    *,
    angle_deg: float = 45.0,
    hole: HoleShape = "projected",
    tail_from: TailSource = "imaging",
    mirror_reflectance: float = 1.0,
    lossless: bool | Callable[[int, object], bool] = glass_surfaces_lossless,
    illumination_flux: float = 1.0,
    object_flux: float = 1.0,
    illumination_half_angle_deg: float | None = None,
    object_half_angle_deg: float | None = None,
    sample_size: float | None = None,
    camera_pixels: tuple[int, int] = (256, 256),
    sample_pixels: tuple[int, int] = (128, 128),
    dump_distance: float = 30.0,
) -> tuple[NSQScene, FoldReport]:
    """Fold an imaging and an illumination path at a perforated mirror.

    Args:
        imaging: Sequential optic traced from the sample (object) to the
            camera (image). Its coordinates become the global frame.
        illumination: Sequential optic traced from the light source
            (object) to the sample (image).
        fold_imaging: Index of the imaging surface that is the mirror
            hole (an air-to-air aperture).
        fold_illumination: Index of the illumination surface that is the
            mirror ring (an air-to-air annular aperture).
        angle_deg: Mirror tilt about the global y axis [deg]; 45 folds the
            illumination arm, which lies along -x, onto -z.
        hole: ``"projected"`` makes the hole an ellipse in the mirror plane
            so that it appears as the imaging file's circular aperture
            along the axis; ``"physical"`` keeps the circle of that
            diameter in the mirror plane (a smaller, elliptical aperture on
            axis).
        tail_from: Which file supplies the shared tail between the sample
            and the fold. The other copy is compared and differences are
            reported.
        mirror_reflectance: Reflectance of the ring mirror.
        lossless: Coating policy for refractive surfaces, see
            :func:`~optiland.nonsequential.surface_conversion.add_optic_surfaces`.
            The default coats catalog glass and leaves constant-index media
            (an eye model) with Fresnel reflection.
        illumination_flux: Flux of the illumination source inside its cone
            [W]; not used when the illumination path's LED ring states the
            flux of its LEDs.
        object_flux: Flux of each sample point source [W].
        illumination_half_angle_deg: Cone half angle of the illumination
            emitter; ``None`` derives it from the illumination entrance
            pupil.
        object_half_angle_deg: Cone half angle of the sample sources;
            ``None`` derives it per field from the imaging entrance pupil.
        sample_size: Edge length of the square sample detector [mm];
            ``None`` = the larger of 2.6 times the largest imaging field
            height and 2.2 times the illumination's paraxial image height
            (at least 1 mm).
        camera_pixels: Pixel counts of the camera detector.
        sample_pixels: Pixel counts of the sample detector.
        dump_distance: Distance of the hole-leak dump behind the mirror
            along +x [mm].

    Returns:
        ``(scene, report)``.

    Raises:
        ConversionError: If a fold index is not an air-to-air aperture or a
            geometry is unsupported.
        ValueError: For an out-of-range fold index.
    """
    from optiland.coordinate_system import CoordinateSystem  # noqa: PLC0415
    from optiland.nonsequential.components.geometry.analytic.annulus import (  # noqa: PLC0415
        AnnularPlaneGeometry,
    )
    from optiland.nonsequential.components.reflective import (  # noqa: PLC0415
        ReflectiveComponent,
    )
    from optiland.nonsequential.detectors.configs import (  # noqa: PLC0415
        IrradianceDetectorConfig,
    )
    from optiland.nonsequential.scene import NSQScene  # noqa: PLC0415
    from optiland.nonsequential.sources.configs import (  # noqa: PLC0415
        ExtendedSourceConfig,
    )
    from optiland.nonsequential.surface_conversion import _same_medium  # noqa: PLC0415

    s_img = list(imaging.surfaces.surfaces)
    s_ill = list(illumination.surfaces.surfaces)
    if not 1 <= fold_imaging < len(s_img) - 1:
        raise ValueError(f"fold_imaging={fold_imaging} is not an inner surface.")
    if not 1 <= fold_illumination < len(s_ill) - 1:
        raise ValueError(
            f"fold_illumination={fold_illumination} is not an inner surface."
        )
    for label, surface, index in (
        ("imaging", s_img[fold_imaging], fold_imaging),
        ("illumination", s_ill[fold_illumination], fold_illumination),
    ):
        if not _same_medium(surface.material_pre, surface.material_post):
            comment = str(getattr(surface, "comment", "") or "").strip()
            where = f"surface {index}" + (f" {comment!r}" if comment else "")
            raise ConversionError(
                f"The {label} fold surface must be an air-to-air aperture, but "
                f"{where} separates two different media "
                f"({_medium_label(surface.material_pre)} | "
                f"{_medium_label(surface.material_post)}). If surfaces were "
                "inserted or removed ahead of it, the fold index no longer "
                "points at the mirror."
            )

    hole_ap = _aperture_of(s_img[fold_imaging], imaging, fold_imaging)
    ring_ap = _aperture_of(s_ill[fold_illumination], illumination, fold_illumination)
    r_hole = float(hole_ap.r_max or 0.0)
    r_rim = float(ring_ap.r_max or 0.0)
    if r_hole <= 0.0 or r_rim <= r_hole:
        raise ConversionError(
            f"Mirror apertures are inconsistent: hole radius {r_hole:g} mm, rim "
            f"radius {r_rim:g} mm."
        )
    angle = math.radians(angle_deg)
    if hole == "projected":
        semi_axes = (r_hole / math.cos(angle), r_hole)
    elif hole == "physical":
        semi_axes = (r_hole, r_hole)
    else:
        raise ValueError(f"hole must be 'projected' or 'physical', not {hole!r}.")

    x_fold, y_fold, z_fold = (
        _scalar(v) for v in s_img[fold_imaging].geometry.cs.position_in_gcs
    )
    z_fold_ill = _surface_z(s_ill[fold_illumination])

    report = FoldReport(
        fold_z=z_fold,
        angle_deg=angle_deg,
        hole_semi_axes=semi_axes,
        rim_radius=r_rim,
        tail_from=tail_from,
        tail_differences=compare_tails(
            imaging, illumination, fold_imaging, fold_illumination
        ),
    )
    if ring_ap.r_min > 0.0 and abs(ring_ap.r_min - r_hole) > 1e-6:
        report.notes.append(
            f"illumination ring inner radius {ring_ap.r_min:g} mm differs from "
            f"the imaging hole radius {r_hole:g} mm; the hole is used"
        )

    scene = NSQScene()

    # Fold mirror: normal (sin a, 0, cos a). A beam along +x reflects to -z.
    mirror_cs = CoordinateSystem(x=x_fold, y=y_fold, z=z_fold, ry=angle)
    scene.add_component(
        MIRROR,
        ReflectiveComponent(
            cs=mirror_cs,
            geometry=AnnularPlaneGeometry(
                inner_radius=semi_axes[0],
                outer_radius=r_rim,
                inner_radius_y=semi_axes[1],
            ),
            reflectance=mirror_reflectance,
            name=MIRROR,
        ),
    )

    # Illumination arm along -x: local +z -> global +x.
    frame_ill = CoordinateSystem(
        x=x_fold - z_fold_ill, y=y_fold, z=z_fold, ry=math.pi / 2
    )
    report.illumination_arm = add_optic_surfaces(
        scene,
        illumination,
        frame=frame_ill,
        start=1,
        stop=fold_illumination,
        prefix="ill.",
        lossless=lossless,
    )

    # Shared tail.
    if tail_from == "imaging":
        report.tail = add_optic_surfaces(
            scene,
            imaging,
            start=1,
            stop=fold_imaging,
            prefix="tail.",
            lossless=lossless,
        )
    elif tail_from == "illumination":
        # Reverse the illumination tail onto the imaging axis: local +z -> -z.
        frame_tail = CoordinateSystem(
            x=x_fold, y=y_fold, z=z_fold + z_fold_ill, ry=math.pi
        )
        report.tail = add_optic_surfaces(
            scene,
            illumination,
            frame=frame_tail,
            start=fold_illumination + 1,
            stop=len(s_ill) - 1,
            prefix="tail.",
            lossless=lossless,
        )
    else:
        raise ValueError(
            f"tail_from must be 'imaging' or 'illumination', not {tail_from!r}."
        )

    # Imaging arm behind the mirror.
    report.imaging_arm = add_optic_surfaces(
        scene,
        imaging,
        start=fold_imaging + 1,
        stop=len(s_img) - 1,
        prefix="img.",
        lossless=lossless,
    )

    # Sources: sample points (imaging fields) and the illumination emitter.
    report.sources.extend(
        add_field_point_sources(
            scene,
            imaging,
            prefix=OBJECT_PREFIX,
            total_flux=object_flux,
            half_angle_deg=object_half_angle_deg,
        )
    )
    # The emitter comes from the illumination path's LED ring when it has
    # one; otherwise the ring is guessed from the span of its field radii.
    led_ring = getattr(illumination, "light_source", None)
    if led_ring is not None:
        r_inner, r_outer = led_ring.inner_radius, led_ring.outer_radius
    else:
        ill_points = object_field_points(illumination)
        radii = [math.hypot(x, y) for x, y, _ in ill_points]
        r_outer = max(radii)
        r_inner = min(radii)
    z_pupil, epd = entrance_pupil(illumination)
    obj_z = _surface_z(s_ill[0])
    if illumination_half_angle_deg is None:
        angle_ill = math.degrees(math.atan2(epd / 2.0 + r_outer, abs(z_pupil - obj_z)))
        cone_ill = min(89.0, 1.15 * angle_ill)
    else:
        cone_ill = illumination_half_angle_deg
    if r_outer <= 0.0:
        raise ConversionError(
            "The illumination fields are all on axis; an extended emitter needs "
            "a non-zero object height."
        )
    if led_ring is not None:
        emitter, emitter_note = _led_ring_emitter(led_ring, cone_ill, illumination_flux)
    else:
        emitter = ExtendedSourceConfig(
            spectrum=_build_spectrum(illumination),
            total_flux=illumination_flux,
            aperture_radius=r_outer,
            inner_radius=r_inner if 0.0 < r_inner < r_outer else None,
            half_angle_deg=cone_ill,
            lambertian_cone=True,
        )
        emitter_note = (
            f"illumination emitter: ring {r_inner:g}..{r_outer:g} mm, the span of "
            f"the illumination field radii, Lambertian cone {cone_ill:.1f} deg, "
            f"{illumination_flux:g} W inside the cone (declare the LED ring of "
            "the illumination path for the true emitter)"
        )
    scene.add_source(
        ILLUMINATION,
        flat_coordinate_system(s_ill[0].geometry.cs, frame_ill),
        emitter,
    )
    report.sources.append(ILLUMINATION)
    report.notes.append(emitter_note)

    # Detectors.
    add_image_detector(scene, imaging, CAMERA, num_pixels=camera_pixels)
    report.detectors.append(CAMERA)

    if sample_size is None:
        fields = object_field_points(imaging)
        field_extent = 2.6 * max(math.hypot(x, y) for x, y, _ in fields)
        try:
            y_chief, _ = illumination.paraxial.chief_ray()
            illuminated = 2.2 * abs(_scalar(y_chief[-1]))
        except Exception:  # noqa: BLE001 -- no paraxial data: field only
            illuminated = 0.0
        sample_size = max(1.0, field_extent, illuminated)
    sample_cs = flat_coordinate_system(s_img[0].geometry.cs)
    scene.add_detector(
        SAMPLE,
        sample_cs,
        IrradianceDetectorConfig(
            width=sample_size,
            height=sample_size,
            num_pixels_x=sample_pixels[0],
            num_pixels_y=sample_pixels[1],
        ),
    )
    report.detectors.append(SAMPLE)

    coarse = IrradianceDetectorConfig(
        width=2.0 * r_rim + 4.0,
        height=2.0 * r_rim + 4.0,
        num_pixels_x=32,
        num_pixels_y=32,
    )
    scene.add_detector(
        DUMP,
        CoordinateSystem(x=x_fold + dump_distance, y=y_fold, z=z_fold, ry=-math.pi / 2),
        coarse,
    )
    report.detectors.append(DUMP)
    scene.add_detector(
        RETURN,
        CoordinateSystem(
            x=x_fold - z_fold_ill + obj_z - 1.0, y=y_fold, z=z_fold, ry=math.pi / 2
        ),
        coarse,
    )
    report.detectors.append(RETURN)
    return scene, report


def trace_per_source(
    scene: NSQScene,
    num_rays: int,
    *,
    seed: int | None = None,
    sources: list[str] | None = None,
    **trace_kwargs,
) -> dict[str, object]:
    """Trace the scene once per source with all other sources removed.

    A detector's flux is otherwise the sum over every source, which hides
    which arm the light came from -- the whole point of a folded scene.
    Each trace launches ``num_rays`` rays from the one active source; the
    registry is restored afterwards even if a trace fails.

    Args:
        scene: The scene.
        num_rays: Rays per source.
        seed: RNG seed (the same for every source).
        sources: Registry names to trace; ``None`` = all.
        **trace_kwargs: Forwarded to :meth:`NSQScene.trace`.

    Returns:
        ``{source_name: SimulationResult}`` in registry order.
    """
    registry = scene.source_registry
    saved = dict(registry._registry)
    names = list(saved) if sources is None else list(sources)
    results: dict[str, object] = {}
    try:
        for name in names:
            registry._registry.clear()
            registry._registry[name] = saved[name]
            results[name] = scene.trace(num_rays=num_rays, seed=seed, **trace_kwargs)
    finally:
        registry._registry.clear()
        registry._registry.update(saved)
    return results
