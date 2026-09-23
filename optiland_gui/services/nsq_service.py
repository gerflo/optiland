"""System document service for the Optiland GUI.

The sequential ``OptilandConnector`` and its undo snapshots work on one
``Optic``. The GUI's *document* is a
:class:`~optiland.nonsequential.system.MultiAxisSystem`: a non-sequential
scene plus the named sequential optical paths it is built from. Exactly
one of those paths can be *active*: its design is loaded into the
connector, so the lens data editor, the 2D layout and every sequential
analysis work on it, and edits flow back into the system.

:class:`NSQService` owns that document: it starts one from a plain
sequential design (a ``.json`` opened in the GUI becomes path 1), loads
and saves ``.olsys`` files, tracks whether the document has unsaved
changes, and runs Monte Carlo traces on a worker thread so a long run never
blocks the UI.

Author: Optiland contributors, 2026
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QThread, Signal

from optiland_gui.services.file_service import SpecialFloatEncoder
from optiland_gui.worker import _Worker

if TYPE_CHECKING:
    from optiland.nonsequential.scene import NSQScene
    from optiland.nonsequential.system import MultiAxisSystem, OpticalPath
    from optiland.nonsequential.tracer import SimulationResult
    from optiland.optic import Optic

logger = logging.getLogger(__name__)

#: Extension of the document file.
DOCUMENT_EXTENSION = ".olsys"
#: Name shown for a document that was never saved and has no source file.
UNTITLED_DOCUMENT = "Untitled" + DOCUMENT_EXTENSION
#: Optic names that do not deserve to name a path.
_PLACEHOLDER_OPTIC_NAMES = {"", "new untitled system", "default system", "optic"}


def _fingerprint(data: dict[str, Any]) -> str:
    """A comparable rendering of a design dict (arrays and NaN included)."""
    return json.dumps(data, sort_keys=True, cls=SpecialFloatEncoder)


def default_path_name(optic_name: str | None, source_path: str | None) -> str:
    """The name a new single path gets.

    The stem of the file the design came from wins; otherwise the optic's
    own name, unless it is a placeholder; otherwise ``"Path 1"``.
    """
    if source_path:
        stem = os.path.splitext(os.path.basename(str(source_path)))[0].strip()
        if stem:
            return stem
    name = (optic_name or "").strip()
    if name.lower() not in _PLACEHOLDER_OPTIC_NAMES:
        return name
    return "Path 1"


class NSQService(QObject):
    """Owns the current system document and its latest trace result.

    Signals:
        sceneChanged: The scene was replaced or rebuilt (sample built, file
            loaded or saved, path edited).
        pathsChanged: The list of path names changed.
        activePathChanged (object): Another path (or ``None``) became the
            one loaded into the sequential tools.
        traceStarted: A background trace began.
        traceFinished (object): A trace completed; carries the
            :class:`~optiland.nonsequential.tracer.SimulationResult`.
        traceFailed (str): A trace raised; carries the error message.
        sceneOutdated (str): A loaded file's scene could not be built again
            from its paths; carries the reason. The stored scene is shown.
    """

    sceneChanged = Signal()
    pathsChanged = Signal()
    activePathChanged = Signal(object)
    traceStarted = Signal()
    traceFinished = Signal(object)
    traceFailed = Signal(str)
    sceneOutdated = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._system: MultiAxisSystem | None = None
        self._scene: NSQScene | None = None
        self._scene_path: str | None = None
        self._scene_label: str = ""
        self._suggested_stem: str | None = None
        self._dirty = False
        self._result: SimulationResult | None = None
        self._active_path: str | None = None
        self._activating = False
        self._scene_outdated: str | None = None
        self._thread: QThread | None = None
        self._worker: _Worker | None = None

    # ------------------------------------------------------------------
    # Document state
    # ------------------------------------------------------------------

    @property
    def scene(self) -> NSQScene | None:
        """The current scene, or ``None`` before anything was loaded."""
        return self._scene

    @property
    def result(self) -> SimulationResult | None:
        """The latest trace result for the current scene, if any."""
        return self._result

    @property
    def scene_path(self) -> str | None:
        """File the document was loaded from or saved to (``.olsys``), if any."""
        return self._scene_path

    @property
    def scene_label(self) -> str:
        """Human-readable label of the current scene."""
        return self._scene_label

    @property
    def document_name(self) -> str:
        """File name the document has, or would get when saved.

        The saved file's name; else the stem of the design file the
        document was started from plus ``.olsys``; else ``Untitled.olsys``.
        """
        if self._scene_path:
            return os.path.basename(self._scene_path)
        if self._suggested_stem:
            return self._suggested_stem + DOCUMENT_EXTENSION
        return UNTITLED_DOCUMENT

    @property
    def is_dirty(self) -> bool:
        """Whether the system changed since it was loaded or saved.

        Edits of the active path are tracked by the connector, not here;
        this flag covers what only the system knows: renamed paths, a path
        filled from a file, a rebuilt scene.
        """
        return self._dirty

    def mark_clean(self) -> None:
        """Forget system-level changes (after saving elsewhere)."""
        self._dirty = False

    @property
    def scene_outdated(self) -> str | None:
        """Why the shown scene is the stored one, or ``None`` when it fits.

        A loaded file's scene is built again from its paths
        (:meth:`load_file`); when that fails, the stored scene stays on
        screen although it may not belong to the saved design, and this is
        the error that stopped the rebuild.
        """
        return self._scene_outdated

    @property
    def is_tracing(self) -> bool:
        """Whether a background trace is running."""
        return self._thread is not None

    @property
    def system(self) -> MultiAxisSystem | None:
        """The multi-axis system that owns the scene (``None`` if none)."""
        return self._system

    @property
    def path_names(self) -> list[str]:
        """Names of the system's optical paths, in order."""
        return [] if self._system is None else self._system.path_names

    @property
    def active_path(self) -> str | None:
        """Name of the path loaded into the sequential tools, if any."""
        return self._active_path

    @property
    def is_activating(self) -> bool:
        """True while a path is being handed to the connector."""
        return self._activating

    def set_scene(self, scene: NSQScene, label: str, path: str | None = None) -> None:
        """Replace the current scene (as a system without paths).

        Args:
            scene: The new scene.
            label: Label shown in the panel.
            path: File the scene belongs to, if any.
        """
        from optiland.nonsequential.system import MultiAxisSystem  # noqa: PLC0415

        self.set_system(MultiAxisSystem(scene), label, path)

    def set_system(
        self, system: MultiAxisSystem, label: str, path: str | None = None
    ) -> None:
        """Replace the current system and drop the previous result.

        Args:
            system: The new multi-axis system.
            label: Label shown in the panel.
            path: File the system belongs to, if any.
        """
        self._system = system
        self._scene = system.scene
        self._scene_label = label
        self._scene_path = path
        self._suggested_stem = None
        self._dirty = False
        self._result = None
        self._active_path = None
        self._scene_outdated = None
        self.pathsChanged.emit()
        self.activePathChanged.emit(None)
        self.sceneChanged.emit()

    def adopt_optic(
        self,
        optic: Optic | dict[str, Any],
        name: str,
        *,
        source: str | None = None,
    ) -> str | None:
        """Start a new document: a single path holding ``optic``, active.

        The connector already holds this design (it was just created,
        opened or imported there), so it is not loaded again.

        Args:
            optic: The design, as an ``Optic`` or its state dict.
            name: Name of the single path.
            source: File the design came from (names the document until it
                is saved); ``None`` for a new or sample design.

        Returns:
            ``None`` when the path was converted into the scene, else the
            conversion error (the document still exists, with an empty
            scene).
        """
        from optiland.nonsequential.system import MultiAxisSystem  # noqa: PLC0415

        system = MultiAxisSystem.from_optic(optic, name, rebuild=False)
        error: str | None = None
        try:
            system.rebuild()
        except Exception as exc:  # noqa: BLE001 -- the document must still open
            logger.warning("Path %r not converted for the System view: %s", name, exc)
            error = str(exc)
        self._system = system
        self._scene = system.scene
        self._scene_label = name
        self._scene_path = None
        self._suggested_stem = (
            os.path.splitext(os.path.basename(source))[0] if source else None
        )
        self._dirty = False
        self._result = None
        self._active_path = name
        self.pathsChanged.emit()
        self.activePathChanged.emit(name)
        self.sceneChanged.emit()
        return error

    # ------------------------------------------------------------------
    # Optical paths
    # ------------------------------------------------------------------

    def path(self, name: str) -> OpticalPath:
        """The optical path called ``name``.

        Raises:
            RuntimeError: If no system is loaded.
            KeyError: If there is no such path.
        """
        if self._system is None:
            raise RuntimeError("No system loaded.")
        return self._system.path(name)

    def activate_path(self, name: str | None, connector) -> None:
        """Load a path's sequential design into the connector.

        The lens data editor, the 2D layout and every sequential analysis
        then work on that path; edits flow back through
        :meth:`sync_active_path`. ``None`` deactivates without touching the
        connector.

        Args:
            name: Path name, or ``None``.
            connector: The GUI connector (``load_optic_from_object``).
        """
        if name is None:
            if self._active_path is not None:
                self._active_path = None
                self.activePathChanged.emit(None)
            return
        path = self.path(name)
        optic = path.build_optic()
        self._activating = True
        try:
            connector.load_optic_from_object(optic)
            restore = getattr(connector, "restore_gui_state", None)
            if restore is not None:
                restore(path.optic)
            # The loaded design is a copy of the saved path: nothing to save
            # yet, so closing the window must not ask about it.
            mark_clean = getattr(connector, "mark_current_state_clean", None)
            if mark_clean is not None:
                mark_clean()
        finally:
            self._activating = False
        self._active_path = name
        self.activePathChanged.emit(name)

    def rename_path(self, old: str, new: str) -> None:
        """Rename a path (the active one stays active under its new name)."""
        if self._system is None:
            raise RuntimeError("No system loaded.")
        self._system.rename_path(old, new)
        if self._active_path == old:
            self._active_path = new.strip()
        self._dirty = True
        self.pathsChanged.emit()
        self.activePathChanged.emit(self._active_path)

    def sync_active_path(self, optic: Optic | dict[str, Any]) -> None:
        """Store the edited design of the active path and rebuild the scene.

        The edited design is kept in the path even when the scene cannot be
        rebuilt from it, so saving never loses an edit; the previous scene
        stays on screen in that case.

        Args:
            optic: The connector's current optic, or its state dict.

        Raises:
            RuntimeError: If no path is active.
            Exception: Whatever the rebuild raises for an inconsistent
                edit.
        """
        if self._system is None or self._active_path is None:
            raise RuntimeError("No active optical path.")
        data = optic if isinstance(optic, dict) else optic.to_dict()
        path = self._system.path(self._active_path)
        if _fingerprint(data) == _fingerprint(path.optic):
            # A refresh signal without an edit (panels re-emitting
            # opticChanged at start-up): nothing changed, nothing to rebuild.
            return
        self._system.set_path_optic(self._active_path, data)
        self._dirty = True
        self._system.rebuild()
        self._scene = self._system.scene
        self._result = None
        self.sceneChanged.emit()

    def fill_path(self, name: str, optic: Optic | dict[str, Any], connector) -> None:
        """Replace the design of path ``name`` from a file and activate it.

        Args:
            name: Path to fill.
            optic: The new design (``Optic`` or state dict).
            connector: The GUI connector the path is activated in.

        Raises:
            Exception: If the system cannot be rebuilt with the new design;
                the path then keeps its previous design.
        """
        if self._system is None:
            raise RuntimeError("No system loaded.")
        previous = self.path(name).optic
        self._system.set_path_optic(name, optic)
        try:
            self._system.rebuild()
        except Exception:
            self._system.set_path_optic(name, previous)
            raise
        self._scene = self._system.scene
        self._result = None
        self._dirty = True
        self.activate_path(name, connector)
        self.sceneChanged.emit()

    def paths_for_component(self, component_name: str) -> list[str]:
        """Names of the paths a scene component, source or detector belongs to."""
        if self._system is None:
            return []
        return self._system.paths_for_component(component_name)

    def load_sample(self, key: str) -> None:
        """Build one of the bundled sample scenes.

        Args:
            key: A key of :data:`optiland.samples.nonsequential.SAMPLE_SCENES`.
        """
        from optiland.samples.nonsequential import (  # noqa: PLC0415
            SAMPLE_SCENES,
            build_sample_scene,
        )

        self.set_scene(build_sample_scene(key), SAMPLE_SCENES[key])

    def load_file(self, path: str, connector=None) -> None:
        """Load a multi-axis system (``.olsys``) or a plain scene file.

        A system with paths is built again from them, so a stored scene
        that no longer belongs to its design is never shown -- a file saved
        after a rebuild had failed, or one an older converter wrote. When
        that rebuild fails, the stored scene stays, :attr:`scene_outdated`
        says why and ``sceneOutdated`` is emitted.

        Args:
            path: Path to a file written by ``MultiAxisSystem.to_json`` or
                ``NSQScene.to_json``.
            connector: When given, the first path (if any) is activated in
                it, so the sequential tools show that design right away.
        """
        from optiland.nonsequential.system import MultiAxisSystem  # noqa: PLC0415

        system = MultiAxisSystem.from_json(path)
        outdated: str | None = None
        if system.paths:
            try:
                system.rebuild()
            except Exception as exc:  # noqa: BLE001 -- reported, file still opens
                logger.exception("Rebuilding the scene of %s failed", path)
                outdated = str(exc)
        self.set_system(system, os.path.basename(path), path)
        self._scene_outdated = outdated
        if outdated is not None:
            self.sceneOutdated.emit(outdated)
        if connector is not None and system.paths:
            self.activate_path(system.paths[0].name, connector)

    def save_file(
        self, path: str, *, application: tuple[str, str] | None = None
    ) -> None:
        """Write the document (scene, paths and fold settings) to ``path``.

        Args:
            path: Destination path.
            application: ``(name, version)`` recorded in the file as the
                program that saved it.

        Raises:
            RuntimeError: If no system is loaded.
        """
        if self._system is None:
            raise RuntimeError("No system to save.")
        self._system.to_json(path, application=application)
        self._scene_path = path
        self._scene_label = os.path.basename(path)
        self._dirty = False
        self.sceneChanged.emit()

    def set_sampling(self, split_depth: int) -> None:
        """Set the scene's bounded-splitting depth (NumPy engine only).

        Args:
            split_depth: ``0`` for single-branch roulette, ``n > 0`` to
                follow both Fresnel/coating branches for the first ``n``
                surface hits of every ray.
        """
        from optiland.nonsequential.ir.scene_ir import SamplingPolicy  # noqa: PLC0415

        if self._scene is None:
            return
        policy = self._scene.sampling_policy
        self._scene.sampling_policy = SamplingPolicy(
            reflect_prob=policy.reflect_prob,
            split_depth=int(split_depth),
            split_budget=policy.split_budget,
            rr_start_flux=policy.rr_start_flux,
        )

    # ------------------------------------------------------------------
    # Tracing
    # ------------------------------------------------------------------

    def _trace_fn(
        self,
        num_rays: int,
        seed: int,
        max_depth: int,
        record_paths: int,
    ):
        """Return the zero-argument callable that runs the trace."""
        from optiland.nonsequential.backends.numpy_backend import (  # noqa: PLC0415
            NumpyBackend,
        )

        scene = self._scene

        def _run():
            # Pin the NumPy engine so a Torch backend selected elsewhere in
            # the process (the scripting terminal) does not turn a GUI
            # trace into a fixed-shape autograd trace.
            return scene.trace(
                num_rays=int(num_rays),
                max_depth=int(max_depth),
                seed=int(seed),
                record_paths=int(record_paths) if record_paths > 0 else False,
                backend=NumpyBackend(seed=int(seed)),
            )

        return _run

    def trace_sync(
        self,
        num_rays: int = 10_000,
        seed: int = 0,
        max_depth: int = 16,
        record_paths: int = 500,
    ) -> SimulationResult:
        """Trace on the calling thread and store the result.

        Args:
            num_rays: Rays to launch.
            seed: RNG seed.
            max_depth: Maximum surface hits per ray.
            record_paths: Approximate number of rays whose paths are
                recorded for the layout overlay (``0`` records nothing).

        Returns:
            The trace result.

        Raises:
            RuntimeError: If no scene is loaded.
        """
        if self._scene is None:
            raise RuntimeError("No non-sequential scene loaded.")
        result = self._trace_fn(num_rays, seed, max_depth, record_paths)()
        self._result = result
        self.traceFinished.emit(result)
        return result

    def trace_async(
        self,
        num_rays: int = 10_000,
        seed: int = 0,
        max_depth: int = 16,
        record_paths: int = 500,
    ) -> bool:
        """Trace on a worker thread; results arrive via :attr:`traceFinished`.

        Args:
            num_rays: Rays to launch.
            seed: RNG seed.
            max_depth: Maximum surface hits per ray.
            record_paths: Approximate number of recorded ray paths.

        Returns:
            ``True`` if a trace was started, ``False`` if none is loaded or
            one is already running.
        """
        if self._scene is None or self._thread is not None:
            return False

        worker = _Worker(self._trace_fn(num_rays, seed, max_depth, record_paths))
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        self._thread = thread
        self._worker = worker
        self.traceStarted.emit()
        thread.start()
        return True

    def _release_thread(self) -> None:
        self._thread = None
        self._worker = None

    def _on_worker_finished(self, result: object) -> None:
        self._release_thread()
        self._result = result
        self.traceFinished.emit(result)

    def _on_worker_error(self, exc: object) -> None:
        self._release_thread()
        logger.error("Non-sequential trace failed: %s", exc)
        self.traceFailed.emit(str(exc))

    def wait(self, timeout_ms: int = 60_000) -> bool:
        """Block until a running background trace has finished.

        Args:
            timeout_ms: Maximum wait in milliseconds.

        Returns:
            ``True`` if no trace is running afterwards.
        """
        thread = self._thread
        if thread is None:
            return True
        return bool(thread.wait(timeout_ms))

    # ------------------------------------------------------------------
    # Result summaries
    # ------------------------------------------------------------------

    def summary_rows(self) -> list[tuple[str, str]]:
        """Key/value rows describing the latest result for a table.

        Returns:
            ``(label, value)`` pairs: one per detector (flux and ray count)
            followed by the global energy balance and timing.
        """
        result = self._result
        if result is None:
            return []
        rows: list[tuple[str, str]] = []
        for name, detector in result.detectors.items():
            flux = getattr(detector, "total_flux_float", None)
            if flux is None:
                flux = getattr(detector, "total_flux", None)
            hits = getattr(detector, "num_rays_hit", None)
            value = f"{float(flux):.6g} W" if flux is not None else "n/a"
            if hits is not None:
                value += f"  ({int(hits)} rays)"
            rows.append((f"Detector '{name}'", value))
        rows.append(("Rays launched", f"{result.num_rays_total}"))
        rows.append(("Flux in", f"{result.total_flux_in:.6g} W"))
        rows.append(("Flux detected", f"{result.total_flux_detected:.6g} W"))
        rows.append(("Flux absorbed (surfaces)", f"{result.total_flux_absorbed:.6g} W"))
        rows.append(
            ("Flux absorbed (bulk)", f"{result.total_flux_bulk_absorbed:.6g} W")
        )
        rows.append(("Flux escaped", f"{result.total_flux_escaped:.6g} W"))
        rows.append(("Flux lost (depth/roulette)", f"{result.total_flux_lost:.6g} W"))
        rows.append(("Conservation error", f"{result.flux_conservation_error:.3e}"))
        rows.append(("Rays escaped", f"{result.num_rays_escaped}"))
        rows.append(("Rays depth-killed", f"{result.num_rays_depth_killed}"))
        rows.append(("Trace time", f"{result.trace_time_sec:.3f} s"))
        return rows
