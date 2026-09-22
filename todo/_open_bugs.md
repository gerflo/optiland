# Offene Fehler in Optiland

Regel (vom Nutzer, 2026-09-22): **Jeder gefundene Fehler in Optiland
(`optiland/`, `optiland_gui/`, Werkzeuge), der nicht sofort behoben wird,
kommt hierher.** Ein Eintrag bleibt, bis der Fix committet ist, und wird im
selben Commit entfernt. Befund, Ursache, Fix und Tests stehen im Commit-Text
(`git log --grep "O<n>"`). Kein Eintrag wird gelöscht, weil er unbequem ist.
Nummern werden nie wiederverwendet; die nächste freie Nummer ist die höchste
je vergebene plus 1 (Datei und `git log -p -- todo/_open_bugs.md` prüfen).

Die Kennung ist `O<n>` (O wie Optiland), damit sie nicht mit den
Fehlernummern `B<n>` von Optomal verwechselt wird; Optomal führt seine Liste
im eigenen Repo (`optomal-code/optomal-dev/todo/_open_bugs.md`).

Abarbeiten mit dem Skill `/bugfix` (alle offenen) oder `/bugfix O3 O4`.

Format eines Eintrags:

```
### O<n> – <kurzer Titel>
- **Gefunden:** <Datum> (<Anlass>) · **Status:** geprüft | ausgeführt | gelesen
- **Ort:** <Dateien, Funktionen>
- **Befund:** <was falsch ist, wie man es sieht>
- **Behandlung:** <geplanter Fix, Regressionstest, offene Entscheidung>
```

Status: **ausgeführt** = mit einem Lauf nachvollzogen, **geprüft** = im Code
nachgesehen, **gelesen** = nur aus einem Bericht, vor dem Fix reproduzieren.

## Offen

### O3 – Nach fehlgeschlagenem Rebuild wird eine veraltete NSQ-Szene ohne Hinweis gespeichert und beim Öffnen gezeigt
- **Gefunden:** 2026-09-22 (GUI-Log: vier gescheiterte Rebuilds 15:52–15:53 (O1, inzwischen behoben), danach 15:54:35 „Saved — RCR-27 Beleuchtung - Asphericon OL.olsys“) · **Status:** geprüft
- **Ort:** `optiland_gui/services/nsq_service.py`, `sync_active_path` (Zeile ~323) und `load_file` (Zeile ~399); `optiland/nonsequential/system.py`, `MultiAxisSystem.from_dict` / `to_json`
- **Befund:** `sync_active_path` übernimmt die Änderung in den Pfad auch dann, wenn `rebuild()` scheitert (gewollt, damit Speichern nichts verliert); die alte Szene bleibt stehen. `save_file` schreibt beides, Pfad-Optik und alte Szene, und setzt `_dirty = False`. `load_file` → `MultiAxisSystem.from_json` baut die Szene nicht neu und prüft nicht, ob sie zur Pfad-Optik passt. Nach Speichern und erneutem Öffnen zeigt der System-Tab (und jede NSQ-Strahlverfolgung) also stillschweigend eine Szene, die nicht zum gespeicherten Design gehört; der Fehler-Toast der letzten Sitzung ist der einzige Hinweis gewesen. Dasselbe gilt für Szenen, die ein älterer Konverter gebaut hat: `RCR-27 Beleuchtung - Asphericon OL.olsys` enthält seit 16:43 den Rand `S4.rim` der Pilzblende mit Radius `inf` (Maske mit unendlichem Klarradius, Konverter behoben am 2026-09-22, siehe `git log --grep "infinite clear radius"`); nach dem Öffnen zeichnet der System-Tab ihn weiter mit NaN-Warnungen, bis eine Änderung im Lens Data Editor neu baut. Spricht für (b).
- **Behandlung:** Offene Entscheidung für den Nutzer: (a) Szene als „veraltet“ markieren (Flag im Speicherstand, Hinweis im System-Tab und beim Speichern/Öffnen), oder (b) beim Öffnen neu bauen und bei Misserfolg warnen, oder (c) Speichern nach gescheitertem Rebuild mit Rückfrage. Bei (a) klären, ob ältere GUIs die Datei noch lesen (Regel `olsys_format_version`: nur erhöhen, wenn nicht). Regressionstest: Pfad-Änderung, die den Rebuild scheitern lässt (z. B. per Monkeypatch), speichern, öffnen → der Zustand „Szene veraltet“ ist sichtbar bzw. die Szene passt zur Pfad-Optik.

### O4 – System-Tab zeigt Maskenblenden nicht rot wie das 2D/3D-Layout
- **Gefunden:** 2026-09-22 (Rest von O1: die NSQ-Umwandlung baut Masken seit dem O1-Fix als Absorber `S<i>.mask` ein, gezeichnet werden sie aber wie jeder Absorber) · **Status:** geprüft
- **Ort:** `optiland/nonsequential/visualization/renderers/surface.py` (Farbe `"absorbing": (0.2, 0.2, 0.2)`), `optiland/nonsequential/surface_conversion.py` (`add_optic_surfaces`, Komponente `f"{name}.mask"`)
- **Befund:** Im 2D/3D-Layout sind Maskenblenden rot (`MASK_COLOR` in `optiland/visualization/system/system.py`); im System-Tab erscheint die blockierende Scheibe bzw. der Ring dunkelgrau wie Randblenden, der Nutzer erkennt die Maske dort nicht als solche. Dasselbe gilt seit 2026-09-22 für die abgeschattete Mitte einer Ringblende (`RadialAperture` mit `r_min > 0`): im 2D/3D-Layout rot wie eine Maske (`_blocked_zone`), im System-Tab die graue Scheibe `S<i>.obscuration`.
- **Behandlung:** Masken- und Ringblenden-Absorber (`.mask`, `.obscuration`) kennzeichnen (z. B. Attribut oder Namensendung, dann in der Serialisierung mitführen) und im 2D/3D-Renderer des System-Tabs in `MASK_COLOR` zeichnen. Regressionstest: Szene mit Circular Mask und Ringblende, beide Absorber haben die Maskenfarbe, eine Randblende nicht.

### O5 – System-Tab, Reiter Detectors: Karte klein an den rechten Rand gedrückt, Titel läuft über
- **Gefunden:** 2026-09-22 (Screenshot `tools/gui_screenshot.py --panel system --dock-only --trace --all-tabs` mit `RCR-27 Beleuchtung - Asphericon OL.olsys`, Canvas ca. 690 x 140 px; auf HEAD vor den Fixes des Tages identisch) · **Status:** ausgeführt
- **Ort:** `optiland_gui/nsq_panel.py`, `NSQPanel._draw_detectors` (`imshow(..., aspect="equal")`, `colorbar(fraction=0.046, pad=0.03)`, Titel `"{name}: {flux} W, {n} rays"`)
- **Befund:** Bei einem flachen Canvas schrumpft die Achse wegen `aspect="equal"` auf die Höhe, die Constrained-Layout-Zelle samt Farbskala bleibt breit, und die Karte landet klein am rechten Rand; der Titel ist breiter als die Achse und wird rechts abgeschnitten. Verstößt gegen die Regel „Plots füllen den verfügbaren Platz“.
- **Behandlung:** Karte und Farbskala zusammen zentrieren bzw. die Farbskala an die Achse binden (`make_axes_locatable` oder `ax.inset_axes`), Titel kürzen oder umbrechen. Regressionstest in `tests/gui/test_nsq_panel.py`: flacher Canvas (z. B. 690 x 140 px), Achse horizontal zentriert, Titel innerhalb der Figur.

### O7 – Eine Constrained-Layout-Warnung bleibt beim Öffnen einer .json in ein offenes System
- **Gefunden:** 2026-09-22 (GUI-Log 16:42:57 direkt nach „Opened — RCR-03 Beleuchtung - Asphericon OL.json“: `run_gui.py:97: UserWarning: constrained_layout not applied because axes sizes collapsed to zero`; die GUI lief seit 16:41 mit 6dc60e96) · **Status:** gelesen
- **Ort:** `optiland_gui/nsq_panel.py` (`layout_figure`, `detector_figure`, die einzigen Figuren mit `layout="constrained"`), `_request_draw` und `eventFilter` (Zeichnen beim Show-Ereignis)
- **Befund:** 6dc60e96 hat die Warnung für verdeckte Canvases beseitigt (vorher zwei beim Öffnen und fast eine bei jeder Bearbeitung); eine einzelne bleibt beim Öffnen einer .json. Vermutung: ein Canvas wird beim Show-Ereignis gezeichnet, bevor das Layout ihm seine endgültige Größe gegeben hat, oder er ist sichtbar, aber sehr klein (System-Dock zusammengeschoben). Nicht nachvollzogen.
- **Behandlung:** Den Ablauf „System offen → File → Open .json → Pfad 1 füllen“ in einem GUI-Test oder mit `tools/gui_screenshot.py` nachstellen, die Warnung mit `warnings.catch_warnings(record=True)` fangen und die Ursache bestimmen; Regressionstest in `tests/gui/test_nsq_panel.py`, Regel „Plots füllen den verfügbaren Platz“ beachten.
