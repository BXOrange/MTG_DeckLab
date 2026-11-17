"""Non-combat edict count, pool, payment and outcome grammar."""
from __future__ import annotations

import re
from typing import Optional

from ...spec import EffectSpec
from ..clause_hooks import parse_effect_body
from .shared import compile_clause, edict_pool, EffectHandler


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
#: PAR-319: the sacrificed-permanent phrase is any `edict_pool` ("a non-zombie creature", "a nonland, nontoken
#: permanent", "a creature or planeswalker", "an artifact, creature, or land"), not only a bare type word.
_EDICT_POOL = r"[a-z][a-z, '-]*?"
_SACRIFICE_EDICT_RE = compile_clause(
    rf"(?P<selector>{'|'.join(_SACRIFICE_EDICT_SELECTOR_WORDS)}) sacrifices? "
    rf"(?P<count>a|an|\d+|x) (?P<pool>{_EDICT_POOL}) of their choice"
)


def _edict_pool_params(count_word: str, pool: str) -> Optional[dict]:
    """The ``what`` / ``object_filter`` / ``count`` params of an edict's pool phrase, or ``None`` (fail closed)."""
    plural = count_word not in ("a", "an")
    resolved = edict_pool(pool, plural=plural)
    if resolved is None:
        return None
    what, flt = resolved
    # PAR-320: "x" is the spell's announced X (RULE 107.3), bound to a number by the resolver's X substitution.
    params: dict = {"what": what, "count": 1 if not plural else (count_word if count_word == "x" else int(count_word))}
    if flt:
        params["object_filter"] = flt
    return params


def _sacrifice_edict(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    pool = _edict_pool_params(m.group("count"), m.group("pool"))
    if pool is None:
        return None
    return [EffectSpec("sacrifice", {"selector": _SACRIFICE_EDICT_SELECTOR_WORDS[m.group("selector")], **pool})]


#: ENG-33: "target player/opponent sacrifices [N] [nontoken] `<what>` [of
#: their choice]" (Diabolic Edict / Chainer's Edict / Dead Drop-shaped, ~21
#: SOLO cards, and the recurring villainous-choice / vote *other* option).
#: A real RULE 115 player target (`SacrificeEffect.target_kind="player"` →
#: reads `targets[0]`), the single-target sibling of `_SACRIFICE_EDICT_RE`'s
#: `each_player`/`each_opponent` mass form.
_TARGET_PLAYER_EDICT_RE = compile_clause(
    rf"target (?P<who>player|opponent) sacrifices? "
    rf"(?P<count>a|an|\d+) (?P<pool>{_EDICT_POOL})(?: of their choice)?"
)


def _target_player_edict(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    pool = _edict_pool_params(m.group("count"), m.group("pool"))
    if pool is None:
        return None
    return [EffectSpec("sacrifice", {"target_kind": "player", **pool})]


#: PAR-320: the count shapes of an edict -- "each player sacrifices **x** lands of their choice" (Tectonic Break),
#: "target opponent sacrifices **half the** nonland permanents **they control** of their choice, **rounded down**"
#: (Lord Xander, Curse of the Cabal, Zodiark, Rakdos the Defiler) -- over PAR-319's `edict_pool`. A fraction is counted
#: per player over their own eligible pool when they choose (`SacrificeEffect.pool_fraction`; RULE 107.1a: rounded
#: down unless the card says up), so the rounding word is required rather than defaulted.
_FRACTION_WORDS: dict[str, int] = {"half": 2, "a third": 3}
_EDICT_FRACTION_PLAYER_WORDS: dict[str, dict] = {
    "each player": {"selector": "each_player"}, "each opponent": {"selector": "each_opponent"},
    "each other player": {"selector": "each_opponent"},
    "target player": {"target_kind": "player"}, "target opponent": {"target_kind": "opponent"},
    "you": {"selector": "controller"},
}
_SACRIFICE_EDICT_FRACTION_RE = compile_clause(
    rf"(?:(?P<who>{'|'.join(_EDICT_FRACTION_PLAYER_WORDS)}) sacrifices?|(?P<bare>sacrifice)) "
    rf"(?P<frac>{'|'.join(_FRACTION_WORDS)}) (?:of )?the (?P<pool>{_EDICT_POOL}) (?P<owner>they|you) control"
    r"(?: of (?:their|your) choice)?, rounded (?P<round>up|down)"
)


def _sacrifice_edict_fraction(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    who = m.group("who") or "you"
    # RULE 109.5: "you ... you control" is the controller's own pool, "they control" the sacrificing player's.
    if (who == "you") != (m.group("owner") == "you"):
        return None
    resolved = edict_pool(m.group("pool"), plural=True)
    if resolved is None:
        return None
    what, flt = resolved
    params: dict = {
        "what": what, "count": 1, **_EDICT_FRACTION_PLAYER_WORDS[who],
        "pool_fraction": {"divisor": _FRACTION_WORDS[m.group("frac")], "round_up": m.group("round") == "up"},
    }
    if flt:
        params["object_filter"] = flt
    return [EffectSpec("sacrifice", params)]


#: PAR-320: an edict followed by its "if they can't" rider -- "that player sacrifices a creature or planeswalker of their
#: choice. If the player can't, they lose 5 life." (Cruel Reality), "...a nonland, nontoken permanent ... If that player
#: can't, they discard a card, they lose 2 life, you draw a card, ..." (Doom Foretold), and the controller's own "sacrifice
#: a creature other than ~. If you can't, ~ deals 7 damage to you." (Lord / Liege of the Pit, Eldrazi Monument, Rust
#: Elemental). RULE 701.17a: a player can't sacrifice a permanent they don't control, so the rider is true for a player
#: with fewer eligible permanents than the count (`SacrificeEffect.unable_effects`, applied to that player alone).
_CANT_WHO = r"(?:they|the player|that player)"
_SACRIFICE_CANT_RE = compile_clause(
    rf"(?:(?P<who>target player|target opponent) sacrifices|(?P<bare>sacrifice)) "
    rf"(?P<count>a|an|another) (?P<pool>{_EDICT_POOL})(?P<other> other than ~)?(?P<choice> of their choice)?\. "
    rf"if (?:(?P<theirs>{_CANT_WHO})|(?P<yours>you)) can'?t(?: sacrifice [a-z ]+)?, (?P<rider>[^.]+)"
)
_RIDER_PIECE_SPLIT_RE = re.compile(r",\s*(?:then\s+)?|\s+and\s+(?=they\b|you\b|that player\b)")
_RIDER_THEY_RE = re.compile(r"^(?:they|that player) (?P<verb>lose|discard|draw|gain) (?P<rest>.+)$")
_THIRD_PERSON: dict[str, str] = {"lose": "loses", "discard": "discards", "draw": "draws", "gain": "gains"}


def _cant_rider_effects(rider: str) -> Optional[list[dict]]:
    """The serialized effects of an "if they can't" rider: a "they ..." piece is about the sacrificing player (read as
    "target player ..."), every other piece about the ability's controller. ``None`` fails closed on a piece the shared
    grammar does not read, or one that names some other target."""
    effects: list[dict] = []
    for piece in _RIDER_PIECE_SPLIT_RE.split(rider.strip().rstrip(".")):
        they = _RIDER_THEY_RE.match(piece)
        text = f"target player {_THIRD_PERSON[they.group('verb')]} {they.group('rest')}" if they else re.sub(
            r"^then ", "", piece)
        parsed = parse_effect_body(text) or (parse_effect_body(text[len("you "):]) if text.startswith("you ") else None)
        if not parsed:
            return None
        for spec in parsed:
            targeted = {k: v for k, v in spec.params.items() if "target" in k and k != "target_kind"}
            # "source" is the ability's own object ("tap ~"); "player" is the sacrificing player; nothing else is aimed.
            if targeted or spec.params.get("target_kind") not in (None, "player", "source"):
                return None
            if spec.params.get("target_kind") == "player" and not they:
                return None  # a "you ..." piece must stay the controller's
            effects.append(spec.to_dict())
    return effects


def _sacrifice_cant(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    controller = m.group("bare") is not None
    if controller != (m.group("yours") is not None):
        return None  # "that player sacrifices ... if you can't" / "sacrifice ... if they can't" name two players
    count_word = m.group("count")
    other = bool(m.group("other")) or count_word == "another"
    if (m.group("choice") is not None) == controller:
        return None  # an edict says "of their choice"; the controller's own sacrifice does not
    pool = _edict_pool_params("a" if count_word == "another" else count_word, m.group("pool"))
    rider = _cant_rider_effects(m.group("rider"))
    if pool is None or not rider:
        return None
    params: dict = {**pool, "unable_effects": rider}
    if other:
        params["exclude_source"] = True
    if controller:
        params["selector"] = "controller"
    else:
        params["target_kind"] = "opponent" if m.group("who") == "target opponent" else "player"
    return [EffectSpec("sacrifice", params)]


#: PAR-320: the edict that lets the asked player buy out -- "each opponent sacrifices a permanent of their choice
#: **unless they pay {1}**" (Rishadan Cutpurse/Footpad/Brigand), "that player sacrifices ... unless they pay {1}"
#: (Aether Barrier, Spelltithe Enforcer: the player the cast event names), "each opponent sacrifices a creature of their
#: choice unless they discard a card" (The Long Reach of Night), and the controller's own "sacrifice a permanent unless
#: you discard a card" (Bebop & Rocksteady). RULE 118.12: the asked player chooses whether to pay; if they don't (or
#: can't), the edict happens to that player alone (`each_player_pay_or` asks in turn order, the decliner is the target).
_PUNISHER_WHO: dict[str, str] = {
    "each opponent": "each_opponent", "each player": "each_player", "that player": "event_player",
    "you": "controller",
}
_SACRIFICE_UNLESS_RE = compile_clause(
    rf"(?:(?P<who>each opponent|each player|that player) sacrifices|(?P<you>sacrifice)) "
    rf"(?P<count>a|an) (?P<pool>{_EDICT_POOL})(?: of their choice)? "
    r"unless (?P<payer>they|you) (?P<cost>pay (?:\{[a-z0-9]\})+|discard a card)"
)


def _sacrifice_unless(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    pool = _edict_pool_params(m.group("count"), m.group("pool"))
    if pool is None:
        return None
    who = _PUNISHER_WHO[m.group("who") or "you"]
    cost = m.group("cost")
    if (who == "controller") != (m.group("payer") == "you"):
        return None  # "you ... unless they" / "each opponent ... unless you" name two different players
    return [EffectSpec("each_player_pay_or", {
        "cost": cost, "scope": who,
        "effects": [EffectSpec("sacrifice", {"target_kind": "player", **pool}).to_dict()],
    })]


#: "each opponent / target opponent sacrifices a creature with the greatest power among creatures they
#: control" (Crackling Doom, Gix's Command, Szat's Will, Professor Onyx's −3 — the hand-authored original) —
#: `SacrificeEffect.greatest_power` narrows the pick to the tied leaders of that player's own board.
#: …and the same edict by **mana value**, over creatures or creatures and planeswalkers, as a sacrifice or an exile
#: (Blot Out / End of the Hunt "exiles", Flare of Malice / Soul Shatter / Break Under Pressure "sacrifices"). A tie is
#: the chosen player's pick among the tied leaders (`SacrificeEffect.greatest`).
_SACRIFICE_GREATEST_POWER_RE = compile_clause(
    r"(?P<who>each opponent|target opponent|target player) (?P<verb>sacrifices|exiles) a "
    r"(?P<what>creature|creature or planeswalker) "
    r"(?:with the (?P<extreme>greatest|least) (?P<stat>power|mana value) among (?P<pool>creatures|creatures and planeswalkers) "
    r"(?:they|that player) controls?"
    r"|they control with the (?P<extreme2>greatest|least) (?P<stat2>power|mana value) among (?P<pool2>creatures|creatures and planeswalkers) "
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
    # PAR-317: "the least power among creatures they control" (Witch-king, Bringer of Ruin) is the lowest-end mirror.
    extreme = groups["extreme"] or groups["extreme2"] or "greatest"
    params: dict = {
        "what": "creature" if groups["what"] == "creature" else "creature_or_planeswalker", "count": 1,
        "least" if extreme == "least" else "greatest": stat.replace(" ", "_"),
    }
    if groups["verb"] == "exiles":
        params["action"] = "exile"
    if m.group("who") == "each opponent":
        params["selector"] = "each_opponent"
    else:
        params["target_kind"] = "player"
    return [EffectSpec("sacrifice", params)]


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


# PAR-320: coordinate player-scoped instructions without turning each player's whole
# sequence into a separate resolution (Pox / Death Cloud, RULE 608.2c).
_EDICT_SEQUENCE_RE = compile_clause(
    r"each player (?P<body>loses [^.]+)(?:\. round (?P<round>up|down) each time)?"
)


def _edict_sequence(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    pieces = re.split(r", (?:then )?", m.group("body"))
    if len(pieces) < 2 or not all(re.match(r"(?:loses|discards|sacrifices) ", p) for p in pieces):
        return None
    effects = []
    for piece in pieces:
        rounding = m.group("round")
        if rounding and re.search(r"half|a third", piece):
            piece += f", rounded {rounding}"
        # Fractional life is measured separately on each affected player.
        life = re.fullmatch(r"loses (half|a third of) their life, rounded (up|down)", piece)
        if life:
            effects.append(EffectSpec("lose_life", {
                "selector": "each_player", "amount": {"kind": "resource", "resource": "life",
                "divide": 2 if life[1] == "half" else 3, "round_up": life[2] == "up"},
                "measure_per_player": True,
            }))
        elif piece == "discards x cards":
            effects.append(EffectSpec("discard", {"scope": "each_player", "count": "x"}))
        else:
            parsed = parse_effect_body("each player " + piece)
            if not parsed:
                return None
            effects.extend(parsed)
    return effects


_OPTIONAL_EDICT_RE = compile_clause(
    rf"(?P<who>target opponent|target player|that player) may sacrifice "
    rf"(?P<count>a|an|\d+) (?P<pool>{_EDICT_POOL})(?: of their choice)?\. "
    r"if (?P<decliner>they|you|the player) (?:don't|doesn't|do not|does not), (?P<rider>.+)"
)


def _optional_edict(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    pool = _edict_pool_params(m.group("count"), m.group("pool"))
    rider = _cant_rider_effects(m.group("rider"))
    if pool is None or not rider:
        return None
    who = m.group("who")
    if m.group("decliner") == "you":
        return None
    return [EffectSpec("pay_cost_then", {
        "cost": {"sacrifice_count": [pool["count"], pool["what"]],
                 "sacrifice_filter": pool.get("object_filter")},
        "payer": "target" if who.startswith("target") else "event_player" if who == "that player" else "controller",
        **({"target_kind": "opponent" if who == "target opponent" else "player"} if who.startswith("target") else {}),
        "else_effects": rider,
    })]


_REPEAT_EDICT_RE = compile_clause(
    r"(?P<body>target opponent sacrifices a creature of their choice\. if they can't, .+)\. "
    r"then repeat this process for an enchantment and a planeswalker"
)


def _repeat_edict(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    initial = parse_effect_body(m.group("body"))
    if not initial or len(initial) != 1 or initial[0].type != "sacrifice":
        return None
    effects = [initial[0].to_dict()]
    for what in ("enchantment", "planeswalker"):
        params = {**initial[0].params, "what": what, "player": {"of": "previous_target"}}
        params.pop("target_kind", None)
        effects.append(EffectSpec("sacrifice", params).to_dict())
    return [EffectSpec("seq", {"effects": effects})]


ROWS: list[EffectHandler] = [
    EffectHandler("edict_sequence", _EDICT_SEQUENCE_RE, _edict_sequence),
    EffectHandler("optional_edict", _OPTIONAL_EDICT_RE, _optional_edict),
    EffectHandler("repeat_edict", _REPEAT_EDICT_RE, _repeat_edict),
    EffectHandler("sacrifice_greatest_power", _SACRIFICE_GREATEST_POWER_RE, _sacrifice_greatest_power),
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
    # PAR-320: "[each player|target opponent|you] sacrifice[s] half the <pool> [they|you] control ..., rounded up/down".
    EffectHandler("sacrifice_edict_fraction", _SACRIFICE_EDICT_FRACTION_RE, _sacrifice_edict_fraction),
    # PAR-320: "<who> sacrifices a <pool> of their choice unless they pay {N} / discard a card".
    EffectHandler("sacrifice_unless", _SACRIFICE_UNLESS_RE, _sacrifice_unless),
    # PAR-320: "<who> sacrifices a <pool>. If <they|you> can't, <rider>."
    EffectHandler("sacrifice_cant", _SACRIFICE_CANT_RE, _sacrifice_cant),
    EffectHandler(
        "sacrifice_controller",
        _SACRIFICE_CONTROLLER_RE,
        _sacrifice_controller,
    ),
]
