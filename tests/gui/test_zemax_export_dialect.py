"""Tests for the GUI's Zemax export: dialect choice and dropped-data warnings."""

from __future__ import annotations

from unittest.mock import MagicMock


def _file_service(optic):
    from optiland_gui.services.file_service import FileService

    conn = MagicMock()
    conn.toast_manager = MagicMock()
    conn._undo_redo_manager = MagicMock()
    conn._optic = optic
    return FileService(conn), conn


class TestZemaxExportDialect:
    def test_export_writes_the_requested_dialect(self, tmp_path, qapp):
        from optiland.samples.objectives import CookeTriplet

        svc, conn = _file_service(CookeTriplet())
        out = tmp_path / "cooke.zmx"

        svc.export_zemax(str(out), dialect="zemax2003")

        assert out.read_bytes().startswith(b"VERS 30106 149")
        conn.toast_manager.notify.assert_not_called()

    def test_default_export_stays_opticstudio(self, tmp_path, qapp):
        from optiland.samples.objectives import CookeTriplet

        svc, _ = _file_service(CookeTriplet())
        out = tmp_path / "cooke.zmx"

        svc.export_zemax(str(out))

        assert out.read_text(encoding="utf-8").startswith("VERS 240000")

    def test_dropped_aperture_is_shown_as_warning_toast(self, tmp_path, qapp):
        """An aperture the file cannot carry used to vanish without a word."""
        from optiland.physical_apertures.elliptical import EllipticalAperture
        from optiland.samples.objectives import CookeTriplet

        optic = CookeTriplet()
        optic.surfaces[1].aperture = EllipticalAperture(a=5.0, b=3.0)
        svc, conn = _file_service(optic)

        svc.export_zemax(str(tmp_path / "cooke.zmx"))

        conn.toast_manager.notify.assert_called_once()
        call = conn.toast_manager.notify.call_args
        assert call[0][1] == "warning"
        assert "EllipticalAperture cannot be written" in str(call)
