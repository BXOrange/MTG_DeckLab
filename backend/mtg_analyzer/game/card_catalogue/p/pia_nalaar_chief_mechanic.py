from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pia_nalaar_chief_mechanic() -> list[AbilitySpec]:
    """Whenever one or more artifact creatures you control deal combat damage to a player, you get {E}{E} (two energy counters).
    At the beginning of your end step, you may pay one or more {E}. If you do, create an X/X colorless Vehicle artifact token named Nalaar Aetherjet with flying and crew 2, where X is the amount of {E} paid this way.

    — PLAY-ALL (Living Energy). The trigger is the parser's group-damage head. The end-step payment is the new variable
    `pay_energy_then` (``variable``: one ``pay_x:<n>`` option per affordable amount, n binds ``"x"``) over `create_token`
    with the new ``vehicle`` flag (an Artifact — Vehicle whose X/X is its printed Vehicle P/T) and Crew 2 from its text.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"amount": 2, "kind": "energy"})],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {
                    "subject": "group", "controller": "you", "other": False,
                    "filter": {"card_type_all": ["artifact", "creature"]},
                },
                "contributors": {"min": 1},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_energy_then", {"amount": 1, "variable": True, "effects": [
                {"type": "create_token", "params": {
                    "count": 1, "power": "x", "toughness": "x", "colors": [], "subtypes": ["Vehicle"],
                    "keywords": ["flying", "Crew"], "is_artifact": True, "vehicle": True,
                    "token_name": "Nalaar Aetherjet", "oracle_text": "Flying\nCrew 2",
                }},
            ]})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Pia Nalaar, Chief Mechanic", _pia_nalaar_chief_mechanic)
