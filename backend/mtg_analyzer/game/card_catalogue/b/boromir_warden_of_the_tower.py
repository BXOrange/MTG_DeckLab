from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _boromir_warden_of_the_tower() -> list[AbilitySpec]:
    """Vigilance
    Whenever an opponent casts a spell, if no mana was spent to cast it,
    counter that spell.
    Sacrifice Boromir: Creatures you control gain indestructible until end
    of turn. The Ring tempts you.

    — Boromir, Warden of the Tower. Shares Lavinia's ``mana_spent`` trigger
    verbatim (see her entry). Vigilance comes from the RULE 702 keyword
    catalogue, independent of this registry.

    "The Ring tempts you." (RULE 701.51a) is now real: `RulesEngine.
    the_ring_tempts_you` levels the tempting player's Ring emblem up (0–4,
    `Player.ring_level`) and re-chooses their Ring-bearer (`Player.
    ring_bearer_id`, an interactive ``ring_bearer`` `pending_choice` when
    there's more than one creature to pick). The emblem's four abilities are
    all source-less like the monarch's and the initiative's — ability 1 is a
    static split between `continuous._apply_ring_bearer_static` (legendary)
    and `GameEngine.can_block` (the greater-power blocking restriction),
    abilities 2–4 are built fresh per firing by `RulesEngine.
    _collect_ring_triggers`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("counter", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "filter": {"mana_spent": 0},
                "reflexive": True,
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0, "keywords": ["indestructible"],
                "selector": "creatures_you_control",
            }), EffectSpec("the_ring_tempts_you", {})],
            cost={"sacrifice": "self"},
        ),
    ]


register("Boromir, Warden of the Tower", _boromir_warden_of_the_tower)
