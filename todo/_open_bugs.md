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
Nummer: O14.

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

### O13 – Eine Dickenänderung legt das Objekt auf Fläche 1, wenn Fläche 1 nicht bei z = 0 liegt
- **Gefunden:** 2026-09-25 (RCR07-Gesamtsystem, Dateien eines externen Exporters) · **Status:** ausgeführt
- **Ort:** `optiland/optic/optic_updater.py` `OpticUpdater.set_thickness` (setzt Fläche 1 fest auf z = 0 und baut nur Flächen 1..n neu auf); `optiland/surfaces/object_surface.py` (`to_dict`/`_from_dict` ohne Objektdicke)
- **Befund:** Eine JSON-Datei mit Objekt bei z = 0 und Fläche 1 bei z = d > 0 lädt und rechnet richtig. Der erste `set_thickness(…, k ≥ 1)` (jede Dickeneingabe im Lens Data Editor) verschiebt Fläche 1 nach z = 0 und lässt das Objekt stehen: Objektabstand 0 statt d, ohne Meldung. Nachvollzogen mit `RCR07_Beobachtung_Fokus_550nm.json` (Downloads, RCR07-Paket): z vorher [0, 0.237, 0.795, …], nach `set_thickness(gleicher Wert, 2)` [0, 0, 0.558, …]; die Netzhaut rückt 0.237 mm vor, der Sensorfokus springt um ~1.4 mm. Optiland-eigene Dateien sind nicht betroffen (dort liegt Fläche 1 immer bei 0, das Objekt bei −d).
- **Behandlung:** Entweder beim Laden normieren (alle z um −z₁ verschieben, wenn die Achse global z ist) oder in `set_thickness` an der aktuellen z-Lage von Fläche 1 statt an 0 verankern. Regressionstest: Dict mit Objekt bei 0 und Fläche 1 bei 0.237, Dicke einer späteren Fläche neu setzen, Objektabstand muss 0.237 bleiben (NumPy und Torch). Umgangen im RCR07-Gesamtsystem durch normierte Pfadkopien.

### O14 – Faltung: der Lambert-Emitter der Beleuchtung ist nur die Spanne der Feldpunkte
- **Gefunden:** 2026-09-25 (RCR07-Gesamtsystem) · **Status:** geprüft
- **Ort:** `optiland/nonsequential/fold.py` `fold_paths` (Emitter aus `min`/`max` der Feldradien); `FoldSettings` in `optiland/nonsequential/system.py`
- **Befund:** Der Emitterring ist `min..max` der Beleuchtungs-Feldradien. Liegen die Felder als Stützstellen im Inneren des leuchtenden Rings (RCR07: 36 Gauss-Knoten in r², r 2.811..3.734 bei einem Ring DI5.30/DA7.70 = r 2.65..3.85), ist der Emitter stillschweigend zu schmal; der Innenrand bestimmt den dunklen Kern an der Hornhaut und damit die Reflexbewertung. Die GUI baut die Szene beim Öffnen aus den Pfaden neu, ein Nachpatchen der Szene in der `.olsys` hilft daher nicht.
- **Behandlung:** Offene Entscheidung: expliziter Emitterring als Faltungseinstellung (`FoldSettings`, neuer Schlüssel → nach der Formatregel `olsys_format_version` 2 und GUI-Version anheben) oder Apertur auf der Objektfläche (braucht Serialisierung in `ObjectSurface`). Bis dahin: zwei Felder mit Gewicht 0 an den Ringrändern (so im RCR07-Gesamtsystem). Regressionstest: Feldpunkte im Ringinneren plus deklarierter Ring → Emitter = deklarierter Ring.
