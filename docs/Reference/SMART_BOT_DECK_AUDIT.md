# SmartBot 1 und 2: Prüfung der gespeicherten Decklisten

**Historische Baseline vor PLR-15.** Der inzwischen implementierte SmartBot 2 ist in [SMART_BOT.md](SMART_BOT.md) beschrieben; die damaligen Messwerte bleiben unverändert.

Stand: 22.10.2026. Gegenstand sind die **63 tatsächlich in der lokalen Deckdatenbank gespeicherten Listen**: 59 reguläre Listen und vier als Cube markierte Sammlungen/Testlisten. Keine Deckliste und kein Bot-Code wurden verändert.

## Ergebnis

**Beide Bots entwickeln Ressourcen meist plausibel, verfolgen aber viele reale Gewinnpläne nur unvollständig. SmartBot 2 ist keine generell bessere Spielstrategie.** Er addiert Kartenboni; Timing, Aktionsfilter, Choice-Grundlogik, Angriffe und Combo-Ausführung bleiben geerbt. Bei **23 von 63 Listen sind sämtliche gemessenen Nichtland-Kartenwerte identisch**. Bei 40 Listen gibt es Unterschiede, deren Nutzen vom Deck abhängt. Das sind Scoring-Messungen, keine Siegquoten.

Am ehesten passt Version 2 zu Equipment/Voltron, Ressourcen und dem erkannten Poison/Proliferate-Paket. Besonders problematisch bleiben Combat-Combos, Reanimator, Spellslinger-Sequenzen, Toughness-Combat, X-Spells und alternative Siege. Die vier Cube-Listen sind separat als Pools bewertet; daraus folgt kein Urteil über ein später daraus gebautes Deck.

## Methode und Aussagegrenzen

- Deckdaten ausschließlich mit SQLite `mode=ro` gelesen; Commander und Mainboard mit dem vorhandenen `parse_deck_sections` zerlegt. Sideboards werden nicht als aktive Strategie mitgezählt. Karten lokal aus dem konfigurierten Karten-Cache geladen, inklusive normalisierter Doppelkartennamen. **Eine nicht aufgelöste Karte:** Erebor Heirloom in Sans Soleil MWI.
- Oracle-Texte, tatsächliche Kartenkombinationen und Commander-Fähigkeiten bilden die Grundlage der fachlichen Deckplan-Einschätzung. Die folgende Archetypbeschreibung ist eine analytische Einordnung; die separat ausgewiesenen Bot-Archetypen sind das gemessene Ergebnis des Codes.
- Profile mit dem aktuellen `build_strategy` erstellt, inklusive gespeicherter Archetypen, falls gesetzt. Der lokale Spellbook-Snapshot ist initialisiert: **113.013 Varianten**, Version **7.1.4**, Quelldatum **04.10.2026**. Matches mit ungelösten Template-Anforderungen werden wie im Bot ausgeschlossen. Combo-Zahl bedeutet Zahl der akzeptierten Varianten, nicht Zahl unabhängig ausführbarer Gewinnlinien; Voraussetzungen wie Board, Mana und Timing sind damit nicht bewiesen.
- **Vergleichssituation für alle Zahlen:** drei eigene Länder im Spiel, fünf neutrale Hand-Platzhalter, kein Stack, keine zugänglichen Combo-Teile im Spiel/auf der Hand/in der Command Zone. Die geprüfte Karte wird nur für die Quellenauflösung in einer eigenen sichtbaren Zone geführt. Beide echten `_card_value`-Methoden bewerten dieselbe hypothetische Cast-Aktion. So bleiben Commander-, Rollen-, Philosophie- und grundsätzlicher Combo-Bonus messbar, ohne zufällige Starthand oder Bibliothekswissen. Es wird weder behauptet, dass alle Karten zugleich bezahlbar sind, noch dass diese Rangfolge eine vollständige reale Zugfolge ist. Activations-Mali und Timingfilter kommen beim tatsächlichen `play` zusätzlich hinzu.
- **5.151 Nichtland-Kartenbewertungen je Version**, gezählt als Karte-pro-Liste; Länder erscheinen in der CSV als Inventar ohne Cast-Score. Die CSV enthält Deck-ID, Stückzahlen, Rollen und beide Scores. Ranglisten zeigen drei höchste Grundwerte; bei Gleichstand kann die Listenreihenfolge entscheiden. Identische Werte in dieser Situation bedeuten nicht identische gesamte Spielverläufe, weil etwa Blocking auf diese Werte zugreift und Laufzeit-Combo-Fortschritt sich ändern kann.
- Statische Codeanalyse und direkte Ausführung der Profil-/Bewertungsfunktionen, **keine gespielte 63-Deck-Turniersimulation**, keine Winrate-Aussage und keine vollständige Engine-Coverage-Prüfung. Die bestehenden **34 SmartBot-Tests bestehen**, darunter Engine-Tests für Commander-Entwicklung, Combat und Oracle/Consultation; sie beweisen nicht die hier untersuchten Gewinnlinien jedes Decks. Es gibt unter `backend/tests` derzeit keine expliziten SmartBot2-Tests.

Vollständige Daten: [Karteninventar und Bewertungsvergleich](SMART_BOT_DECK_AUDIT.csv).

## Was die Gewichtung tatsächlich tut

SmartBot 1 beginnt mit `16 − 1,5 × gedruckter Mana Value`. Hinzu kommen Commander **+28**, Regex-wincon **+24**, jede zum Theme passende Rolle **+12**, Ramp bei drei Ländern **+16** (mit explizitem Ramp-Archetyp zusätzlich +8), Draw bei fünf Handkarten **+8** bzw. bei höchstens drei **+18**, Tutor bei vorhandenen Combos **+30**. Combo-Pieces erhalten mindestens **+35**, bei als gewinnrelevant erkanntem Output zusätzlich **+15**; sichtbarer Board-Fortschritt und vollständige Erreichbarkeit erhöhen das weiter. Es zählt der beste Combo-Wert, nicht die Summe sämtlicher Matches. Aktivierungen erhalten zusätzlich **−10**, bei Sacrifice-Kosten grundsätzlich weitere **−20** und teilweise harte Sperren.

SmartBot 2 addiert pro überlappender Rolle: combat **+14**, control **+12**, resources **+10**, graveyard **+12**, spells **+10**, lands **+14**, counters **+12**. Zusätzlich gibt es für sacrifice unter graveyard **+14**, für Instants unter control **+6** sowie unter bestimmten combat-Bedingungen für stompy/attack **+8**. Das ist ein Bonus pro Rolle, nicht einmal pro Karte: Mehrfachrollen können den Ausschlag überproportional verschieben.

## Gemeinsame und zusätzliche Fehlsteuerungen

1. **Unwirksame Philosophie-Rollen:** `ROLE_PATTERNS` erzeugt keine der Version-2-Rollen cantrip, flashback, magecraft, storm oder spells-matter. Der gesamte spells-Bonus bleibt deshalb leer. Dasselbe gilt für landfall, land-ramp, land-cycle und fetch: lands ist als Philosophie vorhanden, aber deren Rollen werden nicht erzeugt. Das ist eine Code-Feststellung, keine Vermutung über einzelne Karten.
2. **Graveyard fällt auf midrange zurück:** Die Auto-Erkennung liefert häufig `graveyard` oder `sacrifice`; beide fehlen als Schlüssel in `ARCHETYPE_PHILOSOPHIES`. Sie werden `midrange`, während nur speziellere Tags wie aristocrats/reanimator zur Philosophie graveyard führen. Von den gespeicherten regulären Listen aktiviert Dance of the Elements diese Philosophie durch seine expliziten Tags. Allgemeine Rekursion selbst bekommt zudem keinen wirksamen Version-2-Rollenbonus, weil `graveyard` nicht zu dessen Match-Menge gehört.
3. **Combo-Pieces dürfen niemals angreifen:** `_attack` überspringt jedes erkannte Combo-Piece unabhängig von laufender Gewinnchance. Das verhindert normale Value-Angriffe und kann angriffsabhängige Combos blockieren. Der Kommentar in SmartBot2 über eine gelockerte Angriffssperre entspricht nicht dem Code: `_attack` fragt den erhöhten Kartenwert überhaupt nicht ab.
4. **Kartenbonus ist keine Timingstrategie:** Die Behauptung im Version-2-Kommentar, Instants förderten das Offenhalten von Mana, ist nicht als Reservierungslogik implementiert. In eigener Mainphase kann der erhöhte Wert sogar zum früheren Ausgeben führen. Außerhalb der eigenen leeren Mainphase werden generisch nur Counter/gezielte gegnerische Removal-Reaktionen berücksichtigt; freie Endstep-Entwicklung, proaktiver Schutz und viele Commander-Aktivierungen werden so verpasst.
5. **Sacrifice- und Target-Value ignorieren den Ertrag:** Opfer/Discard orientieren sich überwiegend am niedrigsten Kartenwert; beneficial-Ziele am hohen Wert und richtigem Controller. Gisa, Dina, Felothar, Polymorph und Reanimation benötigen dagegen konkrete Input/Output-Bewertung. Unter Primary-Archetyp combo werden sacrifice-markierte Quellen bis zur vollständigen Board-Combo zusätzlich gesperrt. Sacrifice-Kosten an einem nicht tutor-markierten Combo-Piece können eine Aktivierung sogar ganz ausschließen.
6. **Combat ist kein Archetyp-Solver:** Power/Toughness-Vergleich, einfache Flying/Reach-/Deathtouch-Abfragen und Lebenspunkte bestimmen Angriffe. Commander-Schaden, Poison-Abschluss, Trample durch mehrere Blocker, Toughness-Schaden und Ertrag von Attack-Triggern werden nicht passend bewertet. Version 2 verbessert diese Logik nicht; geerbte Blocks können durch höhere Kartenwerte immerhin anders sortiert werden.
7. **Oracle hat genau einen Spezialplan:** Oracle/Consultation ist ausdrücklich sequenziert. Bei Bibliothek >2 wartet Oracle auf Consultation in Hand und kohärentes UU+B, auch wenn Tainted Pact oder eine andere Library-Line vorhanden ist. Generic Spellbook-Assembly führt weder Doomsday-Piles noch Breach-, Food-Chain- oder beliebige Aktivierungsschleifen aus.
8. **Reminder und enge Regex verzerren Rollen:** Witch's Mark enthält über den Wicked-Role-Reminder einen Opponent-Life-Loss-Text und erhält deshalb wincon-Bonus. Umgekehrt verpassen Formulierungen wie `get +X/+X`, variables Pump und anders formulierte alternative Siege das enge Muster. `proliferate` wird stets poison, obwohl es auch andere Counter-Pläne trägt. Typal-Dichte, X-Größe, tatsächliche Rabatte und viele Cast-/Combat-Schwellen bleiben unbewertet.
9. **Archetypwahl ist empfindlich:** Gespeicherte Tags ersetzen die automatische Archetypwahl, aber nicht die Regex-Themes. Auto-Themes gleicher Stärke werden aus einem Set sortiert, ohne festen Zweitschlüssel; eine Gleichstandsreihenfolge kann zwischen Python-Prozessen wechseln. Werte dieser Bestandsaufnahme beziehen sich auf den gemessenen Prozess. Ein bloßes Nachtragen von Tags würde mehrere Probleme verdecken, die fehlenden Rollen und Sequenzen aber nicht beheben.

## Deckweise Bewertung

„Besser“ bezeichnet die Passung des zusätzlichen Scorings zum Deckplan, nicht eine gemessene höhere Siegquote. „Identisch“ bezeichnet alle untersuchten Nichtland-Grundwerte bei diesem gespeicherten Profil.

### 01. Wyleth Equip

**Commander:** Wyleth, Soul of Steel. **Umfang:** 100 Karten. **ID:** `dbf5882c-558d-4683-9036-40ed4803b9c7`.

**Deckplan:** Voltron / Equipment. Wyleth ausrüsten, beim Angriff Karten ziehen und mit großem bzw. doppelschlagendem Commander gewinnen; Ardenn, Sigarda's Aid und Bruenor senken den Aufwand.

**Bot-Profil:** gespeicherte Tags `voltron`; wirksam `voltron` → Philosophien `combat`. Auto ohne Tags: `voltron, tokens`. Themes: `lifegain, tokens, voltron`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Wyleth, Soul of Steel **59.5 → 73.5**; Sword of the Animist **41 → 55**; Sword of Hearth and Home **39.5 → 53.5**.

**Größte Zusatzboni, Beispiele:** Akiri, Fearless Voyager **31.5 → 45.5**; Ardenn, Intrepid Archaeologist **23.5 → 37.5**; Argentum Armor **19 → 33**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Leicht besser. Commander- und Equipment-Boni passen. Version 2 stärkt auch nützliche Ausrüstungen, bewertet aber weder Equip-Kosten noch den fertigen Träger als Gesamtpaket. Bereits angelegte Ausrüstung wird grundsätzlich nicht neu angelegt; Schutz und Evasion werden im Angriff nur teilweise berücksichtigt.

### 02. Goblins

**Commander:** Krenko, Mob Boss. **Umfang:** 100 Karten. **ID:** `aa69b9d1-2474-4ead-9491-3f3a0d67c55d`.

**Deckplan:** Goblin-Tokens / Combo / Go-wide. Krenko vervielfacht Goblins; Purphoros, Impact Tremors und Goblin Bombardment verwerten die Masse. Krenko oder Kiki-Jiki plus Thornbite Staff und Bombardment bilden erkannte Schleifen.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, tokens` → Philosophien `combo, resources`. Auto ohne Tags: `combo, tokens`. Themes: `sacrifice, tokens, voltron`. Akzeptierte Combo-Varianten: **2**.

**Hohe Grundwerte (1 → 2):** Krenko, Mob Boss **100 → 100**; Thornbite Staff **87 → 87**; Goblin Bombardment **75 → 75**.

**Größte Zusatzboni, Beispiele:** Mind Stone **37 → 57**; Sol Ring **30.5 → 40.5**; Arcane Signet **29 → 39**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gemischt. Combo-Priorität passt, aber Krenko/Staff/Bombardment erhalten Vorfahrt vor dem normalen Schwarmplan. Version 2 stärkt Ramp/Draw statt Goblin-Dichte und Haste. Der Primary-Combo-Guard kann Opfer-Outlets vor vollständig liegender Combo sperren; der Token-Beatdown wird zu konservativ gespielt.

### 03. cEDH Kinnan

**Commander:** Kinnan, Bonder Prodigy. **Umfang:** 100 Karten. **ID:** `56bec085-29c5-4af7-97a9-c4038f08449d`.

**Deckplan:** Mana-Combo / Kinnan-Big-Mana. Kinnan plus Basalt Monolith erzeugt farbloses Mana; weitere Mana-Schleifen und Thrasios/Kinnan erschließen Kreaturen und einen Abschluss.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, spellslinger` → Philosophien `combo, spells`. Auto ohne Tags: `combo, spellslinger`. Themes: `clones, graveyard, group-slug, sacrifice, spellslinger`. Akzeptierte Combo-Varianten: **10**.

**Hohe Grundwerte (1 → 2):** Kinnan, Bonder Prodigy **92 → 92**; Machine God's Effigy **73 → 73**; Crop Rotation **72.5 → 72.5**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Aufbau sinnvoll, Abschluss lückenhaft. **SmartBot 2:** Identisch. Die echten Mana-Pieces werden erkannt. Spellslinger als zweites Etikett ist irreführend und bewirkt in Version 2 keinen Bonus. Farbloses Endlosmana wird nicht als komplette Gewinnlinie geplant; Aktivierungen sind auf 64 je Fähigkeit/Turn begrenzt. Das Finden eines Mana-Motors beweist keinen verwertbaren Abschluss.

### 04. cEDH M-K

**Commander:** Kediss, Emberclaw Familiar / Malcolm, Keen-Eyed Navigator. **Umfang:** 100 Karten. **ID:** `b0c60fbc-7bec-42ba-9468-d855a3761cfa`.

**Deckplan:** Pirate-Combat / Malcolm-Combo. Malcolm und Kediss erzeugen über Kampfschaden Treasures; Glint-Horn Buccaneer sowie Niv-Mizzet mit Curiosity/Ophidian Eye liefern alternative Schleifen.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, spellslinger` → Philosophien `combo, spells`. Auto ohne Tags: `combo, spellslinger`. Themes: `graveyard, group-slug, spellslinger, tokens`. Akzeptierte Combo-Varianten: **7**.

**Hohe Grundwerte (1 → 2):** Malcolm, Keen-Eyed Navigator **141.5 → 141.5**; Niv-Mizzet, Parun **77 → 77**; Curiosity **72.5 → 72.5**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Kritischer Plankonflikt. **SmartBot 2:** Identisch. Malcolm ist erkanntes Combo-Piece und wird deshalb von _attack ausgeschlossen: gerade sein normaler Treasure-Aufbau entfällt. Auch eine angriffsabhängige Buccaneer-Linie kann daran scheitern. Gute Assembly-Scores gleichen diese harte Sperre nicht aus.

### 05. K'rrik cEDH

**Commander:** K'rrik, Son of Yawgmoth. **Umfang:** 100 Karten. **ID:** `421deb7a-cf2d-419e-822a-b8a7bb48dbe1`.

**Deckplan:** Schwarz: Leben als Mana / Reanimation / Drain. K'rrik beschleunigt schwarze Kosten über Leben; Tutoren, Reanimation, Gray Merchant und Drain-Spells verwerten den Vorsprung. Maralen plus Opposition Agent ist ein erkannter Lock, kein unmittelbarer Sieg.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, lifegain` → Philosophien `combo`. Auto ohne Tags: `combo, lifegain`. Themes: `graveyard, lifegain`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Dark Petition **66.5 → 66.5**; Wayfarer's Bauble **60.5 → 60.5**; Beseech the Queen **53 → 53**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Identisch. Der einzige lokale Combo-Match zieht alle Tutoren an, obwohl der Plan mehr als diesen Lock umfasst. K'rriks alternative Bezahlung, Lebensbudget und großes X werden nicht strategisch bewertet. Wayfarer's Bauble kann deutlich über dem Commander liegen. Lifegain→combo fügt in Version 2 keine Hilfe hinzu.

### 06. Eliferate

**Commander:** High Perfect Morcant. **Umfang:** 100 Karten. **ID:** `485432a7-b6d9-413e-826e-428fc5252056`.

**Deckplan:** Elfball / Blight / Poison / Overrun. Elfen entwickeln Mana und Morcant-Blight; Proliferate, Triumph of the Hordes oder Craterhoof schließen ab. Staff/Umbral-Mantle-Mana-Schleifen sind vorhanden.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, poison` → Philosophien `combo, counters`. Auto ohne Tags: `combo, poison`. Themes: `graveyard, lifegain, poison, tokens, voltron`. Akzeptierte Combo-Varianten: **11**.

**Hohe Grundwerte (1 → 2):** High Perfect Morcant **103 → 115**; Elvish Archdruid **86.5 → 86.5**; Deathrite Shaman **66.5 → 66.5**.

**Größte Zusatzboni, Beispiele:** Evolution Sage **41.5 → 53.5**; Glistener Elf **44.5 → 56.5**; Infectious Bite **43 → 55**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gezielt besser. Version 2 stärkt Poison/Proliferate tatsächlich, obwohl der Sammelbegriff Poison Blight und andere Counter vermischt. Angriffe werden weiterhin anhand Lebenspunkten statt Poison-Lethal bewertet; Combo-Elfen werden vollständig zurückgehalten. Den Übergang von Mana-Elfen zum Overrun plant keine Version.

### 07. Oops! All Night's Whispers

**Commander:** Marchesa, Dealer of Death. **Umfang:** 100 Karten. **ID:** `e0ed78f9-a95d-45c7-a951-9f4d8e49bc99`.

**Deckplan:** Crime-Value / Reanimator. Marchesa macht günstige gegnerische Ziele zu Kartenselektion und Friedhofsfüllung; Reanimate und weitere Rückholer bringen große Threats oder Gray Merchant zurück.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `graveyard, spellslinger` → Philosophien `midrange, spells`. Auto ohne Tags: `graveyard, spellslinger`. Themes: `graveyard, spellslinger`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** An Offer You Can't Refuse **42.5 → 42.5**; Marchesa, Dealer of Death **39.5 → 39.5**; Faithless Looting **34.5 → 34.5**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Identisch. Crime und Reanimationsziel werden nicht als zusammenhängende Linie bewertet; der Commander enthält nicht das einfache Draw-Muster. Das automatisch erkannte graveyard wird nicht auf die Philosophie graveyard abgebildet. Version 2 hat daher trotz passender Deckidee keinen wirksamen Reanimator-Bonus.

### 08. Imodane

**Commander:** Imodane, the Pyrohammer. **Umfang:** 100 Karten. **ID:** `a49a7c9f-8c97-400d-ad63-d6be85739da8`.

**Deckplan:** Single-target-Burn / Imodane-Combo. Ein großer auf genau eine Kreatur gerichteter Schadensspruch löst Imodanes Tischschaden aus; Grafted Exoskeleton und Shivan Meteor bilden einen lokalen Gewinn-Match.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, graveyard` → Philosophien `combo, midrange`. Auto ohne Tags: `combo, graveyard`. Themes: `graveyard, sacrifice, spellslinger, tokens, voltron`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Imodane, the Pyrohammer **73 → 73**; Witch's Mark **69 → 69**; Grafted Exoskeleton **57 → 57**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Identisch. Der wichtige Unterschied zwischen Creature-Target und Player-Target wird nicht anhand des Imodane-Outputs bewertet. Witch's Mark erhält über seinen erzeugten Wicked Role-Reminder wincon- und weitere Rollenboni und kann Schlüsselschaden verdrängen. Die Erkennung graveyard beschreibt den eigentlichen Burn-Plan schlecht.

### 09. cEDH staples

**Commander:** Ashling, the Limitless. **Umfang:** 215 Karten · Cube/Testpool. **ID:** `a01a10ff-a347-4fc9-ba72-a2fa1dfaba9e`.

**Deckplan:** Cube / cEDH-Kartensammlung. 215 Karten mit zahlreichen alternativen Combos; erst ein daraus gebautes Deck besitzt einen verlässlichen Gewinnplan.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, sacrifice` → Philosophien `combo, midrange`. Auto ohne Tags: `combo, sacrifice`. Themes: `clones, graveyard, group-slug, lifegain, sacrifice, spellslinger, tokens`. Akzeptierte Combo-Varianten: **32**.

**Hohe Grundwerte (1 → 2):** Thassa's Oracle **87 → 87**; Lion's Eye Diamond **82 → 82**; Lotus Petal **82 → 82**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Kein normaler Deckmaßstab. **SmartBot 2:** Identisch. 32 lokale Matches beschreiben den Pool, keine kohärente 100-Karten-Strategie. Als direkt gestartete Liste entstehen opportunistische Combo-Prioritäten und geschützte Angreifer. Die gleiche Bewertung beider Versionen ist kein Qualitätsnachweis.

### 10. Keywords Showcase

**Commander:** Kenrith, the Returned King. **Umfang:** 100 Karten · Cube/Testpool. **ID:** `5e9df66c-30f0-43c6-b879-3f1cbbe1fea0`.

**Deckplan:** Keyword-Testliste / Fünffarben-Value. Kenrith und gemischte Keyword-Kreaturen dienen vor allem der Demonstration; Kampfschaden und Ressourcen bilden den allgemeinen Plan.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `tokens, lifegain` → Philosophien `combo, resources`. Auto ohne Tags: `tokens, lifegain`. Themes: `lifegain, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Kenrith, the Returned King **60.5 → 60.5**; Gilded Goose **54.5 → 64.5**; Prosperous Innkeeper **53 → 63**.

**Größte Zusatzboni, Beispiele:** Seize the Spoils **47.5 → 67.5**; Wall of Omens **21 → 31**; Elvish Mystic **30.5 → 40.5**.

**Urteil SmartBot 1:** Für Entwicklung plausibel. **SmartBot 2:** Mehr Ressourcen, kein Strategiebeweis. Als Cube markierte 100-Karten-Liste. Version 2 bevorzugt Mana/Draw, insbesondere doppelt erkannte Karten wie Seize the Spoils. Die automatische Lifegain-Combo-Philosophie bedeutet hier keine tatsächlich erkannte Combo. Die Liste eignet sich für Funktionsproben, kaum als Archetyp-Benchmark.

### 11. cEDH staples 2

**Commander:** Jodah, the Unifier. **Umfang:** 636 Karten · Cube/Testpool. **ID:** `ed8bb218-932e-4d9c-b5d1-d2f475f62520`.

**Deckplan:** Großer cEDH-Testpool. 636 Karten und 313 lokale Combo-Matches bilden einen Werkzeugkasten statt eines fokussierten Spiels.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, sacrifice` → Philosophien `combo, midrange`. Auto ohne Tags: `combo, sacrifice`. Themes: `clones, graveyard, group-slug, lifegain, sacrifice, spellslinger, tokens, voltron`. Akzeptierte Combo-Varianten: **313**.

**Hohe Grundwerte (1 → 2):** Malcolm, Keen-Eyed Navigator **113.5 → 113.5**; Witherbloom Apprentice **96 → 96**; Laboratory Maniac **93.5 → 93.5**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Kein normaler Deckmaßstab. **SmartBot 2:** Identisch. Combo-Häufigkeit ist hier ein Pool-Effekt. Viele alternative Outlets und Commander werden als zu schützende Teile eingestuft; daraus lässt sich keine reale Deckführung ableiten. Erst konkrete Draft-/Deck-Auswahlen vergleichen.

### 12. Wick Snail Boom

**Commander:** Wick, the Whorled Mind. **Umfang:** 100 Karten. **ID:** `56b28a96-8205-4909-ae6a-c37f350d3469`.

**Deckplan:** Wick: Snail-Fling / Power-Pump. Ratten erzeugen und vergrößern die Schnecke; Wick opfert sie für Schaden an allen Gegnern und entsprechend viele Karten. Ausrüstung und Pump sind Munition für die Schnecke.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `voltron, sacrifice` → Philosophien `combat, midrange`. Auto ohne Tags: `voltron, sacrifice`. Themes: `graveyard, sacrifice, tokens, voltron`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Wick, the Whorled Mind **62 → 62**; Siege Smash **37 → 51**; Invigorated Rampage **37 → 51**.

**Größte Zusatzboni, Beispiele:** Siege Smash **37 → 51**; Invigorated Rampage **37 → 51**; Demonspine Whip **25 → 39**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gemischt. Voltron wird aus den Ausrüstungen erkannt, obwohl der Schaden über die geopferte Schnecke kommt. Version 2 stärkt Pump und Equipment, plant aber nicht Pump→Wick-Aktivierung. Sacrifice-Ziele werden nach Kartenwert statt Schneckenstärke/Schadensabschluss gewählt.

### 13. [cEDH] Glarb Bloomsday

**Commander:** Glarb, Calamity's Augur. **Umfang:** 100 Karten. **ID:** `ee9ccf2f-3131-476b-afb7-0bf8a5ab0cc0`.

**Deckplan:** Doomsday / Library-Combo / Glarb-Value. Doomsday, Oracle/Jace und Tainted Pact nutzen eine kleine bzw. leere Bibliothek; Glarb bietet Surveil und Topdeck-Zugriff.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, spellslinger` → Philosophien `combo, spells`. Auto ohne Tags: `combo, spellslinger`. Themes: `graveyard, sacrifice, spellslinger`. Akzeptierte Combo-Varianten: **6**.

**Hohe Grundwerte (1 → 2):** Jace, Wielder of Mysteries **92 → 92**; Doomsday **91.5 → 91.5**; Thassa's Oracle **87 → 87**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Kritischer Ausführungsmangel. **SmartBot 2:** Identisch. Die hohe Assembly-Priorität passt, aber es existiert keine allgemeine Doomsday-Pile-Planung. Oracle wird bei mehr als zwei Bibliothekskarten ausschließlich mit Demonic Consultation auf der Hand zugelassen; die vorhandene Pact-Linie bekommt keine gleichwertige Sequenz. Kein Combo-Match ersetzt diese fehlende Planung.

### 14. Marchesa V4.2

**Commander:** Marchesa, the Black Rose. **Umfang:** 100 Karten. **ID:** `aa999912-632d-46d6-921d-fb59a8131b01`.

**Deckplan:** Marchesa-Aristocrats / Counter-Reanimation. Mit +1/+1-Countern sterbende Kreaturen kommen im Endstep zurück; Opfer-Outlets und Mikaeus ermöglichen wiederholte ETBs bzw. Schleifen.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, sacrifice` → Philosophien `combo, midrange`. Auto ohne Tags: `combo, sacrifice`. Themes: `lifegain, sacrifice, spellslinger, tokens`. Akzeptierte Combo-Varianten: **10**.

**Hohe Grundwerte (1 → 2):** Ashnod's Altar **89.5 → 89.5**; Phyrexian Altar **89.5 → 89.5**; Mikaeus, the Unhallowed **81 → 81**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Kritischer Plankonflikt. **SmartBot 2:** Identisch. Der Combo-Guard hält Sacrifice-Aktivierungen bis zur vollständigen Combo zurück und kann fairen Marchesa-Value verhindern. Gleichzeitig priorisiert _attack niedrige gegnerische Lebenspunkte statt des Dethrone-Ziels mit den meisten Leben. sacrifice wird auf midrange statt graveyard abgebildet.

### 15. Hobbits

**Commander:** Frodo, Adventurous Hobbit / Sam, Loyal Attendant. **Umfang:** 100 Karten. **ID:** `e7c674c0-d620-4de6-ba2a-807214ca0019`.

**Deckplan:** Food / Lifegain / Aristocrats. Sam erzeugt billiges Food, Frodo verwandelt rechtzeitigen Lifegain in Angriffswert; Took/Confectioner und Mirkwood Bats bieten Token- und Drain-Pläne.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, lifegain` → Philosophien `combo`. Auto ohne Tags: `combo, lifegain`. Themes: `graveyard, lifegain, sacrifice, tokens`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Many Partings **84.5 → 84.5**; Experimental Confectioner **82.5 → 82.5**; Gilded Goose **66.5 → 66.5**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Identisch. Die lokale Food-Schleife wird erkannt, aber der passende Food-/Resources-Plan wird von combo/lifegain verdrängt. Kein Plan spart Food gezielt für Frodos Vor-Combat-Schwelle. Opferkosten und alternative Drain-Siege werden nur über grobe Rollen bewertet.

### 16. Kodama

**Commander:** Kodama of the West Tree. **Umfang:** 100 Karten. **ID:** `94ec0b5b-225f-4dd2-908a-fd4517144c47`.

**Deckplan:** Modified-Combat / Land-Ramp. Modifizierte Kreaturen verbinden Kodamas Trample mit Land-Suche; breite Boards und Craterhoof/Pathbreaker Ibex gewinnen.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, tokens` → Philosophien `combo, resources`. Auto ohne Tags: `combo, tokens`. Themes: `clones, graveyard, lifegain, tokens, voltron`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Kodama of the West Tree **97.5 → 107.5**; Springheart Nantuko **84 → 84**; Nissa, Who Shakes the World **73.5 → 73.5**.

**Größte Zusatzboni, Beispiele:** The Great Henge **38.5 → 58.5**; Throne of Eldraine **32.5 → 52.5**; Archdruid's Charm **57.5 → 67.5**.

**Urteil SmartBot 1:** Kritischer Plankonflikt. **SmartBot 2:** Leicht besser beim Aufbau. Kodama selbst ist Combo-Piece und greift daher nicht an, obwohl ein modifizierter Kodama den Ramp-Plan tragen könnte. Version 2 fördert Mana/Draw, aber Modified und sichere Trample-Angriffe werden nicht gezielt aufgebaut; tokens ersetzt den eigentlichen Combat/Lands-Plan.

### 17. SpongeBob and the legendary Burger

**Commander:** Jodah, the Unifier. **Umfang:** 100 Karten. **ID:** `a1c51a53-28a4-44d8-bdd0-ac9ba22e7221`.

**Deckplan:** Legendary-Matters / Jodah-Kaskade. Legendäre Spells bauen Jodahs wachsende Armee auf; Sisay-Tutoren und Ratadrabik/Boromir liefern zusätzliche Value- bzw. Schleifenlinien.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, graveyard` → Philosophien `combo, midrange`. Auto ohne Tags: `combo, graveyard`. Themes: `graveyard, tokens`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Ratadrabik of Urborg **57 → 57**; Boromir, Warden of the Tower **46.5 → 46.5**; Nature's Lore **43 → 43**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Identisch. Die einzige erkannte Combo gibt Ratadrabik/Boromir Vorrang. Legendary-Dichte und der Nutzen einer Jodah-Kaskadenfolge haben keinen eigenen Bonus. Jodahs get +X/+X fällt nicht unter das numerische wincon-Muster; graveyard→midrange hilft Version 2 nicht.

### 18. Raggadragga, Goreguts Boss

**Commander:** Raggadragga, Goreguts Boss. **Umfang:** 100 Karten. **ID:** `ba4357a2-0662-4d5c-8ba5-f31fb0469cd5`.

**Deckplan:** Mana-Dorks als Angreifer / Big-Mana-Combo. Raggadragga macht Mana-Kreaturen kampfstark und enttappt sie beim Angriff; große Spells und Mana-Schleifen öffnen Finisher.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, tokens` → Philosophien `combo, resources`. Auto ohne Tags: `combo, tokens`. Themes: `stompy, tokens`. Akzeptierte Combo-Varianten: **25**.

**Hohe Grundwerte (1 → 2):** Fanatic of Rhonas **88 → 98**; Elvish Archdruid **86.5 → 96.5**; Gwenna, Eyes of Gaea **74.5 → 84.5**.

**Größte Zusatzboni, Beispiele:** Freyalise, Llanowar's Fury **44.5 → 64.5**; Heart Warden **37 → 57**; Selvala, Heart of the Wilds **70.5 → 90.5**.

**Urteil SmartBot 1:** Kritischer Plankonflikt. **SmartBot 2:** Gemischt. Viele Dorks sind unter den 25 Combo-Matches und werden dadurch nie zum Angriff geschickt. Version 2 stärkt sie als Ressourcen noch mehr, beseitigt aber die Angriffssperre nicht. Der spezielle Sieben-Mana-Trigger und sein bestes Untap-Ziel erhalten keinen eigenen Plan.

### 19. Hydranten

**Commander:** Zaxara, the Exemplary. **Umfang:** 100 Karten. **ID:** `bb6bc5c6-78de-4124-9d8e-cc0cbc56e5f9`.

**Deckplan:** Zaxara / X-Spells / Hydra-Tokens. Zaxara plus Freed from the Real oder Pemmin's Aura erzeugt Mana; große X-Spells und Hydra-Boards bzw. Simic Ascendancy verwerten es.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, tokens` → Philosophien `combo, resources`. Auto ohne Tags: `combo, tokens`. Themes: `lifegain, tokens, voltron`. Akzeptierte Combo-Varianten: **4**.

**Hohe Grundwerte (1 → 2):** Zaxara, the Exemplary **101 → 111**; Kodama of the West Tree **69.5 → 79.5**; Farseek **59 → 69**.

**Größte Zusatzboni, Beispiele:** Brass Infiniscope **46 → 66**; Arcane Signet **29 → 39**; Birds of Paradise **30.5 → 40.5**.

**Urteil SmartBot 1:** Aufbau sinnvoll, Abschluss lückenhaft. **SmartBot 2:** Leicht besser beim Aufbau. Version 2 stärkt Ramp/Draw, während X bei der gedruckten Mana-Bewertung praktisch unsichtbar bleibt. Kein spezieller Solver verbindet Mana-Schleife, genügend großes X und Abschluss. Die automatisch erzeugten Hydra-Tokens allein beweisen keine passende X-Wahl.

### 20. Hope to the last

**Commander:** Hope Estheim. **Umfang:** 100 Karten. **ID:** `40a76fd1-53d1-47c9-821f-3c3917693346`.

**Deckplan:** Lifegain→Mill / alternative Siege. Hope übersetzt Lifegain im Endstep in gegnerisches Mill; Traumatize und Riverchurn Monument beschleunigen, Felidar Sovereign/Angel of Destiny bieten andere Enden.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, lifegain` → Philosophien `combo`. Auto ohne Tags: `combo, lifegain`. Themes: `graveyard, lifegain, tokens, voltron`. Akzeptierte Combo-Varianten: **2**.

**Hohe Grundwerte (1 → 2):** Riverchurn Monument **75 → 75**; Shabraz, the Skyshark **63.5 → 63.5**; Drogskol Reaver **60.5 → 60.5**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Identisch. Wichtige Lifegain- und Millkarten erhalten isolierte Werte, aber weder Bibliotheksrest noch Lifegain-Schwelle priorisieren die konkrete Gewinnbedingung. Aetherflux Reservoir und Angel of Destiny werden vom engen wincon-Muster nicht verlässlich erfasst. Version 2 bleibt vollständig unverändert.

### 21. cEDH Rocco

**Commander:** Rocco, Cabaretti Caterer. **Umfang:** 100 Karten. **ID:** `33f061d4-0c85-4546-bf7b-1566fc1b20f9`.

**Deckplan:** Rocco-Tutor / Food-Chain-Combo. Rocco sucht Kreaturen passend zu X; Food Chain und Squee bilden einen Mana-Motor mit ETB-/Cast-Verwertung und Purphoros als Abschlussoption.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, spellslinger` → Philosophien `combo, spells`. Auto ohne Tags: `combo, spellslinger`. Themes: `spellslinger`. Akzeptierte Combo-Varianten: **2**.

**Hohe Grundwerte (1 → 2):** Rocco, Cabaretti Caterer **69.5 → 69.5**; Food Chain **62.5 → 62.5**; Guardian Sunmare **54.5 → 54.5**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Aufbau sinnvoll, Abschluss lückenhaft. **SmartBot 2:** Identisch. Rocco und Food Chain werden sinnvoll gewichtet. Es fehlt aber die Planung des Tutor-X und der Reihenfolge bis zum Outlet; Exil-Mana ist keine universelle Manaressource. Das Spellslinger-Etikett liefert Version 2 keine Unterstützung.

### 22. yshtola

**Commander:** Y'shtola, Night's Blessed. **Umfang:** 100 Karten. **ID:** `619fa984-e61b-46aa-87ef-ce0665115a3c`.

**Deckplan:** Y'shtola: Nichtkreatur-Drain / Control. Nichtkreaturspells ab Mana Value 3 lösen Tischschaden und Lifegain aus; Lebensverlust pro Zug speist die Endstep-Karten, Cleric/Onyx verstärken den Drain.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `spellslinger, lifegain` → Philosophien `combo, spells`. Auto ohne Tags: `spellslinger, lifegain`. Themes: `graveyard, lifegain, spellslinger, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Y'shtola, Night's Blessed **70 → 70**; Starscape Cleric **61 → 61**; Professor Onyx **55 → 55**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Identisch. Commander und Drain-Payoffs stehen sinnvoll weit oben. Der Malus für höhere Mana Values konkurriert jedoch mit der entscheidenden Dreier-Schwelle. Fremde Züge werden ohne gegnerischen Stack nicht genutzt; Version 2 kennt weder diese Schwelle noch eine wirksame spells-Philosophie.

### 23. Commander Cube

**Commander:** Tom Bombadil. **Umfang:** 749 Karten · Cube/Testpool. **ID:** `90e172f6-28a4-4e1b-9daa-070dddd7e18a`.

**Deckplan:** Commander-Draftpool. 749 Karten mit Tom Bombadil als gespeichertem Commander; daraus entstehen unterschiedliche Draftdecks, kein einheitlicher Saga- oder Combo-Plan.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, tokens` → Philosophien `combo, resources`. Auto ohne Tags: `combo, tokens`. Themes: `clones, graveyard, group-slug, lifegain, poison, sacrifice, spellslinger, stompy, tokens, vehicles, voltron`. Akzeptierte Combo-Varianten: **7**.

**Hohe Grundwerte (1 → 2):** Cleric Class **88.5 → 88.5**; Brallin, Skyshark Rider **84 → 84**; Godo, Bandit Warlord **84 → 84**.

**Größte Zusatzboni, Beispiele:** Bone Miser **44.5 → 64.5**; Commander's Sphere **35.5 → 55.5**; Dragon's Hoard **35.5 → 55.5**.

**Urteil SmartBot 1:** Kein normaler Deckmaßstab. **SmartBot 2:** Ressourcenverschiebung ohne Deckurteil. Die automatische tokens/combo-Auswahl beschreibt den Pool. Sie passt nicht zwangsläufig zu einem tatsächlich gebauten Saga-Deck. Beide Bots brauchen die finale Auswahl; aus sieben Pool-Matches kann keine Spielqualität für ein Draftdeck geschlossen werden.

### 24. Lorehold Spirit - Secrets of Strixhaven

**Commander:** Quintorius, History Chaser. **Umfang:** 100 Karten. **ID:** `c8d5d0b2-4148-4bf6-a422-484270411e18`.

**Deckplan:** Graveyard-Exit / Spirit-Tokens. Quintorius erzeugt Spirits, wenn Karten den Friedhof verlassen; Looting und Rekursion füttern diesen Plan, Double Strike verwandelt Spirits in einen Abschluss.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `graveyard, tokens` → Philosophien `midrange, resources`. Auto ohne Tags: `graveyard, tokens`. Themes: `graveyard, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Quintorius, History Chaser **70 → 80**; Lorehold Charm **49 → 49**; Seize the Spoils **47.5 → 67.5**.

**Größte Zusatzboni, Beispiele:** Seize the Spoils **47.5 → 67.5**; Mind Stone **37 → 57**; Primary Research **28.5 → 38.5**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gemischt. Version 2 bevorzugt besonders Seize the Spoils und Mind Stone, während die eigentliche Graveyard-Exit-Kette keinen Bonus erhält. Die Planeswalker-Modi werden vorwiegend über denselben Quellenwert verglichen; der −4-Abschluss braucht eine Boardbewertung, keine pauschale Commander-Prämie.

### 25. Prismari Artistry - Secrets of Strixhaven

**Commander:** Rootha, Mastering the Moment. **Umfang:** 100 Karten. **ID:** `dedc9954-f215-4e43-82cf-785839cafbc2`.

**Deckplan:** Big-Spells vor Combat / Token-Finisher. Rootha erzeugt zu Kampfbeginn einen fliegenden Haste-Token anhand des größten zuvor gewirkten Instant/Sorcery-Spells.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `tokens, spellslinger` → Philosophien `resources, spells`. Auto ohne Tags: `tokens, spellslinger`. Themes: `clones, graveyard, spellslinger, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Leitmotif Composer **55.5 → 65.5**; Storm-Kiln Artist **50 → 60**; Rootha, Mastering the Moment **50 → 50**.

**Größte Zusatzboni, Beispiele:** Solemn Simulacrum **34 → 54**; Big Score **46 → 66**; Prismari Charm **21 → 31**.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Gemischt. Mainphase 1 erlaubt grundsätzlich Vorbereitung, aber die 1,5-Punkte-Strafe je Mana Value bevorzugt kleine statt große Rootha-Enabler. Version 2 stärkt Ressourcen wie Big Score, nicht den entscheidenden Größenvergleich. Combat-Timing und Mana-Value-Payoff bleiben ungeplant.

### 26. Quandrix Unlimited - Secrets of Strixhaven

**Commander:** Zimone, Infinite Analyst. **Umfang:** 100 Karten. **ID:** `2570028f-c867-484b-b0af-8c29d4e73ad2`.

**Deckplan:** X-Spells / +1/+1-Counter-Rabatt. Der erste X-Spell pro Zug verstärkt Zimone und erhält zunehmenden Rabatt; große X-Effekte und Fractals schließen ab.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `tokens, spellslinger` → Philosophien `resources, spells`. Auto ohne Tags: `tokens, spellslinger`. Themes: `lifegain, spellslinger, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Brass Infiniscope **46 → 66**; Zimone, Infinite Analyst **39.5 → 39.5**; Guardian Augmenter **35.5 → 35.5**.

**Größte Zusatzboni, Beispiele:** Brass Infiniscope **46 → 66**; Troyan, Gutsy Explorer **35.5 → 55.5**; Nexus Mentality **18 → 28**.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Nur generische Verbesserung. X-Größe, erster Spell pro Zug und Zimones Rabatt werden nicht bewertet. Die automatisch erkannten tokens/spellslinger verpassen den Counter-Plan. Brass Infiniscope und Troyan steigen durch Ressourcenboni stark, ohne dass der eigentliche X-Abschluss besser geplant würde.

### 27. Silverquill Influence - Secrets of Strixhaven

**Commander:** Killian, Decisive Mentor. **Umfang:** 100 Karten. **ID:** `2ef232e5-256e-4ab2-b07d-accc9b3f39ac`.

**Deckplan:** Auren / Goad / Enchantress. Killian tappt und goadet bei Enchantment-ETB; Angriffe mit durch eigene Auren verzauberten Kreaturen ziehen Karten. Eriette liefert einen Drain-Plan.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `voltron, tokens` → Philosophien `combat, resources`. Auto ohne Tags: `voltron, tokens`. Themes: `graveyard, group-slug, lifegain, tokens, voltron`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Eriette of the Charmed Apple **47.5 → 61.5**; Killian, Decisive Mentor **47.5 → 57.5**; Forum Filibuster **44.5 → 58.5**.

**Größte Zusatzboni, Beispiele:** Coercive Impetus **31.5 → 55.5**; Pearl-Ear, Imperial Advisor **31.5 → 55.5**; Sram, Senior Edificer **33 → 57**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Leicht besser, Zielwahl riskant. Auren- und Draw-Boni passen teilweise. Das generelle beneficial→eigene Kreatur trifft aber nicht jede Aura: Goad-Auren können gerade auf gegnerischen Angreifern wertvoll sein. Version 2 unterscheidet nicht zwischen eigenem Voltron und gegnerischem Aura-Politikziel.

### 28. Witherbloom Pestilence - Secrets of Strixhaven

**Commander:** Dina, Essence Brewer. **Umfang:** 100 Karten. **ID:** `57a5dbde-da00-4301-b6d1-8542b154a3de`.

**Deckplan:** Sacrifice / Lifegain / Counter-Aristocrats. Dina verwertet Kreaturenopfer in Karten, Leben und Counter; Zulaport Cutthroat/Dina, Soul Steeper und große Körper liefern Drain bzw. Combat.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `sacrifice, lifegain` → Philosophien `combo, midrange`. Auto ohne Tags: `sacrifice, lifegain`. Themes: `graveyard, lifegain, sacrifice, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Dina, Essence Brewer **71.5 → 71.5**; Gilded Goose **66.5 → 66.5**; Zulaport Cutthroat **61 → 61**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Identisch. Dina und Drain-Enabler werden richtig hoch bewertet. Dennoch wird sacrifice zur midrange-Philosophie statt zu graveyard, wodurch Version 2 keinen Bonus erhält. Opferziele maximieren weder Dina-Power-Ertrag noch Sterbe-Trigger; einmal-pro-Zug-Kartenvorteil wird nicht gezielt über Züge verteilt.

### 29. Turtle Power! - Teenage Mutant Ninja Turtles Commander Deck

**Commander:** Heroes in a Half Shell. **Umfang:** 100 Karten. **ID:** `b53542ed-c517-42b7-ac02-b926e7aba873`.

**Deckplan:** Typal-Combat / +1/+1-Counter. Mutants/Ninjas/Turtles müssen Spieler treffen, damit das Team Counter und Karten bekommt; Food und Lifegain unterstützen diesen Kampfplan.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `tokens, sacrifice` → Philosophien `midrange, resources`. Auto ohne Tags: `tokens, sacrifice`. Themes: `clones, lifegain, sacrifice, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Ninja Pizza **51.5 → 61.5**; Shellshock **50.5 → 50.5**; Tempestra, Dame of Games **49 → 49**.

**Größte Zusatzboni, Beispiele:** April O'Neil, Live on the Scene **33 → 43**; Baxter, Fly in the Ointment **18 → 28**; Ray Fillet, Wave Warrior **19.5 → 29.5**.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Gemischt. Die Erkennung tokens/lifegain übersieht den eigentlichen Typal-Combat-Motor. Version 2 investiert mehr in Ressourcen, ohne passende Angreifer, Evasion oder Counter-Skalierung zu priorisieren. Die konservative Angriffsregel kann wertvolle Combat-Draw-Fenster auslassen.

### 30. Dance of the Elements - Lorwyn Eclipsed Commander Deck

**Commander:** Ashling, the Limitless. **Umfang:** 100 Karten. **ID:** `58d5b17f-abbc-44fb-aaea-0070a7926b8a`.

**Deckplan:** Elemental-Evoke / ETB / Aristocrats. Ashling macht geopferte Elementals zu temporären Kopien; Evoke, ETB und Blink/Death-Verwertung bilden den Motor.

**Bot-Profil:** gespeicherte Tags `blink, aristocrats`; wirksam `blink, aristocrats` → Philosophien `combo, graveyard`. Auto ohne Tags: `tokens, graveyard`. Themes: `clones, graveyard, lifegain, sacrifice, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Ashling, the Limitless **75.5 → 101.5**; Jubilation **55 → 55**; Shimmercreep **44.5 → 44.5**.

**Größte Zusatzboni, Beispiele:** Omnath, Locus of Rage **29.5 → 55.5**; Descendants' Fury **22 → 48**; Ashling, the Limitless **75.5 → 101.5**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gezielt besser, Kosten bleiben blind. Die gespeicherten Tags blink/aristocrats aktivieren tatsächlich graveyard. Opferrollen erhalten zusammen +26, Ashling und Omnath profitieren. Das gilt aber pauschal auch beim Casten oder als Opferwert und ersetzt weder Evoke-Auswahl noch die Entscheidung über WUBRG zum Erhalt einer Kopie.

### 31. Blight Curse - Lorwyn Eclipsed Commander Deck

**Commander:** Auntie Ool, Cursewretch. **Umfang:** 100 Karten. **ID:** `c1e175f2-9add-4c12-838e-eb258c6d16c5`.

**Deckplan:** −1/−1-Counter / Blight-Aristocrats. Auntie Ool verwandelt −1/−1-Counter in Karten oder Lebensverlust; Hapatra, Blowfly Infestation und Flourishing Defenses kombinieren Counter mit Token-Schleifen.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, sacrifice` → Philosophien `combo, midrange`. Auto ohne Tags: `combo, sacrifice`. Themes: `graveyard, lifegain, poison, sacrifice, tokens`. Akzeptierte Combo-Varianten: **2**.

**Hohe Grundwerte (1 → 2):** Grave Venerations **70 → 70**; Hapatra, Vizier of Poisons **60 → 60**; Blowfly Infestation **58.5 → 58.5**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Identisch. Der Combo-Match ist hilfreich, aber sacrifice verdrängt den Counter-Archetyp. −1/−1-Counter werden nicht als eigene Rollenfamilie erkannt; weder passendes Counter-Ziel noch drohender Kollateralschaden wird als Sequenz bewertet. Version 2 bleibt ohne Counter-Philosophie wirkungslos.

### 32. Counter Intelligence - Edge of Eternities Commander Deck

**Commander:** Kilo, Apogee Mind. **Umfang:** 100 Karten. **ID:** `a557d8f3-ebb7-4c54-b86b-f1366b41488f`.

**Deckplan:** Proliferate / Artefakt-Counter. Kilo muss getappt werden und vervielfacht Counter; Proliferate verstärkt Artefakte und alternative Ziele wie Darksteel Reactor.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `poison, tokens` → Philosophien `counters, resources`. Auto ohne Tags: `poison, tokens`. Themes: `graveyard, poison, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Kilo, Apogee Mind **69.5 → 81.5**; Tezzeret's Gambit **48 → 70**; Experimental Augury **43 → 55**.

**Größte Zusatzboni, Beispiele:** Tezzeret's Gambit **48 → 70**; Tekuthal, Inquiry Dominus **40 → 52**; Experimental Augury **43 → 55**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gezielt besser. Poison ist als Etikett zu eng, erzeugt aber die nützliche counters-Philosophie. Tezzeret's Gambit erhält Draw- plus Counter-Bonus. Das konkrete Tappen von Kilo, Counter-Art/-Anzahl und Reactor-Siegschwelle werden weiterhin nicht vorausgeplant.

### 33. World Shaper - Edge of Eternities Commander Deck

**Commander:** Szarel, Genesis Shepherd. **Umfang:** 100 Karten. **ID:** `4dbf021e-53ae-4fbd-862c-a8e450fb24f2`.

**Deckplan:** Land-Sacrifice / Land-Replay / Counters. Szarel spielt Länder aus dem Friedhof und verwandelt geopferte Permanents in große Counter-Pakete; Land- und Opfer-Payoffs schaffen Board und Schaden.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, sacrifice` → Philosophien `combo, midrange`. Auto ohne Tags: `combo, sacrifice`. Themes: `graveyard, lifegain, sacrifice, tokens`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Sprouting Goblin **79 → 79**; The Gitrog Monster **78.5 → 78.5**; Springbloom Druid **69.5 → 69.5**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Identisch. Sprouting Goblin/Gitrog/Harrow erhalten Combo-/Ramp-Prioritäten, aber lands wird nicht erkannt. sacrifice landet bei midrange; der entscheidende Wiederausspielwert eines geopferten Landes und Szarels Power-Skalierung werden nicht eingerechnet. Ein Match darf den normalen Land-Loop nicht ersetzen.

### 34. Death Toll - Duskmourn: House of Horror Commander

**Commander:** Winter, Cynical Opportunist. **Umfang:** 100 Karten. **ID:** `8e25b06e-a499-47c1-af4c-3fea8d303239`.

**Deckplan:** Delirium / Self-Mill / Reanimator. Winter füllt beim Angriff den Friedhof und tauscht im Endstep vier Kartentypen gegen einen starken Permanent mit Finality Counter.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `graveyard, tokens` → Philosophien `midrange, resources`. Auto ohne Tags: `graveyard, tokens`. Themes: `graveyard, lifegain, sacrifice, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Grist, the Hunger Tide **71.5 → 71.5**; Winter, Cynical Opportunist **50 → 50**; Titania, Nature's Force **43 → 43**.

**Größte Zusatzboni, Beispiele:** Commander's Sphere **35.5 → 55.5**; Solemn Simulacrum **34 → 54**; Mind Stone **37 → 57**.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Gemischt. Die generische Exil-/Choice-Logik optimiert nicht vier Typen plus wertvolles Reanimationsziel. Version 2 fördert Rocks, nicht Delirium. _attack berücksichtigt keinen Deathtouch-Vorteil des eigenen Angreifers und kann Winters Mill-Angriffe unnötig auslassen.

### 35. Endless Punishment - Duskmourn: House of Horror Commander

**Commander:** Valgavoth, Harrower of Souls. **Umfang:** 100 Karten. **ID:** `41a51bb5-ecb2-4073-9a34-7e646128ae1f`.

**Deckplan:** Group-Slug / Schaden auf gegnerischen Zügen. Valgavoth benötigt Lebensverlust auf den jeweiligen gegnerischen Zügen; dauerhafte Pinger, Mogis, Kardur und Drain machen daraus Karten, Counter und Sieg.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `sacrifice, lifegain` → Philosophien `combo, midrange`. Auto ohne Tags: `sacrifice, lifegain`. Themes: `group-slug, lifegain, sacrifice, voltron`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Bastion of Remembrance **59.5 → 59.5**; Kardur, Doomscourge **58 → 58**; Mogis, God of Slaughter **46 → 46**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Identisch. Die Erkennung sacrifice/lifegain verfehlt die zeitliche Group-Slug-Struktur. Beide Bots entwickeln in der eigenen Mainphase und aktivieren außerhalb davon ohne gegnerischen Stack keine gewöhnlichen Schadensfähigkeiten. Gerade Valgavoths erster Lebensverlust pro gegnerischem Zug wird nicht gezielt ausgelöst.

### 36. Jump Scare! - Duskmourn: House of Horror Commander

**Commander:** Zimone, Mystery Unraveler. **Umfang:** 100 Karten. **ID:** `90934772-37f6-49e4-9609-93e123fffaee`.

**Deckplan:** Landfall / Manifest Dread / Face-up-Value. Zimone braucht mehrere Landfalls pro Zug: erst Manifest Dread, danach kostenloses Aufdecken eines passenden Permanents; große Treffer tragen den Sieg.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, graveyard` → Philosophien `combo, midrange`. Auto ohne Tags: `combo, graveyard`. Themes: `graveyard, tokens`. Akzeptierte Combo-Varianten: **3**.

**Hohe Grundwerte (1 → 2):** Yavimaya Elder **100.5 → 100.5**; Sakura-Tribe Elder **94 → 94**; Zimone, Mystery Unraveler **73 → 73**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Identisch. Ramp wird hoch bewertet, aber der stets zuerst ausgeführte Landdrop wird nicht gegen die beste Reihenfolge von Landfall-Auslösern und Zielpermanents abgewogen. Face-up-/Manifest-Ziele werden nicht als Gesamtplan bewertet. graveyard/combo trifft die Landfall-Struktur nur zufällig.

### 37. Miracle Worker - Duskmourn: House of Horror Commander

**Commander:** Aminatou, Veil Piercer. **Umfang:** 100 Karten. **ID:** `083df84b-4d77-463a-a774-bae5caf7662a`.

**Deckplan:** Enchantments / Miracle / Topdeck-Control. Aminatou nutzt Surveil und stark reduzierte Miracle-Enchantments; Enchantment-Value, Token und große Permanents gewinnen.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, tokens` → Philosophien `combo, resources`. Auto ohne Tags: `combo, tokens`. Themes: `clones, graveyard, lifegain, sacrifice, tokens`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Life Insurance **68.5 → 68.5**; Ondu Spiritdancer **67.5 → 67.5**; Solemn Simulacrum **64 → 84**.

**Größte Zusatzboni, Beispiele:** Solemn Simulacrum **64 → 84**; Commander's Sphere **35.5 → 55.5**; Mind Stone **37 → 57**.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Gemischt. Die Bewertung kennt weder den ersten Draw pro Zug noch den Vorteil eines oben gehaltenen teuren Enchantments. Life Insurance und eine Nebencombo können den Kernplan verdrängen. Version 2 hebt Solemn Simulacrum/Rocks an, ohne Enchantress- oder Miracle-Priorität zu ergänzen.

### 38. Riveteer Rampage - New Capenna Commander

**Commander:** Henzie "Toolbox" Torre. **Umfang:** 100 Karten. **ID:** `82062424-42ab-4294-b941-45a4bbc39383`.

**Deckplan:** Blitz / ETB-Death-Value / Reanimator. Henzie verwandelt große Kreaturen durch Blitz in sofortigen Angriff, ETB, Death-Trigger und Karten; Rekursion wiederholt das.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `sacrifice, tokens` → Philosophien `midrange, resources`. Auto ohne Tags: `sacrifice, tokens`. Themes: `graveyard, lifegain, sacrifice, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Henzie "Toolbox" Torre **47.5 → 57.5**; Disciple of Bolas **42 → 52**; Caldaia Guardian **42 → 52**.

**Größte Zusatzboni, Beispiele:** Migration Path **34 → 54**; Solemn Simulacrum **34 → 54**; Commander's Sphere **35.5 → 55.5**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gemischt. Commander- und Draw-Boni helfen beim Aufbau, aber es fehlt der Vergleich zwischen normalem Cast und Blitz samt kommendem Tod. Version 2 fördert Ramp/Draw, nicht den Wert eines konkreten ETB-/Death-Pakets. sacrifice wird erneut nicht zur graveyard-Philosophie.

### 39. Shorikai Vehicles

**Commander:** Shorikai, Genesis Engine. **Umfang:** 100 Karten. **ID:** `14d6276e-d6fa-44af-9d69-0513769d1420`.

**Deckplan:** Vehicle-Value / Shorikai-Draw / Untap-Combo. Shorikai produziert Karten und Piloten; Fahrzeuge tragen Combat. Dramatic Reversal und weitere Artefakt-/Untap-Kombinationen bieten andere Wege.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, vehicles` → Philosophien `combo, resources`. Auto ohne Tags: `combo, vehicles`. Themes: `graveyard, spellslinger, tokens, vehicles`. Akzeptierte Combo-Varianten: **4**.

**Hohe Grundwerte (1 → 2):** Shorikai, Genesis Engine **105 → 115**; Solemn Simulacrum **64 → 84**; Sensei's Divining Top **57.5 → 67.5**.

**Größte Zusatzboni, Beispiele:** Solemn Simulacrum **64 → 84**; Arcane Signet **29 → 39**; Cultivator's Caravan **39.5 → 49.5**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Leicht besser beim Aufbau. Commander und Draw-Aktivierung sind sinnvoll hoch gewichtet. Version 2 hilft Ressourcen, unterscheidet aber nicht den Wert von Pilot als Crew, Blocker oder Token. Besatzungskosten und der Bedarf, Shorikai als Draw-Motor ungetappt zu halten, werden nicht vorausgerechnet.

### 40. Ojer cEDH

**Commander:** Ojer Axonil, Deepest Might // Temple of Power. **Umfang:** 100 Karten. **ID:** `e2847cd6-24e5-4eb3-afd2-f11cdbebf39b`.

**Deckplan:** Group-Slug / Ojer-Schadensersatz. Kleine rote Nichtkampfschadensquellen werden auf Ojers Stärke angehoben; dauerhafte Pinger und Pyrohemia erreichen den ganzen Tisch.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, group-slug` → Philosophien `combo, control`. Auto ohne Tags: `combo, group-slug`. Themes: `group-slug, spellslinger, tokens`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Ojer Axonil, Deepest Might // Temple of Power **88 → 88**; Pyrohemia **60 → 72**; Coruscation Mage **37 → 49**.

**Größte Zusatzboni, Beispiele:** Pyroblast **14.5 → 44.5**; Red Elemental Blast **14.5 → 44.5**; Abrade **13 → 31**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gemischt. Der Commander erhält gute Priorität. Version 2 stärkt aber besonders mehrrollige Interaktion wie Pyroblast/Red Elemental Blast, nicht proportional den durch Ojer vervielfachten Tischschaden. Dieselbe Schutzfunktion wird über counter, removal und Instant mehrfach belohnt.

### 41. Vivi B4

**Commander:** Vivi Ornitier. **Umfang:** 100 Karten. **ID:** `fbd1cc8a-3db7-4dc0-846c-ea9bc8565e94`.

**Deckplan:** Spellslinger / Storm / Breach. Vivi wächst mit Nichtkreaturspells und produziert einmal pro eigenem Zug Mana nach Stärke; Breach, LED/Lotus Petal und Brain Freeze bilden Schleifen.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, spellslinger` → Philosophien `combo, spells`. Auto ohne Tags: `combo, spellslinger`. Themes: `graveyard, group-slug, sacrifice, spellslinger, tokens, voltron`. Akzeptierte Combo-Varianten: **5**.

**Hohe Grundwerte (1 → 2):** Vivi Ornitier **102.5 → 102.5**; Lion's Eye Diamond **82 → 82**; Lotus Petal **82 → 82**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Aufbau sinnvoll, Timing schwach. **SmartBot 2:** Identisch. Vivi und Breach-Pieces stehen passend oben. Seine Mana-Aktivierung benötigt jedoch ein Timing nach ausreichendem Wachstum; der Bot vergleicht nur aktuelle Aktionen ohne Sequenzsuche. Version 2 besitzt für spells keine erzeugten Match-Rollen; Witch's Mark wird durch Reminder-Rollen überbewertet.

### 42. Counter Blitz - Final Fantasy Commander

**Commander:** Tidus, Yuna's Guardian. **Umfang:** 100 Karten. **ID:** `89398937-7f93-4ec1-8c99-3aedd99d04f3`.

**Deckplan:** +1/+1-Counter / Proliferate-Combat. Tidus verschiebt Counter und belohnt Kampftreffer mit Draw/Proliferate; Hardened Scales und Walking Ballista verwerten Counter.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, sacrifice` → Philosophien `combo, midrange`. Auto ohne Tags: `combo, sacrifice`. Themes: `lifegain, poison, sacrifice, tokens`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Walking Ballista **66 → 66**; Hardened Scales **64.5 → 64.5**; Gatta and Luzzu **61.5 → 61.5**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Identisch. Die automatische combo/sacrifice-Erkennung verpasst den dominierenden Counter-Plan vollständig. +1/+1-Counter und ihre optimale Verteilung sind keine bewerteten Rollen. Version 2 hat ohne counters-Philosophie keinen Vorteil; X-Wahl und Schaden von Ballista sind nicht durch ihren hohen Assembly-Score bewiesen.

### 43. Limit Break - Final Fantasy Commander

**Commander:** Cloud, Ex-SOLDIER. **Umfang:** 100 Karten. **ID:** `ec96f2bd-b472-492c-95a8-67cd2ae3a559`.

**Deckplan:** Equipment-Combat / Cloud. Cloud legt beim ETB Ausrüstung an, zieht je ausgerüstetem Angreifer Karten und erzeugt ab Stärke 7 Treasures.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `voltron, tokens` → Philosophien `combat, resources`. Auto ohne Tags: `voltron, tokens`. Themes: `graveyard, sacrifice, tokens, voltron`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Cloud, Ex-SOLDIER **68.5 → 92.5**; Skullclamp **46.5 → 70.5**; Sephiroth, Fallen Hero **44.5 → 58.5**.

**Größte Zusatzboni, Beispiele:** Mask of Memory **33 → 57**; Puresteel Paladin **33 → 57**; Skullclamp **46.5 → 70.5**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gezielt besser. Version 2 stärkt Commander, Equipment-Draw und Ramp passend. Ein einzelner großer Cloud und mehrere ausgerüstete Angreifer sind aber unterschiedliche Pläne; die Sieben-Stärke-Schwelle und die Team-Verteilung werden nicht bewertet. Bereits angelegte Ausrüstung kann nicht strategisch umverteilt werden.

### 44. Revival Trance - Final Fantasy Commander

**Commander:** Terra, Herald of Hope. **Umfang:** 100 Karten. **ID:** `f37439be-781b-4022-9b23-6ee9480471f5`.

**Deckplan:** Combat-Reanimator / Low-Power-ETBs. Terra millt vor Combat und reanimiert nach einem Treffer für zwei Mana Kreaturen mit Power höchstens 3; große ETB-Wirkung bei geringer Power ist besonders wertvoll.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `graveyard, tokens` → Philosophien `midrange, resources`. Auto ohne Tags: `graveyard, tokens`. Themes: `graveyard, sacrifice, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Shadow, Mysterious Assassin **55.5 → 65.5**; Terra, Herald of Hope **51.5 → 51.5**; Pitiless Plunderer **50 → 60**.

**Größte Zusatzboni, Beispiele:** Big Score **46 → 66**; Commander's Sphere **35.5 → 55.5**; Mind Stone **37 → 57**.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Gemischt. Die Bewertung kennt weder das Power-3-Zielfenster noch das dafür freizuhaltende Mana. Version 2 fördert generische Ressourcen und nicht das Terra-Target. Eine bezahlte optionale Reanimation kann in die konservative Basis-Choice fallen statt als Kernplan erkannt zu werden.

### 45. Scions & Spellcraft - Final Fantasy Commander

**Commander:** Y'shtola, Night's Blessed. **Umfang:** 100 Karten. **ID:** `d71885a3-195c-4cbe-a975-b0a9872cd6ac`.

**Deckplan:** Y'shtola-Spells / Drain / Tokens. Spells ab Mana Value 3 lösen Drain aus; wiederholter Lebensverlust versorgt die Endsteps, Token und Exsanguinate ergänzen den Abschluss.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `spellslinger, tokens` → Philosophien `resources, spells`. Auto ohne Tags: `spellslinger, tokens`. Themes: `clones, graveyard, lifegain, sacrifice, spellslinger, tokens, voltron`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Bastion of Remembrance **71.5 → 71.5**; Y'shtola, Night's Blessed **70 → 80**; Summon: Good King Mog XII **56.5 → 56.5**.

**Größte Zusatzboni, Beispiele:** Coveted Jewel **31 → 51**; Sol Ring **30.5 → 40.5**; Alphinaud Leveilleur **18 → 28**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Leicht besser beim Aufbau. Anders als bei yshtola erzeugt die zweite Theme-Wahl tokens eine resources-Philosophie und damit echte Boni. Das stärkt Draw/Ramp, ohne die relevante Dreier-Schwelle, fremde Endsteps oder passende Spell-Sequenzen zu lösen. Die Klassifikation erzeugt unterschiedliche Hilfe für denselben Commander.

### 46. Abzan Armor - Tarkir: Dragonstorm Commander

**Commander:** Felothar the Steadfast. **Umfang:** 100 Karten. **ID:** `27f1ecdb-7caa-4a03-9ec2-2c5c55119eec`.

**Deckplan:** Toughness-Combat / Defender. Felothar lässt Kreaturen mit Widerstandskraft Schaden zufügen und Defender angreifen; Walls werden zum Angriff und zu einem großen Draw-Opfer verwertet.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `sacrifice, lifegain` → Philosophien `combo, midrange`. Auto ohne Tags: `sacrifice, lifegain`. Themes: `graveyard, lifegain, sacrifice, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Rampart Architect **50 → 50**; Felothar the Steadfast **50 → 50**; Indulging Patrician **47.5 → 47.5**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Kritischer Plankonflikt. **SmartBot 2:** Identisch. _attack summiert Power statt tatsächlich zu erwartendem Toughness-Schaden; Trades und Ziele folgen ebenfalls einfachen P/T-Werten. lifegain/sacrifice verfehlt den Archetyp, Version 2 bleibt unverändert. Opferwahl maximiert nicht Karten gleich Toughness bei kleinem Discard gleich Power.

### 47. Jeskai Striker - Tarkir: Dragonstorm Commander

**Commander:** Shiko and Narset, Unified. **Umfang:** 100 Karten. **ID:** `fb0c8357-7d17-45a9-911d-480fdb0d8ce1`.

**Deckplan:** Second-Spell / Kopieren / Spellslinger. Shiko/Narset kopiert den zweiten Spell pro Zug bei geeignetem Target bzw. zieht eine Karte; gute Enabler und Payoffs benötigen die richtige Reihenfolge.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, spellslinger` → Philosophien `combo, spells`. Auto ohne Tags: `combo, spellslinger`. Themes: `graveyard, spellslinger, tokens`. Akzeptierte Combo-Varianten: **2**.

**Hohe Grundwerte (1 → 2):** Adaptive Training Post **58.5 → 58.5**; Storm-Kiln Artist **50 → 50**; Narset's Reversal **48 → 48**.

**Version-2-Effekt:** alle gemessenen Nichtland-Kartenwerte unverändert.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Identisch. Das Scoring zählt weder bisher gewirkte Spells noch den Mehrwert eines großen zweiten Zielspells. Kleine günstige Spells können dadurch das Kopierfenster verbrauchen. Die spells-Philosophie bringt Version 2 keinen einzigen Rollenbonus; auch gegnerische Züge werden nicht aktiv für den zweiten Spell vorbereitet.

### 48. Mardu Surge - Tarkir: Dragonstorm Commander

**Commander:** Zurgo Stormrender. **Umfang:** 100 Karten. **ID:** `1d3f6986-7524-426a-b1bb-a3356239d3e2`.

**Deckplan:** Mobilize / Token-Combat / Aristocrats. Zurgo schickt temporäre Tokens in den Angriff; ihr Verlassen gibt während des Angriffs Karten, sonst Tisch-Drain. Anthems und Death-Payoffs ergänzen den Schwarm.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `tokens, sacrifice` → Philosophien `midrange, resources`. Auto ohne Tags: `tokens, sacrifice`. Themes: `sacrifice, tokens, voltron`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Zurgo Stormrender **83.5 → 93.5**; Deadly Dispute **61 → 81**; Bastion of Remembrance **59.5 → 59.5**.

**Größte Zusatzboni, Beispiele:** Solemn Simulacrum **34 → 54**; Deadly Dispute **61 → 81**; Bone Devourer **18 → 28**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gemischt. Commander und Deadly Dispute stehen plausibel weit oben. Die Entscheidung, Tokens vor oder nach Ende des Angriffs zu opfern, verändert jedoch den Ertrag und wird nicht geplant. Version 2 gibt Draw/Ramp mehr Gewicht, ohne die zwei verschiedenen Zurgo-Ausgänge zu vergleichen.

### 49. Sultai Arisen - Tarkir: Dragonstorm Commander

**Commander:** Teval, the Balanced Scale. **Umfang:** 100 Karten. **ID:** `89847c52-416a-4f95-8ebe-2f9a23f7292a`.

**Deckplan:** Attack-Self-Mill / Lands / Graveyard-Tokens. Teval millt beim Angriff, bringt ein Land zurück und erzeugt bei Graveyard-Exits Zombies; Jarad und das wachsende Board liefern den Abschluss.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `graveyard, tokens` → Philosophien `midrange, resources`. Auto ohne Tags: `graveyard, tokens`. Themes: `graveyard, sacrifice, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Teval, the Balanced Scale **62 → 62**; Jarad, Golgari Lich Lord **58 → 58**; Woe Strider **47.5 → 47.5**.

**Größte Zusatzboni, Beispiele:** Life from the Loam **33 → 43**; River Kelpie **16.5 → 26.5**; Disciple of Bolas **30 → 40**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Leicht besser beim Aufbau. Teval erhält einen sinnvollen Commander-Bonus, aber Angriffe werden ohne den Wert der Mill-/Land-Rückkehr bewertet. graveyard→midrange verwehrt Version 2 den eigentlichen Rekursionsbonus. Ein Loam-Draw-Bonus ersetzt keine Land-/Exit-Sequenz.

### 50. Temur Roar - Tarkir: Dragonstorm Commander

**Commander:** Eshki, Temur's Roar. **Umfang:** 100 Karten. **ID:** `470d134f-31eb-4f46-b74a-d53cf0a5920b`.

**Deckplan:** Big-Creature-Cast / Power-Schwellen. Kreaturen-Casts wachsen Eshki; Power ab 4 zieht Karten, ab 6 verursacht Schaden an allen Gegnern. Der Cast-Payoff ergänzt Combat.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `tokens, stompy` → Philosophien `combat, resources`. Auto ohne Tags: `tokens, stompy`. Themes: `graveyard, stompy, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Temur Ascendancy **47.5 → 79.5**; Eshki, Temur's Roar **47.5 → 57.5**; Become the Avalanche **43 → 75**.

**Größte Zusatzboni, Beispiele:** Temur Ascendancy **47.5 → 79.5**; Become the Avalanche **43 → 75**; Deceptive Frostkite **41 → 63**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gezielt besser mit Verzerrung. Version 2 stärkt Stompy-Enabler erheblich, berücksichtigt aber nicht die konkrete gedruckte Power der nächsten Kreatur und deren 4-/6-Schwellen. Die zusätzlichen +8 für Stompy sind Kartenwerte und ändern die Angriffslogik nicht. Kleine Value- oder Rampkarten können weiterhin die eigentlichen Trigger-Bodycasts verdrängen.

### 51. Eternal Might - Aetherdrift Commander

**Commander:** Temmet, Naktamun's Will. **Umfang:** 100 Karten. **ID:** `0aea2144-645a-46c8-b9ad-0743fa765b34`.

**Deckplan:** Zombie-Draw / Attack / Reanimator. Temmet zieht und lootet beim Angriff; jede gezogene Karte pumpt Zombies bis Zugende. Draw vor bzw. während Combat skaliert den Angriff.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `tokens, graveyard` → Philosophien `midrange, resources`. Auto ohne Tags: `tokens, graveyard`. Themes: `clones, graveyard, lifegain, sacrifice, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** The Scarab God **56.5 → 56.5**; Gate to the Afterlife **55.5 → 65.5**; Crowded Crypt **51.5 → 61.5**.

**Größte Zusatzboni, Beispiele:** Commander's Sphere **35.5 → 55.5**; Rhet-Tomb Mystic **21 → 31**; Commence the Endgame **27 → 37**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Leicht besser beim Aufbau. Version 2 stärkt Draw/Ramp und trifft damit einen Teil des Plans. Sie plant Draw aber nicht anhand der Zahl angriffsbereiter Zombies und des möglichen Schadens. Die naive Rollenkennung verpasst '+1/+1 until end of turn' auf andere Formulierungen und unterscheidet Mainphase 1/2 nicht nach diesem Pump-Fenster.

### 52. Living Energy - Aetherdrift Commander

**Commander:** Saheeli, Radiant Creator. **Umfang:** 100 Karten. **ID:** `1f4af9da-02ef-41ac-b794-8915442ad989`.

**Deckplan:** Energy / Artefakt-Copies / Combat. Saheeli sammelt Energy aus passenden Casts und kopiert zum Combat ein Permanent als 5/5-Haste-Kreatur; Energy- und Extra-Combat-Schleifen sind vorhanden.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, energy` → Philosophien `combo, resources`. Auto ohne Tags: `combo, energy`. Themes: `clones, energy, tokens, vehicles`. Akzeptierte Combo-Varianten: **4**.

**Hohe Grundwerte (1 → 2):** Saheeli, Radiant Creator **109 → 109**; Attune with Aether **72.5 → 82.5**; Solemn Simulacrum **64 → 84**.

**Größte Zusatzboni, Beispiele:** Commander's Sphere **35.5 → 55.5**; Solemn Simulacrum **64 → 84**; Aetheric Amplifier **27.5 → 37.5**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Leicht besser beim Aufbau. Commander und Enabler bekommen hohe Werte. Version 2 stärkt Ressourcen statt Energy-Schwelle oder bestes Copy-Ziel; drei Energy rechtzeitig frei zu halten ist kein explizites Ziel. Combat-Combo-Pieces dürfen weiterhin gar nicht angreifen, selbst wenn ihr Angriff für die Schleife nötig ist.

### 53. Animated Army - Bloomburrow Commander

**Commander:** Bello, Bard of the Brambles. **Umfang:** 100 Karten. **ID:** `4b83591c-f52d-4b0d-b5c9-53c486ad10dc`.

**Deckplan:** Bello: große Artefakte/Enchantments als Armee. Bello macht passende Permanents ab Mana Value 4 im eigenen Zug zu unzerstörbaren Haste-Angreifern mit Combat-Draw.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, tokens` → Philosophien `combo, resources`. Auto ohne Tags: `combo, tokens`. Themes: `tokens, voltron`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Bello, Bard of the Brambles **59.5 → 69.5**; Farseek **59 → 69**; Rampant Growth **59 → 69**.

**Größte Zusatzboni, Beispiele:** Big Score **46 → 66**; Hedron Archive **34 → 54**; Mind Stone **37 → 57**.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Gemischt. Der hohe Wert von genau vier Mana wird vom allgemeinen Mana-Value-Malus nicht erkannt. Version 2 stärkt Draw/Ramp, während eine nebensächliche Landfall-Combo Teile vor dem Angriff schützt. Auch teure scheinbare Nichtkreaturen sind nur mit Bello echte Threats; dies braucht Board- und Sequenzbewertung.

### 54. Family Matters - Bloomburrow Commander

**Commander:** Zinnia, Valley's Voice. **Umfang:** 100 Karten. **ID:** `f0583ada-fab5-472e-95b9-c0c1afe5357e`.

**Deckplan:** Offspring / ETB / Go-wide. Zinnia kopiert Kreaturen durch Offspring in 1/1-Form; ETBs und ein breites Team stärken den fliegenden Commander. Helm plus Combat Celebrant ist eine Nebencombo.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, tokens` → Philosophien `combo, resources`. Auto ohne Tags: `combo, tokens`. Themes: `lifegain, tokens`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Solemn Simulacrum **64 → 84**; Helm of the Host **57 → 57**; Zinnia, Valley's Voice **51.5 → 51.5**.

**Größte Zusatzboni, Beispiele:** Mind Stone **37 → 57**; Solemn Simulacrum **64 → 84**; Boros Signet **29 → 39**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gemischt. Version 2 stärkt Solemn Simulacrum sehr deutlich, ohne dessen optionalen Offspring-Aufpreis mit einer Alternative zu vergleichen. Combat Celebrant als Combo-Piece wird grundsätzlich nicht angegriffen, was die Angriffslinie beeinträchtigt. Niedrige Basispower und ETB-Nutzen werden nicht spezifisch kombiniert.

### 55. Peace Offering - Bloomburrow Commander

**Commander:** Ms. Bumbleflower. **Umfang:** 100 Karten. **ID:** `d21a06b5-746e-4383-b17d-793d31f62c5f`.

**Deckplan:** Group-Hug / Draw-Counters / alternative Siege. Bumbleflower schenkt Draw, wächst das Board und belohnt den zweiten Spell; Triskaidekaphile, Twenty-Toed Toad, Simic Ascendancy und Psychosis Crawler liefern Abschlüsse.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `tokens, group-slug` → Philosophien `control, resources`. Auto ohne Tags: `tokens, group-slug`. Themes: `group-slug, lifegain, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Ms. Bumbleflower **46 → 56**; Triskaidekaphile **45 → 55**; Twenty-Toed Toad **42 → 52**.

**Größte Zusatzboni, Beispiele:** An Offer You Can't Refuse **30.5 → 58.5**; Long River's Pull **21 → 49**; Wear Down **21 → 43**.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Gemischt. group-slug ist hier eine Fehlklassifikation gegenüber Group-Hug. Version 2 belohnt dadurch Control-Interaktion und Ressourcen, kennt aber weder Handkarten-Zielzahl noch Counter-/Upkeep-Schwelle. Draw wird sogar bei kleiner Hand stärker gewichtet; der notwendige Wechsel zum Bewahren einer konkreten Gewinnkonfiguration fehlt.

### 56. Squirreled Away - Bloomburrow Commander

**Commander:** Hazel of the Rootbloom. **Umfang:** 100 Karten. **ID:** `67f93f62-4d95-4eac-9623-f092f0d6d145`.

**Deckplan:** Squirrel-Tokens / Aristocrats / Mana. Hazel macht Tokens zu Mana und kopiert sie im Endstep; Chatterfang, Drain-Payoffs, Anthems und ein Artefakt-Token-Motor ergänzen sich.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, tokens` → Philosophien `combo, resources`. Auto ohne Tags: `combo, tokens`. Themes: `clones, graveyard, lifegain, sacrifice, tokens`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Gilded Goose **101.5 → 111.5**; Hazel of the Rootbloom **78 → 88**; Gourmand's Talent **73.5 → 73.5**.

**Größte Zusatzboni, Beispiele:** Deadly Dispute **61 → 81**; Skullclamp **34.5 → 44.5**; Golgari Signet **29 → 39**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Leicht besser beim Aufbau. Resources trifft einen echten Bedarf, aber Gilded Goose erhält durch viele sich überlagernde Rollen und Combo-Zugehörigkeit extremen Vorrang. Kein expliziter Vergleich zwischen Tokens für Mana tappen, angreifen oder opfern; auch Hazels Kopierziel folgt keinem Ertrag über mehrere Züge.

### 57. Multiverse Reforged - Reality Fracture

**Commander:** Jace, Multiverse Architect. **Umfang:** 100 Karten. **ID:** `a06f644d-c23a-4d6c-9d91-86f5113b1eaa`.

**Deckplan:** Token→Polymorph / Planeswalker-Value. Jace und Polymorph-Effekte tauschen kleine Tokens gegen große Kreaturen/Planeswalker; Draw/Topdeck-Manipulation und starke Treffer tragen den Plan.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, tokens` → Philosophien `combo, resources`. Auto ohne Tags: `combo, tokens`. Themes: `lifegain, spellslinger, tokens`. Akzeptierte Combo-Varianten: **1**.

**Hohe Grundwerte (1 → 2):** Brainstorm **57.5 → 67.5**; Venser, Fervent Forger **54 → 54**; Fatehold Charm **45 → 55**.

**Größte Zusatzboni, Beispiele:** Staff of the Storyteller **33 → 43**; Occult Epiphany **34.5 → 44.5**; Shark Typhoon **39 → 49**.

**Urteil SmartBot 1:** Schwach. **SmartBot 2:** Gemischt. Die erkannte Brainstorm/Dack/Venser-Combo zieht Priorität, aber die normale Polymorph-Linie benötigt Ziel- und Bibliotheksplanung. beneficial-Ziele nach höchstem Kartenwert können gerade das wertvolle eigene Permanent statt des entbehrlichen Tokens auswählen. Version 2 verbessert nur Ressourcen, nicht die Umwandlungsrendite.

### 58. Calling All Angels - Foundations Commander

**Commander:** Giada, Font of Hope. **Umfang:** 100 Karten. **ID:** `3e6f01ec-ceb5-4010-a75c-43c6f0b34fe3`.

**Deckplan:** Angel-Typal / Counter / Flying-Combat. Giada beschleunigt Angels und lässt sie mit wachsenden Countern eintreten; fliegende große Bodies, Lifegain und Anthems gewinnen.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `lifegain, tokens` → Philosophien `combo, resources`. Auto ohne Tags: `lifegain, tokens`. Themes: `graveyard, lifegain, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Giada, Font of Hope **57 → 67**; Righteous Valkyrie **47.5 → 47.5**; Speaker of the Heavens **38.5 → 38.5**.

**Größte Zusatzboni, Beispiele:** Commander's Sphere **35.5 → 55.5**; Mind Stone **37 → 57**; Angelic Sleuth **31.5 → 41.5**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Leicht besser beim Aufbau. Giadas Ramp-Rolle wird passend hoch gewichtet. lifegain/tokens beschreibt jedoch den eigentlichen Angel-/Counter-Plan ungenau. Version 2 bevorzugt Rocks und Draw stärker; das Eintreten weiterer Angels und die Giada-Skalierung fehlen als Synergiebonus.

### 59. Keen Engineering - Foundations Commander

**Commander:** Sai, Master Thopterist. **Umfang:** 100 Karten. **ID:** `c0ce6eae-32ba-4df5-889c-00d324b663e4`.

**Deckplan:** Artefakt-Engine / Thopter-Go-wide. Sai macht aus Artefakt-Casts fliegende Thopters; Anthems, Nettlecyst, große Artefaktkörper und Psychosis Crawler verwerten das Board bzw. Draw.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `tokens, vehicles` → Philosophien `resources`. Auto ohne Tags: `tokens, vehicles`. Themes: `tokens, vehicles, voltron`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Sai, Master Thopterist **59.5 → 69.5**; Psychosis Crawler **40.5 → 50.5**; Cultivator's Caravan **39.5 → 49.5**.

**Größte Zusatzboni, Beispiele:** Hedron Archive **34 → 54**; Mind Stone **37 → 57**; Mazemind Tome **21 → 31**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gemischt. Resources ist passend, voltron beschreibt nur einen Teil. Psychosis Crawler erhält in Version 2 einen Combat-wincon-Bonus, obwohl sein Drain kein Combat ist. Die generische Opferwahl schützt teure Karten statt den Nettoertrag von zwei Artefakten gegen eine Karte samt Death-/Recursion-Effekten zu berechnen.

### 60. Reign of Dragons - Foundations Commander

**Commander:** Lathliss, Dragon Queen. **Umfang:** 100 Karten. **ID:** `3647486c-7e13-47ef-8a99-7a2ecc2d5015`.

**Deckplan:** Dragon-Typal / ETB-Damage / Flying-Combat. Lathliss vervielfacht eintretende Dragons; Dragon Tempest/Scourge of Valkas und große fliegende Angriffe schließen ab.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `tokens, graveyard` → Philosophien `midrange, resources`. Auto ohne Tags: `tokens, graveyard`. Themes: `graveyard, stompy, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Lathliss, Dragon Queen **47 → 47**; Unexpected Windfall **46 → 66**; Rapacious Dragon **36.5 → 46.5**.

**Größte Zusatzboni, Beispiele:** Unexpected Windfall **46 → 66**; Dragon's Hoard **35.5 → 55.5**; Commander's Sphere **35.5 → 55.5**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gemischt. Version 2 stärkt Stompy und Ressourcen, aber Lathliss selbst bekommt keinen Zusatzbonus und kann hinter Unexpected Windfall fallen. Dragon-Dichte und der nächste Dragon-ETB mit vorhandenem Payoff werden nicht berechnet. Die Kontrolle, wann genug Ramp vorhanden ist, hängt nur teilweise am Board.

### 61. Tramplesaurus Rex - Foundations Commander

**Commander:** Ghalta, Primal Hunger. **Umfang:** 100 Karten. **ID:** `828251db-02d6-44cb-a4e0-97d649c6e486`.

**Deckplan:** Power-Ramp / Stompy / Ghalta. Kreaturenstärke verbilligt Ghalta; Trample, Haste und Overrun-Effekte wandeln große Bodies in einen schnellen Abschluss um.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `stompy, lifegain` → Philosophien `combat, combo`. Auto ohne Tags: `stompy, lifegain`. Themes: `lifegain, stompy, tokens, voltron`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Rhonas the Indomitable **63.5 → 91.5**; Goreclaw, Terror of Qal Sisma **62 → 90**; Ilysian Caryatid **57 → 71**.

**Größte Zusatzboni, Beispiele:** Rhonas the Indomitable **63.5 → 91.5**; Goreclaw, Terror of Qal Sisma **62 → 90**; Shamanic Revelation **56.5 → 70.5**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Besser bei Kartenwahl, Combat unverändert. Version 2 stärkt Rhonas/Goreclaw, aber Ghalta bleibt nach gedrucktem Mana Value 12 abgewertet, obwohl die tatsächlichen Kosten oft viel kleiner sind. Das zusätzliche lifegain→combo-Etikett unterdrückt den vorgesehenen Stompy-Extra-+8. Trample-Lethal und profitable Mehrfachblock-Angriffe werden weiter verfehlt.

### 62. Wretched Ranks - Foundations Commander

**Commander:** Ghoulcaller Gisa. **Umfang:** 100 Karten. **ID:** `742cad96-fb1b-44a1-9ca3-343842733bea`.

**Deckplan:** Zombie-Tokens / Sacrifice / Drain. Gisa verwandelt hohe Power in viele Zombies; Lords, Rekursion und Ayara/Gray Merchant/Vengeful Dead verwerten Masse und Tod.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `tokens, graveyard` → Philosophien `midrange, resources`. Auto ohne Tags: `tokens, graveyard`. Themes: `graveyard, lifegain, sacrifice, tokens`. Akzeptierte Combo-Varianten: **0**.

**Hohe Grundwerte (1 → 2):** Ayara, First of Locthwain **67.5 → 77.5**; Ghoulcaller Gisa **60.5 → 60.5**; Bontu's Monument **47.5 → 47.5**.

**Größte Zusatzboni, Beispiele:** Infernal Idol **35.5 → 55.5**; Mind Stone **37 → 57**; Commander's Sphere **35.5 → 55.5**.

**Urteil SmartBot 1:** Bedingt sinnvoll. **SmartBot 2:** Gemischt. Gisa und Drain-Payoffs sind sinnvoll hoch, doch Opferziele werden nach niedrigstem Kartenwert statt größtem Zombie-Ertrag mit vertretbaren Kosten gewählt. graveyard wird nicht zur gleichnamigen Philosophie, Version 2 erhöht hauptsächlich Rocks und Draw. Keine echte Zombie-Typal- oder Opfer-Rendite-Bewertung.

### 63. Sans Soleil MWI

**Commander:** Dack Fayden, Helping Hand. **Umfang:** 100 Karten. **ID:** `d4dc46d6-92d4-48cb-a908-be5e9ad08746`.

**Deckplan:** Stax / Blink-Combo / Commander verschenkt Kreaturen. Dack bringt Kreaturen aus der eigenen Bibliothek unter gegnerische Kontrolle; die Liste enthält Blink-/Preston-Schleifen, Stax und Blind Obedience als Verwertung.

**Bot-Profil:** gespeicherte Tags `keine`; wirksam `combo, tokens` → Philosophien `combo, resources`. Auto ohne Tags: `combo, tokens`. Themes: `group-slug, lifegain, spellslinger, tokens`. Akzeptierte Combo-Varianten: **10**.

**Hohe Grundwerte (1 → 2):** Charitable Levy **75 → 85**; Eldrazi Confluence **73 → 83**; Expedition Map **60.5 → 70.5**.

**Größte Zusatzboni, Beispiele:** Staff of Compleation **35.5 → 55.5**; Abeyance **21 → 31**; Arcane Signet **29 → 39**.

**Urteil SmartBot 1:** Kritischer Sonderplan; Datenlücke. **SmartBot 2:** Gemischt. Erebor Heirloom fehlt im Karten-Cache: die Messung ist unvollständig. Dacks ETB verändert die Kontrolle der geladenen Kreaturen; ein pauschaler Commander-Bonus bildet dieses Risiko nicht ab. Stax-Karten besitzen meist keine Rolle, während resources generische Karten stärkt. Blink-Ziele und an Gegner abgegebene Combo-Kreaturen benötigen eine explizite Planung.

## Priorität für eine Verbesserung

1. **Zuerst harte Plankonflikte:** Combo-Angriffssperre kontextabhängig machen; Commander-Trigger, Toughness-, Poison- und Commander-Schaden im Combat bewerten. Malcolm, Raggadragga und Felothar sind konkrete Prüfdecks.
2. **Erkennung und Scoring auf dasselbe Vokabular bringen:** erzeugte Rollen für spells/lands/counters, korrekte graveyard/sacrifice-Zuordnung und reproduzierbare Theme-Gleichstände. Erst danach zusätzliche Boni abstimmen. Marchesa, Tidus, Zimone und Vivi sind geeignete Gegenproben.
3. **Entscheidungsertrag statt Quellkartenwert:** Opfermenge/-ziel, Equip-Ziel, Reanimation, Copy und Polymorph anhand des tatsächlichen Effekts bewerten. Gisa, Dina, Cloud und Multiverse Reforged decken unterschiedliche Fehler auf.
4. **Deckplan-Sequenzen ergänzen:** zuerst Oracle/Pact und notwendige Attack-Combos, dann X-/Tutor-/Mana-Outlet-Verwertung, zweite-Spells-pro-Zug und Endstep-/gegnerische-Turn-Pläne. Erkannte Combo-Assembly ausdrücklich von ausführbarer Win-Line unterscheiden.
5. **Danach empirisch vergleichen:** gleiche Seeds/Starthände, identische Gegner/Seats und getrennte Erfolgsgrößen für Entwicklung, Planfortschritt, verpasste Abschlüsse und Siege. Diese Bestandsaufnahme liefert die Hypothesen und Prüfdecks; die bestehenden 34 Tests reichen als Deckqualitätsnachweis nicht aus.

## Lokale Quellen und Verifikation

- [Strategie- und Rollenerkennung](../../backend/mtg_analyzer/services/bot_strategy.py): `ROLE_PATTERNS`, `ARCHETYPE_PHILOSOPHIES`, `build_strategy`.
- [SmartBot 1](../../backend/mtg_analyzer/services/bot_policies/smart.py): `_card_value`, `answer_choice`, `play`, `_attack`, `blocks`.
- [SmartBot 2](../../backend/mtg_analyzer/services/bot_policies/smart2.py): `_PHILOSOPHY_ROLES`, `_card_value`; keine eigene Spiel-/Angriffsmethode.
- [Solo-Setup](../../backend/mtg_analyzer/api/solo.py): gespeicherte Archetypen werden an die Session übergeben.
- [Regressionstests](../../backend/tests/services/test_smart_bot.py): ausgeführt mit `python3 backend/scripts/run_tests.py tests/services/test_smart_bot.py -q`, **34 passed**.
- Lokale Datenquellen: `backend/data/decks.db`, `backend/cache/db/cards.db`, `backend/data/commander_spellbook.db` (nur gelesen). Die Deck-ID in jedem Abschnitt unterscheidet auch gleich benannte Listen.

### Fingerabdrücke der analysierten Quellen

SHA-256 der relevanten Dateien zum Messzeitpunkt; Änderungen an diesen Dateien können die Ergebnisse verändern.

| Quelle | SHA-256 |
| --- | --- |
| `backend/mtg_analyzer/services/bot_strategy.py` | `14a4d78a435b82b611e714aad1abffb858c8d6df9493d9e534c61db10aa278e3` |
| `backend/mtg_analyzer/services/bot_policies/smart.py` | `502e1dfd9e7cd63e4fed4ab5a0f2ee71c3f16f9471b43b75303118adab1f6a3c` |
| `backend/mtg_analyzer/services/bot_policies/smart2.py` | `cb3502c8d5e37ca95bcb2e5e4af0b212f1e59e22a06ac7fa065b561dd9ea0aed` |
