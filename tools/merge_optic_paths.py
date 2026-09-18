"""Merge an imaging and an illumination path into one non-sequential scene.

Both paths are given as unfolded sequential Optiland files that share a
tail and meet at a perforated fold mirror (a fundus camera, a coaxial
illuminator). The result is a multi-axis system file (``.olsys``) the GUI
opens in its Non-Sequential panel, plus an optional per-source trace with a
Markdown report and PNG plots.

Examples::

    # Fold the RCR-03 paths at their Lochspiegel (surface 7 in the
    # observation file, surface 12 in the illumination file):
    python tools/merge_optic_paths.py \\
        --imaging "RCR-03 Beobachtung.json" --illumination "RCR-03 Beleuchtung.json" \\
        --fold-imaging 7 --fold-illumination 12 --out merged.olsys

    # ... and trace 200 000 rays per source, writing a report and plots:
    python tools/merge_optic_paths.py ... --trace 200000 --report report.md --plots out/

The scene is written as a multi-axis system file (``.olsys``, appended when
``--out`` has no extension); the GUI opens it via File -> Open.

See :mod:`optiland.nonsequential.fold` for what the merge does and assumes.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from pathlib import Path

import numpy as np


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--imaging", required=True, help="Sequential JSON, sample -> camera."
    )
    parser.add_argument(
        "--illumination", required=True, help="Sequential JSON, source -> sample."
    )
    parser.add_argument(
        "--fold-imaging", type=int, required=True, help="Hole surface index (imaging)."
    )
    parser.add_argument(
        "--fold-illumination",
        type=int,
        required=True,
        help="Ring surface index (illumination).",
    )
    parser.add_argument(
        "--out", required=True, help="Multi-axis system file to write (.olsys)."
    )
    parser.add_argument(
        "--imaging-name",
        default=None,
        help="Name of the imaging path (default: the file's system name).",
    )
    parser.add_argument(
        "--illumination-name",
        default=None,
        help="Name of the illumination path (default: the file's system name).",
    )
    parser.add_argument("--angle", type=float, default=45.0, help="Mirror tilt [deg].")
    parser.add_argument(
        "--hole",
        choices=["projected", "physical"],
        default="projected",
        help="'projected': the hole appears circular on axis (elliptical in the "
        "mirror plane); 'physical': a circle of that diameter in the plane.",
    )
    parser.add_argument(
        "--tail-from",
        choices=["imaging", "illumination"],
        default="imaging",
        help="Which file supplies the shared tail between sample and mirror.",
    )
    parser.add_argument(
        "--mirror-reflectance", type=float, default=1.0, help="Ring mirror reflectance."
    )
    parser.add_argument(
        "--lossless",
        choices=["glass", "all", "none"],
        default="glass",
        help="Lossless coatings on catalog-glass surfaces (default), on every "
        "refractive surface, or on none (bare Fresnel everywhere).",
    )
    parser.add_argument(
        "--illumination-flux", type=float, default=1.0, help="Emitter flux [W]."
    )
    parser.add_argument(
        "--object-flux",
        type=float,
        default=1.0,
        help="Flux per sample point source [W].",
    )
    parser.add_argument(
        "--illumination-half-angle",
        type=float,
        default=None,
        help="Emitter cone half angle [deg]; default from the entrance pupil.",
    )
    parser.add_argument(
        "--sample-size", type=float, default=None, help="Sample detector edge [mm]."
    )
    parser.add_argument(
        "--camera-pixels",
        type=int,
        default=256,
        help="Camera detector pixels per edge.",
    )
    parser.add_argument(
        "--trace", type=int, default=0, help="Rays per source to trace (0 = no trace)."
    )
    parser.add_argument("--seed", type=int, default=7, help="RNG seed for the traces.")
    parser.add_argument("--max-depth", type=int, default=48, help="Max hits per ray.")
    parser.add_argument("--report", default=None, help="Markdown report to write.")
    parser.add_argument("--plots", default=None, help="Directory for PNG plots.")
    return parser.parse_args()


def _centroid_and_rms(detector) -> tuple[float, float, float]:
    """``(x, y, rms_radius)`` of an irradiance map, flux weighted."""
    irr = np.asarray(detector.irradiance, dtype=float)
    total = irr.sum()
    if total <= 0.0:
        return math.nan, math.nan, math.nan
    xx, yy = np.meshgrid(detector.x_coords, detector.y_coords)
    cx = float((irr * xx).sum() / total)
    cy = float((irr * yy).sum() / total)
    rms = float(math.sqrt((irr * ((xx - cx) ** 2 + (yy - cy) ** 2)).sum() / total))
    return cx, cy, rms


def _encircled_radius(detector, fraction: float = 0.9) -> float:
    """Radius around the centroid containing ``fraction`` of the flux."""
    irr = np.asarray(detector.irradiance, dtype=float)
    total = irr.sum()
    if total <= 0.0:
        return math.nan
    cx, cy, _ = _centroid_and_rms(detector)
    xx, yy = np.meshgrid(detector.x_coords, detector.y_coords)
    r = np.hypot(xx - cx, yy - cy).ravel()
    w = irr.ravel()
    order = np.argsort(r)
    cumulative = np.cumsum(w[order]) / total
    return float(r[order][np.searchsorted(cumulative, fraction)])


def _trace_and_report(scene, report, args, out_path: Path) -> str:
    from optiland.nonsequential.fold import CAMERA, SAMPLE, trace_per_source

    lines = [
        f"# Folded scene: {out_path.name}",
        "",
        "```",
        report.summary(),
        "```",
        "",
    ]
    if args.trace <= 0:
        return "\n".join(lines) + "\n"

    started = time.time()
    results = trace_per_source(
        scene,
        args.trace,
        seed=args.seed,
        max_depth=args.max_depth,
        record_paths=400,
    )
    elapsed = time.time() - started
    detectors = scene.detector_names
    lines.append(
        f"## Per-source powers ({args.trace} rays per source, seed {args.seed}, "
        f"{elapsed:.0f} s)"
    )
    lines.append("")
    header = (
        "| source | launched W | " + " | ".join(detectors) + " | absorbed | escaped |"
    )
    lines.append(header)
    lines.append("|" + " --- |" * (len(detectors) + 4))
    for name, result in results.items():
        source = scene.source_registry.get(name)
        launched = float(np.ravel(np.asarray(source.total_flux))[0])
        cells = [
            f"{result.detectors[d].total_flux_float:.5f} "
            f"({result.detectors[d].num_rays_hit})"
            for d in detectors
        ]
        lines.append(
            f"| {name} | {launched:.3f} | "
            + " | ".join(cells)
            + f" | {result.total_flux_absorbed:.5f} | {result.total_flux_escaped:.5f} |"
        )
    lines.append("")
    lines.append("## Spots on the camera and the sample")
    lines.append("")
    lines.append(
        "| source | detector | centroid x | centroid y | rms radius | r(90 %) |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for name, result in results.items():
        for det_name in (CAMERA, SAMPLE):
            det = result.detectors[det_name]
            if det.num_rays_hit == 0:
                continue
            cx, cy, rms = _centroid_and_rms(det)
            r90 = _encircled_radius(det)
            lines.append(
                f"| {name} | {det_name} | {cx:.4f} | {cy:.4f} | {rms:.4f} | {r90:.4f} |"
            )
    lines.append("")

    if args.plots:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plots = Path(args.plots)
        plots.mkdir(parents=True, exist_ok=True)
        from optiland.nonsequential.visualization.viewer_2d import NSQViewer2D

        lines.append("## Plots")
        lines.append("")
        for name, result in results.items():
            fig, ax = plt.subplots(figsize=(12, 6))
            NSQViewer2D(scene).view(result, ax=ax, num_rays=120, projection="XZ")
            ax.set_aspect("equal", adjustable="datalim")
            ax.set_title(f"{out_path.stem}: {name} (XZ)")
            path = plots / f"{out_path.stem}_{name}_layout.png"
            fig.savefig(path, dpi=130, bbox_inches="tight")
            plt.close(fig)
            lines.append(f"- {name}: layout `{path}`")
            hit = [d for d in detectors if result.detectors[d].num_rays_hit > 0]
            if hit:
                fig, axes = plt.subplots(
                    1, len(hit), figsize=(4.5 * len(hit), 4.2), layout="constrained"
                )
                for ax, det_name in zip(np.atleast_1d(axes), hit, strict=True):
                    result.detectors[det_name].plot(ax=ax)
                    ax.set_title(f"{name} -> {det_name}")
                path = plots / f"{out_path.stem}_{name}_detectors.png"
                fig.savefig(path, dpi=130)
                plt.close(fig)
                lines.append(f"- {name}: detectors `{path}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    """Fold the two files, write the scene and optionally trace and report."""
    args = _parse_args()
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import optiland.backend as be
    from optiland.fileio import load_optiland_file
    from optiland.nonsequential.serialization import SCENE_FILE_EXTENSION
    from optiland.nonsequential.system import fold_system

    be.set_backend("numpy")
    imaging = load_optiland_file(args.imaging)
    illumination = load_optiland_file(args.illumination)
    system, report = fold_system(
        imaging,
        illumination,
        args.fold_imaging,
        args.fold_illumination,
        imaging_name=args.imaging_name,
        illumination_name=args.illumination_name,
        angle_deg=args.angle,
        hole=args.hole,
        tail_from=args.tail_from,
        mirror_reflectance=args.mirror_reflectance,
        lossless=args.lossless,
        illumination_flux=args.illumination_flux,
        object_flux=args.object_flux,
        illumination_half_angle_deg=args.illumination_half_angle,
        sample_size=args.sample_size,
        camera_pixels=(args.camera_pixels, args.camera_pixels),
    )
    scene = system.scene
    out_path = Path(args.out)
    if not out_path.suffix:
        out_path = out_path.with_suffix(SCENE_FILE_EXTENSION)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    system.to_json(out_path)
    print(report.summary())
    print(f"paths: {', '.join(system.path_names)}")
    print(f"system written to {out_path}")

    text = _trace_and_report(scene, report, args, out_path)
    if args.trace > 0:
        print(text)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
        print(f"report written to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
