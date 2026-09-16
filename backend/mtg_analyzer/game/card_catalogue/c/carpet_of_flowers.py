from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _carpet_of_flowers() -> list[AbilitySpec]:
    """At the beginning of each of your main phases, if you haven't added
    mana with this ability this turn, you may add X mana of any one
    color, where X is the number of Islands target opponent controls.

    — Carpet of Flowers (ENG-27). Unlike Wild Growth/Kinnan just above,
    this one genuinely **targets** ("target opponent"), which RULE 605.5a
    disqualifies from ever being a mana ability at all regardless of what
    it produces — so it's an ordinary triggered ability that goes on the
    stack, not the RULE 605.4 off-stack shape. Two standing entries, one
    per main phase: the engine fires a real ``step="main1"``/``"main2"``
    event, never a generic ``"main"`` one (that spelling is `Mana Drain`'s
    own delayed-trigger-only sentinel, a different mechanism entirely).

    Both ride the same new primitives: `AddManaEffect.
    amount_from_target_count_selector` (X evaluated against the *resolved
    target*, not this permanent's own controller — `continuous.
    count_selector`'s pre-existing ``lands_you_control_of_type_island``,
    scoped to whichever opponent got picked) and `once_per_turn_ability`
    (`GameObject.added_mana_with_ability_this_turn`, reset each untap
    step). ``optional=True`` is RULE 603.5's "you may" — declining never
    puts the trigger on the stack at all, so a decline never touches the
    once-per-turn flag either, exactly matching a real "no, thanks" at the
    table. **Documented simplification**: the "if you haven't added mana…"
    gate is a resolve-time no-op rather than a full RULE 603.4
    intervening-if, so the "you may" prompt can still appear on a turn
    it would do nothing (see `AddManaEffect`'s own docstring) — no
    observable difference once resolved, since it just adds no mana either way.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {
                "colors": ["ANY"],
                "target_kind": "opponent",
                "amount_from_target_count_selector": "lands_you_control_of_type_island",
                "once_per_turn_ability": True,
            })],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": step},
                "phase_relation": "you",
            },
            optional=True,
        )
        for step in ("main1", "main2")
    ]


register("Carpet of Flowers", _carpet_of_flowers)
