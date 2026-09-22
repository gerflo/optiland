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
