from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _selvala_s_stampede() -> list[AbilitySpec]:
    """Council's dilemma — Starting with you, each player votes for wild or free. Reveal cards from the top of your library until you reveal a creature card for each wild vote. Put those creature cards onto the battlefield, then shuffle the rest into your library. You may put a permanent card from your hand onto the battlefield for each free vote.

    — PLAY-ALL Step 2 (Temur Roar). Fateful Tempest's vote machinery (`vote` with ``per_vote_specs``, each
    entry's ``count`` scaled by that option's vote total). Wild is `reveal_until` for ``count`` creature
    cards onto the battlefield with the rest shuffled back (``library_shuffled``); free is
    `put_from_hand_onto_battlefield` for ``count`` permanent cards (the six permanent types, each pick
    optional by construction).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("vote", {
                "options": ["wild", "free"],
                "per_vote_specs": [
                    {"option": 0, "scale": 1, "effects": [{"type": "reveal_until", "params": {
                        "criteria": "creature", "count": 1, "hit_destination": "battlefield",
                        "rest_destination": "library_shuffled",
                    }}]},
                    {"option": 1, "scale": 1, "effects": [{"type": "put_from_hand_onto_battlefield", "params": {
                        "criteria": {"type": ["Land", "Creature", "Artifact", "Enchantment", "Planeswalker", "Battle"]},
                        "count": 1,
                    }}]},
                ],
            })],
        ),
    ]


register("Selvala's Stampede", _selvala_s_stampede)
