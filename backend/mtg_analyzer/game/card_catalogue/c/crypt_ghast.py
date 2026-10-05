from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _crypt_ghast() -> list[AbilitySpec]:
    """Extort
    Whenever you tap a Swamp for mana, add an additional {B}.

    — MEC-43 round 4B. Extort was parser-recognized (the keyword
    catalogue) but never bound to real behaviour — built here as a
    composition of two already-shipped primitives, not a new one:
    `PayCostThenEffect` (RULE 118.3, ``payer="controller"`` default) for
    the "you may pay {W/B}" optional payment, and `GainLifeEffect`'s
    existing ``count_selector="life_lost_this_way"`` (`GameContext.
    life_lost_this_way`, Gray Merchant of Asphodel's own RULE 119 drain
    accumulator) for "you gain **that much** life" — the total across
    every opponent, not a flat 1, which matters the moment there are 2+
    opponents. The mana ability is Wild Growth's own `EventType.
    TAPPED_FOR_MANA` triggered-mana-ability shape (RULE 605.1b), scoped by
    the ``subtypes`` filter `effect_binder._build_group_ok` already
    supports generically for any subtype word, land or creature alike
    (Burning Earth's own live "nonbasic" board check is the sibling
    precedent for a filter this event doesn't pre-stamp).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{W/B}",
                "effects": [
                    {"type": "lose_life", "params": {"amount": 1, "selector": "each_opponent"}},
                    {"type": "gain_life", "params": {"count_selector": "life_lost_this_way"}},
                ],
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"colors": ["B"]})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "type": "land", "subtypes": ["swamp"], "controller": "you"},
                "mana_ability": True,
            },
        ),
    ]


register("Crypt Ghast", _crypt_ghast)
