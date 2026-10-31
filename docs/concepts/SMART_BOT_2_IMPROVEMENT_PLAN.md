# SmartBot 2: umfassender Verbesserungsplan

**Status:** Unter PLR-15 umgesetzt als begrenzte, mechanik- und stilbasierte Politik. [Implementierte Fähigkeiten](../Reference/SMART_BOT.md#smart-bot-2--independent-mechanic-and-style-policy) und [Validierung mit Grenzen](../Reference/SMART_BOT_2_VALIDATION.md) sind für den Lieferstand maßgeblich. Das folgende Design hält Zielbild und Abnahmevertrag vom 22.10.2026 fest. Grundlage: [deckweiser Vergleich der 63 gespeicherten Listen](../Reference/SMART_BOT_DECK_AUDIT.md) und aktueller Code. Die Arbeitspakete unten sind eine vorgeschlagene Reihenfolge innerhalb dieses Vorhabens, keine Umpriorisierung des Projektbacklogs. Ihre Abnahmekriterien sind vorgeschlagene Lieferbedingungen.

## 1. Ziel und Umfang

SmartBot 2 soll den Gewinnplan eines Decks in konkrete, legale Spielentscheidungen übersetzen: entwickeln, Ressourcen reservieren, Trigger nutzen, Ziele und Kosten passend auswählen und erkannte Gewinnsequenzen ausführen. Er soll auf unbekannte Kartenkombinationen und Commander übertragen und auch ohne bekannte Combo solide spielen.

Dafür wird aus der heutigen zusätzlichen `_card_value`-Schicht eine eigenständige Strategiepolitik. Entwicklungs- und Abnahmeeinheit sind Archetypen, Spielstile und mechanische Entscheidungsmuster. Die 59 regulären gespeicherten Listen sind ein bereits untersuchter Regressionssatz, kein repräsentativer Trainings- oder Generalisierungsnachweis. Die vier Cube-/Testpools dienen als Extraktions- und Belastungsfälle. Die Umsetzung priorisiert übertragbare Fähigkeiten nach ihrer Bedeutung über Strategiefamilien hinweg; Karten- und Commander-Namen bestimmen weder Gewichtstabellen noch die Implementierungsreihenfolge.

**Erfolg:** messbar weniger verpasste Planaktionen und Abschlüsse, sinnvollere Ziele/Kosten/Angriffe, reproduzierbare Entscheidungen und bessere gepaarte Spielergebnisse ohne Verluste bei Legalität, Geheimhaltung und Laufzeit. Eine bloße Steigerung von Rollenwerten oder Combo-Assembly-Zahlen reicht nicht.

SmartBot 1 (`smart`) bleibt als Vergleich verfügbar; `smart2` behält seine Kennung. Goldfish, Greedy, ManaMaximizer und AI-Bot ändern ihre Politik durch diesen Umbau nicht. Insbesondere bleibt die heutige Standardauswahl zunächst erhalten. Eine spätere Änderung des Defaults ist eine separate Produktentscheidung nach Auswertung.

## 2. Belegte Ausgangsprobleme

| Befund | Konsequenz | Geplante Lösung |
| --- | --- | --- |
| Bei 23/63 Listen gleiche Nichtland-Grundwerte | Version 2 bietet dort im gemessenen Profil keinen Scoring-Vorteil | Gemeinsames, tatsächlich erzeugtes Rollenmodell |
| `spells`- und `lands`-Bonusrollen werden nicht erzeugt | Ganze Strategiefamilien bleiben wirkungslos | Erzeuger/Verbraucher-Vertrag, Katalogintegration |
| Auto-Tags `graveyard`/`sacrifice` werden `midrange` | Reanimator/Aristocrats bekommen falsche Philosophie | Explizite Alias-/Familienzuordnung |
| Alle Combo-Pieces werden von Angriffen ausgeschlossen | Malcolm, Dorks und Attack-Combos verlieren ihren Normalplan | Kontextabhängiger Opportunitätswert statt Sperre |
| Combat-, Timing- und Choice-Logik werden unverändert geerbt | Neue Werte beseitigen die wesentlichen Fehler nicht | Eigene SmartBot2-Hooks für alle Entscheidungstypen |
| Quellkartenwert bestimmt Ziel und Opfer | Gisa, Dina, Polymorph, Equipment und Rekursion werden falsch beurteilt | Effekt- und ertragsbezogene Auswahl |
| Oracle-Spezialfall kennt nur Consultation | Alternative Ausführungen derselben Gewinnidee bleiben unvollständig | Mechanisch beschriebene Voraussetzungen und Sequenzoperatoren; Sonderfälle separat ausweisen |
| X wird über Greedy `_fill_in` grundsätzlich auf `max_x` gesetzt | Maximaler Einsatz kann Anschlussaktion oder Schutz verhindern | Wenige sinnvolle X-/Kostenvarianten vergleichen |
| Mehrere Rollen werden unbeschränkt addiert | Reminder-Text und Mehrfachrollen dominieren reale Wirkung | Evidenz, getrennte Effekte und begrenzte Bonusfamilien |
| Vorhandene Dynamikanalyse misst vor allem Goldfish/Assembly | Keine belastbare Aussage über interaktive Spielqualität | Szenarien und gepaarte Bot-vs-Bot-Kampagnen |

Die Ursachen sind vor Gewichtsoptimierung zu beseitigen. Der Report ist eine statische Bestandsaufnahme mit ausgeführten Score-Proben; seine Urteile werden durch Gameplay-Szenarien geprüft und bei Gegenbelegen korrigiert.

## 3. Bestehende Bausteine weiterverwenden

- `services/archetype_database.py` und `data/archetypes.json`: bereits vorhandene Archetypen, Philosophien, Signalkarten und typische Wincondition-Karten. Kein zweiter konkurrierender Archetypenkatalog.
- `services/archetype_analysis.py`: `score_archetypes` und `detect_typal_signals` liefern zusätzliche Decksignale. Die dortigen Prozentwerte sind heuristische Scores, keine kalibrierten Wahrscheinlichkeiten.
- `services/bot_strategy.py`: Normalisierung, Deckprior, Commander-/Mengenwissen und lokale Spellbook-Matches. Die bisherige öffentliche Schnittstelle bleibt für SmartBot 1 und AI-Bot stabil.
- `Bot.decide`, Registry und `run_bots`: Prioritäts-/Choice-Dispatcher, Fehlerfeedback und kontrollierter Aktionspfad bleiben die Grundlage.
- `GameSession.view(perspective=…)`, `legal_actions`, `pending_choice`, `mana_potential`: einzige Laufzeit-Informationsquelle für die Politik.
- `game/engine/legal_actions_mixin.py`: vorhandene Angebote für Ziele, Cast-Alternativen, X, Kicker sowie Sacrifice-/Tap-Kosten. Fähigkeiten werden zuerst gegen diese Angebote geprüft, bevor neue View-Felder vorgeschlagen werden.
- Engine-Zufall über `rng_seed`/`rng_counter` ist bereits vorhanden. Initiale Shuffles, globale Zufallsquellen und prozessabhängiges `hash()` müssen im Vergleichsharness zusätzlich kontrolliert werden.
- `services/dynamic_analysis.py`: Metriken und Begrenzungen möglichst wiederverwenden; interaktive Benchmarks brauchen einen eigenen Runner, weil passive Goldfish-Gegner gegnerische Turns/Timing nicht abdecken.

## 4. Zielarchitektur

```text
Eigenes Setupdeck + Archetypenkatalog + lokaler Spellbook-Snapshot
                              ↓
                    versioniertes Deckprofil
                              ↓
Redigierte View + legale Angebote → Entscheidungskontext + aktive Pläne
                              ↓
             vollständige Aktionsvarianten einschließlich Pass
                              ↓
     Effekt-, Kosten-, Timing-, Combat- und Planbewertung
                              ↓
              begrenzter Vergleich kurzer Sequenzen
                              ↓
          genau eine Aktion → normaler Engine-Aktionspfad
                              ↓
              nächste View lesen und Plan neu prüfen
```

**Keine Engine-Simulation mit echtem verdecktem Zustand.** Die Politik bekommt weder `engine.state` noch eine Session zum Klonen/Probe-Ausführen. Kurze Vorschauen sind konservative Projektionen bekannter Effekte aus der eigenen View. Nicht verstandene Effekte erzeugen keine erfundenen Zustandsübergänge. Die Engine entscheidet weiterhin allein über Legalität, Kosten und tatsächliche Wirkung.

### 4.1 Modulgrenzen und Kompatibilität

Vorgeschlagene Module unter `services/`:

| Bereich | Verantwortung |
| --- | --- |
| `bot_policies/smart2.py` | Politik-Hooks, Integration; keine zweite Rules Engine |
| `smart_bot2/profile.py` | versioniertes Profil, Rollen, Archetypen-/Typal-Evidenz und mehrdimensionale Spielstile |
| `smart_bot2/context.py` | normalisierte sichtbare Ressourcen, Threats und Timingfenster |
| `bot_policies/smart2.py` (`_variants`, `_fill_in`, `play`) | legale Parameterkombinationen, X, Kosten, Modi, Pass |
| `smart_bot2/evaluation.py` | erklärbarer Nettoertrag, getrennte Kosten/Risiken |
| `smart_bot2/choices.py` | Effekt-spezifische Ziele, Kosten und Resolution-Choices |
| `smart_bot2/combat.py` | Angriffs-/Blockpakete und bekannte Schadenskanäle |
| `smart_bot2/plans.py` | Planfortschritt, Reservierungen und Planwechsel |
| `smart_bot2/recipes.py` | deklarative mechanische Planvorlagen und begründete Ausnahmen |
| `bot_policies/smart2.py` (`_record`) | versionierter Entscheidungsnachweis ohne fremde Geheimnisse |

Diese Aufteilung beschreibt Verantwortlichkeiten; kleine Bereiche dürfen zunächst zusammenliegen. Die Implementierung soll keine leeren Framework-Module vorab erzeugen.

SmartBot 2 kann während der Migration von `SmartBot` erben, muss aber die betroffenen Hooks (`play`, `answer_choice`, `setup`, `rank_targets`, `_attack`, `blocks`, `can_pass_turn`, gegebenenfalls `_fill_in`) gezielt ersetzen. Ziel ist die Nutzung gemeinsamer Dispatch-/Transporthilfen ohne versteckte geerbte Strategieverbote. Ein Wechsel zur direkten Ableitung von `Bot` erfolgt nur, wenn die benötigten Hilfen explizit abgetrennt und durch Paritätstests abgesichert sind.

Neue Profile verwenden eigene Session-Cache-Schlüssel mit Profilversion, Deck-Fingerprint und Spellbook-Version; sie überschreiben weder `_bot_strategies` von SmartBot 1 noch AI-Bot-Kontext. Entscheidungen werden bei geänderter View neu bewertet. Neustart leert Planmemory, Lobby-Rebuild erhält sie. Undo/Takeback invalidiert Pläne und Reservierungen anhand der aktuellen Position; Aktionszähler aus einer zurückgenommenen Zukunft dürfen keine legale Linie sperren.

### 4.2 Rollen- und Deckprofil

Das Profil trennt:

1. **Mechanik/Effekt:** Draw, Ramp, Tutor, Sacrifice-Outlets, Death-Payoffs, Reanimation, Blink, Landfall, Counter-Arten, Equipment, Schadenskanäle, Typal-Verweise.
2. **Nutzungskontext:** Cast/ETB/Attack/Combat-Hit/Death/Upkeep/Endstep, Kosten, Zielfilter und einmal-pro-Zug-/Schwellenbedingungen.
3. **Deckplan:** Enabler → Engine → Payoff → Abschluss; daneben fairer Entwicklungs- und Ausweichplan.

Jede Zuordnung speichert Evidenz und Sicherheit: etwa strukturierter Effekt, Katalogsignal oder Oracle-Heuristik. Commander-Fähigkeiten werden über ihre Mechanik und Nutzungskontexte eingeordnet, nicht über den Namen. Eine Rollenvermutung ist kein Nachweis funktionierender Engine-Abdeckung. Vorhandene Parser-/IR-Metadaten dürfen über einen stabilen Adapter für das eigene Setupdeck einfließen; der Bot importiert keine Engine-Interna zur Laufzeit und ändert keine Coverage-Verdikte.

Rollen und Philosophie-Verbraucher verwenden dieselben Bezeichner. Ein Vertragscheck verlangt für jede gewichtete Rolle einen Erzeuger und einen positiven sowie negativen Beispieltest. Keine generelle Entfernung von Klammertext: relevante Token-Fähigkeiten können darin stehen. Stattdessen muss zugeordnet werden, ob ein Effekt die Karte selbst, einen erzeugten Token oder eine bedingte spätere Aktion beschreibt.

Gespeicherte Archetypen bleiben explizite Nutzerhinweise. Sie werden nicht still in der DB korrigiert. Widersprüche zu Commander/Karten erscheinen im Analyse-Trace; mechanische Fähigkeiten bleiben unabhängig vom Etikett sichtbar. Der interne Plan darf mehrere Familien und Alternativen behalten, auch wenn die UI weiterhin höchstens zwei Archetypen speichert. Signale werden auf Deckgröße/Mengen und Kreaturenverteilung bezogen; alle Gleichstände erhalten feste Zweitschlüssel.

### 4.2.1 Archetyp, Spielstil und aktuelle Rolle getrennt modellieren

Ein Archetyp beschreibt den strategischen Zusammenhang, etwa Aggro, Control, Ramp, Tempo, Combo, Reanimator oder Aristocrats; auch diese Kategorien können sich überschneiden. Ein Spielstil beschreibt, **wie** ein konkreter Build Ressourcen und Zeit verwendet. Er ist kein weiterer exklusiver Name im Archetypenkatalog, sondern ein aus Kartenfunktionen abgeleitetes Merkmalsprofil:

| Dimension | Mögliche Ausprägungen / gemessene Evidenz | Entscheidungswirkung |
| --- | --- | --- |
| Zeit und Initiative | frühe Kurve, langfristiger Value, Setup-Bedarf, reaktive Angebote | Entwicklung gegen Manareserve und Verzögerung abwägen |
| Ressourcenökonomie | Mana-, Karten-, Lebens-, Friedhofs-, Token- oder Counter-Nutzung | marginaler Nutzen und tatsächliche Kosten statt pauschaler Bonus |
| Interaktionsweise | proaktiv/reaktiv, punktuell/symmetrisch, Schutz/Disruption | geeignete Fenster, Threats und Anschlussaktion |
| Boardstruktur | breit/konzentriert, permanent-/spelllastig, Typal-Abhängigkeit | Angriffspakete, Equip, Sweeper, Rekursion |
| Abhängigkeit und Redundanz | verteilte Payoffs, einzelner Motor, alternative Enabler/Outlets | Schutzbedarf und Ausweichplan |
| Siegkanal | Combat, Commander-Schaden, Poison, Drain/Burn, Mill, bedingter Sieg | Fortschritt anhand der passenden Distanz zum Abschluss |

Mischungen bleiben zulässig. Spellslinger kann etwa proaktives Tempo, reaktives Control oder Combo spielen; Sacrifice kann Aggro oder langfristigen Value unterstützen. Deshalb darf kein Archetyp pauschal „immer angreifen“, „immer Mana offenhalten“ oder „alle Opfer-Outlets schützen“ bedeuten. Die Merkmale bestimmen erwarteten Nutzen und Planungshorizont; aktuelle Hand, Board und Matchup bestimmen die **momentane Rolle** als Angreifer, Stabilisierer oder Spieler, der eine Engine schützen muss.

Das Profil schätzt keine unkalibrierten Stilwerte als sichere Wahrscheinlichkeiten. Evidenz und Unsicherheit bleiben sichtbar. Fehlt eine belastbare Stilzuordnung, entscheidet die allgemeine Effekt-/Kostenbewertung. Ein falsches Label darf ein mechanisch klares Spiel nicht verbieten.

**Verallgemeinerungsvertrag:** Strategiemodule dürfen auf Effekte, Kosten, Trigger, Ressourcen und verfügbare Aktionen verzweigen. Deck-ID, Deckname und Commander-Name sind keine strategischen Schalter. Katalog-Signalkarten dürfen die Erkennung unterstützen, aber ein namensbasiertes Signal allein darf keine Aktionsprämie auslösen. Änderungen an Gewichten benötigen Belege aus mehreren unabhängigen Situationen und Kartenrealisierungen derselben Entscheidungsfamilie.

### 4.3 Bewertung von Aktionen statt pauschalen Kartenwerten

Der intrinsische Kartenwert bleibt für unbekannte Effekte ein Fallback und für Discard eine Teilgröße. Die Aktionsentscheidung vergleicht dagegen:

- beobachtbaren Ertrag: Karten, nutzbares Mana, Board, Schaden, Counter und konkrete Trigger;
- Fortschritt des gerade erreichbaren Plans, nicht aller denkbaren Combos zugleich;
- tatsächlich angebotene Kosten: Mana, Leben, Karten, Tap, Sacrifice, verlorene Combat-/Aktivierungsoptionen;
- zeitlichen Nutzen und verfallende Gelegenheiten: Combat, zweiter Spell, Endstep, temporäre Tokens;
- bekanntes Risiko: offener gegnerischer Threat, verlorener Blocker, symmetrischer Schaden, eigener Lock;
- Unsicherheit bei nicht projizierbarer Wirkung.

Es gibt getrennte Bonusfamilien mit Sättigung, damit etwa Draw+Ramp auf derselben Karte nicht mehrfach unbegrenzt denselben Ressourcengewinn belohnt. Mana Value bleibt eine Karteneigenschaft, ersetzt aber nicht die echten Kosten eines angebotenen Casts. Ressourcenwert sinkt bei ausreichendem Mana; Draw hängt auch an Kartengüte, Deckout und alternativen Siegbedingungen. Ein Commander erhält keine pauschale Pflichtprämie unabhängig vom Board.

**Entscheidungsordnung:** belegbarer unmittelbarer Sieg bzw. Abwehr eines sichtbaren unmittelbaren Verlusts; danach Nettoertrag unter Timing und Planfortschritt. Konflikte zwischen mehreren Threats werden explizit bewertet. Eine bloß erkannte Combo oder eine optimistische Combat-Prognose darf nicht als sicherer Sieg markiert werden. Pass/Advance ist eine echte Alternative, nicht nur der Restfall einer leeren Kandidatenliste.

### 4.4 Ziele, Kosten, Modi und Resolution-Choices

Alle Parameter stammen aus dem jeweiligen Angebot. Zielgruppen, Pflichtziele, Mehrfachziele, Mengen und optionale Ablehnung bleiben erhalten. Der Bot optimiert gemeinsam Aktion und Parameter; ein guter Spell mit schlechtem Ziel ist kein guter Kandidat.

| Auswahl | Bewertung | Prüfbeispiel |
| --- | --- | --- |
| Sacrifice | Ertrag minus verlorener permanenter Wert, Recursion und noch benötigte Rolle | Gisa: Zombie-Ausbeute; Dina: Power; Felothar: Toughness minus Discard |
| Discard/Surveil | künftige Castbarkeit, Friedhofswert, benötigte Typen, keine pauschale Billigkarte | Winter, Marchesa, Terra |
| Reanimation | legaler Filter, ETB, Synergie, Angriffschance und Folgekosten | Terra Power ≤3; Winter vier Typen |
| Equipment/Auren | Träger, Equip-Aufwand, Combat-Draw, Schutz und Überkill | Wyleth/Cloud; gegnerische Goad-Aura bei Killian |
| Polymorph/Blink/Copy | geopferter/getauschter Input gegen plausiblen Output; ETB-/Control-Folgen | Jace, Preston, Ashling, Dack |
| Proliferate/Counter | Counter-Art, Controller, aktuelle Schwelle; schädliche Vermehrung vermeiden | Morcant, Kilo, Tidus, Reactor |
| X/Kicker/Offspring/Blitz/Evoke | wenige relevante Varianten mit reservierten Anschlusskosten vergleichen | Rocco, Zaxara, Zimone, Zinnia, Henzie |
| Tutor | fehlende **erreichbare** Zutat oder Schutz/Mana statt nutzlosem Combo-Stück | Kinnan, Rocco, Food, Reanimator |
| Optional zahlen | Ertrag der konkreten Folge, verbleibende Ressourcen und Fenster | Marchesa-Crime, Terra, Ashling-Kopie |

X-Varianten: legaler Minimalwert, relevante Schwellen/Targets, Wert nach sinnvoller Reserve und Maximum; keine Enumeration aller Zahlen. X=0 darf eine legale, positive Synergieaktion sein und wird nicht pauschal verboten. Kartenmodi und Fähigkeiten derselben Quelle werden anhand ihrer eigenen Wirkung unterschieden.

### 4.5 Timing, Mana und kurze Pläne

Reservierungen benennen Zweck, Kosten, Ablaufzeit und Abbruchbedingung. Beispiele: zwei Mana für Terras Treffer, UBR für die gepumpte Wick-Schnecke, passende Counterspell-Farben gegen einen sichtbaren Threat, Mana für den zweiten Spell oder Food vor Frodos Angriff. Sie sind keine ewigen Sperren und werden bei besserem Abschluss oder geänderter Bedrohung aufgegeben.

Mana wird über kohärente vorhandene `mana_potential`-Varianten bewertet, inklusive Restriktionen und Commander Tax soweit angeboten. Alternative Bezahlung wie K'rriks Leben und Food-Chain-Mana muss aus legalen Angeboten kommen; der Bot nimmt keine freie Konvertierbarkeit an. Fehlen strategisch nötige öffentliche Kosteninformationen, wird eine kleine allgemein nutzbare View-Erweiterung separat implementiert und getestet. Kartenschema-Änderungen werden nicht nur für Bot-Scores eingeführt.

Länder werden häufig zuerst gespielt, aber nicht ausnahmslos: Landfall-Reihenfolge, vorab nötiger Commander und Mehrfach-Landfall müssen vergleichbar sein. Einmal-pro-Zug-Mana wie Vivi wird nach Wachstum genutzt, sofern das höhere Mana einen besseren Plan ermöglicht. Mana-Dorks werden nicht ohne Vergleich zwischen Mana-, Block- und Angriffswert getappt.

`can_pass_turn` muss aktive Endstep-/Instant-/Trigger-Pläne berücksichtigen. Ein gesetztes Turn-Yield darf das relevante Fenster nicht überspringen. Unterdrückte Fenster brauchen eigene Integrationstests mit interaktiver Priorität und dem echten Driver.

Begrenzte Vorschau startet mit höchstens **zwei eigenen planrelevanten Aktionen** und wenigen Kandidaten je Parameterdimension; eine Erweiterung auf drei folgt nur nach Laufzeitmessung. Das ist eine Projektion, kein Vollspiel-Suchbaum. Nach jeder echten Aktion wird neu geplant. Unbekannter Draw liefert keinen angenommenen Wunschspell; unbekannte gegnerische Hand wird weder ausgelesen noch als sicher leer angenommen.

### 4.6 Combat und Multiplayer

Combat erhält eigene Bewertungen für:

- Lebenspunkte-, Poison- und Commander-Schaden sowie Toughness-basierte Schadenszuweisung;
- Flying/Reach, Trample, First/Double Strike, Deathtouch, Indestructible und bekannte relevante Einschränkungen;
- Attack-/Hit-Trigger und deren Ressourcenwert: Malcolm, Kodama, Winter, Teval, Terra, Frodo;
- Dethrone-Ziele, Goad und Kosten bekannter Angriffshindernisse;
- Blocker-Erhalt, Trades, Mehrfachblocks und Rückschlag mehrerer Gegner;
- legale Angriffe auf Planeswalker/Battles, wenn das Entfernen eines Threats mehr wert ist als Gesichtsschaden.

Combo-Zugehörigkeit erhöht nur den Verlust-/Opportunitätswert. Sie sperrt Angriffe nicht. Gerade eine Attack-Combo muss ihren Enabler angreifen lassen. Eine nötige Kreatur bleibt zurück, wenn ihr erwarteter Verlust die beste erreichbare Linie zerstört und der Angriff keinen besseren Ausgang bietet.

Die Auswahl prüft kleine Angriffspakete und plausible Blockantworten; Tokenmassen werden nach relevanten Eigenschaften gruppiert. Falls die aktuelle Action-Oberfläche nur einen gemeinsamen Defender zulässt, nutzt die erste Version diesen Vertrag vollständig. Mehrere Verteidiger oder zusätzliche Constraints werden erst nach Nachweis einer View-Lücke als eigener Engine-/API-Scope ergänzt. Keine vollständige Block-Kombinatorik und kein zweites Layer-System.

### 4.7 Ausführbare Gewinnpläne

Spellbook liefert weiter Kandidaten und Zutaten. Ein Plan ist erst **ausführbar**, wenn seine mechanisch beschriebenen Voraussetzungen und nächsten angebotenen Aktionen geprüft werden können. Status: erkannt → erreichbar → startbar → in Ausführung → tatsächlich gewonnen. Ein Start ist kein Sieg; unbekannte Voraussetzungen werden ausdrücklich ausgewiesen.

Rezepte deklarieren Zutaten, benötigte Zonen, Kosten, Trigger-/Timingfenster, Opfer-/Zielauswahl, Output und Abbruchbedingungen. Sie erzeugen Vorschläge aus legalen Angeboten statt eigene Engine-Aktionen. Faire Alternativen bleiben verfügbar; eine fehlende Combo verbietet nicht jede Sacrifice-Aktion.

**Reihenfolge nach Operatorfamilien:** zunächst Ressourcen erzeugen und in einen vorhandenen Payoff umsetzen; dann Opfer-/Rekursions- und Untap-Schleifen; danach an Combat oder Stack-Fenster gebundene Sequenzen; zuletzt komplexe Bibliotheks-/Pile-Manipulation. Die Priorität richtet sich nach Übertragbarkeit, nachgewiesenem Fehler und Implementierungsrisiko über Archetypen hinweg. Bekannte Combos sind konkrete Realisierungen dieser Operatoren, keine eigene Entwicklungsroadmap.

Bibliothek leeren, auf einen Trigger reagieren oder einen Angreifer für eine Schleife benötigen sind mechanische Voraussetzungen; sie werden nicht aus einem Combo-Namen angenommen. Nicht sicher interpretierbare Spellbook-Prosa bleibt ein Assembly-Hinweis. Seltene Mechaniken können später eine eng begrenzte Kartenausnahme benötigen. Solche Ausnahmen sind optional, isoliert, dokumentiert und separat zu testen; sie zählen nicht zum Nachweis der allgemeinen Archetypkompetenz. Ein Abschalttest zeigt, welche Verbesserungen auch ohne diese Ausnahmen bestehen.

Die Grenze von 64 Wiederholungen wird nicht pauschal entfernt. Sichtbarer Fortschritt, wiederholte Zustände und Driver-Budget bleiben Schutzmechanismen. Ein endlicher lethal Loop kann sein verbleibendes Ziel berechnen, muss aber durch normale Aktionen laufen; große echte Schleifen werden über Driver-Aufrufe fortgesetzt und mit explizitem Budget-Ende ausgewiesen. Jede eventuelle Engine-Abkürzung wäre ein eigenständiges Vorhaben.

## 5. Arbeitspakete und Reihenfolge

Die Kennzeichen A–I sind lokale Planbezeichnungen, keine neu vergebenen Backlog-Ticketnummern. Vor Umsetzung in konkrete PLR-/BUG-Tickets überführen; separat bestätigte Engine-/Parser-Lücken erhalten ihre vorhandene fachliche Route.

| Paket | Priorität / Voraussetzung | Lieferung | Abnahme |
| --- | --- | --- | --- |
| **A · reproduzierbare Basis** | P0, zuerst | Archetyp-/Stilmatrix, unabhängige Entwicklungs-/Validierungs-/Testsätze, Read-only Deckmanifest, feste Seeds/Seats, Szenarioformat, Versionen und Entscheidungstrace; getrennte Baselines smart und heutiges smart2 | Gleiche Inputs ergeben prozessübergreifend gleiche Entscheidungen; bekannte heutige Fehlentscheidungen sind reproduziert; keine fremden Geheimnisse im Trace |
| **B · Profil und Rollen** | P0, A | Katalog-/Typal-Integration, Alias-Mapping, Effekt-Evidenz, stabile Gleichstände, eigener Smart2-Cache | Jede gewichtete Rolle hat Erzeuger und Gegenprobe; unbekannte Commander und Ersatzkarten korrekt eingeordnet; Token-/Reminder-Folgeeffekt kein unbedingter eigener Finisher; Smart1-/AI-Profile unverändert |
| **C · eigenständige Aktionsbewertung** | P0, A–B | Smart2-`play`, vollständige Kandidaten, Pass, Nettoertrag, gedeckelte Bonusfamilien und Erklärungen | Derselbe Effekt mit anderem Ziel/Kosten kann anders gewählt werden; keine pauschale Cast-/Sacrifice-/Combo-Sperre; unbekannte Effekte haben legalen Fallback |
| **D · effektbezogene Choices** | P1, C | Opfer, Discard, Search, Reanimation, Equip/Blink/Copy, Modi und X | Ertrags-, Filter- und Opportunitätsfälle mit mehreren unabhängigen Kartenrealisierungen; gebundene Kosten/Targets bleiben legal; keine strategische Umverteilung aus Versehen gesperrt |
| **E · Combat** | P1, C, dann D | Angriff/Block, Schadenskanäle, Attack-Value und Combo-Opportunität | Attack-Value wird gegen Verlust und Blockbedarf abgewogen; alternative Schadensbasis korrekt; Poison-/Commander-Lethal; mehrere Blocker und Rückschlag; Combo-Piece wird im notwendigen Schutzfall erhalten |
| **F · Timing und Ressourcenpläne** | P1, C–D | Reservierungen, Gegenreaktionen, Endsteps, Landfall, zweite Spells, zwei-Aktionen-Vorschau | skalierbare Einmal-Ressource sinnvoll getimt; Vor-Combat-Bedingungen, Fremdturn-Trigger, Anschlussreserve und zweiter Spell erfüllt; keine Yield-Fensterverluste |
| **G · Gewinnrezepte** | P1/P2, D–F | Mechanische Planoperatoren, zunächst ohne Kartenausnahmen | Operatoren übertragen auf andere Karten/Commander; sichere Abschlüsse und Abbruch bei gestörter Voraussetzung in echten Engine-Szenarien; Assembly und Execution bleiben getrennte Metriken |
| **H · breite Auswertung und Tuning** | P2, A und jeweilige Pakete | Archetyp-/Stil-/Matchup-Vergleich auf gesperrtem Testsatz, ergänzend lokale 59-Deck-Regression, gepaarte Ergebnisse, Laufzeitmessung | Übertragung auf unbekannte Commander/Kartenrealisierungen nachgewiesen; Effekte pro Familie und Stil ausgewiesen; nachgewiesene Regressionen erklärt/behoben; kein Tuning allein auf Gesamtsiegquote |
| **I · Integration und Dokumentation** | Abschluss nach H | Solo/Multiplayer/Restart/Undo, Trace-Zugriff, Nutzerbeschreibung und gepflegte Referenz | Policy-Auswahl unverändert kompatibel; kein Default-Wechsel; dokumentierte Grenzen stimmen mit Tests überein |

**Lieferstufen:** A–C schaffen das belastbare Fundament. D–F beheben die meisten normalen Spielmuster. G liefert schrittweise übertragbare Planausführung; kartenspezifische Ausnahmen sind kein Abschlusskriterium dieser Lieferstufe. H läuft nach jeder Stufe und endet vor I mit dem breiten Vergleich. Verbesserte Rollenboni allein werden nicht als „umfassend verbessert“ abgeschlossen.

Eine feste Kalenderzusage wäre vor A und der Engine-Verifikation nicht belastbar. Größte Unsicherheit liegt bei projizierbaren Effekten, Combat-Komplexität, fehlenden öffentlichen Kostenmerkmalen und Engine-Coverage der Combo-Rezepte. Kleine View-Erweiterungen und echte Mechaniklücken werden getrennt geschätzt, sobald nachgewiesen.

## 6. Archetypen, Spielstile und Generalisierungsprüfung

Die Testmatrix wird **vor** Gewichtstuning festgelegt und unabhängig von der Zusammensetzung der lokalen Sammlung befüllt. Die vorhandenen Decks haben bereits die Fehlersuche und diesen Plan beeinflusst; auch ein nachträglich als Holdout bezeichnetes lokales Deck ist deshalb kein unberührter Testfall.

### 6.1 Strategische Entscheidungsfamilien

| Archetyp-/Mechanikfamilie | Zu prüfende Stilvarianten | Allgemeine Entscheidung / Gegenprobe |
| --- | --- | --- |
| Aggro / Tempo | Go-wide, konzentrierter Threat, evasiv, Spell-Unterstützung | Druck gegen Entwicklung, Schutz und Rückschlag; mehr Schaden ist nicht immer mehr Gesamtnutzen |
| Midrange / Value | ETB, Typal, wiederkehrende Ressourcen, robuste Einzelkarten | Engine gegen sofortigen Boardeinfluss; Kartenvorteil gegen Tempo |
| Control / Stax | Draw-go, Tap-out, symmetrische Einschränkungen | Manareserve gegen eigenes Wachstum; Threat-Auswahl und eigene Lock-Kosten |
| Ramp / Big-Mana | Land-, Kreatur-, Artefakt- oder temporäres Mana | weitere Quelle gegen Payoff; Nutzbarkeit, Einschränkungen und Redundanz |
| Spellslinger | Tempo, Control, Storm/Combo, größere Einzelspells | Spell-Reihenfolge, Trigger-Schwellen und eigener/gegnerischer Turn |
| Tokens / Aristocrats | Combat, Sacrifice-Value, Drain, Token als Mana | angreifen, blocken, tappen oder opfern anhand des konkreten Ertrags |
| Graveyard / Reanimator | schneller großer Threat, Rekursions-Value, Self-Mill | Discard als Kosten/Nutzen, Zielfilter, Timing und Verlust an Rekursionsmaterial |
| Voltron / Equipment / Auren | ein Träger, mehrere Träger, Schutz, politisches Target | Schadens-/Draw-Zuwachs gegen Ausrüstungsaufwand und Ausfallrisiko |
| Counters | +1/+1, −1/−1, Poison, andere Ressourcen-/Siegcounter | jeweils passenden Fortschritt statt pauschalem Proliferate-/Poison-Bonus |
| Lands / Landfall | Ramp, Wiederverwertung, Combat-/Token- oder Combo-Payoff | Reihenfolge und Anzahl der Land-Ereignisse gegen Opportunitätskosten |
| Combo | Mana→Outlet, Sacrifice/Rekursion, Attack-, Cast-/Trigger-Schleifen | Erreichbarkeit, Ressourcen, Timing, Redundanz und Abbruch; fairer Ausweichplan |
| Alternate Win / Mill / Burn | Aufbau, Schutz einer Schwelle, unmittelbarer Abschluss | zum richtigen Siegkanal wechseln; unnötigen Draw oder Setup vermeiden |

Keine vollständige kartesische Kombination ist nötig. Jede Familie muss aber mit wechselnden Ressourcenständen, vorne/ausgeglichen/hinten auf dem Board, passenden und unpassenden Gegnern sowie relevanten Stilüberschneidungen vertreten sein. Hybride und Rollenwechsel sind eigene Fälle: derselbe Build kann gegen Aggro stabilisieren und gegen Control Druck machen müssen.

### 6.2 Trennung der Datensätze

- **Entwicklung:** synthetische, mechanisch minimale Szenarien und mehrere voneinander unabhängige Kartenrealisierungen je Entscheidungsfamilie. Die lokalen Decks dürfen bekannte Regressionen liefern. Ziele und Prüfungen beziehen sich auf Ertrag und Spielmuster, nicht auf einen gewünschten Karten-Score.
- **Validierung:** getrennte Builds und Commander zum Wählen zwischen allgemeinen Profil-/Gewichtungsvarianten. Keine bloßen Seed-Varianten oder fast identischen Listen des Entwicklungssatzes.
- **Gesperrter Test:** vor Tuning festgelegte, bislang nicht zur Entwicklung verwendete Commander, Build-Familien und Kartenpakete. Zusätzlich werden Kombinationen bekannter Mechaniken zurückgehalten, damit auch die Komposition der Fähigkeiten geprüft wird. Testresultate dürfen nicht direkt nachgetunt und erneut als unabhängiger Nachweis ausgegeben werden.

Nahe Listen und dieselben benannten Combo-Pakete werden über einen gemeinsamen Gruppenbezeichner zusammengehalten. Splits erfolgen nach Commander-/Build-/Paket-Verwandtschaft, nicht zufällig pro Partie. Wiederholungen mit anderen Seeds messen Varianz, keine Generalisierung. Wo Daten knapp sind, ergänzen gruppierte Cross-Validation und explizites Zurückhalten einer Strategiefamilie die Auswertung; der gesperrte Endtest bleibt separat. Neue Testdecks werden nicht in die Nutzerdatenbank geschrieben.

### 6.3 Prüfungen gegen Überanpassung

1. **Identitätsinvarianz:** bei gleichen mechanischen Merkmalen und Angeboten dürfen geänderte Deck-/Kartennamen oder unbekannte Commander-Namen in synthetischen View-Tests die Wahl nicht verändern. Echte namensgebundene Regeln/Combo-Matches werden in diesem Test ausgeklammert und separat verifiziert.
2. **Funktionaler Kartentausch:** gleichartige Enabler/Payoffs durch andere unterstützte Karten ersetzen; bei unterschiedlichem Ertrag muss die Entscheidung dessen Änderung folgen, nicht einer Namenliste.
3. **Gezielte Störfälle:** neue, redundante oder für den Plan irrelevante Karten, veränderte Kurve/Farben und fehlende Combo-Pieces. Der Bot soll sinnvoll umplanen und nicht unabhängig vom Board am vermuteten Archetyp festhalten.
4. **Kontextwechsel bei gleichem Archetyp:** proaktiver und reaktiver Build sowie dasselbe Deck in unterschiedlichen Matchups. Unterschiedliche Entscheidungen sind richtig, wenn Stil und sichtbare Lage sie begründen.
5. **Ablation:** Archetyp-Tags, benannte Katalogsignale, Spellbook und eventuelle Kartenausnahmen getrennt abschalten. Das trennt allgemeine Effekt-/Stilkompetenz vom Nutzen spezifischen Vorwissens. Fähigkeitsverlust bei fehlender notwendiger Information wird ausgewiesen, nicht pauschal als Fehler gewertet.
6. **Entwicklungs-/Testlücke:** Verbesserungen und Regressionen pro Familie und Split gegenüber beiden Baselines ausweisen; keine Überlegenheitsbehauptung nur aus Fortschritten auf den lokalen Sample-Decks.

### 6.4 Rolle der gespeicherten Listen

Die 59 regulären lokalen Listen bleiben ein ergänzender Regressionstest; die vier Pools prüfen Extraktion und Laufzeit. Bekannte Beispiele wie Malcolm für Attack-Value oder Gisa für Opfer-Ertrag illustrieren einen allgemeinen Fall. Seine Abnahme benötigt zusätzlich andere Kartenrealisierungen und passende Gegenfälle. Es gibt keine eigene Lieferstufe „Commander X gut spielen“ und keinen Vorrang aufgrund seiner Präsenz in der lokalen Sammlung.

### Testebenen

1. **Profil-Verträge:** Rollen, Bedingungstrennung, Philosophie, Mengen, Commander, Typal, wiederholbare Hashes; keine Tests, die nur dieselbe Additionsformel abschreiben.
2. **Entscheidungsszenarien:** feste eigene View plus Angebote, zulässige Zielentscheidung bzw. erwarteter Nutzenbereich; keine unnötige Festlegung auf genau eine gleichwertige Karte.
3. **Echte Engine-Szenarien:** gezielte Board-/Hand-Situationen bis zum Trigger, Ertrag oder Spielende treiben. Die Politik bleibt blind; nur Fixture-Aufbau und Ergebnisprüfung dürfen den Enginezustand nutzen.
4. **Integrationsfälle:** Solo und interaktive Multiplayer-Priorität, Rebuild, Restart, Undo, Budget-/Loop-Stopp, Action-Rejection und Fallback. Fremde verdeckte Karten bzw. die unbekannte Library-Reihenfolge variieren, während dieselbe sichtbare Entscheidungssituation erhalten bleibt; die Entscheidung muss unverändert bleiben.
5. **Gepaarte Kampagnen:** eingefrorene Decks, Seeds, Seats, Format, Engine-/Parser-/Spellbook-Version, Aktions- und Zugbudgets; smart, heutiges smart2 und Kandidat mit denselben Startbedingungen gegen dasselbe feste Gegnerprogramm. Zusätzliche Kandidaten-Mirror-Matches messen Interaktion, ersetzen den festen Vergleich nicht.

Ablauf der Kampagnen: zunächst mechanischer Smoke-Satz; anschließend die vorab definierte Archetyp-/Stilmatrix in Entwicklung und Validierung; nach eingefrorenem Design der gesperrte Test. Die lokalen Listen werden ergänzend geprüft. Vorgeschlagener Startumfang der Breitenprüfung: **10 Seeds × 59 Decks × 3 Politikstände = 1.770 Läufe** mit vorab balanciertem Seat-/Gegnerplan. Das ist ein technischer Regressionstest, kein ausreichender Nachweis kleiner Winrate-Vorteile. Für belastbare Aussagen danach die Paarzahl pro strittiger Familie anhand Streuung und Konfidenzintervall erhöhen; separate echte Mehrspieler-Pods ergänzen. Deckgleiche Duelle allein reichen für Control/Politik nicht. Für die Generalisierungsprüfung ist der Umfang pro Archetyp-/Stilzelle und unabhängigem Build festzulegen; die lokale Zahl von 1.770 Läufen ersetzt diese Prüfung nicht.

Heutiges SmartBot 2 wird über eine eingefrorene Ausgangsrevision bzw. einen isolierten Baseline-Checkout gemessen, nicht über eine dauerhaft kopierte Produktionsklasse. Bis eine solche Revision verfügbar ist, dienen gesicherte Baseline-Traces/Fixtures als Entscheidungsvergleich; daraus wird keine nachträgliche Baseline-Winrate konstruiert.

### Metriken und Abnahmetore

| Größe | Was gemessen wird / vorgeschlagenes Tor |
| --- | --- |
| Korrektheit | Keine neuen illegalen gewählten Aktionen oder nicht abschließbaren Pflichtchoices im kontrollierten Szenariosatz; Kampagnenfehler immer separat ausweisen |
| Reproduzierbarkeit | Gleiche Manifeste/Seeds/Views reproduzieren Szenariowahl und Trace über Prozesse hinweg |
| Geheimhaltung | Gleich sichtbare Situation führt unabhängig von verdecktem Zustand zur gleichen Entscheidung; keine verbotenen Zugriffe |
| Planfortschritt | Verpasste nutzbare Attack-/Draw-/Landfall-/zweite-Spell-Fenster, ungenutzte bezahlbare Kernaktionen und unbrauchbare Tutorziele |
| Abschluss | Erkannte Zutaten, gestartete Rezepte, tatsächlich ausgeführte Linien und echte Siege separat zählen; keine Assembly als Sieg |
| Ressourcen | Überflüssige Manaausgaben, fehlende Anschlusszahlung, ungünstige Opfer/Discard und verschenkte alternative Siegkonfigurationen |
| Stabilität | Stalls, Budgetabbrüche, wiederholte No-op-Aktivierungen und fehlerhafte Wiederaufnahme; Stalls niemals als gewöhnliche Niederlage verstecken |
| Spielstärke | Gepaarte Sieg-/Verlustraten und Zeit bis Abschluss mit Unsicherheit pro Archetyp, Stil, Matchup und Datensplit; Makromittel über Familien statt Dominanz häufig gespeicherter Decks; Draws/Timeouts getrennt, gleiche Horizonte |
| Generalisierung | Gesperrte unbekannte Commander-/Build-/Paketgruppen, Entwicklungs-/Testlücke und Ablationen; Verbesserung nur mit Kartenausnahmen oder nur auf lokalen Listen erfüllt das Ziel nicht |
| Laufzeit | Entscheidungszeit p50/p95/p99 und Besuchszahl pro Entscheidungstyp; Vorschlagsbudget zunächst p95 ≤100 ms und harter Arbeitsrahmen von 250 ms auf dokumentierter Referenzhardware, nach A validieren |

Alle verbindlichen P0/P1-Szenarien müssen bestehen. Für unsupported Mechaniken werden Blocker, Nenner und betroffene Karten separat berichtet; ein Szenario wird erst nach Engine-Nachweis als Qualitätsgate aktiviert. Der Support-Nenner wird für den gepaarten Vergleich eingefroren, damit nachträgliches Ausschließen schwieriger Spiele keine Verbesserung vortäuscht.

Winrate-Zielwerte werden nach der Baseline gesetzt: der vorhandene Score-Audit liefert dafür keine Grundlage. Eine Veröffentlichung braucht zusätzlich zur Verbesserung der Fehlentscheidungen keinen klaren Hinweis auf materielle Regression in den geschützten Familien. Bei unsicherem Ergebnis sind mehr gepaarte Spiele oder engerer Lieferumfang erforderlich, keine behauptete Überlegenheit.

## 7. Risiken und Begrenzung

- **Falsche Gewissheit durch Vorschau:** nur bekannte Teilwirkungen projizieren, Unsicherheit mitführen, keinen vollständigen Rules-Nachbau schaffen.
- **Überanpassung an gespeicherte Decks oder Archetyp-Schablonen:** gruppengetrennte neue Testfälle, Identitäts-/Kartentauschtests, Stilüberschneidungen, Rollenwechsel und Ablationen verpflichtend machen. Lokale Listen sind bereits bekannte Regressionen. Maximal zwei Archetyp-Labels dürfen keinen Plan erzwingen.
- **Veränderung anderer Bots:** eigene Smart2-Profilversion und getrennte Memory; gemeinsame Änderungen nur mit Regressionen für bestehende Verbraucher.
- **Zu viele Spezialfälle:** allgemeine Planoperatoren zuerst; Kartenausnahmen nur bei nachgewiesener semantischer Lücke, isoliert und ohne Strategiegewichte nach Namen. Jede Ausnahme braucht einen echten Ausführungstest und einen Ablationsvergleich; sie zählt nicht als allgemeiner Fortschritt.
- **Combo- und Token-Laufzeit:** Kandidaten begrenzen, gruppieren und budgetieren; Fallback wählt aus aktuellen legalen Angeboten. Keine unbegrenzte Endlosschleifen-Suche.
- **Datenschutz und Nutzerdaten:** Tests mit isolierten Verzeichnissen; niemals `MTG_CACHE_DIR` auf Produktionscache zeigen lassen. Produktions-Decks nur lesen. Abgeleitete Fixtures enthalten ausschließlich benötigte Karten und keine persönlichen Deck-Metadaten. Vollständige lokale Startzustände/Replays bleiben unversionierte Diagnoseartefakte.

## 8. Dokumentation und Übergang zur Umsetzung

Dieser Plan wird aus [SMART_BOT.md](../Reference/SMART_BOT.md) verlinkt. Nach Lieferung wird dort die tatsächliche Smart2-Politik beschrieben, in `Done_Backend.md` der dauerhafte Stand ergänzt und der Deckreport als historische Baseline erhalten. `CLAUDE.md` wird nur bei einer projektweit relevanten neuen Konvention angepasst. Frontend-Engine-Coverage wird nur verändert, wenn tatsächlich Engine-Coverage geliefert wurde.

Als erster konkreter Implementierungsauftrag bietet sich **A einschließlich Archetyp-/Stilmatrix und Datentrennung plus der eng begrenzte Rollenvertrag aus B** an. Danach folgen C und zwei allgemeine End-to-End-Fähigkeiten: **Attack-Ertrag gegen Verlust-/Blockbedarf** sowie **Opfer-Ertrag gegen Ressourcen-/Planverlust**. Jede wird mit mehreren Kartenrealisierungen, unbekanntem Commander, Positiv-/Warte-/Alternativfall und Kontextwechsel geprüft. Bekannte Deckbeispiele sind ergänzende Regressionen. Erst nach diesem Übertragungsnachweis weitere Entscheidungsfamilien und mechanische Planoperatoren ausbauen.

Für Backend-Änderungen sind die passende Teilprüfung und anschließend die Backend-Suite erforderlich; bei tatsächlicher Engine-/Parser-Arbeit zusätzlich das Full-Cache-Tier gemäß Projektkonvention. Neue Skill-/Rules-Recherche folgt der jeweils betroffenen Implementierung, nicht einer pauschalen Änderung von Regeln im Bot.
