from __future__ import annotations

#: Version of the Optiland GUI application. Shown in the About dialog and
#: written into every ``.olsys`` file the GUI saves (``"application"`` key).
#:
#: Raise it whenever the ``.olsys`` format version
#: (``optiland.nonsequential.system.OLSYS_FORMAT_VERSION``) is raised: a file
#: an older GUI cannot open must come from a newer GUI version.
__version__ = "0.3.0"
