"""
Antireflexpunkte in den Optiland-Beleuchtungsstrahlengang einbauen
==================================================================

Fügt zwei Antireflexpunkte als Blenden-Surfaces ein:

  Punkt 1:  z = 160.7 mm  (Pupillenkonjugat, zwischen 47637 S1 und Lochspiegel)
  Punkt 2:  am Lochspiegel (z = 164.5 mm, bereits vorhandene Fläche modifizieren)

Beide Punkte sind DifferenceAperture: volle Öffnung MINUS zentraler Absorptionsdot.
Der Dot-Radius wird als Parameter übergeben und kann empirisch angepasst werden.

Verwendung:
    python antireflexpunkte_einbauen.py input.json output.json [r_dot1_mm] [r_dot2_mm]
"""

import sys
import json
import copy
import math

# ─── Parameter ──────────────────────────────────────────────────────────────
Z_DOT1         = 160.7    # mm, Position Antireflexpunkt 1 (Pupillenkonjugat)
Z_47637_S1     = 100.5    # mm, vorherige Fläche (47637 S1)
Z_LOCHSPIEGEL  = 164.5    # mm, Lochspiegel (Antireflexpunkt 2)

R_OUTER        = 10.0     # mm, äußere Grenze der Blende (Strahlradius hier ~8mm)

# Standard Dot-Radien (empirisch anpassen):
# - Kleiner als r=5.2mm (innere Kante der Ringbeleuchtung am Konjugat)
# - Groß genug um Ghost-Strahl vollständig zu blockieren
R_DOT1_DEFAULT = 2.5      # mm, Radius Antireflexpunkt 1
R_DOT2_DEFAULT = 2.5      # mm, Radius Antireflexpunkt 2 (Lochspiegel)


# ─── JSON-Helfer ─────────────────────────────────────────────────────────────

def load_json(path):
    """Lädt JSON mit Infinity-Behandlung."""
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    # Python-json kennt kein Infinity – temporär ersetzen
    text = text.replace('Infinity', '1e30').replace('-1e30', '-1e30')
    data = json.loads(text)
    return data

def save_json(data, path):
    """Speichert JSON, stellt Infinity wieder her."""
    text = json.dumps(data, indent=4, ensure_ascii=False)
    text = text.replace('1e+30', 'Infinity').replace('1e30', 'Infinity')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"  Gespeichert: {path}")


def make_surface_dict(z, thickness, r_dot, r_outer, comment):
    """Erzeugt ein Standard-Surface-Dict für eine Antireflexpunkt-Blende."""
    return {
        "type": "Surface",
        "surface_type": "standard",
        "thickness": thickness,
        "geometry": {
            "type": "Plane",
            "cs": {
                "x": 0.0, "y": 0.0, "z": z,
                "rx": 0.0, "ry": 0.0, "rz": 0.0,
                "reference_cs": None
            },
            "radius": 1e30  # Infinity → Planfläche
        },
        "material_post": {
            "type": "IdealMaterial",
            "propagation_model": {"class": "HomogeneousPropagation"},
            "index": 1.0,
            "absorp": 0.0
        },
        "is_stop": False,
        "aperture": {
            "type": "DifferenceAperture",
            "a": {"type": "RadialAperture", "r_max": r_outer, "r_min": 0.0},
            "b": {"type": "RadialAperture", "r_max": r_dot,   "r_min": 0.0}
        },
        "comment": comment,
        "group_id":   None,
        "group_name": None,
        "group_role": None,
        "interaction_model": {
            "type": "RefractiveReflectiveModel",
            "is_reflective": False,
            "coating": None,
            "bsdf": None
        }
    }


def add_antireflexpunkte(input_path, output_path, r_dot1=R_DOT1_DEFAULT, r_dot2=R_DOT2_DEFAULT):
    """Hauptfunktion: liest System, fügt Antireflexpunkte ein, speichert."""

    print(f"\n=== Antireflexpunkte einbauen ===")
    print(f"  Eingabe:   {input_path}")
    print(f"  Ausgabe:   {output_path}")
    print(f"  Dot1 bei z={Z_DOT1}mm, r={r_dot1}mm")
    print(f"  Dot2 am Lochspiegel z={Z_LOCHSPIEGEL}mm, r={r_dot2}mm")

    data = load_json(input_path)
    surfaces = data["surface_group"]["surfaces"]

    # ── Flächen-Index-Suche ─────────────────────────────────────────────────
    def find_surface_by_z(z_target, tol=0.1):
        for i, s in enumerate(surfaces):
            z = s.get("geometry", {}).get("cs", {}).get("z", None)
            if z is not None and abs(z - z_target) < tol:
                return i
        return None

    def find_surface_by_comment(comment_substr):
        for i, s in enumerate(surfaces):
            if comment_substr.lower() in s.get("comment", "").lower():
                return i
        return None

    # ── (1) 47637 S1-Dicke anpassen ─────────────────────────────────────────
    idx_47637 = find_surface_by_z(Z_47637_S1)
    if idx_47637 is None:
        idx_47637 = find_surface_by_comment("47637")
        # nimm das letzte 47637-Element
        for i, s in enumerate(surfaces):
            if "47637" in s.get("comment", "") and s.get("geometry", {}).get("cs", {}).get("z", 0) < 110:
                idx_47637 = i

    if idx_47637 is None:
        print("  FEHLER: 47637 S1-Fläche nicht gefunden!")
        return

    old_thickness_47637 = surfaces[idx_47637]["thickness"]
    new_thickness_47637 = Z_DOT1 - Z_47637_S1   # 60.2 mm
    surfaces[idx_47637]["thickness"] = new_thickness_47637
    print(f"\n  [1] 47637 S1 (idx={idx_47637}): Dicke {old_thickness_47637} → {new_thickness_47637:.1f} mm")

    # ── (2) Antireflexpunkt-1-Fläche einfügen ──────────────────────────────
    dot1 = make_surface_dict(
        z         = Z_DOT1,
        thickness = Z_LOCHSPIEGEL - Z_DOT1,   # 3.8 mm
        r_dot     = r_dot1,
        r_outer   = R_OUTER,
        comment   = f"Antireflexpunkt 1 (r={r_dot1}mm, Hornhaut-Ghost)"
    )

    # Einfügen direkt NACH 47637 S1 (= vor Lochspiegel)
    insert_pos = idx_47637 + 1
    surfaces.insert(insert_pos, dot1)
    print(f"  [2] Antireflexpunkt 1 eingefügt bei Index {insert_pos} (z={Z_DOT1}mm)")

    # ── (3) Antireflexpunkt 2: Lochspiegel-Apertur modifizieren ────────────
    # Nach dem Einfügen hat sich der Index verschoben
    idx_lochsp = find_surface_by_z(Z_LOCHSPIEGEL)
    if idx_lochsp is None:
        idx_lochsp = find_surface_by_comment("lochspiegel")

    if idx_lochsp is not None:
        lochsp = surfaces[idx_lochsp]
        old_aperture = lochsp.get("aperture")

        if old_aperture and old_aperture.get("type") == "DifferenceAperture":
            # Bereits eine DifferenceAperture → nur Innenradius anpassen
            lochsp["aperture"]["b"]["r_max"] = max(
                lochsp["aperture"]["b"].get("r_max", 0), r_dot2
            )
            print(f"  [3] Lochspiegel (idx={idx_lochsp}): DifferenceAperture-Innenradius auf r={r_dot2}mm gesetzt")
        else:
            # Bisher nur RadialAperture → zu DifferenceAperture upgraden
            r_outer_ls = old_aperture["r_max"] if old_aperture else R_OUTER
            lochsp["aperture"] = {
                "type": "DifferenceAperture",
                "a": {"type": "RadialAperture", "r_max": r_outer_ls, "r_min": 0.0},
                "b": {"type": "RadialAperture", "r_max": r_dot2,     "r_min": 0.0}
            }
            print(f"  [3] Lochspiegel (idx={idx_lochsp}): Apertur auf DifferenceAperture(r_dot={r_dot2}mm) umgestellt")
    else:
        print("  [3] Lochspiegel nicht gefunden – Punkt 2 übersprungen")

    # ── Validation ──────────────────────────────────────────────────────────
    print(f"\n  Validierung der Surface-Positionen nach Einfügen:")
    for i, s in enumerate(surfaces):
        z = s.get("geometry", {}).get("cs", {}).get("z", "?")
        comment = s.get("comment", s.get("type", ""))[:40]
        t = s.get("thickness", "-")
        print(f"    [{i:2d}] z={z:>7}  t={t:>7}  {comment}")

    # ── Speichern ────────────────────────────────────────────────────────────
    save_json(data, output_path)
    print(f"\nFertig. Lade die neue Datei in Optiland:")
    print(f"  from optiland.fileio.optiland_handler import load_optiland_file")
    print(f"  lens = load_optiland_file('{output_path}')")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Verwendung: python antireflexpunkte_einbauen.py INPUT.json OUTPUT.json [r_dot1] [r_dot2]")
        print()
        print("Beispiele:")
        print("  python antireflexpunkte_einbauen.py system.json system_mit_arp.json")
        print("  python antireflexpunkte_einbauen.py system.json system_mit_arp.json 2.0 2.5")
        sys.exit(1)

    input_file  = sys.argv[1]
    output_file = sys.argv[2]
    r_dot1 = float(sys.argv[3]) if len(sys.argv) > 3 else R_DOT1_DEFAULT
    r_dot2 = float(sys.argv[4]) if len(sys.argv) > 4 else R_DOT2_DEFAULT

    add_antireflexpunkte(input_file, output_file, r_dot1, r_dot2)
