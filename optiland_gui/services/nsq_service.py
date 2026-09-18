"""Non-sequential (NSQ) document service for the Optiland GUI.

The sequential ``OptilandConnector`` and its undo snapshots work on an
``Optic``. A non-sequential scene is a different document: it has sources,
components and detectors instead of a surface list, its own JSON format
(``nsq_schema_version``) and Monte Carlo results instead of ray records.
:class:`NSQService` owns that document for the GUI: it loads sample scenes
or scene files, saves them, and runs traces on a worker thread so a long
Monte Carlo run never blocks the UI.

Author: Optiland contributors, 2026
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal

from optiland_gui.worker import _Worker

if TYPE_CHECKING:
    from optiland.nonsequential.scene import NSQScene
    from optiland.nonsequential.system import MultiAxisSystem, OpticalPath
    from optiland.nonsequential.tracer import SimulationResult
    from optiland.optic import Optic

logger = logging.getLogger(__name__)


class NSQService(QObject):
    """Owns the current non-sequential scene and its latest trace result.

    Signals:
        sceneChanged: The scene was replaced (sample built, file loaded).
        traceStarted: A background trace began.
        traceFinished (object): A trace completed; carries the
            :class:`~optiland.nonsequential.tracer.SimulationResult`.
        traceFailed (str): A trace raised; carries the error message.
    """

    sceneChanged = Signal()
    pathsChanged = Signal()
    activePathChanged = Signal(object)
    traceStarted = Signal()
    traceFinished = Signal(object)
    traceFailed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._system: MultiAxisSystem | None = None
        self._scene: NSQScene | None = None
        self._scene_path: str | None = None
        self._scene_label: str = ""
        self._result: SimulationResult | None = None
        self._active_path: str | None = None
        self._activating = False
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
        """File the current scene was loaded from or saved to, if any."""
        return self._scene_path

    @property
    def scene_label(self) -> str:
        """Human-readable label of the current scene."""
        return self._scene_label

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
        self._result = None
        self._active_path = None
        self.pathsChanged.emit()
        self.activePathChanged.emit(None)
        self.sceneChanged.emit()

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
        optic = self.path(name).build_optic()
        self._activating = True
        try:
            connector.load_optic_from_object(optic)
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
        self.pathsChanged.emit()
        self.activePathChanged.emit(self._active_path)

    def sync_active_path(self, optic: Optic) -> None:
        """Take the edited sequential design of the active path and rebuild.

        Args:
            optic: The connector's current optic.

        Raises:
            RuntimeError: If no path is active or the system cannot be
                rebuilt (no fold settings).
            Exception: Whatever the fold raises for an inconsistent edit;
                the previous scene is kept in that case.
        """
        if self._system is None or self._active_path is None:
            raise RuntimeError("No active optical path.")
        previous = self._system.path(self._active_path).optic
        self._system.set_path_optic(self._active_path, optic)
        try:
            self._system.rebuild()
        except Exception:
            self._system.set_path_optic(self._active_path, previous)
            raise
        self._scene = self._system.scene
        self._result = None
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

    def load_file(self, path: str) -> None:
        """Load a multi-axis system (``.olsys``) or a plain scene file.

        Args:
            path: Path to a file written by ``MultiAxisSystem.to_json`` or
                ``NSQScene.to_json``.
        """
        from optiland.nonsequential.system import MultiAxisSystem  # noqa: PLC0415

        system = MultiAxisSystem.from_json(path)
        self.set_system(system, os.path.basename(path), path)

    def save_file(self, path: str) -> None:
        """Write the current scene to an NSQ JSON file.

        Args:
            path: Destination path.

        Raises:
            RuntimeError: If no scene is loaded.
        """
        if self._system is None:
            raise RuntimeError("No non-sequential scene to save.")
        self._system.to_json(path)
        self._scene_path = path
        self._scene_label = os.path.basename(path)
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
