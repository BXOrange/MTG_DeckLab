from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "…by exiling three other cards from your graveyard in addition to paying its other costs."
_GRAVEYARD_CARDS_EXILED = 3


def _kotis_sibsig_champion() -> list[AbilitySpec]:
    """Once during each of your turns, you may cast a creature spell from your graveyard by exiling three other cards
    from your graveyard in addition to paying its other costs.
    Whenever one or more creatures you control enter, if one or more of them entered from a graveyard or was cast
    from a graveyard, put two +1/+1 counters on Kotis.

    — PLAY-ALL Step 2 (Sultai Arisen). The permission is a `graveyard_cast_permission` for creature spells, once per
    turn, active on your turn only, with the new ``exile_graveyard_cards`` additional cost (the engine takes the
    oldest three other graveyard cards — documented simplification: no pick is offered). The counters are a RULE 603.2c
    batch trigger over your creatures entering (the same members one at a time would be a per-creature trigger), each
    counted when it entered from a graveyard or its spell was cast from one (new ``from_zone_or_cast_from`` trigger
    key over the ENTERS event's ``from_zone``/``cast_from_zone``).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_cast_permission", {
                "spell_criteria": {"type": "creature"}, "once_per_turn": True,
                "exile_graveyard_cards": _GRAVEYARD_CARDS_EXILED, "active_if": {"kind": "your_turn"},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 2, "kind": "+1/+1"})],
            trigger={
                "event": "EVENT_BATCH",
                "condition": {
                    "subject": "group", "controller": "you", "other": False, "filter": {"card_type": "creature"},
                },
                "batch": {"of": EventType.ENTERS_BATTLEFIELD, "min": 1},
                "from_zone_or_cast_from": "graveyard",
            },
        ),
    ]


register("Kotis, Sibsig Champion", _kotis_sibsig_champion)
