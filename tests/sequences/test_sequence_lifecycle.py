"""Sequences follow their surfaces through base-optic edits.

A named sequence is resolved against surface *objects*; its raw step indices
are a serialization detail. Inserting or removing other surfaces keeps the
route intact and renumbers the steps on the next trace/serialization;
removing a surface the route passes through is an error, not a silently
different route.

Kramer Harrison, 2026
"""

from __future__ import annotations

import pytest

import optiland.backend as be
from optiland.materials.ideal import IdealMaterial
from optiland.optic import Optic
from optiland.sequences.resolver import SequenceValidationError
from optiland.sequences.sequenced_surface_group import SequenceStaleError

from ..utils import assert_allclose

GHOST = [0, 1, (2, "reflect"), (1, "reflect"), 2, 3]


def _build_optic() -> Optic:
    optic = Optic()
    optic.surfaces.add(index=0, thickness=100)
    optic.surfaces.add(
        index=1, thickness=10, material=IdealMaterial(n=1.5), is_stop=True
    )
    optic.surfaces.add(index=2, thickness=50)
    optic.surfaces.add(index=3)
    optic.fields.set_type("angle")
    optic.fields.add(y=0)
    optic.set_aperture("EPD", 10.0)
    optic.wavelengths.add(0.55, is_primary=True)
    return optic


def _trace(seq):
    return seq.trace(Hx=0, Hy=0, wavelength=0.55, num_rays=6, distribution="line_y")


class TestUneditedSequence:
    def test_is_not_stale_and_refresh_keeps_views(self, set_test_backend):
        optic = _build_optic()
        seq = optic.add_sequence("ghost", GHOST)
        views_before = seq.surfaces.surfaces

        assert seq.is_stale is False
        seq.refresh()
        optic.refresh_sequences()

        assert seq.surfaces.surfaces == views_before
        assert seq.raw_steps == GHOST


class TestInsertedSurface:
    def test_insert_before_the_route_renumbers_the_steps(self, set_test_backend):
        optic = _build_optic()
        seq = optic.add_sequence("ghost", GHOST)
        route_surfaces = [view.base_surface for view in seq.surfaces]

        # A plane air/air surface in front of the lens: every route index
        # shifts by one, the route itself does not change.
        optic.surfaces.add(index=1, thickness=5.0)

        assert seq.is_stale is True
        assert seq.raw_steps == [0, 2, (3, "reflect"), (2, "reflect"), 3, 4]
        assert seq.is_stale is False
        assert [view.base_surface for view in seq.surfaces] == route_surfaces

    def test_trace_after_insert_matches_a_fresh_definition(self, set_test_backend):
        optic = _build_optic()
        seq = optic.add_sequence("ghost", GHOST)
        optic.surfaces.add(index=1, thickness=5.0)

        traced = _trace(seq)
        fresh = optic.add_sequence(
            "fresh", [0, 2, (3, "reflect"), (2, "reflect"), 3, 4]
        )
        expected = _trace(fresh)

        assert_allclose(traced.y, expected.y)
        assert_allclose(traced.z, expected.z)
        assert_allclose(traced.opd, expected.opd)

    def test_serialization_writes_the_renumbered_steps(self, set_test_backend):
        optic = _build_optic()
        optic.add_sequence("ghost", GHOST)
        optic.surfaces.add(index=1, thickness=5.0)

        data = optic.to_dict()
        assert data["sequences"]["ghost"] == [
            0,
            2,
            (3, "reflect"),
            (2, "reflect"),
            3,
            4,
        ]
        restored = Optic.from_dict(data)
        assert len(restored.sequences["ghost"].surfaces) == 6
        # The restored route passes through the glass surface, not the
        # inserted air plate.
        n_glass = restored.sequences["ghost"].surfaces[1].material_post.n(0.55)
        assert float(be.to_numpy(n_glass)) == pytest.approx(1.5)

    def test_insert_that_breaks_the_medium_chain_raises(self, set_test_backend):
        optic = _build_optic()
        seq = optic.add_sequence("fwd", [0, 1, 2, 3])
        # A second glass surface between the two faces: the old step 1 -> 2
        # join now exits into n=1.5 glass but the next route surface is
        # entered from n=1.7 glass.
        optic.surfaces.add(index=2, thickness=3.0, material=IdealMaterial(n=1.7))

        with pytest.raises(SequenceValidationError):
            seq.refresh()
        with pytest.raises(SequenceValidationError):
            _trace(seq)


class TestRemovedSurface:
    def test_removing_a_route_surface_raises_on_trace(self, set_test_backend):
        optic = _build_optic()
        seq = optic.add_sequence("ghost", GHOST)
        optic.surfaces.remove(2)

        assert seq.is_stale is True
        with pytest.raises(SequenceStaleError, match="removed from the optic"):
            _trace(seq)
        with pytest.raises(SequenceStaleError):
            optic.refresh_sequences()
        # The sequence stays registered for inspection.
        assert "ghost" in optic.sequences

    def test_removing_an_unrelated_surface_keeps_the_route(self, set_test_backend):
        optic = _build_optic()
        optic.surfaces.add(index=3, thickness=2.0)  # air plate before the image
        seq = optic.add_sequence("fwd", [0, 1, 2, 4])
        route_surfaces = [view.base_surface for view in seq.surfaces]

        optic.surfaces.remove(3)

        assert seq.raw_steps == [0, 1, 2, 3]
        assert [view.base_surface for view in seq.surfaces] == route_surfaces
        rays = _trace(seq)
        assert be.size(rays.x) == 6


class TestReplacedSurface:
    def test_replaced_surface_object_is_picked_up_by_index(self, set_test_backend):
        """The GUI replaces a Surface object in place when its type changes;
        the route follows the index because the old object is gone."""
        optic = _build_optic()
        seq = optic.add_sequence("fwd", [0, 1, 2, 3])
        old_surface = optic.surfaces.surfaces[2]

        optic.surfaces.remove(2)
        optic.surfaces.add(index=2, thickness=50.0)

        assert seq.is_stale is True
        with pytest.raises(SequenceStaleError):
            seq.refresh()
        assert optic.surfaces.surfaces[2] is not old_surface
