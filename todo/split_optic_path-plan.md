# Multi-Path Optics - Strahlenteiler / Beam Splitter

Status: korrigiert gegen den aktuellen Code-Stand am 2026-05-21.

Ziel: Optiland um optische Systeme mit mehreren Strahlenwegen erweitern, z.B.
ein Strahlenteiler, der Beleuchtung von der Seite und Abbildung in Transmission
kombiniert.

Die wichtigste Korrektur zur ersten Skizze: `Optic.trace()` und
`SurfaceGroup.trace()` duerfen im ersten Schritt nicht pauschal von
`RealRays` auf `dict[str, RealRays]` umgestellt werden. Sehr viele Analyse-,
Visualisierungs- und GUI-Pfade erwarten aktuell ein einzelnes, mutiertes
`RealRays`-Objekt. Multi-Path sollte deshalb ueber eine explizite neue API
eingefuehrt werden, z.B. `trace_paths()` / `trace_generic_paths()`, waehrend
die bestehende Single-Path-API unveraendert bleibt.

---

## 0. Korrigierte Architektur-Leitplanken

- [ ] Kein rohes Tuple als dauerhafte Schnittstelle verwenden.
      Empfehlung: ein explizites Datenobjekt einfuehren, z.B.
      `RaySplit` / `TraceBranches`, das Path-IDs enthaelt:
      `branches: dict[str, RealRays]`.
- [ ] `Optic.trace()` bleibt rueckwaertskompatibel und gibt weiter `RealRays`
      zurueck. Neue API fuer Multi-Path:
      `optic.trace_paths(...) -> dict[str, RealRays]`.
- [ ] `SurfaceGroup.trace()` bleibt fuer bestehende Systeme single-path.
      Neue API:
      `surface_group.trace_paths(rays, start_path="main", skip=0)`.
- [ ] Die lineare `previous_surface`-Verkettung ist fuer verzweigte Pfade nicht
      ausreichend. Multi-Path braucht einen Pfad-/Medium-Kontext, damit
      `material_pre` und `material_post` pro Pfad korrekt sind.
- [ ] Erste Implementierungsstufe eng halten:
      Real rays, feste Split-Ratio, NumPy + Torch, keine paraxiale
      Multi-Path-Auswertung, kein GUI-Zwang.
- [ ] Paraxiale und Analyse-Pfade muessen Multi-Path-Systeme erkennen und mit
      klarer Fehlermeldung abbrechen, solange sie keinen Pfadparameter
      unterstuetzen.

Moegliche neue Datenstrukturen:

```python
@dataclass(frozen=True)
class OpticalPath:
    path_id: str
    surface_indices: tuple[int, ...]
    image_surface_index: int | None = None


@dataclass
class RaySplit:
    branches: dict[str, RealRays]
```

Optional spaeter:

```python
@dataclass
class TracePathState:
    path_id: str
    rays: RealRays
    surface_cursor: int
    material_pre: BaseMaterial
```

---

## 1. Ray-Kopien zuerst

**Dateien:** `optiland/rays/real_rays.py`, `optiland/rays/polarized_rays.py`,
`tests/test_rays.py` oder neues `tests/test_ray_copy.py`

- [ ] `RealRays.copy()` oder `RealRays.clone()` einfuehren.
      Derzeit existiert diese Methode nicht.
- [ ] Alle ray state fields unabhaengig kopieren:
      `x, y, z, L, M, N, i, w, opd, L0, M0, N0, is_normalized`.
- [ ] `PolarizedRays` separat behandeln:
      zusaetzlich `p, _i0, _L0, _M0, _N0` kopieren.
- [ ] Backend-agnostisch mit `be.copy()` arbeiten.
- [ ] Tests fuer NumPy und Torch:
      geaenderte Felder eines Branches duerfen den anderen Branch nicht
      veraendern.

Grund: Der Strahlenteiler muss denselben Eingangsstrahl in mindestens zwei
unabhaengige Ausgangs-Raysets verzweigen, bevor `reflect()` und `refract()`
mutierend aufgerufen werden.

---

## 2. Core: BeamSplitterInteractionModel

**Dateien:** `optiland/interactions/beam_splitter_model.py` (neu),
`optiland/interactions/__init__.py`,
`optiland/interactions/base.py`,
`optiland/surfaces/factories/interaction_model_factory.py`,
`optiland/_types.py`

- [ ] Neue Klasse `BeamSplitterInteractionModel(BaseInteractionModel)`.
- [ ] Konstruktor-Parameter:
      - `split_ratio: float` im Bereich `[0, 1]`, Anteil Reflexion.
      - `reflected_path: str = "reflected"`.
      - `transmitted_path: str = "transmitted"`.
      - `coating: BaseCoating | None = None`.
      - `bsdf: BaseBSDF | None = None`.
- [ ] `interaction_type = "beam_splitter"` setzen.
- [ ] `interact_real_rays()` gibt ein explizites Split-Objekt zurueck,
      nicht ein positionsabhaengiges Tuple:

      ```python
      reflected = rays.copy()
      transmitted = rays.copy()
      reflected.reflect(nx, ny, nz)
      transmitted.refract(nx, ny, nz, n1, n2)
      reflected.i = reflected.i * split_ratio
      transmitted.i = transmitted.i * (1.0 - split_ratio)
      return RaySplit({
          reflected_path: reflected,
          transmitted_path: transmitted,
      })
      ```

- [ ] Energieerhaltung validieren:
      `0 <= split_ratio <= 1` und `R + T == 1` fuer das Fixed-Ratio-Modell.
- [ ] Coatings nicht blind ueber `_apply_coating_and_bsdf()` anwenden:
      der Helper nutzt aktuell `self.is_reflective` als globales Flag.
      Fuer Splitter braucht die Coating-Anwendung pro Branch ein explizites
      `reflect=True` bzw. `reflect=False`.
- [ ] Zunaechst eine klare Entscheidung treffen:
      Fixed-Ratio und Coating/Fresnel sind entweder zwei Modi, oder ein Modus
      hat dokumentierten Vorrang. Keine doppelte Intensitaetsskalierung.
- [ ] `interact_paraxial_rays()`:
      vorerst `NotImplementedError("Paraxial tracing is not supported for beam splitters.")`.
- [ ] `flip()`:
      wenn Rueckwaerts-Tracing fuer Splitter nicht implementiert ist, klar
      dokumentieren und nicht still falsche Pfade erzeugen.
- [ ] `to_dict()` um `split_ratio`, `reflected_path`,
      `transmitted_path` erweitern.
- [ ] `BaseInteractionModel.from_dict()` pruefen:
      aktuell instanziiert es Subklassen direkt und nutzt deren eigene
      `from_dict()`-Methode nicht. BeamSplitter-Daten muessen entweder zu
      diesem generischen Pfad passen oder der Loader muss sauber an
      Subklassen-Deserialisierung delegieren.
- [ ] `InteractionModelFactory.create()` um `"beam_splitter"` erweitern.
- [ ] `SurfaceParameters` in `optiland/_types.py` um relevante kwargs
      erweitern: `interaction_type`, `split_ratio`, `reflected_path`,
      `transmitted_path`, ggf. `bsdf`.

---

## 3. Surface-Schicht: Branch-Awareness

**Datei:** `optiland/surfaces/standard_surface.py`

Korrektur zur ersten Skizze: Nicht nur `_trace_real()` muss angepasst werden.
Die entscheidende Stelle ist `Surface.trace()`, weil dort lokalisiert,
globalisiert und recorded wird.

Aktueller Ablauf:

```python
self.geometry.localize(rays)
rays = rays.trace_on_surface(self)
self.geometry.globalize(rays)
rays.record_on_surface(self)
return rays
```

Bei einem Split liegen nach `interact_real_rays()` mehrere lokale Raysets vor.
Alle muessen globalisiert und separat recorded werden.

- [ ] Rueckgabetypen typisieren:
      `RealRays | RaySplit` fuer real rays, `ParaxialRays` fuer paraxial.
- [ ] `Surface.trace()` branch-aware machen:
      - Single `RealRays`: bisheriger Pfad unveraendert.
      - `RaySplit`: jedes Branch-Rayset globalisieren und pro Path-ID
        aufzeichnen.
- [ ] Recording erweitern:
      - Bestehende Felder `x, y, z, L, M, N, intensity, opd` bleiben fuer
        Single-Path/Legacy erhalten.
      - Neues Feld, z.B. `ray_paths: dict[str, SurfaceRayRecord]` oder
        `path_records: dict[str, RealRays]`.
- [ ] Wenn dieselbe Surface von mehreren Pfaden getroffen wird, duerfen ihre
      Daten nicht ueberschrieben werden. Pfad-ID muss Teil des Records sein.
- [ ] `reset()` muss auch neue Pfad-Records leeren.

---

## 4. SurfaceGroup: Verzweigtes Tracing ohne Legacy-Bruch

**Datei:** `optiland/surfaces/surface_group.py`

- [ ] `SurfaceGroup` um optionale Pfad-Konfiguration erweitern:

      ```python
      paths: dict[str, OpticalPath]
      # oder serialisierbar:
      paths: dict[str, list[int]]
      ```

- [ ] Default fuer bestehende Systeme:
      `{"main": tuple(range(num_surfaces))}`.
- [ ] Neue Methode:

      ```python
      def trace_paths(self, rays, start_path: str = "main", skip: int = 0) -> dict[str, RealRays]:
          ...
      ```

- [ ] `trace()` fuer Legacy-Systeme unveraendert lassen.
      Optional kann `trace()` intern `trace_paths()` verwenden, aber nur wenn
      das Ergebnis eindeutig single-path ist.
- [ ] Aktive Pfade als States verwalten:
      `path_id`, aktuelle Surface-Sequenz, Rayset, ggf. aktuelles Medium.
- [ ] Split-Ausgang nicht ueber `surface.path_id` modellieren.
      Besser: Splitter-Interaktion erzeugt Branch-IDs, und `SurfaceGroup`
      routed diese Branches in die passende `OpticalPath.surface_indices`.
- [ ] Lineare `previous_surface`-Abhaengigkeit pruefen:
      `Surface.material_pre` nutzt aktuell die vorherige Surface in der
      globalen Liste. Das ist fuer reflektierte oder seitliche Arme oft falsch.
      Fuer korrekte Physik braucht ein Branch entweder:
      - pfad-spezifische Surface-Links,
      - einen expliziten `material_pre`/`material_post` Kontext,
      - oder eine erste Scope-Einschraenkung, die nur Systeme mit gleichem
        Umgebungsmedium nach dem Split erlaubt.
- [ ] Aggregations-Properties `x`, `y`, `z`, `intensity` nicht einfach ueber
      alle Pfade stapeln. Pfade haben unterschiedliche Laengen und Surface-IDs.
      Neue API einfuehren, z.B.:
      `surface_group.path_records[path_id]` oder
      `surface_group.get_path_arrays(path_id)`.
- [ ] `reset()` muss alle Surface-Records und alle Path-Records leeren.

---

## 5. Ray-Tracer und Optic-API

**Dateien:** `optiland/raytrace/real_ray_tracer.py`,
`optiland/optic/optic.py`,
ggf. `optiland/optic/extended_source_optic.py`

- [ ] Neue `RealRayTracer.trace_paths()` Methode.
- [ ] Neue `Optic.trace_paths()` Methode.
- [ ] Neue `Optic.trace_generic_paths()` Methode, wenn generische Strahlen
      fuer Multi-Path benoetigt werden.
- [ ] `Optic.trace()` und `Optic.trace_generic()` geben weiter `RealRays`
      zurueck.
- [ ] Final propagation pro Pfad ausfuehren:
      derzeit propagiert `RealRayTracer.trace()` nur ein Rayset mit
      `last_surface.thickness`.
      Multi-Path braucht pro Pfad eine Terminal-/Image-Surface.
- [ ] Intensitaetsupdate nicht mehr nur ueber
      `self.optic.surfaces.intensity[-1, :]` abwickeln.
      Multi-Path braucht pfad-spezifische Endrecords.
- [ ] `optic.surfaces.add(...)` ist die primaere Add-API.
      `Optic.add_surface()` ist deprecated und sollte nur weiterreichen.
- [ ] Falls `add_path()` / `add_beam_splitter()` eingefuehrt werden, eher an
      `SurfaceGroup` oder einen kleinen `PathManager` haengen:

      ```python
      optic.surfaces.add_path("transmitted", [0, 1, 2, 3])
      optic.surfaces.add_path("reflected", [0, 1, 4, 5])
      ```

- [ ] Analyse-Methoden spaeter um `path_id` erweitern oder bei Multi-Path ohne
      eindeutigen Hauptpfad mit klarer Meldung abbrechen.
- [ ] Feldpunkte und Apertur pro Pfad sind Phase 2. Fuer Phase 1 denselben
      Eingangsraysatz splitten.

---

## 6. Paraxiale / analytische Unterstuetzung

**Dateien:** `optiland/raytrace/paraxial_ray_tracer.py`,
`optiland/paraxial.py`, Analyse-Module

Korrektur: `ParaxialRayTracer.trace_generic()` nutzt eigene lineare Logik und
ruft nicht die normalen Interaction-Modelle auf. Ein
`BeamSplitterInteractionModel.interact_paraxial_rays()`-Stub allein schuetzt
also nicht alle paraxialen Pfade.

- [ ] Multi-Path-/BeamSplitter-Erkennung zentral einfuehren, z.B.
      `surface_group.has_ray_splits`.
- [ ] `ParaxialRayTracer.trace()` und `trace_generic()` muessen vor der
      linearen Berechnung abbrechen, solange Splitter nicht unterstuetzt sind.
- [ ] Fehlermeldung:
      `"Paraxial analysis is not supported for multi-path optics. Select a single path or use real-ray tracing."`
- [ ] Spaetere Ausbaustufe: paraxiale Berechnung nur fuer einen expliziten
      Pfad, z.B. `optic.paraxial.trace_path("transmitted", ...)`.

---

## 7. Serialisierung / Datei-I/O

**Dateien:** `optiland/optic/optic_serializer.py`,
`optiland/surfaces/surface_group.py`,
`optiland/fileio/optiland_handler.py`

- [ ] Optiland-eigene Persistenz ist aktuell JSON-basiert ueber
      `OpticSerializer` und `optiland/fileio/optiland_handler.py`.
      YAML nur erwaehnen, wenn konkret eingefuehrt wird.
- [ ] Pfad-Konfiguration serialisieren, bevorzugt in `surface_group`:

      ```json
      {
        "surface_group": {
          "surfaces": [...],
          "paths": {
            "main": [0, 1, 2, 3],
            "reflected": [0, 1, 4, 5]
          }
        }
      }
      ```

- [ ] Rueckwaertskompatibel laden:
      wenn `paths` fehlt, automatisch `main = all surfaces`.
- [ ] Splitter-Interaction serialisiert `split_ratio`, `reflected_path`,
      `transmitted_path`.
- [ ] Tests fuer Roundtrip:
      alter JSON-Stand ohne `paths`, neuer Stand mit `paths`, und
      BeamSplitter-Interaction.
- [ ] Zemax-/CodeV-Import nicht im ersten Schritt versprechen.
      Erst pruefen, welche Non-Sequential- oder Fold-/Coating-Konventionen
      gemappt werden koennen.

---

## 8. GUI-Integration

**Dateien:** `optiland_gui/services/surface_service.py`,
`optiland_gui/lens_editor.py`,
`optiland_gui/system_properties_panel.py`,
Undo/Redo- und Connector-Code

Korrektur: Ein Beam Splitter ist in diesem Design keine neue Geometry
`surface_type`, sondern ein neues Interaction Model. Darum nicht einfach
`AVAILABLE_SURFACE_TYPES` erweitern. Die GUI nutzt fuer Surface-Typen aktuell
die `GeometryFactory`-Registry.

- [ ] Zuerst Core-API stabilisieren, dann GUI.
- [ ] GUI braucht eine eigene Anzeige/Bearbeitung fuer Interaction Models:
      `refractive_reflective`, `phase`, `diffractive`, `thin_lens`,
      `beam_splitter`.
- [ ] Es gibt aktuell keine `_get_interaction_type()`-Methode in
      `SurfaceService`; diese muesste neu entstehen, falls die LDE den
      Interaction-Typ anzeigen soll.
- [ ] Eigenschaften fuer BeamSplitter:
      - Split-Ratio in Prozent Reflexion.
      - Reflected Path.
      - Transmitted Path.
      - Optional: Coating-Modus.
- [ ] Pfadverwaltung in System-Properties oder eigenem Dialog:
      Path-ID, Surface-Liste, Terminal-/Image-Surface.
- [ ] Undo/Redo:
      Pfad- und Interaction-Aenderungen muessen ueber vorhandene
      `_capture_optic_state()` / `_restore_optic_state()`-Mechanik laufen.
- [ ] Nebenbefund fuer spaetere GUI-Korrektur pruefen:
      `SurfaceService._set_material_data()` setzt aktuell `surface.is_reflective`,
      waehrend Core-Code `surface.interaction_model.is_reflective` nutzt.
      Fuer BeamSplitter-UI darf diese Inkonsistenz nicht weiter ausgebaut
      werden.

---

## 9. Visualisierung

**Dateien:** `optiland/visualization/system/rays.py`,
`optiland/visualization/system/optic_viewer.py`,
`optiland/visualization/system/optic_viewer_3d.py`,
`optiland_gui/viewer_panel.py`

- [ ] Erst nach stabilem `trace_paths()` implementieren.
- [ ] `Rays2D._process_traced_rays()` kann aktuell nur
      `optic.surfaces.x/y/z/intensity` lesen. Fuer Multi-Path braucht es
      pfad-spezifische Records.
- [ ] Pfade getrennt plotten:
      - je Path-ID eigene Farbe.
      - Legende mit Path-ID.
      - Option zum Ausblenden einzelner Pfade.
- [ ] Pfad-Laengen koennen unterschiedlich sein; nicht voraussetzen, dass alle
      Pfade ein rechteckiges Array `[num_surfaces, num_rays]` besitzen.
- [ ] 3D/VTK analog ueber Pfadrecords bauen.
- [ ] Strahlenteiler-Flaeche optional halbdurchsichtig darstellen, aber erst
      nach Core/Trace-Records.

---

## 10. Tests

**Verzeichnis:** `tests/`

- [ ] Unit-Tests: `tests/test_beam_splitter_model.py`
      - Split-Ratio validiert `[0, 1]`.
      - Energieerhaltung fuer Fixed-Ratio.
      - Reflektierter Branch erfuellt Reflexionsgesetz.
      - Transmittierter Branch erfuellt Snell.
      - Branch-IDs stimmen.
      - Serialisierung round-trip.
- [ ] Copy-Tests: `tests/test_ray_copy.py`
      - `RealRays.copy()`/`clone()` kopiert alle Felder.
      - Keine Aliasing-Probleme NumPy/Torch.
      - `PolarizedRays` kopiert Polarisationstate korrekt.
- [ ] Surface-Tests: `tests/test_standard_surface.py`
      - Single-Path-Verhalten unveraendert.
      - Split-Branch wird globalisiert und pro Pfad recorded.
- [ ] SurfaceGroup-Tests: `tests/test_surface_group_paths.py`
      - Alte Systeme ohne `paths` laufen unveraendert.
      - `trace_paths()` liefert `dict[str, RealRays]`.
      - Pfad-Konfiguration routet reflected/transmitted korrekt.
      - Unterschiedliche Pfadlaengen funktionieren.
- [ ] Optic-/Tracer-Tests: `tests/test_multi_path_optic.py`
      - `optic.trace()` bleibt `RealRays`.
      - `optic.trace_paths()` liefert erwartete Pfade.
      - Final propagation pro Pfad korrekt.
      - NumPy und Torch via `set_test_backend`.
- [ ] Paraxial-Tests:
      - BeamSplitter/Multi-Path wirft klare `NotImplementedError`.
- [ ] GUI-Tests erst nach GUI-Integration:
      `tests/gui/test_beam_splitter_service.py`.

Keine Toleranzen lockern, nur um Tests gruen zu bekommen.

---

## 11. Dokumentation & Beispiele

**Verzeichnisse:** `docs/`, `docs/examples/`, `_changes/`, `agents.md`

- [ ] Docstrings fuer neue Klassen und Methoden im Google-Stil.
- [ ] `_changes/` Eintrag erstellen, sobald Implementierung existiert.
- [ ] Beispiel/Notebook erst nach stabilem Core:
      `Tutorial_11_Beam_Splitter_Systems.ipynb`.
- [ ] Beispiele:
      - Einfacher 50:50 Splitter.
      - Abbildung + Beleuchtung.
      - Optional spaeter Mach-Zehnder, wenn Phasen/Interferenz sauber
        abgebildet werden.
- [ ] `agents.md` nur aktualisieren, wenn Multi-Path zur dauerhaften
      Architektur-Konvention wird.

---

## Empfohlene Phasen

```text
Phase 0: Ray copy/clone + Tests
    -> Phase 1: RaySplit-Datenstruktur + BeamSplitterInteractionModel
        -> Phase 2: Surface.trace() branch-aware machen
            -> Phase 3: SurfaceGroup paths + trace_paths()
                -> Phase 4: RealRayTracer/Optic trace_paths()
                    -> Phase 5: Serialisierung
                    -> Phase 6: Paraxial fail-fast
                    -> Phase 7: Visualisierung
                    -> Phase 8: GUI
                    -> Phase 9: Docs/Examples
```

Tests laufen phasenbegleitend, nicht erst am Ende.

---

## Kritische Risiken

| Risiko | Beschreibung | Korrigierte Massnahme |
| --- | --- | --- |
| Rueckwaertskompatibilitaet | `trace()` Rueckgabetyp-Aenderung bricht viele Aufrufer | `trace()` unveraendert lassen, neue `trace_paths()` API |
| Tuple-API | Tuple-Reihenfolge ist unklar und verliert Path-IDs | Explizites `RaySplit` / `branches: dict[str, RealRays]` |
| Material-Kontext | `previous_surface` ist linear und fuer Branches oft falsch | Pfad-/Medium-Kontext einfuehren oder Scope begrenzen |
| Lokale Koordinaten | Split-Branches entstehen vor `globalize()` | `Surface.trace()` muss alle Branches globalisieren/recorden |
| Backend-Kompatibilitaet | Clones koennen NumPy/Torch-Arrays teilen | `be.copy()` und Aliasing-Tests fuer beide Backends |
| Polarisation | `PolarizedRays` hat zusaetzlichen Zustand | Polarized clone + branch-aware coating tests |
| Coatings | `_apply_coating_and_bsdf()` nutzt ein globales Reflect-Flag | Branch-spezifische Coating-Anwendung |
| Paraxial | Paraxial tracer umgeht Interaction-Modelle teilweise | Fruehe Multi-Path-Erkennung und klare Fehlermeldung |
| Visualisierung | Bestehende Arrays sind rechteckig und single-path | Pfadrecords statt globalem Stack |
| GUI | BeamSplitter ist Interaction, nicht Geometry | Eigene Interaction-UI statt Surface-Type-Dropdown |
