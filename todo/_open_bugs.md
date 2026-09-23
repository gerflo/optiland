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

### O10 – Blenden-Editor setzt die Apertur bei jedem Tastendruck und meldet per print
- **Gefunden:** 2026-09-23 (GUI-Log 09:52–09:54: „Aperture updated: float_by_stop_size, 0.6 / 40.6 / 4.6 / 4.0 / 4.5“ als nackte stdout-Zeilen) · **Status:** geprüft
- **Ort:** `optiland_gui/system_properties_panel.py`, Blenden-Editor `init_ui` (Signalverdrahtung um Zeile 481) und `apply_aperture_changes` (um Zeile 509)
- **Befund:** `spnApertureValue.valueChanged` ist ohne `setKeyboardTracking(False)` mit `apply_aperture_changes` verbunden: jede Zwischeneingabe (40.6 beim Tippen von 4.5) wird auf die Optik gesetzt und löst per `opticChanged` Neuzeichnen und Trace aus; der Knopf „Apply Aperture Changes“ ist damit überflüssig. Erfolg und Fehler (`ValueError`) gehen per `print` auf stdout statt über den Logger bzw. den Toast wie im Rest der GUI.
- **Behandlung:** Keyboard-Tracking abschalten oder nur `editingFinished` und den Knopf anschließen; `print` durch `logger.info`/`logger.warning` plus Toast ersetzen. Test: Tippen von „4.5“ in das Feld setzt die Apertur genau einmal (Zähler auf `opticChanged`), ein ungültiger Wert erzeugt eine Logger-Meldung und keine stdout-Ausgabe.
