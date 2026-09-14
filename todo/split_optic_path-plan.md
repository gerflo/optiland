# Multi-Path Optics - Strahlenteiler / Beam Splitter

Status: erneut gegen die Codebasis am 2026-09-11 geprueft, HEAD `7b59f229`.
Die nachfolgenden offenen Punkte sind ein Implementierungsplan, keine bereits
umgesetzten Erweiterungen.

Ziel: Beleuchtung von der Seite und Abbildung in Transmission sowie die
Aufteilung eines gemeinsamen Eingangsbuendels an einem Strahlenteiler.
Unabhaengige Quellen und das Splitten eines einzelnen Buendels sind
unterschiedliche Anforderungen und muessen getrennt nachgewiesen werden.

**Wesentliche Korrektur:** Die Codebasis besitzt inzwischen benannte
sequentielle Routen und einen nichtsequentiellen Tracer mit Strahlteilung.
Eine neue Pfadverwaltung in `SurfaceGroup` und ein neuer
`BeamSplitterInteractionModel` sind daher nicht mehr der automatische
erste Schritt. Zuerst vorhandene APIs nutzen und die verbleibenden Luecken
gezielt schliessen. `Optic.trace()` bleibt rueckwaertskompatibel.

## 1. Verifizierter Bestand

- [x] `Optic.add_sequence(name, steps)` erzeugt ein `SequencedOptic` und
      registriert es in `optic.sequences`.
      Schritte erlauben Surface-Indizes und Overrides wie `(1, "reflect")`
      oder `(1, "refract")`.
- [x] `optiland/sequences/surface_view.py` stellt pro Flaechenbesuch eigene
      Records und einen angepassten Material-/Interaction-Kontext bereit.
      Geometrie und weitere physische Flaecheneigenschaften werden geteilt.
      Wiederholte Besuche muessen deshalb nicht mehr durch neue globale
      Surface-Record-Felder erfunden werden.
- [x] `OpticSerializer` speichert benannte Routen bereits im optionalen
      Top-Level-Feld `sequences` und stellt sie beim Laden wieder her.
- [x] `NSQScene` in `optiland/nonsequential/scene.py` unterstuetzt mehrere
      Quellen, Komponenten und Detektoren. Die physische Trefferreihenfolge
      ergibt sich aus der Geometrie.
- [x] `RefractiveComponent` kann mit
      `SimpleCoating(transmittance=T, reflectance=R)` als idealisierte
      teilreflektierende Grenzflaeche dienen. Ohne Coating wird unpolarisiertes
      Fresnel-R/T verwendet.
- [x] `SamplingPolicy` unterstuetzt importance-gewichtete Branch-Auswahl
      sowie begrenztes echtes Splitting im NumPy-Backend.
      `reflect_prob` steuert die Sampling-Wahrscheinlichkeit, nicht das
      physische Reflexionsvermoegen.
- [x] NSQ-Ergebnisse enthalten getrennte Detektorergebnisse und optional
      `ray_paths["events"]`. `scene.view(result)` und
      `scene.view3d(result)` sind bereits vorhanden.
- [x] NSQ besitzt eigene JSON-Serialisierung und den Konverter
      `sequential_to_nonsequential` mit einem Bericht ueber Einschraenkungen.
- [x] `optiland/paraxial_path.py` modelliert bereits einen gefalteten
      paraxialen Einzelpfad mit Richtungs-/Koordinatenkontext und
      Domaenenpruefungen. Das ist kein Verzweigungsgraph.

Diese Haken bestaetigen vorhandene Bausteine, nicht die vollstaendige
Erfuellung des Zielsystems.

## 2. Architekturentscheidung

| Anforderung | Vorhandener Ansatz | Verbleibende Grenze |
| --- | --- | --- |
| Explizite Route durch vorhandene Flaechen | `Optic.add_sequence()` | Ein einzelner Trace verfolgt nur diese Route; keine gemeinsame Verzweigung |
| Mehrere unabhaengige Quellen/Detektoren | `NSQScene` | Nicht automatisch sequentielle Abbildungsanalyse oder eigenes Ray-Aiming pro Arm |
| Inkohaerente Leistungsteilung | NSQ + `RefractiveComponent` + Coating | Numerikbefund in Abschnitt 3; keine Polarisation |
| Beide Kinder jedes Eingangsstrahls verfolgen | NSQ mit `split_depth > 0` | Nur NumPy, begrenzt durch Tiefe und Budget |
| Deterministisches Splitting mit Torch | Noch nicht vorhanden | Torch warnt bei `split_depth > 0` und verwendet stochastische Auswahl |
| OPD/Jones-Zustand je deterministischem Arm | Sequentielle Rays als Ausgangspunkt | Branch-Ausfuehrung, Zustandskopien und Coating-Semantik fehlen |
| Kohaerente Rekombination/Interferenz | Kein hier nachgewiesener Ansatz | Nicht Bestandteil der ersten Stufe |

Empfohlener Ausgangspunkt ist ein NSQ-Referenzaufbau fuer den inkohaerenten
Beleuchtungsfall. Benannte Sequenzen dienen separat zur Beschreibung
ausgewaehlter sequentieller Routen.

Nur wenn deterministische Torch-Branches, OPD/Polarisation oder die
Anbindung an sequentielle Analysen zwingend sind, eine zusaetzliche
Branch-Ausfuehrungs-API planen. Vor einem solchen Core-Umbau die
Architekturentscheidung abstimmen. Dabei:

- `Optic.trace()` und `SurfaceGroup.trace()` behalten ihr
  Single-Path-Verhalten und ihre bisherigen Rueckgabevertraege.
- `trace_paths()` / `trace_generic_paths()` sind moegliche neue APIs,
  aber noch keine beschlossene oder vorhandene Schnittstelle.
- Keine parallele `OpticalPath.surface_indices`-Verwaltung neben
  `SequenceStep`, Resolver und `optic.sequences` ohne nachgewiesenen Bedarf.
- Physische Interaktion liefert Ausgaenge wie Reflexion/Transmission.
  Die Zuordnung dieser Ausgaenge zu benannten Routen gehoert in die
  Pfadausfuehrung, nicht in das Coating oder die Materialdefinition.
- Ein reines `dict[str, RealRays]` genuegt eventuell fuer Endbuendel,
  ersetzt aber weder Zwischenrecords noch Herkunft und Verzweigungsstruktur.

## 3. Verbleibende Grenzen und Befunde

### Numerik: reproduzierbare Mehrfachtreffer unter Torch float32

Ein kleiner Referenzaufbau funktioniert bereits mit vorhandenen APIs:
1 W kollimiertes Licht entlang +z, eine um 45 Grad um y gedrehte
50:50-Grenzflaeche bei z=10, Vakuum auf beiden Seiten, je ein Detektor
im transmittierten und reflektierten Arm.

Bei 2.048 Eingangsstrahlen und Seed 7 wurden folgende Werte gemessen:

| Backend / Praezision | Sampling | Transmission [W] | Reflexion [W] | Strahlen mit mehrfachem Splitter-Treffer |
| --- | --- | --- | --- | --- |
| NumPy / float64 | `split_depth=1` | 0.500000 | 0.500000 | Nicht ausgewertet |
| NumPy / float64 | `split_depth=0` | 0.500977 | 0.499023 | 0 |
| Torch / float64 | `split_depth=0` | 0.500977 | 0.499023 | 0 |
| Torch / float32 | `split_depth=0` | 0.404297 | 0.595703 | 1.011 |

Im letzten Fall wurden insgesamt 3.976 Splitter-Treffer erfasst, maximal
12 fuer denselben Strahl. Dieser einfache Aufbau erlaubt physisch nur
einen Besuch der Splitter-Ebene pro Strahl. Die Abweichung ist daher nicht
nur durch Monte-Carlo-Streuung erklaert. Die Summe der Detektorleistungen
bleibt trotzdem etwa 1 W: Ein reiner Energieerhaltungstest entdeckt den
Fehler nicht.

- [ ] Ursache der Mehrfachtreffer untersuchen, insbesondere
      Trefferabstand/Origin-Offset und Praezisionsabhaengigkeit.
      Dies ist eine Arbeitshypothese, noch kein nachgewiesener Root Cause.
- [ ] Regression mit identischer Szene fuer NumPy/Torch und expliziten
      float32-/float64-Einstellungen aufnehmen.
- [ ] Pro Strahl maximal einen Splitter-Treffer und korrekte
      Detektorverteilung pruefen, nicht nur die Gesamtleistung.
- [ ] Keine Toleranzen aufweiten, um diese Abweichung zu akzeptieren.

### Medien und Flaechenbesuche

`SurfaceView` und `resolve_view_materials()` loesen bereits einen Teil des
frueher beschriebenen `previous_surface`-Problems. Sie stellen je Besuch
einen eigenen Materialkontext her. Der Resolver wechselt die
Rueckwaertsrichtung nach Reflexionen; diese Reflexionsparitaet ersetzt
keine allgemeine geometrische Vorder-/Rueckseitenbestimmung fuer beliebige
seitliche 3D-Arme.

- [ ] Materialzuordnung fuer beide Anstrahlrichtungen und wiederholte
      Flaechenbesuche testen; vorhandenen View-/Resolver-Ansatz nutzen.
- [ ] Bei reflektierten Views physische Medien des Coatings von dem Medium
      unterscheiden, in dem der reflektierte Strahl weiterlaeuft.
      `SurfaceView._rebind_coating()` bindet Fresnel-/ThinFilm-Coatings neu;
      insbesondere bei `material_post == material_pre` durch Reflexion
      muss die korrekte Grenzflaechenphysik gezielt geprueft werden.
- [ ] Bei NSQ `material_front`/`material_back`, geometrische Normale und
      den aktuellen Strahl-Mediumzustand verwenden. Der diagnostische
      `medium_stack` ist nicht die Quelle fuer die Brechungsindizes.
- [ ] Festlegen, wie Sequenzen nach Hinzufuegen/Entfernen von Flaechen
      aktualisiert oder ungueltig werden. Die Views werden aktuell bei
      Erstellung aufgeloest; rohe Indizes werden nicht automatisch remapped.

### Leistung, Polarisation und Differenzierbarkeit

- [ ] Fuer ein passives konstantes R/T-Modell endliche Koeffizienten mit
      `R >= 0`, `T >= 0`, `R + T <= 1` verlangen.
      `R + T == 1` gilt nur im explizit verlustfreien Fall.
- [ ] Exakte deterministische Teilung und statistische Schaetzung getrennt
      testen. Unter Roulette muessen Gewichte und Erwartungswerte stimmen;
      nicht jeder endliche Lauf liefert exakt die Sollverteilung.
- [ ] NumPy-Splitting ist begrenzt: `split_depth` zaehlt Interaktionstiefe,
      `split_budget` begrenzt die lebenden Strahlen relativ zu `batch_size`
      (Default 4.0). Beim Budgetlimit faellt die Ausfuehrung auf Roulette
      zurueck. Daher nicht uneingeschraenkt als deterministisch bezeichnen.
- [ ] Absorption bis zur Flaeche, Apertur-Clipping, Coating-Verlust und
      Branch-Gewichtung jeweils genau einmal beruecksichtigen.
- [ ] Totalreflexion explizit behandeln, bevor ein ungueltiger
      Transmissionsstrahl erzeugt wird. Einfach beide mutierenden Methoden
      `reflect()`/`refract()` aufzurufen ist kein vollstaendiges Modell.
- [ ] NSQ hat derzeit keinen Jones-/OPD-Zustand und weist polarisierte
      Coatings zurueck. Keine Polarisation oder Interferenz versprechen.
- [ ] `RefractiveComponent` wandelt die verwendeten einfachen
      Coating-Koeffizienten in Python-`float` um. Torch-Ausfuehrung bedeutet
      hier nicht automatisch Gradienten bezueglich R/T.
- [ ] Fuer eine spaetere sequentielle polarisierte Erweiterung
      `p`, `_i0` und die Polarisationsbasis beachten.
      Nur `rays.i *= R` ist unzureichend, weil `update_intensity()`
      Intensitaet aus dem Polarisationszustand neu berechnet.
      Coatings pro Ausgang explizit reflektierend/transmittierend anwenden;
      keine doppelte Skalierung durch Split-Ratio und Coating.

### Records und Pfadidentitaet

NSQ-Ereignisse enthalten `ray_id`, `event_type`, Position, Richtung,
`flux`, `wavelength`, `bounce` und `component_name`. Beim Splitting
erhalten Kinder eigene Ray-IDs, aber das Ereignisschema enthaelt derzeit
keine explizite Eltern-ID oder semantische Path-ID.

- [ ] Fuer einen vollstaendigen Branch-Baum Herkunft/Split-Ereignis
      definieren; unterschiedliche Ray-IDs allein verknuepfen die Kinder
      nicht mit dem gemeinsamen Eingangsweg.
- [ ] Benannte Sollrouten, tatsaechlich aufgetretene Trefferfolgen und
      Detektorergebnisse nicht als dieselbe Pfadidentitaet behandeln.
- [ ] Begrenztes `record_paths`-Sampling dient der Diagnose/Visualisierung,
      nicht der vollstaendigen Leistungsbilanz.
- [ ] Diagnose-/Plot-Records nicht versehentlich als differenzierbare
      Ergebnisdaten behandeln.

## 4. Falls sequentielle Branch-Ausfuehrung erforderlich bleibt

Die folgenden Integrationsstellen ersetzen die inzwischen veralteten
direkten Eingriffe des vorherigen Plans. Erst nach der Entscheidung in
Abschnitt 2 implementieren.

### Ray-Zustand und Interaktion

- [ ] `RealRays.copy()`/`clone()` fehlt weiterhin. Nur fuer die
      sequentielle Erweiterung als Voraussetzung einfuehren, nicht fuer
      den bereits vorhandenen NSQ-Prototyp.
- [ ] Alle vorhandenen Zustandsarrays unabhaengig kopieren:
      `x, y, z, L, M, N, i, w, opd`, optionale
      `L0, M0, N0` und `is_normalized`.
      Bei `PolarizedRays` zusaetzlich `p, _i0, _L0, _M0, _N0`.
- [ ] `be.copy()` nutzen. Der aktuelle Torch-Helper liegt in
      `optiland/backend/torch_backend/indexing.py` und verwendet
      `clone()`, nicht `detach()`. Aliasingfreiheit und Gradientenfluss
      getrennt pruefen.
- [ ] NSQ-`NSQRayBundle.select()`/`concat()` sind kein Ersatz fuer
      einen vollstaendigen backend-agnostischen `RealRays`-Clone.
- [ ] Neue Interaktionen ueber
      `InteractionModelFactory.register(name, builder)` registrieren.
      Die Factory ist inzwischen registry-basiert.
- [ ] `SurfaceFactory` und `SurfaceParameters` mitpruefen:
      Neue Interaction-Parameter werden nicht automatisch durchgereicht;
      aktuell existieren spezielle Weiterleitungen fuer
      `focal_length` und `phase_profile`.
- [ ] Fuer spezialisierte Deserialisierung den vorhandenen Hook
      `BaseInteractionModel._deserialize_init_data()` verwenden.
      Der generische `from_dict()` ruft diesen bereits fuer Subklassen auf;
      keinen zweiten allgemeinen Deserialisierungsmechanismus einfuehren.

### Koordinaten, Ausfuehrung und Endzustand

- [ ] `Surface.trace(rays, record=True)` delegiert inzwischen an
      `_TracingCoordinator` in `standard_surface.py`.
      Dort liegen Reset, Lokalisierung, Dispatch, Globalisierung und
      optionales Recording. Alle Branches muessen denselben korrekten
      lokalen/globalen Uebergang durchlaufen.
- [ ] `SurfaceGroup.trace()` und `SequencedSurfaceGroup.trace()`
      verlassen sich auf Mutation und ignorieren Surface-Rueckgaben.
      Ein `RaySplit`-Rueckgabewert allein erzeugt keine Verzweigung.
- [ ] Vorhandene `SurfaceView`-Records pro Besuch wiederverwenden.
      Wiederholte Aufrufe resetten Records; gemeinsame Prefixe und
      Branches benoetigen einen Trace-eigenen Record-Lebenszyklus,
      damit kein Arm den anderen ueberschreibt.
- [ ] `record=False` des Standard-Tracers erhalten. Sequenzen reichen
      derzeit keinen entsprechenden Record-Schalter durch.
- [ ] Einen gemeinsamen Eingang bis zur Verzweigung nur einmal propagieren.
      Mehrfaches unabhaengiges `sequence.trace()` ist kein Nachweis fuer
      die Verzweigung desselben Ray-Zustands.
- [ ] Spezialverhalten von `ObjectSurface` und `ImageSurface` erhalten;
      Views dispatchen bereits nach dem Typ ihrer Basisflaeche.
- [ ] Terminierung pro Arm explizit definieren.
      `RealRayTracer` propagiert nach dem Surface-Trace noch um die letzte
      Thickness; `SequencedOptic.trace()` tut dies nicht zusaetzlich.
      Ein identisches Verhalten darf nicht still vorausgesetzt werden.
- [ ] Polarisationsupdate und Endrecords konsistent halten.
      Die alte Zuweisung
      `self.optic.surfaces.intensity[-1, :] = rays.i`
      ist im aktuellen `RealRayTracer` nicht mehr vorhanden.
- [ ] Vorhandene `be.no_grad_unless_enabled()`-Semantik respektieren;
      Torch-Tests muessen den benoetigten Gradientenmodus explizit setzen.

## 5. Paraxiale Analyse und Ray-Aiming

`ParaxialRayTracer.trace_generic()` und die Transfermatrixberechnung
verwenden eigene skalare Berechnungen mit
`ParaxialRayTracer.prepare_scalar_sequence()` und `ParaxialPath`. Ein
`interact_paraxial_rays()`-Stub schuetzt diese Wege nicht.

- [ ] Vorhandene `ParaxialPath`-Validierung und
      `UnsupportedParaxialGeometryError`/`ParaxialDomainWarning` nutzen.
      Einzelpfad, gefalteter Nominalpfad und Verzweigungsgraph unterscheiden.
- [ ] Nicht pauschal jede Optik mit benannten Sequenzen fuer paraxiale
      Berechnungen sperren. Bereits unterstuetzte Nominalpfade erhalten.
- [ ] `SequencedOptic` delegiert Apertur, Felder, Wellenlaengen,
      Paraxialmodell und Ray-Generierung an die Basisoptik.
      Ein eigener Eingang/Paraxialkontext pro Arm ist noch nicht vorhanden.
- [ ] Die High-Level-Ray-Generierung verwendet standardmaessig paraxiales
      Ray-Aiming. Ein globales Paraxial-Verbot kann deshalb auch
      `trace()` fuer reale Strahlen verhindern.
      Einen gueltigen nominalen Aiming-Kontext oder eine explizite
      Eingangsrays-API vorsehen; `trace_generic()` ist nicht pauschal
      eine freie Rohstrahl-Schnittstelle.
- [ ] Analyse je Arm nur fuer tatsaechlich unterstuetzte Kontexte anbieten.
      NSQ-Detektorleistung ist kein Ersatz fuer sequentielle
      First-Order-, OPD- oder Abbildungsanalyse.

## 6. Persistenz, GUI und Visualisierung

- [ ] Bestehendes optionales `sequences`-JSON-Feld des `OpticSerializer`
      erhalten. Keine zweite unversionierte Routenliste unter
      `surface_group.paths` einfuehren.
- [ ] NSQ-JSON bleibt ein eigenes Szenenformat
      (`nsq_schema_version=1`), kein automatischer Teil von Optic-JSON.
      Aktuell werden Simulationsergebnisse und Autograd-Zustand nicht als
      vollstaendiger Sitzungszustand persistiert.
- [ ] Roundtrips gezielt fuer Coatings, Sampling-Policy, Quellen, Medien,
      Detektoren und gegebenenfalls neue Branch-Verknuepfungen pruefen.
      Vorhandene Serialisierung nicht ungeprueft als lueckenlos annehmen.
- [ ] `sequential_to_nonsequential` und seinen Konvertierungsbericht
      nutzen. Insbesondere Polarisation, unbeschichtete
      Fresnel-Verluste und Geometriegrenzen verhindern einen allgemein
      verlustlosen Austausch.
- [ ] GUI erst nach stabiler Core-Nutzung erweitern. Der aktuelle
      Connector und seine Snapshots arbeiten mit `Optic`;
      NSQ benoetigt eine ausdrueckliche Dokument-/Service-Anbindung,
      nicht nur ein weiteres Dropdown.
- [ ] Geometrie und Interaktion getrennt behandeln:
      `beam_splitter` nicht einfach als Geometry-Typ aufnehmen.
      Eine `SurfaceService._get_interaction_type()`-Methode existiert
      weiterhin nicht. GeometryRegistry und die Validierung beim
      Typwechsel gemeinsam pruefen.
- [ ] Vorhandene `_capture_optic_state()`/`_restore_optic_state()` fuer
      sequentielle Aenderungen nutzen; fuer NSQ Undo/Redo und Persistenz
      separat anbinden. Lange Traces nicht auf dem GUI-Thread ausfuehren.
- [ ] Angrenzender GUI-Befund: `_set_material_data()` setzt weiterhin
      `surface.is_reflective` statt
      `surface.interaction_model.is_reflective`.
      Vor einer neuen Interaction-UI gezielt korrigieren und testen,
      nicht in dieser Planpruefung nebenbei Source-Code aendern.
- [ ] NSQ-Viewer in `optiland/nonsequential/visualization/`
      wiederverwenden. Die sequentiellen Viewer lesen weiter
      rechteckige Surface-Arrays; gemeinsame Darstellung mehrerer
      Sequenzen/Branches ist eine gesonderte Erweiterung.
- [ ] Fuer Pfaddarstellung variable Laengen, Herkunft und unvollstaendige
      Ereignisaufzeichnung beruecksichtigen; keinen rechteckigen
      `[num_surfaces, num_rays]`-Stack erzwingen.

## 7. Korrigierte Implementierungsfolge

1. [ ] NSQ-Referenzfall mit einer Quelle, 45-Grad-Splitter und zwei
       Detektoren als gezielten Test/Beispiel festhalten.
       Den float32-Mehrfachtreffer aus Abschnitt 3 untersuchen und beheben.
2. [ ] Den eigentlichen Beleuchtungs-/Abbildungsaufbau mit getrennten
       Eintrittsarmen aufbauen; benoetigte Ergebnisarten festlegen.
       Mehrere Quellen nicht mit deterministischen Kindern verwechseln.
3. [ ] Anhand dieses Aufbaus entscheiden, welche Anforderungen NSQ und
       benannte Sequenzen nicht abdecken. Insbesondere Torch-Splitting,
       Polarisation/OPD und arm-spezifische Analyse getrennt priorisieren.
4. [ ] Nur die erforderlichen Luecken implementieren:
       bevorzugt vorhandene NSQ-/Sequence-Bausteine erweitern;
       einen neuen sequentiellen Branch-Tracer nur nach Architekturfreigabe.
5. [ ] Persistenz, Record-Herkunft, Mediumkontext und Analysegrenzen
       waehrend der Implementierung absichern.
6. [ ] Bestehende Viewer erweitern und erst danach die passende
       GUI-Dokument-/Service-Anbindung hinzufuegen.
7. [ ] Vorhandene Entwicklerdokumentation
       `docs/developers_guide/sequences_framework.rst`,
       `docs/developers_guide/nonsequential_raytracing.rst`,
       `docs/gallery/nonsequential/` und
       `docs/examples/Tutorial_10a_Non_Sequential_and_Illumination.ipynb`
       aktualisieren. Ein neues Tutorial oder `agents.md`-Update ist
       keine technische Voraussetzung.
       Changelog/Google-Docstrings fuer tatsaechlich implementierte APIs
       ergaenzen; kein Interferenzbeispiel ohne kohaerentes Modell.

Tests laufen phasenbegleitend, nicht erst nach GUI und Dokumentation.

## 8. Abnahmetests

- [ ] Bestehende `tests/sequences/` und `tests/nonsequential/`
      gezielt erweitern, bevor parallele neue Teststrukturen entstehen.
- [ ] Physische Richtungen und Medien: 45-Grad-Splitter, beide Seiten,
      Brechung, Reflexion, Totalreflexion und wiederholte Besuche.
- [ ] R/T-Randwerte 0 und 1, verlustbehaftete Coatings, ungueltige
      Koeffizienten sowie Absorption/Aperturverluste.
- [ ] Deterministische NumPy-Teilung innerhalb des Budgets, Roulette
      am Budgetlimit und explizite Torch-Warnung bei `split_depth > 0`.
- [ ] Statistische Tests mit begruendeten Konfidenzgrenzen und Seeds;
      keine exakten 50:50-Counts von Roulette verlangen.
- [ ] NumPy/Torch mit `set_test_backend` und zusaetzlich explizit
      float32/float64 testen. Das vorhandene Fixture verwendet fuer Torch
      float64 und deckt den dokumentierten float32-Befund nicht ab.
- [ ] Records/Herkunft, keine unphysikalischen Selbsttreffer,
      unterschiedliche Armlaengen und wiederholte Traces.
- [ ] Bei neuen Ray-Kopien Aliasingfreiheit und Gradientenfluss,
      bei Polarisationsunterstuetzung Jones-/Intensitaetskonsistenz.
- [ ] Legacy-Trace, `record=False`, Endpropagation, Ray-Aiming und
      unterstuetzte paraxiale Nominalpfade bleiben unveraendert.
- [ ] Alte Optic-Dateien ohne `sequences`, Sequence-Roundtrips und
      NSQ-Roundtrips getrennt pruefen.
- [ ] GUI-/Undo-Tests erst fuer die tatsaechlich gewaehlte Integration.
      Keine globale Testsuite blind starten und keine Toleranzen lockern.

## 9. Pruefnachweis dieser Revision

Ausgefuehrt:

```powershell
.venv\Scripts\python.exe -m pytest -q tests/sequences/test_sequenced_optic.py tests/sequences/test_surface_view.py tests/nonsequential/test_nsq_coatings.py tests/nonsequential/test_nsq_sampling_policy.py
```

Ergebnis: **57 passed, 2 warnings**. Warnungen: Torch-Tensor mit
`requires_grad` wird in einem Sequence-Test zu einem Skalar konvertiert;
Pytest konnte seinen Cache wegen fehlender Schreibberechtigung nicht
aktualisieren. Kein Testfehler.

Zusaetzlich wurde der Referenzaufbau aus Abschnitt 3 mit NumPy und Torch
ausgefuehrt. Folgender eigenstaendig ausfuehrbarer Aufbau reproduziert
die drei Roulette-Zeilen der Tabelle und zaehlt Mehrfachtreffer:

```python
import math

import numpy as np

import optiland.backend as be
from optiland.coatings import SimpleCoating
from optiland.coordinate_system import CoordinateSystem
from optiland.nonsequential import (
    VACUUM,
    CollimatedSourceConfig,
    IrradianceDetectorConfig,
    NSQScene,
    RefractiveComponent,
    Spectrum,
)
from optiland.nonsequential.components.geometry.analytic.plane import (
    FinitePlaneGeometry,
)

for backend, precision in [
    ("numpy", "float64"),
    ("torch", "float64"),
    ("torch", "float32"),
]:
    be.set_backend(backend)
    be.set_precision(precision)
    scene = NSQScene()
    scene.add_source(
        "source",
        CoordinateSystem(),
        CollimatedSourceConfig(
            spectrum=Spectrum.monochromatic(0.55),
            total_flux=1.0,
            aperture_radius=1.0,
        ),
    )
    scene.add_component(
        "splitter",
        RefractiveComponent(
            cs=CoordinateSystem(z=10, ry=math.pi / 4),
            geometry=FinitePlaneGeometry(aperture_radius=5),
            material_front=VACUUM,
            material_back=VACUUM,
            coating=SimpleCoating(transmittance=0.5, reflectance=0.5),
            name="splitter",
        ),
    )
    for name, cs in [
        ("transmitted", CoordinateSystem(z=20)),
        ("reflected", CoordinateSystem(x=-10, z=10, ry=math.pi / 2)),
    ]:
        scene.add_detector(
            name,
            cs,
            IrradianceDetectorConfig(
                width=10, height=10, num_pixels_x=8, num_pixels_y=8
            ),
        )
    result = scene.trace(num_rays=2048, seed=7, record_paths=True)
    events = result.ray_paths["events"]
    hits = events[
        (events["component_name"] == "splitter")
        & (events["event_type"] == "hit")
    ]
    _, counts = np.unique(hits["ray_id"], return_counts=True)
    print(
        backend,
        precision,
        result.detectors["transmitted"].total_flux,
        result.detectors["reflected"].total_flux,
        len(hits),
        np.count_nonzero(counts > 1),
        counts.max(),
    )
```

Fuer den deterministischen NumPy-Vergleich vor `scene.trace()` zusaetzlich
`scene.sampling_policy = SamplingPolicy(split_depth=1)` setzen;
`SamplingPolicy` liegt in `optiland.nonsequential.ir.scene_ir`.
Das Beispiel in einem separaten Prozess ausfuehren; kuenftige Tests muessen
Backend und Praezision ueber ihre Fixtures wiederherstellen.

Diese Revision aendert nur den Plan. Der dokumentierte Numerikbefund und
die offenen Implementierungspunkte sind noch nicht behoben.
