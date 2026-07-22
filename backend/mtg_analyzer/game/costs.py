"""Activated-ability costs, recognized from cost text the regex way (RULE 602).

An activated ability is written ``[Cost]: [Effect].`` (RULE 602.1) — the cost
is everything left of the first colon, a comma-separated list of cost items.
Those items follow a small, regular grammar, so a handful of regexes read them
into a structured `ActivationCost` the engine can actually charge:

* mana symbols ``{2}{R}`` — the mana portion, handed to `ManaCost`;
* ``{T}`` / ``{Q}`` — tap / untap the source (RULE 602.1, 107.5);
* "Sacrifice ~ / a creature / an artifact" (RULE 701.17);
* "Pay N life" (RULE 118.4);
* "Discard a card / N cards / your hand" (RULE 701.8);
* "Remove a +1/+1 counter / N loyalty counters" (RULE 701.19).

Pure data + parsing only (it composes `ManaCost` and holds no game state), so
the binder and engine can share it. Charging a parsed cost against a player is
the engine's job (`GameEngine.activate_ability`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from ..models.mana_cost import ManaCost

#: Every ``{...}`` token in a cost string.
_BRACE_RE = re.compile(r"\{([^}]+)\}")

#: Number words a cost might spell out ("Discard two cards"); "a"/"an" == 1.
#: The tens words (twenty/thirty/forty/fifty) exist only for a "Pay N {E}"
#: energy cost's own outsized real counts (Aetherflux Conduit's "fifty").
_NUMBER_WORDS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}
#: RULE 122 energy: "Pay <word> {E}" (Aethersquall Ancient's "Pay eight
#: {E}", Aetherflux Conduit's "Pay fifty {E}") — a single ``{E}`` pip with a
#: spelled-out count in front, unlike the ordinary repeated-pip form
#: ("Pay {E}{E}{E}{E}", Guide of Souls) `_parse_text`'s brace loop already
#: counts directly.
_PAY_ENERGY_WORD_RE = re.compile(
    r"pay\s+(?P<n>" + "|".join(_NUMBER_WORDS) + r")\s+\{e\}", re.IGNORECASE
)

_SACRIFICE_RE = re.compile(
    r"sacrifice\s+(this\s+\w+|~|an?\s+(\w+)|another\s+(\w+))", re.IGNORECASE
)
_PAY_LIFE_RE = re.compile(r"pay\s+(\d+)\s+life", re.IGNORECASE)
_DISCARD_RE = re.compile(
    r"discard\s+(your\s+hand|a\s+card|\d+\s+cards?|[a-z]+\s+cards?)", re.IGNORECASE
)
#: Channel (RULE 702.29)/Cycling (RULE 702.28)'s own cost component:
#: "Discard this card: <effect>." / "{cost}, Discard this card: Draw a
#: card." — discarding the *specific* card bearing the ability, not a
#: player's choice of any card from hand (`_DISCARD_RE`'s generic shape).
#: Checked first so "this card" never falls through to `_DISCARD_RE` and
#: gets misread as "discard a card".
_DISCARD_SELF_RE = re.compile(r"discard this card", re.IGNORECASE)
_REMOVE_COUNTERS_RE = re.compile(
    r"remove\s+(\d+|[a-z]+)\s+([+\-]?\d+/[+\-]?\d+|[a-z]+)\s+counters?", re.IGNORECASE
)
#: "Remove any number of <kind> counters from ~" (the Mana Battery cycle/
#: storage lands/Geistflame Reservoir/Rhys the Evermore/The Astonishing
#: Ant-Man) — checked before `_REMOVE_COUNTERS_RE` since "any number of"
#: doesn't fit that regex's single-token count group at all.
_REMOVE_ANY_COUNTERS_RE = re.compile(
    r"remove\s+any number of\s+([+\-]?\d+/[+\-]?\d+|[a-z]+)\s+counters?", re.IGNORECASE
)
#: RULE 702.x-adjacent bulk-tap cost: "Tap two untapped Elves you control"
#: (Birchlore Rangers, Heritage Druid) — taps *other* permanents of a
#: creature type instead of the source itself. The type word is kept as
#: printed (plural, e.g. "Elves") and singularised by `_singularize` below.
_TAP_OTHERS_RE = re.compile(
    r"tap\s+(\d+|[a-z]+)\s+untapped\s+([a-z]+)\s+you control", re.IGNORECASE
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
    r"exile this \w+ from your hand", re.IGNORECASE
)
#: RULE 702.138b — Escape's own cost component: "Exile N other cards from
#: your graveyard". ``N`` may be a digit or a spelled-out number word.
_EXILE_GRAVEYARD_RE = re.compile(
    r"exile\s+(\d+|[a-z]+)\s+other\s+cards?\s+from\s+your\s+graveyard", re.IGNORECASE
)
#: "Exile the top card of your library" (Thought Lash) — a non-mana
#: additional cost paid straight off the payer's own library, distinct from
#: `exile_self_from_hand`'s hand-zone alternative-cost shape (which the
#: engine still doesn't charge through this path — see that field's own
#: docstring) since this one always has a real battlefield source to pay it
#: from.
_EXILE_TOP_LIBRARY_RE = re.compile(
    r"exile\s+the\s+top\s+card\s+of\s+your\s+library", re.IGNORECASE
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
#: needs this yet (`docs/implementation-state/ToDo_Backend.md`) — an
#: unrecognized/absent clause leaves ``x_selector`` unset, so `{X}` stays 0
#: (RULE 107.3c's safe default) rather than guessed.
_WARD_X_SELECTOR_RE = re.compile(
    r"where x is the number of (?P<phrase>[a-z ]+?)\s*(?=[.\n]|$)", re.IGNORECASE
)
_WARD_X_SELECTOR_PHRASES: dict[str, str] = {
    "creatures you control": "creatures_you_control",
    "lands you control": "lands_you_control",
    "permanents you control": "permanents_you_control",
    "artifacts you control": "artifacts_you_control",
    "cards in your graveyard": "cards_in_your_graveyard",
}

#: Sentinel for "discard your hand" — count isn't known until pay time.
DISCARD_HAND = -1

#: Sentinel for "pay X life" (RULE 601.2b's ~ additional-cost template) — the
#: amount isn't known until pay time, since it's tied to the spell's own
#: announced X, not a printed number.
PAY_LIFE_X = -1

#: Sentinels for `ActivationCost.remove_counters`'s ``count`` half, mirroring
#: `PAY_LIFE_X`'s idiom — the actual amount isn't a printed number, it's
#: announced at activation time (RULE 601.2b's template, applied to a
#: non-mana cost component): "Remove X counters" (`REMOVE_COUNTERS_X` — the
#: activation's own announced X, the same `x` a co-occurring `{X}` mana
#: symbol would also use, e.g. Chamber Sentry/Marath; several real cards
#: have no `{X}` mana at all, e.g. Blademane Baku, so X is announced purely
#: by this cost clause) and "Remove any number of counters"
#: (`REMOVE_COUNTERS_ANY` — a freely chosen amount, 0..however many are on
#: the permanent, not tied to any other X — the Mana Battery cycle/storage
#: lands). Both are paid/validated against the same `x` parameter
#: `activate_ability` already threads through for mana `{X}`.
REMOVE_COUNTERS_X = -1
REMOVE_COUNTERS_ANY = -2


def _word_to_int(word: str) -> int:
    word = word.strip().lower()
    if word.isdigit():
        return int(word)
    return _NUMBER_WORDS.get(word, 1)


def _singularize(word: str) -> str:
    """A plural creature type → singular ("elves"→"elf", "goblins"→"goblin")."""
    if word.endswith("ves"):
        return word[:-3] + "f"
    if word.endswith("s"):
        return word[:-1]
    return word


@dataclass
class ActivationCost:
    """The parsed cost of an activated ability (RULE 602.1), as pure data.

    ``mana`` is the mana portion; the rest are the non-mana cost items the
    engine charges in turn. ``sacrifice`` is what must be sacrificed —
    ``"self"`` for "Sacrifice ~", otherwise a type word ("creature",
    "artifact", "permanent", …). ``discard`` is a card count (or `DISCARD_HAND`
    for "your hand"); ``remove_counters`` is ``(kind, count)``.
    """

    mana: ManaCost = field(default_factory=ManaCost)
    taps_self: bool = False
    untaps_self: bool = False
    sacrifice: Optional[str] = None
    pay_life: int = 0
    #: RULE 122 energy: how many energy counters this cost pays (a player-
    #: level resource, `Player.counters["energy"]` — the same generic
    #: per-player counter dict "rad"/"poison" already use). Parsed from
    #: ``{E}`` pips in the cost text (`_parse_text`); charged by
    #: `GameEngine._pay_activation_cost` via `RulesEngine.add_player_counters`.
    pay_energy: int = 0
    discard: int = 0
    #: Channel (RULE 702.29)/Cycling (RULE 702.28): the cost is discarding
    #: *this specific card* from hand, not a player's choice of any card —
    #: distinct from ``discard`` (a battlefield ability's "discard N cards"),
    #: and paid from hand rather than off a battlefield permanent.
    discard_self: bool = False
    remove_counters: Optional[tuple[str, int]] = None
    #: RULE 702.138b (Escape): how many *other* cards must be exiled from the
    #: payer's own graveyard — "Exile four other cards from your graveyard".
    exile_from_graveyard: int = 0
    #: "Tap N untapped <type>s you control" (Birchlore Rangers, Heritage
    #: Druid) — ``(count, singular type word)``; taps *other* permanents
    #: instead of the source. Not limited by the tapped permanents' own
    #: summoning sickness (RULE 302.6 only restricts a permanent's own
    #: {T}-cost ability, not being tapped as someone else's cost).
    tap_others: Optional[tuple[int, str]] = None
    #: "Put a <kind> counter on this creature" as a *cost* (Devoted Druid's
    #: untap ability) — ``(kind, count)``; always payable (no minimum to
    #: check), unlike `remove_counters`.
    add_counters_cost: Optional[tuple[str, int]] = None
    #: "Return a Forest you control to its owner's hand" (Quirion Ranger/
    #: Scryb Ranger) — a non-mana additional cost; the lowercased subtype
    #: word (`continuous.has_subtype`-compatible) of the permanent to
    #: return, or ``None`` when this isn't such a cost.
    return_to_hand: Optional[str] = None
    #: "Exile this card from your hand" (Elvish Spirit Guide) — an
    #: alternative-zone cost the engine doesn't charge yet (no hand-zone
    #: activation path); recognised so the ability is never treated as a
    #: free battlefield tap (see `game/mana_abilities.py`).
    exile_self_from_hand: bool = False
    #: "Spend only mana of the chosen color to activate this ability" (Throne
    #: of Eldraine's second ability, RULE 601.2b/106.6) — a colour-lock on
    #: *this ability's own* mana cost (as opposed to a spend restriction on
    #: mana the ability *produces*): the whole mana cost must be paid with
    #: mana of the source's `GameObject.chosen_color`. Enforced by
    #: `GameEngine._can_pay_activation_cost`/`_pay_activation_cost`.
    spend_only_chosen_color: bool = False
    #: "Exile the top card of your library" (Thought Lash) — a non-mana
    #: additional cost paid off the payer's own library, charged by
    #: `GameEngine._pay_activation_cost` via `RulesEngine.exile`.
    exile_top_of_library: bool = False
    #: Loyalty-ability cost (RULE 606.5c): the signed change to the source's
    #: loyalty counters — ``+2`` for ``[+2]``, ``-3`` for ``[-3]``, ``0`` for
    #: ``[0]``. ``None`` means this is not a loyalty ability.
    loyalty: Optional[int] = None
    #: Sorcery-speed timing restriction (RULE 711.4b Leveler / 716.4c Class
    #: level-up abilities) that isn't tied to a planeswalker — see
    #: `GameEngine._sorcery_speed_ok`. Not itself a cost component.
    sorcery_speed_only: bool = False
    #: RULE 716.3/716.4c: this ability advances a Class to this level — legal
    #: only when the Class's current `class_level` is exactly one less. A
    #: legality precondition riding along with the cost, not something paid.
    class_level: Optional[int] = None
    #: "Unattach this Equipment" as its own cost component (Sunforger/Akiri,
    #: Fearless Voyager's second ability) — RULE 301.5c-adjacent: legal only
    #: while the source is actually attached to something (`GameEngine.
    #: _pay_activation_cost` checks/clears `attached_to`), distinct from
    #: Reconfigure's own "or unattach" *effect* (an alternative the Equip-
    #: like activated ability itself offers, not a cost paid to reach it).
    unattach_self: bool = False
    #: RULE 702.21b: a ward cost's own "where X is …" definition for an
    #: unresolved ``{X}`` in ``mana`` — one of `_WARD_X_SELECTOR_PHRASES`'
    #: values, resolved at the *ward ability's* resolution time (not when it
    #: triggers) by `RulesEngine._resolve_ward_x`. ``None`` when ``mana``
    #: has no `{X}`, or the "where X is …" clause wasn't recognized (X stays
    #: 0 — RULE 107.3c).
    x_selector: Optional[str] = None
    #: "This ability costs {1} less to activate for each rad counter you
    #: have." (Mariposa Military Base) — ``{"kind": "rad", "generic_per":
    #: 1}``: the generic mana cost drops by ``generic_per`` for every
    #: counter of ``kind`` the *activating player* (not the source) has,
    #: read live each activation (`GameEngine._reduced_activation_mana`).
    #: Unlike `continuous.activation_cost_reduction_for`'s Power Artifact-
    #: shaped static (a fixed amount granted by a *different* permanent),
    #: this is the ability's own printed, dynamically-scaled reduction —
    #: hand-authored only (`game/ability_catalogue.py`); no oracle-text
    #: grammar for it yet.
    dynamic_reduction: Optional[dict[str, Any]] = None
    raw: str = ""

    @property
    def is_loyalty(self) -> bool:
        """Whether this is a planeswalker loyalty ability (RULE 606.5c)."""
        return self.loyalty is not None

    @property
    def is_free(self) -> bool:
        """No cost at all — nothing to pay (RULE 118.5 "cost of {0}" analogue)."""
        return not (
            self.mana.symbols
            or self.taps_self
            or self.untaps_self
            or self.sacrifice
            or self.pay_life
            or self.pay_energy
            or self.discard
            or self.discard_self
            or self.remove_counters
            or self.loyalty is not None
            or self.exile_from_graveyard
            or self.tap_others
            or self.add_counters_cost
            or self.exile_self_from_hand
            or self.return_to_hand
        )

    def label(self) -> str:
        """A short "{T}, Sacrifice a creature, Pay 2 life" style summary."""
        parts: list[str] = []
        if self.mana.symbols:
            parts.append(self.mana.raw or "".join(f"{{{s.kind}}}" for s in self.mana.symbols))
        if self.taps_self:
            parts.append("{T}")
        if self.untaps_self:
            parts.append("{Q}")
        if self.sacrifice:
            what = "~" if self.sacrifice == "self" else f"a {self.sacrifice}"
            parts.append(f"Sacrifice {what}")
        if self.pay_life:
            parts.append("Pay X life" if self.pay_life == PAY_LIFE_X else f"Pay {self.pay_life} life")
        if self.pay_energy:
            parts.append(f"Pay {'{E}' * self.pay_energy}")
        if self.discard:
            parts.append("Discard your hand" if self.discard == DISCARD_HAND
                         else f"Discard {self.discard} card(s)")
        if self.discard_self:
            parts.append("Discard this card")
        if self.remove_counters:
            kind, count = self.remove_counters
            if count == REMOVE_COUNTERS_X:
                parts.append(f"Remove X {kind} counter(s)")
            elif count == REMOVE_COUNTERS_ANY:
                parts.append(f"Remove any number of {kind} counters")
            else:
                parts.append(f"Remove {count} {kind} counter(s)")
        if self.exile_from_graveyard:
            parts.append(f"Exile {self.exile_from_graveyard} other card(s) from your graveyard")
        if self.tap_others:
            count, subtype = self.tap_others
            parts.append(f"Tap {count} untapped {subtype}(s) you control")
        if self.add_counters_cost:
            kind, count = self.add_counters_cost
            parts.append(f"Put {count} {kind} counter(s) on this")
        if self.exile_self_from_hand:
            parts.append("Exile this card from your hand")
        if self.return_to_hand:
            parts.append(f"Return a {self.return_to_hand.capitalize()} you control to its owner's hand")
        if self.loyalty is not None:
            parts.append(f"[{'+' if self.loyalty >= 0 else ''}{self.loyalty}]")
        return ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mana": self.mana.raw,
            "taps_self": self.taps_self,
            "untaps_self": self.untaps_self,
            "sacrifice": self.sacrifice,
            "pay_life": self.pay_life,
            "pay_energy": self.pay_energy,
            "discard": self.discard,
            "discard_self": self.discard_self,
            "remove_counters": list(self.remove_counters) if self.remove_counters else None,
            "exile_from_graveyard": self.exile_from_graveyard,
            "tap_others": list(self.tap_others) if self.tap_others else None,
            "add_counters_cost": list(self.add_counters_cost) if self.add_counters_cost else None,
            "exile_self_from_hand": self.exile_self_from_hand,
            "return_to_hand": self.return_to_hand,
            "loyalty": self.loyalty,
            "x_selector": self.x_selector,
            "label": self.label(),
        }


def parse_activation_cost(
    cost: Union[None, str, dict[str, Any], ActivationCost]
) -> ActivationCost:
    """Recognize an `ActivationCost` from a cost text, a spec dict, or nothing.

    A **string** is the raw cost text (the part before the ability's colon,
    which callers may pass with or without the trailing effect). A **dict** is
    an `AbilitySpec.cost` — its explicit structured keys (``mana``,
    ``taps_self``, …) win over anything a ``text``/``cost_text`` field parses,
    so hand-authored specs stay authoritative. `None` yields a free cost.
    """
    if cost is None:
        return ActivationCost()
    if isinstance(cost, ActivationCost):
        return cost
    if isinstance(cost, str):
        return _parse_text(cost)

    # dict: parse any free text, then let explicit structured fields override.
    text = str(cost.get("text") or cost.get("cost_text") or "")
    parsed = _parse_text(text) if text else ActivationCost()
    if cost.get("mana"):
        parsed.mana = ManaCost.parse(str(cost["mana"]))
    if "taps_self" in cost:
        parsed.taps_self = bool(cost["taps_self"])
    if "untaps_self" in cost:
        parsed.untaps_self = bool(cost["untaps_self"])
    if cost.get("sacrifice"):
        parsed.sacrifice = str(cost["sacrifice"])
    if "pay_life" in cost:
        value = cost["pay_life"]
        parsed.pay_life = PAY_LIFE_X if value == "x" else int(value)
    if "pay_energy" in cost:
        parsed.pay_energy = int(cost["pay_energy"])
    if "discard" in cost:
        parsed.discard = int(cost["discard"])
    if "discard_self" in cost:
        parsed.discard_self = bool(cost["discard_self"])
    if cost.get("loyalty") is not None:
        parsed.loyalty = int(cost["loyalty"])
    if "exile_from_graveyard" in cost:
        parsed.exile_from_graveyard = int(cost["exile_from_graveyard"])
    if cost.get("tap_others"):
        count, subtype = cost["tap_others"]
        parsed.tap_others = (int(count), str(subtype))
    if cost.get("add_counters_cost"):
        kind, count = cost["add_counters_cost"]
        parsed.add_counters_cost = (str(kind), int(count))
    if cost.get("remove_counters"):
        kind, count = cost["remove_counters"]
        parsed.remove_counters = (str(kind), int(count))
    if cost.get("x_selector"):
        parsed.x_selector = str(cost["x_selector"])
    if "exile_self_from_hand" in cost:
        parsed.exile_self_from_hand = bool(cost["exile_self_from_hand"])
    if "spend_only_chosen_color" in cost:
        parsed.spend_only_chosen_color = bool(cost["spend_only_chosen_color"])
    if "exile_top_of_library" in cost:
        parsed.exile_top_of_library = bool(cost["exile_top_of_library"])
    if cost.get("return_to_hand"):
        parsed.return_to_hand = str(cost["return_to_hand"])
    if "sorcery_speed_only" in cost:
        parsed.sorcery_speed_only = bool(cost["sorcery_speed_only"])
    if cost.get("class_level") is not None:
        parsed.class_level = int(cost["class_level"])
    if "unattach_self" in cost:
        parsed.unattach_self = bool(cost["unattach_self"])
    if cost.get("dynamic_reduction"):
        parsed.dynamic_reduction = dict(cost["dynamic_reduction"])
    parsed.raw = parsed.raw or text
    return parsed


def _parse_text(text: str) -> ActivationCost:
    """Regex a cost string into an `ActivationCost` (the "very REGEX way")."""
    # Only look at the cost — the part before the first colon (RULE 602.1).
    cost_text = text.split(":", 1)[0] if ":" in text else text

    cost = ActivationCost(raw=cost_text.strip())

    # A loyalty ability's whole cost is its ``[±N]`` bracket (RULE 606.5c);
    # when present it is the entire cost, so return it directly.
    loyalty = _LOYALTY_RE.match(cost_text)
    if loyalty:
        magnitude = int(loyalty.group(2))
        sign = loyalty.group(1)
        cost.loyalty = -magnitude if sign in ("-", "−") else magnitude
        return cost

    # Mana + the {T}/{Q} symbols share the {...} syntax; split them apart.
    mana_tokens: list[str] = []
    energy_pips = 0
    for token in _BRACE_RE.findall(cost_text):
        upper = token.strip().upper()
        if upper == "T":
            cost.taps_self = True
        elif upper == "Q":
            cost.untaps_self = True
        elif upper == "E":
            # RULE 122: "Pay {E}{E}..." — each repeated pip pays one energy
            # counter; `_PAY_ENERGY_WORD_RE` below overrides this count for
            # the differently-worded "Pay <word> {E}" spelled-out form.
            energy_pips += 1
        else:
            mana_tokens.append(token.strip())
    if mana_tokens:
        cost.mana = ManaCost.parse("".join(f"{{{t}}}" for t in mana_tokens))
    if energy_pips:
        word_pay = _PAY_ENERGY_WORD_RE.search(cost_text)
        cost.pay_energy = _NUMBER_WORDS[word_pay.group("n").lower()] if word_pay else energy_pips
    if cost.mana.has_variable:
        # RULE 702.21b: a ward cost may define what its own {X} means.
        selector_match = _WARD_X_SELECTOR_RE.search(cost_text)
        if selector_match:
            cost.x_selector = _WARD_X_SELECTOR_PHRASES.get(
                selector_match.group("phrase").strip().lower()
            )

    sac = _SACRIFICE_RE.search(cost_text)
    if sac:
        whole = sac.group(1).lower()
        if whole.startswith("this") or whole == "~":
            cost.sacrifice = "self"
        else:
            cost.sacrifice = (sac.group(2) or sac.group(3) or "permanent").lower()

    life = _PAY_LIFE_RE.search(cost_text)
    if life:
        cost.pay_life = int(life.group(1))

    if _DISCARD_SELF_RE.search(cost_text):
        cost.discard_self = True
    else:
        discard = _DISCARD_RE.search(cost_text)
        if discard:
            phrase = discard.group(1).lower()
            if "hand" in phrase:
                cost.discard = DISCARD_HAND
            else:
                cost.discard = _word_to_int(phrase.split()[0])

    any_counters = _REMOVE_ANY_COUNTERS_RE.search(cost_text)
    if any_counters:
        cost.remove_counters = (any_counters.group(1).lower(), REMOVE_COUNTERS_ANY)
    else:
        counters = _REMOVE_COUNTERS_RE.search(cost_text)
        if counters:
            amount_word = counters.group(1).strip().lower()
            count = REMOVE_COUNTERS_X if amount_word == "x" else _word_to_int(amount_word)
            cost.remove_counters = (counters.group(2).lower(), count)

    exile_graveyard = _EXILE_GRAVEYARD_RE.search(cost_text)
    if exile_graveyard:
        cost.exile_from_graveyard = _word_to_int(exile_graveyard.group(1))

    if _EXILE_TOP_LIBRARY_RE.search(cost_text):
        cost.exile_top_of_library = True

    tap_others = _TAP_OTHERS_RE.search(cost_text)
    if tap_others:
        count = _word_to_int(tap_others.group(1))
        cost.tap_others = (count, _singularize(tap_others.group(2).lower()))

    add_counter = _ADD_COUNTER_COST_RE.search(cost_text)
    if add_counter:
        cost.add_counters_cost = (add_counter.group(1).lower(), 1)

    if _EXILE_FROM_HAND_RE.search(cost_text):
        cost.exile_self_from_hand = True

    return_to_hand = _RETURN_TO_HAND_RE.search(cost_text)
    if return_to_hand:
        cost.return_to_hand = return_to_hand.group(1).lower()

    return cost
