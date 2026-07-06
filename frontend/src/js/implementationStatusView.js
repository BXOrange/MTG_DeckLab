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
      ['partial', 'Passiver Gegner ("Goldfisch")', 'Gültiges Angriffsziel; spielt selbst keine Karten. Interaktiver Blocker-/Multiplayer-Modus fehlt.'],
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
      ['partial', 'Protection from …', 'Verhindert Schaden & Blocken nach Farbe/„creatures"/„everything". Farbe wird über die Color-Identity approximiert.'],
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
      ['full', 'Layer 4 — Typänderung', 'z. B. Land wird 0/0-Kreatur (add_types + P/T).'],
      ['full', 'Layer 6 — Fähigkeiten verleihen', 'Keyword-Grants (z. B. „… haben Flying") fließen in den Kampf.'],
      ['full', 'Layer 7 — Stärke/Widerstandskraft', '7b Setzen → 7c Marken → 7d Ändern (Anthems „+X/+X").'],
      ['full', 'Kostenanpassung (kein Layer)', '„Zaubersprüche kosten {N} weniger/mehr" (RULE 601.2f), generisch, beim Zaubern.'],
      ['planned', 'Layer 1–3, 5, 7a, 7e', 'Kopie, Kontrollwechsel, Textänderung, Farbe, CDAs, P/T-Tausch — noch nicht modelliert.'],
      ['planned', 'Abhängigkeits-/Zeitstempel-Ordnung', 'Innerhalb eines Layers derzeit Registrierungs-Reihenfolge (RULE 613.7).'],
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
      ['partial', 'UI im Goldfisch', 'Engine + Bezahlung getestet; noch nicht als Button im Frontend (braucht Ziel-/Kostenauswahl).'],
    ],
  },
  {
    title: 'Ausgelöste Fähigkeiten',
    rule: 'RULE 603',
    intro:
      'Ereignisbasierte Trigger (TriggeredAbility) reagieren auf den Ereignis-Bus der ' +
      'Engine und werden nach APNAP auf den Stack gelegt.',
    items: [
      ['full', 'Ereignis-Trigger', 'ENTERS_BATTLEFIELD, DIES, DRAW, DAMAGE, ATTACKS, SPELL_CAST, LIFE_GAINED u. a.'],
      ['full', '„Du darfst"-Trigger', 'Optionale Trigger (RULE 603.5) mit decline.'],
      ['full', 'Ersetzungs-Effekte', 'ReplacementEffect (z. B. Schadensverhütung) wird bei DAMAGE angewandt.'],
      ['partial', 'Reihenfolge innerhalb eines Beherrschers', 'APNAP nach Beherrscher; keine Intra-Spieler-Wahl (RULE 603.3b).'],
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
      ['full', 'search / shuffle', 'Bibliothek durchsuchen (Tutor) mit Kriterien/Ziel/Zahl.'],
      ['full', 'cascade / discover', 'Kaskade & Discover mit Spieler-Entscheidung.'],
      ['full', 'anthem / pt_set / grant_keyword / type_change / cost_reduction', 'Die statischen Effekte oben.'],
    ],
  },
  {
    title: 'Weitere Mechaniken',
    rule: '',
    items: [
      ['full', 'Mana-Modell', 'Generisch, farbig, farblos, Hybrid, Mono-Hybrid, Phyrexianisch, {X}; Dual-Land-Farbwahl.'],
      ['full', 'Zielwahl (Targeting)', 'Legale Ziele pro Anforderung, gesperrte Sprüche ohne Ziel (RULE 601.2c).'],
      ['full', 'Tokens & Marken', '+1/+1 / −1/−1 (annihilieren als SBA), Loyalitäts-/Ladungsmarken.'],
      ['full', 'Commander-Regeln', '21 Commander-Schaden, Rückkehr in die Kommandozone.'],
      ['partial', 'Anhänge (Auren/Ausrüstung)', 'Nur gruppierte Darstellung am Wirt; die eigentliche Equip-/Verzauberungs-Auflösung fehlt noch.'],
      ['full', 'Auswertung', 'Statistiken nach dem Spiel (gezogen/gespielt, Mana-Kurve, Schaden).'],
    ],
  },
  {
    title: 'Noch nicht implementiert',
    rule: '',
    items: [
      ['planned', 'Oracle-Text-Parser (Frontend)', 'Fähigkeits-Specs sind derzeit handgeschrieben; NLP-Erkennung (docs/09) folgt.'],
      ['planned', 'Interaktiver Blocker-/Multiplayer-Modus', 'Braucht die Zwei-Spieler-Prioritäts-Schleife.'],
      ['planned', 'Ability-Kinds: replacement, keyword (Bindung)', 'Vom Binder noch nicht realisiert.'],
      ['planned', 'Reihenfolge-Wahlen', 'Trigger-/Ersetzungs-Reihenfolge durch den betroffenen Spieler (RULE 616.1 / 603.3b).'],
      ['planned', 'Commander-Steuer', 'RULE 903.8 (+{2} je vorheriges Wirken) noch nicht modelliert.'],
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
