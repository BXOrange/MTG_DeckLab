"""Draw/discard/hand rows, free-cast and play windows, put-from-hand (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import re

from typing import Any, Optional
from ..casting_window import (
    parse_dig_cast_free,
    parse_exile_cast_window,
    parse_linked_play,
    parse_linked_move,
    parse_exile_followup,
    parse_exile_copy_cast,
    parse_free_cast_zone,
    parse_graveyard_play_window,
)
from ..characteristic_phrase import parse_object_phrase, PERMANENT_CARD_TYPES
from ..clause_hooks import parse_effect_body
from ..count_phrase import parse_amount_phrase, parse_count_phrase
from ..subgrammars import (
    COUNT,
    count_of,
    count_or_x_of,
    COUNT_X,
    DEVOTION,
    devotion_selector,
    NUMBER,
    PERMANENT_TYPE_WORDS,
    resolve_color_word,
    resolve_target_kind,
    subtype_count_selector,
)
from ..subtype_vocabulary import SUBTYPES
from ...normalize import SELF
from ...spec import EffectSpec
from ..clause_hooks import match_clause
from ..clause_reading import PLAYER
from .shared import (
    ANY_NUMBER_TARGET_CAP,
    CAST_WINDOW_COLORS,
    compile_clause,
    EffectHandler,
    EVENT_PLAYER_EVENTS_KEY,
    GRAVEYARD_SCOPE_WORD,
    graveyard_target_kind,
    GRAVEYARD_TYPE_WORD,
    NAMED_TOKEN_WORDS,
    NONCREATURE_SUBTYPE_WORDS,
    SACRIFICE_EDICT_WHAT_WORDS,
    xx_token_mid_params,
)


#: "Each creature deals N damage to its controller." (Rakdos Charm) — unlike
#: `_SELECTOR_WORD_MAP`'s rows, the subject here is "each creature"
#: itself, not "~"/the source, and the recipient varies per creature
#: (`effects.DealDamageEffect`'s ``"each_creature_controller"`` selector).
_DAMAGE_EACH_CREATURE_TO_CONTROLLER_RE = compile_clause(
    rf"each creature deals {NUMBER} damage to its controller"
)


def _damage_each_creature_to_controller(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {"amount": int(m.group("n")), "selector": "each_creature_controller"})]


#: "draw that many cards" (Vilis, Broker of Blood's "whenever you lose
#: life, draw that many cards" — MEC-43) — "that many" refers back to the
#: firing event's own ``amount`` (RULE 603.1), the same `count_from_
#: trigger_event` idiom `_create_token_that_many`/the "put that many
#: counters" row already use for their own effect types.
_DRAW_THAT_MANY_RE = compile_clause(r"draws? that many cards?")


def _draw_that_many(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw", {"count_from_trigger_event": "amount"})]


#: The wheel (RULE 701.8f): "Each player discards their hand, then draws N cards." (Reforge the Soul, Wheel
#: of Fate) is a `seq` of a whole-hand mass discard and a mass draw — the hand-authored Wheel of Fortune's
#: own shape. "…**may** discard their hand and draw N cards" (Raphael's Technique, Ruin Grinder, Will of the
#: Jeskai) is each player's own choice: a loop over the players whose body asks that player (`optional`'s
#: ``player="target"``, the loop item handed in as the target) and then acts on them.
_WHEEL_RE = compile_clause(r"each player discards (?:their|all the cards in their) hand, then draws (?P<n>\d+) cards?")
_MAY_WHEEL_RE = compile_clause(r"each player may discard their hand and draw (?P<n>\d+) cards?")


def _wheel(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("seq", {"effects": [
        {"type": "discard", "params": {"scope": "each_player", "whole_hand": True}},
        {"type": "draw", "params": {"selector": "each_player", "count": int(m.group("n"))}},
    ]})]


def _may_wheel(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("for_each", {"over": {"players": "each_player"}, "effects": [
        {"type": "optional", "params": {"player": "target", "effects": [
            {"type": "discard", "params": {"target_kind": "player", "whole_hand": True}},
            {"type": "draw", "params": {"target_kind": "player", "count": int(m.group("n"))}},
        ]}},
    ]})]


#: "draw an / N additional cards" — a draw-step trigger's bonus draw (Overbeing of Myth,
#: Well of Ideas). "Additional" changes no draw semantics; N is an ordinary draw count.
#: Fullmatched, so a trailing count qualifier must be handled by the composition grammar.
_DRAW_ADDITIONAL_RE = compile_clause(r"(?:you )?draw (?P<n>an|\d+) additional cards?")

# The choice's existing discard delta survives suspension and draws only
# the number actually discarded, including zero (RULE 701.8).
_DISCARD_UP_TO_DRAW_RE = compile_clause(
    r"(?:you may )?discard up to (?P<n>\d+) cards?(?:, then|\. if you do,) draw that many cards"
)

# RULE 401.4: preserve the pre-move hand size across the ordering choice.
_HAND_BOTTOM_DRAW_RE = compile_clause(
    r"(?:you )?put the cards in your hand on the bottom of your library in any order, "
    r"then draw that many cards"
)


def _hand_bottom_draw(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("bind", {
        "name": "n", "amount": {"kind": "resource", "resource": "hand_size", "of": "you"},
        "effects": [
            EffectSpec("put_hand_on_bottom", {}).to_dict(),
            EffectSpec("draw", {"count": "$n"}).to_dict(),
        ],
    })]


#: "Target player draws N cards, then discards M cards." (Prismari Command /
#: Whispering Madness-adjacent) — the loot shape aimed at a chosen player.
#: The trailing bare "discards" has no explicit subject, so the connector
#: split can't link it (that only fires after a *creature* target); this
#: dedicated row emits the `previous_subject` link itself.
_TARGET_PLAYER_LOOT_RE = compile_clause(
    r"target player draws (?P<draw_n>a|an|\d+) cards?, "
    r"then discards (?P<disc_n>a|an|\d+|x) cards?"
)


def _target_player_loot(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("draw", {"count": count_of(m.group("draw_n")), "target_kind": "player"}),
        EffectSpec("discard", {
            "count": count_or_x_of(m.group("disc_n")), "previous_subject": True,
        }),
    ]


#: "You and target opponent each draw N cards." (Secret Rendezvous / Sky
#: Crier / Loran of the Third Path / Farsight Adept / Flumph) — a symmetric
#: two-player draw: one untargeted draw for the source's controller and one
#: `RULE 115` targeted draw for the chosen opponent, resolved in that order.
_YOU_AND_TARGET_OPP_DRAW_RE = compile_clause(
    r"you and target opponent each draw (?P<n>a|an|\d+) cards?"
)


def _you_and_target_opponent_draw(m: re.Match[str]) -> list[EffectSpec]:
    n = count_of(m.group("n"))
    return [
        EffectSpec("draw", {"count": n}),
        EffectSpec("draw", {"count": n, "target_kind": "opponent"}),
    ]


def _draw(m: re.Match[str]) -> list[EffectSpec]:
    # `COUNT_X` also matches a literal "x" (RULE 107.3c's own announced
    # {X}, "draw X cards" — Contaminated Drink), resolved via the same
    # ``"x"`` sentinel `RulesEngine._substitute_x` already substitutes for
    # every other one-shot effect's magnitude field.
    params: dict = {"count": count_or_x_of(m.group("n"))}
    # "target player/opponent draws a card" (Kenrith/Oona's Grace-shaped) is
    # a real RULE 115 target, mirroring `_discard`'s own ``who`` treatment —
    # without this, "target player draws a card" would have made the
    # *source's controller* draw instead of the chosen player. "each
    # player/opponent draws" is the untargeted mass form (RULE 601.2c).
    who = (m.groupdict().get("who") or "").strip()
    if who in ("target player", "target opponent"):
        params["target_kind"] = "player"
    elif who in ("each player", "each opponent"):
        params["selector"] = who.replace(" ", "_")
    return [EffectSpec("draw", params)]


def _draw_next_upkeep(m: re.Match[str]) -> list[EffectSpec]:
    """RULE 603.7 delayed trigger: "draw a card at the beginning of the next
    turn's upkeep" (Clairvoyance/Balduvian Rage/Carrier Pigeons-shaped, ~46
    real cards). Arms via `create_delayed_trigger` — the same primitive
    Batch 22 built for Mana Drain — with ``scope="any"``: no "your"
    qualifier means the very next upkeep regardless of whose turn (RULE
    603.7a), unlike Mana Drain's own controller-scoped "your next main
    phase". A pronoun-scoped variant ("its controller may draw...", Arcane
    Denial's own first sentence) is deliberately unclaimed here — a
    different, indirect-referent grammar shape, same family of gap as
    Run Away Together's (`docs/implementation-state/BACKLOG.md`)."""
    return [EffectSpec("create_delayed_trigger", {
        "step": "upkeep",
        "scope": "any",
        "effects": [{"type": "draw", "params": {"count": count_of(m.group("n"))}}],
    })]


# A mill's captured pool composes with ordinary selection and return effects.
_RECOVER_MILLED_RE = compile_clause(
    r"(?P<may>you may )?put (?P<quant>an?|up to \d+|all|any number of) "
    r"(?P<what>.+? cards?) from among the milled cards "
    r"(?P<dest>into your hand|onto the battlefield|on top of your library)"
    r"(?P<control> under your control)?"
)


def _recover_milled(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    parsed = parse_object_phrase(m.group("what"), plural=True)
    if parsed is None or parsed[1] is not None:
        return None
    destination = {"into your hand": "hand", "onto the battlefield": "battlefield",
                   "on top of your library": "library_top"}[m.group("dest")]
    if m.group("control") and destination != "battlefield":
        return None
    quant = m.group("quant")
    count = int(quant.split()[-1]) if quant.startswith("up to ") else "all" if quant in {"all", "any number of"} else 1
    return [EffectSpec("choose_objects", {
        "action": "select_referent", "what": "card", "pool_zone": "milled",
        "permanent_filter": parsed[0], "count": count,
        "optional": bool(m.group("may")) or quant.startswith("up to ") or quant == "any number of",
        "then": [{"type": "return_from_graveyard", "params": {
            "previous_subject": True, "destination": destination,
            "under_your_control": destination == "battlefield",
        }}],
    })]


#: PAR-208 (RULE 608.2d / 701.x "return"): "return a creature card from your graveyard to your hand" / "return up to 2
#: creature cards ..." / "return a creature card and a land card ..." with no "target": the resolving player's own pick
#: from their graveyard (`ChooseObjectsEffect`, ``pool_zone="graveyard"``), "up to N" being an optional pick. Mill-then-
#: return (Another Chance, Carrion Cruiser, Sudden Reclamation) reaches it through the ordinary "then" connector.
_OWN_GRAVEYARD_PICK = r"(?:an?|up to (?:\d+|one|two|three)) [a-z/ -]+? cards?"
_RETURN_OWN_GRAVEYARD_RE = compile_clause(
    rf"return (?P<picks>{_OWN_GRAVEYARD_PICK}(?: and {_OWN_GRAVEYARD_PICK})?) from your graveyard to your hand"
)
_OWN_GRAVEYARD_PICK_RE = re.compile(r"(?P<q>an?|up to (?P<n>\d+|one|two|three)) (?P<what>[a-z/ -]+? cards?)")
_UP_TO_WORDS = {"one": 1, "two": 2, "three": 3}


def _return_own_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    picks = re.split(r" and (?=an? |up to )", m.group("picks"))
    specs: list[EffectSpec] = []
    for text in picks:
        pick = _OWN_GRAVEYARD_PICK_RE.fullmatch(text)
        if pick is None:
            return None
        parsed = parse_object_phrase(pick.group("what"), plural=True)
        if parsed is None or parsed[1] is not None or "target" in text:
            return None
        n = pick.group("n")
        count = 1 if n is None else _UP_TO_WORDS.get(n) or int(n)
        specs.append(EffectSpec("choose_objects", {
            "action": "return_from_graveyard_to_hand", "what": "permanent", "pool_zone": "graveyard",
            "permanent_filter": parsed[0], "count": count, "optional": n is not None,
        }))
    return specs


# Per-type keeper choices share one pool and sacrifice its complement.
_CHOOSE_KEEP_TYPES_RE = compile_clause(
    r"(?P<who>each player|each opponent) chooses (?P<choices>an? [a-z]+(?:(?:, |,? and )an? [a-z]+)*) "
    r"from among the (?P<pool>.+?) they control, then sacrifices the rest"
)


def _choose_keep_types(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    kinds = [re.sub(r"^an? ", "", word) for word in re.split(r",? and |, ", m.group("choices"))]
    if len(set(kinds)) != len(kinds) or any(kind not in PERMANENT_CARD_TYPES for kind in kinds):
        return None
    pool = parse_count_phrase(m.group("pool") + " you control")
    if pool is None or pool.get("zone") != "battlefield" or pool.get("of") != "you":
        return None
    return [EffectSpec("choose_player_objects", {
        "action": "sacrifice_rest", "keep_types": kinds, "permanent_filter": pool.get("filter", {}),
        "player_scope": "each_player" if m.group("who") == "each player" else "each_opponent",
    })]


#: MEC-127 (RULE 101.4, 608.2e, 701.17/701.8): "each player chooses N <permanents> they control[, then sacrifices the
#: rest | . Destroy the rest | . Destroy all other X | . Return all X not chosen this way to their owners' hands]"
#: (Razia's Purification, Covetous Elegy, Single Combat, Divine Reckoning, Fall of the First Civilization, Urza's
#: Sylex, Consuming Tide). One counted pick per player in APNAP order, then one simultaneous removal of the rest.
_CHOOSE_KEEP_COUNT_RE = compile_clause(
    r"(?P<who>each player|each opponent) chooses (?P<up>up to )?(?P<n>an?|\d+) (?P<pool>[a-z ]+?) they control"
    r"(?:, then (?P<sac>sacrifices the rest)"
    r"|\. (?:(?P<dest>destroy (?:the rest|all other (?P<dvict>[a-z ]+?)))"
    r"|return all (?P<rvict>[a-z ]+?) not chosen this way to their owners' hands))"
)


#: Smallest count the "up to N" keep form accepts. The only printed "up to" keeper is Covetous Elegy ("up to two"),
#: so smaller optional counts stay unclaimed (fail closed) until a real card needs one and a test covers it.
_KEEP_UP_TO_MIN_COUNT = 2


def _choose_keep_count(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    pool = parse_count_phrase(m.group("pool") + " you control")
    if pool is None or pool.get("zone") != "battlefield" or pool.get("of") != "you":
        return None
    count = 1 if m.group("n") in ("a", "an") else int(m.group("n"))
    if count < 1 or (m.group("up") and count < _KEEP_UP_TO_MIN_COUNT):
        return None
    params: dict = {
        "action": "sacrifice_rest", "keep_count": count, "permanent_filter": pool.get("filter", {}),
        "player_scope": "each_player" if m.group("who") == "each player" else "each_opponent",
        "rest_action": "sacrifice" if m.group("sac") else "destroy" if m.group("dest") else "return_to_hand",
    }
    if m.group("up"):
        params["keep_up_to"] = True
    victims = m.group("dvict") or m.group("rvict")
    if victims:
        # The removal can name a wider class than the pool one chooses from ("choose 6 lands ... destroy all other
        # permanents"); an identical class is just the pool again.
        wide = parse_count_phrase(victims + " you control")
        if wide is None or wide.get("zone") != "battlefield" or wide.get("of") != "you":
            return None
        if wide.get("filter", {}) != params["permanent_filter"]:
            params["victim_filter"] = wide.get("filter", {})
    return [EffectSpec("choose_player_objects", params)]


#: Planar Overlay: "Each player chooses a land they control of each basic land type. Return those lands to their
#: owners' hands." (RULE 305.6: one keeper category per basic land type; the *chosen* lands are the ones returned.)
_CHOOSE_LAND_OF_EACH_TYPE_RE = compile_clause(
    r"each player chooses a land they control of each basic land type\. "
    r"return those lands to their owners' hands"
)
_BASIC_LAND_TYPE_WORDS = ("plains", "island", "swamp", "mountain", "forest")


def _choose_land_of_each_type(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("choose_player_objects", {
        "action": "sacrifice_rest", "keep_types": list(_BASIC_LAND_TYPE_WORDS), "act_on_chosen": True,
        "rest_action": "return_to_hand", "permanent_filter": {"card_type": "land"}, "player_scope": "each_player",
    })]


# Library slices share one deterministic exile primitive: whose library,
# which edge to remove from, and how many cards to remove or retain.
_LIBRARY_EXILE_RE = compile_clause(
    r"(?:(?P<who>that player) exiles|exile) (?:(?P<all>all cards)|all but the (?P<keep_edge>top|bottom) "
    r"(?:(?P<keep_n>\d+) cards?|(?P<keep_one>card))|the (?P<edge>top|bottom) "
    r"(?:(?P<n>\d+) cards?|(?P<one>card))) (?:of|from) "
    r"(?P<owner>your|their|that player'?s|target player'?s|target opponent'?s|each player'?s|each opponent'?s) library"
    r"(?P<face_down> face down)?"
)


def _library_exile(m: re.Match[str], reading) -> Optional[list[EffectSpec]]:
    owner = m.group("owner").replace("'", "")
    params: dict = {"face_down": bool(m.group("face_down"))}
    if owner in ('their', 'that players'):
        if (owner == 'their') != bool(m['who']):
            return None
        previous = any(ref.kind == PLAYER for ref in reading.referents)
        params['player'] = {'of': 'previous_player' if previous else 'trigger_player', 'as': 'self'}
        if not previous:
            params['event_player_events'] = ['DAMAGE', 'ATTACKS', 'SPELL_CAST', 'STEP_BEGIN',
                                              'CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER']
    elif m['who']:
        return None
    elif owner.startswith("target "):
        params.update(player_selector="target", target_kind=resolve_target_kind(owner[:-1]))
    else:
        params["player_selector"] = {"your": "controller", "each players": "each_player",
                                     "each opponents": "each_opponent"}[owner]
    if m.group("all") or m.group("keep_edge"):
        params["keep_bottom"] = int(m.group("keep_n") or (1 if m.group("keep_one") else 0))
        params["position"] = "bottom" if m.group("keep_edge") == "top" else "top"
    else:
        params.update(count=int(m.group("n") or 1), position=m.group("edge"))
    return [EffectSpec("exile_top_of_library", params)]


#: RULE 601.3b's "impulsive draw" shape (PAR-13, Dungeon of the Mad Mage's
#: "Runestone Caverns" — "Exile the top two cards of your library. You may
#: play them."; also Bonehoard Dracosaur/Painter's Studio's own trailing
#: duration variants) — `ImpulsiveDrawEffect` already existed as a
#: hand-authored-only primitive (Light Up the Stage); this is the first
#: oracle-text recognizer to reach it. A bare, undurationed "you may play
#: them" (the dungeon room's own phrasing, with no explicit window at all)
#: defaults to the effect's own "until the end of your next turn" — the
#: more common real-card convention for an unqualified "you may play them".
#: MEC-12 fourth pass widened this: the *leading*-duration word order
#: ("Until the end of your next turn, you may play those cards." — Light Up
#: the Stage/Reckless Impulse/Commune with Lava's own real printed text,
#: not the trailing form this row was first written against) is at least as
#: common cache-wide as the trailing one, "that card"/"those cards" are as
#: real as the pronoun "them"/"it", the singular "the top card" (no number)
#: needs its own alternative since ``\d+`` can't match zero digits, and
#: ``count_or_x_of`` covers "the top x cards" (Commune with Lava) via the
#: same ``"x"``-sentinel/`RulesEngine._substitute_x` idiom every other
#: X-scaled one-shot effect already uses.
#: "…until your next end step." (Opera Love Song) accepted as a third
#: duration word alongside "this turn"/"until the end of your next turn" —
#: **documented simplification**: `ImpulsiveDrawEffect`'s window is turn-
#: scoped (`_grant_temp_play_permission`'s ``same_turn_only`` sweeps at
#: *this* turn's own cleanup, the finest granularity it has), so this maps
#: to ``same_turn_only=True`` rather than a genuine step-scoped expiry.
#: Exact when cast during the caster's own turn (their next end step
#: *is* later this same turn); an instant-speed cast on an opponent's turn
#: would close the window at that turn's cleanup instead of carrying it
#: into the caster's own next end step — narrower than RAW, not wider.
#: PAR-137 widened the row: the window word may also be "until end of turn", and a *choice* of one
#: of the exiled cards is accepted — "exile the top 2 cards of your library[,] [then] choose 1 of
#: them. You may play that card this turn" and "… you may play 1 of those cards this turn" — which
#: keeps the play permission on the pick alone (`ImpulsiveDrawEffect.choose_one`).
_EXILE_TOP_WINDOW = r"this turn|until (?:the )?end of turn|until the end of your next turn|until your next end step|for as long as (?:they|it) remain(?:s)? exiled"
_EXILE_TOP_PLAY_RE = compile_clause(
    r"(?:exile the top (?:(?P<n>\d+|x) cards?|card) of (?:your|(?P<each>each player'?s)) library"
    r"|(?P<damaged>that player) exiles that many cards from the top of their library)(?:\.|, then) "
    r"(?P<choose>choose 1(?: of (?:them|those cards))?\. )?"
    rf"(?:(?P<dur_pre>{_EXILE_TOP_WINDOW}), )?"
    r"you may play (?P<what>(?P<lands>lands from among those cards)|them|it|that card|those cards|the exiled cards|cards exiled this way|1 of those cards)"
    rf"(?: (?P<dur_post>{_EXILE_TOP_WINDOW}))?"
    # PAR-163 (Lidless Gaze): RULE 605.1a spend permission on those spells, "any color" / "any type".
    r"(?P<wild>,? and (?:you may spend mana as though it were mana of any (?P<wild_what>color|type) to cast those spells"
    r"|mana of any (?P<wild_what2>color|type) can be spent to cast those spells))?"
)


def _exile_top_play(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dur = (m.groupdict().get("dur_pre") or m.groupdict().get("dur_post") or "").strip()
    same_turn_only = dur in ("this turn", "until end of turn", "until the end of turn", "until your next end step")
    n = m.group("n")
    what = m.group("what")
    choose_one = bool(m.group("choose")) or what == "1 of those cards"
    count = {'kind': 'trigger_event', 'field': 'amount'} if m.group('damaged') else count_or_x_of(n) if n else 1
    # "that card"/"it" names *the* card — one exiled card, or the pick; "them"/"those cards" every one.
    singular = what in ("it", "that card")
    if singular and not choose_one and count != 1:
        return None
    if m.group("each") and (singular or choose_one):
        return None  # one card per library: a lone "that card" names no particular one
    if m.group("choose") and what != "that card":
        return None
    params: dict = {"count": count, "same_turn_only": same_turn_only}
    if m.group('damaged'):
        params['library_of'] = 'that_player'
    if dur.startswith('for as long as '):
        params['standing'] = True
    if m.group('lands'):
        params['card_filter'] = {'card_type': 'land'}
    if choose_one:
        params["choose_one"] = True
    if m.group("each"):
        params["each_player"] = True  # one exile per library, every card playable by the controller (Mezzio Mugger shape)
    if m.group("wild"):
        params["mana_wildcard"] = m.group("wild_what") or m.group("wild_what2")
    return [EffectSpec("impulsive_draw", params)]


#: PAR-163: the play-window half of an exile-and-may-play pair -- "[Until the end of your next turn,] you may
#: play/cast that card [until the end of your next turn][, and you may spend mana as though it were mana of any
#: color to cast that spell]" after a clause that exiled a card (`ExileEffect` leaves it as the referent). Only the
#: RULE 611.2 "end of your next turn" window; "that card" only ("it" is too often something else).
_PLAY_WINDOW_NEXT_TURN = r"until the end of your next turn"
_PLAY_WINDOW_PREVIOUS_RE = compile_clause(
    rf"(?:(?P<pre>{_PLAY_WINDOW_NEXT_TURN}), )?(?:you may )?(?P<verb>play|cast) that card"
    rf"(?P<post> {_PLAY_WINDOW_NEXT_TURN})?"
    r"(?P<wild>,? and you may spend mana as though it were mana of any color to cast that spell)?"
)


def _play_window_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if bool(m.group("pre")) == bool(m.group("post")):
        return None  # exactly one window phrase
    params: dict = {}
    if m.group("verb") == "cast":
        params["only_spells"] = True
    if m.group("wild"):
        params["mana_wildcard"] = "color"
    return [EffectSpec("grant_play_window_previous_exiled", params)]


#: PAR-167: an exile clause plus the casting window it opens ("Exile the top 4 cards of your library. Until end of turn,
#: you may cast noncreature spells from among those cards without paying their mana costs."). The whole pair is one
#: row so the pronoun can only name what the first sentence exiled; `casting_window.py` owns every axis of the window.
_EXILE_CAST_WINDOW_RE = compile_clause(r"(?:exile|mill|target (?:player|opponent) mills|each opponent mills) [^.]+\.\s+[^.]+")


def _exile_cast_window(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return parse_exile_cast_window(m.group(0), match_clause)


#: PAR-163 (Moonstone, Harsh Mistress): the discard trigger's "exile that card from your graveyard. If you do,
#: until the end of your next turn, you may play that card." -- `ExileTriggeringDiscardMayPlayThisTurnEffect` with its
#: RULE 611.2 next-turn window (its hand-authored "this turn" siblings, Containment Construct, keep the default).
_EXILE_DISCARD_PLAY_NEXT_TURN_RE = compile_clause(
    r"exile that card from your graveyard\. if you do, "
    rf"(?:{_PLAY_WINDOW_NEXT_TURN}, you may play that card|you may play that card {_PLAY_WINDOW_NEXT_TURN})"
)


def _exile_discard_play_next_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile_triggering_discard_may_play_this_turn", {"same_turn_only": False})]


#: PAR-163 (Mosswood Dreadknight): "When ~ dies, you may cast it from your graveyard as an Adventure until the end of
#: your next turn." (RULE 715.3a) -- `GrantSelfAdventureCastFromGraveyardEffect`, first built for a hand-authored card.
_SELF_ADVENTURE_FROM_GRAVEYARD_RE = compile_clause(
    rf"cast it from your graveyard as an adventure {_PLAY_WINDOW_NEXT_TURN}"
)


def _self_adventure_from_graveyard(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_self_adventure_cast_from_graveyard", {})]


#: "Draw N cards and reveal them. You may cast one of them without paying
#: its mana cost." (PAR-13, Dungeon of the Mad Mage's own "Mad Wizard's
#: Lair") — `DrawRevealCastOneFreeEffect`'s only oracle-text route; reveal
#: itself carries no mechanical weight to model (RULE 701.28).
_DRAW_REVEAL_CAST_FREE_RE = compile_clause(
    r"draw (?P<n>\d+) cards? and reveal (?:them|it)\. you may cast (?:\d+|a) of "
    r"them without paying its mana cost"
)


def _draw_reveal_cast_free(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw_reveal_cast_one_free", {"count": int(m.group("n"))})]


#: RULE 601.2f-adjacent "Expertise" cycle template (MEC-20) — "You may cast
#: a spell with mana value N or less from your hand without paying its mana
#: cost." (Kari Zev's/Sram's/Yahenni's/Baral's/Rishkar's Expertise), its
#: ``{X}``-scaled sibling ("…mana value x or less…", Electrodominance —
#: ``COUNT_X``/``count_or_x_of``, resolved against the spell's own announced
#: {X} by `RulesEngine._substitute_x`'s existing ``criteria`` walk, no new
#: wiring needed), and the trailing "where x is the number of attacking
#: creatures" tail (Epistolary Librarian's own triggered-ability body, which
#: has no cast {X} of its own to substitute — a board-read count instead,
#: `continuous.count_selector`'s existing ``"attacking_creatures"`` entry).
#: `FreeCastFromHandEffect` (`game/effects/core.py`) is a resolve-time *choice*
#: among the controller's own hand, not a target — none of these print
#: "target". The leading "you may " is optional here (not required) since
#: `segmenter.peel_optional` already strips it before `parse_effect_body`
#: ever reaches a handler, for both the bare spell-effect and the
#: triggered-ability wrapper paths — MEC-18's own "the generic 'you may '
#: stripper eats the clause first" lesson, guarded against directly rather
#: than by exempting `peel_optional` (nothing else about this clause is
#: sensitive to the optional marker: `spec.optional` is read only by the
#: ``triggered`` binder branch, never ``spell_effect``, and this effect's
#: own `_request_choose_objects(optional=True)` already models the "may").
_FREE_CAST_FROM_HAND_RE = compile_clause(
    # ENG-33 (Great Intelligence's Plan) / ENG-32 (Waterbend "cast a
    # noncreature spell without paying"): the "with mana value N or less"
    # cap and the "noncreature" qualifier are both optional — an uncapped
    # `free_cast_from_hand` offers every nonland hand card.
    # "with mana value N or less" and "from your hand" appear in either
    # order — "…spell with mana value N or less from your hand…" (the
    # Expertise cycle) and "…spell from your hand with mana value N or
    # less…" (Marvo, Deep Operative). Two positions for the cap, read back
    # by `_free_cast_from_hand` as ``n`` or ``n_after``.
    rf"(?:you may )?cast (?:an? (?P<noncreature>noncreature )?spell|(?P<isorc>an instant or sorcery spell))"
    rf"(?: with mana value {COUNT_X} or less)? from your hand"
    rf"(?: with mana value (?P<n_after>a|an|x|\d+) or less)? "
    rf"without paying its mana cost(?P<selector>, where x is the number of attacking creatures)?"
)


def _free_cast_from_hand(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {}
    if m.groupdict().get("noncreature"):
        params["noncreature_only"] = True
    if m.groupdict().get("isorc"):
        # RULE 608.2g: Arcane Endeavor casts it while the spell resolves, not later in the turn.
        params["instant_sorcery_only"] = True
        params["during_resolution"] = True
    cap = m.groupdict().get("n") or m.groupdict().get("n_after")
    if m.group("selector"):
        params["max_mana_value_selector"] = "attacking_creatures"
    elif cap is not None:
        params["max_mana_value"] = count_or_x_of(cap)
    return [EffectSpec("free_cast_from_hand", params)]

#: PAR-167: "cast `<a / any number of>` `<type>` spell(s) from your hand/graveyard [with mana value `<cap>`] without
#: paying its mana cost" over every cap and filter axis (`casting_window.py`); the original Expertise row above owns the
#: plain hand wording and is tried first.
_FREE_CAST_ZONE_RE = compile_clause(r"(?:you may )?cast [^.]+? without paying (?:its|their) mana costs?(?:, where x is [^.]+)?\.?")


def _free_cast_zone(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return parse_free_cast_zone(m.group(0), parse_amount_phrase)

#: PAR-167: the turn-long graveyard play window ("Until end of turn, you may play lands and cast spells from your
#: graveyard.") and the turn-long exile replacement beside it (Gaea's Will, Magus of the Will).
_GRAVEYARD_PLAY_WINDOW_ROW_RE = compile_clause(
    r"(?:until end of turn, )?(?:you may )?play lands and cast spells from your graveyard[^.]*"
    r"(?:\.\s*if a card would be put into your graveyard from anywhere this turn, exile (?:that card|it) instead)?\.?"
    r"|if a card would be put into your graveyard from anywhere this turn, exile (?:that card|it) instead\.?"
    r"|(?:until end of turn, )?(?:you may )?cast [^.]+ spells from (?:your|any) graveyard[^.]*"
    r"(?:\.\s*if a spell cast this way would be put into a graveyard, exile it instead)?\.?"
)

#: PAR-167: "[Target opponent] exile[s] cards from the top of [your/their] library until [you/they] exile a `<kind>` card.
#: [Until end of turn,] you may cast that card without paying its mana cost." (Nico Minoru, Wanda's Vision, Stolen Goods).
_DIG_CAST_FREE_RE = compile_clause(r"(?:target opponent exiles|exile) cards from the top of (?:your|their) library until [^.]+\.\s+[^.]+")

#: PAR-167: "Exile [up to one] target `<card>` from a graveyard [and copy it | . Copy it]. You may cast the copy [without
#: paying its mana cost]." -- the exile clause is any one this table already reads, or the filtered graveyard form
#: below ("with mana value N or less", a colour word, the "nonland" type), so the card filter and the origin graveyard
#: are the same axes the targeted cast window uses.
_EXILE_COPY_CAST_RE = compile_clause(r"exile [^.]+?(?: and copy (?:it|that card)|\.\s+copy (?:it|that card))(?:\.\s+|, then )[^.]+")


def _exile_graveyard_clause(text: str) -> Optional[list[EffectSpec]]:
    specs = match_clause(text)
    if specs:
        return specs
    m = _EXILE_GRAVEYARD_FILTERED_RE.fullmatch(text.strip())
    if m is None:
        return None
    type_word = m.group("type")
    kind = graveyard_target_kind(None if type_word == "nonland" else type_word, m.group("scope"))
    if kind is None:
        return None
    if type_word == "nonland":
        kind = kind.removesuffix("_card") + "_nonland_card"
    params: dict = {"target_kind": kind}
    if m.group("upto"):
        params["optional"] = True
    if m.group("n"):
        params["max_mana_value"] = int(m.group("n"))
    if m.group("color"):
        params["colors"] = [CAST_WINDOW_COLORS[m.group("color").lower()]]
    return [EffectSpec("exile", params)]


def _exile_copy_cast(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return parse_exile_copy_cast(m.group(0), _exile_graveyard_clause)


def _dig_cast_free(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return parse_dig_cast_free(m.group(0))


def _graveyard_play_window(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return parse_graveyard_play_window(m.group(0))


#: PAR-118: the shared clause "exile a card from your hand with a number of time counters on it equal to its mana
#: value" (the counters are always the mana value on all three printed cards) plus whichever rider follows:
#:
#: * ``suspend``  — "If it doesn't have suspend, it gains suspend." (The Eleventh Doctor);
#: * ``opponent`` — "Then target opponent does the same. Cards exiled this way that don't have suspend gain suspend."
#:   (The Wedding of River Song; the grant covers both players' cards);
#: * ``alaundo``  — "… and put a number of time counters on it equal to its mana value. It gains "When the last time
#:   counter is removed from this card, if it's exiled, you may cast it without paying its mana cost. If you cast a
#:   creature spell this way, it gains haste until end of turn." Then remove a time counter from each other card you
#:   own in exile." The quoted cast ability is granted for that exact exile visit;
#:   counter removal queues it separately from other removal payoffs.
_EXILE_HAND_TIME_RE = compile_clause(
    # Both multi-sentence cards open "Draw N card(s), then …": the draw rides in front so the window that sees the
    # later sentences (the sentence split would otherwise strand them) starts at the draw.
    rf"(?:draw {COUNT} cards?, then )?"
    r"(?P<may>you may )?exile an? (?P<nonland>nonland )?card from your hand"
    r"(?:"
    r" with a number of time counters on it equal to its mana value"
    r"(?:\. (?P<suspend>if it doesn't have suspend, it gains suspend)"
    r"|\. then (?P<opponent>target opponent does the same)\. "
    r"cards exiled this way that don't have suspend gain suspend)?"
    r"|"
    r" and put a number of time counters on it equal to its mana value\. "
    r"it gains \"when the last time counter is removed from this card, if it's exiled, "
    r"you may cast it without paying its mana cost\. "
    r"if you cast a creature spell this way, it gains haste until end of turn\.\" "
    r"then (?P<alaundo>remove a time counter from each other card you own in exile)"
    r")\.?"
)


def _exile_hand_time_counters(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict[str, Any] = {"time_counters_from_mana_value": True}
    draw = [EffectSpec("draw", {"count": count_of(m.group("n"))})] if m.group("n") else []
    if m.group("may"):
        params["optional"] = True
    if m.group("nonland"):
        params["nonland"] = True
    if m.group("suspend"):
        params["grant_suspend"] = True
    if m.group("opponent"):
        params.update(grant_suspend=True, then_opponent=True)
    if m.group("alaundo"):
        params.update(sweep_time_counters=True, grant_suspend_cast=True)
    return draw + [EffectSpec("exile_hand_card", params)]


#: ENG-33: "you may put a `<type>` card from your hand onto the battlefield"
#: (Dr. Eggman, Sonic's Nemesis — a villainous-choice option body).
#: `PutFromHandOntoBattlefieldEffect` already exists (Tooth and Nail); this
#: reaches it from a resolving effect. Every named type/subtype must be a
#: recognized word (fail-closed) — a bare `card_query` substring test would
#: silently match nothing on a typo.
_PUT_FROM_HAND_TYPE_WORDS: frozenset[str] = frozenset(PERMANENT_TYPE_WORDS) | {
    "construct", "robot", "vehicle", "equipment", "aura", "clue",
    "food", "treasure",
}
_PUT_FROM_HAND_RE = compile_clause(
    r"(?:you may )?put an? (?P<types>[a-z, ]+?) card"
    # RULE 601.2c-style card filter between "card" and "from your hand":
    # "with lesser power" (Shadowfax) — vs this effect's source; "with mana
    # value N or less" (fixed) / "with mana value x or less" (dynamic, needs
    # the trailing ", where X is …" clause below to resolve X).
    r"(?P<filt> with lesser power| with mana value (?P<mv>\d+) or less| with mana value x or less)?"
    r" from your hand(?P<or_gy> or graveyard)? onto the battlefield"
    # RULE 508.4 "…tapped and attacking" (Preeminent Captain, Kaalia of the
    # Vast) → `PutFromHandOntoBattlefieldEffect.attacking`; or the plain
    # "…tapped" entry (Dread Tiller, Arboreal Grazer, Cultivator Colossus).
    # Longer alternative first so "tapped and attacking" isn't mis-split.
    r"(?:(?P<tapped_attacking> tapped and attacking)|(?P<tapped_plain> tapped))?"
    # The trailing "that player"/"that opponent" (Kaalia, The Vast Scrier)
    # names the defender the source is already attacking — `put_onto_
    # battlefield_attacking` derives that from the other attackers, so the
    # phrase is consumed, not re-modeled.
    r"(?P<atk_defender> that (?:player|opponent))?"
    r"(?P<xdef>, where x is the number of attacking creatures you control)?"
    # PAR-152: "…with mana value X or less …, where X is ~'s power" (Paladin Elizabeth Taggerdy).
    rf"(?P<xpow>, where x is {re.escape(SELF)}'?s power)?"
    # The Vast Scrier's two trailing sentences: (1) an explicit instruction
    # that the placed creature's own "whenever ~ attacks" triggers fire —
    # unlike ordinary RULE 508.4 entry, this is *not* a no-op; (2) "if you don't put a card … this way,
    # <body>." → `miss_effect_specs` (via `_request_search`'s
    # ``then_specs_if_none``).
    r"(?:\. (?P<trigger_attacks>if it has any \"whenever ~ attacks\" triggers,? those trigger))?"
    r"(?:\. if you don'?t put a card onto the battlefield this way, (?P<elsebody>.+?))?"
)

#: The main card types a "put a … card from your hand" clause can name; a
#: two-word segment ending in one of these ("dragon creature") makes the
#: leading word a *subtype* filter.
_PUT_FROM_HAND_MAIN_TYPES: frozenset[str] = frozenset(
    {"creature", "artifact", "enchantment", "land", "planeswalker", "permanent"}
)


def _is_creature_subtype_word(word: str) -> bool:

    return word in SUBTYPES and word not in NONCREATURE_SUBTYPE_WORDS


def _put_from_hand(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    segments = [
        s.strip() for s in re.split(r",\s*or\s+|,\s*|\s+or\s+", m.group("types"))
        if s.strip()
    ]
    if not segments:
        return None
    last = segments[-1].split()
    if (
        len(last) == 2
        and last[1] in _PUT_FROM_HAND_MAIN_TYPES
        and all(len(s.split()) == 1 for s in segments[:-1])
    ):
        # "soldier creature card" / "angel, demon, or dragon creature card"
        # — the leading words are creature subtypes (an OR), the trailing
        # main type is implied by them. `card_query` treats a ``type`` list
        # as an OR substring match, which is exactly a subtype filter here.
        qualifiers = segments[:-1] + [last[0]]
        colours = [resolve_color_word(w) for w in qualifiers]
        if last[1] == "creature" and qualifiers in (["artifact"], ["enchantment"], ["land"]):
            # PAR-152: "an artifact creature card" (Ultra Magnus) is both types, not either-or.
            criteria = {"all_types": [qualifiers[0], "creature"]}
        elif all(colours):
            # "blue or red creature card" (Mindwrack Liege) — a colour
            # filter, not a subtype: nothing's type line contains "blue".
            criteria: dict = {"color": colours if len(colours) > 1 else colours[0]}
        elif any(
            w in ("multicolored", "monocolored", "colorless", "historic",
                  "nonlegendary", "nontoken", "nonbasic")
            for w in qualifiers
        ):
            return None  # a derived quality with no clean `card_query` key — fail closed
        else:
            criteria = {"type": qualifiers if len(qualifiers) > 1 else qualifiers[0]}
    elif all(s in _PUT_FROM_HAND_TYPE_WORDS for s in segments):
        criteria = {"type": segments if len(segments) > 1 else segments[0]}
    elif len(segments) == 1 and len(last) == 1 and _is_creature_subtype_word(last[0]):
        # PAR-152: "a Vampire card from your hand" (Strefan) — a bare creature subtype.
        criteria = {"type": last[0]}
    else:
        return None
    filt = (m.groupdict().get("filt") or "").strip()
    if filt == "with lesser power":
        params_extra: dict = {"power_less_than_source": True}
    elif m.groupdict().get("mv"):
        criteria = {**criteria, "max_mana_value": int(m.group("mv"))}
        params_extra = {}
    elif filt == "with mana value x or less":
        if m.groupdict().get("xpow"):
            params_extra = {"max_mana_value_selector": "source_power"}
        elif m.groupdict().get("xdef"):
            params_extra = {"max_mana_value_selector": "attacking_creatures_you_control"}
        else:
            return None  # unresolvable X → fail closed
    else:
        params_extra = {}
    params: dict = {"criteria": criteria, "count": 1, **params_extra}
    if m.groupdict().get("tapped_attacking"):
        params["tapped"] = True
        params["attacking"] = True
    elif m.groupdict().get("tapped_plain"):
        params["tapped"] = True
    if m.groupdict().get("or_gy"):
        params["zones"] = ["hand", "graveyard"]
    if m.groupdict().get("trigger_attacks"):
        params["trigger_attacks"] = True
    elsebody = (m.groupdict().get("elsebody") or "").strip().rstrip(".")
    if elsebody:

        else_specs = parse_effect_body(elsebody)
        if else_specs is None:
            return None  # else-branch didn't parse — fail closed
        params["miss_effect_specs"] = [s.to_dict() for s in else_specs]
    return [EffectSpec("put_from_hand_onto_battlefield", params)]


#: MEC-73: Sneak Attack's hand cheat with the haste/delayed-sacrifice tail.
#: The optional subtype is deliberately limited to one word: it is a creature
#: subtype in the printed ``<Subtype> creature card`` grammar, not an
#: arbitrary card-query string. The whole sequence must be one effect because
#: the chosen hand card is only known after the interactive choice resolves.
_CHEAT_CREATURE_FROM_HAND_RE = compile_clause(
    r"(?:you may )?put an? (?:(?P<subtype>[a-z]+) )?creature card from your hand onto the battlefield\. "
    r"that creature gains haste until end of turn\. "
    r"sacrifice (?:it|that creature|the creature) at the beginning of the next end step"
)


def _cheat_creature_from_hand(m: re.Match[str]) -> list[EffectSpec]:
    params: dict[str, object] = {}
    if m.group("subtype"):
        params["subtypes"] = [m.group("subtype").capitalize()]
    return [EffectSpec("cheat_creature_from_hand", params)]


#: RULE 119/701.8's "Target opponent/player reveals their hand. You choose
#: a `<filter>` card from it[ with mana value N or less]. That player
#: discards that card[. You lose N life]." (Duress/Thoughtseize/Coercion/
#: Distress/Inquisition of Kozilek-shaped — one of the most repeated hand-
#: disruption templates in the cache). Deliberately just the five real
#: filter phrasings found so far (bare/nonland/noncreature+nonland/
#: creature-or-planeswalker/artifact-or-creature) rather than a fully
#: general card-type grammar, plus the two real trailing riders (MEC-43
#: round 2: a mana-value cap on the chosen card — Inquisition of Kozilek —
#: and the caster's own life loss — Thoughtseize) — "or a card from their
#: graveyard" and any other rider stays unclaimed rather than guessed at.
_HAND_DISRUPTION_FILTERS: dict[str, dict] = {
    "a card": {},
    "a nonland card": {"exclude_land": True},
    "a noncreature, nonland card": {"exclude_land": True, "exclude_creature": True},
    "a creature or planeswalker card": {"card_types": ["creature", "planeswalker"]},
    "an artifact or creature card": {"card_types": ["artifact", "creature"]},
}
# RULE 701.20 / 701.9: reveal/look, select a filtered card, then act on it.
# The type-list grammar composes all supported printed card types rather than
# growing one handler per Duress/Despise/Collective Brutality variant.
_HAND_DISRUPTION_RE = compile_clause(
    r"(?:(?P<target>target opponent|target player) reveals their hand"
    r"|look at (?P<look>target opponent|target player)'s hand)"
    r"(?:\. |, | and )you (?P<may>may )?choose (?P<filter>an? [a-z ,]*?card) "
    r"from it(?: with mana value (?P<mv>\d+) or (?P<cmp>less|greater))?"
    r"(?P<graveyard> or a card from their graveyard)?"
    r"(?:\. |, then | and )(?P<action>that player discards that card|exile (?:that card|it))"
    r"(?:\. you lose (?P<life>\d+) life)?"
)


def _hand_disruption_discard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    target = m.group("target") or m.group("look")
    if resolve_target_kind(target) != "player":
        return None
    filt = m.group("filter")
    if filt in _HAND_DISRUPTION_FILTERS:
        filters = _HAND_DISRUPTION_FILTERS[filt]
    else:
        phrase = parse_object_phrase(re.sub(r"^an? ", "", filt))
        if phrase is None or phrase[1] is not None:
            return None
        filters = {"card_filter": phrase[0]}
    params: dict = {"target_kind": "opponent" if target == "target opponent" else "player", **filters}
    if m.group("mv"):
        params["min_mana_value" if m.group("cmp") == "greater" else "max_mana_value"] = int(m.group("mv"))
    if m.group("graveyard"):
        params["include_graveyard"] = True
    if m.group("action").startswith("exile"):
        params["destination"] = "exile"
    if m.group("may"):
        params["optional"] = True
    if m.group("look"):
        params["reveal"] = False
    specs = [EffectSpec("reveal_hand_choose_discard", params)]
    if m.group("life"):
        specs.append(EffectSpec("lose_life", {"amount": int(m.group("life"))}))
    return specs


#: "Target player reveals their hand. You choose a nonland card from it. That player puts that card into their library
#: third from the top." (Lost Hours) and "Look at target player's hand and choose `<N>` cards from it. `<tail>`" (Mind
#: Warp / Extortion / Abandon Hope discard them, Agonizing / Painful Memories put them on top of the library): the same
#: `reveal_hand_choose_discard` effect with a pick count (`count`, `up_to`) and a `destination`. Looking at a hand is
#: the same zero-effect visibility step as revealing it.
_HAND_PICK_FILTERS: dict[str, dict] = {"a nonland card": _HAND_DISRUPTION_FILTERS["a nonland card"], "a card": {}}
_HAND_PICK_TAILS: dict[str, str] = {
    "that player discards (?:that card|those cards)": "discard",
    "put (?:that card|them) on top of that player's library(?: in any order)?": "library_top",
    "that player puts that card into their library third from the top": "library_third",
}
_HAND_PICK_RE = compile_clause(
    r"(?:(?P<reveal>target opponent|target player) reveals their hand\. you choose (?P<rfilter>a nonland card) from it"
    r"|look at (?P<look>target opponent|target player)'s hand and choose "
    r"(?:(?P<upto>up to )?(?P<n>\d+|x) cards?|(?P<a>a card)) from it)\. "
    rf"(?P<tail>{'|'.join(_HAND_PICK_TAILS)})"
)


def _hand_pick(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    target = m.group("reveal") or m.group("look")
    if resolve_target_kind(target) != "player":
        return None
    destination = next(dest for pattern, dest in _HAND_PICK_TAILS.items() if re.fullmatch(pattern, m.group("tail")))
    if m.group("reveal") and destination != "library_third":
        return None  # the plain reveal-and-discard form is `hand_disruption_discard`'s
    params: dict = {"target_kind": "opponent" if target == "target opponent" else "player"}
    if m.group("look"):
        params["reveal"] = False
    if m.group("rfilter"):
        params.update(_HAND_PICK_FILTERS[m.group("rfilter")])
    if m.group("n"):
        params["count"] = "x" if m.group("n") == "x" else int(m.group("n"))
    if m.group("upto"):
        params["up_to"] = True
    if destination != "discard":
        params["destination"] = destination
    return [EffectSpec("reveal_hand_choose_discard", params)]


#: RULE 701.20's "defending player reveals the top card of their library.
#: If it's a land card, that player puts it into their hand." (Goblin
#: Guide-shaped) — a triggered-ability body (the "whenever ~ attacks,"
#: prefix that opens it is recognized separately, by the segmenter's own
#: trigger-condition grammar). Deliberately just the "defending player"
#: subject and the three real card-type words found so far.
_REVEAL_TOP_CONDITIONAL_RE = compile_clause(
    r"defending player reveals the top card of their library\. "
    r"if it'?s an? (?P<type>land|creature|artifact) card, that player puts it into their hand"
)


def _reveal_top_conditional(m: re.Match[str]) -> list[EffectSpec]:
    # ENG-37 B5: a `seq` of `reveal_top` (stash the top card as the
    # `revealed` referent) then an `if_else` on its card type — the engine-
    # side `reveal_top_conditional_to_hand` fusion is retired.
    return [EffectSpec("seq", {"effects": [
        {"type": "reveal_top", "params": {"whose": "defending_player"}},
        {"type": "if_else", "params": {
            "condition": {
                "kind": "is_card_type", "of": "revealed",
                "card_type": m.group("type"),
            },
            "then": [{
                "type": "put_revealed_card",
                "params": {"destination": "hand", "whose": "defending_player"},
            }],
            "else": [],
        }},
    ]})]


#: RULE 701.20 + 121.4 (PAR-215): "reveal the top card of your library and put that card into your hand" -- the
#: reveal stashes the card as `GameContext.revealed_card` (a later "its mana value" measures it), and the put is
#: not a draw. Two flat specs, so the sequencer sees `put_revealed_card` as the clause's last effect.
_REVEAL_TOP_TAKE_RE = compile_clause(
    r"reveal the top card of your library and put (?:that card|it) into your hand"
)


def _reveal_top_take(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("reveal_top", {"whose": "you"}),
        EffectSpec("put_revealed_card", {"destination": "hand"}),
    ]


#: PAR-152 (Zareth San): "put this card from your hand onto the battlefield [tapped and attacking]." — the card's own
#: activated ability from hand (`bind_ability` infers the hand zone from the effect), RULE 508.4 for the combat entry.
_PUT_SELF_FROM_HAND_RE = compile_clause(
    r"put (?:this card|~) from your hand onto the battlefield(?P<tapped> tapped)?(?P<atk> and attacking)?"
)


def _put_self_from_hand(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("atk") and not m.group("tapped"):
        return None
    params: dict = {}
    if m.group("tapped"):
        params["tapped"] = True
    if m.group("atk"):
        params["attacking"] = True
    return [EffectSpec("put_self_onto_battlefield_from_hand", params)]


#: PAR-152: "look at defending player's hand." (Zara, Renegade Recruiter) — the informational look
#: (`LookAtHandEffect`), no target: the player the source attacks.
_LOOK_DEFENDING_HAND_RE = compile_clause(r"look at defending player'?s hand")

#: PAR-152 / RULE 508.4 + 110.2: "you may put a `<type>` card from it onto the battlefield under your control tapped
#: and attacking that player or a planeswalker they control." — "it" is the hand just looked at (the defending
#: player's), so this row is only offered right after `_LOOK_DEFENDING_HAND_RE`'s clause.
_PUT_FROM_DEFENDING_HAND_RE = compile_clause(
    r"(?:you may )?put an? (?P<type>creature|artifact|enchantment|planeswalker|land|permanent) card from it onto the "
    r"battlefield under your control tapped and attacking that player or a planeswalker they control"
)


def _put_from_defending_hand(m: re.Match[str]) -> list[EffectSpec]:
    criteria = {} if m.group("type") == "permanent" else {"type": m.group("type")}
    return [EffectSpec("put_from_defending_hand", {"criteria": criteria, "tapped": True, "attacking": True})]


#: RULE 701.20 + 508.4: "reveal the top card of your library. If it's a `<type>` card, put it onto the battlefield
#: [tapped [and attacking [defending player or a planeswalker they control]]]. Otherwise, put that card into your
#: hand. [When you put a `<type>` card onto the battlefield this way, it fights ~.]" (Hans Eriksson; Coiling Oracle's
#: plain shape). The reveal is `reveal_top`'s referent, the branch an `if_else` on its type, both placements
#: `put_revealed_card`; the fight is a RULE 603.12 reflexive trigger fired by the placement (`fights_source`).
_REVEAL_TOP_PUT_OR_HAND_RE = compile_clause(
    r"reveal the top card of your library\. if it'?s an? (?P<type>land|creature|artifact|enchantment|planeswalker) card, "
    r"put it onto the battlefield(?P<tapped> tapped)?(?P<atk> and attacking(?: defending player or a planeswalker they control)?)?\. "
    r"otherwise, put (?:that card|it) into your hand"
    rf"(?:\. when you put an? (?P=type) card onto the battlefield this way, it fights {re.escape(SELF)})?"
)


def _reveal_top_put_or_hand(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    groups = m.groupdict()
    if groups["atk"] and not groups["tapped"]:
        return None  # "attacking" on its own isn't a printed spelling
    if not groups["atk"] and "fights" not in m.group(0):
        return None  # the plain shape (Coiling Oracle) stays with `reveal_top_branch`'s inspect pick (land entry rules)
    destination = "battlefield_attacking" if groups["atk"] else (
        "battlefield_tapped" if groups["tapped"] else "battlefield"
    )
    put: dict = {"destination": destination}
    if "fights" in m.group(0):
        put["fights_source"] = True
    return [EffectSpec("seq", {"effects": [
        {"type": "reveal_top", "params": {"whose": "you"}},
        {"type": "if_else", "params": {
            "condition": {"kind": "is_card_type", "of": "revealed", "card_type": groups["type"]},
            "then": [{"type": "put_revealed_card", "params": put}],
            "else": [{"type": "put_revealed_card", "params": {"destination": "hand"}}],
        }},
    ]})]


#: "create an X/X blue Shark creature token with flying, where X is that
#: spell's mana value." (Shark Typhoon's spell-cast trigger) — an X/X token
#: sized off the firing `SPELL_CAST` event's own ``mana_value`` field
#: (`CreateTokenEffect.pt_from_trigger_event`), read fresh at resolve time.
_MANA_VALUE_XX_TOKEN_RE = compile_clause(
    r"create an? x/x (?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z]+(?:, [a-z]+)*(?: and [a-z]+)?))?, "
    r"where x is that spell'?s mana value"
)


def _mana_value_xx_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    return [EffectSpec("create_token", {**params, "pt_from_trigger_event": "mana_value"})]


#: The RULE 702.28c Cycling-cost sibling — "create an X/X blue Shark
#: creature token with flying." (Shark Typhoon's own "When you cycle this
#: card" bonus) — X here is the Cycling cost's own paid {X}
#: (`GameObject.cycling_x_paid`), substituted through the same ``"x"``
#: sentinel/`_substitute_x` idiom (`"cycling_x"`) every other X-scaled
#: effect uses, just a different source field.
CYCLING_XX_TOKEN_RE = compile_clause(
    r"create an? x/x (?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z]+(?:, [a-z]+)*(?: and [a-z]+)?))?"
)


def cycling_xx_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    return [EffectSpec("create_token", {**params, "power": "cycling_x", "toughness": "cycling_x"})]


#: The plainer sibling of `_BLINK_NON_SUBTYPE_RE`, with no subtype
#: exclusion — "exile [up to N] [another] target creature/[nonland]
#: permanent you control, then return that card/it to the battlefield
#: under your/its owner's control" (Felidar Guardian/Emiel the Blessed/
#: Displacer Kitten-shaped). "another" needs no special handling: every
#: ``*_you_control`` `legal_targets` branch already excludes the source
#: object regardless (`o is not source`), so a plain and an "another"-
#: qualified target kind resolve identically. "up to N" threads through
#: to `BlinkEffect`'s own ``optional``/``count_max`` (MEC-12) rather than
#: the yes/no "you may" a *mandatory*-single-target blink relies on
#: (stripped upstream, same as `_blink_non_subtype` needs no "you may" in
#: its own pattern either). "other" (MEC-79's The Mind Stone — "up to one
#: **other** target nonland permanent you control") is the same free case as
#: "another": the source-excluding ``*_you_control`` `legal_targets` branch
#: makes plain / "another" / "other" resolve identically.
#: Plural targets (Displace / Illusionist's Stratagem "exile up to 2 target creatures you control, then return those
#: cards …", Brago "any number of target nonland permanents", Gandalf, Shadow's Foe "up to 3 target lands … tapped")
#: ride the same row: the count is the target count, "those cards"/"them" the referent, "under their owner's
#: control" the owner form.
_BLINK_PLAIN_RE = compile_clause(
    r"exile (?:(?P<any_number>any number of )|up to (?P<up_to>one|[0-9]+) |(?P<exactly>[2-9]) )?"
    r"(?:(?:an)?other )?target "
    # "…target **tapped** creature you control…" (Far Traveler's granted
    # end-step blink) — a state filter on the target, `BlinkEffect.
    # creature_filter` (the same param `_blink_non_subtype` uses for its
    # subtype exclusion).
    r"(?P<tapped>tapped )?(?P<kind>nonland permanents?|permanents?|creatures?|lands?) you (?:control|own), "
    # PAR-152 (The Neutrinos): "…then return it to the battlefield under your control tapped **and attacking**"
    # (RULE 508.4). "you own" is read as "you control" (a documented simplification: a creature you own but an
    # opponent controls is not offered).
    r"then return (?:that card|it|those cards|them) to the battlefield(?P<enters_tapped> tapped)?(?P<enters_atk> and attacking)? "
    r"under (?P<who>your|its owner'?s|their owners?'?s?) control(?P<tail_ta> tapped and attacking)?"
)
#: How many a plural blink target phrase may name when it says "any number" (the engine's own multi-target cap).
_BLINK_ANY_NUMBER_CAP = 10


def _blink_plain(m: re.Match[str]) -> list[EffectSpec]:
    kind_word = m.group("kind").rstrip("s") if m.group("kind") != "lands" else "land"
    target_kind = {
        "creature": "creature_you_control",
        "permanent": "permanent_you_control",
        "nonland permanent": "nonland_permanent_you_control",
        "land": "land_you_control",
    }[kind_word]
    params: dict = {"target_kind": target_kind}
    if m.group("who") == "your":
        params["under_your_control"] = True
    if m.group("tapped"):
        params["creature_filter"] = {"tapped": True}
    if m.group("enters_tapped"):
        params["tapped"] = True
    if m.group("enters_atk") or m.group("tail_ta"):
        if not (m.group("enters_tapped") or m.group("tail_ta")):
            return None
        params["tapped"] = True
        params["attacking"] = True
    up_to = m.group("up_to")
    if m.group("any_number"):
        params["optional"] = True
        params["target_count_max"] = _BLINK_ANY_NUMBER_CAP
    elif up_to:
        params["optional"] = True
        params["target_count_max"] = 1 if up_to == "one" else int(up_to)
    elif m.group("exactly"):
        params["target_count"] = int(m.group("exactly"))
    return [EffectSpec("blink", params)]


def _discard(m: re.Match[str]) -> list[EffectSpec]:
    # "you discard"/bare "discard" is the controller (untargeted); "target
    # player/opponent discards" is a real RULE 115 target; "each player/
    # opponent discards" is the untargeted mass form (RULE 601.2c). Mirrors
    # `_gain_life`'s ``who``-group treatment — and without the target_kind
    # half, "target player discards a card" would have made the *source's
    # controller* discard instead of the chosen player.
    params: dict = {"count": count_of(m.group("n"))}
    who = (m.groupdict().get("who") or "").strip()
    if who == "target player":
        params["target_kind"] = "player"
    elif who == "target opponent":
        # PAR-128: an opponent, not any player — Honden of Night's Reach must
        # not be able to aim the discard at its own controller.
        params["target_kind"] = "opponent"
    elif who == "each player":
        params["scope"] = "each_player"
    elif who == "each opponent":
        params["scope"] = "each_opponent"
    elif who == "defending player":
        # PAR-208 (RULE 508.1b): the player the source attacks, named by the firing combat event's
        # ``defending_player_id``; only an attack / unblocked / blocked head carries it.
        params["player"] = {"of": "trigger_player", "as": "self"}
        params[EVENT_PLAYER_EVENTS_KEY] = _DEFENDING_PLAYER_COMBAT_EVENTS
    if m.groupdict().get("at_random"):
        params["random"] = True
    return [EffectSpec("discard", params)]


#: Combat events that name the attacked player (``defending_player_id``): ATTACKS, ATTACKER_UNBLOCKED (RULE 509.1h),
#: BECOMES_BLOCKED (RULE 509.1).
_DEFENDING_PLAYER_COMBAT_EVENTS = ["ATTACKS", "ATTACKER_UNBLOCKED", "BECOMES_BLOCKED"]


#: "Discard N cards unless you discard a `<quality>` card." (Thirst for Knowledge, Compulsive Research, Alpharael,
#: Arm-Mounted Anchor, …) — `DiscardEffect.unless_discard`: the discarder may give up one matching card instead of N.
#: "that player" is the player an earlier clause chose (``previous_subject``). The quality is "nonland", a card type
#: or a creature/permanent subtype the shared count grammar knows (fail-closed on anything else).
_DISCARD_UNLESS_RE = compile_clause(
    r"(?:then )?(?:(?P<who>you|that player|target player|target opponent|each opponent|each player) )?"
    # PAR-208: "an instant or sorcery card" (a type union) and "a basic land card" (supertype + type).
    rf"discards? {COUNT} cards? unless (?:you|they) discards? (?:a|an) (?P<basic>basic )?(?P<quality>[a-z]+(?: or [a-z]+)?) card"
)
_DISCARD_UNLESS_CARD_TYPES = frozenset({"artifact", "creature", "land", "enchantment", "instant", "sorcery", "planeswalker"})


def _discard_unless(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    quality = m.group("quality").lower()
    if " or " in quality:
        parts = quality.split(" or ")
        if m.group("basic") or not all(part in _DISCARD_UNLESS_CARD_TYPES for part in parts):
            return None
        unless = {"card_types": parts}  # RULE 205.2: either type satisfies it
    elif m.group("basic"):
        if quality != "land":
            return None
        unless = {"card_type": "land", "basic": True}
    elif quality == "nonland":
        unless: dict = {"nonland": True}
    elif quality in _DISCARD_UNLESS_CARD_TYPES:
        unless = {"card_type": quality}
    else:
        selector = subtype_count_selector(f"{quality}s")
        subtype = ((selector or {}).get("filter") or {}).get("subtype")
        if not subtype:
            return None
        unless = {"subtype": subtype}
    who = (m.group("who") or "").strip()
    params: dict = {"count": count_of(m.group("n")), "unless_discard": unless}
    if who == "that player":
        params["previous_subject"] = True
    elif who == "target player":
        params["target_kind"] = "player"
    elif who == "target opponent":
        params["target_kind"] = "opponent"
    elif who == "each player":
        params["scope"] = "each_player"
    elif who == "each opponent":
        params["scope"] = "each_opponent"
    return [EffectSpec("discard", params)]


def _that_many_player_discards(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("discard", {"count": 0, "previous_subject": True,
                                    "count_from_trigger_event": "amount"})]


#: RULE 601.2c mass edict — "each player sacrifices a nontoken creature of
#: their choice" (Accursed Marauder-shaped) / "each player sacrifices N
#: creatures of their choice" (Liliana, Dreadhorde General's own -4) — each
#: player independently choosing their own victim(s) via `effects.
#: SacrificeEffect`'s ``selector="each_player"``/``"each_opponent"``, not a
#: random/rules-picked edict (RulesEngine.sacrifice is a real interactive
#: choice per player).
_SACRIFICE_EDICT_SELECTOR_WORDS: dict[str, str] = {
    "each player": "each_player", "each opponent": "each_opponent",
    # PAR-128: RULE 109.5 "each other player" — every player but the controller,
    # the same reading `_SELECTOR_WORD_MAP` gives it (no team play, RULE 809+).
    "each other player": "each_opponent",
}
_SACRIFICE_EDICT_RE = compile_clause(
    rf"(?P<selector>{'|'.join(_SACRIFICE_EDICT_SELECTOR_WORDS)}) sacrifices? "
    rf"(?P<count>a|an|\d+) (?P<nontoken>nontoken )?"
    rf"(?P<what>{'|'.join(SACRIFICE_EDICT_WHAT_WORDS)})s? of their choice"
)


def _sacrifice_edict(m: re.Match[str]) -> list[EffectSpec]:
    selector = _SACRIFICE_EDICT_SELECTOR_WORDS[m.group("selector")]
    what = SACRIFICE_EDICT_WHAT_WORDS[m.group("what")]
    if m.group("nontoken") and what == "creature":
        what = "nontoken_creature"
    count_word = m.group("count")
    count = 1 if count_word in ("a", "an") else int(count_word)
    return [EffectSpec("sacrifice", {"selector": selector, "what": what, "count": count})]


#: ENG-33: "target player/opponent sacrifices [N] [nontoken] `<what>` [of
#: their choice]" (Diabolic Edict / Chainer's Edict / Dead Drop-shaped, ~21
#: SOLO cards, and the recurring villainous-choice / vote *other* option).
#: A real RULE 115 player target (`SacrificeEffect.target_kind="player"` →
#: reads `targets[0]`), the single-target sibling of `_SACRIFICE_EDICT_RE`'s
#: `each_player`/`each_opponent` mass form.
_TARGET_PLAYER_EDICT_RE = compile_clause(
    rf"target (?P<who>player|opponent) sacrifices? "
    rf"(?P<count>a|an|\d+) (?P<nontoken>nontoken )?"
    rf"(?P<what>{'|'.join(SACRIFICE_EDICT_WHAT_WORDS)})s?(?: of their choice)?"
)


def _target_player_edict(m: re.Match[str]) -> list[EffectSpec]:
    what = SACRIFICE_EDICT_WHAT_WORDS[m.group("what")]
    if m.group("nontoken") and what == "creature":
        what = "nontoken_creature"
    count_word = m.group("count")
    count = 1 if count_word in ("a", "an") else int(count_word)
    return [EffectSpec("sacrifice", {"target_kind": "player", "what": what, "count": count})]


#: "each opponent / target opponent sacrifices a creature with the greatest power among creatures they
#: control" (Crackling Doom, Gix's Command, Szat's Will, Professor Onyx's −3 — the hand-authored original) —
#: `SacrificeEffect.greatest_power` narrows the pick to the tied leaders of that player's own board.
#: …and the same edict by **mana value**, over creatures or creatures and planeswalkers, as a sacrifice or an exile
#: (Blot Out / End of the Hunt "exiles", Flare of Malice / Soul Shatter / Break Under Pressure "sacrifices"). A tie is
#: the chosen player's pick among the tied leaders (`SacrificeEffect.greatest`).
_SACRIFICE_GREATEST_POWER_RE = compile_clause(
    r"(?P<who>each opponent|target opponent|target player) (?P<verb>sacrifices|exiles) a "
    r"(?P<what>creature|creature or planeswalker) "
    r"(?:with the greatest (?P<stat>power|mana value) among (?P<pool>creatures|creatures and planeswalkers) "
    r"(?:they|that player) controls?"
    r"|they control with the greatest (?P<stat2>power|mana value) among (?P<pool2>creatures|creatures and planeswalkers) "
    r"they control"
    r"|they control with the greatest power)"
)


def _sacrifice_greatest_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    groups = m.groupdict()
    stat = groups["stat"] or groups["stat2"] or "power"
    pool = groups["pool"] or groups["pool2"] or ("creatures" if groups["what"] == "creature" else None)
    # The "among …" pool must be the picked type: "creature" ↔ "creatures", "creature or planeswalker" ↔ both.
    if pool is not None and (pool == "creatures") != (groups["what"] == "creature"):
        return None
    if groups["verb"] == "exiles" and m.group("who") == "each opponent":
        return None  # an exile edict printed on every opponent is not a card yet
    params: dict = {
        "what": "creature" if groups["what"] == "creature" else "creature_or_planeswalker", "count": 1,
        "greatest": stat.replace(" ", "_"),
    }
    if groups["verb"] == "exiles":
        params["action"] = "exile"
    if m.group("who") == "each opponent":
        params["selector"] = "each_opponent"
    else:
        params["target_kind"] = "player"
    return [EffectSpec("sacrifice", params)]


#: "Create a number of 1/1 red Warrior creature tokens equal to the number of creatures target player
#: controls." (Will of the Mardu) — the count is taken *as that player* (`effect_amounts`' ``of: "target"``),
#: so the player is announced by a bare `choose_targets` and the token count bound to their creatures.
_TOKENS_PER_TARGET_PLAYER_CREATURE_RE = compile_clause(
    r"create a number of (?P<token>\d+/\d+ [a-z ]+? creature) tokens equal to the number of creatures "
    r"target player controls"
)


def _tokens_per_target_player_creature(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    token = match_clause(f"create a {m.group('token')} token")
    if not token or len(token) != 1 or token[0].type != "create_token":
        return None
    params = {**token[0].params, "count": "$n"}
    return [
        EffectSpec("choose_targets", {"kinds": ["player"]}),
        EffectSpec("bind", {
            "name": "n",
            "amount": {
                "kind": "count_selector", "of": "target",
                "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
            },
            "effects": [{"type": "create_token", "params": params}],
        }),
    ]


#: "Any number of target opponents each sacrifice a creature with the greatest power among creatures that
#: player controls and lose N life." (Will of the Abzan) — the targets are announced by a bare
#: `choose_targets` ("any number" is a RULE 601.2c declinable count), then a loop over exactly those
#: chosen opponents hands each one to a sacrifice and a life loss that read the item as their player.
_ANY_OPPONENTS_SACRIFICE_LOSE_RE = compile_clause(
    r"any number of target opponents each sacrifice a creature with the greatest power among creatures "
    r"that player controls and lose (?P<n>\d+) life"
)


def _any_opponents_sacrifice_lose(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("choose_targets", {
            "kinds": ["opponent"], "count": ANY_NUMBER_TARGET_CAP, "optional": True,
        }),
        EffectSpec("for_each", {"over": {"targets": True}, "effects": [
            {"type": "sacrifice", "params": {
                "what": "creature", "count": 1, "greatest_power": True, "target_kind": "player",
            }},
            {"type": "lose_life", "params": {"amount": int(m.group("n")), "target_kind": "player"}},
        ]}),
    ]


#: "Sacrifice a creature." (Inevitable End's quoted upkeep ability) — an
#: untargeted RULE 701.17 choice made by the ability's controller.  This is
#: an effect body, not the superficially identical activated/casting *cost*;
#: those are peeled by the segmenter before this catalogue is consulted.
_SACRIFICE_CONTROLLER_RE = compile_clause(
    r"sacrifice (?P<count>a|an|\d+) (?P<what>creature|artifact|land|permanent)s?"
)


def _sacrifice_controller(m: re.Match[str]) -> list[EffectSpec]:
    count_word = m.group("count")
    return [EffectSpec("sacrifice", {
        "selector": "controller", "what": m.group("what"),
        "count": 1 if count_word in ("a", "an") else int(count_word),
    })]


#: "Each player loses N life unless they discard a card."/"...unless they
#: sacrifice a creature, artifact, or land of their choice." (PAR-13, Tomb
#: of Annihilation's "Veils of Fear"/"Sandfall Cell" dungeon rooms) — RULE
#: 101.4's APNAP mass "unless", `RulesEngine._request_each_player_pay_or`'s
#: only oracle-text route. Only these two cost phrasings (the ones real
#: cards in the pool actually print for this shape) — a compound sacrifice
#: cost the plain-word `_SACRIFICE_RE`/`ActivationCost.sacrifice` vocabulary
#: doesn't otherwise reach (`costs._SACRIFICE_CREATURE_ARTIFACT_OR_LAND_RE`).
_EACH_PLAYER_LOSE_LIFE_UNLESS_RE = compile_clause(
    r"each (?P<who>player|opponent) loses (?P<n>\d+) life unless they "
    r"(?P<cost>discard a card"
    # "…discard a card **or** sacrifice a creature." (Polygraph Orb) — the
    # OR form; `_each_player_lose_life_unless` sets `sacrifice_or_discard`.
    r"(?P<or_sac> or sacrifice a creature)?"
    r"|sacrifice a creature,\s*(?:an?\s+)?artifact,?\s*(?:or|and)\s*(?:an?\s+)?land of their choice)"
)


def _each_player_lose_life_unless(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "cost": "discard a card" if m.groupdict().get("or_sac") else m.group("cost"),
        "effects": [{
            "type": "lose_life",
            "params": {"amount": int(m.group("n")), "target_kind": "player"},
        }],
    }
    if m.group("who") == "opponent":
        params["scope"] = "each_opponent"
    if m.groupdict().get("or_sac"):
        params["sacrifice_or_discard"] = True
    return [EffectSpec("each_player_pay_or", params)]


#: "Discard a card and sacrifice a creature, an artifact, and a land."
#: (PAR-13, Dungeon of the Mad Mage's "Oubliette" room) — a mandatory
#: compound cost-shaped punishment, not an "unless" choice: one `discard`
#: plus three independent `choose_objects` sacrifices (the payer's own
#: pick within each type, RULE 701.17a — `ChooseObjectsEffect` already
#: resolves with no prompt when there's nothing to choose between, and as a
#: no-op when a type has no legal candidate at all). A standalone whole-
#: clause row rather than relying on the generic `" and "` connector split
#: (`segmenter._CONNECTORS`), since that would also split the sacrifice's
#: own internal "a creature, an artifact, **and** a land" list.
_DISCARD_AND_SACRIFICE_TRIPLE_RE = compile_clause(
    r"discard a card and sacrifice a creature, an artifact, and a land"
)


def _discard_and_sacrifice_triple(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("discard", {"count": 1}),
        EffectSpec("choose_objects", {"action": "sacrifice", "what": "creature", "count": 1}),
        EffectSpec("choose_objects", {"action": "sacrifice", "what": "artifact", "count": 1}),
        EffectSpec("choose_objects", {"action": "sacrifice", "what": "land", "count": 1}),
    ]


#: MEC-27's own residual: the "draw"/"you gain life"/"you lose life" verb
#: families `{DEVOTION}` had never been wired to, unlike the "each player/
#: opponent loses life"/damage/counters/pump/token families above — always
#: the caster/ability's own controller (RULE 118), not a mass "each
#: player/opponent" recipient, so each is its own plain row rather than
#: routed through `_selector_devotion_builder`'s selector-word plumbing.
_DRAW_DEVOTION_RE = compile_clause(rf"draws? x cards?, where x is {DEVOTION}")


def _draw_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [EffectSpec("draw", {"amount_from_count_selector": dsel})]


_GAIN_LIFE_DEVOTION_RE = compile_clause(rf"you gains? x life, where x is {DEVOTION}")


def _gain_life_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [EffectSpec("gain_life", {"count_selector": dsel})]


_LOSE_LIFE_SELF_DEVOTION_RE = compile_clause(rf"you loses? x life, where x is {DEVOTION}")


def _lose_life_self_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [EffectSpec("lose_life", {"amount_from_count_selector": dsel})]


#: The three "draw X and gain/lose X life" combined templates (Champion of
#: Dusk/Graveborn Muse/Minions' Murmurs, Nissa/Camaraderie) — two one-shot
#: effects sharing one `{DEVOTION}` amount, in the printed clause's own
#: order (RULE 608.2b). The repeated "you" (Champion of Dusk's "you draw x
#: cards and **you** lose x life") is optional since some printings drop it
#: (Painful Truths' "you draw x cards and lose x life").
_DRAW_AND_LOSE_LIFE_DEVOTION_RE = compile_clause(
    rf"you draws? x cards? and (?:you )?loses? x life, where x is {DEVOTION}"
)
_GAIN_LIFE_AND_DRAW_DEVOTION_RE = compile_clause(
    rf"you gains? x life and draws? x cards?, where x is {DEVOTION}"
)
#: PAR-31 (Ob Nixilis of the Black Oath's −8 emblem): "You gain X life and
#: draw X cards, where X is the sacrificed creature's power." — the same
#: two-effects-share-one-X shape as the `{DEVOTION}` combos above, but X is
#: `continuous.count_selector`'s ``"sacrificed_cost_power"`` (stamped on the
#: ability source when a "sacrifice a creature" cost is paid — Altar of
#: Dementia's own idiom, MEC-43). Its own row rather than folded into
#: `{DEVOTION}` (a subgrammar reused far too widely to widen for one card).
_GAIN_LIFE_AND_DRAW_SAC_POWER_RE = compile_clause(
    r"you gains? x life and draws? x cards?, "
    r"where x is the sacrificed creature'?s power"
)
def _draw_and_lose_life_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [
        EffectSpec("draw", {"amount_from_count_selector": dsel}),
        EffectSpec("lose_life", {"amount_from_count_selector": dsel}),
    ]


def _gain_life_and_draw_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [
        EffectSpec("gain_life", {"count_selector": dsel}),
        EffectSpec("draw", {"amount_from_count_selector": dsel}),
    ]


def _gain_life_and_draw_sac_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [
        EffectSpec("gain_life", {"count_selector": "sacrificed_cost_power"}),
        EffectSpec("draw", {"amount_from_count_selector": "sacrificed_cost_power"}),
    ]


#: "Each opponent loses X life and you gain X life, where X is `{DEVOTION}`."
#: (Mishra, Claimed by Gix-shaped drain) — a fourth combined shape, distinct
#: from Gray Merchant's "each opponent loses X life... you gain life equal to
#: the life lost this way" (that one's already `_lose_life_selector_devotion`
#: + `_gain_life_lost_this_way`, two independently-claimed clauses): here
#: both halves name the *same* count directly, in one sentence, with no
#: {X}-cost of its own — critically, this must be claimed as **one** clause
#: rather than left to the generic `" and "` connector split
#: (`segmenter._CONNECTORS`), which would otherwise match its first half
#: ("each opponent loses x life") against the plain `_lose_life_selector`
#: row's `COUNT_X` — that row's "x" is RULE 107.3c's *announced-{X}*
#: sentinel, never substituted for a triggered ability with no X cost, so
#: the split would leave a `LoseLifeEffect(amount="x")` that crashes
#: (`"x" <= 0`) instead of reading `{DEVOTION}` at all.
_LOSE_LIFE_AND_GAIN_LIFE_DEVOTION_RE = compile_clause(
    rf"each opponent loses x life and you gains? x life, where x is {DEVOTION}"
)


def _lose_life_and_gain_life_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [
        EffectSpec("lose_life", {"amount_from_count_selector": dsel, "selector": "each_opponent"}),
        EffectSpec("gain_life", {"count_selector": dsel}),
    ]
_EXILE_GRAVEYARD_FILTERED_RE = compile_clause(
    r"exile (?P<upto>up to (?:1|one) )?target (?:(?P<color>white|blue|black|red|green) )?"
    r"(?:(?P<type>nonland|" + GRAVEYARD_TYPE_WORD + r") )?card(?: with mana value (?P<n>\d+) or less)? "
    rf"(?:from|in) (?P<scope>{GRAVEYARD_SCOPE_WORD}) graveyard"
)


#: Covetous Elegy's tail: "then you create a tapped Treasure token for each creature your opponents control" --
#: the count is read live when the (already finished) edict has resolved. Anchored to the controller ("you"/
#: subject-less, the singular verb): the builder always emits the controller as creator, and "your opponents" in the
#: count is relative to the controller, so a third-person "that player creates ..." / "each opponent creates ..."
#: (whose Treasures would go to someone else) stays UNMODELED rather than paying the controller (BUG-6).
_NAMED_TOKEN_PER_OPPONENT_CREATURE_RE = compile_clause(
    rf"(?:then )?(?:you )?create an? (?P<tapped>tapped )?(?P<name>{'|'.join(NAMED_TOKEN_WORDS)}) token "
    r"for each creature your opponents control"
)


def _named_token_per_opponent_creature(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {"token_name": NAMED_TOKEN_WORDS[m.group("name")], "count_selector": "creatures_opponents_control"}
    if m.group("tapped"):
        params["tapped"] = True
    return [EffectSpec("create_token", params)]


#: Single Combat's tail: "Players can't cast creature or planeswalker spells until the end of your next turn." (RULE
#: 601.3a prohibition, RULE 611.2 duration): a floating `cast_prohibition` over every player's spells of those types.
_PLAYERS_CANT_CAST_TYPES_UNTIL_RE = compile_clause(
    r"players can't cast (?P<types>(?:artifact|creature|enchantment|planeswalker|instant|sorcery)"
    r"(?:(?:, | or |, or )(?:artifact|creature|enchantment|planeswalker|instant|sorcery))*) spells "
    r"until the end of your next turn"
)


def _players_cant_cast_types_until(m: re.Match[str]) -> list[EffectSpec]:
    types = re.split(r", or |, | or ", m.group("types"))
    return [EffectSpec("grant_until", {
        "target_kind": None, "duration": "end_of_your_next_turn",
        "static": {"type": "cast_prohibition", "params": {"scope": "all", "spell_types": types}},
    })]


#: Consuming Tide's tail: "then you draw a card for each opponent who has more cards in their hand than you."
#: Anchored to the controller ("you"/subject-less, the singular verb): the builder emits a plain controller `draw`
#: and "than you" in the count is relative to the controller, so a third-person "each opponent / target player /
#: that player draws ..." stays UNMODELED rather than drawing for the wrong player (BUG-7).
_DRAW_PER_OPPONENT_WITH_MORE_CARDS_RE = compile_clause(
    r"(?:then )?(?:you )?draw a card for each opponent who has more cards in their hand than you"
)


def _draw_per_opponent_with_more_cards(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw", {"count": {
        "kind": "count_selector", "selector": "opponents_with_more_cards_in_hand"}})]


ROWS: list[EffectHandler] = [
    # MEC-27: the draw/gain-life/lose-life verb families `{DEVOTION}` had
    # never reached — always the ability's own controller, unlike the mass
    # "each player/opponent loses life" row below.
    EffectHandler("draw_devotion", _DRAW_DEVOTION_RE, _draw_devotion),
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_count_amount_resolver.py (devotion amount grammar).
    EffectHandler("gain_life_devotion", _GAIN_LIFE_DEVOTION_RE, _gain_life_devotion),
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_count_amount_resolver.py (devotion amount grammar).
    EffectHandler("lose_life_self_devotion", _LOSE_LIFE_SELF_DEVOTION_RE, _lose_life_self_devotion),
    EffectHandler(
        "draw_and_lose_life_devotion", _DRAW_AND_LOSE_LIFE_DEVOTION_RE, _draw_and_lose_life_devotion
    ),
    EffectHandler(
        "gain_life_and_draw_devotion", _GAIN_LIFE_AND_DRAW_DEVOTION_RE, _gain_life_and_draw_devotion
    ),
    EffectHandler(
        "gain_life_and_draw_sac_power",
        _GAIN_LIFE_AND_DRAW_SAC_POWER_RE,
        _gain_life_and_draw_sac_power,
    ),
    EffectHandler(
        "lose_life_and_gain_life_devotion",
        _LOSE_LIFE_AND_GAIN_LIFE_DEVOTION_RE,
        _lose_life_and_gain_life_devotion,
    ),
    # "Each creature deals 1 damage to its controller." (Rakdos Charm).
    EffectHandler(
        "damage_each_creature_to_controller",
        _DAMAGE_EACH_CREATURE_TO_CONTROLLER_RE,
        _damage_each_creature_to_controller,
    ),
    # "draw that many cards" (Vilis, Broker of Blood-shaped "that many"
    # trigger-event payoff) — tried before the plain row below since it's a
    # strict superset match on that specific phrase.
    EffectHandler(
        "draw_that_many",
        _DRAW_THAT_MANY_RE,
        _draw_that_many,
    ),
    EffectHandler("sacrifice_greatest_power", _SACRIFICE_GREATEST_POWER_RE, _sacrifice_greatest_power),
    EffectHandler(
        "tokens_per_target_player_creature", _TOKENS_PER_TARGET_PLAYER_CREATURE_RE,
        _tokens_per_target_player_creature,
    ),
    EffectHandler(
        "any_opponents_sacrifice_lose", _ANY_OPPONENTS_SACRIFICE_LOSE_RE, _any_opponents_sacrifice_lose,
    ),
    EffectHandler("wheel", _WHEEL_RE, _wheel),
    EffectHandler("may_wheel", _MAY_WHEEL_RE, _may_wheel),
    EffectHandler("hand_bottom_draw", _HAND_BOTTOM_DRAW_RE, _hand_bottom_draw),
    EffectHandler("discard_up_to_draw", _DISCARD_UP_TO_DRAW_RE,
                  lambda m: [EffectSpec("discard", {
                      "count_max": int(m.group("n")), "then_draw_discarded": True,
                  })]),
    EffectHandler(
        "draw_additional",
        _DRAW_ADDITIONAL_RE,
        lambda m: [EffectSpec("draw", {"count": count_of(m.group("n"))})],
    ),
    # "Target player draws N cards, then discards M cards." (Prismari
    # Command) — tried before the plain `draw` row, whose bare match would
    # leave the trailing "then discards …" dangling with no subject link.
    EffectHandler(
        "target_player_loot",
        _TARGET_PLAYER_LOOT_RE,
        _target_player_loot,
    ),
    # "you and target opponent each draw N cards." — before the generic
    # `draw` row (whose optional `who` group would otherwise claim just the
    # "you" prefix and choke on the "and target opponent" tail).
    EffectHandler(
        "you_and_target_opponent_draw",
        _YOU_AND_TARGET_OPP_DRAW_RE,
        _you_and_target_opponent_draw,
    ),
    # "draw a card" / "draw 3 cards" / "you draw two cards" / "draw X cards" /
    # "target player draws a card" / "each opponent draws a card"
    EffectHandler(
        "draw",
        compile_clause(
            r"(?P<who>you|target player|target opponent|each player|each opponent)?\s*"
            rf"draws? {COUNT_X} cards?"
        ),
        _draw,
    ),
    # "draw a card at the beginning of the next turn's upkeep" (RULE 603.7
    # delayed trigger) — Clairvoyance/Balduvian Rage/Carrier Pigeons-shaped.
    EffectHandler(
        "draw_next_upkeep",
        compile_clause(rf"(?:you )?draws? {COUNT} cards? at the beginning of the next turn's upkeep"),
        _draw_next_upkeep,
    ),
    EffectHandler("recover_milled", _RECOVER_MILLED_RE, _recover_milled),
    EffectHandler("return_own_graveyard", _RETURN_OWN_GRAVEYARD_RE, _return_own_graveyard),  # PAR-208
    EffectHandler("choose_keep_types", _CHOOSE_KEEP_TYPES_RE, _choose_keep_types),
    EffectHandler("choose_keep_count", _CHOOSE_KEEP_COUNT_RE, _choose_keep_count),
    EffectHandler("choose_land_of_each_type", _CHOOSE_LAND_OF_EACH_TYPE_RE, _choose_land_of_each_type),
    EffectHandler("named_token_per_opponent_creature", _NAMED_TOKEN_PER_OPPONENT_CREATURE_RE,
                  _named_token_per_opponent_creature),
    EffectHandler("players_cant_cast_types_until", _PLAYERS_CANT_CAST_TYPES_UNTIL_RE, _players_cant_cast_types_until),
    EffectHandler("draw_per_opponent_with_more_cards", _DRAW_PER_OPPONENT_WITH_MORE_CARDS_RE,
                  _draw_per_opponent_with_more_cards),
    EffectHandler("library_exile", _LIBRARY_EXILE_RE, _library_exile, reading_aware=True),
    EffectHandler(
        "exile_discard_play_next_turn",
        _EXILE_DISCARD_PLAY_NEXT_TURN_RE,
        _exile_discard_play_next_turn,
    ),
    EffectHandler(
        "self_adventure_from_graveyard",
        _SELF_ADVENTURE_FROM_GRAVEYARD_RE,
        _self_adventure_from_graveyard,
    ),
    # PAR-163: the "until the end of your next turn, you may play that card" half after an exile clause.
    EffectHandler(
        "play_window_previous",
        _PLAY_WINDOW_PREVIOUS_RE,
        _play_window_previous,
    ),
    # PAR-167: the exile clause plus a casting window over its pool (cast/play, filter, free or wild mana, window).
    EffectHandler("linked_exile_move", compile_clause(r"(?:return|put) [^.]+exiled with (?:~|it) [^.]+\.?"),
                  lambda m: parse_linked_move(m.group(0))),
    EffectHandler("exile_play_followup", compile_clause(r"(?:[^.]+, )?(?:you may )?(?:cast|play) [^.]+\.?"),
                  lambda m, reading: parse_exile_followup(m.group(0), reading), reading_aware=True),
    EffectHandler("linked_exile_play", compile_clause(r"(?:[^.]+, )?(?:you may )?(?:cast|play) [^.]+exiled with (?:~|it)[^.]*\.?"),
                  lambda m: parse_linked_play(m.group(0))),
    EffectHandler("exile_cast_window", _EXILE_CAST_WINDOW_RE, _exile_cast_window),
    # PAR-13: "exile the top N cards of your library. you may play them
    # [this turn/until the end of your next turn]." — RULE 601.3b impulsive
    # draw (Runestone Caverns/Bonehoard Dracosaur/Painter's Studio-shaped).
    EffectHandler(
        "exile_top_play",
        _EXILE_TOP_PLAY_RE,
        _exile_top_play,
        fallback_for=("exile_cast_window",),
    ),
    # PAR-13: "draw N cards and reveal them. you may cast one of them
    # without paying its mana cost." — Mad Wizard's Lair's own room.
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_par13_dungeons_and_variants.py (dungeon room text, not a pool card).
    EffectHandler(
        "draw_reveal_cast_free",
        _DRAW_REVEAL_CAST_FREE_RE,
        _draw_reveal_cast_free,
    ),
    EffectHandler("free_cast_zone", _FREE_CAST_ZONE_RE, _free_cast_zone),
    # MEC-20: RULE 601.2f "Expertise" cycle — "you may cast a spell with
    # mana value N/X or less from your hand without paying its mana cost
    # [, where x is the number of attacking creatures]".
    EffectHandler(
        "free_cast_from_hand",
        _FREE_CAST_FROM_HAND_RE,
        _free_cast_from_hand,
        fallback_for=("free_cast_zone",),
    ),
    EffectHandler("exile_copy_cast", _EXILE_COPY_CAST_RE, _exile_copy_cast),
    EffectHandler("dig_cast_free", _DIG_CAST_FREE_RE, _dig_cast_free),
    EffectHandler("graveyard_play_window", _GRAVEYARD_PLAY_WINDOW_ROW_RE, _graveyard_play_window),
    EffectHandler(
        "cheat_creature_from_hand",
        _CHEAT_CREATURE_FROM_HAND_RE,
        _cheat_creature_from_hand,
    ),
    # ENG-33: "you may put a <type> card from your hand onto the
    # battlefield" (Dr. Eggman — a villainous-choice option body).
    EffectHandler(
        "put_from_hand",
        _PUT_FROM_HAND_RE,
        _put_from_hand,
    ),
    # "Target opponent reveals their hand. You choose a nonland card from
    # it. That player discards that card." (Duress/Thoughtseize-shaped) —
    # tried before the plain `discard` row below (unrelated shapes, but
    # this one's much longer clause should never partially match that
    # row's short one anyway).
    EffectHandler(
        "hand_disruption_discard",
        _HAND_DISRUPTION_RE,
        _hand_disruption_discard,
    ),
    EffectHandler("hand_pick", _HAND_PICK_RE, _hand_pick),
    # "exile [up to N] [another] target creature/[nonland] permanent you
    # control, then return that card/it to the battlefield under your/its
    # owner's control." (Felidar Guardian/Emiel the Blessed/Displacer
    # Kitten-shaped) — tried after the subtype-exclusion row above so a
    # Restoration Angel-shaped clause still matches that narrower row first.
    EffectHandler(
        "blink_plain",
        _BLINK_PLAIN_RE,
        _blink_plain,
    ),
    # "defending player reveals the top card of their library. If it's a
    # land card, that player puts it into their hand." (Goblin Guide-shaped).
    EffectHandler(
        "reveal_top_conditional",
        _REVEAL_TOP_CONDITIONAL_RE,
        _reveal_top_conditional,
    ),
    EffectHandler("reveal_top_put_or_hand", _REVEAL_TOP_PUT_OR_HAND_RE, _reveal_top_put_or_hand),
    EffectHandler("reveal_top_take", _REVEAL_TOP_TAKE_RE, _reveal_top_take),
    EffectHandler("put_self_from_hand", _PUT_SELF_FROM_HAND_RE, _put_self_from_hand),
    EffectHandler(
        "look_defending_hand", _LOOK_DEFENDING_HAND_RE,
        lambda m: [EffectSpec("look_at_hand", {"defending_player": True})],
    ),
    EffectHandler("put_from_defending_hand", _PUT_FROM_DEFENDING_HAND_RE, _put_from_defending_hand),
    # "create an X/X blue Shark creature token with flying, where X is that
    # spell's mana value." (Shark Typhoon-shaped spell-cast payoff). Note
    # `cycling_xx_token`/`CYCLING_XX_TOKEN_RE` (this row's sibling for
    # RULE 702.28c's Cycling-cost X) is deliberately NOT registered here —
    # a bare "create an X/X ... token." with no trailing explanation is
    # ambiguous outside a "when you cycle this card" wrapper (Wurmcalling/
    # Slime Molding's X is their own {X} mana cost, not a Cycling cost) —
    # `segmenter.py`'s cycle-trigger dispatch calls it directly instead,
    # scoped to exactly that context.
    EffectHandler(
        "mana_value_xx_token",
        _MANA_VALUE_XX_TOKEN_RE,
        _mana_value_xx_token,
    ),
    # "you discard a card" / "discard 2 cards" / "target player discards a
    # card" / "…discards a card at random" (RULE 701.8d — Black Cat /
    # Hypnotic Specter / Bottomless Pit's "that player" via the
    # `that_player_discards` row).
    EffectHandler(
        "that_player_discards_that_many",
        compile_clause(r"that player discards that many cards?"),
        _that_many_player_discards,
    ),
    EffectHandler("discard_unless", _DISCARD_UNLESS_RE, _discard_unless),
    # "Untap up to three lands." (Frantic Search, Cloud of Faeries, Palinchron, Peregrine Drake) — an untargeted pick
    # (`choose_objects` with the ``untap`` action), unlike "untap up to two **target** lands" (RULE 115).
    EffectHandler(
        "untap_up_to_lands",
        compile_clause(r"untap up to (?P<n>\d+) lands(?P<own> you control)?"),
        lambda m: [EffectSpec("choose_objects", {
            "action": "untap", "what": "land", "count": int(m.group("n")), "optional": True,
            "pool_player_selector": "chooser" if m['own'] else "all",
            "prompt": "Wähle bis zu %d Länder zum Enttappen" % int(m.group("n")),
        })],
    ),
    EffectHandler(
        "discard",
        compile_clause(
            r"(?P<who>you|target player|target opponent|each player|each opponent|defending player)?\s*"
            rf"discards? {COUNT} cards?(?P<at_random> at random)?"
        ),
        _discard,
    ),
    # "look at target player's hand." (Clairvoyance, Peek, Glasses of Urza) — an informational pick, see
    # `RulesEngine.look_at_hand`; "that player's hand" follows an earlier clause that chose the player.
    EffectHandler(
        "look_at_hand",
        compile_clause(r"look at target (?P<who>player|opponent)'s hand"),
        lambda m: [EffectSpec("look_at_hand", {
            "target_kind": "opponent" if m.group("who") == "opponent" else "player"})],
    ),
    # PAR-74: "target opponent exiles a card from their hand." (Kyoki,
    # Sanity's Eclipse) — the exile-zone sibling of the plain ``discard``
    # row above; RULE 701.5a's interactive "that player chooses" (the
    # `ExileHandCardEffect`/`exile_hand_choice` chooser, not an auto-pick).
    EffectHandler(
        "exile_hand_card",
        compile_clause(
            rf"(?P<who>you|target player|target opponent) exiles? {COUNT} "
            r"cards? from (?:your|their) (?P<zone>hand|graveyard)"
        ),
        lambda m: [EffectSpec("exile_hand_card", {
            "count": count_of(m.group("n")),
            **({"zone": "graveyard"} if m.group("zone") == "graveyard" else {}),
            **(
                {"target_kind": "player"}
                if m.group("who") in ("target player", "target opponent")
                else {}
            ),
        })],
    ),
    # PAR-118 (RULE 702.62): "[you may] exile a [nonland] card from your hand [and put] with a number of time counters
    # on it equal to its mana value" and its three printed riders (The Eleventh Doctor, The Wedding of River Song,
    # Alaundo the Seer) — see `_EXILE_HAND_TIME_RE`.
    EffectHandler("exile_hand_time_counters", _EXILE_HAND_TIME_RE, _exile_hand_time_counters),
    # PAR-74: "target player reveals their hand and discards all cards with
    # that spell's mana value." (Infernal Kirin) — "reveals their hand" is
    # pure flavor at this engine's fidelity (same treatment `_SEARCH_REVEAL`
    # gives a tutor's own "reveal it," — nothing else reads the reveal), so
    # only the discard half becomes an effect: RULE 601.2c's non-interactive
    # "all `<X>`" mass discard (`DiscardEffect.filter`'s new
    # ``mana_value_from_trigger_event`` key, `DestroyEffect.filter`'s
    # identical key/referent).
    EffectHandler(
        "reveal_hand_discard_matching_mv",
        compile_clause(
            r"(?P<who>target player|target opponent) reveals? (?:their|its) hand "
            r"and discards? all cards with that spell'?s mana value"
        ),
        lambda m: [EffectSpec("discard", {
            "target_kind": "player", "filter": {"mana_value_from_trigger_event": True},
        })],
    ),
    # PAR-13: "each player loses N life unless they discard a card/sacrifice
    # a creature, artifact, or land of their choice." — Veils of Fear/
    # Sandfall Cell's own APNAP mass "unless".
    EffectHandler(
        "each_player_lose_life_unless",
        _EACH_PLAYER_LOSE_LIFE_UNLESS_RE,
        _each_player_lose_life_unless,
    ),
    # "each player/opponent sacrifices a[n] [nontoken] creature/artifact/
    # land/permanent of their choice" (Accursed Marauder/Liliana, Dreadhorde
    # General's -4 mass edict).
    EffectHandler(
        "sacrifice_edict",
        _SACRIFICE_EDICT_RE,
        _sacrifice_edict,
    ),
    # ENG-33: "target player/opponent sacrifices a <what> of their choice"
    # (Diabolic Edict-shaped, and villainous/vote's *other* option).
    EffectHandler(
        "target_player_edict",
        _TARGET_PLAYER_EDICT_RE,
        _target_player_edict,
    ),
    EffectHandler(
        "sacrifice_controller",
        _SACRIFICE_CONTROLLER_RE,
        _sacrifice_controller,
    ),
    # PAR-13: "discard a card and sacrifice a creature, an artifact, and a
    # land." — Oubliette's own compound mandatory punishment.
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_par13_dungeons_and_variants.py (dungeon room text, not a pool card).
    EffectHandler(
        "discard_and_sacrifice_triple",
        _DISCARD_AND_SACRIFICE_TRIPLE_RE,
        _discard_and_sacrifice_triple,
    ),
]
