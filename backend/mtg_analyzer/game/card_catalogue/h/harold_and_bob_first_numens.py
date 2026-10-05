from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _harold_and_bob() -> list[AbilitySpec]:
    """Vigilance, reach
    When Harold and Bob dies, if it was a creature, return it to the
    battlefield. It's an Aura enchantment with enchant Forest you control
    and "{T}: Add three mana of any one color. You get two rad counters."
    Harold and Bob loses all other abilities.

    — Harold and Bob, First Numens. Vigilance/reach are picked up
    unconditionally (RULE 702 keyword fold-in). "If it was a creature" is a
    no-op condition given how this engine already only ever fires DIES for
    an object that was a creature (`RulesEngine._move_to_graveyard`'s own
    ``was_creature`` gate) — always true in practice, so no separate check
    is needed. The return itself is a wholly new compound shape, well
    beyond RULE 712.8's ordinary "return transformed" (which needs a real
    printed back face this card doesn't have):
    `ReturnDiesAsNewPermanentEffect`/`RulesEngine.return_dies_as_new_
    permanent` swaps the returned object's own `Card` for a synthetic Aura
    built from the quoted text right here, attached to a real RULE 115
    target ("enchant Forest you control", `targeting.py`'s new
    ``forest_you_control`` kind) — "loses all other abilities" is made
    literal by simply never re-binding the original creature's catalogue
    specs onto the new permanent. The granted "{T}: Add three mana of any
    one color. You get two rad counters." is a genuine compound mana
    ability (`game/mana_abilities.py`'s ``self_rad_counters`` rider,
    alongside fixing a latent "any one color" amount bug — the parser
    always produced 1 mana regardless of a printed fixed count > 1, since
    no card before this one printed one) — read live off the synthetic
    card's own oracle text, no further hand-authoring needed for it.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_dies_as_new_permanent", {
                "new_type_line": "Enchantment — Aura",
                "new_oracle_text": "Enchant Forest you control\n{T}: Add three mana of any "
                                   "one color. You get two rad counters.",
                "target_kind": "forest_you_control",
            })],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
        ),
    ]


register("Harold and Bob, First Numens", _harold_and_bob)
