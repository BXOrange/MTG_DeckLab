# SmartBot 2 — Validierung und Liefergrenzen (PLR-15)

Stand: 22.10.2026. Implementierung: [SMART_BOT.md](SMART_BOT.md#smart-bot-2--independent-mechanic-and-style-policy).
Die [ursprüngliche Deckanalyse](SMART_BOT_DECK_AUDIT.md) bleibt die historische
Baseline; ihre Kartenwerte sind keine Messung der neuen Politik.

## Ergebnis und Bedeutung

Die neue Politik erfüllt die mechanischen Abnahmefälle für Rollen/Stile,
Namensunabhängigkeit, tatsächlichen Aktions-/Kosten-/Zielertrag, Combat,
Timing, alternative Ziele, Geheimhaltung und Lebenszyklus. Sie ist eine
begrenzte Heuristik. Aus den folgenden kleinen Fixture-Kampagnen folgt keine
allgemeine Commander- oder cEDH-Siegquote.

- Vollständige Backend-Prüfung einschließlich `--full-cache`: **15.682 passed,
  1 skipped**; lokale Proxytests liefen mit erlaubtem Loopback-Testserver.
- Abschließende spezifische SmartBot-2-Abnahme: **67 passed**. Darunter echte
  Engine-Siege über Combat sowie Oracle/Consultation und Oracle/Pact, ein
  echter Mana-/Untap-Motor, variable Devotion-Schwellen, zwei unterschiedliche
  Typal-Realisierungen unter absichtlich unpassendem Archetyp-Tag, funktional
  gleiche Karten mit verschiedenen Namen/Stückzahlen und eine 256-Kreaturen-
  Token-Armee. Zusätzliche Engine-Regressionen prüfen Rückseitenzahlung und
  die Reservierung einer zum Aktivieren benötigten Tap-Ressource.
- Ein früher Gesamtlauf fand veraltete Registry-Erwartungen ohne `smart2` und
  Sandbox-Socketbeschränkungen. Die Erwartungen wurden an die bereits
  vorhandene Registry angepasst; die vollständigen Folgeläufe bestanden.

## Vergleichsmethode

Der Runner `backend/scripts/benchmark_smart_bot2.py` verwendet echte
interaktive Zweispieler-Sessions, einen unveränderten Greedy-Gegner mit
festem Kreaturendeck, feste Start-/Mulligan-/Rules-Seeds, getrennte Profile
und kontrollierte Allocation-IDs. Wiederholte Läufe desselben Seeds werden
per Aktionstrace verglichen; ein anderer Seed muss eine andere Startfolge
ergeben. Gemessen wird die Zeit in `decide`, einschließlich Parameter- und
Combat-Auswahl, **ohne** Session-Aufbau, Profilaufbau, View-Erzeugung oder
Engine-Ausführung. Daher sind die Zahlen keine API-Antwortzeit.

Baseline 1 ist die unveränderte `smart`-Politik. Baseline 2 ist eine explizit
gesicherte historische `smart2.py`, geladen über `--baseline-source`.
Alle Politiken eines Vergleichs benutzen dieselbe Engine und dieselben
Startbedingungen. Das Verfahren kann auch ohne historische Quelle laufen;
dann wird Baseline 2 nicht erfunden.

Es gibt getrennte Entwicklungs-, Validierungs- und Testgruppen. Die Testgruppe
enthält andere statische Kosten/Körper und ein zusätzliches Support-Paket
(Vigilance und Attack→Scry), also neue Kombinationen bekannter Fähigkeiten.
Weder Decknamen noch Commander-Namen werden zu Strategiegewichten.
Zusätzlich prüfen Entscheidungstests Namen-/Reprint-Austausch, inkonsistente
Tags, alternative Spielstile desselben Archetyps und geänderte verdeckte
Informationen. Spellbook kann für Ablationen durch `combos=[]`, benannte
Katalogsignale durch `named_signals=False` abgeschaltet werden.

Die Gruppen sind synthetische Mechanikdecks, keine repräsentative Stichprobe
kompetitiver Commander-Listen. Ein Test pro Familie und ein fester Gegner
reichen nicht für statistische Überlegenheitsbehauptungen. Die Testgruppe
benutzt Seed 0 und die erste Startposition; die separate Validierung mit
zwei Seeds enthält beide Startpositionen. Mehrspieler-Podstärke wurde nicht
als Ergebnis dieser Kampagne gemessen. Ein echter Drei-Spieler-Sieg und gezielte
Prioritäts-/Rebuild-/Restart-/Undo-/Takeback-Tests sichern die Integration.

## Zurückgehaltene Mechanikgruppe

17 Familien × 3 Politikstände × 1 Seed = **51 Partien**.
Budget: 600 Driver-Aktionen und 24 einzelne Spielerzüge je Partie.
Alle verwendeten Fixture-Texte wurden von der Engine als MODELED erkannt;
kein Parser-Blocker wurde für eine bessere Quote aus dem Nenner entfernt.

| Familie | SmartBot 1 | bisheriger SmartBot 2 | neuer SmartBot 2 |
| --- | --- | --- | --- |
| aggro | Sieg | Sieg | Sieg |
| alternate-win | Sieg | Sieg | Sieg |
| burn | Sieg | Sieg | Sieg |
| combo | Aktionsbudget | Aktionsbudget | Sieg |
| control | Sieg | Sieg | Sieg |
| counters | Sieg | Sieg | Sieg |
| graveyard | Sieg | Sieg | Sieg |
| lands | Sieg | Sieg | Sieg |
| midrange | Sieg | Sieg | Sieg |
| mill | Sieg | Sieg | Sieg |
| ramp | Sieg | Sieg | Sieg |
| sacrifice | Niederlage | Niederlage | Sieg |
| spells | Sieg | Sieg | Sieg |
| stax | Sieg | Sieg | Sieg |
| tempo | Sieg | Sieg | Sieg |
| tokens | Sieg | Sieg | Sieg |
| voltron | Sieg | Sieg | Sieg |

**Summen:** beide Baselines 15 Siege, eine Niederlage und ein Aktionsbudget-
Abbruch; Kandidat 17 Siege. Kein Aktionsfehler, kein Stillstand und keine
abgewiesene Aktion in dieser Gruppe. Das Aktionsbudget wird separat gezählt,
nicht als normale Niederlage umetikettiert.

Der zusätzliche Validierungssatz über die ursprünglichen 14 Familien mit
je zwei Seeds umfasste 84 Partien: Kandidat 28 Siege, jede Baseline 26 Siege
und zwei Niederlagen; ebenfalls keine Aktionsablehnung. Dieser Satz diente
der Validierung, nicht dem unabhängigen Nachweis einer allgemeinen Gewinnrate.

## Bekannte gespeicherte Decks

Die 63 gespeicherten Listen sind schon aus der Analyse bekannt und bleiben
**Regressionsdaten**, kein unabhängiger Holdout. Vier als Cube markierte Pools
wurden nicht als normale Spiele gewertet. Bei Sans Soleil MWI fehlt weiterhin
Erebor Heirloom im lokalen Cache; seine Identität wurde nicht ersetzt oder
still aus der Liste entfernt. Die Profilinventur erfasst diese Datenlücke.

Der breite Kurzlauf umfasst die übrigen **58 Listen × 3 Politikstände =
174 Partien**, jeweils Seed 0, 150 Aktionen und sechs einzelne Spielerzüge.
Die unveränderten Baselines und der Kandidat hatten jeweils eine Niederlage
und 57 Zugbudget-Abbrüche. Dieser kurze Horizont prüft Start-/Aktionsstabilität
und ist für Aussagen über die Gewinnpläne dieser Decks ausdrücklich zu kurz.

Der Lauf deckte in einer Kandidatenpartie wiederholte Aktivierungsablehnungen
an einer Tap-Manaquelle auf. Eine längere Diagnose betraf denselben allgemeinen
Ressourcenkonflikt auch bei anderen Ländern. Die Ursache lag in der gemeinsamen
Engine: die automatische Zahlung konnte eine Quelle tappen, deren Tap noch
zur Aktivierung gehörte. Der Manaplaner reserviert jetzt diese Quelle und
gewählte Tap-/Crew-Ressourcen sowohl bei der Angebotsprüfung als auch bei der
Ausführung. Beide Seiten der Regression sind getestet (keine Doppelzahlung;
korrekte Ausführung mit zweiter Quelle).

Nach dieser Korrektur wurden die vier betroffenen Deckfälle erneut mit allen
drei Politiken und dem längeren Budget von 300 Aktionen / zwölf Spielerzügen
geprüft: **12 Partien ohne Ablehnung oder Ausnahme**. Kandidat: vier Zugbudget-
Abbrüche; Baselines: jeweils eine Niederlage und drei Zugbudget-Abbrüche.
Das ist eine gezielte Zahlungsregression und ersetzt keinen längeren
Turniervergleich der 58 Listen.

Zusätzlich reproduzierte die Kampagne eine vorhandene Rückseiten-Casting-
Lücke: ein Angebot war über Mana-Potenzial bezahlbar, der Ausführungspfad
prüfte jedoch den realen Pool vor dem Tappen. Back/Fuse nutzt jetzt vor der
Prüfung den vorhandenen Auto-Tap-Hook mit den Kosten der gewählten Seite.
Eine Gegenprobe mit falscher Manafarbe bleibt illegal und tappt kein Land.

## Laufzeit

Referenzsystem der Kampagnen: macOS 27.0.1 / arm64, Python 3.13.7,
zehn logische CPUs, drei Benchmarkworker.

| Vergleich | höchstes partieweises p95 in `decide` beim Kandidaten |
| --- | ---: |
| 17-Familien-Testgruppe | 1.418 ms |
| 58-Deck-Kurzregression | 1.076 ms |
| Zahlungs-Gegenprobe | 0.706 ms |

Dies liegt in diesen Messungen unter dem vorgeschlagenen 100-ms-p95-Ziel.
Die Such-/Kandidatenbudgets begrenzen Arbeit; eine harte universelle
250-ms-Garantie für beliebig große gemischte Boards wird daraus nicht
abgeleitet. Die 256er-Token-Gegenprobe prüft den gruppierten Pfad separat.

## Explizite Grenzen

- Effekt-/Rollenextraktion bleibt heuristisch; sie ersetzt weder Parser-IR
  noch Rules Engine und verändert kein Coverage-Verdikt.
- Kurze Projektionen simulieren nur bekannte mechanische Teilwirkungen;
  sie suchen keine vollständigen Partien und erfinden keine Draws.
- Komplexe Doomsday-Piles, beliebige Storm-/Breach-/Food-Chain-Linien und
  alle denkbaren bedingten Siege werden nicht als universell gelöst
  ausgewiesen. Unverstandene Spellbook-Prosa bleibt Assembly-Hinweis.
- Proliferate wurde nach dieser Benchmark-Kampagne auf echte Empfängerauswahl
  umgestellt. Smart1/Smart2 und die änderbare Frontend-Vorauswahl teilen die
  Bewertung aller Markenarten je Empfänger. Gezielte Engine-/Policy-Tests und
  ein Chromium-Test prüfen Auswahl, gemischte Marken, Wiederholungen und
  Bestätigung. Die obigen Match-Ergebnisse werden dadurch nicht rückwirkend
  als Messung der neuen Proliferate-Strategie ausgegeben.
- Combat bleibt eine begrenzte Schätzung; seltene Keywords, große gemischte
  Boards und komplexe Politik können darüber hinausgehen.
- Eine breitere unabhängige Deck-/Gegnermatrix mit genügend Seeds für
  belastbare Unsicherheitsintervalle ist für eine Stärke- oder Default-
  Entscheidung erforderlich. Der Default bleibt `smart`.

## Reproduktion und Provenienz

Die Standalone-CLI schreibt `manifest.json`, `matches.jsonl` und `summary.json`
unter `--output`. Das Manifest enthält Politikstände, Quelldatei-Fingerabdrücke,
Deck-Fingerprints, Ausschlüsse, Hardware, Seeds und Budgets. Die Matches führen
Familie/Split, echte Endzustände, unmodeled Kartentexte, Ablehnungen und
Zensierungen. Große lokale Deck-/Replay-Diagnosedaten bleiben unversioniert.

Die hier ausgewerteten lokalen Artefakte liegen unter
`/tmp/plr15-frozen-test`, `/tmp/plr15-frozen-local` und
`/tmp/plr15-payment-recheck`; die rohe historische Politik unter
`/tmp/plr15-baseline/smart2.py`. Für eine langfristige Wiederholung kann
`--baseline-source` auf eine archivierte, vertrauenswürdige Ausgangsrevision
zeigen. Die Quellfingerabdrücke in den Kampagnenmanifests sind maßgeblich für
den jeweiligen Lauf; abschließende Face-/Mengen-/Schwellen-/Typal-Verträge
werden zusätzlich durch die spezifische Abnahmesuite abgesichert.

```bash
cd backend
venv/bin/python -m pytest -q --full-cache
venv/bin/python -m pytest -q tests/services/test_smart_bot2.py
```

Die neuen Unterlagen beschreiben gelieferte Bot-Fähigkeiten und zwei
Ausführungskorrekturen. Sie behaupten keine neu unterstützten Parserfamilien
oder veränderte Commander-Coverage.
