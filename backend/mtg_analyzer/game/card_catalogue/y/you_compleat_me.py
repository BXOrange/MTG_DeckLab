from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _you_compleat_me() -> list[AbilitySpec]:
    """If your life total is greater than 10, it becomes 10. For the rest of
    the game, your maximum life total is 10. You get an emblem with "Pay 2
    life: Add one mana of any color" and "At the beginning of your upkeep,
    you draw a card and you lose 1 life."

    — PAR-31 / MEC-54. A genuine singleton (the only printed "maximum life
    total is N" card), hand-authored: the oracle parser has no route for
    any of its three intertwined clauses. Pieces:

    * ``set_life`` with ``only_reduce`` — the conditional half-set (never
      raises a lower total).
    * ``set_max_life_total`` — MEC-54's permanent player-scoped cap
      (`RulesEngine.set_max_life_total` / `_max_life_total`, honoured at
      `gain_life`'s choke point).
    * one ``create_emblem`` carrying **both** quoted abilities via the new
      ``abilities`` list (`CreateEmblemEffect.abilities` /
      `RulesEngine.create_emblem`'s list branch): a `pay_life` mana ability
      (an emblem's first — RULE 605.1a keeps it off the `mana_abilities.py`
      path, so it can only live as an `ActivatedAbility` here) and the
      upkeep draw/lose-life trigger.
    """
    mana_ability = AbilitySpec(
        "activated",
        [EffectSpec("add_mana", {"colors": ["ANY"], "amount": 1})],
        cost={"text": "Pay 2 life", "pay_life": 2},
    ).to_dict()
    upkeep_ability = AbilitySpec(
        "triggered",
        [EffectSpec("draw", {"count": 1}), EffectSpec("lose_life", {"amount": 1})],
        trigger={"event": "STEP_BEGIN", "filter": {"step": "upkeep"},
                 "phase_relation": "you"},
    ).to_dict()
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("set_life", {"amount": 10, "only_reduce": True,
                                        "target_kind": None}),
                EffectSpec("set_max_life_total", {"amount": 10}),
                EffectSpec("create_emblem", {"abilities": [mana_ability, upkeep_ability]}),
            ],
        ),
    ]


register("You Compleat Me", _you_compleat_me)
