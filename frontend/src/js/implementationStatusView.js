// "Status" tab: a readable overview of what the rules engine actually
// implements — combat/evasion keywords, the static-ability layer system
// (RULE 613), activated & triggered abilities, one-shot effects and the
// remaining gaps. Static content (no server call); kept in sync by hand with
// the backend (mtg_analyzer/game/) — see CLAUDE.md "Implementation state".

const LEGEND = [
  ['full', '✅', 'Vollständig', 'Von der Engine umgesetzt und getestet.'],
  ['partial', '◐', 'Teilweise', 'Grundfall funktioniert, mit dokumentierten Grenzen.'],
  ['planned', '✖', 'Geplant', 'Modelliert/vorgesehen, aber noch nicht umgesetzt.'],
];

// section = { title, rule, intro?, items: [ [status, label, note] ] }
const SECTIONS = [
  {
    title: 'Spielablauf & Zugstruktur',
    rule: 'RULE 500–514',
    intro:
      'Der Goldfisch-Modus spielt gegen die echte Backend-Regel-Engine: Schritt für ' +
      'Schritt durch den Zug, mit Stack, Prioritätsfenstern und Zustandsbasierten ' +
      'Aktionen (SBA). Jeder Zug wird server-seitig validiert; Zurücknehmen/Neustart jederzeit.',
    items: [
      ['full', 'Phasen & Schritte', 'Untap, Upkeep, Draw, Main I, Kampf (5 Schritte), Main II, End, Cleanup.'],
      ['full', 'Stack & Priorität', 'LIFO-Auflösung (RULE 608), Instants als Antwort, Priorität abgeben.'],
      ['full', 'Zustandsbasierte Aktionen', 'Leben ≤ 0, leere Bibliothek, 0 Widerstandskraft, tödlicher Schaden, Legenden-Regel.'],
      ['full', 'Mulligan', 'London-Mulligan mit Karten-auf-den-Boden-Legen; „on the play/draw".'],
      ['full', 'Rückgängig / Neustart / Rewind', 'Snapshot-Historie pro Aktion.'],
      ['partial', 'Interaktive Priorität (Basis)', '`pass_priority(player)` reicht Priorität nach APNAP weiter und löst den Stack erst auf, wenn alle Spieler nacheinander passen (RULE 117.3-4); eine Aktion holt die Priorität zurück. Engine-Primitive vorhanden; noch nicht in die Multiplayer-Session/WS eingehängt.'],
      ['partial', 'Passiver Gegner ("Goldfisch")', 'Gültiges Angriffsziel; spielt selbst keine Karten. Interaktiver Blocker-Modus über `declare_blockers` vorhanden, aber solo ungenutzt.'],
    ],
  },
  {
    title: 'Replay / Puzzle-Modus',
    rule: 'UC3-Schwester',
    intro:
      'Neben dem Goldfisch: einen beliebigen Spielzustand bauen (1 Spieler = Puzzle, ' +
      'oder mit 1 Gegner) und daraus spielen — dieselbe Regel-Engine, aber frei ' +
      'editierbar. Als JSON-Datei speicherbar/ladbar; ein Goldfisch-Zustand lässt ' +
      'sich per „Als Replay speichern" exportieren und hier wieder öffnen.',
    items: [
      ['full', 'Karten/Token in jede Zone', 'Hinzufügen/Entfernen/Verschieben in Schlachtfeld, Hand, Friedhof, Bibliothek, Exil, Kommandozone.'],
      ['full', 'Objekt-Zustand', 'Tappen, Umwandeln (DFC), beliebige Marken setzen (+1/+1, Loyalität, …).'],
      ['full', 'Spieler-Werte', 'Leben, Giftmarken (10 = Verlust, SBA), Energie/Erfahrung & freie Marken, Commander-Schaden.'],
      ['full', 'Zug/Phase setzen', 'Zugnummer, Schritt und aktiven Spieler direkt setzen, um mitten im Zug zu starten.'],
      ['full', 'Speichern/Laden (JSON)', 'Re-auflösbares Replay-Format (Karten aus dem Cache rekonstruiert); Export/Import per Datei.'],
      ['partial', 'Spielerzahl', 'Aktuell 1 (Puzzle) oder 2 (mit Gegner); mehr Spieler noch nicht.'],
    ],
  },
  {
    title: 'Kampf- & Evasion-Keywords',
    rule: 'RULE 702',
    intro:
      'Erkannt aus der Scryfall-`keywords`-Liste und dem Oracle-Text (klausel-genau, ' +
      'game/combat.py) und vollständig in der Kampf-Engine umgesetzt. Auf dem Board als ' +
      'Badges sichtbar (FLY, TR, DT …).',
    items: [
      ['full', 'Flying / Reach', 'Flieger nur von Flying/Reach blockbar (RULE 509.1b).'],
      ['full', 'First Strike / Double Strike', 'Zwei Schadens-Schritte (RULE 510); Erstschlag tötet vor Rückschlag.'],
      ['full', 'Deathtouch', 'Jeder Schaden ist tödlich (RULE 702.2b), auch bei Trample.'],
      ['full', 'Trample', 'Überschuss über Letalschaden trifft den Verteidiger.'],
      ['full', 'Vigilance', 'Angreifen tappt nicht.'],
      ['full', 'Lifelink', 'Beherrscher gewinnt Leben in Höhe des Schadens.'],
      ['full', 'Menace', 'Muss von ≥ 2 Kreaturen geblockt werden.'],
      ['full', 'Defender / Haste', 'Kann nicht angreifen / ignoriert Einsatzkrankheit.'],
      ['full', 'Indestructible', 'Übersteht tödlichen Schaden und Deathtouch.'],
      ['full', 'Landwalk', '„Islandwalk"/„Forestwalk" … — nicht blockbar, solange der Verteidiger ein Land des Typs kontrolliert (RULE 702.14); gebunden aus dem Keyword-Katalog + Layer-6-Grants.'],
      ['full', 'Protection from …', '„DEBT" komplett (RULE 702.16): verhindert Schaden von jeder Quelle (nicht nur im Kampf), Blocken, Anvisieren durch Zaubersprüche/Fähigkeiten sowie Verzaubern/Ausrüsten/Fortifizieren durch eine Quelle der genannten Eigenschaft — Farbe (inkl. Layer-5-Farbwechsel), „creatures", Kartentyp („artifacts" …), Kreaturentyp („Dragons" …), „all colors" und „everything"; mehrere Eigenschaften über „and from" (Sword-of-X-and-Y-Zyklus).'],
    ],
  },
  {
    title: 'Statische Fähigkeiten — Layer-System',
    rule: 'RULE 613',
    intro:
      'game/continuous.py leitet die Eigenschaften jeder bleibenden Karte in Layer-' +
      'Reihenfolge neu her (bei jeder SBA-Prüfung und vor jeder Ansicht), inklusive einer ' +
      'Layer-für-Layer-Herleitung pro Objekt (im Goldfisch über „🔍 Statische Effekte" sichtbar).',
    items: [
      ['full', 'Layer 2 — Kontrollwechsel', 'Statischer „Du kontrollierst …"-Effekt weist die Kontrolle neu zu (RULE 613.2), idempotent über Recompute.'],
      ['full', 'Layer 4 — Typänderung', 'z. B. Land wird 0/0-Kreatur (add_types + P/T).'],
      ['full', 'Layer 5 — Farbwechsel', '„… ist schwarz" setzt/ergänzt die Farbe (RULE 613.4b); fließt in Protection.'],
      ['full', 'Layer 6 — Fähigkeiten verleihen', 'Keyword-Grants (z. B. „… haben Flying") fließen in den Kampf. Auch Mana-Fähigkeiten („Elfen … haben {T}: Erzeuge {B}", Tyvar Kell) und volle ausgelöste Fähigkeiten (Dionus: „… haben Wenn-diese-Kreatur-tappt-…") lassen sich verleihen — trotz CR 612.1 kein Layer 3, siehe unten.'],
      ['full', 'Layer 7 — Stärke/Widerstandskraft', '7a CDA (P/T = Anzahl X) → 7b Setzen → 7c Marken → 7d Ändern (Anthems) → 7e P/T-Tausch.'],
      ['full', 'Zeitstempel-Ordnung', 'Innerhalb eines Layers nach Objekt-Zeitstempel (RULE 613.7b) — der jüngste Effekt zuletzt.'],
      ['full', 'Kostenanpassung (kein Layer)', '„Zaubersprüche kosten {N} weniger/mehr" (RULE 601.2f), generisch, beim Zaubern.'],
      ['partial', 'Layer 1 — Kopie-Effekte', '„Wird eine Kopie von Zielobjekt" (RULE 706/707): `RulesEngine.become_copy` ersetzt Name/Manakosten/Farbe/Typ/Text/S-W/Fähigkeiten durch die des kopierten Objekts (siehe „become_copy" unten), inklusive interaktiver Zielwahl. Als gewöhnlicher ETB-Trigger modelliert, nicht als echter „tritt als … ins Spiel"-Ersetzungseffekt (RULE 614.1c/614.12).'],
      ['planned', 'Layer 3 (wörtliche Textänderung) & echte Abhängigkeits-Ordnung', 'Wörtliche Textänderung (Layer 3, RULE 612 — z. B. Artificial Evolution ersetzt ein Kreaturtyp-Wort im Text) und die volle Abhängigkeitsanalyse (RULE 613.8) fehlen bewusst: kein Kartenpool-Eintrag braucht wörtliche Textänderung, und die aktuelle Effekt-Palette kann gar keinen Fall erzeugen, in dem zwei Effekte im selben Layer voneinander abhängen (jede echte Interaktion läuft über verschiedene, bereits fest geordnete Layer) — eine allgemeine Abhängigkeits-Analyse wäre also ungetestet und spekulativ. Das Verleihen einer fremden Fähigkeit (Tyvar Kell, Dionus) ist trotz CR 612.1 kein Fall davon — das ist Layer 6, oben bereits abgedeckt.'],
    ],
  },
  {
    title: 'Aktivierte Fähigkeiten & Kosten',
    rule: 'RULE 602',
    intro:
      'Kosten werden per Regex aus dem „Kosten: Effekt"-Text erkannt (game/costs.py) und ' +
      'beim Aktivieren bezahlt; die Fähigkeit landet auf dem Stack.',
    items: [
      ['full', 'Mana-Kosten', 'Inkl. {X}, Hybrid, Phyrexianisch (aus dem Mana-Modell).'],
      ['full', '{T} / {Q} — Tappen / Enttappen', '{T} respektiert Einsatzkrankheit (RULE 302.6).'],
      ['full', 'Opfern', '„Opfere ~" (selbst) oder „Opfere eine Kreatur/…" (Typ).'],
      ['full', 'Leben zahlen / Karten abwerfen', '„Pay N life", „Discard a card / N cards / your hand".'],
      ['full', 'Marken entfernen', '„Remove N +1/+1 / loyalty counters".'],
      ['full', 'Loyalitäts-Kosten', '[+N]/[−N]/[0] als Kosten (RULE 606.5c) — nur zu Hexerei-Zeit, einmal pro Zug je Planeswalker.'],
      ['full', 'Als Button im Goldfisch', 'Aktivierbare Fähigkeiten erscheinen als Aktion unter der Karte (mit Ziel-/{X}-Auswahl).'],
      ['full', 'Fetch-Länder', 'z. B. Evolving Wilds: „{T}, Opfern: Standardland getappt ins Spiel" — gebunden & spielbar.'],
    ],
  },
  {
    title: 'Ausgelöste Fähigkeiten',
    rule: 'RULE 603',
    intro:
      'Ereignisbasierte Trigger (TriggeredAbility) reagieren auf den Ereignis-Bus der ' +
      'Engine und werden nach APNAP auf den Stack gelegt.',
    items: [
      ['full', 'Ereignis-Trigger', 'ENTERS_BATTLEFIELD, DIES, DRAW, DAMAGE, ATTACKS, SPELL_CAST, LIFE_GAINED, TAPPED („wird getappt", RULE 701.21b — nicht bei getappt ins Spiel kommenden Karten) u. a.'],
      ['full', 'Zielwahl für ausgelöste Fähigkeiten', 'Braucht die erste zielsuchende Wirkung eines Triggers ein Ziel, öffnet sich vor dem Auflösen eine Wahl (RULE 115) — ein Knopf je legalem Ziel, dieselbe generische Wahl-UI wie bei Tutor/Kaskade/Discover/Trigger-Reihenfolge. Ohne legales Pflichtziel landet der Trigger gar nicht erst auf dem Stack (RULE 603.3c).'],
      ['full', '„Du darfst"-Trigger', 'Optionale Trigger (RULE 603.5) fragen echt nach: mit Ziel bietet die Zielwahl „Nichts wählen" an; ohne Ziel („du darfst eine Karte ziehen") öffnet sich ein Ausführen/Nichts-tun-Entscheid.'],
      ['full', 'Ersetzungs-Effekte', 'ReplacementEffect wird bei DAMAGE angewandt; `prevent_damage` bindet aus einer `replacement`-Spec (ReplacementRegistry).'],
      ['full', 'Reihenfolge-Wahl (Trigger)', 'Bei mehreren gleichzeitigen Triggern des aktiven Spielers wählt er die Reihenfolge (RULE 603.3b, `interactive_ordering`); sonst APNAP-Standard. Kombiniert mit einer Ziel-Wahl für einen der georderten Trigger nicht abgedeckt (Randfall).'],
    ],
  },
  {
    title: 'Einmal-Effekte (Effect-Registry)',
    rule: 'RULE 608',
    intro:
      'Whitelist benannter Effekte (game/effects.py), die Spell-/aktivierte/ausgelöste ' +
      'Fähigkeiten beim Auflösen ausführen. Ziele laufen über das Targeting-System (RULE 115).',
    items: [
      ['full', 'damage / destroy / counter', 'Schaden an beliebiges Ziel, Zerstören, Spruch neutralisieren.'],
      ['full', 'draw / discard / gain_life', 'Karten ziehen/abwerfen, Leben gewinnen.'],
      ['full', 'mill / exile / tap', 'Mühlen, Exilieren, Tappen/Enttappen von Zielen.'],
      ['full', 'add_counters (+1/+1 / −1/−1)', '+1/+1- oder −1/−1-Marken auf ein Ziel (RULE 122); −1/−1 annihilieren als SBA.'],
      ['full', 'pump („+N/+N bis Zugende")', 'Temporärer P/T-Bonus und/oder Keyword-Grant bis Zugende (Riesenwuchs; Layer 7d/6, RULE 613.4d); im Cleanup entfernt (514.2). Auch −N/−N.'],
      ['full', 'scry', 'Hellsehen N (RULE 701.18): legale Ausführung (behält oben), feuert ein SCRY-Ereignis.'],
      ['full', 'create_token', 'Inline- und benannte Tokens (RULE 111.5 / 701.6).'],
      ['full', 'search / shuffle', 'Bibliothek durchsuchen (Tutor) mit Kriterien/Ziel/Zahl.'],
      ['full', 'cascade / discover', 'Kaskade & Discover mit Spieler-Entscheidung.'],
      ['full', 'copy_permanent', 'Token-Kopie einer Ziel-bleibenden Karte (RULE 707).'],
      ['full', 'become_copy', 'Das Objekt selbst wird eine Kopie von Zielobjekt (RULE 706/707.2, statt eines neuen Tokens) — inkl. „außer dass …"-Typzusätzen (Clever Impersonator, Phantasmal Image, Copy Artifact), interaktiv spielbar über die Ziel-Wahl bei ausgelösten Fähigkeiten. Als ETB-Trigger modelliert, nicht als „tritt als … ins Spiel"-Ersetzungseffekt.'],
      ['full', 'anthem / pt_set / grant_keyword / type_change / cost_reduction', 'Die statischen Effekte oben.'],
      ['full', 'grant_mana_ability / grant_triggered_ability', 'Verleiht eine Mana- bzw. eine volle ausgelöste Fähigkeit statt eines bloßen Keywords (Tyvar Kell / Dionus, Elvish Archdruid) — Layer 6, siehe oben. Jedes betroffene Objekt bekommt eine eigene, über Recompute-Durchläufe hinweg zwischengespeicherte Instanz, damit z. B. „nur einmal pro Zug" (RULE 603.2) korrekt verfolgt wird und mit dem Verschwinden der verleihenden Fähigkeit automatisch endet.'],
    ],
  },
  {
    title: 'Weitere Mechaniken',
    rule: '',
    items: [
      ['full', 'Mana-Modell', 'Generisch, farbig, farblos, Hybrid, Mono-Hybrid, Phyrexianisch, {X}; Dual-Land-Farbwahl.'],
      ['full', 'Bind-on-load (Karten-Katalog + Oracle-Parser)', 'Fähigkeiten werden beim Spielaufbau an die Karten gebunden — aus einem Namens-Katalog (game/ability_catalogue.py) und, für nicht katalogisierte Karten, aus dem Oracle-Parser (docs/09).'],
      ['full', 'Enters tapped', 'Reine Tap-Länder kommen getappt (RULE 614.1, aus dem Oracle-Text). Bedingte Tap-Länder (Shock/Check/Fast/Slow) siehe unten.'],
      ['full', 'Bedingte Tap-Länder', 'Shock-Länder („you may pay 2 life") öffnen beim Spielen eine echte Wahl (Leben zahlen ↔ getappt, `RulesEngine.enter_land_tapped`/`resolve_land_tapped_choice`); Check-Länder („unless you control a/an …") und Fast-/Slow-Länder („… two or fewer/more other lands") werden deterministisch anhand des Boards zum Zeitpunkt des Spielens ausgewertet — keine Wahl, aber kein pauschales „ungetappt" mehr.'],
      ['full', 'Zielwahl (Targeting)', 'Legale Ziele pro Anforderung, gesperrte Sprüche ohne Ziel (RULE 601.2c).'],
      ['full', 'Tokens & Marken', '+1/+1 / −1/−1 (annihilieren als SBA), Loyalitäts-/Lore-/Ladungsmarken.'],
      ['full', 'Loyalitäts-Fähigkeiten (Planeswalker)', '[+N]/[−N]/[0] aktivierbar (RULE 606): Start-Loyalität beim Eintreten, Hexerei-Timing + einmal pro Zug, 0-Loyalität-SBA (704.5i), Kampfschaden entfernt Marken.'],
      ['full', 'Commander-Regeln + Steuer', '21 Commander-Schaden, Rückkehr in die Kommandozone, Commander-Steuer +{2} je vorheriges Wirken aus der Kommandozone (RULE 903.8).'],
      ['full', 'Kartenstrukturen (Basis)', 'Doppelseitige Karten transformieren auf dem Board (RULE 712.8, `GameObject.transform`), Token-Kopien (707) und Sagas (714: Lore-Marken pro Zug + Opfern beim letzten Kapitel).'],
      ['full', 'Anhänge (Auren/Ausrüstung/Reconfigure)', 'Auren verzaubern beim Auflösen ihr Ziel (RULE 303.4f); Equip/Fortify/Reconfigure sind aktivierbare Hexerei-Fähigkeiten mit passender Zielwahl (nur Kreaturen bzw. die Enchant-Qualität). Verlässt der Wirt das Spiel: Aura ins Grab (704.5m), Equipment/Fortification/Reconfigure werden nur unverbunden und bleiben liegen (704.5n); ein angehängtes Reconfigure-Objekt verliert/bekommt dabei seinen Kreaturtyp zurück (702.151b). Der Bonus/Keyword-Grant der Aura/Ausrüstung fließt jetzt selbst über das Layer-System („attached_permanent").'],
      ['full', 'Auswertung', 'Statistiken nach dem Spiel (gezogen/gespielt, Mana-Kurve, Schaden).'],
    ],
  },
  {
    title: 'Noch nicht implementiert',
    rule: '',
    items: [
      ['partial', 'Karten-Abdeckung (Specs)', 'Oracle-Parser Phase 1 aktiv: Instants/Hexereien, ETB-Trigger, „Kosten: Effekt"-Aktivierfähigkeiten und statische Anthem-/Lord-Effekte aus den Familien Schaden/Ziehen/Abwerfen/Zerstören/Lebensgewinn/Neutralisieren/Mühlen/Exil/Tappen/±1/±1-Marken/Pump (+N/+N bis Zugende)/Keyword-Grant bis Zugende/Hellsehen/Token-Erzeugung werden ohne Katalog-Eintrag erkannt (parser/oracle → normalize/segmenter/handlers/gate). Anthems inkl. Stammes-Lords („Andere Goblins, die du kontrollierst …"), Token-Anthems (Intangible Virtue), farb-basierte („Schwarze Kreaturen bekommen +1/+1", Bad Moon) und globale Anthems (ohne „die du kontrollierst" — alle Spieler) über Subtyp-/Token-/Farb-Filter im Layer-System. Token folgen den Regeln zum Aufhören-zu-existieren (RULE 704.5d). Fail-closed: nur vollständig abgedeckte Karten (MODELED) binden Effekte. Weitere Familien (Regenerieren/Modi „wähle eins"/„bis zu N" Ziele) folgen (docs/09).'],
      ['partial', 'Parametrische Keywords (Bindung)', 'Landwalk bindet vollständig in den Kampf; Annihilator/Kicker/Ward/Protection-Qualität werden mit Parameter geführt (`parametric_keywords`), aber ihr Verhalten (Alternativkosten, Kampfmathematik) ist noch nicht verdrahtet.'],
      ['partial', 'Ersetzungs-Reihenfolge', 'Trigger-Reihenfolge ist interaktiv (603.3b); die Ersetzungs-/Verhütungs-Reihenfolge (RULE 616.1) läuft noch deterministisch.'],
      ['partial', 'Multiplayer-Session', 'Interaktive Prioritäts-Primitive vorhanden (RULE 117); noch nicht an die WebSocket-/Multiplayer-Session angeschlossen (create_multiplayer weiterhin gestubbt).'],
      ['partial', 'Kartentyp-Strukturen (erweitert)', 'MDFC-Rückseite aus der Hand spielen/wirken (712.10) ist fertig: Vorder- und Rückseite werden als zwei unabhängige Aktionen angeboten, `RulesEngine.switch_to_face` bindet die Fähigkeiten der gewählten Seite neu (wie bei „wird zur Kopie"), ein abgelehntes Wirken der Rückseite macht den Seitenwechsel rückgängig. Noch offen: Adventure/Split-Wirken (709/715), Saga-/Class-/Level-Kapitel-Fähigkeiten (711/714/716) und Battles/Dungeons — deren Grundgerüst (Transform, Kopie, Saga-Marken) steht, die Spezial-Wirk-/Kapitel-Logik fehlt noch.'],
    ],
  },
];

function statusMeta(status) {
  return LEGEND.find((l) => l[0] === status) || LEGEND[0];
}

function itemHtml([status, label, note]) {
  const [, icon, , ] = statusMeta(status);
  return `
    <li class="impl-item impl-${status}">
      <span class="impl-badge" title="${statusMeta(status)[2]}">${icon}</span>
      <span class="impl-text"><strong>${label}</strong>${note ? ` — ${note}` : ''}</span>
    </li>`;
}

function sectionHtml(section) {
  return `
    <section class="impl-section">
      <div class="impl-section-head">
        <h3>${section.title}</h3>
        ${section.rule ? `<span class="impl-rule">${section.rule}</span>` : ''}
      </div>
      ${section.intro ? `<p class="impl-intro">${section.intro}</p>` : ''}
      <ul class="impl-list">${section.items.map(itemHtml).join('')}</ul>
    </section>`;
}

export function renderImplementationStatusView(container) {
  const legend = LEGEND.map(
    ([status, icon, name, desc]) =>
      `<span class="impl-legend-item impl-${status}"><span class="impl-badge">${icon}</span> <strong>${name}</strong> — ${desc}</span>`
  ).join('');

  container.innerHTML = `
    <div class="impl-status">
      <h2>Implementierungs-Stand der Regel-Engine</h2>
      <p class="hint">
        Was die Backend-Engine (<code>mtg_analyzer/game/</code>) heute tatsächlich kann.
        Referenz sind die offiziellen Comprehensive Rules (RULE-Nummern). Details für die
        Weiterentwicklung: <code>CLAUDE.md</code> und <code>docs/</code>.
      </p>
      <div class="impl-legend">${legend}</div>
      <div class="impl-grid">
        ${SECTIONS.map(sectionHtml).join('')}
      </div>
    </div>`;
}
