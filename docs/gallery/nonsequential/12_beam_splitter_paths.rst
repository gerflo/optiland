.. _nsq_beam_splitter_paths:

Beam Splitters and Multi-Path Illumination
==========================================

This walkthrough covers the two things a beam splitter asks of a ray
tracer: splitting one input beam into two arms, and letting two
*independent* sources share one splitter, the way a side illumination and
a transmission imaging path do in a microscope or fundus camera. Both are
non-sequential problems: the surface order is not fixed, and one ray
becomes two. The scenes below ship in
:mod:`optiland.samples.nonsequential` and are the ones the tests and the
GUI's **Non-Sequential** panel use.

One beam, two arms
------------------

A partially reflecting plate is a
:class:`~optiland.nonsequential.components.refractive.RefractiveComponent`
whose two media are the same (vacuum here) and whose ``coating`` is an
unpolarized ``SimpleCoating``. The coating has to be *passive*: its
reflectance and transmittance are checked at construction to be finite,
non-negative and to sum to at most 1.

.. code-block:: python

    import math

    from optiland.coatings import SimpleCoating
    from optiland.coordinate_system import CoordinateSystem
    from optiland.nonsequential import (
        VACUUM,
        CollimatedSourceConfig,
        FinitePlaneGeometry,
        IrradianceDetectorConfig,
        NSQScene,
        RefractiveComponent,
        Spectrum,
    )

    scene = NSQScene()
    scene.add_source(
        "source",
        CoordinateSystem(),
        CollimatedSourceConfig(
            spectrum=Spectrum.monochromatic(0.55), total_flux=1.0, aperture_radius=1.0
        ),
    )
    scene.add_component(
        "splitter",
        RefractiveComponent(
            cs=CoordinateSystem(z=10, ry=math.pi / 4),   # 45 deg about y
            geometry=FinitePlaneGeometry(aperture_radius=5),
            material_front=VACUUM,
            material_back=VACUUM,
            coating=SimpleCoating(transmittance=0.5, reflectance=0.5),
            name="splitter",
        ),
    )
    detector = IrradianceDetectorConfig(width=10, height=10, num_pixels_x=8, num_pixels_y=8)
    scene.add_detector("transmitted", CoordinateSystem(z=20), detector)
    scene.add_detector("reflected", CoordinateSystem(x=-10, z=10, ry=math.pi / 2), detector)

The same scene is available as ``beam_splitter_scene()``. A beam travelling
along ``+z`` reflects towards ``-x`` at this plate; the reflected arm is
therefore watched by a detector at ``x = -10`` facing the plate.

Roulette or both branches
~~~~~~~~~~~~~~~~~~~~~~~~~

By default every ray takes *one* branch per hit, drawn with the coating's
reflectance as probability and carrying its full flux. The arm powers are
then binomial estimates:

.. code-block:: python

    result = scene.trace(num_rays=2048, seed=7)
    result.detectors["transmitted"].total_flux_float   # ~0.50, sigma 0.011
    result.detectors["reflected"].total_flux_float     # ~0.50

With bounded splitting (NumPy engine only) the first ``split_depth`` hits
of every ray spawn *both* children with the exact weights ``R`` and
``T``; the arm powers are then exact and every source ray ends on both
detectors:

.. code-block:: python

    from optiland.nonsequential.ir.scene_ir import SamplingPolicy

    scene.sampling_policy = SamplingPolicy(split_depth=1)
    result = scene.trace(num_rays=2048, seed=7, record_paths=True)
    result.detectors["transmitted"].total_flux_float   # 0.5 exactly
    result.detectors["reflected"].total_flux_float     # 0.5 exactly

Where each child came from
~~~~~~~~~~~~~~~~~~~~~~~~~~

A spawned child gets a fresh ``ray_id``. Its first event in
``result.ray_paths["events"]`` is a ``"split"`` whose ``parent_id`` column
names the ray it was split from (``-1`` on every other event). Under
``record_paths=<int>`` a child is recorded exactly when its root ray is,
so a recorded parent never loses its children:

.. code-block:: python

    events = result.ray_paths["events"]
    splits = events[events["event_type"] == "split"]
    parent_of = dict(zip(splits["ray_id"], splits["parent_id"]))

Zero-flux children are never spawned: a hit under total internal
reflection, or a coating with ``T = 0``, produces only the reflected ray.

Side illumination, imaging in transmission
------------------------------------------

``side_illumination_transmission_scene()`` puts two independent sources on
one splitter:

- ``"illumination"``: a collimated beam entering from ``+x``. Half of it is
  folded up onto the sample plane at ``z = 25``, where the ``"sample"``
  detector records the illumination footprint; the other half ends on
  ``"illumination_dump"``.
- ``"object"``: a point source *at* the sample plane emitting towards
  ``-z``, standing in for the light the sample transmits. Half of it passes
  the splitter and is imaged by a biconvex lens onto the ``"camera"``
  detector at the paraxial image distance
  (:func:`~optiland.samples.nonsequential.thick_lens_image_distance`);
  the other half is reflected back out to the ``"return"`` detector.

.. code-block:: python

    from optiland.samples.nonsequential import side_illumination_transmission_scene

    scene = side_illumination_transmission_scene()
    scene.sampling_policy = SamplingPolicy(split_depth=1)
    result = scene.trace(num_rays=4096, seed=5, record_paths=True)
    for name, det in result.detectors.items():
        print(f"{name:18s} {det.total_flux_float:.4f} W  {det.num_rays_hit} rays")

::

    sample             0.5000 W  2048 rays
    camera             0.4997 W  2048 rays
    illumination_dump  0.5000 W  2048 rays
    return             0.5000 W  2048 rays

The lens faces carry a lossless coating so the only shortfall on the
camera is the bulk absorption of 4 mm of N-BK7, which the result reports
as ``total_flux_bulk_absorbed`` rather than losing it. The event log shows
that the two arms never mix: every ray on ``"sample"`` and
``"illumination_dump"`` descends from ``"illumination"``, every ray on
``"camera"`` and ``"return"`` from ``"object"``.

Two independent sources are *not* the same thing as one split beam. The
illumination and the object light are incoherent and additive; the
tracer never combines their fields. Coherent recombination (an
interferometer arm meeting itself again) is outside this model.

Precision
---------

A ray that has just interacted with a surface sits *on* that surface up
to the rounding error of its stored position. The tracer pushes every ray
origin forward by a distance that scales with the float precision and the
coordinate magnitude before it intersects (about ``4e-5`` mm at a 10 mm
scale in float32, ``1e-9`` mm in float64), so a float32 trace on the Torch
backend no longer re-hits the plate it just left. The reference tests
check NumPy/float64, Torch/float64 and Torch/float32 explicitly and
require the same arm powers ray for ray.

Saving and the GUI
------------------

Raw surfaces added with ``scene.add_component`` round-trip through
``scene.to_json`` / ``NSQScene.from_json`` (planar, conic and spherical
geometries, catalog glasses or vacuum, ``SimpleCoating`` or a constant
reflectance). The GUI's **Non-Sequential** panel opens the same files,
builds both sample scenes, traces them on a worker thread and shows the
layout with recorded paths, the detector maps and the energy balance.

Related
-------

- :ref:`nsq_sampling` in the developer guide for the sampling policy.
- :doc:`08_stray_light_analysis` for ghosts in a lens, the other common
  use of a partial reflection.
