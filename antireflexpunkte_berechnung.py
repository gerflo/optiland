"""
Antireflexpunkte Funduskamera-Beleuchtung
==========================================

Methode:
  Paraxialer Grenzstrahl vom Apertur-Stop (y=0, nu=1).
  Nulldurchgaenge von y(z) = Konjugate der Pupille = Antireflexpunkt-Positionen.

  Zweite Analyse: OL-Vorderflaechenreflex -- virtuelle Ghost-Quelle wird durch
  das Relay (ohne OL) abgebildet; die Position des Abbildes bestimmt Punkt 2.
"""

import sys
import numpy as np
sys.path.insert(0, r'c:\Projekte\Optiland\optiland-code')

# ----------------------------------------------------------------
# Brechungsindizes (Naeherung mit nD, gut fuer paraxiale Analyse)
# ----------------------------------------------------------------
AIR    = 1.0
SBAH11 = 1.6700
NSF10  = 1.7280
NBAF10 = 1.6700
NSK5   = 1.5891

# ----------------------------------------------------------------
# Systemflächen: (label, z_abs, R, n_post)
# ----------------------------------------------------------------
SURF = [
    #   label                    z        R          n_post
    ("Object/LED",              -1.0,    1e30,       AIR    ),   # 0
    ("Stop (LED-Apertur)",       0.0,    1e30,       AIR    ),   # 1  IS_STOP
    ("Ringblende",               2.0,    1e30,       AIR    ),   # 2
    ("Pilzblende",               8.5,    1e30,       AIR    ),   # 3
    ("47634 S1",                10.5,   24.470,      SBAH11 ),   # 4
    ("47634 S2",                21.5,  -16.490,      NSF10  ),   # 5
    ("47634 S3",                24.0, -131.650,      AIR    ),   # 6
    ("47635 S3",                27.0,  152.940,      NSF10  ),   # 7
    ("47635 S2",                29.5,   18.850,      SBAH11 ),   # 8
    ("47635 S1",                39.0,  -27.970,      AIR    ),   # 9
    ("47637 S3",                89.0,  214.630,      NSF10  ),   # 10
    ("47637 S2",                91.5,   21.980,      NBAF10 ),   # 11
    ("47637 S1",               100.5,  -34.530,      AIR    ),   # 12
    ("Lochspiegel",            164.5,    1e30,       AIR    ),   # 13
    ("OL-AS (Asphäre)",        279.0,   28.256,      NSK5   ),   # 14
    ("OL Rückfläche",          297.0,  -69.283,      AIR    ),   # 15
    ("Bild (Retina)",          339.0,    1e30,       AIR    ),   # 16
]
N = len(SURF)

# ----------------------------------------------------------------
# Paraxialer Vorwaerts-Trace
# ----------------------------------------------------------------
def forward_trace(y0, nu0, start_idx=1):
    """Trace [y, n*u] vorwaerts von start_idx bis Ende.
    Gibt Liste von (z, y, nu, n_nach_Brechung) zurueck."""
    n = SURF[start_idx - 1][3] if start_idx > 0 else AIR
    y, nu = y0, nu0
    out = [(SURF[start_idx][1], y, nu, n, SURF[start_idx][0])]

    for i in range(start_idx + 1, N):
        lbl, z, R, n_post = SURF[i]
        z_prev = SURF[i-1][1]
        d = z - z_prev
        y = y + d / n * nu           # Transfer
        if abs(R) < 1e20:            # Brechung
            phi = (n_post - n) / R
            nu = nu - phi * y
        n = n_post
        out.append((z, y, nu, n, lbl))
    return out

def zero_crossings(trace):
    """Findet Nulldurchgaenge (Vorzeichenwechsel) zwischen Flaechen per linearer Interpolation."""
    zeros = []
    for i in range(1, len(trace)):
        z0, y0, nu0, n0, l0 = trace[i-1]
        z1, y1, nu1, n1, l1 = trace[i]
        if y0 * y1 < 0:
            # Zwischen z0 und z1, Medium = n0 (n_post der Flaeche i-1)
            u = nu0 / n0               # Steigung im Medium
            dz = -y0 / u               # y(z0 + dz) = 0
            z_cross = z0 + dz
            zeros.append((z_cross, l0, l1))
    return zeros

# ----------------------------------------------------------------
# ABCD-Systemmatrix fuer Teilsystem [i_from .. i_to]
# ----------------------------------------------------------------
def sysmat(i_from, i_to):
    """2x2 ABCD-Matrix (Zustandsvektor [y, n*u]) von Flaeche i_from bis i_to."""
    n = SURF[i_from - 1][3] if i_from > 0 else AIR
    M = np.eye(2)
    for i in range(i_from, i_to + 1):
        lbl, z, R, n_post = SURF[i]
        if i > i_from:
            d = z - SURF[i-1][1]
            T = np.array([[1, d/n], [0, 1]])
            M = T @ M
        if abs(R) < 1e20:
            phi = (n_post - n) / R
            M = np.array([[1, 0], [-phi, 1]]) @ M
        n = n_post
    return M

def image_pos(z_obj, n_obj, i_from, i_to):
    """Bildposition fuer Objekt bei z_obj durch Teilsystem [i_from..i_to].
    Gibt (z_bild, m_quer) zurueck."""
    z_first = SURF[i_from][1]
    d_obj   = z_first - z_obj        # negativ wenn Objekt rechts der ersten Flaeche
    T_obj   = np.array([[1, d_obj/n_obj], [0, 1]])
    M       = sysmat(i_from, i_to) @ T_obj
    n_img   = SURF[i_to][3]
    A, B, C, D = M[0,0], M[0,1], M[1,0], M[1,1]
    if abs(D) < 1e-14:
        return None, None
    d_img  = -B * n_img / D
    z_bild = SURF[i_to][1] + d_img
    m      = 1.0 / (A + C * d_img / n_img) if abs(A + C*d_img/n_img) > 1e-10 else None
    return z_bild, m

# ================================================================
# HAUPTRECHNUNG
# ================================================================

print("=" * 70)
print("ANTIREFLEXPUNKTE  --  Funduskamera-Beleuchtungsstrahlengang")
print("=" * 70)

# ----------------------------------------------------------------
# 1. Grenzstrahl-Trace vorwaerts: y=0 am Stop (z=0), nu=1
# ----------------------------------------------------------------
tr = forward_trace(0.0, 1.0, start_idx=1)

print("\n[1]  PARAXIALER GRENZSTRAHL  (y=0 am Stop, nu=1)")
print(f"     {'Flaeche':25}  {'z [mm]':>8}  {'y [mm]':>10}  {'n*u':>9}")
print("     " + "-"*56)
for (z, y, nu, n, lbl) in tr:
    mark = "  *** y~0" if abs(y) < 0.8 else ""
    print(f"     {lbl:25}  {z:8.2f}  {y:10.4f}  {nu:9.5f}{mark}")

zc = zero_crossings(tr)
print()
print("     Nulldurchgaenge (= Pupillenkonjugate der Apertur-Stop):")
for zp, l1, l2 in zc:
    print(f"       z = {zp:.2f} mm   (zwischen '{l1}' und '{l2}')")

# Pupillenkonjugat-Position für spätere Nutzung
z_pk = zc[0][0] if zc else None

# ----------------------------------------------------------------
# 2. Wo wird die Ringblende (z=2mm) auf das Auge abgebildet?
# ----------------------------------------------------------------
z_ring_at_eye, m_ring = image_pos(2.0, AIR, i_from=4, i_to=15)

print(f"\n[2]  RELAY-ABBILDUNG: Ringblende (z=2mm) --> Augenpupille")
print(f"     Bild der Ringblende:  z = {z_ring_at_eye:.2f} mm")
print(f"     (Sollte nahe Pupille/Hornhaut liegen; Retina bei z=339 mm)")
print(f"     Transv. Massstab:     m = {m_ring:.4f}")

# ----------------------------------------------------------------
# 3. Hornhaut-Reflexionsanalyse
# ----------------------------------------------------------------
print(f"\n[3]  HORNHAUT-REFLEXION  (Standardauge)")
R_c = 7.8        # mm, Hornhautradius vorn
z_c = 315.0      # mm, Hornhaut-Vertex (24 mm vor Retina)

# Konvexer Spiegel: f_mirror = -R/2 (divergierend)
f_c = -R_c / 2   # = -3.9 mm

# Ring-Bild liegt bei z_ring_at_eye; Objektweite vom Hornhaut-Spiegel:
g_c = z_ring_at_eye - z_c
print(f"     Hornhaut bei z = {z_c} mm,   f_mirror = {f_c:.2f} mm")
print(f"     Objektweite g = {g_c:.2f} mm  (Ring-Bild -> Hornhaut-Spiegel)")

b_c = 1.0 / (1.0/f_c - 1.0/g_c)
z_ghost_c = z_c + b_c
print(f"     Bildweite b   = {b_c:.2f} mm  (negativ = virtuelle Quelle)")
print(f"     Virtuelle Reflex-Quelle:  z = {z_ghost_c:.2f} mm")

# Diese virtuelle Quelle liegt HINTER der OL-Rückfläche (z=297).
# Ihr Bild durch das Gesamtrelay (Flächen 4-15) finden:
z_dot_c, m_dot_c = image_pos(z_ghost_c, AIR, i_from=4, i_to=15)
print(f"\n     Konjugat der Hornhaut-Ghost-Quelle durch Relay+OL:")
print(f"       z = {z_dot_c:.2f} mm   |m| = {abs(m_dot_c):.2f}")
if z_dot_c is not None and 0 < z_dot_c < 170:
    print(f"       --> Liegt IM Relay/vor Lochspiegel: nutzbar als Antireflexpunkt!")
else:
    print(f"       --> Liegt ausserhalb des nutzbaren Bereichs (z<0 oder z>Lochspiegel)")

# ----------------------------------------------------------------
# 4. OL-Vorderflächen-Reflexionsanalyse
# ----------------------------------------------------------------
print(f"\n[4]  OL-VORDERFLAECHEN-REFLEXION  (z=279mm, R=+28.256mm)")

R_ol   = 28.256   # mm, R>0 -> konvex von links -> divergierender Spiegel
f_ol   = -R_ol/2  # = -14.13 mm (konvexer Spiegel, divergierend)
z_ol   = 279.0

# Wo konvergiert das Beleuchtungsbuendel? (Extrapolation des Grenzstrahls)
# Aus dem Trace: y und u direkt vor OL-AS (z=279)
tr_at_ol = next(item for item in tr if abs(item[0]-279.0) < 0.1)
z_ol_y, y_ol, nu_ol, n_ol, _ = tr_at_ol
u_ol = nu_ol / AIR   # n=1 vor der OL-Flaeche
if abs(u_ol) > 1e-6:
    z_focus_beleuch = z_ol - y_ol / u_ol   # wo konvergiert das Buendel
    print(f"     Konvergenzpunkt Beleuchtungsbuendel: z = {z_focus_beleuch:.2f} mm")

    # Virtuelle Quelle nach Reflexion an OL-Vorderflaeche:
    g_ol   = z_focus_beleuch - z_ol
    b_ol   = 1.0 / (1.0/f_ol - 1.0/g_ol) if abs(g_ol) > 1e-6 else None
    z_ghost_ol = z_ol + b_ol
    print(f"     Objektweite g = {g_ol:.2f} mm   Bildweite b = {b_ol:.2f} mm")
    print(f"     Virtuelle OL-Ghost-Quelle:  z = {z_ghost_ol:.2f} mm")

    # Bild durch Relay 4..13 (OHNE OL, da Ghost vor OL entsteht)
    z_dot_ol, m_dot_ol = image_pos(z_ghost_ol, AIR, i_from=4, i_to=13)
    print(f"\n     Konjugat der OL-Ghost-Quelle durch Relay (ohne OL):")
    print(f"       z = {z_dot_ol:.2f} mm   |m| = {abs(m_dot_ol):.3f}")
    if z_dot_ol is not None and 0 < z_dot_ol < 170:
        print(f"       --> Liegt IM Relay: nutzbar als Antireflexpunkt!")
    else:
        print(f"       --> Liegt ausserhalb (z={z_dot_ol:.1f} mm, nur virtuell nutzbar)")

# ----------------------------------------------------------------
# 5. Dot-Groesse am Pupillenkonjugat z_pk
# ----------------------------------------------------------------
print(f"\n[5]  DOT-GROESSE an z = {z_pk:.2f} mm (Pupillenkonjugat)")

# Am Pupillenkonjugat konvergiert der Grenzstrahl auf y=0.
# Die Groesse des blockierten Bereichs haengt von der Ghost-Quelle ab.
# Einfache Naeherung: Ray-Groesse am Konjugat durch Interpolation.
# Die nutzbare Apertur (Ringblende r_min=2.44, r_max=3.6 mm) wird
# mit |m_partial| auf die Konjugat-Ebene abgebildet.

# Teilsystem von Ringblende (idx=2) bis Pupillenkonjugat z_pk:
# Systemmatrix 4..12 plus Transfer bis z_pk
def ray_at_z(z_target):
    """Interpoliert y aus dem Grenzstrahl-Trace an beliebiger z-Position."""
    for i in range(1, len(tr)):
        z0, y0, nu0, n0, _ = tr[i-1]
        z1, y1, nu1, n1, _ = tr[i]
        if z0 <= z_target <= z1:
            return y0 + (z_target - z0) / n0 * nu0, nu0
    return None, None

# Am Pupillenkonjugat ist y~0. Die Ghost-Strahlen haben dort einen bestimmten Radius.
# Der blockierte Radius = |m_relay| * r_ring_min (Ringblende innen = 2.44mm)
r_ring_min = 2.44
r_ring_max = 3.60

# Teilvergroesserung von z=2 bis z_pk:
# Einfach: ratio y_ring/nu_ring am Stop vs. am Konjugat ergibt m ~ kleiner Wert
# Korrekt: nutze die ABCD-Systemmatrix von idx 2 bis z_pk

# Transfer bis kurz vor Lochspiegel (idx 13), dann interpolieren
M_to_lochsp = sysmat(2, 13)
# Nun Transfer bis z_pk (im Freiraum, n=AIR):
dz_pk = z_pk - SURF[13][1]   # negativ (pk liegt links vom Lochspiegel)
T_pk  = np.array([[1, dz_pk/AIR], [0, 1]])
M_pk  = T_pk @ M_to_lochsp

# Systemmatrix fuer ein Objekt am Stop (idx 1, z=0):
# Transfer Stop->Ringblende (2mm), dann M_pk:
T_stop = np.array([[1, 2/AIR], [0, 1]])  # 2mm von Stop zu Ringblende
M_full = M_pk @ T_stop

# Punkt-zu-Punkt-Abbildung: fuer y_obj=r_ring am Ringblende (idx 2)
# Ghost-Bild-Radius am Konjugat:
# Bei y_obj=r_ring_min, u_obj=0 (kollimiert vom Ring, Naeherung):
# [y', nu'] = M_full * [r_ring_min, 0]
y_pk_min = M_full[0,0] * r_ring_min + M_full[0,1] * 0
y_pk_max = M_full[0,0] * r_ring_max + M_full[0,1] * 0
print(f"     (Naeherung: kollimiert von Ringblende, Massstab M[0,0] = {M_full[0,0]:.4f})")
print(f"     Ringblende r_min={r_ring_min}mm --> am Konjugat: r = {abs(y_pk_min):.3f} mm")
print(f"     Ringblende r_max={r_ring_max}mm --> am Konjugat: r = {abs(y_pk_max):.3f} mm")
print(f"     Empfohlener Absorptionspunkt-Radius: {abs(y_pk_min):.2f} .. {abs(y_pk_max):.2f} mm")

# ----------------------------------------------------------------
# 6. ZUSAMMENFASSUNG
# ----------------------------------------------------------------
print()
print("=" * 70)
print("ZUSAMMENFASSUNG")
print("=" * 70)
print(f"""
Grundprinzip (Koehler-Beleuchtung):
  Die Ringblende (z=2mm) ist konjugiert zur Augenpupille.
  Der zentrale Reflex entsteht durch Rueckwaertsstreuung an Hornhaut und OL.
  Antireflexpunkte blockieren diese Geisterstrahlen an ihren Fokus-Ebenen
  im Beleuchtungsrelay = den Pupillenkonjugat-Ebenen.

Pupillenkonjugat-Ebene(n) der Apertur-Stop im Beleuchtungsrelay:
  --> z = {z_pk:.2f} mm   (zwischen '47637 S1' bei z=100.5mm und
                              'Lochspiegel' bei z=164.5mm)
  Physischer Ort: ca. {z_pk-100.5:.0f} mm nach dem letzten Relay-Element (47637)
                  = ca. {164.5-z_pk:.0f} mm VOR dem Lochspiegel

Empfehlung fuer zwei Antireflexpunkte:

  PUNKT 1  (primaer, Hornhaut-Reflex):
    Position: z ≈ {z_pk:.1f} mm
    Ort:      freie Strecke zwischen 47637 und Lochspiegel
    Ausfueh.: schwarzer Absorptionsdot auf planparalleler Glasplatte
              (oder direkt auf der Lochspiegelflaeche, z=164.5mm)

  PUNKT 2  (sekundaer, OL-Vorderflaechenreflex):
    Virtueller Ghost bei z={z_ghost_ol:.1f}mm hat kein reelles Konjugat
    im Relay-Bereich (Konjugat bei z={z_dot_ol:.0f}mm, nicht nutzbar).
    --> Praxis: zweiten Dot ebenfalls nahe z={z_pk:.0f}mm, aber mit
        anderem Radius fuer den OL-Ghost-Winkel.
    --> Oder: Lochspiegel selbst als zweites Antireflexelement nutzen
        (Pilzblende z=8.5mm blockiert bereits die Source-Seite).

  DOT-RADIUS am Pupillenkonjugat z={z_pk:.1f}mm:
    Empfohlen: r ≈ {abs(y_pk_min):.2f} mm (aus Ringblende r_min={r_ring_min}mm)
    bis        r ≈ {abs(y_pk_max):.2f} mm (aus Ringblende r_max={r_ring_max}mm)
    --> Typisch: Dot-Durchmesser ≈ {2*abs(y_pk_min):.1f} .. {2*abs(y_pk_max):.1f} mm

Berechnungsweg:
  1. Paraxialen Grenzstrahl von Stop-Mitte (y=0, n*u=1) durch alle
     Flaechen verfolgen (Transfer + Brechung mit ABCD-Matrizen).
  2. Nulldurchgang = Pupillenkonjugat = Antireflexpunkt-Position.
  3. Dot-Groesse: ABCD-Systemmatrix von Ringblende bis Konjugat,
     angewendet auf den inneren/aeusseren Ringradius.
""")
