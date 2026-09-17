"""Tests for the ZEMAX 2003 dialect of the Zemax writer.

ZEMAX-EE of January 2003 reads current OpticStudio output only partly. The
dialect writes the operands, order and token counts found in the sample files
shipped with that release. These tests pin that vocabulary and check that
Optiland reads the result back unchanged.
"""

from __future__ import annotations

import pytest

import optiland.backend as be
from optiland.fileio import load_zemax_file, save_zemax_file
from optiland.fileio.zemax.writer.exporter import ZemaxWriter
from optiland.materials import IdealMaterial
from optiland.optic import Optic
from optiland.physical_apertures import OffsetRadialAperture, RadialAperture
from tests.utils import assert_allclose

# Operands found in the sample files of ZEMAX-EE 2003 (VERS 30106).
_HEADER_OPERANDS_2003 = {
    "VERS", "MODE", "NAME", "NOTE", "UNIT", "ENPD", "FLOA", "OBNA", "PUPD",
    "GFAC", "GCAT", "RAIM", "PUSH", "SDMA", "FTYP", "ROPD", "PICB", "XFLD",
    "YFLD", "FWGT", "WAVL", "WWGT", "PWAV", "POLS", "GLRS", "GSTD", "NSCD",
    "COFN", "SURF", "BLNK", "TOL", "MNUM", "MOFF",
}  # fmt: skip
_SURFACE_OPERANDS_2003 = {
    "CLAP", "COAT", "COMM", "CONI", "CURV", "DIAM", "DISZ", "FLAP", "GLAS",
    "HIDE", "PARM", "POPS", "SLAB", "STOP", "TYPE",
}  # fmt: skip


def _singlet(
    fields=((0.0, 0.0), (0.0, 2.0)), wavelengths=(0.55, 0.65), name="Singlet"
) -> Optic:
    optic = Optic()
    optic.name = name
    optic.surfaces.add(index=0, thickness=20.0)
    optic.surfaces.add(
        index=1,
        radius=50.0,
        thickness=5.0,
        material="N-BK7",
        is_stop=True,
        aperture=RadialAperture(r_max=8.0),
    )
    optic.surfaces.add(
        index=2, radius=-50.0, thickness=45.0, material=IdealMaterial(1.406)
    )
    optic.surfaces.add(index=3, radius=-80.0, thickness=10.0)
    optic.surfaces.add(index=4)
    optic.set_aperture(aperture_type="float_by_stop_size", value=10.0)
    optic.fields.set_type(field_type="object_height")
    for x, y in fields:
        optic.fields.add(x=x, y=y)
    for i, wavelength in enumerate(wavelengths):
        optic.wavelengths.add(wavelength, is_primary=(i == 0))
    return optic


def _export(optic: Optic, tmp_path, name: str = "out.zmx"):
    path = tmp_path / name
    with pytest.warns(UserWarning, match="MODEL glass"):
        save_zemax_file(optic, str(path), dialect="zemax2003")
    return path


def _lines(path) -> list[str]:
    return path.read_bytes().decode("cp1252").splitlines()


def _surface(lines: list[str], index: int) -> dict[str, list[str]]:
    """The operands of block ``SURF index``, keyed by operand name."""
    block: dict[str, list[str]] = {}
    inside = False
    for line in lines:
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0] == "SURF":
            inside = int(tokens[1]) == index
        elif inside and line.startswith("  "):
            block[tokens[0]] = tokens[1:]
    return block


def _header(lines: list[str], operand: str) -> list[str]:
    for line in lines:
        tokens = line.split()
        if tokens and tokens[0] == operand:
            return tokens[1:]
    raise AssertionError(f"{operand} not found")


class TestZemax2003Header:
    def test_version_and_unit_lines(self, tmp_path):
        lines = _lines(_export(_singlet(), tmp_path))

        assert lines[0] == "VERS 30106 149"
        assert "UNIT MM NW NWC" in lines

    def test_only_operands_of_that_release(self, tmp_path):
        lines = _lines(_export(_singlet(), tmp_path))

        header = {line.split()[0] for line in lines if line and line[0] != " "}
        surface = {line.split()[0] for line in lines if line.startswith("  ")}
        assert header <= _HEADER_OPERANDS_2003, header - _HEADER_OPERANDS_2003
        assert surface <= _SURFACE_OPERANDS_2003, surface - _SURFACE_OPERANDS_2003

    def test_fields_and_wavelengths_are_value_lists(self, tmp_path):
        lines = _lines(_export(_singlet(), tmp_path))

        assert _header(lines, "FTYP") == ["1", "0"]
        assert [float(v) for v in _header(lines, "YFLD")] == [0.0, 2.0]
        assert [float(v) for v in _header(lines, "XFLD")] == [0.0, 0.0]
        assert [float(v) for v in _header(lines, "WAVL")] == [0.55, 0.65]
        assert [float(v) for v in _header(lines, "WWGT")] == [1.0, 1.0]
        assert _header(lines, "PWAV") == ["1"]

    def test_trailer(self, tmp_path):
        lines = _lines(_export(_singlet(), tmp_path))

        assert [line.split()[0] for line in lines[-4:]] == [
            "BLNK",
            "TOL",
            "MNUM",
            "MOFF",
        ]

    def test_windows_1252_with_crlf_line_ends(self, tmp_path):
        path = _export(_singlet(name="Mausauge Beleuchtung ü"), tmp_path)

        data = path.read_bytes()
        assert data.count(b"\n") == data.count(b"\r\n")
        assert b"NAME Mausauge Beleuchtung \xfc" in data


class TestZemax2003Surfaces:
    def test_floating_stop_semi_diameter_is_fixed(self, tmp_path):
        lines = _lines(_export(_singlet(), tmp_path))

        stop = _surface(lines, 1)
        assert "STOP" in stop
        assert float(stop["DIAM"][0]) == 5.0
        assert stop["DIAM"][1:] == ["1", "0"]

    def test_surface_aperture_has_minimum_and_maximum_only(self, tmp_path):
        lines = _lines(_export(_singlet(), tmp_path))

        assert [float(v) for v in _surface(lines, 1)["CLAP"]] == [0.0, 8.0]

    def test_constant_index_medium_is_a_blank_model_glass(self, tmp_path):
        lines = _lines(_export(_singlet(), tmp_path))

        glas = _surface(lines, 2)["GLAS"]
        assert glas[:3] == ["___BLANK", "1", "0"]
        assert float(glas[3]) == pytest.approx(1.406)
        assert float(glas[4]) == 0.0

    def test_schott_glass_declares_both_schott_catalogs(self, tmp_path):
        lines = _lines(_export(_singlet(), tmp_path))

        assert _header(lines, "GCAT") == ["SCHOTT", "SCHOTT_2000"]
        assert _surface(lines, 1)["GLAS"][:3] == ["N-BK7", "0", "0"]

    def test_coordinate_break_writes_every_parameter(self, tmp_path):
        optic = _singlet()
        optic.surfaces[3].geometry.cs.x = be.array(1.0)
        lines = _lines(_export(optic, tmp_path))

        breaks = [
            index
            for index in range(8)
            if _surface(lines, index).get("TYPE") == ["COORDBRK"]
        ]
        assert breaks
        parms = [
            line for line in lines if line.startswith("  PARM ")
        ]  # every PARM 1..6 of every break, zeros included
        assert len(parms) == 6 * len(breaks)


class TestZemax2003Limits:
    def test_more_than_twelve_fields_raises_before_writing(self, tmp_path):
        optic = _singlet(fields=[(0.0, 0.1 * i) for i in range(13)])
        path = tmp_path / "too_many.zmx"

        with (
            pytest.raises(ValueError, match="at most 12 fields"),
            pytest.warns(UserWarning, match="MODEL glass"),
        ):
            save_zemax_file(optic, str(path), dialect="zemax2003")
        assert not path.exists()

    def test_vignetting_factors_are_reported(self, tmp_path):
        optic = _singlet()
        optic.fields.fields[1].vy = 0.2

        with (
            pytest.warns(UserWarning, match="vignetting factors"),
            pytest.warns(UserWarning, match="MODEL glass"),
        ):
            save_zemax_file(optic, str(tmp_path / "v.zmx"), dialect="zemax2003")

    def test_decentred_aperture_is_reported_and_left_out(self, tmp_path):
        optic = _singlet()
        optic.surfaces[1].aperture = OffsetRadialAperture(r_max=8.0, offset_x=1.0)
        path = tmp_path / "d.zmx"

        with (
            pytest.warns(UserWarning, match="decentred surface aperture"),
            pytest.warns(UserWarning, match="MODEL glass"),
        ):
            save_zemax_file(optic, str(path), dialect="zemax2003")
        assert "CLAP" not in _surface(_lines(path), 1)

    def test_unknown_dialect_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown Zemax dialect"):
            save_zemax_file(_singlet(), str(tmp_path / "x.zmx"), dialect="zemax99")


class TestZemax2003RoundTrip:
    def test_singlet_reads_back_unchanged(self, tmp_path):
        original = _singlet()
        reloaded = load_zemax_file(str(_export(original, tmp_path)))

        assert reloaded.surfaces.num_surfaces == original.surfaces.num_surfaces
        for a, b in zip(
            original.surfaces.surfaces, reloaded.surfaces.surfaces, strict=True
        ):
            assert_allclose(a.geometry.cs.z, b.geometry.cs.z, atol=1e-12)
            assert_allclose(a.geometry.radius, b.geometry.radius, rtol=1e-12)
            assert_allclose(a.material_post.n(0.6), b.material_post.n(0.6), atol=1e-12)
        assert reloaded.aperture.ap_type == "float_by_stop_size"
        assert reloaded.aperture.value == pytest.approx(10.0)
        assert [float(f.y) for f in reloaded.fields] == [0.0, 2.0]
        assert [float(w.value) for w in reloaded.wavelengths] == [0.55, 0.65]

    def test_cooke_triplet_keeps_its_focal_length(self, tmp_path):
        from optiland.samples.objectives import CookeTriplet

        original = CookeTriplet()
        path = tmp_path / "cooke.zmx"
        save_zemax_file(original, str(path), dialect="zemax2003")
        reloaded = load_zemax_file(str(path))

        assert_allclose(original.paraxial.f2(), reloaded.paraxial.f2(), rtol=1e-9)
        assert [float(w.value) for w in reloaded.wavelengths] == pytest.approx(
            [float(w.value) for w in original.wavelengths]
        )

    def test_zemax_writer_passes_the_dialect_on(self, tmp_path):
        from optiland.samples.objectives import CookeTriplet

        path = tmp_path / "writer.zmx"
        ZemaxWriter(dialect="zemax2003").write(CookeTriplet(), str(path))

        assert _lines(path)[0] == "VERS 30106 149"
