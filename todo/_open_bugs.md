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
Nummer: O17.

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

### O14 – Faltung: der Lambert-Emitter der Beleuchtung ist nur die Spanne der Feldpunkte
- **Gefunden:** 2026-09-25 (RCR07-Gesamtsystem) · **Status:** geprüft
- **Ort:** `optiland/nonsequential/fold.py` `fold_paths` (Emitter aus `min`/`max` der Feldradien); `FoldSettings` in `optiland/nonsequential/system.py`
- **Befund:** Der Emitterring ist `min..max` der Beleuchtungs-Feldradien. Liegen die Felder als Stützstellen im Inneren des leuchtenden Rings (RCR07: 36 Gauss-Knoten in r², r 2.811..3.734 bei einem Ring DI5.30/DA7.70 = r 2.65..3.85), ist der Emitter stillschweigend zu schmal; der Innenrand bestimmt den dunklen Kern an der Hornhaut und damit die Reflexbewertung. Die GUI baut die Szene beim Öffnen aus den Pfaden neu, ein Nachpatchen der Szene in der `.olsys` hilft daher nicht.
- **Behandlung:** Offene Entscheidung: expliziter Emitterring als Faltungseinstellung (`FoldSettings`, neuer Schlüssel → nach der Formatregel `olsys_format_version` 2 und GUI-Version anheben) oder Apertur auf der Objektfläche (braucht Serialisierung in `ObjectSurface`). Bis dahin: zwei Felder mit Gewicht 0 an den Ringrändern (so im RCR07-Gesamtsystem). Regressionstest: Feldpunkte im Ringinneren plus deklarierter Ring → Emitter = deklarierter Ring.
