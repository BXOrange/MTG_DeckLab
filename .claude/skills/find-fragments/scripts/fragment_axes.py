"""Axis classification and ticket assignment for open fragments (`find_fragments.py --axes`).

Every open sentence is assigned to exactly one work package, so the packages
together cover the whole open pool with no unassigned remainder:

  BIND   claims together with its predecessor sentence      -> P1-E
  HEAD   trigger/cost head missing, body claims              -> P1-D
  MOD    deleting exactly one modifier makes it claim        -> P1-A/B/C/F
  REF    replacing a back-reference by a target makes it claim -> P1-E
  CORE   no single-axis repair; filed under its operation family -> P2-<family>,
         or P3 (singleton review) when no family pattern matches

For a MOD sentence a substitution probe then separates the two possible causes:
the modifier is replaced by a filler the parser is known to read. If that
claims, the row offers the slot and only the vocabulary is missing ("vokabel");
if not, the row does not offer the slot at all ("slot").

Deletion and substitution are diagnostics: an upper bound on what a package can
unlock, never proof. READ-ONLY, like the rest of this skill.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from mtg_analyzer.parser.composition_diagnostics import (
    _ACTIVATED_SPLIT,
    _MODIFIER_AXES,
    _TRIGGER_SPLIT,
    CompositionProbe,
)

TICKET_CONDITIONS = "P1-A Bedingungen"
TICKET_AMOUNTS = "P1-B Mengen"
TICKET_FILTERS = "P1-C Objektfilter"
TICKET_HEADS = "P1-D Trigger-/Kostenköpfe"
TICKET_REFERENTS = "P1-E Rückbezug"
TICKET_SMALL_MODIFIERS = "P1-F Kleinmodifikatoren"
TICKET_SINGLETON_REVIEW = "P3 Einzelprüfung (kein Familienmuster)"
TICKET_REMEASURE = "P0 Re-measure (nur Wrapper)"
#: CORE sentences without a family on cards outside the Commander-legal pool: almost all
#: Un-set, ante, playtest and variant-format text, which needs a support-policy decision first.
TICKET_SPECIAL_POOL = "P2 Nicht Commander-legale Sonderkarten (Support-Entscheidung)"
#: Parked by owner decision (DEFERRED.md), keyed by Scryfall metadata of the card's printing.
#: Parked packages stay in the assignment so the pool remains fully accounted for.
PARKED_UN_SETS = "GEPARKT Un-Sets (DEFERRED.md)"
PARKED_HORDE = "GEPARKT Horde-Challenge-Deck (DEFERRED.md)"
UN_SET_TYPE = "funny"          # Scryfall `set_type` of Un-sets, holiday and playtest joke cards
HORDE_SET_CODE = "tbth"        # "Battle the Horde" challenge deck


def parked_package(raw_card: dict) -> str | None:
    """The parked package a raw Scryfall record belongs to, if any."""
    if raw_card.get("set") == HORDE_SET_CODE:
        return PARKED_HORDE
    if raw_card.get("set_type") == UN_SET_TYPE:
        return PARKED_UN_SETS
    return None
FAMILY_TICKET_PREFIX = "P2 "

#: Modifier deletions beyond `composition_diagnostics._MODIFIER_AXES`.
_EXTRA_MODIFIER_AXES = {
    "x amount": r"\bx\b",
    "'you may' anywhere": r"\byou may ",
    "'of their/your choice'": r" of (their|your) choice",
    "'at random'": r" at random",
    "'under <who> control'": r" under (your|its owner's|their owner's|that player's) control",
    "'attacking'": r" tapped and attacking| attacking",
    "'with <quality>'": r" with [^.,]+",
    "'from <zone>'": r" from [^.,]+",
    "'named/shares/same name'": r" (named|that shares?|with the same name as) [^.,]+",
    "'in any/random order'": r" in (any|a random) order",
    "'rather than/as though'": r" (rather than|as though) [^.,]+",
    "'once each turn/activate only'":
        r"\b(this ability triggers only once each turn|activate only [^.]+|only once each turn)\.?",
    "qualifier adjective":
        r"\b(non[a-z]+|legendary|tapped|untapped|attacking|blocking|historic|modified|token|nontoken) ",
}
MODIFIER_AXES = {**_MODIFIER_AXES, **_EXTRA_MODIFIER_AXES}

#: Which Phase-1 package owns each modifier axis. Axes not listed are small modifiers.
_AXIS_TICKETS = {
    "leading 'if <cond>,'": TICKET_CONDITIONS,
    "trailing 'if <cond>'": TICKET_CONDITIONS,
    "trailing 'unless <cond>'": TICKET_CONDITIONS,
    "for each <count>": TICKET_AMOUNTS,
    "where X is / equal to <amount>": TICKET_AMOUNTS,
    "x amount": TICKET_AMOUNTS,
    "'with <quality>'": TICKET_FILTERS,
    "'from <zone>'": TICKET_FILTERS,
    "'named/shares/same name'": TICKET_FILTERS,
    "'another / other'": TICKET_FILTERS,
    "qualifier adjective": TICKET_FILTERS,
    "'tapped'": TICKET_FILTERS,
    "'attacking'": TICKET_FILTERS,
    "'you don't control / an opponent controls'": TICKET_FILTERS,
    "scope word (each opponent / target player)": TICKET_FILTERS,
}

#: Known-good fillers for the substitution probe (axis -> replacement text).
_AXIS_FILLERS = {
    "leading 'if <cond>,'": "if you control a creature, ",
    "trailing 'if <cond>'": " if you control a creature",
    "trailing 'unless <cond>'": " unless you pay {1}",
    "for each <count>": " for each creature you control",
    "'with <quality>'": " with flying",
    "'from <zone>'": " from your graveyard",
}
_WHERE_X_FILLER = ", where x is the number of creatures you control"
_EQUAL_TO_FILLER = " equal to the number of creatures you control"

#: Back-references and the stand-in antecedent that replaces each in the REF probe.
_REFERENT_STANDINS = [
    (r"\bthat creature\b", "target creature"), (r"\bthose creatures\b", "all creatures"),
    (r"\bthat card\b", "target card"), (r"\bthose cards\b", "target cards"),
    (r"\bthat player\b", "target player"), (r"\bthat permanent\b", "target permanent"),
    (r"\bthat spell\b", "target spell"), (r"\bthem\b", "target creature"), (r"\bit\b", "target creature"),
    (r"\bthat many\b", "2"), (r"\bthat much\b", "2"), (r"\bthe exiled card\b", "target card"),
    (r"\bthe token\b", "target creature"), (r"\bthat land\b", "target land"),
    (r"\bthat opponent\b", "target opponent"), (r"\btheir\b", "your"), (r"\bthey\b", "you"),
]

#: Table rows ("1—9 | "), loyalty costs ("+1: "), ability words ("descend 4 — "),
#: bullets and saga chapters in front of a body: not part of the operation.
_BODY_PREFIX_RE = re.compile(
    r"^(?:\d+(?:[—-]\d+)?\+? \| |[+−-]?\d+: |[a-z' ]{2,30}(?: \d+)? — |• |[ivx]+(?:, [ivx]+)* — )+")

#: Operation families for CORE sentences, first match wins (order = precedence:
#: linkage kinds first, then zones, then plain operations).
FAMILY_PATTERNS = [
    ("Ersatzeffekte (would/instead)", r"\bwould\b|\binstead\b"),
    ("Zauber-Erlaubnis und Alternativkosten",
     r"\bmay (cast|play|activate)\b|rather than|as though|without paying"),
    ("Kostenmodifikatoren und Zusatzkosten",
     r"\bcosts? (\{|x|up to)|\bcost an additional\b|\bcost is reduced\b|\bless to (cast|activate)|\bmore to (cast|activate)|additional cost"),
    ("Einschränkungen (can't/must/only)",
     r"\bcan't\b|\bmust\b|\bcan (attack|block)\b|\bonly (during|if|as|once|any)\b|\bactivate only\b"
     r"|\bno more (than|times)\b|\bonly .*\bmay activate\b|\bcan cast only\b"),
    ("Statische Dauereffekte (as long as/has/gets)",
     r"\bas long as\b|^(~|enchanted|equipped|each|all|other|creatures?|[a-z]+s you control)\b.*"
     r"\b(has|have|gets?|is|are|lose|loses)\b"
     r"|\benters? (un)?tapped\b|\bplay with (your|their) hands? revealed\b|^~ is (the|every|all)\b"
     r"|\b(are|is) [^.]*\bin addition to\b|\bcounters remain\b|\b(don't|doesn't) (cause|trigger)\b"
     r"|\bmaximum hand size\b|\bare (white|blue|black|red|green|colorless)\b|\bare the second chosen type\b|\baren't put into\b|\ban additional time\b"),
    ("As-enters und Enters-with", r"^as ~ |^as this |\bas you cast\b|\benters with\b|\benters tapped\b|\benters? as\b"),
    ("Wahl (choose/vote/random/benennen)",
     r"\bchoose\b|\bvotes?\b|at random|secretly|\bname a\b|\bof (your|their) choice\b|\bguess|\bpiles?\b"
     r"|\bbid(ding)?\b|\bare revealed\b|\btied for\b|\bnote a\b"),
    ("Stapel: Neutralisieren und Ziele ändern", r"\bcounter (target|that|all|up to|it\b)|\bchange (the|a|any) targets?\b|\bcounter the spell\b"),
    ("Textänderung", r"\bchange the text\b|\breplacing all instances\b"),
    ("Spielerbezogene Aktionen",
     r"^(each|target|that|any|an|the) (player|opponent)|\beach foe\b|\ban opponent chooses\b|\beach (player|opponent)\b|\bdefending player\b"
     r"|\battacking player\b|\bits (controller|owner) (may|adds?|puts?|creates?|draws?|loses?|gains?|chooses?)\b"),
    ("Bibliothek (ansehen/aufdecken/suchen/millen)",
     r"\blook at\b|\breveals?\b|\bmills?\b|top (card|\w+ cards)|\bsearch\b|\bbottom of\b|\bshuffle"
     r"|\bfrom among them\b|\bthe rest\b"),
    ("Exil und Bezug auf exilierte Karten", r"\bexiled?\b"),
    ("Friedhof (zurückbringen/reanimieren)", r"\bgraveyard\b"),
    ("Kopie", r"\bcop(y|ies)\b"),
    ("Spielsteine", r"\bcreates?\b|\btokens?\b"),
    ("Marken", r"\bcounters? (on|from|among)\b|\bproliferate|\b(put|remove|move|distribute)\b.*\bcounter"
               r"|\bcounter of that kind\b|\bgets? (a|an|\w+) \w+ counters?\b"),
    ("Schaden", r"\bdamage\b"),
    ("Leben", r"\blife\b"),
    ("Mana und Energie", r"\badd\b.*(\{|mana)|\bmana\b|\{(e|tk|a)\}"),
    ("Optionale Zahlung (you may pay/if you do)", r"\bpays?\b"),
    ("Anlegen (Aura/Ausrüstung)", r"\battach|\bequip|\benchant"),
    ("Kontrolle und Tausch", r"\bgain control|\bexchange\b|\bunder (your|its owner's|their) control\b"),
    ("Kampf", r"\battack|\bblock|\bcombat\b|\bfight"),
    ("Zonenwechsel (return/put)",
     r"\breturn\b|\bputs? .*\b(onto the battlefield|into (your|their|its owner's) hand|on top|on the bottom)\b"
     r"|\binto (its|their) owners?'s? (library|graveyards?)\b|\binto their owners' graveyards\b|\bunattach\b"),
    ("Charakteristik (ist/wird/Basis-P/T)",
     r"\b(it|he|she)'s (a|an|still)\b|\bthey're\b|\bisn't (a|an|snow)\b|\b(is|are) (a|an|no longer)\b|in addition to its other"
     r"|\bbase power\b|\b(double|triple)\b.*\b(power|toughness)\b|\b(power|toughness) (is|are|becomes?)\b"),
    ("P/T und Keyword-Vergabe", r"gets? [+-]|\bgains?\b|\bhas\b|\bhave\b|\bbecomes?\b|\bloses?\b"),
    ("Ziehen/Abwerfen", r"\bdraws?\b|\bdiscards?\b"),
    ("Zug und Phase", r"\bextra turn|\bskip|\buntap step|\badditional (combat|upkeep)|\bend the turn"
                      r"|\bturn order\b|\bcontrols? the second player\b"),
    ("Phasing", r"\bphases? (in|out)\b|\bphased-out\b"),
    ("Tabellen- und Variantenzeilen", r"^\d+ — |^\d+/\d+\b|^(otherwise, )?x is \d|— \d+/\d+\.?$|^to solve —"),
    ("Zähl- und Prozessanweisungen",
     r"\bcount the number\b|\brepeat the following\b|\bdo the same\b|\bdo all of the above\b|^(otherwise, )?x is the\b"
     r"|\bignore this effect\b|\bthis effect (continues|doesn't)\b|\bfor each [^.]* this way\b|\bthe result\b"),
    ("Face-down/Transform", r"face[- ](down|up)|transform|\bflip\b|\bturn(ed)? ~"),
    ("Würfel und Münze", r"\broll|\bflip a coin|\bcoin"),
    ("Keyword-Aktionen (investigate/discover/goad …)",
     r"\b(investigate|discover|goad|scry|surveil|explore|populate|amass|connive|manifest|cloak|bolster"
     r"|adapt|support|venture|incubate|forage|learn|tempts you|explores?|connives?|manifests?|amasses"
     r"|earthbend|empower|time travel|blight|recruit|craft|commander ninjutsu)\b"),
    ("Opfern/Zerstören", r"\bsacrifices?\b|\bdestroy"),
    ("Tappen/Enttappen", r"\buntaps?\b|\btaps?\b"),
    ("Spielausgang und Sonderregeln", r"\b(win|lose) the game\b|\blegend rule\b|\bround (up|down)\b|\brepeat this\b"
                                      r"|\bthe same is true\b|\bdevotion\b|\bcolor identity\b|\bspeed\b|\breroll\b"),
    ("Normalisierungs-Artefakte (Kartenname/Satzgrenze)",
     r"^~(?:$|[ ,][a-z ,!]*[.!]?$)|^[a-z ,']{1,30}!$|^target [a-z]+ card\.?$|^(?:[a-z]\.){2,}$"),
    ("Bedingte Anweisungen (if/otherwise/when)", r"^(if|otherwise|when|whenever|at the beginning)\b"),
]
_FAMILY_RES = [(name, re.compile(pattern)) for name, pattern in FAMILY_PATTERNS]


def split_body(row: dict) -> tuple[str, str]:
    """(body, probe prefix) of one fragment row: the effect text behind a trigger or cost head."""
    sentence = row["clause"].lower().strip()
    if row.get("kind"):
        match = _TRIGGER_SPLIT.match(sentence) or _ACTIVATED_SPLIT.match(sentence)
        if match is not None:
            return match.group("body"), "when ~ enters, " if row["kind"] == "trigger" else "{t}: "
    return sentence, ""


def family_of(body: str) -> str | None:
    # The stripped text first; the raw body second, for rows keyed on the prefix itself ("to solve — ").
    for text in (_BODY_PREFIX_RE.sub("", body), body):
        for name, pattern in _FAMILY_RES:
            if pattern.search(text):
                return name
    return None


def _substitute(axis: str, pattern: str, body: str) -> str | None:
    filler = _AXIS_FILLERS.get(axis)
    if axis == "where X is / equal to <amount>":
        filler = _WHERE_X_FILLER if "where x is" in body else _EQUAL_TO_FILLER
    if filler is None:
        return None
    return re.sub(pattern, filler, body, count=1)


def classify(row: dict, probe: CompositionProbe, legal_names: set[str] | None = None,
             parked: dict[str, str] | None = None) -> dict:
    """Axis class, blocking axis, family and owning ticket of one fragment row."""
    out = {"card": row["card"], "clause": row["clause"], "axis_class": None, "axis": None,
           "slot_gap": None, "family": None, "ticket": None, "also": []}
    if row.get("claims_with_previous"):
        out.update(axis_class="BIND", ticket=TICKET_REFERENTS)
        return out
    head_missing = bool(row.get("kind")) and not row.get("head_ok")
    if head_missing and row.get("body_ok"):
        out.update(axis_class="HEAD", ticket=TICKET_HEADS)
        return out
    body, prefix = split_body(row)

    def claims(text: str) -> bool:
        text = text.strip(" ,.") + "."
        # A bare body is also tried as a trigger body: many effect sentences only read in an ability.
        return probe.claims(prefix + text) or (not prefix and probe.claims("when ~ enters, " + text))

    for axis, pattern in MODIFIER_AXES.items():
        if not re.search(pattern, body):
            continue
        shorter = re.sub(pattern, "", body, count=1).strip(" ,.")
        if shorter and shorter != body.strip(" ,.") and claims(shorter):
            substituted = _substitute(axis, pattern, body)
            gap = None if substituted is None else ("vokabel" if claims(substituted) else "slot")
            out.update(axis_class="MOD", axis=axis, slot_gap=gap,
                       ticket=_AXIS_TICKETS.get(axis, TICKET_SMALL_MODIFIERS))
            break
    else:
        for pattern, standin in _REFERENT_STANDINS:
            if re.search(pattern, body) and claims(re.sub(pattern, standin, body)):
                out.update(axis_class="REF", axis=standin, ticket=TICKET_REFERENTS)
                break
        else:
            family = family_of(body)
            if family:
                ticket = FAMILY_TICKET_PREFIX + family
            elif legal_names is not None and row["card"] not in legal_names:
                ticket = (parked or {}).get(row["card"], TICKET_SPECIAL_POOL)
            else:
                ticket = TICKET_SINGLETON_REVIEW
            out.update(axis_class="CORE", family=family, ticket=ticket)
    if head_missing:
        out["also"].append(TICKET_HEADS)
    return out


def assign(rows: list[dict], probe: CompositionProbe, legal_names: set[str] | None = None,
           parked: dict[str, str] | None = None) -> list[dict]:
    """`legal_names` (Commander-legal card names) and `parked` (card name -> parked package)
    are given on a whole-cache scan only; both apply to sentences without a family."""
    return [classify(row, probe, legal_names, parked) for row in rows]


def check_complete(assignments: list[dict], remeasure: list[str], open_cards: int | None) -> list[str]:
    """Problems that break the completeness rule; an empty list means every open card is covered."""
    problems = [f"Satz ohne Ticket: {a['card']}: {a['clause'][:80]}" for a in assignments if not a["ticket"]]
    assigned = {a["card"] for a in assignments} | set(remeasure)
    if open_cards is not None and len(assigned) != open_cards:
        problems.append(f"zugeordnete Karten {len(assigned)} != offene Karten {open_cards}")
    return problems


def write_axes(assignments: list[dict], remeasure: list[str], totals: dict, out_dir: Path, stem: str,
               scope: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / f"{stem}-zuordnung.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        for a in assignments:
            fh.write(json.dumps(a, ensure_ascii=False) + "\n")
        for name in remeasure:
            fh.write(json.dumps({"card": name, "clause": None, "axis_class": "WRAPPER",
                                 "ticket": TICKET_REMEASURE, "also": []}, ensure_ascii=False) + "\n")

    card_tickets: dict[str, set[str]] = defaultdict(set)
    sentences: Counter = Counter()
    touched: dict[str, set[str]] = defaultdict(set)
    for a in assignments:
        for ticket in [a["ticket"], *a["also"]]:
            card_tickets[a["card"]].add(ticket)
            touched[ticket].add(a["card"])
        sentences[a["ticket"]] += 1
    for name in remeasure:
        card_tickets[name].add(TICKET_REMEASURE)
        touched[TICKET_REMEASURE].add(name)
    only = Counter(next(iter(t)) for t in card_tickets.values() if len(t) == 1)
    pairs = Counter(tuple(sorted(t)) for t in card_tickets.values() if len(t) == 2)

    lines = [f"# Achsen und Ticket-Zuordnung — {stem} ({scope})", "",
             f"Pool {totals.get('pool')} | abgedeckt {totals.get('covered')} | permanent ausgeschlossen "
             f"{totals.get('never_supported')} | offen {totals.get('open')}. Zugeordnet: "
             f"{len(card_tickets)} Karten, {len(assignments)} Sätze.", "",
             "`nur` = Karten, deren sämtliche offenen Sätze in diesem Paket liegen (Obergrenze der "
             "Freischaltung). `berührt` zählt auch Karten, die weitere Pakete brauchen.", "",
             "## Pakete", "", "| Paket | Sätze | berührt | nur |", "| --- | ---: | ---: | ---: |"]
    for ticket in sorted(touched, key=lambda t: (-only[t], t)):
        lines.append(f"| {ticket} | {sentences[ticket]} | {len(touched[ticket])} | {only[ticket]} |")

    by_class = Counter(a["axis_class"] for a in assignments)
    lines += ["", "## Klassen (Sätze)", ""] + [f"- {n} — {cls}" for cls, n in by_class.most_common()]

    mod = defaultdict(Counter)
    for a in assignments:
        if a["axis_class"] == "MOD":
            mod[a["axis"]][a["slot_gap"] or "ungeprüft"] += 1
    lines += ["", "## MOD-Achsen: Vokabel fehlt oder Slot fehlt", "",
              "| Achse | Sätze | Vokabel | Slot | ungeprüft |", "| --- | ---: | ---: | ---: | ---: |"]
    for axis, gaps in sorted(mod.items(), key=lambda kv: -sum(kv[1].values())):
        lines.append(f"| {axis} | {sum(gaps.values())} | {gaps['vokabel']} | {gaps['slot']} | {gaps['ungeprüft']} |")

    lines += ["", "## Häufigste Paket-Paare (Karten, die genau zwei Pakete brauchen)", ""]
    lines += [f"- {n} — {a} + {b}" for (a, b), n in pairs.most_common(25)]

    review = [a for a in assignments if a["ticket"] == TICKET_SINGLETON_REVIEW]
    lines += ["", f"## Ohne Familienmuster ({len(review)} Sätze, Beispiele)", ""]
    lines += [f"- {a['card']}: {a['clause'][:140]}" for a in review[:40]]
    md = out_dir / f"{stem}-achsen.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jsonl, md
