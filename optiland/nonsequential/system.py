"""A multi-axis optical system: a folded scene plus its named optical paths.

A :class:`~optiland.nonsequential.scene.NSQScene` knows surfaces, sources
and detectors, but not that a fundus camera is made of an *observation*
path and an *illumination* path, each a sequential design in its own
right. :class:`MultiAxisSystem` keeps both views together:

- ``scene``: the non-sequential scene that is traced and drawn;
- ``paths``: the named sequential optics the scene was folded from, with
  the scene components each path traverses, so a path can be activated in
  the sequential tools (lens data editor, 2D layout, analyses) and a click
  on a component can select its path;
- ``fold``: the parameters of the fold, so the scene can be rebuilt after
  a path was edited.

The file format (``.olsys``) is the scene JSON of
:func:`~optiland.nonsequential.serialization.scene_to_dict` plus the
top-level keys ``"paths"`` and ``"fold"``, and three version keys:
``"olsys_format_version"`` (see :data:`OLSYS_FORMAT_VERSION`),
``"application"`` (name and version of the program that last saved the
file) and ``"optiland_version"`` (the library). ``NSQScene.from_json``
ignores the extra keys, so a system file is also a plain scene file.

A system without fold settings is converted path by path instead: every
path becomes its own unfolded copy in the scene (surfaces with rim
baffles, one source per field, an image detector). That is what a plain
sequential design opened in the GUI turns into.

Kramer Harrison, 2026
"""

from __future__ import annotations

import importlib.metadata
import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from optiland.nonsequential.fold import (
    CAMERA,
    DUMP,
    ILLUMINATION,
    MIRROR,
    SAMPLE,
    FoldReport,
    fold_paths,
)
from optiland.nonsequential.serialization import scene_from_dict, scene_to_dict
from optiland.nonsequential.surface_conversion import (
    add_field_sources,
    add_image_detector,
    add_optic_surfaces,
    glass_surfaces_lossless,
)

if TYPE_CHECKING:
    import os

    from optiland.nonsequential.scene import NSQScene
    from optiland.optic import Optic

#: Version of the ``.olsys`` file format written by :meth:`MultiAxisSystem.to_dict`.
#:
#: Rule: increment it as soon as a file written by this code can no longer
#: be opened by an older Optiland application, and release that change
#: under a new Optiland (GUI) version. Additions that older readers ignore
#: (new optional keys) keep the number. Readers refuse files with a higher
#: number than they know.
OLSYS_FORMAT_VERSION = 1

#: Name used in the ``"application"`` key when no application is given.
LIBRARY_APPLICATION = "optiland"

#: Lossless-coating policies by name (what the CLI and the file store).
LOSSLESS_POLICIES: dict[str, object] = {
    "glass": glass_surfaces_lossless,
    "all": True,
    "none": False,
}


def optiland_version() -> str:
    """The installed optiland library version (``"unknown"`` outside a package)."""
    try:
        return importlib.metadata.version("optiland")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


@dataclass
class OpticalPath:
    """One sequential optical path of a multi-axis system.

    Attributes:
        name: User-facing name (unique within the system).
        optic: The sequential design as ``Optic.to_dict()`` data, in its
            own unfolded frame.
        role: ``"imaging"`` or ``"illumination"`` for a folded system,
            ``""`` otherwise.
        components: Registry names of the scene components this path
            traverses (used for highlighting and click selection).
        sources: Registry names of the scene sources that belong to it.
        detectors: Registry names of the scene detectors that belong to it.
    """

    name: str
    optic: dict[str, Any]
    role: str = ""
    components: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    detectors: list[str] = field(default_factory=list)

    def build_optic(self) -> Optic:
        """Instantiate the sequential optic of this path."""
        from optiland.optic import Optic  # noqa: PLC0415

        return Optic.from_dict(self.optic)


@dataclass
class FoldSettings:
    """Parameters that rebuild the scene from two paths (see ``fold_paths``).

    Attributes:
        imaging: Name of the imaging path.
        illumination: Name of the illumination path.
        fold_imaging: Fold (hole) surface index in the imaging optic.
        fold_illumination: Fold (ring) surface index in the illumination
            optic.
        angle_deg, hole, tail_from, mirror_reflectance, lossless,
        illumination_flux, object_flux, illumination_half_angle_deg,
        object_half_angle_deg, sample_size, camera_pixels, sample_pixels,
        dump_distance: As in :func:`~optiland.nonsequential.fold.fold_paths`;
            ``lossless`` is a policy name of :data:`LOSSLESS_POLICIES`.
    """

    imaging: str
    illumination: str
    fold_imaging: int
    fold_illumination: int
    angle_deg: float = 45.0
    hole: str = "projected"
    tail_from: str = "imaging"
    mirror_reflectance: float = 1.0
    lossless: str = "glass"
    illumination_flux: float = 1.0
    object_flux: float = 1.0
    illumination_half_angle_deg: float | None = None
    object_half_angle_deg: float | None = None
    sample_size: float | None = None
    camera_pixels: tuple[int, int] = (256, 256)
    sample_pixels: tuple[int, int] = (128, 128)
    dump_distance: float = 30.0

    def fold_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for :func:`~optiland.nonsequential.fold.fold_paths`."""
        if self.lossless not in LOSSLESS_POLICIES:
            raise ValueError(
                f"Unknown lossless policy {self.lossless!r}; expected one of "
                f"{sorted(LOSSLESS_POLICIES)}."
            )
        return {
            "angle_deg": self.angle_deg,
            "hole": self.hole,
            "tail_from": self.tail_from,
            "mirror_reflectance": self.mirror_reflectance,
            "lossless": LOSSLESS_POLICIES[self.lossless],
            "illumination_flux": self.illumination_flux,
            "object_flux": self.object_flux,
            "illumination_half_angle_deg": self.illumination_half_angle_deg,
            "object_half_angle_deg": self.object_half_angle_deg,
            "sample_size": self.sample_size,
            "camera_pixels": tuple(self.camera_pixels),
            "sample_pixels": tuple(self.sample_pixels),
            "dump_distance": self.dump_distance,
        }


class MultiAxisSystem:
    """A scene together with the named sequential paths it is made of.

    Args:
        scene: The non-sequential scene.
        paths: The optical paths (may be empty for a hand-built scene).
        fold: Fold parameters when the scene was folded from two paths.

    Attributes:
        application: ``{"name": ..., "version": ...}`` of the program that
            last saved the file this system was read from (``None`` for a
            system that was never saved).
    """

    def __init__(
        self,
        scene: NSQScene,
        paths: list[OpticalPath] | None = None,
        fold: FoldSettings | None = None,
    ) -> None:
        self.scene = scene
        self.paths: list[OpticalPath] = list(paths or [])
        self.fold = fold
        self.last_report: FoldReport | None = None
        self.application: dict[str, str] | None = None
        names = [p.name for p in self.paths]
        if len(set(names)) != len(names):
            raise ValueError(f"Path names must be unique, got {names}.")

    @classmethod
    def from_optic(
        cls,
        optic: Optic | dict[str, Any],
        name: str | None = None,
        *,
        rebuild: bool = True,
    ) -> MultiAxisSystem:
        """A system with a single, unfolded path holding ``optic``.

        Args:
            optic: The sequential design (an ``Optic`` or its ``to_dict()``
                data).
            name: Path name; defaults to the optic's name or ``"Path 1"``.
            rebuild: Convert the path into the scene right away.

        Returns:
            The new system (its scene is empty when ``rebuild`` is false).
        """
        from optiland.nonsequential.scene import NSQScene  # noqa: PLC0415

        if isinstance(optic, dict):
            data = optic
            fallback = str(data.get("name") or "").strip() or "Path 1"
        else:
            data = optic.to_dict()
            fallback = _default_name(optic, "Path 1")
        system = cls(NSQScene(), [OpticalPath(name=name or fallback, optic=data)])
        if rebuild:
            system.rebuild()
        return system

    # -- paths -------------------------------------------------------------

    @property
    def path_names(self) -> list[str]:
        """Names of the paths, in order."""
        return [p.name for p in self.paths]

    def path(self, name: str) -> OpticalPath:
        """The path called ``name``.

        Raises:
            KeyError: If there is no such path.
        """
        for p in self.paths:
            if p.name == name:
                return p
        raise KeyError(f"No optical path named {name!r}; have {self.path_names}.")

    def rename_path(self, old: str, new: str) -> None:
        """Rename a path, keeping the fold settings consistent.

        Raises:
            KeyError: If ``old`` does not exist.
            ValueError: If ``new`` is empty or already taken.
        """
        new = new.strip()
        if not new:
            raise ValueError("A path name must not be empty.")
        if new != old and new in self.path_names:
            raise ValueError(f"A path named {new!r} already exists.")
        p = self.path(old)
        p.name = new
        if self.fold is not None:
            if self.fold.imaging == old:
                self.fold.imaging = new
            if self.fold.illumination == old:
                self.fold.illumination = new

    def set_path_optic(self, name: str, optic: Optic | dict[str, Any]) -> None:
        """Replace the sequential design of a path (no rebuild yet).

        Args:
            name: Path name.
            optic: An ``Optic`` or its ``to_dict()`` data.
        """
        data = optic if isinstance(optic, dict) else optic.to_dict()
        self.path(name).optic = data

    def paths_for_component(self, component_name: str) -> list[str]:
        """Names of the paths that traverse a scene component (or source)."""
        return [
            p.name
            for p in self.paths
            if component_name in p.components
            or component_name in p.sources
            or component_name in p.detectors
        ]

    # -- rebuild -------------------------------------------------------------

    def rebuild(self) -> FoldReport:
        """Build the scene again from the current path optics.

        With fold settings the two paths are folded
        (:func:`~optiland.nonsequential.fold.fold_paths`); without, every
        path is converted in place, each in its own frame: surfaces with
        rim baffles, one source per field and an image detector. A single
        path keeps plain registry names (``S1``, ``field_0``, ``image``);
        several unfolded paths get ``"<path name>."`` as prefix.

        Returns:
            The report of the rebuilt scene.

        Raises:
            RuntimeError: If the system has no paths.
            ConversionError: If a path cannot be converted (the scene is
                then left as it was).
        """
        if self.fold is None:
            return self._rebuild_unfolded()
        imaging = self.path(self.fold.imaging).build_optic()
        illumination = self.path(self.fold.illumination).build_optic()
        scene, report = fold_paths(
            imaging,
            illumination,
            self.fold.fold_imaging,
            self.fold.fold_illumination,
            **self.fold.fold_kwargs(),
        )
        _assign_fold_members(self.path(self.fold.imaging), report, "imaging")
        _assign_fold_members(self.path(self.fold.illumination), report, "illumination")
        self.scene = scene
        self.last_report = report
        return report

    def _rebuild_unfolded(self) -> FoldReport:
        if not self.paths:
            raise RuntimeError("This system has no optical paths; nothing to rebuild.")
        from optiland.nonsequential.scene import NSQScene  # noqa: PLC0415

        scene = NSQScene()
        report = FoldReport.unfolded()
        single = len(self.paths) == 1
        members: list[tuple[OpticalPath, list[str], list[str], list[str]]] = []
        for p in self.paths:
            prefix = "" if single else f"{p.name}."
            optic = p.build_optic()
            arm = add_optic_surfaces(
                scene, optic, prefix=prefix, lossless=glass_surfaces_lossless
            )
            sources = add_field_sources(scene, optic, prefix=f"{prefix}field")
            detector = f"{prefix}image"
            add_image_detector(scene, optic, detector)
            report.arms[p.name] = arm
            report.sources.extend(sources)
            report.detectors.append(detector)
            members.append((p, arm.components + arm.baffles, sources, [detector]))
        # Only a complete conversion replaces the scene and the memberships.
        for p, components, sources, detectors in members:
            p.components = components
            p.sources = sources
            p.detectors = detectors
            p.role = ""
        self.scene = scene
        self.last_report = report
        return report

    # -- serialization ---------------------------------------------------------

    def to_dict(self, *, application: tuple[str, str] | None = None) -> dict[str, Any]:
        """Scene JSON data plus versions, ``"paths"`` and ``"fold"``.

        Args:
            application: ``(name, version)`` of the program saving the file;
                defaults to the optiland library and its version.
        """
        name, version = application or (LIBRARY_APPLICATION, optiland_version())
        data: dict[str, Any] = {
            "olsys_format_version": OLSYS_FORMAT_VERSION,
            "application": {"name": str(name), "version": str(version)},
            "optiland_version": optiland_version(),
        }
        data.update(scene_to_dict(self.scene))
        data["paths"] = [asdict(p) for p in self.paths]
        data["fold"] = None if self.fold is None else _fold_to_dict(self.fold)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MultiAxisSystem:
        """Inverse of :meth:`to_dict`; a plain scene dict gives no paths.

        Raises:
            ValueError: If the file's ``"olsys_format_version"`` is newer
                than :data:`OLSYS_FORMAT_VERSION` (or not a positive
                integer). Files from before the key existed count as
                version 1.
        """
        _check_format_version(data)
        scene = scene_from_dict(data)
        paths = [OpticalPath(**p) for p in data.get("paths", []) or []]
        fold_d = data.get("fold")
        fold = _fold_from_dict(fold_d) if fold_d else None
        system = cls(scene, paths, fold)
        application = data.get("application")
        if isinstance(application, dict):
            system.application = {
                "name": str(application.get("name", "")),
                "version": str(application.get("version", "")),
            }
        return system

    def to_json(
        self,
        path: str | os.PathLike,
        *,
        application: tuple[str, str] | None = None,
    ) -> None:
        """Write the system file (``.olsys``).

        Args:
            path: Destination.
            application: ``(name, version)`` of the saving program (see
                :meth:`to_dict`).
        """
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(application=application), f, indent=2)

    @classmethod
    def from_json(cls, path: str | os.PathLike) -> MultiAxisSystem:
        """Read a system file, or a plain scene file (then without paths)."""
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


def _check_format_version(data: dict[str, Any]) -> None:
    version = data.get("olsys_format_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError(
            f"Invalid olsys_format_version {version!r}; expected a positive integer."
        )
    if version > OLSYS_FORMAT_VERSION:
        application = data.get("application") or {}
        written_by = ""
        if isinstance(application, dict) and application.get("name"):
            label = " ".join(
                str(application.get(key, "")) for key in ("name", "version")
            ).strip()
            written_by = f" (written by {label})"
        raise ValueError(
            f"This file uses .olsys format version {version}{written_by}; this "
            f"Optiland reads versions up to {OLSYS_FORMAT_VERSION}. Update "
            "Optiland to open it."
        )


def _fold_to_dict(fold: FoldSettings) -> dict[str, Any]:
    d = asdict(fold)
    d["camera_pixels"] = list(fold.camera_pixels)
    d["sample_pixels"] = list(fold.sample_pixels)
    return d


def _fold_from_dict(d: dict[str, Any]) -> FoldSettings:
    d = dict(d)
    d["camera_pixels"] = tuple(d.get("camera_pixels", (256, 256)))
    d["sample_pixels"] = tuple(d.get("sample_pixels", (128, 128)))
    return FoldSettings(**d)


def _assign_fold_members(path: OpticalPath, report: FoldReport, role: str) -> None:
    """Fill a path's scene membership from a fold report."""
    tail = report.tail.components + report.tail.baffles
    if role == "imaging":
        arm = report.imaging_arm.components + report.imaging_arm.baffles
        path.components = tail + arm + [MIRROR]
        path.sources = [s for s in report.sources if s != ILLUMINATION]
        path.detectors = [CAMERA]
    else:
        arm = report.illumination_arm.components + report.illumination_arm.baffles
        path.components = arm + [MIRROR] + tail
        path.sources = [ILLUMINATION]
        path.detectors = [SAMPLE, DUMP]
    path.role = role


def _default_name(optic: Optic, fallback: str) -> str:
    name = (getattr(optic, "name", "") or "").strip()
    return name or fallback


def fold_system(
    imaging: Optic,
    illumination: Optic,
    fold_imaging: int,
    fold_illumination: int,
    *,
    imaging_name: str | None = None,
    illumination_name: str | None = None,
    **fold_kwargs: Any,
) -> tuple[MultiAxisSystem, FoldReport]:
    """Fold two sequential optics into a :class:`MultiAxisSystem`.

    Args:
        imaging: Imaging optic (sample -> camera).
        illumination: Illumination optic (source -> sample).
        fold_imaging: Fold (hole) surface index in ``imaging``.
        fold_illumination: Fold (ring) surface index in ``illumination``.
        imaging_name: Path name; defaults to the optic's own name or
            ``"Imaging"``.
        illumination_name: Path name; defaults to the optic's own name or
            ``"Illumination"``.
        **fold_kwargs: Fields of :class:`FoldSettings` other than the names
            and indices (``lossless`` as a policy name).

    Returns:
        ``(system, report)``.
    """
    imaging_name = imaging_name or _default_name(imaging, "Imaging")
    illumination_name = illumination_name or _default_name(illumination, "Illumination")
    if imaging_name == illumination_name:
        illumination_name = f"{illumination_name} (illumination)"
    fold = FoldSettings(
        imaging=imaging_name,
        illumination=illumination_name,
        fold_imaging=fold_imaging,
        fold_illumination=fold_illumination,
        **fold_kwargs,
    )
    paths = [
        OpticalPath(name=imaging_name, optic=imaging.to_dict(), role="imaging"),
        OpticalPath(
            name=illumination_name, optic=illumination.to_dict(), role="illumination"
        ),
    ]
    from optiland.nonsequential.scene import NSQScene  # noqa: PLC0415

    system = MultiAxisSystem(NSQScene(), paths, fold)
    report = system.rebuild()
    return system, report
