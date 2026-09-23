"""Surface-by-surface conversion of a sequential optic into an NSQ scene.

Covers what the grouped converter cannot: constant-index media (an eye
model), aspheres, air-to-air apertures, obscurations, an arbitrary frame,
aimed point sources on a curved object and a rectangular image detector.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import optiland.backend as be
from optiland.coordinate_system import CoordinateSystem
from optiland.nonsequential import (
    VACUUM,
    AbsorbingComponent,
    EvenAsphereGeometry,
    NSQScene,
    RefractiveComponent,
)
from optiland.nonsequential.components.base import _get_transform
from optiland.nonsequential.components.geometry.analytic.annulus import (
    AnnularPlaneGeometry,
)
from optiland.nonsequential.components.geometry.analytic.plane import (
    FinitePlaneGeometry,
)
from optiland.nonsequential.convert import ConversionError
from optiland.nonsequential.ir.lower import lower
from optiland.nonsequential.serialization import scene_from_dict, scene_to_dict
from optiland.nonsequential.surface_conversion import (
    add_field_point_sources,
    add_image_detector,
    add_optic_surfaces,
    aim_coordinate_system,
    flat_coordinate_system,
    glass_surfaces_lossless,
    object_field_points,
)
from optiland.optic import Optic
from optiland.physical_apertures import RadialAperture, RectangularAperture


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _eye_and_lens_optic() -> Optic:
    """A curved 'retina' object in a liquid, an ideal-index eye lens, a
    stop, an aspheric glass singlet and a rectangular image."""
    from optiland.materials import IdealMaterial

    optic = Optic()
    optic.add_surface(
        index=0, radius=2.0, thickness=1.0, material=IdealMaterial(n=1.336)
    )
    optic.add_surface(
        index=1,
        radius=-1.5,
        thickness=1.0,
        material=IdealMaterial(n=1.4),
        aperture=RadialAperture(0.8),
    )
    optic.add_surface(index=2, thickness=5.0, aperture=RadialAperture(0.6))
    optic.add_surface(
        index=3, thickness=3.0, is_stop=True, aperture=RadialAperture(2.0, 0.3)
    )
    optic.add_surface(
        index=4,
        radius=10.0,
        thickness=3.0,
        material="N-BK7",
        surface_type="even_asphere",
        coefficients=[0.0, -1e-4],
        aperture=RadialAperture(4.0),
    )
    optic.add_surface(
        index=5, radius=-10.0, thickness=8.0, aperture=RadialAperture(4.0)
    )
    optic.add_surface(index=6, aperture=RectangularAperture(-3.0, 3.0, -2.0, 2.0))
    optic.set_aperture(aperture_type="float_by_stop_size", value=4.0)
    optic.set_field_type(field_type="object_height")
    optic.add_field(y=0.0)
    optic.add_field(y=0.5)
    optic.add_wavelength(value=0.55, is_primary=True)
    return optic


def _ideal(optic: Optic, index: int):
    from optiland.materials.ideal import IdealMaterial

    return isinstance(optic.surfaces.surfaces[index].material_post, IdealMaterial)


def _f(value) -> float:
    return float(np.ravel(be.to_numpy(value))[0])


class TestCoordinateSystems:
    @pytest.mark.parametrize(
        "target",
        [(0.0, 0.0, 10.0), (3.0, -2.0, 5.0), (-1.0, 4.0, -7.0), (5.0, 0.0, 0.0)],
    )
    def test_aimed_z_axis_points_at_the_target(self, target):
        position = (1.0, 2.0, 3.0)
        cs = aim_coordinate_system(position, target)
        translation, rot = _get_transform(cs)
        axis = rot @ np.array([0.0, 0.0, 1.0])
        d = np.asarray(target) - np.asarray(position)
        assert np.allclose(axis, d / np.linalg.norm(d))
        assert np.allclose(translation, position)

    def test_flat_copy_reproduces_a_nested_pose(self):
        frame = CoordinateSystem(x=5.0, z=20.0, ry=math.pi / 2)
        nested = CoordinateSystem(y=1.0, z=3.0, rx=0.2, reference_cs=frame)
        flat = flat_coordinate_system(nested)
        t1, r1 = _get_transform(nested)
        t2, r2 = _get_transform(flat)
        assert flat.reference_cs is None
        assert np.allclose(t1, t2) and np.allclose(r1, r2)

    def test_flat_copy_into_a_frame(self):
        frame = CoordinateSystem(x=-100.0, ry=math.pi / 2)
        cs = flat_coordinate_system(CoordinateSystem(z=30.0), frame)
        translation, rot = _get_transform(cs)
        assert np.allclose(translation, [-70.0, 0.0, 0.0])
        assert np.allclose(rot @ np.array([0.0, 0.0, 1.0]), [1.0, 0.0, 0.0])


class TestAddOpticSurfaces:
    def test_every_surface_kind_is_placed(self):
        optic = _eye_and_lens_optic()
        assert _ideal(optic, 0) and _ideal(optic, 1)
        scene = NSQScene()
        report = add_optic_surfaces(scene, optic, prefix="a.")
        names = scene.component_names
        # Surfaces 1, 2 (ideal media), 4, 5 (glass) refract; 3 is a stop.
        assert report.components == ["a.S1", "a.S2", "a.S4", "a.S5"]
        assert report.aperture_only == [3]
        assert "a.S3.rim" in names and "a.S3.obscuration" in names
        assert report.lossless == []
        rim = scene.component_registry.get("a.S3.rim").component
        assert isinstance(rim, AbsorbingComponent)
        assert isinstance(rim.geometry, AnnularPlaneGeometry)
        assert float(rim.geometry.inner_radius) == pytest.approx(2.0)
        disk = scene.component_registry.get("a.S3.obscuration").component
        assert isinstance(disk.geometry, FinitePlaneGeometry)
        assert float(disk.geometry.aperture_radius) == pytest.approx(0.3)
        asphere = scene.component_registry.get("a.S4").component
        assert isinstance(asphere, RefractiveComponent)
        assert isinstance(asphere.geometry, EvenAsphereGeometry)
        assert asphere.material_front is VACUUM
        assert asphere.material_back.optiland_material.name == "N-BK7"

    def test_ideal_media_are_shared_between_neighbours(self):
        optic = _eye_and_lens_optic()
        scene = NSQScene()
        add_optic_surfaces(scene, optic)
        s1 = scene.component_registry.get("S1").component
        s2 = scene.component_registry.get("S2").component
        assert s1.material_back is s2.material_front
        assert _f(s1.material_front.n(0.55)) == pytest.approx(1.336)
        assert _f(s1.material_back.n(0.55)) == pytest.approx(1.4)
        assert s2.material_back is VACUUM

    def test_lossless_policy(self):
        optic = _eye_and_lens_optic()
        scene = NSQScene()
        report = add_optic_surfaces(scene, optic, lossless=glass_surfaces_lossless)
        assert report.lossless == ["S4", "S5"]
        glass = scene.component_registry.get("S4").component
        assert glass.coating.reflectance == 0.0 and glass.coating.transmittance == 1.0
        assert scene.component_registry.get("S1").component.coating is None
        everything = NSQScene()
        assert add_optic_surfaces(everything, optic, lossless=True).lossless == [
            "S1",
            "S2",
            "S4",
            "S5",
        ]

    def test_rim_sits_at_the_surface_edge(self):
        optic = _eye_and_lens_optic()
        scene = NSQScene()
        add_optic_surfaces(scene, optic, start=1, stop=2)
        rim = scene.component_registry.get("S1.rim").component
        surface = optic.surfaces.surfaces[1]
        assert float(rim.geometry.z_offset) == pytest.approx(
            float(surface.geometry.sag(0.8, 0.0))
        )

    def test_range_and_frame(self):
        optic = _eye_and_lens_optic()
        scene = NSQScene()
        frame = CoordinateSystem(x=-50.0, ry=math.pi / 2)
        report = add_optic_surfaces(scene, optic, frame=frame, start=4, stop=6)
        assert report.components == ["S4", "S5"]
        translation, rot = _get_transform(
            scene.component_registry.get("S5").component.cs
        )
        z5 = float(optic.surfaces.surfaces[5].geometry.cs.z)
        assert np.allclose(translation, [-50.0 + z5, 0.0, 0.0])
        assert np.allclose(rot @ np.array([0.0, 0.0, 1.0]), [1.0, 0.0, 0.0])
        with pytest.raises(ValueError, match="outside"):
            add_optic_surfaces(NSQScene(), optic, start=0, stop=99)

    def test_scene_lowers_strictly_and_round_trips(self):
        optic = _eye_and_lens_optic()
        scene = NSQScene()
        add_optic_surfaces(scene, optic)
        add_field_point_sources(scene, optic)
        add_image_detector(scene, optic, "camera")
        ir = lower(scene, strict=True)
        media = {m.name: m.n_model for m in ir.media}
        assert any(m["kind"] == "constant" and m["n"] == 1.336 for m in media.values())
        restored = scene_from_dict(scene_to_dict(scene))
        a = scene.trace(num_rays=512, seed=4).detectors["camera"]
        b = restored.trace(num_rays=512, seed=4).detectors["camera"]
        assert a.total_flux_float == pytest.approx(b.total_flux_float)
        assert a.num_rays_hit == b.num_rays_hit > 0

    def test_unsupported_geometry_raises(self):
        optic = Optic()
        optic.add_surface(index=0, thickness=10.0)
        optic.add_surface(index=1, radius=20.0, thickness=3.0, material="N-BK7")
        optic.add_surface(
            index=2, thickness=10.0, surface_type="toroidal", radius=40.0, radius_x=30.0
        )
        optic.add_surface(index=3)
        optic.set_aperture(aperture_type="EPD", value=5.0)
        optic.set_field_type(field_type="object_height")
        optic.add_field(y=0.0)
        optic.add_wavelength(value=0.55, is_primary=True)
        with pytest.raises(ConversionError, match="not supported"):
            add_optic_surfaces(NSQScene(), optic)


def _masked_stop_optic(aperture) -> Optic:
    """A collimated beam (EPD 10) through an air-to-air stop carrying
    *aperture*, onto an image plane 5 mm behind it."""
    optic = Optic()
    optic.add_surface(index=0, thickness=np.inf)
    optic.add_surface(index=1, thickness=5.0, is_stop=True, aperture=aperture)
    optic.add_surface(index=2, aperture=RectangularAperture(-6.0, 6.0, -6.0, 6.0))
    optic.set_aperture(aperture_type="EPD", value=10.0)
    optic.fields.set_type("angle")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    return optic


def _irradiance_by_radius(optic: Optic):
    """Trace the beam; return the image irradiance and each pixel's radius.

    The detector splats every hit bilinearly onto the pixels within one
    pitch (0.25 mm) in x and y, so a shadow edge blurs by up to 0.36 mm.
    """
    from optiland.nonsequential.surface_conversion import (
        add_collimated_field_sources,
    )

    scene = NSQScene()
    add_optic_surfaces(scene, optic)
    add_collimated_field_sources(scene, optic)
    add_image_detector(scene, optic, "camera", num_pixels=(48, 48))
    detector = scene.trace(num_rays=40_000, seed=3).detectors["camera"]
    x, y = np.meshgrid(
        np.asarray(detector.x_coords), np.asarray(detector.y_coords)
    )
    return np.asarray(detector.irradiance), np.hypot(x, y)


class TestMaskApertures:
    """O1: a mask stop (``DifferenceAperture`` of two centred radial
    apertures, the Lens Data Editor's Circular/Annular Mask) crashed the
    conversion with "'tuple' object is not callable"; the blocked disk or
    ring must absorb in the NSQ scene."""

    @staticmethod
    def _mask(clear: float, blocked_outer: float, blocked_inner: float = 0.0):
        from optiland.physical_apertures import DifferenceAperture

        return DifferenceAperture(
            RadialAperture(r_max=clear, r_min=0.0),
            RadialAperture(r_max=blocked_outer, r_min=blocked_inner),
        )

    def test_circular_mask_becomes_an_absorbing_disk(self):
        optic = _masked_stop_optic(self._mask(6.0, 2.0))
        scene = NSQScene()
        report = add_optic_surfaces(scene, optic)

        rim = scene.component_registry.get("S1.rim").component
        assert float(rim.geometry.inner_radius) == pytest.approx(6.0)
        disk = scene.component_registry.get("S1.mask").component
        assert isinstance(disk, AbsorbingComponent)
        assert isinstance(disk.geometry, FinitePlaneGeometry)
        assert float(disk.geometry.aperture_radius) == pytest.approx(2.0)
        assert "S1.mask" in report.baffles

    def test_annular_mask_becomes_an_absorbing_ring(self):
        optic = _masked_stop_optic(self._mask(6.0, 3.0, 2.0))
        scene = NSQScene()
        add_optic_surfaces(scene, optic)

        ring = scene.component_registry.get("S1.mask").component
        assert isinstance(ring, AbsorbingComponent)
        assert isinstance(ring.geometry, AnnularPlaneGeometry)
        assert float(ring.geometry.inner_radius) == pytest.approx(2.0)
        assert float(ring.geometry.outer_radius) == pytest.approx(3.0)

    def test_circular_mask_casts_its_shadow(self):
        irradiance, r = _irradiance_by_radius(
            _masked_stop_optic(self._mask(6.0, 2.0))
        )
        assert irradiance[r < 1.6].max() == 0.0
        assert irradiance[(r > 2.5) & (r < 4.5)].min() > 0.0

    def test_annular_mask_casts_a_ring_shadow(self):
        irradiance, r = _irradiance_by_radius(
            _masked_stop_optic(self._mask(6.0, 3.0, 2.0))
        )
        assert irradiance[(r > 2.4) & (r < 2.6)].max() == 0.0
        assert irradiance[r < 1.6].min() > 0.0
        assert irradiance[(r > 3.4) & (r < 4.5)].min() > 0.0

    def test_other_shapes_convert_to_their_circumscribed_circle(self):
        from optiland.physical_apertures import EllipticalAperture

        optic = _masked_stop_optic(EllipticalAperture(a=6.0, b=5.5))
        scene = NSQScene()
        report = add_optic_surfaces(scene, optic)

        rim = scene.component_registry.get("S1.rim").component
        assert float(rim.geometry.inner_radius) == pytest.approx(6.0)
        assert any(
            "S1" in note and "EllipticalAperture" in note for note in report.notes
        )


class TestUnboundedClearAperture:
    """A mask with an infinite clear radius (the Lens Data Editor accepts
    ``inf``) or a ring aperture without outer edge became a rim baffle with
    ``inner_radius == outer_radius == inf``; drawing the System view then
    computed ``inf * 0`` ("invalid value encountered in multiply"). Such a
    surface declares no clear edge: it gets no rim at all, unlike a surface
    without any aperture, whose rim is estimated."""

    def test_a_mask_without_a_clear_edge_gets_no_rim(self):
        optic = _masked_stop_optic(TestMaskApertures._mask(np.inf, 2.0))
        scene = NSQScene()
        report = add_optic_surfaces(scene, optic)

        assert "S1.rim" not in scene.component_names
        assert any("S1: no clear edge, no rim" in note for note in report.notes)
        disk = scene.component_registry.get("S1.mask").component.geometry
        assert float(disk.aperture_radius) == pytest.approx(2.0)
        # A surface without any aperture keeps its estimated rim.
        open_scene = NSQScene()
        add_optic_surfaces(open_scene, _masked_stop_optic(None))
        assert "S1.rim" in open_scene.component_names

    def test_an_unbounded_surface_does_not_inflate_the_scene(self):
        """Its estimated radius must not reach into the scene's extent."""
        optic = _masked_stop_optic(TestMaskApertures._mask(np.inf, 2.0))
        scene = NSQScene()
        add_optic_surfaces(scene, optic)

        corners = [
            corner
            for surface in scene.surfaces
            for box in [surface.geometry.bounding_box(_get_transform(surface.cs))]
            for corner in (box.min_corner, box.max_corner)
        ]
        assert np.max(np.abs(np.asarray(corners)[:, :2])) <= 6.0

    def test_ring_aperture_without_outer_edge_keeps_its_obscuration(self):
        optic = _masked_stop_optic(RadialAperture(r_max=np.inf, r_min=1.5))
        scene = NSQScene()
        add_optic_surfaces(scene, optic)

        assert "S1.rim" not in scene.component_names
        disk = scene.component_registry.get("S1.obscuration").component.geometry
        assert float(disk.aperture_radius) == pytest.approx(1.5)

    def test_scene_draws_and_bounds_without_invalid_values(self):
        import matplotlib.pyplot as plt

        optic = _masked_stop_optic(TestMaskApertures._mask(np.inf, 2.0))
        scene = NSQScene()
        add_optic_surfaces(scene, optic)

        fig, ax = plt.subplots()
        try:
            with np.errstate(invalid="raise"):
                scene.view(ax=ax, projection="YZ")
        finally:
            plt.close(fig)
        for surface in scene.surfaces:
            box = surface.geometry.bounding_box(_get_transform(surface.cs))
            assert np.all(np.isfinite(box.min_corner))
            assert np.all(np.isfinite(box.max_corner))

    def test_mask_casts_its_shadow(self):
        irradiance, r = _irradiance_by_radius(
            _masked_stop_optic(TestMaskApertures._mask(np.inf, 2.0))
        )
        assert irradiance[r < 1.6].max() == 0.0
        assert irradiance[(r > 2.5) & (r < 4.5)].min() > 0.0


class TestObjectAndImage:
    def test_field_points_lie_on_the_curved_object(self):
        optic = _eye_and_lens_optic()
        points = object_field_points(optic)
        obj = optic.surfaces.surfaces[0]
        z0 = float(obj.geometry.cs.z)
        assert points[0] == pytest.approx((0.0, 0.0, z0))
        assert points[1][1] == pytest.approx(0.5)
        assert points[1][2] == pytest.approx(z0 + float(obj.geometry.sag(0.5, 0.0)))
        assert points[1][2] > z0

    def test_sources_are_aimed_at_the_entrance_pupil(self):
        optic = _eye_and_lens_optic()
        scene = NSQScene()
        names = add_field_point_sources(scene, optic, total_flux=0.5)
        assert names == ["object_0", "object_1"]
        off_axis = scene.source_registry.get("object_1")
        translation, rot = _get_transform(off_axis.cs)
        axis = rot @ np.array([0.0, 0.0, 1.0])
        assert axis[1] < 0.0 and axis[2] > 0.0  # tilted back towards the axis
        assert float(off_axis.total_flux) == pytest.approx(0.5)
        assert 0.0 < float(off_axis.half_angle_deg) < 89.0
        assert _f(off_axis.medium.n(0.55)) == pytest.approx(1.336)
        on_axis = scene.source_registry.get("object_0")
        assert float(on_axis.half_angle_deg) < float(off_axis.half_angle_deg)

    def test_fixed_half_angle_and_angle_fields_rejected(self):
        optic = _eye_and_lens_optic()
        scene = NSQScene()
        add_field_point_sources(scene, optic, half_angle_deg=12.0)
        assert float(scene.source_registry.get("object_1").half_angle_deg) == 12.0
        optic.set_field_type(field_type="angle")
        with pytest.raises(ConversionError, match="object-height"):
            add_field_point_sources(NSQScene(), optic)

    def test_image_detector_uses_the_rectangular_aperture(self):
        optic = _eye_and_lens_optic()
        scene = NSQScene()
        config = add_image_detector(scene, optic, "camera", num_pixels=(16, 8))
        assert (config.width, config.height) == (6.0, 4.0)
        assert (config.num_pixels_x, config.num_pixels_y) == (16, 8)
        detector = scene.detector_registry.get("camera")
        translation, _ = _get_transform(detector.cs)
        assert translation[2] == pytest.approx(float(optic.image_surface.geometry.cs.z))


class TestCollimatedFieldSources:
    def test_beams_have_the_pupil_diameter_and_pass_through_its_centre(self):
        from optiland.nonsequential.surface_conversion import (
            add_collimated_field_sources,
            entrance_pupil,
        )
        from optiland.samples.objectives import CookeTriplet

        optic = CookeTriplet()  # angle fields 0, 14 and 20 deg, object at infinity
        scene = NSQScene()
        names = add_collimated_field_sources(scene, optic, total_flux=2.0)
        assert names == ["field_0", "field_1", "field_2"]
        z_pupil, epd = entrance_pupil(optic)
        for name, field in zip(names, optic.fields.fields, strict=True):
            source = scene.source_registry.get(name)
            translation, rot = _get_transform(source.cs)
            axis = rot @ np.array([0.0, 0.0, 1.0])
            assert axis[1] / axis[2] == pytest.approx(
                math.tan(math.radians(float(field.y))), abs=1e-9
            )
            distance = (z_pupil - translation[2]) / axis[2]
            hit = translation + distance * axis
            assert hit[:2] == pytest.approx((0.0, 0.0), abs=1e-9)
            assert translation[2] < 0.0  # starts before the first surface
            assert _f(source.aperture_radius) == pytest.approx(abs(epd) / 2.0)
            assert _f(source.total_flux) == pytest.approx(2.0)

    def test_add_field_sources_dispatches_on_the_field_type(self):
        from optiland.nonsequential.surface_conversion import (
            add_collimated_field_sources,
            add_field_sources,
        )
        from optiland.samples.objectives import CookeTriplet

        eye = _eye_and_lens_optic()
        assert add_field_sources(NSQScene(), eye) == ["field_0", "field_1"]
        assert add_field_sources(NSQScene(), CookeTriplet(), prefix="beam") == [
            "beam_0",
            "beam_1",
            "beam_2",
        ]
        with pytest.raises(ConversionError, match="angle fields"):
            add_collimated_field_sources(NSQScene(), eye)
