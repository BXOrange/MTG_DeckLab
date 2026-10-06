from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ursine_monstrosity() -> list[AbilitySpec]:
    """Trample
    At the beginning of combat on your turn, mill a card and choose an opponent at random. This creature attacks that player this combat if able. Until end of turn, this creature gains indestructible and gets +1/+1 for each card type among cards in your graveyard.

    — PLAY-ALL (Death Toll). Trample is a keyword. The beginning-of-combat head is Territorial Hellkite's; the body is `mill`, then Hellkite's
    `force_attack_unattacked_opponent` in its ``avoid_last_attacked=False`` form (a random opponent becomes the ``must_attack_player_id``
    requirement), then a `bind` measuring the distinct card types in your graveyard (after the mill) into one `pump` of +X/+X and indestructible.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("mill", {"count": 1}),
                EffectSpec("force_attack_unattacked_opponent", {"avoid_last_attacked": False}),
                EffectSpec("bind", {
                    "name": "x",
                    "amount": {"kind": "count_selector", "selector": {"zone": "graveyard", "of": "you", "distinct": "card_type"}},
                    "effects": [{"type": "pump", "params": {"power": "$x", "toughness": "$x", "keywords": ["indestructible"]}}],
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
    ]


register("Ursine Monstrosity", _ursine_monstrosity)
