"""Segmenter: condition riders (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from ..catalogue.clause_reading import (
    ClauseReading,
    EXILED_REFERENT,
    PLAYER,
    REVEALED_REFERENT,
    Referent,
    STANDALONE,
    TARGET,
)
from typing import Any, Optional
from ..catalogue.count_phrase import parse_amount_phrase
from ..spec import EffectSpec
from .activation_clauses import RESOLUTION_ORDINALS
from .late import bind_x_specs, parse_effect_body

def resolution_count_condition(match: "re.Match[str]") -> dict[str, Any]:
    low = RESOLUTION_ORDINALS[match.group("ord").lower()]
    high = RESOLUTION_ORDINALS[(match.group("ord2") or match.group("ord")).lower()]
    return {"kind": "ability_resolution_count", "min": low, "max": high}


FIRST_COMBAT_PHASE_CONDITION_RE = re.compile(
    r"^if it'?s the first combat phase of the turn,\s*(?P<rest>.+)$", re.IGNORECASE,
)

#: RULE 701.52a's Ring-bearer intervening-if, two printed shapes (Tales of
#: Middle-earth): "if you chose a creature **other than** ~ as your
#: Ring-bearer" (Aragorn, Company Leader/Faramir, Field Commander/Galadriel
#: of Lothlórien/Gandalf, Friend of the Shire — ``is_ring_bearer=False``)
#: and Frodo, Adventurous Hobbit's own compound "if ~ **is** your
#: Ring-bearer and the Ring has tempted you N or more times this game" —
#: one `EffectSpec.condition` dict carrying *both*
#: ``"is_ring_bearer"``/``"ring_tempted_at_least"`` keys, which
#: `effects.ConditionalEffect._condition_holds`'s AND-fold requires
#: together (the primitive built for exactly this card).
#: Both tolerate an optional leading "then " — `CONNECTORS`' period-split
#: (tried before its own ",? then " connector, since it's earlier in that
#: tuple and already yields 2+ parts on "…tempts you. Then if ~ is…") lands
#: a literal "Then " prefix on the second half, which neither regex would
#: otherwise expect.
RING_BEARER_OTHER_CONDITION_RE = re.compile(
    r"^(?:then )?if you chose a creature other than ~ as your ring-bearer,\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
RING_BEARER_AND_TEMPTED_CONDITION_RE = re.compile(
    r"^(?:then )?if ~ is your ring-bearer and the ring has tempted you (?P<n>\d+) or more "
    r"times this game,\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

#: "if you don't control a Food, `<effect>`." (Butterbur, Bree Innkeeper-
#: shaped upkeep/end-step "keep a permanent type replenished" payoffs) —
#: same "wrap the rest, tag the condition" idiom as `_LIFE_GAINED_THIS_
#: TURN_CONDITION_RE`, onto `ConditionalEffect`'s new
#: ``"controls_none_of_type"`` key. Scoped to the same closed named-token
#: vocabulary `catalogue.effect_rows.shared.NAMED_TOKEN_WORDS`/`segmenter._
#: SACRIFICE_TYPE_TRIGGER_RE` already trust (Treasure/Clue/Food) rather
#: than an arbitrary noun — a fail-closed choice, not a card-count one.
CONTROLS_NONE_OF_TYPE_CONDITION_RE = re.compile(
    r"^if you don'?t control an? (?P<type>treasure|clue|food),\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

#: PAR-30: "if there's a `<subtype>` card in your graveyard, `<effect>`."
#: (Walltop Sentries — "when ~ dies, if there's a lesson card in your
#: graveyard, you gain 2 life.") — the trigger intervening-if sibling of
#: the `subtype_in_graveyard` static gate, onto `ConditionalEffect`'s
#: already-built ``"graveyard_has_type"`` key (a live type-line scan). One
#: subtype word, so it can't swallow a "N or more cards" count phrasing.
GRAVEYARD_HAS_SUBTYPE_CONDITION_RE = re.compile(
    r"^if there(?:'s| is| are) an? (?P<sub>[a-z][a-z-]+) card in your graveyard,\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

#: The pre-daybound Innistrad **werewolf** day/night check (RULE 603.4
#: intervening-if — ~26 front faces + their backs): "if no spells were cast
#: last turn, transform ~." (front → werewolf) and its mirror "if a player
#: cast 2 or more spells last turn, transform ~." (back → human). Same
#: "wrap the rest, tag the condition" idiom as the rows above, onto
#: `effects.ConditionalEffect`'s ``"no_spells_cast_last_turn"`` /
#: ``"two_or_more_spells_cast_last_turn"`` keys, which read
#: `GameState._last_turn_spell_count` — the same field
#: `RulesEngine.apply_day_night_turn_check` (RULE 732.2a/2b) already uses
#: for the daybound/nightbound successor mechanic.
WEREWOLF_NO_SPELLS_CONDITION_RE = re.compile(
    r"^if no spells were cast last turn,\s*(?P<rest>.+)$", re.IGNORECASE,
)
WEREWOLF_TWO_SPELLS_CONDITION_RE = re.compile(
    r"^if a player cast (?:2|two) or more spells last turn,\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

#: RULE 701.30d's "clash with an opponent. **if you win**, `<effect>`.
#: **otherwise**, `<effect>`." branch (PAR-29) — same "wrap the rest, tag the
#: condition" idiom as `KICKED_CONDITION_RE`, onto `effects.
#: ConditionalEffect`'s ``"clash_won"`` key. The `CONNECTORS` period-split
#: hands each of "clash with an opponent" / "if you win, …" / "otherwise, …"
#: to `parse_effect_body` separately; `_clash` (handlers.py) claims the
#: first, these two the rest. "if you won" (past tense — Entangling Trap's
#: "whenever you clash, … if you won, …", where the clash is the trigger)
#: reads the firing `CLASHED` event instead, handled by the same condition
#: key. "otherwise" carries no explicit "clash" word, so it's deliberately
#: only recognised as a *split part* here (a top-level body never starts
#: with a bare "otherwise") and fails closed if its `<effect>` isn't
#: modelled — and `ConditionalEffect` refuses it anyway when no clash is in
#: scope.
IF_YOU_WIN_CLASH_RE = re.compile(
    r"^if you w(?:in|on)(?: the clash)?,\s*(?P<rest>.+)$", re.IGNORECASE,
)
OTHERWISE_RE = re.compile(
    r"^otherwise,\s*(?P<rest>.+)$", re.IGNORECASE,
)

#: RULE 705 (PAR-151): "flip a coin. **if you win the flip**, `<effect>`. **if you lose the
#: flip**, `<effect>`." — the clash idiom for coin flips: sibling specs gated on the
#: ``coin_won`` condition (the outcome `CoinFlipEffect` left on `GameContext.coin_outcome`),
#: "lose" being its negation. "if the coin comes up heads/tails" is the same two outcomes
#: spelled by face (heads = a won flip, `RulesEngine.coin_flip`'s ``True``).
COIN_FLIP_RESULT_RE = re.compile(
    r"^if (?:you (?P<res>win|lose|won|lost) (?:the|a) (?:coin )?flip"
    r"|(?:the coin|it) comes up (?P<face>heads|tails)),\s*(?P<rest>.+)$",
    re.IGNORECASE,
)


def coin_flip_condition(m: "re.Match[str]") -> dict[str, Any]:
    won = {"kind": "coin_won"}
    outcome = (m.group("res") or m.group("face")).lower()
    return won if outcome in ("win", "won", "heads") else {"kind": "not", "condition": won}


#: RULE 706 (PAR-147): a die roll's outcome as a branch condition — "if the result is 3 or less, `<effect>`",
#: "if you roll a 6, …", "if you rolled 2, 3, or 12, …", "if both results are the same, …", "if any of those
#: results was 10 or higher, …" and the "On a 3 or 4, `<effect>`." spelling. The roll leaves its kept dice on
#: `GameContext.die_results` / ``die_result`` (the sum, "the result"), so the gate is an ordinary
#: ``amount_compare`` over that amount — sibling specs gated on it announce their own targets at cast
#: (RULE 601.2c) exactly like the ``coin_won`` branches, and "otherwise" is the negated gate.
_DIE_VALUE_LIST = r"\d+(?:, \d+)*(?:,? or \d+)?(?: or (?:less|lower|fewer|more|higher|greater))?"
DIE_IF_RE = re.compile(
    r"^if (?P<cond>(?:the (?:result|roll) (?:is|was) (?:a )?(?P<rvals>" + _DIE_VALUE_LIST + r")"
    r"|the (?:result|roll) (?:is|was) equal to or (?P<eqdir>less|more|greater) than (?P<amt>the number of [^,]+?)"
    r"|you (?:a )?roll(?:ed)? (?:a )?(?P<yvals>" + _DIE_VALUE_LIST + r")(?: exactly)?"
    r"|you rolled (?P<face>\d+) exactly (?P<times>\d+) times"
    r"|(?P<same>both results are the same|you rolled doubles)"
    r"|any of those results was (?P<anyvals>\d+ or (?:higher|more|greater|lower|less)))),\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
DIE_ON_A_RE = re.compile(
    r"^on an? (?P<rvals>" + _DIE_VALUE_LIST + r"),\s*(?P<rest>.+)$", re.IGNORECASE,
)
_DIE_DIRECTION_OPS = {
    "less": "le", "lower": "le", "fewer": "le", "more": "ge", "higher": "ge", "greater": "ge",
}


def _die_compare(op: str, right: "dict[str, Any]") -> "dict[str, Any]":
    return {"kind": "amount_compare", "left": {"kind": "die_result"}, "right": right, "op": op}


def _die_value_condition(values: str) -> "Optional[dict[str, Any]]":
    """"3 or less" / "6" / "2, 3, or 12" / "7 or 11" → the ``die_result`` gate for that value list."""
    direction = re.search(r" or (less|lower|fewer|more|higher|greater)$", values)
    if direction is not None:
        number = values[: direction.start()]
        if not number.isdigit():
            return None
        return _die_compare(_DIE_DIRECTION_OPS[direction.group(1)], {"kind": "fixed", "amount": int(number)})
    numbers = [int(n) for n in re.findall(r"\d+", values)]
    if not numbers:
        return None
    equals = [_die_compare("eq", {"kind": "fixed", "amount": n}) for n in numbers]
    return equals[0] if len(equals) == 1 else {"kind": "any", "conditions": equals}


def die_result_condition(m: "re.Match[str]") -> "Optional[dict[str, Any]]":
    groups = m.groupdict()
    if groups.get("times"):
        # "if you rolled 6 exactly seven times": the number of kept dice showing that face.
        return {
            "kind": "amount_compare", "op": "eq",
            "left": {"kind": "die_results", "which": "equal", "value": int(groups["face"])},
            "right": {"kind": "fixed", "amount": int(groups["times"])},
        }
    if groups.get("same"):
        return {"kind": "rolled_doubles"}
    if groups.get("anyvals"):
        number, _, direction = groups["anyvals"].partition(" or ")
        return {"kind": "any_die_result", "op": _DIE_DIRECTION_OPS[direction], "value": int(number)}
    if groups.get("amt"):
        counted = parse_amount_phrase(groups["amt"])
        if counted is None:
            return None
        return _die_compare(
            "le" if groups["eqdir"] == "less" else "ge", {"kind": "count_selector", "selector": counted},
        )
    return _die_value_condition(groups.get("rvals") or groups.get("yvals") or "")


_THAT_MUCH_RE = re.compile(r"\bthat much\b", re.IGNORECASE)


def die_that_much_specs(
    rest: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """"…, you lose **that much** life" / "~ deals **that much** damage to you" after a die gate — "that much" is
    the result just rolled (the gate's own roll), so it reads as X bound to ``die_result``."""
    if _THAT_MUCH_RE.search(rest) is None:
        return None
    return bind_x_specs(
        _THAT_MUCH_RE.sub("x", rest), {"kind": "die_result"}, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject, previous_selector=False),
    )


def _is_die_gate(condition: "Optional[dict[str, Any]]") -> bool:
    """Whether ``condition`` only reads this resolution's die roll (a fact no sibling branch changes)."""
    if not condition:
        return False
    kind = condition.get("kind")
    if kind in ("rolled_doubles", "any_die_result"):
        return True
    if kind == "amount_compare":
        return (condition.get("left") or {}).get("kind") in ("die_result", "die_results")
    if kind in ("any", "all"):
        subs = condition.get("conditions") or []
        return bool(subs) and all(_is_die_gate(sub) for sub in subs)
    return False


def otherwise_specs(
    rest: str, preceding: "list[EffectSpec]", *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """"…`<A>` if `<condition>`. **Otherwise**, `<B>`." → the ``if_else`` that replaces `<A>`.

    `<B>` runs exactly when `<A>`'s gate did not hold, whatever it was (RULE 701.30d's "if you
    win the clash" is one case). The gate has to be *decided once*, before either branch runs:
    "draw a card if you have no cards in hand, otherwise discard" must not re-read the hand
    after the draw — hence one node rather than a second, negated gate. The preceding clause
    must carry a condition; without one there is nothing "otherwise" could mean, so the body
    stays unclaimed rather than guessed at."""
    if not preceding:
        return None
    gate = preceding[0].condition
    if gate is None or any(spec.condition != gate for spec in preceding):
        return None
    inner = parse_effect_body(rest, reading=reading)
    if not inner or any(spec.condition is not None for spec in inner):
        return None
    if gate in ({"kind": "clash_won"}, {"kind": "coin_won"}) or _is_die_gate(gate):
        # RULE 701.30d's clash outcome (and RULE 705's flip outcome) is a fact of the resolution
        # that no branch changes, so the two gated lists it always had are equivalent — and the
        # gated siblings announce their own targets (RULE 601.2c), which `if_else` cannot.
        negated = {"kind": "not", "condition": gate}
        return list(preceding) + [
            EffectSpec(spec.type, dict(spec.params), condition=negated) for spec in inner
        ]
    return [EffectSpec("if_else", {
        "condition": gate,
        "then": [EffectSpec(spec.type, dict(spec.params)).to_dict() for spec in preceding],
        "else": [spec.to_dict() for spec in inner],
    })]


#: MEC-50: "`<process>`, then clash with an opponent. If you win, **repeat
#: this process**." (Hoarder's Greed) — the win branch loops the *whole*
#: preceding process (`RepeatProcessEffect`, capped), not a fresh clause,
#: so it can't ride the generic `IF_YOU_WIN_CLASH_RE` peel (which appends
#: a condition-gated sibling). ``process`` is parsed recursively; a bare
#: `clash` is appended so the loop's own re-clash runs each pass.
CLASH_REPEAT_PROCESS_RE = re.compile(
    r"^(?P<process>.+?),\s*then clash with an opponent\.\s*"
    r"if you w(?:in|on), repeat this process$",
    re.IGNORECASE | re.S,
)

#: MEC-50: "Clash with an opponent, then return target creature to its
#: owner's hand. **If you win, you may put that creature on top of its
#: owner's library instead**." (Whirlpool Whelm) — the win branch
#: *overrides the destination* of the earlier bounce rather than adding an
#: effect (and "that creature" would be a stale RULE 400.7 reference after
#: the hand move), so it's folded into `ReturnToHandEffect.to_library_top_
#: if_clash_won` on the one bounce spec.
CLASH_BOUNCE_OR_LIBRARY_RE = re.compile(
    r"^clash with an opponent, then return target creature to its owner'?s hand\.\s*"
    r"if you w(?:in|on), you may put (?:that creature|it) on top of its owner'?s "
    r"library instead$",
    re.IGNORECASE | re.S,
)

#: PAR-30 Suspect one-off shapes / RULE 701.60c: "choose up to one target
#: creature. If it's suspected, exile it. Otherwise, suspect it." (Agrus
#: Kos, Spirit of Justice) — an if/else over the chosen creature's own
#: suspected state, emitted as two mutually complementary condition-gated
#: specs (the `IF_YOU_WIN_CLASH_RE`/`clash_won` idiom). The exile branch
#: carries the RULE 115 ``target_spec`` ("up to one" ⇒ ``optional``); the
#: "otherwise, suspect it" branch reads that same creature back off
#: `GameContext.previous_targets`. Deliberately the exact printed template
#: only — a card that swapped the two branch bodies is a new shape.
CHOOSE_TARGET_IF_SUSPECTED_RE = re.compile(
    r"^choose up to (?:1|one) target creature\.\s*"
    r"if it'?s suspected, exile it\.\s*otherwise, suspect it$",
    re.IGNORECASE,
)

#: "Destroy target X. It can't be regenerated." (Terminate/Doom Blade's
#: mass/multi/filtered siblings — Death Bomb, Big Game Hunter, Cruel
#: Revival, …) — the single most repeated removal-spell tail in the cache
#: (110 cards SOLO-blocked on it alone, `parser_probe.py blocked`). Unlike
#: every wrapper above, this doesn't prefix-condition the *rest* of the
#: body — it's a trailing sentence that retroactively modifies whichever
#: `destroy` clause came before it (RULE 701.16's "can't be regenerated"
#: shield-denial is a property of *that* destruction, not a free-standing
#: effect), so `parse_effect_body` special-cases it below instead of
#: reaching `match_clause`/the connector-split loop: split on this
#: sentence, parse "before"/"after" independently, then set
#: ``can_be_regenerated: False`` on the last "destroy" spec `before`
#: produced. Deliberately requires the sentence to stand alone (end of
#: body, or followed by its own ``. ``-bounded sentence) — "…it can't be
#: regenerated **this turn**" (Orcish Healer/Carbonize-shaped) is a
#: genuinely different, free-standing prevent-regeneration effect and must
#: NOT match here.
#:
#: PAR-214: the rider also reads as a clause of the same sentence ("destroy target Knight **and it** can't be
#: regenerated"), names a non-creature referent, or points back at the destruction ("a creature destroyed this
#: way can't be regenerated", Damn). The last form is only claimed when exactly the destroy it qualifies exists.
_NO_REGEN_WHO = (
    r"it|they|that creature|the creature|that permanent|that land|that artifact|those creatures"
    r"|(?:an?|each) (?:creature|permanent|artifact|land) destroyed this way"
    r"|(?:creature|permanent|artifact|land)s destroyed this way"
)
NO_REGEN_SENTENCE_RE = re.compile(
    rf"^(?P<before>.+?)(?:\.\s*|,? and )(?P<who>{_NO_REGEN_WHO}) can'?t be regenerated"
    r"(?:\.\s*(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)
#: The plural subjects: a rider that qualifies every destruction of a shared verb ("destroy A and B. They ...").
NO_REGEN_PLURAL_RE = re.compile(r"^(?:they|those creatures|(?:creature|permanent|artifact|land)s destroyed this way)$", re.IGNORECASE)
NO_REGEN_THIS_WAY_RE = re.compile(r"destroyed this way$", re.IGNORECASE)
#: Wrapper nodes whose last effect is what the wrapper's effect ends on (object-phrase composition, PAR-210).
_DESTROY_WRAPPERS = frozenset({"seq", "for_each", "trigger_subject_referent"})


def last_destroy_denying_regeneration(node: dict) -> Optional[dict]:
    """``node`` (an `EffectSpec` dict) with ``can_be_regenerated: False`` on the destroy it ends in, else ``None``.

    RULE 701.19c: the rider qualifies the destruction that immediately precedes it, which the object-phrase
    composition may have wrapped in a target announcement or iteration (`seq` / `for_each`)."""
    if node.get("type") == "destroy":
        return {**node, "params": {**(node.get("params") or {}), "can_be_regenerated": False}}
    if node.get("type") == "if_else" and (node.get("params") or {}).get("then"):
        # A resolution-time condition ("destroy target creature if it's white") gates the destroy it ends in.
        then = node["params"]["then"]
        flagged = last_destroy_denying_regeneration(then[-1])
        if flagged is not None:
            return {**node, "params": {**node["params"], "then": [*then[:-1], flagged]}}
        return None
    inner = (node.get("params") or {}).get("effects")
    if node.get("type") in _DESTROY_WRAPPERS and inner:
        flagged = last_destroy_denying_regeneration(inner[-1])
        if flagged is not None:
            return {**node, "params": {**node["params"], "effects": [*inner[:-1], flagged]}}
    return None


def count_destroys(node: Any) -> int:
    if isinstance(node, dict):
        return (node.get("type") == "destroy") + sum(count_destroys(v) for v in node.values())
    if isinstance(node, list):
        return sum(count_destroys(v) for v in node)
    return 0

#: "Add {R}. **Until end of turn, you don't lose this mana as steps and phases end.**" (Brazen Collector, Savage
#: Ventmaw, Neheb, Sakiko, Avatar Roku's "until end of combat") — a trailing sentence that is a property of the mana
#: the previous clause added, so it tags that clause's `add_mana` specs with ``keep_until`` (`ManaPool.kept`)
#: rather than being an effect of its own. Anything before it that adds no mana fails closed.
KEEP_MANA_SENTENCE_RE = re.compile(
    r"^(?P<before>.+?)\.\s*until (?P<until>end of turn|end of combat), (?:you|they) don'?t lose this mana as "
    r"steps(?: and phases)? end(?:\.\s*(?P<after>.+))?\.?$",
    re.IGNORECASE | re.DOTALL,
)
KEEP_MANA_UNTIL = {"end of turn": "end_of_turn", "end of combat": "end_of_combat"}

#: PAR-109 (Desolation of Smaug, Sarkhan Fireblood, Jaya Ballard, Geosurge, Metamorphosis, Abstract Paintmage): "Add
#: {R}{R}{R}. Spend this mana only to cast instant or sorcery spells." -- RULE 106.6 / 605.3a. Like the keep-mana
#: sentence above it is a property of the mana the previous clause added, so it tags that clause's `add_mana` specs
#: with a ``restriction`` dict (the shape `game/mana_abilities._parse_restriction` builds for a printed mana ability;
#: this package cannot import `game/`, so the closed vocabulary is mirrored). Anything before it that adds no mana, or
#: a restriction outside the vocabulary, fails closed.
SPEND_MANA_SENTENCE_RE = re.compile(
    r"^(?P<before>.+?)\.\s*spend this mana only to cast (?P<what>[a-z]+(?: (?:or|and) [a-z]+)? spells|spells)"
    r"(?:\.\s*(?P<after>.+))?\.?$",
    re.IGNORECASE | re.DOTALL,
)
_SPEND_MANA_ANY_SPELL = {"kind": "spell"}
_SPEND_MANA_INSTANT_SORCERY = {"kind": "instant_or_sorcery_spell"}
#: Card-type words a "cast a(n) `<type>` spell" restriction may name (a `type_spell` restriction reads the spell's
#: types and subtypes alike through `continuous.has_subtype`).
_SPEND_MANA_TYPE_WORD_RE = re.compile(r"^[a-z]+$")


def spend_mana_restriction(what: str) -> Optional[dict[str, Any]]:
    """The restriction dict for "`<X>` spells" in "spend this mana only to cast `<X>` spells", or ``None``."""
    words = what.lower().removesuffix(" spells").removesuffix("spells").strip()
    if not words:
        return dict(_SPEND_MANA_ANY_SPELL)
    parts = re.split(r" (?:or|and) ", words)
    if parts == ["instant", "sorcery"]:
        return dict(_SPEND_MANA_INSTANT_SORCERY)
    if not all(_SPEND_MANA_TYPE_WORD_RE.match(part) for part in parts) or len(parts) > 2:
        return None
    if parts == ["creature"]:
        return {"kind": "creature_spell", "allow_ability": False}
    return {"kind": "type_spell", "types": parts, "allow_ability": False}

#: "~ deals N damage to target creature. **If that creature would die this
#: turn, exile it instead.**" (RULE 616 / 701.11 — Magma Spray / Feed the
#: Flames / Bot Bashing Time / Elspeth's Smite; also the pump form, Bleed
#: Dry's "target creature gets -13/-13 …. If that creature would die this
#: turn, exile it instead.") — the same "trailing sentence retroactively
#: modifies the previous clause's target" idiom as `NO_REGEN_SENTENCE_RE`.
#: Not a second RULE 115 target: the rider arms `grant_die_to_exile_this_
#: turn` on whatever creature the "before" clause already chose
#: (`previous_subject`, off `GameContext.previous_targets`). Fail-closed
#: unless "before" actually announces a creature/permanent target.
#: "~ deals 3 damage to any target. **If it's a creature, it can't be regenerated this
#: turn, and if it would die this turn, exile it instead.**" (Carbonize, Disintegrate) /
#: "**If this spell was kicked, that creature can't be regenerated this turn and if it
#: would die this turn, exile it instead.**" (Scorching Lava) — both riders on the hit
#: set of the damage clause before them, under one gate: "it's a creature" narrows the
#: hit set to creatures (a planeswalker or player takes the damage but neither rider);
#: any other gate becomes the specs' own `condition`.
REGEN_EXILE_RIDER_RE = re.compile(
    r"^(?P<before>.+?)\.\s*if (?P<gate>it'?s a creature|this spell was kicked),\s*(?:it|that creature)"
    r" can'?t be regenerated this turn,?\s*and if (?:it|that creature) would die this turn,"
    r" exile it instead\.?$",
    re.IGNORECASE | re.DOTALL,
)
DIE_TO_EXILE_SENTENCE_RE = re.compile(
    # PAR-62: "a creature dealt damage this way" and "that creature or
    # planeswalker" are the same rider in two more printed spellings. Safe to
    # accept because the use site already refuses a body that announced no
    # target — mass damage ("deals 3 damage to each creature") leaves nothing
    # for `previous_subject` to arm on and so fails closed there, rather than
    # arming a replacement on nobody.
    r"^(?P<before>.+?)\.\s*if (?:that creature(?: or planeswalker)?|that permanent"
    r"|an? (?:creature|permanent) dealt damage this way|it) would die this turn,"
    r" exile it instead(?:\.\s*(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)

#: MEC-82 / RULE 614: "Target creature gets -2/-2 until end of turn. **If
#: this spell was kicked, that creature gets -6/-6 until end of turn
#: instead.**" (Final Flourish / Vayne's Treachery / Explosive Growth /
#: Marsh Casualties; and the Bargain sibling — Candy Grapple). The trailing
#: sentence *replaces* the "before" pump's own P/T magnitude — it is not a
#: second additive pump — so it is stamped onto that spec as
#: `power_if_kicked`/`toughness_if_kicked` (`PumpEffect`'s
#: `DealDamageEffect.amount_if_kicked` sibling), never routed through
#: `if_else`. Fail-closed unless "before" produced a pump with a P/T
#: magnitude; the "instead … and gains <kw>" form (Colossal Growth) is
#: excluded — that is magnitude *plus* a keyword grant, more than an
#: override.
KICKED_MAGNITUDE_OVERRIDE_RE = re.compile(
    r"^(?P<before>.+?)\.\s*if this spell was (?P<cost>kicked|bargained),\s*"
    r"(?:that creature|those creatures|it) gets? "
    r"(?P<p>[+-]\d+)/(?P<t>[+-]\d+)(?: until end of turn)?\s*instead\.?$",
    re.IGNORECASE | re.DOTALL,
)

#: "Create <a token / a token copy>. **The token[s] enter[s] tapped and
#: attacking.**" (RULE 508.4 — Ghired, Kari Zev, Stangg, Living Laser) — a
#: trailing sentence that retroactively describes how the just-created
#: token(s) entered, the same `NO_REGEN_SENTENCE_RE` idiom: split it off,
#: parse "before" independently, then stamp ``tapped``/``attacking`` onto
#: the last `create_token`/`copy_permanent` spec it produced. "It"/"they"
#: are the created-token pronoun here (not a RULE 115 target).
CREATED_ENTERS_ATTACKING_RE = re.compile(
    r"^(?P<before>.+?)\.\s*"
    # subject: a pronoun for the just-made token/tokens, or the token's own
    # name (Kari Zev — "create Ragavan, …. Ragavan enters tapped and
    # attacking."). The name form is only honoured when it matches the
    # ``token_name`` of a spec the "before" half produced (handler below).
    r"(?:the tokens?|that token|those tokens|it|they"
    r"|(?P<name_subj>[a-z][a-z]+(?:\s[a-z]+){0,2})) enters?"
    r" tapped and attacking"
    # "that player"/"that opponent" (Echoing Assault) — the defender the
    # source is already attacking, derived engine-side, consumed here.
    r"(?: that (?:player|opponent))?"
    r"(?:\.\s*(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)

#: "Look at the top N cards of your library. Put M of them into your hand
#: and the rest `<destination>`." (Anticipate/Dig Through Time/Diabolic
#: Vision/Ancestral Memories-shaped — the single biggest template blocker
#: found in the whole cache, 60 cards SOLO-blocked on it alone,
#: `parser_probe.py blocked`). Two sentences that are one indivisible
#: instruction (the "look" alone and the "put" alone are each meaningless),
#: so — same idiom as `NO_REGEN_SENTENCE_RE` just above — this is a
#: `parse_effect_body`-level special case checked on the *whole* two-sentence
#: span before the ordinary connector-split loop would otherwise shatter it
#: into unmatchable halves, with an optional trailing sentence
#: (`Bitter Revelation`'s "You lose 2 life.") recursed into via `after`.
#: `RulesEngine.look_top_select` is the fixed-count sibling of scry/surveil's
#: per-card away/stay decision (`_LOOK_TOP_KINDS`) built for this. Deliberately
#: doesn't handle a *leading* clause before "look at the top…" (Creative
#: Outburst's "~ deals 5 damage to any target. Look at…") — the connector
#: loop splits that off before this check ever sees the two halves together,
#: which is a real, known, narrow gap (one card in the cache) rather than an
#: oversight; a genuinely three-way split ("put 1 into hand, 1 on the
#: bottom, and exile 1" — Expressive Iteration) correctly stays unclaimed too,
#: since the ``dest`` alternation only knows the four two-way destinations
#: real cards actually print.
LOOK_TOP_SELECT_RE = re.compile(
    r"^look at the top (?P<n>\d+|x) cards? of your library"
    r"(?:, where x is the number of (?P<removed>[a-z]+) counters removed this way"
    # MEC-143 (Hoshi Sato): "…, where X is the number of creature types among non-Borg creatures you control."
    r"|, where x is (?P<measured>the number of creature types among [^.]+?))?"
    r"(?:\.\s*|, then\s+)"
    r"put (?P<m>\d+) of (?:them|those cards) into your hand and the (?:rest|other)\s+"
    r"(?P<dest>on the bottom of your library in any order|"
    r"on the bottom of your library in a random order|"
    r"on top of your library in any order|"
    r"into your graveyard)\.?"
    r"(?:\s*(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)
LOOK_TOP_SELECT_DESTINATIONS: dict[str, tuple[str, Optional[str]]] = {
    "on the bottom of your library in any order": ("library_bottom", "any"),
    "on the bottom of your library in a random order": ("library_bottom", "random"),
    "on top of your library in any order": ("library_top", "any"),
    "into your graveyard": ("graveyard", None),
}

#: "Look at the top N cards of your library. You may put a [<subtype>]
#: creature card from among them onto the battlefield tapped and attacking.
#: [It gains <keyword> until end of turn.] Put the rest [of the cards] on
#: the bottom of your library in a random order." (RULE 508.4 — Arthur,
#: Marigold Knight; Owlbear Cub; The Joiner of Cats; **Winota, Joiner of
#: Forces / A-Winota** carry the mid-clause "It gains indestructible until
#: end of turn." interpose — v193). Emitted as an `impulsive_look` with
#: ``hit_destination="battlefield_attacking"`` — the search destination
#: `_put_searched_card` grew for the put-from-hand form (v178), which
#: enters the card tapped and calls `put_onto_battlefield_attacking`; the
#: interpose adds ``hit_grant_keywords`` (temp_keywords on the placed card).
LOOK_TOP_PUT_ATTACKING_RE = re.compile(
    r"^look at the top (?P<n>\d+) cards? of your library\.\s*"
    r"you may put an? (?P<filter>[a-z, ]+?) card from among them "
    # trailing "that player"/"that opponent" (Owlbear Cub) names the defender
    # the source is already attacking — derived engine-side, so consumed here.
    r"onto the battlefield tapped and attacking(?: that (?:player|opponent))?\.\s*"
    # optional "It gains <kw>[ and <kw>] until end of turn." (Winota) —
    # validated against `LOOK_TOP_HIT_GRANT_KEYWORDS`, fail-closed.
    r"(?:it gains (?P<hitkw>[a-z, ]+?(?: and [a-z ]+?)?) until end of turn\.\s*)?"
    r"put the rest(?: of the cards)? on the bottom of your library in a random order\.?"
    # optional else-branch: "if you don't put a card onto the battlefield
    # this way, <body>." (The Joiner of Cats) → `miss_effect_specs`. Runs to
    # end of string (no real card has both an else-branch and a trailing
    # sentence), so the `after` tail below can't also steal it.
    r"(?:\s*if you don'?t put a card onto the battlefield this way, (?P<elsebody>.+?)\.?\s*$)?"
    r"(?:\s*(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)

#: Keyword-grant tokens the ``look_top`` "It gains <kw> until end of turn."
#: interpose (Winota, Joiner of Forces) may name → engine ``temp_keywords``
#: slugs (RULE 514.2 cleanup). Deliberately the small combat-relevant set;
#: anything outside it fails the clause match closed.
LOOK_TOP_HIT_GRANT_KEYWORDS: dict[str, str] = {
    "indestructible": "indestructible",
    "haste": "haste",
    "trample": "trample",
    "flying": "flying",
    "vigilance": "vigilance",
    "lifelink": "lifelink",
    "deathtouch": "deathtouch",
    "menace": "menace",
    "first strike": "first_strike",
    "double strike": "double_strike",
    "hexproof": "hexproof",
}

#: "Gain control of target creature until end of turn. **Untap that
#: creature. It gains haste until end of turn.**" (Act of Treason/Claim the
#: Firstborn-shaped) — same "trailing sentence retroactively describing the
#: previous clause" idiom as `NO_REGEN_SENTENCE_RE` just above, not a
#: second effect: `effects.GainControlUntilEndOfTurnEffect` (built for the
#: hand-authored Zealous Conscripts) already untaps and grants haste as
#: *part of* the control change itself, so a bare "it gains haste until end
#: of turn." restatement is reprinting what the single `gain_control_until_
#: eot` effect (`catalogue.effect_rows.search_control_attach._gain_control_eot`) already does — it's
#: absorbed here rather than re-modeled.
#:
#: The ``grant`` group generalises that tail to the *richer* restatements
#: real cards pair with a threaten ("untap it. **it gains trample and haste
#: until end of turn.**" — Traitorous Blood; "…**it gains haste and myriad
#: until end of turn.**" — Firbolg Flutist): whatever is not the bare-haste
#: form recurses back through `parse_effect_body` with ``previous_subject``
#: on, so the existing `_prev_subject_singular … gains <kw> until end of
#: turn` handler (→ `pump(previous_subject=True)`, writing `temp_keywords`
#: on the just-controlled creature) claims it — no second RULE 115 target,
#: it reads `GameContext.previous_targets`. Requires the "gain control"
#: clause to be the immediately preceding sentence (anchored on "until end
#: of turn" right before the period) so this can't misfire onto an
#: unrelated creature-choosing clause followed by an unrelated genuine
#: untap effect.
GAIN_CONTROL_HASTE_TAIL_RE = re.compile(
    # PAR-204 (Eldrazi Obligator): one comma sentence, "…until end of turn, untap that creature, and it gains haste …".
    r"^(?P<before>(?:for each (?:opponent|player), )?gain control of (?:another |any number of |up to \d+ )?target .+? until end of turn)[.,]\s*"
    r"untap (?:that creature|that permanent|that artifact|those creatures|those permanents|it)[.,]?\s*(?:and\s+)?"
    r"(?P<grant>(?:it|they) gains? [a-z, ]*?haste[a-z, ]*? until end of turn"
    r"|until end of turn, (?:it|they) (?:gains?|has|have|becomes?) .+)"
    r"(?:[.,]\s*(?:and\s+)?(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)
GAIN_CONTROL_BARE_HASTE_RE = re.compile(
    r"^(?:it|they) gains? haste until end of turn$", re.IGNORECASE
)

#: PAR-277, RULE 608.2c: "<recipient> gains control of target <permanent> you control. **If they do**, `<rider>`."
#: (Bill Ferny, Rules of Acquisition) -- the rider runs only when the control change actually moved the permanent
#: (`control_changed_this_way`: a recipient who already controlled it, or an illegal target, skips it).
GIVE_CONTROL_IF_THEY_DO_RE = re.compile(
    r"^(?P<give>(?:target player|target opponent|that player|choose another player\.\s*that player) "
    r"gains control of target [^.]+?)\.\s*if they do,\s*(?P<rider>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-278, RULE 608.2d: the punisher choice -- "Target opponent may have you `<benefit>`. If they don't, `<penalty>`."
#: (Terrapact Intimidator, Combustible Gearhulk, Tell Me What You See) and "Defending player may have you `<benefit>`.
#: If they do, `<more>`." (Shakedown Heavy). The named player, not the controller, decides; saying yes gives *you* the
#: benefit, so it rides `pay_cost_then`'s paid branch with an empty (free) cost, the opponent as its ``payer``.
OPPONENT_MAY_HAVE_YOU_RE = re.compile(
    r"^(?P<who>target opponent|defending player) may have you (?P<benefit>[^.]+)\.\s*"
    r"if (?:they|that player|the player) (?P<link>don't|doesn't|does|do),?\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)
#: The deciding player's own pronoun, sentence-initially ("they lose 4 life"): rewritten to the "that player" wording
#: the RULE 608.2 player referent reads (the only verb the families below use).
_THEY_LOSE_RE = re.compile(r"^they lose\b", re.IGNORECASE)
#: The question put to the deciding player (a fixed template, never derived from card text).
_PUNISHER_PROMPT = "Soll der Kontrollierende den Vorteil erhalten? (Nein: die Folge tritt ein.)"


def punisher_choice(m: "re.Match[str]", reading: ClauseReading) -> Optional[list[EffectSpec]]:
    """`pay_cost_then` (``payer`` = the deciding player, free cost) for `OPPONENT_MAY_HAVE_YOU_RE`; ``None`` when the
    benefit or the consequence is not itself modeled (fail closed)."""
    own = ClauseReading(self_subject=reading.self_subject)
    benefit = parse_effect_body(m.group("benefit").strip() + ".", reading=own)
    if not benefit or any(s.params.get("target_kind") not in (None, "source") for s in benefit):
        return None  # a second announced target would be chosen at the wrong time
    targeted = m.group("who").lower() == "target opponent"
    declined = m.group("link").lower() in ("don't", "doesn't")
    after_text = _THEY_LOSE_RE.sub("that player loses", m.group("after").strip()) if declined else m.group("after").strip()
    after = parse_effect_body(after_text, reading=ClauseReading(
        self_subject=reading.self_subject, referents=(Referent(PLAYER),) if declined and targeted else (),
    ))
    if not after:
        return None
    consequence: list[dict[str, Any]] = []
    for spec in after:
        if spec.type == "trigger_subject_referent" and spec.params.get("referent") == "previous_player":
            # "that player ..." is the deciding player: the branch is handed that target when it runs.
            for inner in spec.params.get("effects", []):
                params = dict(inner.get("params", {}))
                if params.get("target_kind") != "player":
                    return None
                params["target_kind"] = "opponent"
                consequence.append({**inner, "params": params})
        elif spec.params.get("target_kind") not in (None, "source") or "referent" in spec.params:
            return None
        else:
            consequence.append(spec.to_dict())
    params: dict[str, Any] = {"cost": "", "effects": [s.to_dict() for s in benefit], "prompt": _PUNISHER_PROMPT}
    if targeted:
        params.update({"payer": "target", "target_kind": "opponent"})
    else:
        params["payer"] = "defending_player"
    if declined:
        params["else_effects"] = consequence
    else:
        params["effects"] = params["effects"] + consequence
    return [EffectSpec("pay_cost_then", params)]


#: PAR-316, RULE 118.12 / 608.2d: "Defending player may pay `<cost>`. If that player does, `<effect>`." (Mtenda Lion) -- the
#: defending player, not the controller, is offered the payment and only their payment triggers the effect, so it is
#: `pay_cost_then` with ``payer="defending_player"`` (the punisher choice's payer, but with a real cost). The cost is a
#: bare mana cost: that is all `_can_pay_player_cost` charges the payer's own pool for in this wording.
DEFENDING_PLAYER_MAY_PAY_RE = re.compile(
    r"^defending player may pay (?P<cost>(?:\{[wubrgc0-9]+\})+)\.\s*if (?:that player|they) (?:does|do),?\s*(?P<after>[^.]+)\.?$",
    re.IGNORECASE,
)


def defending_player_may_pay(m: "re.Match[str]", reading: ClauseReading) -> Optional[list[EffectSpec]]:
    """`pay_cost_then` paid by the defending player; ``None`` unless the payoff is a modeled untargeted effect."""
    after = parse_effect_body(m.group("after").strip() + ".", reading=ClauseReading(self_subject=reading.self_subject))
    if not after or any(s.params.get("target_kind") not in (None, "source") or "referent" in s.params for s in after):
        return None
    return [EffectSpec("pay_cost_then", {
        "cost": f"pay {m.group('cost').lower()}", "effects": [s.to_dict() for s in after], "payer": "defending_player",
    })]


#: PAR-280, RULE 101.4 / 608.2d: "Any opponent may have you put that card into your `<zone>`." -- the punisher choice put
#: to *each* opponent in turn order until one accepts (Distant Memories: "Search your library for a card, exile it, then
#: shuffle. ... If no player does, you draw three cards."; Sin Prodder: "Reveal the top card of your library. ... If a
#: player does, ~ deals damage to that player equal to that card's mana value. Otherwise, put that card into your
#: hand."). The lead names the one card ("that card"): the search leaves it exiled, the reveal leaves it on top.
ANY_OPPONENT_MAY_HAVE_YOU_RE = re.compile(
    r"^(?P<lead>search your library for a card, exile it, then shuffle|reveal the top card of your library)\.\s*"
    r"any opponent may have you put that card into your (?P<dest>hand|graveyard)\.\s*"
    r"(?:if no player does,\s*(?P<none>[^.]+)|if a player does,\s*(?P<paid>[^.]+)\.\s*otherwise,\s*(?P<other>[^.]+))$",
    re.IGNORECASE,
)
_PUT_THAT_CARD_RE = re.compile(r"^put that card into your (?P<dest>hand|graveyard)$", re.IGNORECASE)
#: The question put to each opponent (a fixed template, never derived from card text).
_ANY_OPPONENT_PROMPT = "Soll der Kontrollierende die Karte erhalten? (Nein: die Folge tritt ein.)"


def _unwrap_accepting_player(spec: dict[str, Any]) -> Optional[list[dict[str, Any]]]:
    """A parsed "that player" damage clause as the paid branch's own effect: the accepting player arrives as the
    branch target (``target_kind`` "opponent" reads it), so the ``bind``/``trigger_subject_referent`` wrappers go."""
    if spec.get("type") == "bind":
        inner = spec.get("params", {}).get("effects", [])
        out = [node for part in inner for node in (_unwrap_accepting_player(part) or [])]
        return [{**spec, "params": {**spec["params"], "effects": out}}] if out else None
    if spec.get("type") == "trigger_subject_referent" and spec.get("params", {}).get("referent") == "previous_player":
        out = []
        for inner in spec["params"].get("effects", []):
            params = dict(inner.get("params", {}))
            if params.get("target_kind") != "player":
                return None
            params["target_kind"] = "opponent"
            out.append({**inner, "params": params})
        return out or None
    return None


def any_opponent_may_have_you(m: "re.Match[str]") -> Optional[list[EffectSpec]]:
    """`all_players_decline_or` (free cost, opponents only) for `ANY_OPPONENT_MAY_HAVE_YOU_RE`; ``None`` (fail
    closed) when a branch is not itself modeled."""
    searching = m.group("lead").lower().startswith("search")
    referent = EXILED_REFERENT if searching else REVEALED_REFERENT

    def put_card(dest: str) -> list[dict[str, Any]]:
        if searching:
            # The searched card sits in exile; it joins the clause's captured referents (`previous_targets`).
            return [EffectSpec("return_to_hand", {"target_kind": None, "previous_subject": True}).to_dict()] \
                if dest == "hand" else []
        return [EffectSpec("put_revealed_card", {"destination": dest}).to_dict()]

    def branch(text: str) -> Optional[list[dict[str, Any]]]:
        put = _PUT_THAT_CARD_RE.match(text.strip())
        if put is not None:
            return put_card(put.group("dest").lower()) or None
        specs = parse_effect_body(text.strip() + ".", reading=ClauseReading(
            self_subject=True, referents=(referent, Referent(PLAYER)),
        ))
        if not specs or any(spec.params.get("target_kind") not in (None, "source", "player") for spec in specs):
            return None
        out: list[dict[str, Any]] = []
        for spec in specs:
            node = spec.to_dict()
            unwrapped = _unwrap_accepting_player(node)
            if unwrapped is None and ("referent" in node["params"] or node["params"].get("target_kind") == "player"):
                return None
            out.extend(unwrapped if unwrapped is not None else [node])
        return out

    benefit = put_card(m.group("dest").lower())
    paid = branch(m.group("paid")) if m.group("paid") else benefit
    other = branch(m.group("none") or m.group("other"))
    if not benefit or not paid or not other:
        return None
    if m.group("paid"):
        paid = benefit + paid  # "have you put that card ..." then the "if a player does" consequence
    params: dict[str, Any] = {
        "cost": "", "opponents_only": True, "paid_effects": paid, "effects": other, "prompt": _ANY_OPPONENT_PROMPT,
        "acceptor_is_target": bool(m.group("paid")),
    }
    if not searching:
        return [EffectSpec("reveal_top", {"whose": "you"}), EffectSpec("all_players_decline_or", params)]
    return [EffectSpec("search", {
        "criteria": {}, "destination": "exile", "optional": False,
        "then_specs": [EffectSpec("all_players_decline_or", params).to_dict()],
    })]
