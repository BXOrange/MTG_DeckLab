// "Status" tab: a compact overview of what's implemented, structured two
// levels deep — top-level by software feature/use-case (docs/requirements/
// 02_MVP_USECASES_REVISED.md's UC1–UC5), then within the engine-heavy
// Goldfisch-Modus feature by the *official Comprehensive Rules chapter*
// (1 Game Concepts, 3 Card Types, 4 Zones, 5 Turn Structure, 6 Spells/
// Abilities/Effects, 7 Additional Rules, 9 Casual Variants) rather than an
// ad hoc topic grouping — mirrors docs/Reference/rules_wiki/'s own rule#
// index. Static content (no server call); kept in sync by hand with the
// backend — see CLAUDE.md "Implementation state". Deliberately heading-
// level only (no per-item prose) — see docs/implementation-state/
// Done_Backend.md / backend/ToDo_Backend.md for the full narrative.

const LEGEND = [
  ['full', '✅', 'Vollständig'],
  ['partial', '◐', 'Teilweise'],
  ['planned', '✖', 'Geplant'],
];

// section = { title?, rule?, items: [ [status, label] ] } — title/rule
// omitted when a chapter/group has only one, self-explanatory section.
// chapter = { title, rule, sections: [section, …] } — one CR chapter.
// group = { title, uc?, sections: [section, …] } XOR { title, uc?, chapters: [chapter, …] }
const GROUPS = [
  {
    title: 'Deck-Import & -Verwaltung',
    uc: 'UC1',
    sections: [
      {
        items: [
          ['full', 'Deckliste laden (Archidekt-Import, manuelle Liste)'],
          ['full', 'Commander-Validierung (100 Karten, Singleton, Farbidentität, Bannliste)'],
          ['full', 'Cube-Modus (Validierung übersprungen)'],
          ['full', 'Karten-Cache (Scryfall, cache-primär/lazy)'],
          ['full', 'Gespeicherte Decks (Filter, Autor, Sleeve)'],
          ['full', 'Player-Assets (Token-Art, Card-Back-Sleeves)'],
          ['full', 'Moxfield-Import (Export-Text einfügen, Commander/Sideboard auto-erkannt)'],
        ],
      },
    ],
  },
  {
    title: 'Deck-Analyse',
    uc: 'UC2',
    sections: [
      {
        items: [
          ['full', 'Statische Analyse (Mana-Kurve, Kartentypen, Pips vs. Quellen, Hand-Odds)'],
          ['full', 'Bracket-Analyse (Commander-Brackets-Heuristik)'],
          ['full', 'Auswertung (Post-Game-Statistik)'],
          ['planned', 'Dynamische Analyse (LLM: Archetyp/Synergien/Kohärenz)'],
        ],
      },
    ],
  },
  {
    title: 'Goldfisch-Modus',
    uc: 'UC3',
    chapters: [
      {
        title: 'Kapitel 1 — Spielkonzepte',
        rule: 'RULE 100–122',
        sections: [
          {
            items: [
              ['full', 'Mana-Modell (106)'],
              ['full', 'Zielwahl / Targeting (115)'],
              ['partial', 'Echte Mehrfachziele (115.1a, N≥2) — nur bei wenigen Effekten'],
              ['full', 'Priorität & Stack (117)'],
              ['partial', 'Interaktive Priorität — Basis (117)'],
              ['full', 'Mulligan — London (103)'],
              ['full', 'Tokens & Marken (111/121)'],
              ['full', 'Embleme (114)'],
            ],
          },
        ],
      },
      {
        title: 'Kapitel 3 — Kartentypen',
        rule: 'RULE 300–316',
        sections: [
          {
            items: [
              ['full', 'Anhänge: Auren / Ausrüstung / Reconfigure (301/303)'],
              ['planned', 'Battles / Dungeons (309/310)'],
            ],
          },
        ],
      },
      {
        title: 'Kapitel 4 — Zonen',
        rule: 'RULE 400–411',
        sections: [
          {
            items: [['full', 'Zonenwechsel-Neuidentität, „Blink" (400.7)']],
          },
        ],
      },
      {
        title: 'Kapitel 5 — Zugstruktur',
        rule: 'RULE 500–514',
        sections: [
          {
            items: [['full', 'Phasen & Schritte']],
          },
        ],
      },
      {
        title: 'Kapitel 6 — Sprüche, Fähigkeiten & Effekte',
        rule: 'RULE 601–616',
        sections: [
          {
            title: 'Zaubersprüche wirken',
            rule: '601',
            items: [
              ['full', 'Zusatzkosten beim Wirken (601.2b/601.2h)'],
              ['full', 'Modale Zaubersprüche (601.2b/700.2)'],
              ['partial', '„Add one mana of any color" — Farbwahl-UI'],
            ],
          },
          {
            title: 'Aktivierte Fähigkeiten',
            rule: '602',
            items: [
              ['full', '{T} / {Q} — Tappen / Enttappen'],
              ['full', 'Opfern'],
              ['full', 'Leben zahlen / Karten abwerfen'],
              ['full', 'Marken entfernen'],
              ['full', 'Als Button im Goldfisch'],
              ['full', 'Fetch-Länder'],
            ],
          },
          {
            title: 'Ausgelöste Fähigkeiten',
            rule: '603',
            items: [
              ['full', 'Ereignis-Trigger'],
              ['full', 'Subjekt-Scoping (self/another/…)'],
              ['full', 'Gruppen-Subjekt bei Kampfschaden („eine Kreatur, die du kontrollierst")'],
              ['full', 'Verliehene Upkeep-/Phasen-Trigger (in Zitat-Fähigkeiten)'],
              ['full', '„Opfere ~, es sei denn, du bezahlst <Kosten>" (interaktiv)'],
              ['full', 'Zielwahl für ausgelöste Fähigkeiten'],
              ['full', 'Modale ausgelöste Fähigkeiten'],
              ['full', '„Du darfst"-Trigger'],
              ['full', 'Reihenfolge-Wahl (Trigger)'],
            ],
          },
          {
            title: 'Loyalitäts-Fähigkeiten',
            rule: '606',
            items: [['full', '[+N] / [−N] / [0]-Kosten (606.5c)']],
          },
          {
            title: 'Auflösen & Einmal-Effekte',
            rule: '608–610',
            items: [
              ['full', 'damage / destroy / regenerate / counter'],
              ['full', 'draw / discard / gain_life'],
              ['full', 'mill / exile / tap'],
              ['full', 'add_counters (+1/+1 / −1/−1)'],
              ['full', 'pump (+N/+N bis Zugende)'],
              ['full', 'scry / surveil'],
              ['full', 'create_token'],
              ['full', 'search / shuffle (Tutor)'],
              ['full', 'return_to_hand / -from_graveyard / exile / lose_life'],
              ['full', 'cascade / discover'],
              ['full', 'copy_permanent / become_copy (706/707)'],
              ['full', 'anthem / pt_set / grant_keyword / type_change / cost_reduction'],
              ['full', 'Skalierung mit gewirktem {X}'],
              ['full', '„Sieh dir oberste N an, nimm eine passende"'],
              ['full', '„Exiliere, du darfst bis Zugende spielen"'],
              ['full', 'Phasing'],
              ['full', 'grant_mana_ability / grant_triggered_ability'],
              ['full', '„Bringe ~ auf die Hand zurück" (Rancor/Flickering Ward)'],
            ],
          },
          {
            title: 'Kontinuierliche Effekte — Layer-System',
            rule: '611–613',
            items: [
              ['full', 'Layer 1 — Kopie-Effekte (kontinuierlich)'],
              ['full', 'Layer 2 — Kontrollwechsel'],
              ['full', 'Layer 3 — Textänderung (eingegrenzt) & Abhängigkeits-Ordnung'],
              ['full', 'Layer 4 — Typänderung'],
              ['full', 'Layer 4 — gewählter Typ auch außerhalb des Schlachtfelds (613.4a)'],
              ['full', 'Layer 5 — Farbwechsel'],
              ['full', 'Layer 6 — Fähigkeiten verleihen'],
              ['full', 'Layer 6 — dauerhaft verliehener Schutz (702.16)'],
              ['full', 'Layer 7 — Stärke/Widerstandskraft (a–e)'],
              ['full', 'Zeitstempel-Ordnung'],
              ['full', 'Kostenanpassung (kein Layer)'],
            ],
          },
          {
            title: 'Ersetzungs-/Verhinderungs-Effekte',
            rule: '614–616',
            items: [
              ['full', 'Ersetzungs-Effekte (prevent_damage/double_damage/double_counters/double_tokens)'],
              ['full', 'Reihenfolge-Wahl bei 2+ gleichzeitigen Ersetzungs-Effekten'],
              ['full', 'Enters tapped (fest & bedingt)'],
              ['full', 'Tritt mit N Marken ins Spiel'],
              ['planned', 'Kicked „instead"-Override-Konditional'],
            ],
          },
        ],
      },
      {
        title: 'Kapitel 7 — Weitere Regeln',
        rule: 'RULE 700–731',
        sections: [
          {
            title: 'Schlüsselwörter (Aktionen & Fähigkeiten)',
            rule: '701/702',
            items: [
              ['full', 'Flying / Reach'],
              ['full', 'First Strike / Double Strike'],
              ['full', 'Deathtouch'],
              ['full', 'Trample'],
              ['full', 'Vigilance'],
              ['full', 'Lifelink'],
              ['full', 'Menace'],
              ['full', 'Defender / Haste'],
              ['full', 'Indestructible'],
              ['full', 'Landwalk'],
              ['full', 'Protection from …'],
              ['full', 'Hexproof'],
              ['full', 'Annihilator / Afflict / Bushido / Rampage'],
              ['full', 'Dethrone (702.107)'],
              ['full', 'Kicker / Multikicker (702.33)'],
              ['full', 'Buyback (702.27)'],
              ['full', 'Flashback / Escape (702.34/702.138)'],
              ['full', 'Channel / Cycling (702.29/702.28)'],
              ['full', 'Bedingte Sofort-Geschwindigkeit (702.8b/606.3)'],
              ['full', 'Ward (702.21)'],
              ['planned', 'Fight-Effekt, Strive-Kostengrammatik'],
              ['planned', 'Verdecktes Morph/Megamorph-Spielen'],
            ],
          },
          {
            title: 'Zustandsbasierte Aktionen',
            rule: '704',
            items: [
              ['full', 'Leben ≤ 0, leere Bibliothek, 0 Widerstandskraft, tödlicher Schaden, Legenden-Regel'],
            ],
          },
          {
            title: 'Sonderkartentypen',
            rule: '708–722',
            items: [
              ['full', 'DFC-Transform (712.8) & Tag/Nacht (731)'],
              ['full', 'Sagas (714)'],
              ['full', 'Class (716) & Leveler (711)'],
              ['full', 'MDFC / Adventure / Split-Fuse / Prepared (709/710/712.10/715/722)'],
            ],
          },
          {
            title: 'Monarch / Initiative / Rad-Marken',
            rule: '725/726/728',
            items: [['full', 'Thron, Initiative, Rad-Marken']],
          },
        ],
      },
      {
        title: 'Kapitel 9 — Commander (Format-Regeln)',
        rule: 'RULE 903',
        sections: [
          {
            items: [['full', '21 Commander-Schaden, Command-Zone-Rückkehr, Steuer +{2}']],
          },
        ],
      },
      {
        title: 'Engine-Verhalten (nicht regelspezifisch)',
        rule: '',
        sections: [
          {
            items: [
              ['full', 'Rückgängig / Neustart / Rewind'],
              ['partial', 'Passiver Gegner ("Goldfisch")'],
              ['partial', 'Gesamtabdeckung Oracle-Parser (23,5 % von ~34 000)'],
            ],
          },
        ],
      },
    ],
  },
  {
    title: 'Replay / Puzzle-Modus',
    uc: 'UC3-Schwester',
    sections: [
      {
        items: [
          ['full', 'Karten/Token in jede Zone'],
          ['full', 'Objekt-Zustand (Tap, DFC, Marken)'],
          ['full', 'Spieler-Werte (Leben, Gift, Commander-Schaden)'],
          ['full', 'Zug/Phase setzen'],
          ['full', 'Speichern/Laden (JSON)'],
          ['partial', 'Spielerzahl (max. 2)'],
        ],
      },
    ],
  },
  {
    title: 'Multiplayer-Modus',
    uc: 'UC4',
    sections: [
      {
        items: [
          ['partial', 'Backend-Route (POST /api/game/multiplayer)'],
          ['planned', 'Interaktive Prioritäts-Schleife (RULE 117)'],
          ['planned', 'WebSocket-Session-Anbindung'],
        ],
      },
    ],
  },
  {
    title: 'Bot-KI',
    uc: 'UC5',
    sections: [
      {
        items: [
          ['partial', 'Greedy-Autoplay (Land, Tap-out, günstigste Zauber, Angriff)'],
          ['planned', 'Gewichtete Bot-Strategie'],
        ],
      },
    ],
  },
];

function statusMeta(status) {
  return LEGEND.find((l) => l[0] === status) || LEGEND[0];
}

function itemHtml([status, label]) {
  const [, icon, name] = statusMeta(status);
  return `
    <li class="impl-item impl-${status}">
      <span class="impl-badge" title="${name}">${icon}</span>
      <span class="impl-text"><strong>${label}</strong></span>
    </li>`;
}

function sectionHtml(section) {
  return `
    <section class="impl-section">
      ${
        section.title
          ? `<div class="impl-section-head">
               <h3>${section.title}</h3>
               ${section.rule ? `<span class="impl-rule">${section.rule}</span>` : ''}
             </div>`
          : ''
      }
      <ul class="impl-list">${section.items.map(itemHtml).join('')}</ul>
    </section>`;
}

function chapterHtml(chapter) {
  return `
    <div class="impl-chapter">
      <div class="impl-chapter-head">
        <h4>${chapter.title}</h4>
        ${chapter.rule ? `<span class="impl-rule">${chapter.rule}</span>` : ''}
      </div>
      <div class="impl-grid">${chapter.sections.map(sectionHtml).join('')}</div>
    </div>`;
}

function groupHtml(group) {
  const inner = group.chapters
    ? group.chapters.map(chapterHtml).join('')
    : `<div class="impl-grid">${group.sections.map(sectionHtml).join('')}</div>`;
  return `
    <div class="impl-group">
      <div class="impl-group-head">
        <h3>${group.title}</h3>
        ${group.uc ? `<span class="impl-uc">${group.uc}</span>` : ''}
      </div>
      ${inner}
    </div>`;
}

export function renderImplementationStatusView(container) {
  const legend = LEGEND.map(
    ([status, icon, name]) =>
      `<span class="impl-legend-item impl-${status}"><span class="impl-badge">${icon}</span> ${name}</span>`
  ).join('');

  container.innerHTML = `
    <div class="impl-status">
      <h2>Implementierungs-Stand</h2>
      <p class="hint">
        Nach Software-Feature (UC1–UC5); der Goldfisch-Motor zusätzlich nach
        offiziellem Regelwerk-Kapitel (Comprehensive Rules). Details in
        <code>docs/implementation-state/Done_Backend.md</code> und
        <code>backend/ToDo_Backend.md</code>.
      </p>
      <div class="impl-legend">${legend}</div>
      ${GROUPS.map(groupHtml).join('')}
    </div>`;
}
