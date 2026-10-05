from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _amphin_mutineer() -> list[AbilitySpec]:
    """When this creature enters, exile up to one target non-Salamander creature. That creature's controller creates a
    4/3 blue Salamander Warrior creature token.
    Encore {4}{U}{U} ({4}{U}{U}, Exile this card from your graveyard: For each opponent, create a token copy that
    attacks that opponent this turn if able. They gain haste. Sacrifice them at the beginning of the next end step.
    Activate only as a sorcery.)

    — PLAY-ALL Step 2 (Sultai Arisen). Encore is the keyword catalogue's fold-in. The ETB is Resculpt's `exile` →
    `create_token` (``creators="previous_target_controller"``, RULE 608.2h) with an optional target whose creature
    filter excludes the Salamander subtype. With no target chosen no token is made ("up to one").
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "exile", "params": {
                    "target_kind": "creature", "optional": True, "creature_filter": {"without_subtype": "salamander"},
                }},
                {"type": "create_token", "params": {
                    "power": 4, "toughness": 3, "colors": ["U"], "subtypes": ["Salamander", "Warrior"], "token_name": "Salamander Warrior",
                    "creators": "previous_target_controller",
                }},
            ]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Amphin Mutineer", _amphin_mutineer)
