from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_ur_sphinx() -> list[AbilitySpec]:
    """Eminence — As long as The Ur-Sphinx is in the command zone or on the battlefield, other Sphinx spells you cast cost {1} less
    to cast.
    Flying
    Whenever one or more Sphinxes you control attack, each player mills that many cards. For each player, you may cast a card that
    player milled this way without paying its mana cost.

    — PLAY-ALL (Multiverse Reforged). Flying is the keyword's. Eminence is a ``cost_reduction`` carrying ``from_command_zone``
    (`continuous._battlefield_static_abilities` collects the marked ability from the command zone, RULE 112.6) and
    ``other_spells``, filtered by ``spell_subtype``. The attack trigger is `ATTACKERS_DECLARED` with a Sphinx attacker filter
    (Prodigy's Prototype's head) over `mill_attackers_each_player_cast_free`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "generic": 1, "spell_subtype": "sphinx", "from_command_zone": True, "other_spells": True,
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("mill_attackers_each_player_cast_free", {"subtype": "sphinx"})],
            trigger={
                "event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"},
                "attackers_declared": {"filter": {"subtype": "sphinx"}, "min": 1},
            },
        ),
    ]


register("The Ur-Sphinx", _the_ur_sphinx)
