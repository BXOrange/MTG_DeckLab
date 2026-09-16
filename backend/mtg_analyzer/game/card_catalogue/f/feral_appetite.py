from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Feral Appetite (conditional-on-what-was-exiled) + Teshar (historic)
# ===========================================================================
# Engine: binder predicate ``spell_is_historic`` (Teshar).


def _feral_appetite() -> list[AbilitySpec]:
    """Attacking Pests you control get +1/+0 and have deathtouch.
    {1}{G}: Exile target card from a graveyard. If a creature card is exiled
    this way, create a 1/1 black and green Pest creature token with "When
    this token dies, you gain 1 life."

    activated ability's conditional token needs authoring."""
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile_target_graveyard", {"target_kind": "graveyard_card"}),
                EffectSpec("create_token", {
                    "count": 1, "token_name": "Pest", "power": 1, "toughness": 1,
                    "colors": ["B", "G"], "subtypes": ["Pest"], "token_dies_gain_life": 1,
                }, condition={"previous_target_is_creature": True}),
            ],
            cost={"mana": "{1}{G}"},
        ),
    ]


register("Feral Appetite", _feral_appetite)
