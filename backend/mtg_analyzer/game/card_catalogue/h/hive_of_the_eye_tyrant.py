from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hive_of_the_eye_tyrant() -> list[AbilitySpec]:
    """If you control two or more other lands, this land enters tapped.
    {T}: Add {B}.
    {3}{B}: Until end of turn, this land becomes a 3/3 black Beholder creature with menace and "Whenever this creature attacks, exile target card from defending player's graveyard." It's still a land.

    Entry and mana use the existing Oracle-derived land helpers. The
    animation's type, color, keyword and attack trigger share one duration
    (RULE 611.2a); adding the creature type retains the land type.
    """
    return [AbilitySpec(
        "activated",
        [EffectSpec("grant_until", {
            "target_kind": None,
            "self_subject": True,
            "duration": "end_of_turn",
            "static": {"type": "type_change", "params": {
                "add_types": ["creature"], "add_subtypes": ["Beholder"],
                "power": 3, "toughness": 3,
            }},
            "extra_statics": [
                {"type": "color_change", "params": {"colors": ["B"], "set": True}},
                {"type": "grant_keyword", "params": {"keywords": ["menace"]}},
                {"type": "grant_triggered_ability", "params": {
                    "trigger_event": EventType.ATTACKS,
                    "grant_effects": [{"type": "exile", "params": {
                        "target_kind": "defending_graveyard_card",
                    }}],
                }},
            ],
        })],
        cost={"mana": "{3}{B}"},
    )]


register("Hive of the Eye Tyrant", _hive_of_the_eye_tyrant)
