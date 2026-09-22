"""Service classes for the Optiland GUI.

This package contains focused service classes extracted from ``OptilandConnector``
following the single-responsibility principle. Each service handles one domain of
the GUI's business logic. Services are plain Python classes (not QObject subclasses)
that receive a connector reference for signal emission and optic access.

The submodules are imported lazily (PEP 562): ``from optiland_gui.services
import SurfaceService`` keeps working, but importing one Qt-free service (for
example ``optiland_gui.services.surface_service``) no longer pulls in the
services that need PySide6 (``optimization_service``, ``nsq_service``). Tools
without a Qt installation, such as the Optomal sidecar, rely on this.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from optiland_gui.services.analysis_runner import AnalysisRunner
    from optiland_gui.services.file_service import FileService
    from optiland_gui.services.optimization_service import OptimizationService
    from optiland_gui.services.surface_service import SurfaceService
    from optiland_gui.services.system_service import SystemService

_EXPORTS: dict[str, str] = {
    "AnalysisRunner": "analysis_runner",
    "FileService": "file_service",
    "OptimizationService": "optimization_service",
    "SurfaceService": "surface_service",
    "SystemService": "system_service",
}

__all__ = [
    "AnalysisRunner",
    "FileService",
    "OptimizationService",
    "SurfaceService",
    "SystemService",
]


def __getattr__(name: str) -> Any:
    """Import the service class on first access (PEP 562)."""
    try:
        module_name = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    module = importlib.import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
