"""Gain/lose life and player-counter rows (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import re

from ..clause_reading import ClauseReading
from typing import Optional
from ..subgrammars import (
    COUNT,
    count_of,
    count_or_x_of,
    COUNT_X,
    DEVOTION,
    devotion_selector,
    NUMBER,
    resolve_target_kind,
    subtype_count_selector,
    TARGET,
)
from ...spec import EffectSpec
from .shared import (
    BECOMES_TARGET_EVENT,
    compile_clause,
    EffectHandler,
    ENTERING_CONTROLLER,
    EVENT_PLAYER_EVENTS_KEY,
    SACRIFICE_EDICT_WHAT_WORDS,
    selector_devotion_builder,
    SELECTOR_WORD_MAP,
    subject_handlers,
)


def _gain_life(m: re.Match[str]) -> list[EffectSpec]:
    # "you gain N life" / "target player gains N life" (Abuna's Chant-shaped)
    # / "you gain X life" (Battle at the Bridge's trailing sentence, PAR-47's
    # widening sweep — the ``"x"`` sentinel `RulesEngine._substitute_x`
    # already resolves on `GainLifeEffect.amount`) — a real RULE 115 target
    # only for the "target player" phrasing.
    params: dict = {"amount": count_or_x_of(m.group("n"))}
    if (m.groupdict().get("who") or "").strip() == "target player":
        params["target_kind"] = "player"
    return [EffectSpec("gain_life", params)]


#: RULE 119's "drain" idiom trailing sentence — "You gain life equal to the
#: life lost this way." (Gray Merchant of Asphodel/Exsanguinate/Kokusho, the
#: Evening Star-shaped, 16+ cache cards) — always the second sentence after
#: a "`<player(s)>` lose[s] `<amount>` life" clause that already parses on
#: its own (`_lose_life`/`_lose_life_selector`); only this trailing pronoun
#: sentence was ever unclaimed, discarding the *whole* two-sentence ability
#: fail-closed.
_GAIN_LIFE_LOST_THIS_WAY_RE = compile_clause(r"you gain life equal to the life lost this way")


def _gain_life_lost_this_way(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"count_selector": "life_lost_this_way"})]


_GAIN_LIFE_SACRIFICED_TOUGHNESS_RE = compile_clause(
    r"you gain life equal to the sacrificed creature'?s toughness"
)


def _gain_life_sacrificed_toughness(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"count_selector": "sacrificed_cost_toughness"})]


#: "You gain life equal to `<its / that creature's>` `<power / toughness>`."
#: (~36 SOLO — Bottle Golems / Angelic Chorus / Weed Strangle [a clash
#: card] / Brightmare / …). The creature isn't a RULE 115 target of the
#: gain-life effect itself; `GainLifeEffect.amount_from_subject` names which
#: object + characteristic. Three gated handlers, one per pronoun subject:
#: "its" on a bare-`~` trigger → ``self_*``; "its" on a group trigger
#: ("a creature you control enters" — the firing creature) →
#: ``trigger_subject_*``; "that creature's" after another clause →
#: ``previous_subject_*`` (RULE 608.2h last-known info — the creature is
#: usually gone by then).
_GAIN_LIFE_EQ_ITS_RE = compile_clause(r"you (?:may )?gain life equal to its (?P<char>power|toughness)")
_GAIN_LIFE_EQ_THAT_RE = compile_clause(
    r"you (?:may )?gain life equal to that (?:creature|permanent)'?s (?P<char>power|toughness)"
)


def _gain_life_eq_its_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"amount_from_subject": f"self_{m.group('char')}"})]


def _gain_life_eq_its_group(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"amount_from_subject": f"trigger_subject_{m.group('char')}"})]


def _gain_life_eq_that_prev(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"amount_from_subject": f"previous_subject_{m.group('char')}"})]


#: "When ~ dies, draw cards equal to its power." (Lifeblood Hydra / Return
#: of the Wildspeaker / Kavu Lair-shaped) and its combined sibling "…you
#: gain life **and** draw cards equal to its power." (Lifeblood Hydra's own
#: single clause, where "equal to its power" scopes both verbs at once, so
#: the ordinary "and" connector split can't reach it). ``trigger_subject_``
#: reads the DIES event's RULE 400.7 power/toughness snapshot
#: (`_characteristic_of_subject`); `DrawCardEffect.amount_from_subject` is
#: the new draw-side sibling of `GainLifeEffect`'s own field. `self_subject_
#: only` — "its" here is the trigger's own subject.
_DRAW_EQ_ITS_RE = compile_clause(r"draw cards equal to its (?P<char>power|toughness)")
_GAIN_LIFE_AND_DRAW_EQ_ITS_RE = compile_clause(
    r"you gain life and draw cards equal to its (?P<char>power|toughness)"
)


def _draw_eq_its_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw", {"amount_from_subject": f"trigger_subject_{m.group('char')}"})]


def _gain_life_and_draw_eq_its_self(m: re.Match[str]) -> list[EffectSpec]:
    key = f"trigger_subject_{m.group('char')}"
    return [
        EffectSpec("gain_life", {"amount_from_subject": key}),
        EffectSpec("draw", {"amount_from_subject": key}),
    ]


#: PAR-115 (`14_` S4 residue): "…. its controller `<verb>` …" — the
#: previous clause's own **controller**, not the previous clause's chosen
#: object itself (`gain_life_eq_that_prev`/`draw_eq_its_self` just above).
#: `EffectHandler.previous_subject_only` already gates on exactly the right
#: antecedent (`segmenter.announces_creature_target`: a destroyed/exiled/
#: countered/bounced/tapped permanent or a countered spell), so these rows
#: reuse that gate rather than adding a new one, and read the referent
#: through `game/effect_operands.py`'s ``{"of": "previous_target", "as":
#: "controller"}`` — the same vocabulary `game/card_catalogue/
#: swords_to_plowshares.py`/`nature_s_claim.py` already spell out by hand
#: for one card each. A trailing "and you {gain,lose} N life" (Certain
#: Death/Inevitable Defeat/Punish Ignorance) needs no grammar here at all:
#: `segmenter._CONNECTORS`' own " and " split recurses on the remainder
#: with the same referent, and the ordinary bare ``gain_life``/``lose_life``
#: rows already claim "you gain/lose N life" by themselves.
_PREVIOUS_TARGET_CONTROLLER: dict = {"of": "previous_target", "as": "controller"}
# "its controller"/"that creature's controller"/"that player" all name the
# same antecedent's controller. Which antecedent that is remains the handler
# gate's job: `previous_subject_only` for a preceding target,
# `group_subject_only` for a RULE 603.1 firing object (Blood Reckoning), and
# `attached_subject_only` for an Aura's host. Keeping the spelling together
# prevents a second parallel referent vocabulary from drifting out of sync.
#
# PAR-120: "that player" reads the same `_PREVIOUS_TARGET_CONTROLLER`
# operand unchanged — no separate referent needed. `effect_operands._derive`
# already resolves "controller of" a referent that turns out to *already be*
# a `Player` (a preceding "target player"/"target opponent" clause) to that
# player directly rather than a controller lookup (Diplomacy of the Wastes:
# "target opponent reveals their hand. … that player discards that card." —
# previous_target is already the opponent), and falls back to reading
# `.controller_id` off a `GameObject` referent otherwise (Carrion Locust's
# exiled graveyard card, Massacre Wurm's group-subject dying creature,
# Dalek Drone's destroyed creature) — the same disambiguation "its
# controller" already relies on, just under a different printed pronoun.
CONTROLLER_REFERENT = r"(?:(?:its|that creature'?s) controller|that player)"
#: ``x`` is a "…loses life equal to <amount>" rewrite's own measurement (`segmenter._where_x_specs` — Deny the Witch);
#: the group/attached rows (`_its_controller_spec`) have nothing to bind it to and refuse it.
_ITS_CONTROLLER_LOSES_LIFE_RE = compile_clause(rf"{CONTROLLER_REFERENT} loses (?P<n>\d+|x) life")
_ITS_CONTROLLER_GAINS_LIFE_RE = compile_clause(rf"{CONTROLLER_REFERENT} gains (?P<n>\d+|x) life")
_ITS_CONTROLLER_DRAWS_RE = compile_clause(rf"{CONTROLLER_REFERENT} draws? {COUNT_X} cards?")
_ITS_CONTROLLER_DISCARDS_RE = compile_clause(rf"{CONTROLLER_REFERENT} discards? {COUNT} cards?")


def _its_controller_loses_life(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {
        "amount": count_or_x_of(m.group("n")), "player": _PREVIOUS_TARGET_CONTROLLER,
    })]


def _its_controller_gains_life(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {
        "amount": count_or_x_of(m.group("n")), "player": _PREVIOUS_TARGET_CONTROLLER,
    })]


def _its_controller_draws(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw", {
        "count": count_or_x_of(m.group("n")), "player": _PREVIOUS_TARGET_CONTROLLER,
    })]


def _its_controller_discards(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("discard", {
        "count": count_of(m.group("n")), "player": _PREVIOUS_TARGET_CONTROLLER,
    })]


#: Torment of Venom — its targeted creature's controller, not the spell's
#: caster, may choose either half of the printed compound cost.  The earlier
#: counter instruction supplies the RULE 608.2 pronoun referent.
_ITS_CONTROLLER_LOSES_LIFE_UNLESS_SAC_OR_DISCARD_RE = compile_clause(
    rf"{CONTROLLER_REFERENT} loses (?P<n>\d+) life unless they sacrifice "
    r"another nonland permanent of their choice or discard a card"
)


def _its_controller_loses_life_unless_sac_or_discard(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pay_cost_then", {
        "cost": "sacrifice a nonland permanent",
        "payer": "previous_target_controller",
        "sacrifice_or_discard": True,
        "capture_previous": True,
        "effects": [],
        "else_effects": [{"type": "lose_life", "params": {
            "amount": int(m.group("n")), "player": _PREVIOUS_TARGET_CONTROLLER,
        }}],
    })]


#: "counter target spell. its controller mills N cards." (Countermand/
#: Didn't Say Please/Psychic Strike/Thought Collapse's own family) —
#: `MillEffect.selector="previous_subject_controller"` already exists,
#: built for Broken Ambitions' "that spell's controller mills four cards"
#: (see that effect's own docstring, RULE 608.2h) — this was only ever
#: missing the "its controller" parser row, not the engine primitive.
_ITS_CONTROLLER_MILLS_RE = compile_clause(rf"{CONTROLLER_REFERENT} mills {COUNT} cards?")


def _its_controller_mills(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("mill", {
        "count": count_of(m.group("n")), "selector": "previous_subject_controller",
    })]


#: "…, its controller gains life equal to its mana value." (Illumination)
#: / "…, its controller mills cards equal to that creature's power."
#: (Grisly Spectacle) — the referent's own `mana_value`/`power`, measured
#: once through a `bind` (ENG-37) exactly the way `swords_to_plowshares.py`
#: already does by hand for "its controller gains life equal to its
#: power", generalized here into an ordinary parser row.
_ITS_CONTROLLER_GAINS_LIFE_EQ_MV_RE = compile_clause(
    r"(?:its|that (?:creature|permanent|artifact|land|enchantment)'s) controller gains life equal to its mana value"
)
_ITS_CONTROLLER_MILLS_EQ_POWER_RE = compile_clause(
    r"its controller mills cards equal to that creature'?s power"
)


def _its_controller_gains_life_eq_mv(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("bind", {
        "name": "mv",
        "amount": {
            "kind": "characteristic", "characteristic": "mana_value", "of": "previous_target",
        },
        "effects": [{
            "type": "gain_life",
            "params": {"amount": "$mv", "player": _PREVIOUS_TARGET_CONTROLLER},
        }],
    })]


def _its_controller_mills_eq_power(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("bind", {
        "name": "power",
        "amount": {"kind": "characteristic", "characteristic": "power", "of": "previous_target"},
        "effects": [{
            "type": "mill",
            "params": {"count": "$power", "selector": "previous_subject_controller"},
        }],
    })]


#: "whenever a Sliver deals damage, its controller gains that much life."
#: (Essence Sliver) — "that much" is the firing DAMAGE event's own
#: ``amount`` field, the ``group_subject_only`` sibling of `_ITS_CONTROLLER_
#: LOSES_THAT_MUCH_LIFE_RE`'s `attached_subject_only` row above (Ragged
#: Veins/Visions of Brutality print the "loses" polarity off an attached
#: host; no cached card yet pairs a group subject with "loses" instead of
#: "gains", so only this polarity is added here).
_ITS_CONTROLLER_GAINS_THAT_MUCH_LIFE_RE = compile_clause(r"its controller gains that much life")


#: PAR-117 (attached-permanent-controller residue): "whenever enchanted
#: creature/land `<trigger>`, its controller `<verb>` …" (Contaminated
#: Bond/Corrupted Roots/Sinister Possession/Ragged Veins/Visions of
#: Brutality/Chronic Flooding/Fate Foretold/Decomposition) — "its" is RULE
#: 303.4/301.5's attached host, a fourth referent alongside
#: `previous_subject_only`/`group_subject_only` above: the trigger
#: condition itself already names it (`{"subject": "attached_permanent"}`),
#: not a pronoun chain within the effect body. `segmenter._ATTACHED_
#: SUBJECT_RE`/`_ATTACHED_MULTI_EVENT_RE`/the ``attached`` groups on
#: `_DAMAGE_TRIGGER_RE`/`_DAMAGE_RECIPIENT_TRIGGER_RE` already recognize
#: every one of this cluster's antecedents; only these bodies were
#: unclaimed. Reuses the same compiled regexes as the `previous_subject`/
#: `group_subject` families above (the printed clause text is identical —
#: only the referent differs) and the same ``{"of": "attached", "as":
#: "controller"}`` operand `effect_conditions.subject_of`/`game/
#: effect_operands.py` now resolve (PAR-117's own `subject_of` widening);
#: `MillEffect` gets the `"attached_permanent_controller"` selector sibling
#: of `"trigger_subject_controller"` the same way `LoseLifeEffect` already
#: had one (built for the hand-authored Parasitic Impetus).
_ATTACHED_CONTROLLER: dict = {"of": "attached", "as": "controller"}


#: "whenever enchanted creature is dealt damage / deals damage, its
#: controller loses that much life." (Ragged Veins / Visions of Brutality)
#: — "that much" is the firing DAMAGE event's own ``amount`` field, the same
#: idiom `_lose_life_from_trigger_amount`/`_gain_life_from_trigger_amount`
#: already use for a RULE 115 target/the ability's own controller; this is
#: their attached-host-controller sibling.
_ITS_CONTROLLER_LOSES_THAT_MUCH_LIFE_RE = compile_clause(r"its controller loses that much life")


#: PAR-117 (sacrifice-verb residue): "its controller sacrifices `<N>`
#: [nontoken] `<what>`[ or `<what2>`] of their choice" (Funeral March —
#: attached_permanent referent; Tainted Aether — group-subject referent).
#: `SacrificeEffect.player` now accepts the same ``{"of": …, "as":
#: "controller"}`` referent `GainLifeEffect`/`LoseLifeEffect`/`DrawCardEffect`/
#: `DiscardEffect`/`MillEffect` already read (widened alongside this row —
#: RULE 601.2c's interactive edict needed no different plumbing than any
#: other player-scoped effect, just the same operand). Reuses
#: `_SACRIFICE_EDICT_WHAT_WORDS`/`_sacrifice_edict`'s own vocabulary; the
#: optional "or `<what2>`" alternation only recognizes the one two-word
#: combination a real card needs (`_SACRIFICE_WHAT_OR_COMBOS`) rather than
#: every pairing, the same closed-vocabulary discipline `_matches_
#: permanent_type` itself follows.
_SACRIFICE_WHAT_OR_COMBOS: dict[frozenset, str] = {
    frozenset({"creature", "land"}): "creature_or_land",
}
_ITS_CONTROLLER_SACRIFICES_RE = compile_clause(
    rf"its controller sacrifices (?P<count>a|an|\d+) (?P<nontoken>nontoken )?"
    rf"(?P<what>{'|'.join(SACRIFICE_EDICT_WHAT_WORDS)})s?"
    rf"(?: or (?P<what2>{'|'.join(SACRIFICE_EDICT_WHAT_WORDS)})s?)? of their choice"
)


def _its_controller_sacrifices_params(m: re.Match[str]) -> Optional[dict]:
    what = SACRIFICE_EDICT_WHAT_WORDS[m.group("what")]
    what2 = m.groupdict().get("what2")
    if what2:
        combo = _SACRIFICE_WHAT_OR_COMBOS.get(frozenset({what, SACRIFICE_EDICT_WHAT_WORDS[what2]}))
        if combo is None:
            return None  # an un-whitelisted "<x> or <y>" pairing → fail closed
        what = combo
    elif m.group("nontoken") and what == "creature":
        what = "nontoken_creature"
    count_word = m.group("count")
    return {"what": what, "count": 1 if count_word in ("a", "an") else int(count_word)}


#: PAR-121: "its controller `<verb>` …" — the verb × subject matrix. The same clause text reads as the controller
#: of the creature a group trigger fired for (``group``, `_ENTERING_CONTROLLER`; Poisonbelly Ogre-shaped) or of an
#: Aura's host (``attached``, `_ATTACHED_CONTROLLER`; Contaminated Bond-shaped) — the two referents differ only
#: in the operand a player-scoped effect reads (and the `MillEffect` selector sibling), so each verb is built once
#: from ``(player operand, mill selector)`` instead of once per subject. The third reading ("its" = an earlier
#: clause's pick, ``previous``) has its own builders above because it resolves through `previous_targets`.
#: "that much" is the firing DAMAGE event's own ``amount`` (Essence Sliver's "gains", Ragged Veins' "loses" —
#: each printed off a different subject only, so each polarity exists for one).
_ITS_CONTROLLER_SUBJECTS: dict[str, tuple[dict, str]] = {
    "group": (ENTERING_CONTROLLER, "trigger_subject_controller"),
    "attached": (_ATTACHED_CONTROLLER, "attached_permanent_controller"),
}


def _its_controller_spec(verb: str, m: re.Match[str], player: dict, mill_selector: str) -> Optional[list[EffectSpec]]:
    if verb in ("loses_life", "gains_life") and m.group("n") == "x":
        return None
    if verb == "loses_life":
        return [EffectSpec("lose_life", {"amount": int(m.group("n")), "player": player})]
    if verb == "gains_life":
        return [EffectSpec("gain_life", {"amount": int(m.group("n")), "player": player})]
    if verb == "loses_that_much_life":
        return [EffectSpec("lose_life", {"amount_from_trigger_event": "amount", "player": player})]
    if verb == "gains_that_much_life":
        return [EffectSpec("gain_life", {"amount_from_trigger_event": "amount", "player": player})]
    if verb == "draws":
        return [EffectSpec("draw", {"count": count_or_x_of(m.group("n")), "player": player})]
    if verb == "discards":
        return [EffectSpec("discard", {"count": count_of(m.group("n")), "player": player})]
    if verb == "mills":
        return [EffectSpec("mill", {"count": count_of(m.group("n")), "selector": mill_selector})]
    if verb == "sacrifices":
        params = _its_controller_sacrifices_params(m)
        return None if params is None else [EffectSpec("sacrifice", {**params, "player": player})]
    return None


def _its_controller_handlers() -> list[EffectHandler]:
    """One row per (subject, verb) the printed cards use, in the order the rows were first written."""
    regexes = {
        "loses_life": _ITS_CONTROLLER_LOSES_LIFE_RE,
        "gains_life": _ITS_CONTROLLER_GAINS_LIFE_RE,
        "loses_that_much_life": _ITS_CONTROLLER_LOSES_THAT_MUCH_LIFE_RE,
        "gains_that_much_life": _ITS_CONTROLLER_GAINS_THAT_MUCH_LIFE_RE,
        "draws": _ITS_CONTROLLER_DRAWS_RE,
        "discards": _ITS_CONTROLLER_DISCARDS_RE,
        "mills": _ITS_CONTROLLER_MILLS_RE,
        "sacrifices": _ITS_CONTROLLER_SACRIFICES_RE,
    }
    matrix = (
        ("group", ("loses_life", "gains_life", "gains_that_much_life", "draws", "discards", "mills", "sacrifices")),
        ("attached", ("loses_life", "loses_that_much_life", "gains_life", "draws", "discards", "mills", "sacrifices")),
    )
    rows = []
    for subject, verbs in matrix:
        player, mill_selector = _ITS_CONTROLLER_SUBJECTS[subject]
        for verb in verbs:
            rows.append((
                f"{subject}_its_controller_{verb}", subject, regexes[verb],
                lambda m, verb=verb, player=player, mill_selector=mill_selector:
                    _its_controller_spec(verb, m, player, mill_selector),
            ))
    return subject_handlers(rows)


#: "Whenever a player casts a spell, they lose 1 life for each spell
#: they've cast this turn." (Rug of Smothering) — the caster's own running
#: `GameState.spells_cast_this_turn` count (`LoseLifeEffect.
#: amount_from_spells_cast_this_turn`, including the cast that fired this
#: trigger), not a flat amount — tried before the plain `_lose_life` row
#: below, whose bare `{NUMBER}` group can't match "each spell...".
_LOSE_LIFE_PER_SPELL_CAST_THIS_TURN_RE = compile_clause(
    rf"they lose {NUMBER} life for each spell they'?ve cast this turn"
)


def _lose_life_per_spell_cast_this_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {
        "amount": int(m.group("n")), "selector": "event_player",
        "amount_from_spells_cast_this_turn": True,
    })]


#: PAR-124: "Whenever a player gains life, **that player** loses N life for
#: each 1 life they gained." (False Cure) — the same "event's own firing
#: player" referent as `_lose_life`'s "they" row (`selector="event_player"`),
#: just spelled "that player"; the magnitude is a live multiple of the
#: `LIFE_GAINED` event's own ``amount`` field, read through the shared
#: `effect_amounts` ``"trigger_event"`` operand's generic ``multiply``
#: modifier (`ENG-47 b`) rather than a bespoke per-effect parameter.
_LOSE_LIFE_PER_LIFE_GAINED_RE = compile_clause(
    r"that player loses (?P<n>\d+) life for each 1 life they gained"
)
_LOSE_LIFE_THAT_CONTROLLER_RE = compile_clause(
    r"that (?:player|spell or ability's controller) loses (?P<n>\d+) life"
)


def _lose_life_that_controller(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {
        "amount": int(m.group("n")), "selector": "event_player",
        EVENT_PLAYER_EVENTS_KEY: [BECOMES_TARGET_EVENT],
    })]


#: PAR-166: "<player> loses half their life, rounded up/down" / "... a third of their life, rounded up" -- the amount is a
#: fraction of that player's *current* life (RULE 107.2/119.3), measured at resolution on the very player who loses it.
_FRACTIONAL_LIFE_DIVISORS = {"half": 2, "a third of": 3}
#: Events whose firing names the "that player" / "they" / "defending player" this clause means: a DAMAGE event's damaged
#: player (RULE 120.3) -- singly or as one combat batch -- and an ATTACKS event's defending player (RULE 508.1b);
#: read by the `trigger_player` referent.
_TRIGGER_PLAYER_EVENTS = ["DAMAGE", "ATTACKS", "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER"]
_DEFENDING_PLAYER_EVENTS = ["ATTACKS"]
_LOSE_FRACTION_OF_LIFE_RE = compile_clause(
    r"(?P<who>you|target opponent|target player|that player|they|defending player) loses? "
    r"(?P<fraction>half|a third of) (?:your|their) life, rounded (?P<round>up|down)"
)


def _lose_fraction_of_life(m: re.Match[str]) -> list[EffectSpec]:
    who = m.group("who")
    amount: dict = {"kind": "resource", "resource": "life", "divide": _FRACTIONAL_LIFE_DIVISORS[m.group("fraction")]}
    if m.group("round") == "up":
        amount["round_up"] = True
    params: dict = {"amount": amount}
    if who in ("target opponent", "target player"):
        params["target_kind"] = "opponent" if who == "target opponent" else "player"
        amount["of"] = "target"
    elif who != "you":
        amount["of"] = "trigger_player"
        params["player"] = {"of": "trigger_player", "as": "self"}
        params[EVENT_PLAYER_EVENTS_KEY] = _DEFENDING_PLAYER_EVENTS if who == "defending player" else _TRIGGER_PLAYER_EVENTS
    return [EffectSpec("lose_life", params)]


def _lose_life_per_life_gained(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {
        "amount": {"kind": "trigger_event", "field": "amount", "multiply": int(m.group("n"))},
        "selector": "event_player",
    })]


def _lose_life(m: re.Match[str]) -> list[EffectSpec]:
    # "you lose N life" / "target player loses N life" / "target opponent
    # loses N life" — same targeting split as `_gain_life`. "target
    # opponent" is the RULE 115 opponent-restricted player target (the
    # `"opponent"` target kind), which pairs with a following "and you gain
    # N life" clause via the ordinary connector split for the Blood Artist
    # drain family. "they lose N life" (Sheoldred, the Apocalypse's
    # "whenever an opponent draws a card, they lose 2 life.") is the group-
    # subject trigger's own firing player, not a fresh RULE 115 target —
    # `LoseLifeEffect`'s ``selector="event_player"``, the same "that player"
    # idiom `_SELECTOR_WORD_MAP`'s ``"event_player"`` row already uses.
    who = (m.groupdict().get("who") or "").strip()
    # "x" is the announced {X} (substituted when the spell resolves) or the one a "where X is …" binds.
    params: dict = {"amount": "x" if m.group("n").lower() == "x" else int(m.group("n"))}
    if who == "target player":
        params["target_kind"] = "player"
    elif who == "target opponent":
        params["target_kind"] = "opponent"
    elif who == "they":
        params["selector"] = "event_player"
    return [EffectSpec("lose_life", params)]


def _lose_life_selector(m: re.Match[str]) -> list[EffectSpec]:
    # "each opponent loses N life" / "each player loses N life" / "each
    # other player loses N life" — the shared `_SELECTOR_WORD_MAP` mass/
    # untargeted-selector shape (RULE 601.2c, not RULE 115 targeting).
    selector = SELECTOR_WORD_MAP[m.group("selector")]
    # ``COUNT_X`` (not just digits) so "each opponent loses X life."
    # (Exsanguinate) carries the ``"x"`` sentinel `RulesEngine._substitute_x`
    # resolves against the spell's actually-announced {X} at resolve time —
    # `LoseLifeEffect.amount` is a plain attribute that sentinel already
    # walks, so no engine change was needed, just this wider capture.
    return [EffectSpec("lose_life", {"amount": count_or_x_of(m.group("n")), "selector": selector})]


#: RULE 202.2f/700.6 "each opponent loses X life, where X is your devotion
#: to `<colour>`." (Gray Merchant of Asphodel-shaped) — `_lose_life_
#: selector`'s devotion-amount sibling, tried first since "x" never matches
#: that row's `NUMBER` (``\d+``).
_LOSE_LIFE_SELECTOR_DEVOTION_RE = compile_clause(
    rf"(?P<selector>each player|each opponent) loses x life, where x is {DEVOTION}"
)


_lose_life_selector_devotion = selector_devotion_builder("lose_life")


#: "Each opponent loses life equal to the number of Vampires you control."
#: (Malakir Bloodwitch) — `continuous.count_selector`'s existing
#: ``creatures_you_control_of_type_<subtype>`` vocabulary (already reached
#: by `_create_token_for_each`'s "for each `<subtype>` you control" reading)
#: applied to life loss instead of a token count.
_LOSE_LIFE_SELECTOR_SUBTYPE_RE = compile_clause(
    r"(?P<selector>each player|each opponent) loses life equal to the number of "
    r"(?P<subtype>[a-z]+) you control"
)


def _lose_life_selector_subtype(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector = SELECTOR_WORD_MAP[m.group("selector")]
    counted = subtype_count_selector(m.group("subtype"))
    if counted is None:
        return None
    return [EffectSpec("lose_life", {"amount_from_count_selector": counted, "selector": selector})]


#: "You gain life equal to the number of creatures/permanents … you
#: control." This is the non-X wording sibling of `_GAIN_LIFE_DEVOTION_RE`;
#: both use the existing live count-selector path. It can follow a token
#: creation clause, where the count includes the just-created tokens.
_GAIN_LIFE_EQUAL_DEVOTION_RE = compile_clause(rf"you gains? life equal to {DEVOTION}")


def _gain_life_equal_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [EffectSpec("gain_life", {"count_selector": dsel})]


def _rad_counter_amount(token: str) -> "int | str":
    # "N rad counters"/"a rad counter" (COUNT) or "X rad counters" (RULE
    # 601.2b's own announced {X} — the same ``"x"`` sentinel
    # `additional_cost`'s `pay_life` uses, substituted at resolve time).
    return "x" if token.strip().lower() == "x" else count_of(token)


#: "[you/target player/defending player] get[s] N rad counters" (RULE 728,
#: player counters — see `_gain_life`/`_lose_life`'s identical who-prefix
#: shape). ``who`` omitted (bare "get two rad counters") covers a "you may"
#: prefix already peeled by the segmenter (Tato Farmer's Landfall).
#: "defending player" (Acquired Mutation, an Aura's "whenever enchanted
#: creature attacks, defending player gets ~") reuses the same
#: ``selector="defending_player"`` afflict/Simian Sling already established
#: for `LoseLifeEffect`/`DealDamageEffect` (`AddPlayerCountersEffect`'s own
#: apply()-time resolution accounts for the Aura-vs-host source split).
_RAD_COUNTER_WHO_SELECTOR: dict[str, str] = {"defending player": "defending_player"}


def _add_rad_counters(m: re.Match[str]) -> list[EffectSpec]:
    who = (m.groupdict().get("who") or "").strip().lower()
    params: dict = {"amount": _rad_counter_amount(m.group("n")), "kind": m.group("kind")}
    if who == "target player":
        params["target_kind"] = "player"
    elif who == "target opponent":
        # PAR-98 (Persuasive Interrogators): a real RULE 115 target, but only
        # among opponents — the "opponent" kind `targeting` already resolves.
        params["target_kind"] = "opponent"
    elif who in _RAD_COUNTER_WHO_SELECTOR:
        params["selector"] = _RAD_COUNTER_WHO_SELECTOR[who]
    return [EffectSpec("add_player_counters", params)]


#: "each player gets N rad counters" / "each opponent gets N poison
#: counters" (RULE 601.2c mass effect, RULE 122.1/104.3d — the same
#: `AddPlayerCountersEffect` primitive parametrized by ``kind``) — the
#: player-counter sibling of `_lose_life_selector`. ``kind`` is a real
#: regex alternation (not a fixed "rad") since Infectious Bite/Prologue to
#: Phyresis-shaped poison cards use the identical "each opponent gets a
#: `<kind>` counter" template.
def _add_rad_counters_selector(m: re.Match[str]) -> list[EffectSpec]:
    selector = SELECTOR_WORD_MAP[m.group("selector")]
    return [EffectSpec("add_player_counters", {
        "amount": _rad_counter_amount(m.group("n")), "kind": m.group("kind"), "selector": selector,
    })]


#: "target player loses all rad counters" (Survivor's Med Kit's RadAway
#: mode) — the removal sibling, always ``target player`` in practice (no
#: real card grants this to "you" untargeted), so ``target_kind`` is
#: unconditional rather than an optional ``who`` group.
def _lose_all_rad_counters(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_all_player_counters", {"kind": "rad", "target_kind": "player"})]


#: "each opponent gets a number of rad counters equal to its power" (Feral
#: Ghoul's "When this creature dies, ..." — a dynamic amount tied to the
#: dying object's own power, RULE 400.7 last-known-information). ENG-37: this
#: is `bind` (measure the dying creature's power) over the generic
#: `add_player_counters`, not a fused effect type — `DiesGrantsRadCounters
#: EqualPowerEffect` is retired. `minimum: 0` reproduces that effect's own
#: `power <= 0` guard (RULE 122.1 — a negative counter count is zero; without
#: it a creature that died with negative power would *remove* opponents' rad
#: counters via `add_player_counters`' non-positive path).
def _dies_rad_counters_equal_power(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("bind", {
        "name": "rad_pow",
        "amount": {
            "kind": "characteristic", "characteristic": "power",
            "of": "source", "minimum": 0,
        },
        "effects": [{"type": "add_player_counters", "params": {
            "kind": "rad", "selector": "each_opponent", "amount": "$rad_pow",
        }}],
    })]


#: "you get half X rad counters, rounded up/down" (Contaminated Drink's
#: "Draw X cards, then you get half X rad counters, rounded up.") — RULE
#: 107.1e's division-and-rounding phrasing, {X}-scaled only (no real card
#: needs a plain, non-X division yet); the ``"half_x_up"``/``"half_x_down"``
#: sentinel `RulesEngine._substitute_x` resolves against the spell's
#: actually-announced {X} at resolve time, mirroring the plain ``"x"``
#: sentinel exactly.
def _add_rad_counters_half_x(m: re.Match[str]) -> list[EffectSpec]:
    who = (m.groupdict().get("who") or "").strip().lower()
    amount = "half_x_up" if m.group("round") == "up" else "half_x_down"
    params: dict = {"amount": amount, "kind": "rad"}
    if who == "target player":
        params["target_kind"] = "player"
    elif who in _RAD_COUNTER_WHO_SELECTOR:
        params["selector"] = _RAD_COUNTER_WHO_SELECTOR[who]
    return [EffectSpec("add_player_counters", params)]


#: RULE 603.1's "Whenever you gain life, …" lifegain-payoff family (RULE
#: 119.3, Ajani's Pridemate-shaped — `_PLAYER_TRIGGER_CONDITIONS`'s
#: ``"you gain life"`` row already claims the *condition*; this is the
#: matching *body* grammar for the two forms real cards actually print:
#: "target opponent loses that much life" (Sanguine Bond/Defiant Bloodlord)
#: and "put that many +1/+1 counters on ~/target creature" (Ageless
#: Entity/Karlov-adjacent). ``amount_from_trigger_event`` reads the firing
#: LIFE_GAINED event's own ``amount`` (`GameContext.trigger_event`,
#: `LoseLifeEffect`/`AddCountersEffect`'s new param) rather than a literal
#: int — the same "that much"/"that many" idiom `AddManaEffect.
#: amount_from_trigger_event` already models for Raphael, Ninja Destroyer's
#: "add that much {R}". Not wired into every trigger family generally
#: (only this one prints "that much"/"that many" this way), so it's a
#: narrow pair of rows rather than a generic COUNT alternative.
def _lose_life_from_trigger_amount(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind != "player":
        return None
    return [EffectSpec("lose_life", {"target_kind": "player", "amount_from_trigger_event": "amount"})]


#: "Whenever ~ deals damage, **you gain that much life**." (El-Hajjâj /
#: Exalted Angel / Horned Cheetah / Whip of Erebos-shaped — the pre-lifelink
#: template, PAR-36). The `_DAMAGE_TRIGGER_RE` condition already parses; only
#: this body was blocked. "That much" is the firing DAMAGE event's own
#: ``amount`` (`GainLifeEffect.amount_from_trigger_event`, the gain sibling
#: of `_lose_life_from_trigger_amount` just above). Untargeted — "you" is
#: the ability's controller, no RULE 115 target.
def _gain_life_from_trigger_amount(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"amount_from_trigger_event": "amount"})]


#: PAR-71: "[you may] gain life equal to that spell's mana value." (Bounteous
#: Kirin's spirit-or-arcane cast trigger) — the ``mana_value`` sibling of
#: `_gain_life_from_trigger_amount`'s ``"amount"`` field, same firing
#: `SPELL_CAST` event `_damage_spell_mv`/`_pump_mana_value` already read.
#: Untargeted (gaining life is never a RULE 115 target); the segmenter peels
#: a triggered ability's own leading "you may" before this ever runs.
def _gain_life_spell_mv(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"amount_from_trigger_event": "mana_value"})]


#: The lose-life sibling — "that player loses life equal to that spell's
#: mana value." (The Frightful Four) — "that player" is whoever the firing
#: SPELL_CAST event names as the caster, `LoseLifeEffect.
#: selector="event_player"`, the same "that player" idiom `MillEffect.
#: selector="event_controller"` already uses for an analogous event-named
#: subject. Deliberately no bare self-referential "you lose life equal to
#: that spell's mana value" sibling: the only real card on that exact
#: wording is Imp's Mischief ("Change the target of target spell with a
#: single target. You lose life equal to that spell's mana value.") —
#: there "that spell" is the *targeted* spell (`GameContext.
#: previous_targets`), not a `SPELL_CAST` trigger event (this ability has
#: no cast trigger at all — `context.trigger_event` is `None` here, so an
#: `amount_from_trigger_event` read would silently resolve to 0 life lost,
#: exactly the "half-modeled" failure mode the coverage gate exists to
#: prevent). Left unclaimed rather than guessed.
def _lose_life_spell_mv_that_player(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {
        "selector": "event_player", "amount_from_trigger_event": "mana_value",
    })]


ROWS: list[EffectHandler] = [
    # RULE 119.5: setting a life total causes the necessary gain or loss;
    # "your" names the resolving controller and announces no player target.
    EffectHandler(
        "set_own_life",
        compile_clause(r"your life total becomes (?P<n>\d+)"),
        lambda m: [EffectSpec("set_life", {"amount": int(m.group("n")), "target_kind": None})],
    ),
    # "you gain 3 life" / "gain 5 life" / "target player gains 3 life" /
    # "you gain x life" (an {X}-cost spell/ability's own announced X).
    EffectHandler(
        "gain_life",
        compile_clause(rf"(?P<who>you |target player )?gains? (?P<n>x|twice x|\d+) life"),
        _gain_life,
    ),
    # Elemental Spectacle / Luminollusk-shaped count-based life gain.
    EffectHandler("gain_life_equal_devotion", _GAIN_LIFE_EQUAL_DEVOTION_RE, _gain_life_equal_devotion),
    # RULE 119's "drain" idiom trailing sentence — "You gain life equal to
    # the life lost this way." (Gray Merchant of Asphodel-shaped).
    EffectHandler("gain_life_lost_this_way", _GAIN_LIFE_LOST_THIS_WAY_RE, _gain_life_lost_this_way),
    EffectHandler(
        "gain_life_sacrificed_toughness", _GAIN_LIFE_SACRIFICED_TOUGHNESS_RE,
        _gain_life_sacrificed_toughness,
    ),
    # "You gain life equal to <its / that creature's> <power / toughness>"
    # (~36 SOLO — Bottle Golems / Angelic Chorus / Weed Strangle [clash] / …).
    # MEC-49: "that creature's <char>" on a *group* trigger — "Whenever a creature dealt damage by ~ this turn
    # dies, you gain life equal to **that creature's toughness**." (Abattoir Ghoul) reads the same firing-event
    # subject as the `its`-pronoun row, so the wordier form is the same builder.
    *subject_handlers([
        ("gain_life_eq_its_self", "self", _GAIN_LIFE_EQ_ITS_RE, _gain_life_eq_its_self),
        ("gain_life_eq_its_group", "group", _GAIN_LIFE_EQ_ITS_RE, _gain_life_eq_its_group),
        ("gain_life_eq_that_prev", "previous", _GAIN_LIFE_EQ_THAT_RE, _gain_life_eq_that_prev),
        ("gain_life_eq_that_group", "group", _GAIN_LIFE_EQ_THAT_RE, _gain_life_eq_its_group),
    ]),
    # "When ~ dies, [you gain life and] draw cards equal to its power."
    # (Lifeblood Hydra) — the combined row tried first so its "you gain
    # life and " prefix isn't left dangling by the bare draw row.
    EffectHandler(
        "gain_life_and_draw_eq_its_self", _GAIN_LIFE_AND_DRAW_EQ_ITS_RE,
        _gain_life_and_draw_eq_its_self, requires=ClauseReading(self_subject=True),
    ),
    EffectHandler(
        "draw_eq_its_self", _DRAW_EQ_ITS_RE, _draw_eq_its_self, requires=ClauseReading(self_subject=True),
    ),
    # PAR-115: "destroy/exile/counter/return/tap `<X>`. its controller
    # `<verb>` …" — the previous clause's own controller, gated on
    # `previous_subject_only` exactly like `gain_life_eq_that_prev` above.
    EffectHandler(
        "its_controller_loses_life_unless_sac_or_discard",
        _ITS_CONTROLLER_LOSES_LIFE_UNLESS_SAC_OR_DISCARD_RE,
        _its_controller_loses_life_unless_sac_or_discard,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "its_controller_loses_life", _ITS_CONTROLLER_LOSES_LIFE_RE,
        _its_controller_loses_life, requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "its_controller_gains_life", _ITS_CONTROLLER_GAINS_LIFE_RE,
        _its_controller_gains_life, requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "its_controller_gains_life_eq_mv", _ITS_CONTROLLER_GAINS_LIFE_EQ_MV_RE,
        _its_controller_gains_life_eq_mv, requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "its_controller_draws", _ITS_CONTROLLER_DRAWS_RE,
        _its_controller_draws, requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "its_controller_discards", _ITS_CONTROLLER_DISCARDS_RE,
        _its_controller_discards, requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "its_controller_mills", _ITS_CONTROLLER_MILLS_RE,
        _its_controller_mills, requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "its_controller_mills_eq_power", _ITS_CONTROLLER_MILLS_EQ_POWER_RE,
        _its_controller_mills_eq_power, requires=ClauseReading(previous_subject=True),
    ),
    # PAR-117: the same four clauses, reusing the same regexes, gated on
    # `group_subject_only` instead — "its" is a RULE 603.1 group-subject
    # trigger's own per-firing object (Poisonbelly Ogre-shaped), not a
    # creature this same body's earlier clause targeted.
    *_its_controller_handlers(),
    # Tried before the plain `lose_life` row below (its own bare
    # `{NUMBER} life` would otherwise stop right after the digit, leaving
    # "for each spell they've cast this turn" unconsumed).
    EffectHandler(
        "lose_life_per_spell_cast_this_turn",
        _LOSE_LIFE_PER_SPELL_CAST_THIS_TURN_RE,
        _lose_life_per_spell_cast_this_turn,
    ),
    EffectHandler("lose_fraction_of_life", _LOSE_FRACTION_OF_LIFE_RE, _lose_fraction_of_life),
    EffectHandler("lose_life_that_controller", _LOSE_LIFE_THAT_CONTROLLER_RE, _lose_life_that_controller),
    # "that player loses N life for each 1 life they gained." (False Cure).
    EffectHandler(
        "lose_life_per_life_gained",
        _LOSE_LIFE_PER_LIFE_GAINED_RE,
        _lose_life_per_life_gained,
    ),
    # "you lose 2 life" / "target player loses 2 life" / "target opponent
    # loses 2 life" / "they lose 2 life" (the group-subject event's own
    # player — see `_lose_life`'s docstring).
    EffectHandler(
        "lose_life",
        compile_clause(r"(?P<who>you |target player |target opponent |they )?loses? (?P<n>\d+|x) life"),
        _lose_life,
    ),
    # RULE 202.2f/700.6 "each opponent loses X life, where X is your
    # devotion to <colour>." (Gray Merchant of Asphodel) — tried before the
    # plain digit-amount row below since "x" never matches its `NUMBER`.
    EffectHandler(
        "lose_life_selector_devotion", _LOSE_LIFE_SELECTOR_DEVOTION_RE, _lose_life_selector_devotion
    ),
    # "Each opponent loses life equal to the number of Vampires you
    # control." (Malakir Bloodwitch) — tried before the plain digit-amount
    # row below.
    EffectHandler(
        "lose_life_selector_subtype", _LOSE_LIFE_SELECTOR_SUBTYPE_RE, _lose_life_selector_subtype
    ),
    # "each opponent loses 2 life" / "each player loses 2 life" (RULE
    # 601.2c mass effect, Deathrite Shaman-shaped).
    EffectHandler(
        "lose_life_selector",
        compile_clause(rf"(?P<selector>each other player|each player|each opponent) loses? {COUNT_X} life"),
        _lose_life_selector,
    ),
    # "whenever you gain life, target opponent loses that much life."
    # (Sanguine Bond/Defiant Bloodlord-shaped) — tried before the plain
    # `lose_life` row above so "that much" wins over that row's literal
    # `NUMBER`.
    EffectHandler(
        "lose_life_from_trigger_amount",
        compile_clause(rf"{TARGET} loses that much life"),
        _lose_life_from_trigger_amount,
    ),
    # PAR-132: "each opponent gains that much life" (Grollub) -- the gain sibling of the row above, reached through
    # the player-scope slot's "target player" reading.
    EffectHandler(
        "gain_life_target_from_trigger_amount",
        compile_clause(rf"{TARGET} gains that much life"),
        lambda m: ([EffectSpec("gain_life", {"target_kind": "player", "amount_from_trigger_event": "amount"})]
                   if resolve_target_kind(m.group("target")) == "player" else None),
    ),
    # "Whenever ~ deals damage, you gain that much life." (El-Hajjâj /
    # Exalted Angel-shaped, PAR-36) — before the plain `gain_life` row so
    # "that much" wins over its literal `NUMBER`.
    EffectHandler(
        "gain_life_from_trigger_amount",
        compile_clause(r"you gain that much life"),
        _gain_life_from_trigger_amount,
    ),
    EffectHandler(
        "gain_life_spell_mv",
        compile_clause(r"gains? life equal to that spell'?s mana value"),
        _gain_life_spell_mv,
    ),
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_par71_that_spells_mana_value.py (trigger-event mana-value amount).
    EffectHandler(
        "lose_life_spell_mv_that_player",
        compile_clause(r"that player loses life equal to that spell'?s mana value"),
        _lose_life_spell_mv_that_player,
    ),
    # "you get half X rad counters, rounded up/down" (Contaminated Drink) —
    # tried before the plain shape below since its own ``n`` group would
    # otherwise never match "half x" anyway (no overlap risk either way).
    EffectHandler(
        "add_player_counters_half_x",
        compile_clause(rf"(?P<who>you |target player |defending player )?gets? half x rad counters?, "
           rf"rounded (?P<round>up|down)"),
        _add_rad_counters_half_x,
    ),
    # "you get two rad counters" / "target player gets four rad counters" /
    # "defending player gets two rad counters" / bare "get two rad
    # counters" (a "you may" prefix already peeled) — RULE 728 player
    # counters.
    EffectHandler(
        "add_player_counters",
        # PAR-148: "you get an experience counter" (RULE 122.1; Kalemne, Otharri, Zuko, Katara, …) — the same primitive.
        compile_clause(rf"(?P<who>you |target player |target opponent |defending player )?gets? (?P<n>a|an|x|\d+) (?P<kind>rad|poison|experience) counters?"),
        _add_rad_counters,
    ),
    # "each player gets three rad counters" / "each opponent gets a poison
    # counter" (RULE 601.2c mass effect).
    EffectHandler(
        "add_player_counters_selector",
        compile_clause(rf"(?P<selector>each player|each opponent) gets? (?P<n>a|an|x|\d+) (?P<kind>rad|poison) counters?"),
        _add_rad_counters_selector,
    ),
    # "target player loses all rad counters" (Survivor's Med Kit).
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_rad_counters.py (RULE 122 player-counter wipe clause).
    EffectHandler(
        "lose_all_player_counters",
        compile_clause(r"target player loses all rad counters"),
        _lose_all_rad_counters,
    ),
    # "each opponent gets a number of rad counters equal to its power"
    # (Feral Ghoul's dies trigger) — ENG-37: emits a `bind` node, not the
    # retired `dies_grants_rad_counters_equal_power` fused type.
    EffectHandler(
        "rad_counters_equal_dying_power",
        compile_clause(r"each opponent gets a number of rad counters equal to its power"),
        _dies_rad_counters_equal_power,
    ),
]
