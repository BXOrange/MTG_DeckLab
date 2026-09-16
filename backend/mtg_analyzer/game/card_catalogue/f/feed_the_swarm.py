from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _feed_the_swarm() -> list[AbilitySpec]:
    """Destroy target creature or enchantment an opponent controls. You
    lose life equal to that permanent's mana value.

    — Feed the Swarm. ``target_kind="permanent"`` is broader than "creature
    or enchantment an opponent controls" (no target kind unions two card
    types *and* restricts to opponents at once) — the same simplification
    tier `parser.oracle.catalogue.subgrammars`'s "target artifact or
    enchantment" → ``"permanent"`` row already uses generically; the life
    loss always hits the caster, matching the printed "you lose life".

    ENG-37: retired from `destroy_lose_life_equal_mana_value`. Unlike Swords
    to Plowshares and Nature's Claim, the recipient here needed no referent
    ("**you** lose life"), only the *amount* did — so this one is a plain
    `destroy` plus a `bind` reading the destroyed permanent's printed mana
    value (RULE 202.3, stable after it leaves — RULE 608.2h last-known
    information, which is what the welded version read too).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"target_kind": "permanent"}),
                EffectSpec("bind", {
                    "name": "mv",
                    "amount": {
                        "kind": "characteristic", "characteristic": "mana_value",
                        "of": "previous_target",
                    },
                    "effects": [
                        {"type": "lose_life", "params": {"amount": "$mv"}},
                    ],
                }),
            ],
        )
    ]


register("Feed the Swarm", _feed_the_swarm)
