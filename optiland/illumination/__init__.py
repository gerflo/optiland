"""Light sources of illumination paths.

:class:`LEDRing` describes a ring of LEDs in the object plane of an
illumination path; :func:`apply_led_ring` makes it the path's light source
and derives the path's fields and wavelengths from it. The non-sequential
fold builds its emitter from the same description.
"""

from __future__ import annotations

from optiland.illumination.led_ring import (
    EMITTER_MODELS,
    LED_RING_TYPE,
    LEDRing,
    LEDType,
    apply_led_ring,
    light_source_from_dict,
)
from optiland.illumination.radiation import PATTERN_KINDS, RadiationPattern
from optiland.illumination.spectrum import SPECTRUM_KINDS, LEDSpectrum

__all__ = [
    "EMITTER_MODELS",
    "LED_RING_TYPE",
    "PATTERN_KINDS",
    "SPECTRUM_KINDS",
    "LEDRing",
    "LEDSpectrum",
    "LEDType",
    "RadiationPattern",
    "apply_led_ring",
    "light_source_from_dict",
]
