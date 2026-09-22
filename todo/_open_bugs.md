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

### O2 – System-Tab: Matplotlib-Warnung „Ignoring fixed x/y limits…“ bei jedem Neuzeichnen nach Zoom/Pan
- **Gefunden:** 2026-09-22 (GUI-Log 16:04:51–16:04:53, vier Warnungen `matplotlib.axes._base: Ignoring fixed y limits to fulfill fixed data aspect with adjustable data limits.`) · **Status:** ausgeführt
- **Ort:** `optiland_gui/nsq_panel.py`, `NSQPanel._draw_layout` (Zeile ~742, `ax.set_aspect("equal", adjustable="datalim")`); `optiland_gui/widgets/plot_navigation.py` (`restore_view`, `on_scroll`, Pan über `drag_pan` setzen feste Grenzen)
- **Befund:** Die Achse des System-Tabs hat `adjustable="datalim"`; sobald Zoom, Pan oder `restore_view` feste Grenzen setzen (Autoscale aus), protokolliert Matplotlib bei jedem `apply_aspect` die Warnung. Nachvollzogen mit einem Skript (NSQPanel, Beispielszene, Grenzen setzen, `remember_view`, `_draw_layout(preserve_view=True)`): 2 Warnungen beim Zeichnen nach dem Zoom, 3 beim Neuzeichnen mit wiederhergestellter Ansicht. Die Analyseplots haben dasselbe Problem schon gelöst: `EqualAspectAxes` in `optiland/analysis/base.py` schaltet Autoscale während `apply_aspect` kurz ein, genau um diese Warnung zu vermeiden. Der System-Tab nutzt die Klasse nicht. Die Darstellung selbst stimmt; das Log füllt sich bei jeder Interaktion mit Rauschen, das echte Fehler verdeckt.
- **Behandlung:** In `_draw_layout` die Achse mit `self.layout_figure.add_subplot(111, axes_class=EqualAspectAxes)` anlegen (DRY, kein zweiter Mechanismus); das `ax.set_aspect("equal")` in `NSQViewer2D.view` (`optiland/nonsequential/visualization/viewer_2d.py:167`) lässt `adjustable` unverändert, die Zeile ~742 im Panel bleibt als Absicherung. Regressionstest in `tests/gui/test_nsq_panel.py`: Grenzen setzen, `remember_view`, `_draw_layout(preserve_view=True)`, `canvas.draw()`, kein Log-Eintrag von `matplotlib.axes._base` (`caplog`), die Achse füllt weiter die ganze Fläche (Regel „Plots füllen den verfügbaren Platz“), Ansicht bleibt erhalten.

### O3 – Nach fehlgeschlagenem Rebuild wird eine veraltete NSQ-Szene ohne Hinweis gespeichert und beim Öffnen gezeigt
- **Gefunden:** 2026-09-22 (GUI-Log: vier gescheiterte Rebuilds 15:52–15:53 (O1, inzwischen behoben), danach 15:54:35 „Saved — RCR-27 Beleuchtung - Asphericon OL.olsys“) · **Status:** geprüft
- **Ort:** `optiland_gui/services/nsq_service.py`, `sync_active_path` (Zeile ~323) und `load_file` (Zeile ~399); `optiland/nonsequential/system.py`, `MultiAxisSystem.from_dict` / `to_json`
- **Befund:** `sync_active_path` übernimmt die Änderung in den Pfad auch dann, wenn `rebuild()` scheitert (gewollt, damit Speichern nichts verliert); die alte Szene bleibt stehen. `save_file` schreibt beides, Pfad-Optik und alte Szene, und setzt `_dirty = False`. `load_file` → `MultiAxisSystem.from_json` baut die Szene nicht neu und prüft nicht, ob sie zur Pfad-Optik passt. Nach Speichern und erneutem Öffnen zeigt der System-Tab (und jede NSQ-Strahlverfolgung) also stillschweigend eine Szene, die nicht zum gespeicherten Design gehört; der Fehler-Toast der letzten Sitzung ist der einzige Hinweis gewesen.
- **Behandlung:** Offene Entscheidung für den Nutzer: (a) Szene als „veraltet“ markieren (Flag im Speicherstand, Hinweis im System-Tab und beim Speichern/Öffnen), oder (b) beim Öffnen neu bauen und bei Misserfolg warnen, oder (c) Speichern nach gescheitertem Rebuild mit Rückfrage. Bei (a) klären, ob ältere GUIs die Datei noch lesen (Regel `olsys_format_version`: nur erhöhen, wenn nicht). Regressionstest: Pfad-Änderung, die den Rebuild scheitern lässt (z. B. per Monkeypatch), speichern, öffnen → der Zustand „Szene veraltet“ ist sichtbar bzw. die Szene passt zur Pfad-Optik.

### O4 – System-Tab zeigt Maskenblenden nicht rot wie das 2D/3D-Layout
- **Gefunden:** 2026-09-22 (Rest von O1: die NSQ-Umwandlung baut Masken seit dem O1-Fix als Absorber `S<i>.mask` ein, gezeichnet werden sie aber wie jeder Absorber) · **Status:** geprüft
- **Ort:** `optiland/nonsequential/visualization/renderers/surface.py` (Farbe `"absorbing": (0.2, 0.2, 0.2)`), `optiland/nonsequential/surface_conversion.py` (`add_optic_surfaces`, Komponente `f"{name}.mask"`)
- **Befund:** Im 2D/3D-Layout sind Maskenblenden rot (`MASK_COLOR` in `optiland/visualization/system/system.py`); im System-Tab erscheint die blockierende Scheibe bzw. der Ring dunkelgrau wie Randblenden, der Nutzer erkennt die Maske dort nicht als solche.
- **Behandlung:** Den Masken-Absorber kennzeichnen (z. B. Attribut oder Namensendung `.mask`, dann in der Serialisierung mitführen) und im 2D/3D-Renderer des System-Tabs in `MASK_COLOR` zeichnen. Regressionstest: Szene mit Circular Mask, der gezeichnete Absorber hat die Maskenfarbe, eine Randblende nicht.

### O5 – System-Tab, Reiter Detectors: Karte klein an den rechten Rand gedrückt, Titel läuft über
- **Gefunden:** 2026-09-22 (Screenshot `tools/gui_screenshot.py --panel system --dock-only --trace --all-tabs` mit `RCR-27 Beleuchtung - Asphericon OL.olsys`, Canvas ca. 690 x 140 px; auf HEAD vor den Fixes des Tages identisch) · **Status:** ausgeführt
- **Ort:** `optiland_gui/nsq_panel.py`, `NSQPanel._draw_detectors` (`imshow(..., aspect="equal")`, `colorbar(fraction=0.046, pad=0.03)`, Titel `"{name}: {flux} W, {n} rays"`)
- **Befund:** Bei einem flachen Canvas schrumpft die Achse wegen `aspect="equal"` auf die Höhe, die Constrained-Layout-Zelle samt Farbskala bleibt breit, und die Karte landet klein am rechten Rand; der Titel ist breiter als die Achse und wird rechts abgeschnitten. Verstößt gegen die Regel „Plots füllen den verfügbaren Platz“.
- **Behandlung:** Karte und Farbskala zusammen zentrieren bzw. die Farbskala an die Achse binden (`make_axes_locatable` oder `ax.inset_axes`), Titel kürzen oder umbrechen. Regressionstest in `tests/gui/test_nsq_panel.py`: flacher Canvas (z. B. 690 x 140 px), Achse horizontal zentriert, Titel innerhalb der Figur.
