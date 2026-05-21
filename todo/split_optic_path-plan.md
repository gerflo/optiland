# Multi-Path Optics – Strahlenteiler / Beam Splitter

Ziel: Optiland um die Fähigkeit erweitern, optische Systeme mit mehreren
Strahlenwegen zu modellieren – z.B. ein Strahlenteiler, der Beleuchtung
(von der Seite) und Abbildung (in Transmission) kombiniert.

---

## 1. Grundlagen & Architektur-Entscheidungen

- [ ] Entscheiden: Dual-Output-Modell (Tuple-Return) vs. zweifacher Trace-Aufruf
      → Empfehlung: Tuple-Return in `interact_real_rays()` → `RealRays | tuple[RealRays, RealRays]`
- [ ] Entscheiden: Wie werden Pfade im `SurfaceGroup` adressiert?
      → Empfehlung: Jeder Pfad bekommt einen `path_id`-String (z.B. `"transmitted"`, `"reflected"`)
- [ ] Entscheiden: Rückwärts-Kompatibilität – bestehende Systeme dürfen nicht brechen
- [ ] Entscheiden: Paraxiale Unterstützung im ersten Schritt? (Empfehlung: Stub mit NotImplementedError)
- [ ] Design-Dokument für Datenfluss skizzieren (Strahlenteiler → zwei Pfade → je eigene Surfaces)

---

## 2. Core: BeamSplitterInteractionModel

**Dateien:** `optiland/interactions/beam_splitter_model.py` (neu),
             `optiland/interactions/base.py`,
             `optiland/surfaces/factories/interaction_model_factory.py`

- [ ] Neue Klasse `BeamSplitterInteractionModel(BaseInteractionModel)` erstellen
      - Konstruktor-Parameter: `split_ratio` (float 0..1, Anteil Reflektion), `coating=None`
      - Alternativ: Vollständige Fresnel-Berechnung anstelle fixer Ratio
- [ ] `interact_real_rays()` implementieren:
      - Eingabe: `RealRays` (N Strahlen)
      - Ausgabe: `tuple[RealRays, RealRays]` → `(reflected_rays, transmitted_rays)`
      - `reflected_rays = rays.copy(); reflected_rays.reflect(nx, ny, nz); reflected_rays.i *= R`
      - `transmitted_rays = rays.copy(); transmitted_rays.refract(nx, ny, nz, n1, n2); transmitted_rays.i *= T`
      - Sicherstellung: `R + T = 1` (Energieerhaltung)
- [ ] `interact_paraxial_rays()` implementieren (Stub → NotImplementedError oder vereinfachte Version)
- [ ] `flip()` implementieren (Richtungsumkehr für Rückwärts-Tracing)
- [ ] `to_dict()` / `from_dict()` für Serialisierung (JSON-Persistenz)
- [ ] `InteractionModelFactory` um `"beam_splitter"` erweitern
- [ ] Prüfen: Verhält sich `_apply_coating_and_bsdf()` korrekt für beide Ausgangspfade?

---

## 3. Ray-Klasse: Copy-Mechanismus

**Datei:** `optiland/rays/real_rays.py`

- [ ] Sicherstellen, dass `RealRays.copy()` alle Felder korrekt dupliziert:
      `x, y, z, L, M, N, i, w, opd, L0, M0, N0`
- [ ] Prüfen: Sind NumPy- und PyTorch-Backend-Arrays nach `copy()` wirklich unabhängig?
      (kein shared memory / aliasing)
- [ ] Ggf. `__deepcopy__` oder explizite `clone()`-Methode ergänzen

---

## 4. Surface-Schicht: Dual-Output-Trace

**Datei:** `optiland/surfaces/standard_surface.py`

- [ ] `_trace_real()` anpassen: Rückgabe von `interact_real_rays()` prüfen
      - Wenn `tuple` → beide Pfade weiterleiten statt einen zurückgeben
      - Wenn `RealRays` → bisheriges Verhalten (Rückwärtskompatibilität)
- [ ] `record_on_surface()` erweitern: Bei Strahlenteiler-Fläche beide Ray-Sets aufzeichnen
      - Neue Felder: `surface.reflected_rays`, `surface.transmitted_rays`
      - Alternativ: `surface.ray_paths: dict[str, RealRays]`
- [ ] `trace()` Signatur ggf. um Rückgabe-Typ erweitern:
      `def trace(self, rays) -> RealRays | tuple[RealRays, RealRays]`

---

## 5. SurfaceGroup: Verzweigtes Tracing

**Datei:** `optiland/surfaces/surface_group.py`

- [ ] Konzept "Pfad" einführen: `OpticalPath` = geordnete Liste von Surfaces + `path_id`
- [ ] `SurfaceGroup` um optionale Pfad-Konfiguration erweitern:
      - `paths: dict[str, list[int]]` → welcher Pfad durchläuft welche Surface-Indizes
      - Beispiel: `{"transmitted": [0,1,2,3,4], "reflected": [0,1,5,6,7]}`
- [ ] `trace()` so umbauen, dass bei Strahlenteiler-Fläche automatisch in zwei Pfade verzweigt wird:
      ```python
      def trace(self, rays, skip=0):
          active_paths = {"main": rays}
          for surface in self.surfaces[skip:]:
              result = surface.trace(active_paths[surface.path_id])
              if isinstance(result, tuple):
                  refl, trans = result
                  active_paths[surface.reflected_path_id] = refl
                  active_paths[surface.transmitted_path_id] = trans
          return active_paths
      ```
- [ ] Properties `x`, `y`, `z`, `intensity` erweitern: Aggregation über alle Pfade
- [ ] `reset()` auf alle Pfade anwenden

---

## 6. Optic-Modell: Multi-Arm-System

**Datei:** `optiland/optic/optic.py`

- [ ] `add_surface()` um Parameter `path` erweitern (optional, default `"main"`)
- [ ] Neues optionales Konzept `MultiPathOptic` (Unterklasse oder Mixin) erwägen:
      - `add_path(name: str, surfaces: list[int])` – definiert einen Arm
      - `add_beam_splitter(index: int, reflected_path: str, transmitted_path: str)`
- [ ] `trace()` anpassen: gibt `dict[str, RealRays]` zurück statt einzelner `RealRays`
- [ ] Analyse-Methoden prüfen: PSF, MTF, Aberrationen – nur auf spezifischem Pfad ausführen
- [ ] Feldpunkte und Apertur pro Pfad konfigurierbar machen (z.B. Beleuchtung hat anderen Eintrittspupillendurchmesser)

---

## 7. Paraxiale / Analytische Unterstützung

**Dateien:** `optiland/rays/paraxial_rays.py`, Analyse-Module

- [ ] Paraxiales Tracing für Strahlenteiler-Systeme definieren (vereinfacht: nur Transmissionsarm)
- [ ] EFL, BFD, ABCD-Matrix für den Haupt-Transmissionspfad weiterhin korrekt berechnen
- [ ] Sicherstellen: `FirstOrderAnalysis` bricht nicht, wenn System Strahlenteiler enthält
      (Fallback: Fehler mit klarer Meldung, kein stiller Absturz)

---

## 8. Serialisierung (Datei-I/O)

**Dateien:** `optiland/fileio/` (YAML/JSON-Persistenz)

- [ ] `BeamSplitterInteractionModel.to_dict()` / `from_dict()` implementieren
- [ ] Pfad-Konfiguration (`paths`-Dictionary) in Optic-Serialisierung aufnehmen
- [ ] Rückwärtskompatibilität: Bestehende `.optiland`-Dateien ohne `paths`-Schlüssel fehlerfrei laden
- [ ] Zemax-Import: Prüfen ob ZMX-Dateien mit Strahlenteiler-Flächen importiert werden können

---

## 9. GUI-Integration

**Dateien:** `optiland_gui/services/surface_service.py`,
             `optiland_gui/lens_editor.py`,
             `optiland_gui/system_properties_panel.py`

- [ ] `SurfaceService.AVAILABLE_SURFACE_TYPES` um `"beam_splitter"` erweitern
- [ ] Im Lens Editor (LDE): Neue Spalte oder Dropdown für `interaction_type = "beam_splitter"`
- [ ] Dialog für Strahlenteiler-Eigenschaften:
      - Split-Ratio (Schieberegler 0–100% Reflektion)
      - Pfad-Zuweisung: "Transmitted Path", "Reflected Path" (Dropdown mit Pfad-Namen)
- [ ] System-Properties-Panel: Anzeige aller definierten Pfade mit Surface-Liste
- [ ] `SurfaceService._get_interaction_type()` um Strahlenteiler-Erkennung erweitern
- [ ] Undo/Redo: Sicherstellen, dass Pfad-Konfiguration in den Command-Stack aufgenommen wird

---

## 10. Visualisierung

**Dateien:** `optiland/visualization/system/rays.py` (Rays2D, Rays3D),
             `optiland_gui/` (3D-Viewer)

### 2D-Visualisierung (Rays2D)
- [ ] `_process_traced_rays()` für Multi-Pfad-Ausgabe erweitern
- [ ] Jeden Pfad in anderer Farbe darstellen (z.B. Blau = Transmission, Rot = Reflektion)
- [ ] Legende mit Pfad-Namen einblenden

### 3D-Visualisierung (Rays3D / VTK)
- [ ] VTK-Linien für jeden Pfad separat erzeugen
- [ ] Strahlenteiler-Fläche in 3D als halbdurchsichtige Scheibe visualisieren
- [ ] Pfade können einzeln ein-/ausgeblendet werden (Checkbox in GUI)

### Systemzeichnung
- [ ] `draw()` und `draw3D()` auf Multi-Pfad-Systeme erweitern
- [ ] Beide optischen Arme in einer Darstellung zeigen

---

## 11. Tests

**Verzeichnis:** `tests/`

- [ ] Unit-Tests: `tests/test_beam_splitter_model.py`
      - `test_energy_conservation()`: R + T = 1.0 für alle Wellenlängen
      - `test_reflected_direction()`: Reflektierter Strahl erfüllt Reflexionsgesetz
      - `test_transmitted_direction()`: Transmittierter Strahl erfüllt Snell'sches Gesetz
      - `test_copy_independence()`: Beide Output-Ray-Sets sind unabhängig (kein Aliasing)
      - `test_serialization()`: `to_dict()` / `from_dict()` round-trip
- [ ] Integration-Tests: `tests/test_multi_path_optic.py`
      - `test_simple_beamsplitter_50_50()`: Einfaches 50:50-Strahlenteiler-System
      - `test_imaging_illumination_system()`: Abbildung + Beleuchtung kombiniert
      - `test_both_backends()`: numpy + torch (via `set_test_backend`-Fixture)
      - `test_trace_returns_dict()`: `optic.trace()` gibt `dict[str, RealRays]` zurück
- [ ] GUI-Tests: `tests/gui/test_beam_splitter_service.py`
      - Surface-Service erkennt Strahlenteiler-Typ korrekt
      - LDE zeigt Strahlenteiler-Eintrag korrekt an
- [ ] Regressions-Tests: Alle bestehenden Tests müssen weiterhin grün bleiben

---

## 12. Dokumentation & Beispiele

**Verzeichnis:** `docs/examples/`

- [ ] Notebook: `Tutorial_11_Beam_Splitter_Systems.ipynb`
      - Einfaches Mach-Zehnder-Interferometer als Einstiegsbeispiel
      - Abbildung + Beleuchtungs-System (der ursprüngliche Use-Case)
      - Visualisierung beider Pfade
- [ ] Docstrings für alle neuen Klassen und Methoden ergänzen
- [ ] `agents.md` um Hinweis auf Multi-Path-Architektur erweitern
- [ ] CHANGELOG / `_changes/` Eintrag erstellen

---

## Abhängigkeiten zwischen Phasen

```
Phase 2 (BeamSplitterModel)
    → Phase 3 (Ray Copy)
    → Phase 4 (Surface Dual-Output)
        → Phase 5 (SurfaceGroup Branching)
            → Phase 6 (Optic Multi-Arm)
                → Phase 7 (Paraxial Stubs)
                → Phase 8 (Serialisierung)
                → Phase 9 (GUI)
                → Phase 10 (Visualisierung)
                → Phase 11 (Tests – laufen parallel zur Implementierung)
                → Phase 12 (Docs – nach vollständiger Implementierung)
```

---

## Kritische Pfade / Risiken

| Risiko | Beschreibung | Maßnahme |
|--------|-------------|----------|
| Rückwärtskompatibilität | `trace()` gibt neu `dict` zurück → bricht alle Aufrufer | Typ-Union oder separates `trace_multi()` |
| Backend-Kompatibilität | `RealRays.copy()` muss für NumPy + PyTorch funktionieren | Expliziter Test für beide Backends |
| Paraxiale Analyse | EFL/BFD-Berechnung bricht bei Strahlenteiler | Klare Fehlermeldung + Fallback |
| GUI-Undo/Redo | Pfad-Konfiguration im Command-Stack | Pfad-Änderungen als eigene Commands kapseln |
| Zemax-Import | ZMX-Dateien nutzen andere Strahlenteiler-Konvention | Mapping-Tabelle erforderlich |
