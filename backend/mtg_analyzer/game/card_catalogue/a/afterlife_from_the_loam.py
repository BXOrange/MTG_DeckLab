from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _afterlife_from_the_loam() -> list[AbilitySpec]:
    """Delve (Each card you exile from your graveyard while casting this spell pays for {1}.)
    For each player, choose up to one target creature card in that player's graveyard. Put those cards onto the
    battlefield under your control. They're Zombies in addition to their other types.

    — PLAY-ALL Step 2 (Sultai Arisen). Delve is a keyword fold-in. `choose_targets` with ``per_player`` announces one
    optional target per player, each scoped to *that player's* graveyard (new ``that_player_graveyard`` scope,
    RULE 601.2c); `return_from_graveyard` with ``previous_subject`` then puts the chosen cards onto the battlefield
    under your control together, and `grant_until` adds the Zombie subtype to those same cards with no duration.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("choose_targets", {
                    "kinds": ["that_player_graveyard_creature"], "count": 1, "optional": True,
                    "per_player": "players",
                }),
                EffectSpec("return_from_graveyard", {
                    "previous_subject": True, "destination": "battlefield", "under_your_control": True,
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "type_change", "params": {"add_subtypes": ["Zombie"]}},
                }),
            ],
        ),
    ]


register("Afterlife from the Loam", _afterlife_from_the_loam)
