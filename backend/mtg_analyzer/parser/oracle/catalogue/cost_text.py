"""Activation-cost *text* grammar — which words of a cost a recognizer reads.

`game/costs.py`'s `parse_activation_cost` turns a cost string ("{1}, {T},
Sacrifice a creature") into the `ActivationCost` the engine charges; this
module is the regex half of that — every cost-component pattern, and
`scan_cost_text`, which runs them in their precedence order and reports what
each one read **and what nobody read** (``CostScan.leftover``, ENG-49).

The leftover is why this lives on the parser side of the security boundary
(docs/09): a fragment no recognizer reads is never charged, so the ability
would be claimed cheaper than printed. The segmenter refuses such an
activated ability (the card stays `UNMODELED`) and the binder refuses to bind
one — both calling this one grammar, so the shapes the gate claims and the
shapes the engine charges can't drift apart (the `lands.py` idiom).

Pure — **no `game/` imports** (front-end security boundary, docs/09).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .subtype_vocabulary import SUBTYPES

#: Every ``{...}`` token in a cost string.
_BRACE_RE = re.compile(r"\{([^}]+)\}")

#: Number words a cost might spell out ("Discard two cards"); "a"/"an" == 1.
#: The tens words (twenty/thirty/forty/fifty) exist only for a "Pay N {E}"
#: energy cost's own outsized real counts (Aetherflux Conduit's "fifty").
NUMBER_WORDS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}
#: RULE 122 energy: "Pay <word> {E}" (Aethersquall Ancient's "Pay eight
#: {E}", Aetherflux Conduit's "Pay fifty {E}") — a single ``{E}`` pip with a
#: spelled-out count in front, unlike the ordinary repeated-pip form
#: ("Pay {E}{E}{E}{E}", Guide of Souls) `_parse_text`'s brace loop already
#: counts directly. The normalizer turns a spelled-out count into digits
#: ("pay 8 {e}", Aethertorch Renegade), so a digit count is accepted too.
_PAY_ENERGY_WORD_RE = re.compile(
    r"pay\s+(?P<n>\d+|" + "|".join(NUMBER_WORDS) + r")\s+\{e\}", re.IGNORECASE
)

#: ENG-51: a word that narrows a permanent phrase in a cost — a colour, a
#: supertype, "token"/"non<type>", a tapped state ("a **black** creature",
#: "a **basic** land", "a **noncreature** artifact"). The engine reads every
#: one through `continuous.matches_permanent_word`.
_QUALIFIER = (
    r"(?:white|blue|black|red|green|colorless|multicolored|nontoken|token|nonland|"
    r"noncreature|nonartifact|nonenchantment|basic|snow|legendary|untapped|tapped)"
)
#: A main type that may follow a subtype ("a Goblin **creature**").
_TYPE_TAIL = r"(?:creature|artifact|land|permanent|enchantment)"
#: "… with defender" / "… with flying" after a permanent phrase.
_WITH_KEYWORD = r"(?:\s+with\s+(?P<kw>defender|flying))?"
#: "Sacrifice ~ / this creature / it / a creature / another artifact" — and
#: ENG-49's either-type form "an artifact or creature" / "another creature or
#: an enchantment", read as the compound ``<type>_or_<alt>`` sacrifice word
#: the engine's matchers split on. ``alt`` refuses a cost verb so "sacrifice a
#: creature or pay 3 life" can never read "pay" as a type. ENG-51 added the
#: qualified forms ("another black creature", "a Goblin creature", "a creature
#: with defender") and "enchanted creature" (the Aura's host).
_SACRIFICE_RE = re.compile(
    r"sacrifice\s+(?P<whole>this\s+\w+|~|it\b|enchanted\s+creature\b"
    r"|(?P<article>an?|another)\s+(?:(?P<qual>" + _QUALIFIER + r")\s+)?(?P<type>\w+)"
    r"(?:\s+(?P<tail>" + _TYPE_TAIL + r")\b)?" + _WITH_KEYWORD
    + r"(?:\s+or\s+(?:an?\s+|another\s+)?"
    r"(?!pay\b|discard\b|sacrifice\b|tap\b|exile\b|remove\b|return\b)(?P<alt>\w+))?)"
    # "Sacrifice a Prism token" (Diamond Kaleidoscope) — the subtype pays it.
    r"(?:\s+token\b)?",
    re.IGNORECASE,
)
#: ENG-49: "Sacrifice N `<type>s`" / "Sacrifice X `<type>s`" (Keldon Arsonist's
#: "Sacrifice two lands", Copper-Leaf Angel's "Sacrifice X lands") — the
#: count-bearing sibling of `_SACRIFICE_RE`. Only a single type word that ends
#: its cost item is read; anything longer ("2 other creatures", "2 lands and
#: ~") is left over, and so refused rather than guessed.
_SACRIFICE_COUNT_RE = re.compile(
    r"sacrifice\s+(?P<n>\d+|x|" + "|".join(w for w in NUMBER_WORDS if w not in ("a", "an"))
    + r")\s+(?:(?P<other>other)\s+)?(?:(?P<qual>" + _QUALIFIER + r")\s+)?(?P<type>[a-z]+)"
    r"(?:\s+tokens)?(?=\s*(?:,|$))",
    re.IGNORECASE,
)
#: "Exile a creature you control: …" (Food Chain, MEC-40) — a genuine RULE
#: 605.1a mana-ability cost component distinct from `_SACRIFICE_RE` above
#: (a different disposition, exile rather than the graveyard).
_EXILE_CREATURE_RE = re.compile(r"exile a creature you control", re.IGNORECASE)
#: PAR-13's compound sacrifice cost — see its check-site below. Real
#: printings vary on whether "artifact"/"land" repeat their own article
#: ("a creature, an artifact, or a land" vs. "a creature, artifact, or
#: land") — both are accepted.
_SACRIFICE_CREATURE_ARTIFACT_OR_LAND_RE = re.compile(
    r"sacrifice a creature,\s*(?:an?\s+)?artifact,?\s*(?:or|and)\s*(?:an?\s+)?land",
    re.IGNORECASE,
)
_PAY_LIFE_RE = re.compile(r"pay\s+(\d+)\s+life", re.IGNORECASE)
#: A count word a cost may print ("two cards", "a card", "X cards").
_COUNT_WORD = r"(?:\d+|x|" + "|".join(NUMBER_WORDS) + r")"
#: "Discard a card / two cards / your hand" — and (ENG-49) a typed card
#: ("discard a creature card", Fauna Shaman) and "at random" (Amok). The
#: type word must be a real card type/supertype/subtype (`_CARD_WORDS`),
#: checked in `scan_cost_text`, so "discard a historic card" stays unread.
_DISCARD_RE = re.compile(
    r"discard\s+(?P<what>your\s+hand|(?P<n>" + _COUNT_WORD + r")\s+(?:(?P<type>[a-z]+)\s+)?cards?)"
    r"(?P<random>\s+at\s+random)?",
    re.IGNORECASE,
)
#: Channel (RULE 702.29)/Cycling (RULE 702.28)'s own cost component:
#: "Discard this card: <effect>." / "{cost}, Discard this card: Draw a
#: card." — discarding the *specific* card bearing the ability, not a
#: player's choice of any card from hand (`_DISCARD_RE`'s generic shape).
#: Checked first so "this card" never falls through to `_DISCARD_RE` and
#: gets misread as "discard a card".
_DISCARD_SELF_RE = re.compile(r"discard this card", re.IGNORECASE)
#: The source a removed counter comes off — "from ~" / "from this creature" /
#: "from it" (ENG-49: read, not dropped; the engine always removes from the
#: ability's own source). "From a creature you control" is a different cost
#: and stays unread.
#: ENG-51: or from a permanent you control ("from a creature you control",
#: Bolrac-Clan Crusher) or spread across several ("from among creatures you
#: control", Hopeful Initiate) — `ActivationCost.remove_counters_from`.
_FROM_SOURCE = (
    r"(?:\s+from\s+(?:~|this\s+\w+|it\b"
    r"|(?:an?|another)\s+(?P<from_one>(?:nonland\s+)?(?:creature|permanent|artifact))\s+you\s+control"
    r"|among\s+(?P<from_among>creatures|permanents)\s+you\s+control))?"
)
#: The counter kind is optional: "remove a counter from ~" (Brambleback Brute)
#: takes a counter of any kind (`costs.REMOVE_COUNTERS_ANY_KIND`, ENG-51).
_REMOVE_COUNTERS_RE = re.compile(
    r"remove\s+(\d+|[a-z]+)\s+(?:([+\-]?\d+/[+\-]?\d+|[a-z]+)\s+)?counters?" + _FROM_SOURCE,
    re.IGNORECASE,
)
#: "Remove any number of <kind> counters from ~" (the Mana Battery cycle/
#: storage lands/Geistflame Reservoir/Rhys the Evermore/The Astonishing
#: Ant-Man) — checked before `_REMOVE_COUNTERS_RE` since "any number of"
#: doesn't fit that regex's single-token count group at all.
_REMOVE_ANY_COUNTERS_RE = re.compile(
    r"remove\s+any number of\s+([+\-]?\d+/[+\-]?\d+|[a-z]+)\s+counters?" + _FROM_SOURCE, re.IGNORECASE
)
#: RULE 702.x-adjacent bulk-tap cost: "Tap two untapped Elves you control"
#: (Birchlore Rangers, Heritage Druid) — taps *other* permanents of a
#: creature type instead of the source itself. The type word is kept as
#: printed (plural, e.g. "Elves") and singularised by `_singularize` below.
#: ENG-51 added the qualified and either-type forms: "Tap an untapped
#: legendary creature you control" (Relic of Legends), "Tap two untapped
#: artifacts and/or creatures you control" (Adaptive Gemguard), "… you
#: control with flying" — the same permanent-phrase encoding as a sacrifice.
_TAP_OTHERS_RE = re.compile(
    r"tap\s+(?P<n>\d+|[a-z]+)\s+untapped\s+(?:(?P<qual>" + _QUALIFIER + r")\s+)?(?P<type>[a-z]+)"
    r"(?:\s+(?:and/)?or\s+(?P<alt>[a-z]+))?\s+you control" + _WITH_KEYWORD,
    re.IGNORECASE,
)
#: "Put a -1/-1 counter on this creature" (Devoted Druid) as an activation
#: *cost* — distinct from `_REMOVE_COUNTERS_RE` (paying by removing existing
#: counters): adding one is always payable.
_ADD_COUNTER_COST_RE = re.compile(
    r"put an?\s+([+\-]?\d+/[+\-]?\d+|[a-z]+)\s+counter on (?:this\s+\w+|~)",
    re.IGNORECASE,
)
#: An alternative-zone cost: "Exile this creature/card from your hand"
#: (Elvish/Simian Spirit Guide) — the ability is activated from hand, not
#: the battlefield; `game/mana_abilities.py`'s `hand_mana_abilities`/
#: `GameEngine.activate_hand_mana_ability` charge it (paid by
#: `RulesEngine.exile`, not through this file's battlefield-oriented
#: `_pay_activation_cost`), and `parse_mana_abilities`'s battlefield path
#: excludes it so such a line is never mistaken for a free/costless
#: battlefield tap ability.
_EXILE_FROM_HAND_RE = re.compile(
    r"exile (?:this \w+|~) from your hand", re.IGNORECASE
)
#: "Exile ~" / "Exile this `<type>`" paid from the battlefield (Lost Isle
#: Calling) — the hand-zone form above is a different cost.
#: ENG-49: "Exile this card from your graveyard" (Adorned Crocodile, the
#: Scavenge-shaped graveyard abilities) — paid by exiling the source from the
#: graveyard it is activated from (`ActivationCost.graveyard_zone`).
_EXILE_SELF_FROM_GRAVEYARD_RE = re.compile(
    r"exile\s+(?:this\s+card|~)\s+from\s+your\s+graveyard", re.IGNORECASE
)
_EXILE_SELF_RE = re.compile(
    r"\bexile (?:~|it|this (?!card\b)\w+)(?! from)(?=\s*(?:,|$))", re.IGNORECASE
)
#: RULE 702.138b — Escape's own cost component: "Exile N other cards from
#: your graveyard". ``N`` may be a digit or a spelled-out number word.
#: ENG-49 widened it to the activated-ability forms: "Exile two cards from
#: your graveyard" (Grim Lavamancer), "Exile a creature card from your
#: graveyard" (Balduvian Dead), "Exile X cards …" (Necropolis Fiend). The
#: type word is vetted like `_DISCARD_RE`'s.
_EXILE_GRAVEYARD_RE = re.compile(
    r"exile\s+(?P<n>" + _COUNT_WORD + r"|another)\s+(?:other\s+)?"
    # ENG-51: an either-type filter too ("an instant or sorcery card").
    r"(?:(?P<type>[a-z]+(?:\s+or\s+[a-z]+)?)\s+)?"
    r"cards?\s+from\s+your\s+graveyard",
    re.IGNORECASE,
)
#: RULE 701.59a "Collect evidence N" — a non-mana cost (an activated
#: ability's, or an additional cast cost) sized by a total-mana-value
#: threshold rather than a card count (`ActivationCost.collect_evidence`).
_COLLECT_EVIDENCE_RE = re.compile(r"collect\s+evidence\s+(\d+)", re.IGNORECASE)
#: RULE 701.61a "Forage" — a compound "exile three graveyard cards or
#: sacrifice a Food" non-mana cost (`ActivationCost.forage`, a bool).
_FORAGE_RE = re.compile(r"\bforage\b", re.IGNORECASE)
#: RULE 701.68 "Blight N" — a non-mana cost (an activated ability's, or an
#: additional cast cost): put N -1/-1 counters on a creature you control
#: (`ActivationCost.blight`). Previously silently dropped from a cost
#: string — the standalone-verb effect handler covered "blight N" only
#: mid-sentence, never `{cost}, Blight N: <effect>`.
_BLIGHT_RE = re.compile(r"\bblight\s+(\d+)", re.IGNORECASE)
#: "Exile the top card of your library" (Thought Lash) / "Exile the top
#: four cards of your library" (Seasoned Tactician, MEC-30) — a non-mana
#: additional cost paid straight off the payer's own library, distinct from
#: `exile_self_from_hand`'s hand-zone alternative-cost shape (which the
#: engine still doesn't charge through this path — see that field's own
#: docstring) since this one always has a real battlefield source to pay it
#: from. The count word is optional (bare "top card" implies exactly one).
_EXILE_TOP_LIBRARY_RE = re.compile(
    r"exile\s+the\s+top\s+(?:(?P<n>\d+|" + "|".join(NUMBER_WORDS) + r")\s+)?cards?\s+of\s+your\s+library",
    re.IGNORECASE,
)
#: "Put a card from your hand on top of your library" (Penance, MEC-30) — a
#: non-mana additional cost paid from hand, the chosen-card sibling of
#: `_EXILE_TOP_LIBRARY_RE`'s library-sourced cost. Charged via
#: `RulesEngine.put_hand_card_on_top_of_library`, resolved by
#: `ActivationMixin._resolve_put_hand_card_cost` (the same "chosen_ids, or
#: auto-pick" shape `_resolve_discard_cost` already uses for a plain
#: discard-N cost).
_PUT_HAND_CARD_ON_LIBRARY_RE = re.compile(
    r"put\s+a\s+card\s+from\s+your\s+hand\s+on\s+top\s+of\s+your\s+library", re.IGNORECASE
)
#: "Return a Forest you control to its owner's hand" (Quirion Ranger/Scryb
#: Ranger) — a non-mana additional cost that returns a permanent of a given
#: type the payer controls to hand, the same shape `_SACRIFICE_RE` uses for
#: "sacrifice a/an <type>" but for bounce instead of sacrifice. The type word
#: is kept as printed (singular on real cards — "Forest", not "Forests") and
#: lowercased for `continuous.has_subtype`'s case-insensitive match.
_RETURN_TO_HAND_RE = re.compile(
    r"return an?\s+([a-z]+)\s+you control to (?:its|your) owner'?s?\s*hand", re.IGNORECASE
)
#: "Unattach ~" (Blinding Powder's granted "Unattach ~: …"; the name itself
#: when a quoted grant is read before name normalization) — the Aura/
#: Equipment comes off whatever it's attached to (`ActivationCost.unattach_self`,
#: or `unattach_grant_source_id` for a granted ability).
_UNATTACH_RE = re.compile(
    r"\bunattach\s+(?:~|this\s+\w+|[a-z][a-z' -]*?)(?=\s*(?:,|$))", re.IGNORECASE
)
#: ENG-49: "Return ~ to its owner's hand" (Rootha, Recurring Nightmare) — the
#: source itself, the self-referring sibling of `_RETURN_TO_HAND_RE`.
_RETURN_SELF_TO_HAND_RE = re.compile(
    r"return\s+(?:~|this\s+\w+)\s+to\s+(?:its|your)\s+owner'?s?\s*hand", re.IGNORECASE
)
#: ENG-51: "Return two lands you control to their owner's hand" (Multani,
#: Yavimaya's Avatar) — `ActivationCost.return_to_hand_count`.
_RETURN_COUNT_TO_HAND_RE = re.compile(
    r"return\s+(?P<n>\d+|" + "|".join(w for w in NUMBER_WORDS if w not in ("a", "an"))
    + r")\s+(?P<type>[a-z]+)\s+you control to their owners?'?s?\s*hands?",
    re.IGNORECASE,
)
#: ENG-51: "Exert ~" as a cost (Fervent Paincaster, RULE 701.43).
_EXERT_SELF_RE = re.compile(r"\bexert\s+(?:~|this\s+\w+)", re.IGNORECASE)
#: ENG-51: "Mill a card" / "Mill two cards" as a cost (Deranged Assistant).
_MILL_RE = re.compile(r"\bmill\s+(?P<n>" + _COUNT_WORD + r")\s+cards?", re.IGNORECASE)
#: ENG-51: "Discard another card named ~" (Baru's Grandeur).
_DISCARD_SAME_NAME_RE = re.compile(r"discard\s+another\s+card\s+named\s+~", re.IGNORECASE)
#: ENG-51: "Exile the top [creature] card of your graveyard" (Alms, Necratog).
_EXILE_GRAVEYARD_TOP_RE = re.compile(
    r"exile\s+the\s+top\s+(?:(?P<type>[a-z]+)\s+)?card\s+of\s+your\s+graveyard", re.IGNORECASE
)
#: ENG-51: "Exile a card from your hand" (Cadaverous Bloom).
_EXILE_HAND_CARD_RE = re.compile(
    r"exile\s+(?P<n>a|an|\d+|" + "|".join(NUMBER_WORDS) + r")\s+cards?\s+from\s+your\s+hand",
    re.IGNORECASE,
)
#: ENG-51: "Pay half your life, rounded up" (Lurking Evil, RULE 119.4).
_PAY_HALF_LIFE_RE = re.compile(r"pay\s+half\s+your\s+life,?\s+rounded\s+up", re.IGNORECASE)
#: ENG-51: "Put a -1/-1 counter on a creature you control" (Hatchet Bully) —
#: exactly what "Blight 1" means (RULE 701.68), charged as one.
_BLIGHT_ONE_SPELLED_RE = re.compile(
    r"put\s+an?\s+-1/-1\s+counter\s+on\s+a\s+creature\s+you\s+control", re.IGNORECASE
)
#: ENG-51: "Tap enchanted creature" / "Tap enchanted land" (Krovikan Plague,
#: Earthlore) — the Aura's host is tapped as the cost.
_TAP_ATTACHED_RE = re.compile(r"\btap\s+enchanted\s+(?:creature|land|permanent)", re.IGNORECASE)
#: ENG-51: "Reveal ~ from your hand" — an ability activated from the hand
#: (`ActivationCost.hand_zone`); revealing is bookkeeping (RULE 701.16).
_REVEAL_SELF_FROM_HAND_RE = re.compile(
    r"reveal\s+(?:~|this\s+card)\s+from\s+your\s+hand", re.IGNORECASE
)
#: A planeswalker loyalty ability's cost — the ``[+2]`` / ``[-3]`` / ``[0]``
#: bracket at the start of the ability (RULE 606.5c). A leading "+" or no sign
#: means add loyalty; "−"/"-" means remove it. Accepts the Unicode minus too.
_LOYALTY_RE = re.compile(r"^\s*\[\s*([+\-−]?)\s*(\d+)\s*\]")

#: RULE 702.21b: "Some ward abilities include an X in their cost and state
#: what X is equal to." A ward cost's own "where X is …" clause — recognized
#: only for the small "count of X you control"/"cards in your graveyard"
#: vocabulary `game/continuous.py`'s `count_selector` already evaluates for
#: a characteristic-defining P/T (RULE 613.7c/604.3), so both share one
#: authored selector list rather than guessing a second one. No real card
#: needs this yet (`docs/implementation-state/BACKLOG.md`) — an
#: unrecognized/absent clause leaves ``x_selector`` unset, so `{X}` stays 0
#: (RULE 107.3c's safe default) rather than guessed.
_WARD_X_SELECTOR_RE = re.compile(
    r"where x is the number of (?P<phrase>[a-z ]+?)\s*(?=[.\n]|$)", re.IGNORECASE
)
WARD_X_SELECTOR_PHRASES: dict[str, str] = {
    "creatures you control": "creatures_you_control",
    "lands you control": "lands_you_control",
    "permanents you control": "permanents_you_control",
    "artifacts you control": "artifacts_you_control",
    "cards in your graveyard": "cards_in_your_graveyard",
}


#: Words a cost text may carry between its components that name no component
#: themselves — the list joiner ("{1}, {T}, and sacrifice ~") and the "pay" in
#: front of a mana/energy symbol run ("Pay {E}{E}", a `pay_cost_then` "pay
#: {X}").
_COST_FILLER_WORDS: frozenset[str] = frozenset({"and", "pay"})
_COST_WORD_RE = re.compile(r"[^\s,.;:]+")
#: The words a typed-card cost ("discard a **creature** card") may name — a
#: card type, a supertype, or a subtype (RULE 205). Anything else ("historic",
#: a colour) is a different filter, left unread so the ability fails closed.
_CARD_WORDS: frozenset[str] = frozenset({
    "artifact", "battle", "creature", "enchantment", "instant", "kindred",
    "land", "planeswalker", "sorcery", "tribal",
    "basic", "legendary", "snow", "world",
}) | SUBTYPES
#: A (lowercased) waterbend cost's keyword — RULE 701.67's "Waterbend {N}"
#: as an activation cost (Aang's Iceberg). Its {N} is read as plain mana, the
#: documented `ActivationCost.help_pay_kind` simplification.
_WATERBEND_RE = re.compile(r"\bwaterbend(?=\s*\{)", re.IGNORECASE)
#: An ability word (RULE 207.2c) the segmenter leaves on the cost ("Teleport —
#: {3}{W}", Blink Dog) — flavor with no rules meaning, so it is read and dropped.
_ABILITY_WORD_PREFIX_RE = re.compile(r"^\s*(?:•\s*)?[a-z][a-z' ]*?\s+—\s*", re.IGNORECASE)
#: Mana symbols that make a cost variable (RULE 107.3).
_VARIABLE_SYMBOLS: frozenset[str] = frozenset({"X", "Y", "Z"})


@dataclass
class CostScan:
    """What `scan_cost_text` read: ``braces`` is every ``{...}`` token's
    inner text in order; ``hits`` maps a recognizer name to its match (a
    component's absence from ``hits`` means the text doesn't carry it);
    ``leftover`` is the words nothing read, or ``None``."""

    braces: list[str] = field(default_factory=list)
    hits: dict[str, re.Match[str]] = field(default_factory=dict)
    leftover: Optional[str] = None


def _vetted_card_filter(phrase: Optional[str]) -> bool:
    """Whether a typed-card filter ("creature", "instant or sorcery") names
    only real card types/supertypes/subtypes (or is absent)."""
    if phrase is None:
        return True
    return all(part in _CARD_WORDS for part in phrase.lower().split(" or "))


def scan_cost_text(cost_text: str) -> CostScan:
    """Run every cost-component recognizer over ``cost_text`` (the part left
    of an ability's colon, RULE 602.1) in precedence order.

    Where two recognizers would read the same words, only the more specific
    one runs (a compound sacrifice before the single-type one, "discard this
    card" before "discard a card", "remove any number of" before "remove N",
    the hand/graveyard exile forms before the battlefield one)."""
    scan = CostScan()
    consumed: list[tuple[int, int]] = []

    def take(name: str, regex: re.Pattern[str], typed: bool = False) -> Optional[re.Match[str]]:
        match = regex.search(cost_text)
        if match is not None and typed and not _vetted_card_filter(match.group("type")):
            match = None  # an unvetted card filter — leave it unread
        if match is not None:
            scan.hits[name] = match
            consumed.append(match.span())
        return match

    # A loyalty ability's whole cost is its ``[±N]`` bracket (RULE 606.5c).
    loyalty = _LOYALTY_RE.match(cost_text)
    if loyalty is not None:
        scan.hits["loyalty"] = loyalty
        return scan

    for brace in _BRACE_RE.finditer(cost_text):
        consumed.append(brace.span())
        scan.braces.append(brace.group(1).strip())
    upper = {token.upper() for token in scan.braces}
    if "E" in upper:
        take("pay_energy_word", _PAY_ENERGY_WORD_RE)
    if upper & _VARIABLE_SYMBOLS:
        take("ward_x_selector", _WARD_X_SELECTOR_RE)
    take("exile_creature", _EXILE_CREATURE_RE)
    if not take("sacrifice_creature_artifact_or_land", _SACRIFICE_CREATURE_ARTIFACT_OR_LAND_RE):
        take("sacrifice", _SACRIFICE_RE)
    take("sacrifice_count", _SACRIFICE_COUNT_RE)
    take("pay_life", _PAY_LIFE_RE)
    take("pay_half_life", _PAY_HALF_LIFE_RE)
    if not take("discard_self", _DISCARD_SELF_RE):
        if not take("discard_same_name", _DISCARD_SAME_NAME_RE):
            take("discard", _DISCARD_RE, typed=True)
    if not take("remove_any_counters", _REMOVE_ANY_COUNTERS_RE):
        take("remove_counters", _REMOVE_COUNTERS_RE)
    if not take("exile_graveyard_top", _EXILE_GRAVEYARD_TOP_RE, typed=True):
        take("exile_from_graveyard", _EXILE_GRAVEYARD_RE, typed=True)
    take("exile_hand_card", _EXILE_HAND_CARD_RE)
    take("exert", _EXERT_SELF_RE)
    take("mill", _MILL_RE)
    take("tap_attached", _TAP_ATTACHED_RE)
    take("reveal_self_from_hand", _REVEAL_SELF_FROM_HAND_RE)
    take("waterbend", _WATERBEND_RE)
    take("ability_word", _ABILITY_WORD_PREFIX_RE)
    take("collect_evidence", _COLLECT_EVIDENCE_RE)
    take("forage", _FORAGE_RE)
    if not take("blight", _BLIGHT_RE):
        take("blight_one", _BLIGHT_ONE_SPELLED_RE)
    take("exile_top_of_library", _EXILE_TOP_LIBRARY_RE)
    take("put_hand_card_on_library", _PUT_HAND_CARD_ON_LIBRARY_RE)
    take("tap_others", _TAP_OTHERS_RE)
    take("add_counters_cost", _ADD_COUNTER_COST_RE)
    if not take("exile_self_from_hand", _EXILE_FROM_HAND_RE):
        if not take("exile_self_from_graveyard", _EXILE_SELF_FROM_GRAVEYARD_RE):
            take("exile_self", _EXILE_SELF_RE)
    take("unattach", _UNATTACH_RE)
    if not take("return_self_to_hand", _RETURN_SELF_TO_HAND_RE):
        if not take("return_count_to_hand", _RETURN_COUNT_TO_HAND_RE):
            take("return_to_hand", _RETURN_TO_HAND_RE)

    kept = list(cost_text)
    for begin, end in consumed:
        kept[begin:end] = [" "] * (end - begin)
    words = [
        word for word in _COST_WORD_RE.findall("".join(kept))
        if word.lower() not in _COST_FILLER_WORDS
    ]
    scan.leftover = " ".join(words) or None
    return scan
