"""
Antireflexpunkte Funduskamera-Beleuchtung
==========================================

Verwendung:
    python antireflexpunkte_berechnung.py system.json [wellenlaenge_um]

Argumente:
    system.json         Optiland-Systemdatei (JSON)
    wellenlaenge_um     Wellenlaenge in Mikrometern, z.B. 0.55 (optional,
                        Standard: primaere Wellenlaenge des Systems)

Methode:
    Paraxialer Grenzstrahl vom Apertur-Stop (y=0, n*u=1).
    Nulldurchgaenge von y(z) = Pupillenkonjugate = Antireflexpunkt-Positionen.
    Zusaetzlich: Hornhau-Reflexions-Analyse und OL-Ghost-Analyse.
"""

import sys
import json
import numpy as np

sys.path.insert(0, r'c:\Projekte\Optiland\optiland-code')

from optiland.optic import Optic


# ────────────────────────────────────────────────────────────────
# System laden
# ────────────────────────────────────────────────────────────────

def load_system(filepath):
    """Ladet Optiland-JSON mit Infinity-Behandlung, gibt Optic zurueck."""
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()
    text = text.replace('Infinity', '1e30')
    data = json.loads(text)
    return Optic.from_dict(data)


def extract_surf_list(lens, wavelength):
    """
    Extrahiert aus einem geladenen Optic-Objekt die Flaechen-Liste
    im Format (label, z, R, n_post) fuer die paraxiale Rechnung.
    """
    surfaces = lens.surfaces.surfaces          # Tuple aller Surface-Objekte
    positions = lens.surfaces.positions        # Shape (N, 1)
    radii     = lens.surfaces.radii            # Shape (N,)
    n_post    = lens.surfaces.n(wavelength)    # Shape (N,)

    surf_list = []
    for i, surf in enumerate(surfaces):
        z     = float(positions[i, 0])
        R     = float(radii[i])
        n     = float(n_post[i])
        label = surf.comment if surf.comment else f"Surface {i}"
        surf_list.append((label, z, R, n))

    return surf_list


# ────────────────────────────────────────────────────────────────
# Paraxialer Trace (identisch mit vorheriger Version)
# ────────────────────────────────────────────────────────────────

def forward_trace(SURF, y0, nu0, start_idx=1):
    n = SURF[start_idx - 1][3] if start_idx > 0 else 1.0
    y, nu = y0, nu0
    out = [(SURF[start_idx][1], y, nu, n, SURF[start_idx][0])]
    for i in range(start_idx + 1, len(SURF)):
        lbl, z, R, n_post = SURF[i]
        d = z - SURF[i-1][1]
        y  = y + d / n * nu
        if abs(R) < 1e20:
            phi = (n_post - n) / R
            nu  = nu - phi * y
        n = n_post
        out.append((z, y, nu, n, lbl))
    return out


def zero_crossings(trace):
    zeros = []
    for i in range(1, len(trace)):
        z0, y0, nu0, n0, l0 = trace[i-1]
        z1, y1, nu1, n1, l1 = trace[i]
        if y0 * y1 < 0:
            u = nu0 / n0
            if abs(u) > 1e-12:
                z_cross = z0 + (-y0 / u)
                zeros.append((z_cross, l0, l1))
    return zeros


def sysmat(SURF, i_from, i_to):
    n = SURF[i_from - 1][3] if i_from > 0 else 1.0
    M = np.eye(2)
    for i in range(i_from, i_to + 1):
        lbl, z, R, n_post = SURF[i]
        if i > i_from:
            d = z - SURF[i-1][1]
            M = np.array([[1, d/n], [0, 1]]) @ M
        if abs(R) < 1e20:
            phi = (n_post - n) / R
            M = np.array([[1, 0], [-phi, 1]]) @ M
        n = n_post
    return M


def image_pos(SURF, z_obj, n_obj, i_from, i_to):
    z_first = SURF[i_from][1]
    T_obj   = np.array([[1, (z_first - z_obj) / n_obj], [0, 1]])
    M       = sysmat(SURF, i_from, i_to) @ T_obj
    n_img   = SURF[i_to][3]
    A, B, C, D = M[0,0], M[0,1], M[1,0], M[1,1]
    if abs(D) < 1e-14:
        return None, None
    d_img  = -B * n_img / D
    z_bild = SURF[i_to][1] + d_img
    denom  = A + C * d_img / n_img
    m      = 1.0 / denom if abs(denom) > 1e-10 else None
    return z_bild, m


# ────────────────────────────────────────────────────────────────
# Hilfsfunktionen fuer System-Inspektion
# ────────────────────────────────────────────────────────────────

def find_stop_index(lens):
    return lens.surfaces.stop_index


def find_last_refractive_before_image(SURF):
    """Gibt den Index der letzten Flaeche mit Brechkraft (R != inf) zurueck,
    ohne die Bild-Flaeche selbst."""
    last = len(SURF) - 2   # Bild-Flaeche ist ganz hinten
    while last > 0 and abs(SURF[last][2]) >= 1e20:
        last -= 1
    return last


def z_region(SURF, z):
    """Beschreibt zwischen welchen Flaechen die Position z liegt."""
    for i in range(len(SURF) - 1):
        if SURF[i][1] <= z <= SURF[i+1][1]:
            return f"zwischen '{SURF[i][0]}' (z={SURF[i][1]:.1f}) und '{SURF[i+1][0]}' (z={SURF[i+1][1]:.1f})"
    return f"ausserhalb des Systems (z={z:.1f})"


# ────────────────────────────────────────────────────────────────
# Hauptrechnung
# ────────────────────────────────────────────────────────────────

def berechne_antireflexpunkte(filepath, wavelength=None):

    # ── System laden ────────────────────────────────────────────
    lens = load_system(filepath)

    wl = wavelength if wavelength is not None else lens.primary_wavelength
    SURF = extract_surf_list(lens, wl)
    N    = len(SURF)

    stop_idx  = find_stop_index(lens)
    last_surf = find_last_refractive_before_image(SURF)

    print("=" * 72)
    print(f"ANTIREFLEXPUNKTE  --  {filepath}")
    print(f"Wellenlaenge: {wl} µm   |   Apertur-Stop: idx={stop_idx} '{SURF[stop_idx][0]}'")
    print("=" * 72)
    print(f"\nSystem: {N} Flaechen, z = {SURF[0][1]:.1f} .. {SURF[-1][1]:.1f} mm")

    # ── 1. Grenzstrahl-Trace ─────────────────────────────────────
    tr = forward_trace(SURF, y0=0.0, nu0=1.0, start_idx=stop_idx)

    print(f"\n[1]  PARAXIALER GRENZSTRAHL  (y=0 am Stop idx={stop_idx}, n*u=1)")
    print(f"     {'Flaeche':30}  {'z [mm]':>8}  {'y [mm]':>10}  {'n*u':>9}")
    print("     " + "-" * 62)
    for (z, y, nu, n, lbl) in tr:
        mark = "  *** y~0" if abs(y) < 0.8 else ""
        print(f"     {lbl:30}  {z:8.2f}  {y:10.4f}  {nu:9.5f}{mark}")

    zc = zero_crossings(tr)
    print(f"\n     Nulldurchgaenge (Pupillenkonjugate):")
    if zc:
        for zp, l1, l2 in zc:
            print(f"       z = {zp:.2f} mm   {z_region(SURF, zp)}")
    else:
        print("       (keine im abgebildeten Bereich)")

    z_pk = zc[0][0] if zc else None

    # ── 2. Ringblende -> Augenpupille ────────────────────────────
    # Ringblende = erste Flaeche nach Stop mit RadialAperture r_min>0
    # Vereinfacht: zweite Flaeche nach Stop (Index stop_idx+1)
    ring_idx = stop_idx + 1
    z_ring   = SURF[ring_idx][1]

    print(f"\n[2]  RELAY-ABBILDUNG: '{SURF[ring_idx][0]}' (z={z_ring:.1f}mm) -> Augenpupille")
    z_ring_at_eye, m_ring = image_pos(SURF, z_ring, 1.0, i_from=stop_idx+2, i_to=last_surf)
    if z_ring_at_eye is not None:
        z_retina = SURF[-1][1]
        print(f"     Bild der Ringblende:  z = {z_ring_at_eye:.2f} mm")
        print(f"     (Retina bei z={z_retina:.1f}mm -> Abstand {z_retina - z_ring_at_eye:.1f}mm)")
        print(f"     Transversaler Massstab: m = {m_ring:.4f}")
    else:
        z_ring_at_eye = SURF[-1][1] - 17.0   # Fallback: 17mm vor Retina
        print(f"     Kein reelles Bild berechenbar, Fallback z={z_ring_at_eye:.1f}mm")

    # ── 3. Hornhaut-Reflexionsanalyse ────────────────────────────
    print(f"\n[3]  HORNHAUT-REFLEXION  (Standardauge: Hornhaut 24mm vor Retina)")
    R_c  = 7.8
    f_c  = -R_c / 2
    z_c  = SURF[-1][1] - 24.0

    g_c  = z_ring_at_eye - z_c
    b_c  = 1.0 / (1.0/f_c - 1.0/g_c) if abs(g_c) > 1e-6 else None
    print(f"     Hornhaut bei z = {z_c:.1f} mm,  f_mirror = {f_c:.2f} mm")
    print(f"     Objektweite g = {g_c:.2f} mm  ->  Bildweite b = {b_c:.2f} mm")
    z_ghost_c = z_c + b_c
    print(f"     Virtuelle Reflex-Quelle: z = {z_ghost_c:.2f} mm")

    z_dot_c, m_dot_c = image_pos(SURF, z_ghost_c, 1.0, i_from=stop_idx+2, i_to=last_surf)
    if z_dot_c is not None:
        z_lochsp = next((SURF[i][1] for i in range(len(SURF)) if abs(SURF[i][2]) >= 1e20
                         and SURF[i][1] > 50 and SURF[i][1] < SURF[-1][1] - 50), SURF[-1][1])
        in_relay = 0 < z_dot_c < z_lochsp
        print(f"     Konjugat durch Relay+OL: z = {z_dot_c:.2f} mm  |m|={abs(m_dot_c):.2f}"
              f"  {'(IM RELAY - nutzbar!)' if in_relay else '(ausserhalb Relay, nicht direkt zugaenglich)'}")

    # ── 4. OL-Vorderflaechenreflex ───────────────────────────────
    # Letzter Surf mit Brechkraft = OL-Vorderflaehe (letzte Linsenflaeche vor Bild)
    ol_front_idx = last_surf
    while ol_front_idx > 0 and abs(SURF[ol_front_idx][3] - 1.0) < 0.001:
        ol_front_idx -= 1  # laufe rueckwaerts bis zur ersten Glasflaeche

    z_ol   = SURF[ol_front_idx][1]
    R_ol   = SURF[ol_front_idx][2]
    print(f"\n[4]  OL-VORDERFLAECHENREFLEX  '{SURF[ol_front_idx][0]}' z={z_ol:.1f}mm, R={R_ol:.3f}mm")

    if abs(R_ol) < 1e20:
        f_ol = -R_ol / 2
        # Konvergenzpunkt des Buendels kurz vor OL:
        tr_at_ol = next(((z, y, nu, n, l) for (z, y, nu, n, l) in tr if abs(z - z_ol) < 1.0), None)
        if tr_at_ol:
            z_ol_y, y_ol, nu_ol, n_ol, _ = tr_at_ol
            u_ol = nu_ol / 1.0
            if abs(u_ol) > 1e-6:
                z_focus = z_ol - y_ol / u_ol
                g_ol    = z_focus - z_ol
                b_ol    = 1.0 / (1.0/f_ol - 1.0/g_ol) if abs(g_ol) > 1e-6 else None
                z_ghost_ol = z_ol + b_ol
                print(f"     f_mirror={f_ol:.2f}mm, Bündelkonvergenz bei z={z_focus:.1f}mm")
                print(f"     Objektweite g={g_ol:.2f}mm -> Bildweite b={b_ol:.2f}mm")
                print(f"     Virtuelle OL-Ghost-Quelle: z = {z_ghost_ol:.2f} mm")

                relay_last = ol_front_idx - 1
                while relay_last > 0 and abs(SURF[relay_last][2]) >= 1e20:
                    relay_last -= 1
                z_dot_ol, m_dot_ol = image_pos(SURF, z_ghost_ol, 1.0,
                                               i_from=stop_idx+2, i_to=relay_last)
                if z_dot_ol is not None:
                    in_range = 0 < z_dot_ol < z_ol
                    print(f"     Konjugat durch Relay: z = {z_dot_ol:.2f} mm  |m|={abs(m_dot_ol):.3f}"
                          f"  {'(im Relay, nutzbar!)' if in_range else '(virtuell)'}")
    else:
        print("     OL-Vorderflaeche hat kein Brechkraft (R=inf) -- uebersprungen")

    # ── 5. Dot-Groesse ───────────────────────────────────────────
    if z_pk is not None:
        print(f"\n[5]  DOT-GROESSE am Pupillenkonjugat z={z_pk:.2f}mm")

        # ABCD von Ringblende bis Pupillenkonjugat
        # -> Teilsystem bis letzte Flaeche vor z_pk, dann Transfer bis z_pk
        last_before_pk = max(
            (i for i in range(len(SURF)) if SURF[i][1] <= z_pk),
            default=stop_idx
        )
        if last_before_pk > stop_idx + 1:
            M_sub = sysmat(SURF, stop_idx + 2, last_before_pk)
            dz    = z_pk - SURF[last_before_pk][1]
            n_med = SURF[last_before_pk][3]
            T_pk  = np.array([[1, dz / n_med], [0, 1]])
            M_pk  = T_pk @ M_sub
            # Transfer von Ringblende (z_ring) zu erstem Relay-Element:
            T_ring = np.array([[1, (SURF[stop_idx + 2][1] - z_ring) / 1.0], [0, 1]])
            M_full = M_pk @ T_ring
        else:
            M_full = np.eye(2)

        m00 = M_full[0, 0]

        # Ringblenden-Radien aus dem System ermitteln
        ring_surf = lens.surfaces.surfaces[ring_idx]
        ap = ring_surf.aperture
        try:
            r_min = float(ap.r_min)
            r_max = float(ap.r_max)
        except AttributeError:
            try:    # DifferenceAperture: nutze inneren Radius
                r_min = float(ap.b.r_max)
                r_max = float(ap.a.r_max)
            except Exception:
                r_min, r_max = 2.44, 3.60   # Fallback

        ring_at_pk_inner = abs(m00) * r_min
        ring_at_pk_outer = abs(m00) * r_max

        print(f"     Ringblende: r_min={r_min:.2f}mm, r_max={r_max:.2f}mm")
        print(f"     Am Konjugat (Skalierung |M[0,0]|={abs(m00):.3f}):")
        print(f"       Ring-Innenradius: {ring_at_pk_inner:.2f} mm")
        print(f"       Ring-Aussenradius: {ring_at_pk_outer:.2f} mm")
        print(f"     Anti-Reflex-Dot muss kleiner als {ring_at_pk_inner:.1f}mm Radius sein.")
        print(f"     Empfehlung: r_dot ~ {ring_at_pk_inner * 0.4:.1f} .. {ring_at_pk_inner * 0.7:.1f} mm")

    # ── Zusammenfassung ──────────────────────────────────────────
    print()
    print("=" * 72)
    print("ZUSAMMENFASSUNG")
    print("=" * 72)

    if zc:
        print(f"\n  ANTIREFLEXPUNKT 1 (primaer):  z = {zc[0][0]:.1f} mm")
        print(f"    {z_region(SURF, zc[0][0])}")
        if z_pk is not None:
            print(f"    Dot-Radius: r < {ring_at_pk_inner:.1f} mm  (Empfehlung: ~{ring_at_pk_inner*0.5:.1f} mm)")
        for extra in zc[1:]:
            print(f"\n  ANTIREFLEXPUNKT (weiterer):  z = {extra[0]:.1f} mm")
            print(f"    {z_region(SURF, extra[0])}")
    else:
        print("\n  Kein Pupillenkonjugat im Relaybereich gefunden.")

    # Lochspiegel = letzte Planflaeche (R=inf) vor der OL im mittleren Bereich
    lochsp_idx = next(
        (i for i in range(len(SURF)-2, 0, -1)
         if abs(SURF[i][2]) >= 1e20 and SURF[i][1] < SURF[last_surf][1] - 50),
        last_surf - 1
    )
    print(f"\n  ANTIREFLEXPUNKT 2 (sekundaer):")
    print(f"    Am Lochspiegel (letzte Planflaeche vor der OL)")
    print(f"    z = {SURF[lochsp_idx][1]:.1f} mm  ('{SURF[lochsp_idx][0]}')")
    print(f"    (Gleiche DifferenceAperture wie Punkt 1, leicht andere Ghost-Geometrie)")

    print(f"""
  Einbau-Befehl:
    python antireflexpunkte_einbauen.py {filepath} output_mit_arp.json \\
           {ring_at_pk_inner*0.5:.1f} {ring_at_pk_inner*0.5:.1f}
""")


# ────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Verwendung: python antireflexpunkte_berechnung.py SYSTEM.json [wellenlaenge_um]")
        print("Beispiel:   python antireflexpunkte_berechnung.py mein_system.json 0.55")
        sys.exit(1)

    filepath   = sys.argv[1]
    wavelength = float(sys.argv[2]) if len(sys.argv) > 2 else None

    berechne_antireflexpunkte(filepath, wavelength)
