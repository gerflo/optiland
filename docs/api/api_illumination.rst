Illumination
============

This section covers the light sources of illumination paths. An
:class:`illumination.LEDRing` describes a ring of identical LEDs in the
object plane of a sequential illumination path: the LED type
(:class:`illumination.LEDType` -- emitting area, radiation pattern,
spectrum, optional flux) and the arrangement. It is stored on the optic as
``Optic.light_source`` and saved with it.

:func:`illumination.apply_led_ring` makes a ring the light source of an
optic and derives the path's settings from it: object-height fields at the
area centroids of radial bands of equal emitting area (optionally framed by
the zone edges at weight 0) and wavelengths at the power centroids of
equal-power bands of the LED spectrum. The non-sequential fold
(:func:`nonsequential.fold.fold_paths`) builds its illumination emitter
from the same ring -- an ``LEDRingSource`` with one chip per LED, or an
annular ``ExtendedSource`` -- with the LED's radiation pattern, spectrum
and flux.

What a datasheet does not give can stay at its default:

- :class:`illumination.RadiationPattern` is Lambertian unless a
  half-intensity angle (``I = cos^m``) or a digitized table is given;
- :class:`illumination.LEDSpectrum` is the central wavelength alone
  (monochromatic) unless a FWHM (Gaussian) or a digitized table is given;
- an unknown flux leaves the non-sequential trace normalised.

.. code-block:: python

   from optiland.illumination import LEDRing, LEDSpectrum, LEDType, apply_led_ring

   led = LEDType(
       name="ring LED",
       chip_width=1.2,  # tangential [mm]
       chip_height=1.2,  # radial [mm]
       spectrum=LEDSpectrum(center_um=0.53),
   )
   ring = LEDRing(led=led, count=12, pitch_diameter=6.5, field_count=5)
   apply_led_ring(illumination_optic, ring)  # fields and wavelengths follow

.. autosummary::
   :toctree: illumination/
   :caption: Illumination Modules

   illumination.led_ring
   illumination.radiation
   illumination.spectrum
