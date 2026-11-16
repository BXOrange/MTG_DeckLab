"""Segmenter: activation clauses (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Any, Optional
from ..catalogue.object_trigger_head import EXCESS_DAMAGE_KEY
from ..catalogue.cost_text import scan_cost_text
from ..catalogue.count_phrase import parse_count_phrase
from ..catalogue.clause_primitives import TARGET_PARAM_KEYS
from ..spec import EffectSpec

def is_activation_cost(cost: str) -> bool:
    """Whether the text left of a colon is an activation cost (RULE 602.1):
    the lexical `_COST_LOOKS_REAL` sniff, or (ENG-51) a text the cost
    grammar reads *completely* — "Tap enchanted creature", "Pay half your
    life, rounded up", "Exile the top card of your graveyard" name no symbol
    the sniff keys on, yet nothing in them is left unread."""
    if _COST_LOOKS_REAL.search(cost):
        return True
    scan = scan_cost_text(cost)
    return scan.leftover is None and bool(set(scan.hits) - {"ability_word"})


#: ENG-51: "`<cost>` or `<cost>`: …" — two alternative costs, each starting
#: with a mana/tap symbol ("{3}, {T} or {U}, {T}", Crystal Shard).
ALTERNATIVE_COST_RE = re.compile(r"(?P<a>\{[^:]*?\})\s+or\s+(?P<b>\{[^:]*)", re.IGNORECASE)

#: The one announced-X mana effect the engine scales — mirrors `game/
#: mana_abilities._ADD_X_ANY_ONE_COLOR_RE` (the front-end can't import it).
MANA_ABILITY_X_SUPPORTED_RE = re.compile(
    r"add x mana of any (?:one|1) colou?r\.?(?:\s*you gain x life\.?)?", re.IGNORECASE
)
#: A "Sacrifice X `<things>`" cost on a *mana* ability — see its guard.
MANA_ABILITY_SACRIFICE_X_RE = re.compile(r"\bsacrifice x\b", re.IGNORECASE)

#: An activated-ability wrapper: "<cost>: <effect>" (RULE 602.1). The cost is
#: everything before the first colon. Excludes `"` from the cost group too —
#: a real cost never contains a literal quote, but a quoted-ability-grant
#: line ("equipped creature has '{3}, {Q}: ...'") does, and its *inner*
#: colon isn't this line's own cost/effect boundary; without this guard the
#: quote-blind ``[^:]+`` swallows straight through to that inner colon
#: first, so the grant is never reached by `static_effect_specs` below.
ACTIVATED_RE = re.compile(r'^(?P<cost>[^:"]+):\s*(?P<effect>.+)$', re.S)

#: Throne of Eldraine's colour-lock rider on its second ability — a trailing
#: "Spend only mana of the chosen color to activate this ability." sentence,
#: peeled off the effect body and recorded as an `ActivationCost` flag.
SPEND_ONLY_CHOSEN_COLOR_RE = re.compile(
    r"\s*\.?\s*spend only mana of the chosen colou?r to activate this ability\.?",
    re.IGNORECASE,
)

#: "This ability costs {1} less to activate for each creature in your
#: party." (Seafloor Stalker, PAR-72) — a trailing sentence on the ability's
#: own effect body, peeled off and folded into `ActivationCost.
#: dynamic_reduction` (already wired for a `count_selector`-scaled per-
#: activation reduction, `costs.parse_activation_cost`'s ``dynamic_
#: reduction`` key — Eiganjo, Seat of the Empire's own hand-authored shape,
#: PAR-72 is the oracle-text route to the same primitive) rather than
#: becoming a (non-existent) effect.
ACTIVATION_COST_REDUCTION_PARTY_RE = re.compile(
    r"\s*\.?\s*this ability costs \{(?P<n>\d+)\} less to activate "
    r"for each creature in your party\.?",
    re.IGNORECASE,
)

# PAR-94: the general trailing, per-unit activation discount.  This stays a
# closed vocabulary: the engine may only receive a count selector it actually
# evaluates, and a novel "for each" phrase must leave its card unclaimed.
ACTIVATION_COST_REDUCTION_FOR_EACH_RE = re.compile(
    r"\s*\.?\s*this ability costs \{(?P<n>\d+)\} less to activate "
    r"for each (?P<what>.+?)(?=\.?\s*(?:activate\b|$))",
    re.IGNORECASE,
)

#: RULE 601.2f / 602.2b: "This ability costs {X} less to activate, where X is the number of `<phrase>`." (Astute
#: Terraformer, Suus Mahna Practitioner) -- one generic mana per counted object, the same reduction as the per-unit
#: "{1} less ... for each" form above (`ActivationCost.dynamic_reduction`).
ACTIVATION_COST_REDUCTION_WHERE_X_RE = re.compile(
    r"\s*\.?\s*this ability costs \{x\} less to activate, where x is the number of "
    r"(?P<what>.+?)(?=\.?\s*(?:activate\b|$))",
    re.IGNORECASE,
)

ACTIVATION_COST_REDUCTION_GRAVEYARD_MV_RE = re.compile(
    r"\s*\.?\s*this ability costs \{(?P<n>\d+)\} less to activate if there are "
    r"(?P<minimum>\d+) or more mana values among cards in your graveyard\.?$",
    re.IGNORECASE,
)

ACTIVATION_COST_REDUCTION_CONDITIONAL_RE = re.compile(
    r"\s*\.?\s*this ability costs \{(?P<n>\d+)\} less to activate if "
    r"(?P<condition>.+?)(?=\.?\s*(?:activate\b|$))",
    re.IGNORECASE,
)
ACTIVATION_COST_REDUCTION_COLORED_RE = re.compile(
    r"\s*\.?\s*this ability costs (?P<generic>\{\d+\})?"
    r"(?P<symbols>(?:\{[WUBRG]\})+) less to activate if "
    r"(?P<condition>.+?)(?=\.?\s*(?:activate\b|$))",
    re.IGNORECASE,
)

#: PAR-120: the quantity a counter-gated leaving trigger goes on to use —
#: "…if it had 1 or more +1/+1 counters on it, you may put **that many**
#: +1/+1 counters on target creature" (Reyhan), "…if it had counters on it,
#: create x … tokens, **where x is the number of counters on that
#: creature**" (Felisa). Both name the departing object's counters, which only
#: the event's RULE 400.7 snapshot still holds (`effect_amounts`'
#: ``trigger_event_counter``). Recognized only behind that gate, where "that
#: many" can mean nothing else.
LEAVING_COUNTER_THAT_MANY_RE = re.compile(r"\bthat (?:many|number of)\b", re.IGNORECASE)
LEAVING_COUNTER_WHERE_X_RE = re.compile(
    r"^(?P<rest>.+?),\s*where x is the number of (?:(?P<kind>\+1/\+1|-1/-1|[a-z]+) )?"
    r"counters (?:it had )?on (?:that creature|that permanent|it)\.?$",
    re.IGNORECASE | re.DOTALL,
)
#: PAR-243, RULE 120.4a: under an "is dealt excess damage" head the body's measure is the head's own excess -- "amass
#: Orcs X, where X is that excess damage" / "~ deals damage equal to the excess to ...". Both are read as a literal X
#: bound to the firing DAMAGE event's ``excess_damage`` (re-read when the ability resolves, so a recipient that has since
#: left the battlefield still counts).
EXCESS_WHERE_X_RE = re.compile(r"^(?P<rest>.+?),\s*where x is (?:that|the) excess(?: damage)?\.?$", re.IGNORECASE | re.DOTALL)
EXCESS_DAMAGE_EQUAL_RE = re.compile(r"\bdamage equal to the excess\b", re.IGNORECASE)
EXCESS_DAMAGE_EVENT_AMOUNT: dict[str, Any] = {"kind": "trigger_event", "field": EXCESS_DAMAGE_KEY}
#: The DAMAGE event field naming the *recipient* (`binding.core._subject_event_key` reads the same one for a
#: recipient-side head); "other than that permanent" under such a head excludes it, not the damage source.
_DAMAGE_RECIPIENT_EVENT_KEY = "target_id"


def stamp_recipient_exclusion(node: Any) -> Any:
    """``node`` with every ``excluding_trigger_subject`` target naming the damaged permanent as that subject."""
    if isinstance(node, EffectSpec):
        return EffectSpec(node.type, stamp_recipient_exclusion(node.params), condition=node.condition)
    if isinstance(node, list):
        return [stamp_recipient_exclusion(item) for item in node]
    if not isinstance(node, dict):
        return node
    stamped = {key: stamp_recipient_exclusion(value) for key, value in node.items()}
    if stamped.get("excluding_trigger_subject") is True:
        stamped["excluding_trigger_subject_key"] = _DAMAGE_RECIPIENT_EVENT_KEY
    return stamped


LEAVING_COUNTER_COPY_RE = re.compile(
    r"^create (?P<count>\d+) tokens? that are copies of it\.?$", re.IGNORECASE,
)
LEAVING_COUNTER_RETURN_LOSE_RE = re.compile(
    r"^return it to the battlefield under its owner'?s control and "
    r"it loses all abilities\.?$", re.I,
)
LEAVING_COUNTER_IF_ELSE_RE = re.compile(
    r"^exile it if it had a (?P<kind>[a-z]+) counter on it\.\s*"
    r"otherwise,? return it to the battlefield under your control and "
    r"put a (?P=kind) counter on it\.?$", re.I | re.S,
)
#: "…, create a token that's a copy of it at the beginning of the next end
#: step. The token enters with half that many +1/+1 counters on it, rounded
#: down." (Ochre Jelly's Split). "That many" may already read "x" here.
LEAVING_COUNTER_DELAYED_COPY_RE = re.compile(
    r"^create a token that's a copy of it at the beginning of the next end step\.\s*"
    r"the token enters with half (?:that many|x) (?P<kind>\+1/\+1|[a-z]+) counters on it,"
    r" rounded down\.?$", re.I | re.S,
)
LEAVING_COUNTER_CREATE_TRANSFER_RE = re.compile(
    r"^(?P<create>create a 0/0 [^.]+? creature token),? then "
    r"put ~'s counters on that token\.?$", re.I | re.S,
)

COST_PAID_SOURCE_HAD_RE = re.compile(
    r"\bif it had (?P<n>\d+) or more (?P<kind>\+1/\+1|[a-z]+) counters on it,", re.I,
)
LEAVING_COUNTER_INTERVENING_RE = re.compile(
    r"^if it had (?:(?P<no>no)|(?P<count>\d+) or more|(?P<article>a|an))?\s*"
    r"(?P<kind>\+\d+/\+\d+|\-\d+/\-\d+|[a-z]+)?\s*"
    r"counters? on it,\s*(?P<rest>.+)$",
    re.IGNORECASE | re.S,
)

#: PAR-120 (PARSER_VERSION 470): PAR-94's original 14-entry table shrunk to
#: the six shapes the shared `count_phrase` grammar genuinely doesn't reach
#: — a distinct-land-*type* count (not an object count), the "and" union
#: idiom (RULE 400.1, same reasoning as `static_handlers._SELF_COST_PER_PHRASES`), a
#: two-card-type union, and the "other `<X>`"/"modified `<X>`" qualifiers
#: (`not_reference`/a modified flag aren't reachable through this entry
#: point — confirmed via direct `parse_count_phrase` checks, not assumed).
#: A `+1/+1 counter` *count* is a different measurement axis entirely (how
#: many counters, not how many objects), so it was never going to be a
#: `count_phrase` selector regardless. `activation_cost_reduction_selector`
#: below tries the grammar first for everything else — six of the original
#: fourteen entries retired that way, plus the old `island`-only land
#: fallback (the same subtype match the grammar already makes generically).
_ACTIVATION_COST_REDUCTION_SELECTORS: dict[str, str] = {
    "basic land type among lands you control": "basic_land_types_among_lands_you_control",
    "instant and sorcery card in your graveyard": "instant_or_sorcery_cards_in_your_graveyard",
    "legendary creature and planeswalker you control": "legendary_creatures_and_planeswalkers_you_control",
    "other artifact you control": "other_artifacts_you_control",
    "other equipment you control": "other_permanents_you_control_of_subtype_equipment",
    "other town you control": "other_permanents_you_control_of_subtype_town",
    "modified creature you control": "modified_creatures_you_control",
    "+1/+1 counter on creatures you control": "plus_one_counters_on_creatures_you_control",
}


def activation_cost_reduction_selector(what: str) -> "Optional[str | dict]":
    """Map PAR-94's per-unit discount vocabulary to live readers."""
    normalized = " ".join(what.lower().split())

    structured = parse_count_phrase(normalized)
    if structured is not None:
        return structured
    selector = _ACTIVATION_COST_REDUCTION_SELECTORS.get(normalized)
    if selector is not None:
        return selector
    counter = re.fullmatch(
        r"(?P<kind>[a-z][a-z-]*) counters? on (?:~|this (?:artifact|creature|enchantment))",
        normalized,
    )
    if counter is not None:
        return f"source_{counter.group('kind')}_counters"
    power = re.fullmatch(
        r"creature with power (?P<n>\d+) or greater your opponents control", normalized
    )
    if power is not None:
        return f"creatures_opponents_control_with_power_ge_{power.group('n')}"
    return None

# An activated ability may end with its RULE 602 legality sentence rather
# than making it a separate oracle line: "{1}: Draw a card. Activate only if
# <condition> [and only once]."  Peel only this closed tail before parsing
# the actual body; the existing handler catalogue supplies the condition
# marker and the existing binder owns both activation limits.
ANY_PLAYER_MAY_ACTIVATE_RE = re.compile(
    r"\s*\bany player may activate this ability(?P<sorcery> but only as a sorcery)?\.?\s*$", re.IGNORECASE
)
ACTIVATE_ONLY_IF_TRAILING_RE = re.compile(
    r"\.\s*activate (?:this ability )?only (?:if (?P<cond>.+?)|during the (?P<step>declare attackers) step"
    r"(?: and only if (?P<cond2>.+?))?)(?P<once> and only once)?\.?$",
    re.IGNORECASE,
)

#: A cost is only trusted as one if it actually *looks* like a cost — a mana/
#: {T} symbol, or one of the non-mana cost words. This keeps a stray sentence
#: colon (and loyalty "[+1]:" costs, not modeled yet — RULE 606) from being
#: mis-read as an activation cost (fail-closed). "put a counter on this/~"
#: is Devoted Druid's "Put a -1/-1 counter on this creature: Untap this
#: creature." cost; "tap ... untapped ... you control" is Birchlore Rangers'/
#: Heritage Druid's bulk-tap cost (RULE 602.1, `costs.tap_others`); "remove a
#: [+1/+1] counter from this creature" is Walking Ballista/Triskelion's
#: counter-removal cost (RULE 701.19, `costs.remove_counters` — this module
#: can't import `game/costs.py`'s `_REMOVE_COUNTERS_RE` directly, front-end
#: security boundary, so the count/kind shape here is kept loose and just
#: needs to sniff "is this a cost at all", not fully parse it — keep the verb
#: fragment in sync if that regex's grammar ever changes).
_COST_LOOKS_REAL = re.compile(
    r"\{[^}]+\}|sacrifice|pay \d+ life|discard|put an? .+ counter on|"
    # RULE 701.59a / 701.61a / 701.68 keyword-action costs — Gristle
    # Glutton ("{T}, Blight 1: …"), Polygraph Orb / Hedge Whisperer /
    # Tenth District Hero ("…, collect evidence N: …"). All three are real
    # `costs.parse_activation_cost` fragments (`ActivationCost.collect_
    # evidence`/`forage`/`blight`) charged by `_can`/`_pay_player_cost`.
    r"collect evidence \d+|forage|blight \d+|"
    r"tap .+ untapped .+ you control|remove .+ counters?|"
    r"return an? [a-z]+ you control to (?:its|your) owner'?s?\s*hand|"
    r"exile (?:this \w+|~) from (?:your|their) hand|"
    # An attached Aura/Equipment can be named in a quoted granted ability's
    # cost (Blinding Powder). The nested grant parser supplies the precise
    # granting-object reference after this lexical cost check.
    r"unattach (?:this \w+|~|[a-z][a-z' -]+)|"
    # "Exile a creature you control: …" (Food Chain, MEC-40) — a RULE
    # 605.1a mana-ability cost component (`costs._EXILE_CREATURE_RE`),
    # the battlefield-zone sibling of the hand-zone exile cost just above.
    r"exile an? [a-z]+ you control",
    re.I,
)

#: A planeswalker loyalty ability: "+N:", "-N:", "0:" then the effect (RULE
#: 606.5c) — real Scryfall oracle text prints the sign/digit bare, with no
#: surrounding brackets ("+1: Target player mills two cards. Draw a card.",
#: not "[+1]: ..."); an optional bracket pair is still accepted too (some
#: older fixtures/UI conventions use it), so either form matches. Bare
#: sign+digit+colon is unambiguous as a loyalty cost — no mana-cost/
#: sacrifice/pay-life/discard activated-ability cost is ever templated this
#: way — so this is checked before the generic activated case whose cost
#: sniff (`_COST_LOOKS_REAL`) wouldn't accept a bare "+1" anyway.
LOYALTY_LINE_RE = re.compile(
    r"^\s*\[?\s*([+\-−]?)\s*(\d+|x)\s*\]?\s*:\s*(?P<effect>.+)$", re.S
)

#: A mana ability's effect ("add {g}", "add 1 mana of any color"): the engine
#: models these in `game/mana_abilities.py`, not through effect specs, so such a
#: line is *claimed* here (covered) but contributes no spec.
MANA_EFFECT_RE = re.compile(r"^add\b", re.I)

#: RULE 605.1a: unlike the legacy prefix recognizer, this validates the whole
#: fixed-symbol mana body before it can become a quoted token ability.
FIXED_MANA_EFFECT_RE = re.compile(r"add (?:\{[wubrgc]\})+\.?", re.I)

#: "For each color among permanents you control, add one mana of that
#: color." (Bloom Tender/Faeburrow Elder-shaped) — doesn't start with "add"
#: (that's mid-sentence, after the "for each" clause), so `MANA_EFFECT_RE`
#: above never matches it; mirrors `game/mana_abilities.py`'s own
#: `_COLORS_AMONG_PERMANENTS_RE` exactly; this module can't import that one
#: directly (front-end security boundary), so the shape is duplicated
#: rather than shared — keep the two in sync if it ever changes.
COLORS_AMONG_PERMANENTS_MANA_RE = re.compile(
    r"^for each colou?r among permanents you control, add (?:one|1) mana of that colou?r\.?$",
    re.IGNORECASE,
)

#: "Choose a color. Add an amount of mana of that color equal to your
#: devotion to that color." (Nykthos, Shrine to Nyx) — same "doesn't start
#: with 'add'" gap `COLORS_AMONG_PERMANENTS_MANA_RE` closes, this time for
#: `game/mana_abilities.py`'s ``"devotion_to_chosen_color"`` kind; mirrors
#: `mana_abilities.py`'s own `_DEVOTION_CHOSEN_COLOR_ADD_RE` (front-end
#: can't import `game/`, so the shape is duplicated, not shared).
DEVOTION_CHOSEN_COLOR_MANA_RE = re.compile(
    r"^choose a colou?r\. add an amount of mana of that colou?r equal to "
    r"your devotion to that colou?r\.?$",
    re.IGNORECASE,
)

#: "Choose a color. Add an amount of mana of that color equal to the number of `<phrase>`." (Starfleet Academy) --
#: `game/mana_abilities.py`'s ``_COUNTED_CHOSEN_COLOR_ADD_RE``; claimed only when the shared amount grammar reads
#: the phrase, exactly as the engine side requires.
COUNTED_CHOSEN_COLOR_MANA_RE = re.compile(
    r"^choose a colou?r\. add an amount of mana of that colou?r equal to (?P<amount>the number of .+?)\.?$",
    re.IGNORECASE,
)

#: "Play with the top card of your library revealed." (Oracle of Mul
#: Daya/Future Sight-shaped) — purely informational, no separate game-state
#: effect: it's always printed as its own line right next to the actual
#: play/cast-from-top permission (`catalogue.static_handlers.
#: _TOP_LIBRARY_PERMISSION_RE`), whose own grant already implies visibility
#: (`game/top_library.py`'s `may_look_at_top_of_library` — "a permission to
#: play cards from the top implies seeing them"), so this line adds no new
#: information over that grant. Claimed as a documented no-op (mirroring how
#: a mana-ability's own effect line is "covered but no spec" above) rather
#: than wired into new behaviour. Contrast the *standalone* "you may look at
#: the top card of your library any time." line (Sphinx of Jwar Isle-shaped,
#: no accompanying play/cast permission on ~57 real cards) — that one is a
#: genuine, independent RULE 400.2-adjacent visibility grant, so it's
#: claimed by `static_handlers._LOOK_AT_TOP_ANY_TIME_RE` instead, as a real
#: `top_library_permission {"look": True}` spec, not here.
PLAY_WITH_TOP_REVEALED_RE = re.compile(
    r"^play with the top card of your library revealed\.?$", re.IGNORECASE
)

#: Connectors that chain two effect clauses in one ability body, tried in this
#: order when the whole body isn't a single handled clause.
#: PAR-141: a comma before a *pronoun-led* effect clause is a sentence boundary too ("put a +1/+1 counter on that
#: creature, it gains haste until end of turn, and it becomes a Vampire …", Olivia) — only when the next clause
#: opens with "it"/"that creature" plus a verb that acts on it, so a comma inside one clause is never split.
PRONOUN_COMMA_CONNECTOR = r",\s+(?:and\s+)?(?=(?:it|that creature)\s+(?:gains?|becomes|gets?|has|loses)\b)"
#: Effects that neither target nor create anything, so a pronoun chain runs straight through them: "clash with
#: an opponent" (PAR-30) and the player designations ("you take the initiative", "you become the monarch" —
#: PAR-139: From the Catacombs' "put … onto the battlefield … with a corpse counter on it. You take the
#: initiative. If that creature would leave the battlefield, exile it instead …").
REFERENT_TRANSPARENT_TYPES: frozenset[str] = frozenset(
    {"clash", "coin_flip", "roll_die", "take_initiative", "become_monarch"}
)

#: PAR-137: the longest run of consecutive sentences a clause row may claim as one unit when a body
#: is split on periods ("return up to 1 target … to the battlefield. Exile the top 2 cards of your
#: library. Until the end of your next turn, you may play those cards." — the exile row owns *two*
#: sentences). Four covers the longest multi-sentence rows (a dig with its rest and else tail);
#: a longer window would only be a slower way of failing.
MAX_SENTENCE_WINDOW = 4


AND_CONNECTOR = r"\s+and\s+"
#: PAR-208: the commas of a series "A, B, and C" ("target player mills 2 cards, draws 2 cards, and loses 2 life"; "you
#: draw a card, gain 1 life, and scry 1") sit between whole effect clauses of one sentence. Only a comma whose next
#: word opens an effect clause (a whitelisted effect verb, or a stated player subject) is a boundary, so a comma
#: inside a condition, an amount phrase or a target description is never split. The last "and" of the series is
#: consumed with its comma; a two-clause "A and B" keeps `AND_CONNECTOR`.
_SERIES_VERBS = (
    r"draws?|discards?|mills?|loses?|gains?|scry|surveil|creates?|sacrifices?|exiles?|returns?|untaps?|taps?|"
    r"destroys?|puts?|adds?|investigate|proliferate|explores?|goads?|reveals?|shuffles?|searches"
)
SERIES_COMMA_CONNECTOR = (
    rf",\s+(?:and\s+)?(?=(?:(?:{_SERIES_VERBS})\b|(?:you|each opponent|each player|target (?:player|opponent))\s+(?:{_SERIES_VERBS})\b))"
)
CONNECTORS: tuple[str, ...] = (
    r"\.\s+", r";\s+", r",?\s+then\s+", PRONOUN_COMMA_CONNECTOR, SERIES_COMMA_CONNECTOR, AND_CONNECTOR,
)


#: The connectors that end a sentence (RULE 608.2c), as opposed to ones inside it.
SENTENCE_CONNECTORS: tuple[str, ...] = (CONNECTORS[0], CONNECTORS[1])
#: A sentence that opens with a gate and continues after a comma ("If it's a land card, you gain 1 life"); the match
#: runs to the end of that sentence.
_SENTENCE_LEADING_GATE_RE = re.compile(r"(?:^|\.\s+)(?:if|unless) [^,.]+,\s[^.]*", re.IGNORECASE)


def splits_inside_gated_sentence(body: str, separator: str) -> bool:
    """Whether ``separator`` would cut a sentence that opens with a gate after its consequent has begun."""
    # An "instead" sentence replaces a whole earlier instruction, so all of its clauses are the replacement
    # (`instead_override_specs` re-gates them itself); only plain gated sentences are kept whole here.
    spans = [m.span() for m in _SENTENCE_LEADING_GATE_RE.finditer(body) if not re.search(r"\binstead\b", m.group(0))]
    return any(lo <= cut.start() < hi for cut in re.finditer(separator, body) for lo, hi in spans)


def split_effect_connector(body: str, separator: str) -> list[str]:
    """Keep a quoted ability intact while splitting the surrounding effects."""
    spans = [(m.start(), m.end()) for m in re.finditer(separator, body)
             if body[:m.start()].count('"') % 2 == 0]
    if separator == CONNECTORS[0]:
        # A quoted ability's final period also ends its
        # enclosing sentence; retain the closing quote in that first part.
        spans.extend((m.start() + 1, m.end()) for m in re.finditer(r'(?<=\.)"\s+', body)
                     if body[:m.start()].count('"') % 2 == 1)
    parts = []
    start = 0
    for left, right in sorted(spans):
        if left < start:
            continue
        parts.append(body[start:left])
        start = right
    parts.append(body[start:])
    return [part for part in parts if part.strip()]
#: "**target player|opponent** draws a card" … "and **loses** 2 life": a third-person-singular verb opening a
#: later "and" part has no subject of its own (the bare "lose" of "you draw and lose" is the controller's).
ELIDED_TARGET_LOSS_RE = re.compile(r"\b(?:other|another)\b", re.IGNORECASE)
#: ENG-52 (RULE 109.5/115.3): a later clause naming "any other target" / "another target …" / "a third target" must
#: not repeat what an earlier clause of the same ability chose. `resolve_target_kind` reads those words down to the
#: plain kind, so the distinctness is stamped on the clause's own effect (`TargetSpec.distinct_from_others`).
#: The single-requirement effect types the flag is stamped on (`binding.build_effects` applies it to the effect's
#: `TargetSpec`; `damage`/`add_counters` also read it in their own factory). A verb with several requirements of
#: its own (fight, damage equal to power) keeps its dedicated parameter.
_DISTINCT_FROM_OTHERS_TYPES = frozenset({"damage", "add_counters", "pump", "destroy", "exile", "tap", "return_to_hand"})


def stamp_distinct_from_others(effects: list[EffectSpec]) -> tuple[list[EffectSpec], bool]:
    """``effects`` with ``distinct_from_others`` set on each targeting effect that supports it, and whether
    any was stamped (a clause whose effect has no such parameter keeps its old reading)."""
    stamped = False
    out: list[EffectSpec] = []
    for effect in effects:
        if (
            effect.type in _DISTINCT_FROM_OTHERS_TYPES
            and effect.params.get("selector") is None and effect.params.get("group") is None
            and (effect.params.get("target_kind") is not None or effect.type in ("damage", "add_counters"))
        ):
            out.append(EffectSpec(effect.type, {**effect.params, "distinct_from_others": True}, condition=effect.condition))
            stamped = True
        else:
            out.append(effect)
    return out, stamped
ELIDED_AMOUNT_VERBS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("~ deals ", re.compile(r"^(?:\d+|x) damage\b", re.IGNORECASE)),
    ("you gain ", re.compile(r"^(?:\d+|x) life\b", re.IGNORECASE)),
)
_TARGET_PLAYER_SUBJECT_RE = re.compile(r"^target (?:player|opponent) ", re.IGNORECASE)
ELIDED_PLAYER_VERB_RE = re.compile(r"^(?:loses|gains|draws|discards|mills)\b", re.IGNORECASE)
#: How each effect type is pointed at the player an earlier clause of the same sentence chose
#: (`GameContext.previous_targets`): a flag the effect reads, or a ``player`` referent. A type missing here
#: has no such reading, so the sentence is refused rather than left acting on the controller.
_PREVIOUS_PLAYER_STAMPS: dict[str, dict[str, Any]] = {
    "lose_life": {"previous_subject": True},
    "discard": {"previous_subject": True},
    "draw": {"player": {"of": "previous_player"}},
    "gain_life": {"player": {"of": "previous_player"}},
}


def elides_player_subject(first_part: str, part: str) -> bool:
    return (_TARGET_PLAYER_SUBJECT_RE.match(first_part.strip()) is not None
            and ELIDED_PLAYER_VERB_RE.match(part.strip()) is not None)


def stamp_previous_player(effects: list[EffectSpec]) -> "Optional[list[EffectSpec]]":
    """See `_PREVIOUS_PLAYER_STAMPS`; ``None`` when an effect has no such reading."""
    stamped: list[EffectSpec] = []
    for effect in effects:
        if any(effect.params.get(k) is not None for k in TARGET_PARAM_KEYS):
            stamped.append(effect)  # it names its own target
            continue
        extra = _PREVIOUS_PLAYER_STAMPS.get(effect.type)
        if extra is None:
            return None
        stamped.append(EffectSpec(effect.type, {**effect.params, **extra}, condition=effect.condition))
    return stamped

#: RULE 702.33b/701.x's "if `<this spell was kicked|it was kicked[
#: twice]|this spell/it was bargained>`, `<effect>`." — a *second,
#: additional* effect gated on an optional cost actually having been paid.
#: "This spell" (Vastwood Surge-shaped: a base effect, then this as its own
#: sentence) is a spell's own resolution; "it" (PAR-17, Heartstabber
#: Mosquito/Citanul Woodreaders-shaped) is the *same* gate as a triggered
#: ability's own — and, there, only — effect body, "it" being the
#: ability's source rather than a spell. Three gates: bare "kicked" (Kicker
#: paid at least once), "kicked twice" (RULE 702.34a Multikicker's own
#: count threshold — Archangel of Wrath, ``kicked_at_least``), and
#: "bargained" (RULE 701.x, Beseech the Mirror — `effects.
#: ConditionalEffect._condition_holds` has supported this key since the
#: cEDH-cube batch, but no oracle-text recognizer ever reached it until
#: now). Only "additional effect" shapes are recognised; "if kicked, it
#: deals N damage instead" (overriding an *earlier* effect's own amount —
#: Burst Lightning/Rite of Replication-shaped) is a different, unmodeled
#: grammar — the wrapped ``rest`` there fails `match_clause` on its own (no
#: target/full clause of its own), so it fails closed here too rather than
#: needing a separate check.
KICKED_CONDITION_RE = re.compile(
    r"^if (?:this spell|it) was (?P<kind>kicked(?: twice)?|bargained),\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

#: PAR-30 / RULE 601.2b: "if this spell's additional cost was paid,
#: `<effect>`." (Ruinous Waterbending, Secret of Bloodbending, Katara
#: Seeking Revenge's ETB) — the generic optional-additional-cost sibling of
#: `KICKED_CONDITION_RE`, onto `EffectSpec.condition`'s
#: ``"additional_cost_paid"`` key (`GameObject.additional_cost_paid`, set at
#: cast time). Only the *additive* "if paid, <extra effect>" shape; the
#: "…, <effect> instead" amount-override shape (Spirit Water Revival) fails
#: `match_clause` on ``rest`` the same way the "if kicked … instead" shape
#: does, so it stays unclaimed here too.
ADDITIONAL_COST_PAID_CONDITION_RE = re.compile(
    r"^if (?:this spell's|the spell's|its|her|his|their) additional cost was paid,\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

#: MEC-106 / RULE 702.174k: "if the gift was[n't] promised, `<effect>`." — an additive rider
#: gated on the caster having promised the gift. "Instead" overrides ("… , instead `<effect>`")
#: are a different, override grammar and fall to `_INSTEAD_OVERRIDE_RE`.
GIFT_PROMISED_CONDITION_RE = re.compile(
    r"^if the gift (?P<neg>was|wasn'?t) promised,\s*(?P<rest>(?!instead\b).+)$", re.IGNORECASE,
)

#: PAR-56 / RULE 702.194: Teamwork is an optional additional cost with its
#: own cast-state marker, so ordinary "if this spell was cast using
#: teamwork" riders use the same additive conditional-effect path as Kicker.
TEAMWORK_PAID_CONDITION_RE = re.compile(
    r"^if this spell was cast using teamwork,\s*(?P<rest>.+)$", re.IGNORECASE,
)

#: PAR-275 / RULE 601.2: "If this spell is the first spell you've cast this game, `<effect>`." (First Contact) -- the
#: resolving spell's own game-long cast ordinal (`source_is_first_spell_cast_this_game`).
FIRST_SPELL_THIS_GAME_CONDITION_RE = re.compile(
    r"^if this spell is the first spell you'?ve cast this game,\s*(?P<rest>.+)$", re.IGNORECASE,
)

#: PAR-30 / RULE 601.2b: the *negative, suffix* sibling — "`<effect>` unless
#: `<its>` additional cost was paid." (Katara, Seeking Revenge — "draw a
#: card, then discard a card **unless her additional cost was paid**."):
#: the effect body applies only when the optional cost was *not* paid, so
#: each spec is tagged ``condition={"additional_cost_paid": False}``.
ADDITIONAL_COST_NOT_PAID_SUFFIX_RE = re.compile(
    r"^(?P<rest>.+?) unless (?:this spell's|the spell's|its|her|his|their) additional cost was paid$",
    re.IGNORECASE,
)

#: RULE 603.4 intervening-if as a *suffix* — "`<effect>` **if an opponent
#: lost N or more life this turn**." (Davros, Dalek Creator's own end-step
#: token). Same "parse the rest, tag every spec's condition" idiom as the
#: prefix conditions above, onto `EffectSpec.condition`'s
#: ``"opponent_lost_life_this_turn_at_least"`` key (`GameState.
#: life_lost_this_turn`). ``rest`` is non-greedy so the shortest clause that
#: still parses carries the gate.
OPPONENT_LOST_LIFE_SUFFIX_RE = re.compile(
    r"^(?P<rest>.+?) if an opponent lost (?P<n>\d+) or more life this turn$",
    re.IGNORECASE,
)

#: RULE 603.4-style intervening-if keyed to a just-chosen *target*, rather
#: than an announced-cost flag (The Ghoul, Gunslinger: "target player gets
#: two rad counters. If that player is you, create a Treasure token.") —
#: mirrors `KICKED_CONDITION_RE`'s "wrap the rest, tag the condition" idiom
#: exactly, onto `EffectSpec.condition`'s ``"target_is_controller"`` key
#: instead of ``"kicked"``. "If that player isn't you, ..." (the negation)
#: is real MTG templating too, so both polarities are recognised here.
TARGET_IS_CONTROLLER_RE = re.compile(
    r"^if that player is(?P<neg> not|n't)? you,\s*(?P<rest>.+)$", re.IGNORECASE
)

#: RULE 119.3's "if you gained N or more life this turn, `<effect>`."
#: (Frodo, Adventurous Hobbit's own first clause) — same "wrap the rest, tag
#: the condition" idiom as `KICKED_CONDITION_RE`, onto `GameState.
#: life_gained_this_turn` via `EffectSpec.condition`'s new
#: ``"life_gained_this_turn_at_least"`` key. ``rest`` is non-greedy with an
#: explicit ``trailing`` tail for Frodo's own printed shape — "if A, effect1.
#: Then if B, effect2." is *two* independently-gated sentences, not one
#: condition spanning both; without splitting here the naive greedy-``.+``
#: reading would slap *this* condition onto the second sentence's own
#: `EffectSpec` too, silently discarding its real "if ~ is your Ring-bearer
#: and the Ring has tempted you N or more times" gate — a wrong-but-modeled
#: card, worse than leaving it unclaimed.
LIFE_GAINED_THIS_TURN_CONDITION_RE = re.compile(
    r"^if you gained (?P<n>\d+) or more life this turn,\s*(?P<rest>.+?)"
    r"(?P<trailing>\.\s+then\s+if\s+.+)?$",
    re.IGNORECASE,
)

#: RULE 603.4's own textbook example — "if it's the first combat phase of
#: the turn, `<effect>`." (Karlach, Fury of Avernus/Finest Hour/Genji
#: Glove/Raiyuu-shaped — every one of them an extra-combat-granting
#: trigger guarding against re-triggering itself in the extra phase it just
#: made, the same self-loop `not_already_exerted` guards for Exert) — same
#: "wrap the rest, tag the condition" idiom as `KICKED_CONDITION_RE`, onto
#: `effects.ConditionalEffect`'s new ``"is_first_combat_phase"`` key
#: (`GameState.combats_this_turn`).
#: PAR-120: "…if this is the second time this ability has resolved this
#: turn" (Rumor Gatherer, Elrond, Tannuk) and the ladder that continues it —
#: "`<effect>` if this is the first time …. if it's the second time,
#: `<effect>`. if it's the third time, `<effect>`." (Omnath, Locus of
#: Creation; Belladonna Took; Vito). The bare "it's the second time" only
#: ever prints as such a ladder's continuation, naming the same count. Read
#: off `GameContext.ability_resolution_count` (the resolution now happening
#: included — "the third time" is exactly the third, never the fourth, per
#: the cards' rulings), so it is an effect-time gate only: deliberately not
#: in `static_condition()`, where an "as long as" static could claim it.
RESOLUTION_ORDINALS: dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
}
RESOLUTION_TIME = (
    r"(?:this is|it'?s|it is) the (?P<ord>first|second|third|fourth|fifth)"
    r"(?: or (?P<ord2>second|third|fourth|fifth))? time"
    r"(?: this ability has resolved this turn)?"
)
RESOLUTION_COUNT_PREFIX_RE = re.compile(
    rf"^if {RESOLUTION_TIME},\s*(?P<rest>.+)$", re.IGNORECASE | re.DOTALL,
)
RESOLUTION_COUNT_SUFFIX_RE = re.compile(
    rf"^(?P<rest>.+?),?\s+if {RESOLUTION_TIME}\.?$", re.IGNORECASE | re.DOTALL,
)
