# Multi-Path Optics - Strahlenteiler / Beam Splitter

Status: umgesetzt am 2026-09-17 auf dem Branch `feat/beam-splitter-paths`
(Basis `237c1ac9`). Die Revision vom 2026-09-11 (HEAD `7b59f229`) war ein
Implementierungsplan; dieser Stand dokumentiert, was davon realisiert wurde,
welche Entscheidungen getroffen wurden und was bewusst offen bleibt.

Ziel: Beleuchtung von der Seite und Abbildung in Transmission sowie die
Aufteilung eines gemeinsamen Eingangsbuendels an einem Strahlenteiler.
Unabhaengige Quellen und das Splitten eines einzelnen Buendels sind
unterschiedliche Anforderungen und wurden getrennt nachgewiesen
(`tests/nonsequential/test_nsq_beam_splitter.py` bzw.
`tests/nonsequential/test_nsq_side_illumination.py`).

## 0. Ergebnis in Kuerze

| Anforderung | Umsetzung | Nachweis |
| --- | --- | --- |
| Ein Buendel in zwei Arme teilen | `optiland.samples.nonsequential.beam_splitter_scene()`; NSQ `RefractiveComponent` + `SimpleCoating` | 21 Tests, NumPy/Torch x float64/float32 |
| Beleuchtung von der Seite, Abbildung in Transmission | `side_illumination_transmission_scene()`: zwei unabhaengige Quellen an einem 45-Grad-Splitter, Linse, Kamera in der paraxialen Bildebene | 13 Tests, Armleistungen exakt, Arme bleiben getrennt |
| float32-Mehrfachtreffer (Abschnitt 3 der Vorrevision) | Ursache: fester Selbsttreffer-Schutz 1e-9 mm; behoben durch skalen- und praezisionsabhaengigen Origin-Offset | Pre-Fix im Worktree: 4 Tests rot, danach gruen; Torch float32 = float64 strahlgenau |
| Herkunft der Kinder beim Splitting | `"split"`-Ereignis mit `parent_id`; Kinder folgen dem Root-Strahl beim Subset-Recording; Null-Fluss-Kinder (TIR) werden nicht erzeugt | `test_nsq_split_provenance.py` |
| Passives R/T-Modell | `R, T` endlich, `>= 0`, `R + T <= 1` bei Konstruktion; Tensor-Koeffizienten bleiben differenzierbar | `test_nsq_passive_coating.py` |
| Medien bei reflektierten Views | `SurfaceView.interface_materials`; Fresnel-/ThinFilm-Coating an die physische Grenzflaeche gebunden (vorher R = 0 bei innerer Reflexion) | `tests/sequences/test_view_media.py` |
| Sequenzen nach Flaechen-Edits | Sequenzen folgen ihren Flaechen-Objekten; Indizes werden bei `trace()`/`to_dict()` neu nummeriert, entfernte Routenflaeche -> `SequenceStaleError` | `tests/sequences/test_sequence_lifecycle.py` |
| Persistenz | Rohflaechen (`add_component`) und `SurfaceConfig`-Overrides von Lens/Doublet/Mirror im NSQ-JSON; Sequenzen nummerieren sich beim Speichern selbst neu | `test_nsq_surface_serialization.py` |
| Viewer | 2D/3D zeichnen Rohflaechen (Umriss / Sag-Profil) und Quellen (Marker + Emissionsrichtung) | `test_nsq_surface_rendering.py` |
| GUI | `NSQService` (Dokument, Worker-Thread) + `NSQPanel` (Layout, Detektoren, Bilanz), Sidebar "Non-Seq", Dock-Fokus-Fix, "Mirror"-Edit-Fix | `tests/gui/test_nsq_panel.py`, `test_focus_dock_widget.py`, `test_surface_service_edits.py`; Screenshots via `tools/gui_screenshot.py` |

Nicht umgesetzt (bewusst, siehe Abschnitt 4): deterministische Branch-
Ausfuehrung im sequentiellen Tracer, Torch-Splitting, Polarisation/OPD
je Arm, kohaerente Rekombination.

## 1. Verifizierter Bestand (unveraendert gueltig)

- [x] `Optic.add_sequence(name, steps)` / `optic.sequences`.
- [x] `SurfaceView` mit eigenen Records je Besuch; Geometrie geteilt.
- [x] `OpticSerializer` speichert `sequences`.
- [x] `NSQScene` mit mehreren Quellen, Komponenten, Detektoren.
- [x] `RefractiveComponent` + `SimpleCoating` als teilreflektierende Grenzflaeche.
- [x] `SamplingPolicy` mit Importance-Biasing und begrenztem Splitting (NumPy).
- [x] NSQ-Ereignisse, `scene.view()`/`view3d()`, eigenes JSON, Konverter.
- [x] `optiland/paraxial_path.py` als gefalteter Einzelpfad (kein Verzweigungsgraph).

## 2. Architekturentscheidung (getroffen)

Der inkohaerente Fall wird vollstaendig mit NSQ abgebildet; benannte
Sequenzen beschreiben weiterhin einzelne sequentielle Routen. Eine neue
Branch-Ausfuehrungs-API im sequentiellen Kern wurde **nicht** gebaut:

- `Optic.trace()` / `SurfaceGroup.trace()` und ihre Rueckgabevertraege
  sind unveraendert (Tests `tests/sequences/` und `tests/nonsequential/`
  vollstaendig gruen, siehe Abschnitt 9).
- Keine parallele `OpticalPath`-Verwaltung; `SequencedSurfaceGroup`
  wurde nur um `is_stale`/`refresh` erweitert.
- Die Zuordnung Reflexion/Transmission zu Routen liegt in der
  NSQ-Pfadausfuehrung (Interpreter, `forced_branch`) und in den
  Sequence-Overrides `(i, "reflect")`, nicht im Coating.
- `dict[str, RealRays]` als Endbuendel-API wurde nicht eingefuehrt;
  Herkunft und Verzweigung liefert das NSQ-Ereignisprotokoll.

Begruendung: Der Beleuchtungs-/Abbildungsaufbau (Abschnitt 7, Schritt 2)
liess sich mit NSQ vollstaendig und exakt nachweisen. Die verbleibenden
Wuensche (Torch-Splitting, OPD/Polarisation je Arm) betreffen
Faelle, die dieser Aufbau nicht braucht; sie bleiben als Abschnitt 4
dokumentiert.

## 3. Befunde und ihre Behebung

### Numerik: Mehrfachtreffer unter Torch float32 - behoben

Root Cause (nachgewiesen, nicht mehr Hypothese): `BaseComponent.intersect`
und `BaseDetector.intersect` verwarfen Treffer nur unterhalb eines festen
`T_EPSILON = 1e-9` mm. Der float32-Rundungsrest einer Position bei
~10 mm liegt bei ~1e-6 mm (gemessen: Selbsttreffer bei
1e-9 ... 8.1e-7 mm, Median 1.8e-7 mm), also oberhalb der Schwelle.

Fix (`optiland/nonsequential/_utils.py::self_intersection_offset`):
Der lokale Strahlursprung wird vor dem Geometrie-Test um
`max(1e-9, 16 * eps * (1 + |p|_inf + |t|_inf))` entlang der Richtung
verschoben und der Offset auf `t` addiert. `eps` ist das Maschinen-Epsilon
des Datentyps, `p` die globale Position, `t` die Translation der
Komponente. float64 verhaelt sich wie zuvor (1e-9-Boden), float32 erhaelt
~4e-5 mm bei 10 mm. Der zweite Wurzelpunkt geschlossener Geometrien
(Kugelinnenseite) bleibt erreichbar, weil nur verschoben, nicht gefiltert
wird.

Messung nach dem Fix (2048 Strahlen, Seed 7):

| Backend / Praezision | Sampling | Transmission [W] | Reflexion [W] | Splitter-Treffer |
| --- | --- | --- | --- | --- |
| NumPy / float64 | `split_depth=1` | 0.500000 | 0.500000 | 2048, max 1 je Strahl |
| NumPy / float64 | `split_depth=0` | 0.500977 | 0.499023 | 2048, max 1 |
| Torch / float64 | `split_depth=0` | 0.500977 | 0.499023 | 2048, max 1 |
| Torch / float32 | `split_depth=0` | 0.500977 | 0.499023 | 2048, max 1 |

- [x] Ursache untersucht und behoben (Origin-Offset).
- [x] Regression fuer NumPy/Torch x float64/float32 mit eigener Fixture
      (`backend_precision`), da `set_test_backend` nur float64 setzt.
- [x] Pro Strahl maximal ein Splitter-Treffer und Detektorverteilung
      geprueft (`num_rays_hit`-Summe, 4-sigma-Grenzen, exakt bei Splitting).
- [x] Keine Toleranzen aufgeweitet; zusaetzlich float32 == float64
      strahlgenau (`abs=1e-4`, gleiche Trefferzahlen).

### Medien und Flaechenbesuche

- [x] Materialzuordnung fuer beide Richtungen und wiederholte Besuche
      getestet (`test_view_media.py::TestMediaPerVisit`).
- [x] Reflektierte Views: `SurfaceView.interface_materials` liefert
      `(incident, far)`; `_rebind_coating` bindet Fresnel/ThinFilm daran.
      Nachweis: innere Reflexion Glas/Luft bei senkrechtem Einfall liefert
      R = 0.04 (vorher 0), Geisterbild-Rundlauf T*R*R*T exakt.
- [x] NSQ nutzt weiterhin `n_geom` fuer n1/n2; der `medium_stack` bleibt
      Diagnose. Neu: Transmission zwischen identischen Medien
      (Splitter Vakuum|Vakuum) erzeugt keinen Underflow mehr.
- [x] Sequenzen nach Hinzufuegen/Entfernen von Flaechen: Regel festgelegt
      und implementiert - Sequenzen folgen ihren Flaechen-Objekten;
      `is_stale`/`refresh()` nummerieren die Rohindizes neu, entfernte
      Routenflaeche -> `SequenceStaleError`, gebrochene Medienkette ->
      `SequenceValidationError`. `Optic.refresh_sequences()` prueft eager.

### Leistung, Polarisation und Differenzierbarkeit

- [x] Passives R/T-Modell: `validate_passive_coating` /
      `validate_reflectance` in `coating_support.py`; `R + T == 1` nur
      im verlustfreien Fall, verlustbehaftet erlaubt und in der Bilanz
      sichtbar (`test_lossy_coating_keeps_the_energy_balance_honest`).
- [x] Exakte Teilung (`split_depth=1`) und statistische Schaetzung
      (Roulette, 4-sigma) getrennt getestet.
- [x] NumPy-Splitting-Grenzen unveraendert dokumentiert
      (`split_budget`, Roulette am Limit); Diagnose
      `split_budget_saturated` im Test geprueft.
- [x] Absorption, Apertur, Coating-Verlust, Branch-Gewicht je einmal:
      Zwei-Arm-Szene bilanziert Kamera + Bulk-Absorption = 0.5 W exakt.
- [x] Totalreflexion: T=0 erzwungen; Null-Fluss-Transmissionskind wird
      nicht mehr erzeugt (`TestTotalInternalReflection`).
- [x] Keine Polarisation/Interferenz versprochen (Doku, Abschnitt 4).
- [x] Coating-Koeffizienten bleiben als Tensor angebunden
      (`coating_coefficient`); `d(P_reflektiert)/dR` unter Torch geprueft.
- [ ] Sequentielle polarisierte Erweiterung (p, `_i0`) - nicht Teil dieser
      Stufe (Abschnitt 4).

### Records und Pfadidentitaet

- [x] `"split"`-Ereignis mit `parent_id` (`_EVENT_DTYPE` um `parent_id`
      erweitert, -1 sonst); `PathRecorder.root_of()` fuer verschachtelte
      Splits.
- [x] Sollrouten (Sequenzen), Trefferfolgen (Ereignisse) und
      Detektorergebnisse bleiben getrennte Begriffe; Quellen/Detektoren
      tragen jetzt ihre Registry-Namen in Birth-/Hit-Ereignissen.
- [x] `record_paths=int` bleibt Diagnose; Kinder werden mit ihrem
      Root-Strahl aufgezeichnet (Test `..._keeps_children_with_their_parents`).
- [x] Diagnose-Records sind NumPy (detached), unveraendert.

## 4. Sequentielle Branch-Ausfuehrung - nicht umgesetzt

Nach der Entscheidung in Abschnitt 2 wurde kein sequentieller
Branch-Tracer gebaut. Die dort gelisteten Integrationsstellen
(`RealRays.copy()`, `InteractionModelFactory.register`, `SurfaceFactory`,
`_TracingCoordinator`, Record-Lebenszyklus, Terminierung je Arm,
`be.no_grad_unless_enabled()`) bleiben als Leitfaden fuer eine spaetere
Stufe stehen. Voraussetzung waere ein Bedarf, den NSQ nicht deckt:
deterministische Torch-Branches, OPD/Jones je Arm oder arm-spezifische
sequentielle Analysen. Der jetzige Referenzaufbau braucht keines davon.

## 5. Paraxiale Analyse und Ray-Aiming - unveraendert

Keine Aenderung an `ParaxialRayTracer`, `ParaxialPath` oder dem
Ray-Aiming. Die Zwei-Arm-Szene legt die Kameraebene mit einer expliziten
Dickenlinsen-Formel (`thick_lens_image_distance`) fest und prueft die
Abbildung ueber die Einschnuerung des Kamerabilds (>95 % innerhalb
0.3 mm), nicht ueber eine sequentielle First-Order-Analyse je Arm. Diese
bleibt eine Erweiterung nach Abschnitt 4.

## 6. Persistenz, GUI und Visualisierung

- [x] `sequences`-JSON-Feld erhalten; Rohschritte werden beim Speichern
      neu nummeriert (Test `test_serialization_writes_the_renumbered_steps`).
- [x] NSQ-JSON bleibt eigenes Format (`nsq_schema_version=1`); neu:
      `"surface"`-Eintraege fuer Rohflaechen, `SurfaceConfig`-Overrides
      fuer Lens/Doublet/Mirror. BSDF und Callable-Reflektanz werfen
      `TypeError` statt still zu verschwinden.
- [x] Roundtrips gezielt geprueft: beide Referenzszenen liefern nach
      dict-/Datei-Roundtrip identische Armleistungen (`abs=1e-12`).
      Befund dabei: Linsen-Face-Coatings gingen vorher verloren
      (Kamera 0.4528 statt 0.4997 W) - behoben.
- [x] `sequential_to_nonsequential` unveraendert genutzt (kein Bedarf).
- [x] GUI nach stabiler Core-Nutzung: `optiland_gui/services/nsq_service.py`
      (Dokument, Laden/Speichern, `trace_async` auf QThread, `trace_sync`
      fuer Tests/Skripte) und `optiland_gui/nsq_panel.py` (Dock
      "Non-Sequential", Tabs Layout/Detectors/Summary, Split-Tiefe,
      Recorded paths, Projektion). Registriert in `PanelManager`,
      Sidebar "Non-Seq", Theme-Weitergabe.
- [x] Geometrie und Interaktion getrennt: kein `beam_splitter`-Geometrietyp;
      der Splitter ist `FinitePlaneGeometry` + `RefractiveComponent`.
- [x] Undo/Redo: NSQ-Szenen werden im GUI nicht editiert (nur geladen,
      getraced, gespeichert); daher keine Undo-Anbindung noetig.
      Lange Traces laufen im Worker-Thread.
- [x] `_set_material_data()` setzt `interaction_model.is_reflective`
      (Regressionstests `TestMirrorMaterialEdit`).
- [x] NSQ-Viewer wiederverwendet: `NSQViewer2D.view(ax=...)` im Panel;
      neue Renderer `renderers/surface.py`, `renderers/source.py`.
      Layout-Achsen nutzen den ganzen Canvas
      (`adjustable="datalim"`, Test `test_layout_axes_fill_the_canvas`).
- [x] Pfaddarstellung: variable Laengen ueber Ereignisse, Kinder starten
      am Split-Punkt (`_EVENT_ORDER["split"] = 0`).
- [x] Zusaetzlich behoben: `MainWindow.focus_dock_widget` hob tabifizierte
      Docks nicht an (Sidebar-Klick zeigte den Nachbar-Tab).

## 7. Implementierungsfolge (Ist)

1. [x] NSQ-Referenzfall als Sample + Tests; float32-Mehrfachtreffer behoben.
2. [x] Beleuchtungs-/Abbildungsaufbau mit getrennten Eintrittsarmen;
       Ergebnisarten: Detektorleistungen je Arm, Kamerabild-Einschnuerung,
       Arm-Trennung ueber Ereignis-Herkunft.
3. [x] Entscheidung: keine Kern-Erweiterung noetig (Abschnitt 2/4).
4. [x] Luecken geschlossen: Guard, R/T-Validierung, Provenance,
       Coating-Bindung, Sequenz-Lebenszyklus, Persistenz, Renderer.
5. [x] Persistenz, Herkunft, Medien und Analysegrenzen abgesichert.
6. [x] Viewer erweitert, dann GUI-Dokument-/Service-Anbindung.
7. [x] Doku: `docs/developers_guide/nonsequential_raytracing.rst`
       (Abschnitt 4a), `docs/developers_guide/sequences_framework.rst`,
       `docs/gallery/nonsequential/12_beam_splitter_paths.rst`,
       `limitations_and_roadmap.rst`, `docs/gui_quickstart.rst`,
       Tutorial 10a (neuer Abschnitt 4), `_changes/beam-splitter-multi-path.md`.

## 8. Abnahmetests (Stand)

- [x] `tests/sequences/` und `tests/nonsequential/` erweitert, keine
      parallelen Teststrukturen.
- [x] Physische Richtungen/Medien: 45-Grad-Splitter beidseitig
      (Beleuchtung von +x, Objektlicht von der Rueckseite), Brechung
      (Linse), Reflexion, Totalreflexion, wiederholte Besuche.
- [x] R/T-Randwerte 0 und 1, verlustbehaftet, ungueltig, Absorption.
- [x] Deterministisches NumPy-Splitting, Roulette, Torch-Warnung
      (bestehender Test `test_nsq_sampling_policy.py`).
- [x] Statistische Tests mit 4-sigma-Grenzen und festen Seeds.
- [x] NumPy/Torch x float64/float32 explizit.
- [x] Records/Herkunft, keine Selbsttreffer, unterschiedliche Armlaengen.
- [x] Aliasing/Gradientenfluss der Coating-Koeffizienten (`d/dR`).
- [x] Legacy-Trace unveraendert (Suiten gruen).
- [x] Alte Optic-Dateien ohne `sequences`, Sequence-Roundtrips,
      NSQ-Roundtrips getrennt.
- [x] GUI-Tests fuer die gewaehlte Integration (Panel, Service, Dock-Fokus,
      Mirror-Edit); Screenshots der realen GUI mit `tools/gui_screenshot.py`.

## 9. Pruefnachweis dieser Revision

Ausgefuehrt (Auszug; Details in den Commit-Nachrichten):

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:randomly tests/nonsequential tests/sequences
.venv\Scripts\python.exe -m pytest -q -p no:randomly tests/gui
.venv\Scripts\python.exe tools/gui_screenshot.py --panel nonsequential --trace --all-tabs out/nsq.png
.venv\Scripts\python.exe tools/gui_screenshot.py --panel nonsequential --dock-only --scene side_illumination --trace --split-depth 1 --all-tabs out/side.png
```

Pre-Fix-Nachweise (detached Worktrees auf dem jeweiligen HEAD, nur die
neuen Tests kopiert): float32-Guard - 4 rot / 17 gruen; Coating-Bindung
reflektierter Views - 6 rot / 4 gruen. Nach den Fixes jeweils vollstaendig
gruen.

Offen bleibende Punkte sind ausschliesslich die in Abschnitt 4 und 5
genannten Erweiterungen; sie sind keine Voraussetzung fuer den
Beleuchtungs-/Abbildungsaufbau.
