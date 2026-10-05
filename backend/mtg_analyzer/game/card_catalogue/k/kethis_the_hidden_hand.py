from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kethis_the_hidden_hand() -> list[AbilitySpec]:
    """Legendary spells you cast cost {1} less to cast.
    Exile two legendary cards from your graveyard: Until end of turn, each
    legendary card in your graveyard gains "You may play this card from your
    graveyard."

    — PLAY-ALL Step 2 (SpongeBob). The discount is `cost_reduction` with the new
    ``spell_legendary`` filter (`continuous.cost_reduction_for`, RULE 205.4).
    The ability's cost ("Exile two legendary cards from your graveyard") is the
    plain `ActivationCost.exile_from_graveyard` with a ``legendary`` filter. Its
    effect is Backdraft Hellkite's turn-scoped graveyard permission
    (`grant_graveyard_cast_permission_this_turn`) widened by two params:
    ``spell_criteria`` (legendary cards, not just instants/sorceries) and
    ``plays_lands`` (a legendary *land* in the graveyard is playable too —
    "play", not just "cast" — via `graveyard_cast.graveyard_land_play_grant_for`).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "spell_legendary": True})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_graveyard_cast_permission_this_turn", {
                "spell_criteria": {"type": "Legendary"}, "instant_sorcery_only": False, "plays_lands": True,
            })],
            cost={"text": "Exile two legendary cards from your graveyard"},
        ),
    ]


register("Kethis, the Hidden Hand", _kethis_the_hidden_hand)
