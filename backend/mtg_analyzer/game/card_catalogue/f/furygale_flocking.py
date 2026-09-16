from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# ``per_opponent`` token creation (PAR-60)
# ===========================================================================
# `CreateTokenEffect.per_opponent` ("for each opponent, create a … token")
# already exists; Furygale Flocking is that with ``count=2``.


def _furygale_flocking() -> list[AbilitySpec]:
    """This spell costs {1} less for each instant/sorcery card in your
    graveyard (folds in from the parser).
    For each opponent, create two 3/3 blue and red Elemental creature tokens
    with flying that attack that opponent this turn if able. They gain haste
    until end of turn.

    Documented simplification: the "attack that opponent this turn if able"
    directed requirement is dropped (no turn-scoped directed must-attack
    designation for a freshly created token); the tokens keep flying + haste
    and the caster swings them. Haste is baked on rather than until-end-of-
    turn — unobservable past the turn they're made (summoning sickness)."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("create_token", {
                "count": 2, "per_opponent": True, "power": 3, "toughness": 3,
                "colors": ["U", "R"], "subtypes": ["Elemental"],
                "keywords": ["flying", "haste"], "token_name": "Elemental",
            })],
        ),
    ]


register("Furygale Flocking", _furygale_flocking)
