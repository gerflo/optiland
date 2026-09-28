# Offene Fehler in Optiland

Regel (vom Nutzer, 2026-09-22): **Jeder gefundene Fehler in Optiland
(`optiland/`, `optiland_gui/`, Werkzeuge), der nicht sofort behoben wird,
kommt hierher.** Ein Eintrag bleibt, bis der Fix committet ist, und wird im
selben Commit entfernt. Befund, Ursache, Fix und Tests stehen im Commit-Text
(`git log --grep "O<n>"`). Kein Eintrag wird gelöscht, weil er unbequem ist.
Nummern werden nie wiederverwendet; die nächste freie Nummer ist die höchste
je vergebene plus 1 (Datei, `git log -p -- todo/_open_bugs.md` und
`git log --grep "O[0-9]"` prüfen; ein Eintrag, der in derselben Sitzung
angelegt und behoben wurde, steht nur im Fix-Commit). Höchste vergebene
Nummer: O22.

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

### O22 – Frisches Dokument gilt nach dem JSON-Export als geändert
- **Gefunden:** 2026-09-28 (Tests zu O19; Nutzer sah den Speichern-Dialog
  in den Testläufen) · **Status:** ausgeführt (nur im Test, mit frischem
  `Untitled.olsys`; mit einer geöffneten, gespeicherten Datei tritt es
  nicht auf)
- **Ort:** `optiland_gui/services/file_service.py::FileService.save`
  (`aboutToSave`), `optiland_gui/system_properties_panel.py::_apply_changes`,
  `optiland_gui/nsq_panel.py::_rebuild_from_active_path`,
  `optiland_gui/services/nsq_service.py::sync_active_path`
- **Befund:** `connector.save_optic_to_file()` auf dem frischen Dokument
  sendet `aboutToSave`; die System Properties schreiben Name/Beschreibung
  per `set_metadata` zurück, der Connector wird danach als sauber markiert,
  aber der entprellte Rebuild des NSQ-Panels findet einen anderen
  Fingerabdruck als im gespeicherten Pfad und setzt `_dirty = True`. Etwa
  eine Sekunde später fragt jede „zerstörende“ Aktion (Öffnen, Schließen)
  „Save changes to 'Untitled.olsys'…?“, obwohl der Nutzer nichts geändert
  hat. Nachweis: Test `tests/gui/test_window_start.py::TestCommandLineFile::
  test_file_from_the_command_line_is_opened` mit `window.connector.
  save_optic_to_file` statt eines eigenen Connectors (Dialog-Watchdog der
  Fixture meldet den Dialog).
- **Behandlung:** Prüfen, warum `get_metadata`/`set_metadata` auf dem
  frischen Optic nicht symmetrisch sind (Name „Default System“ vs.
  Placeholder, Beschreibung `None` vs. `""`) bzw. den Pfad-Fingerabdruck
  nach `mark_current_state_clean()` mitziehen. Regressionstest: Export
  eines frischen Dokuments, 1,5 s Ereignisse, `_document_has_unsaved_changes()`
  muss `False` bleiben.
