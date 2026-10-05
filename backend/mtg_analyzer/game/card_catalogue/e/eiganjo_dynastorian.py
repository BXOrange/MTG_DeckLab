from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# the "~ becomes prepared" trigger cluster (STX Learn/Prepared DFCs)
# ===========================================================================
# The `become_prepared` effect + the parser's own body handler already exist;
# only the trigger *headers* were unreachable. Engine: binder predicates
# `spell_mana_value_at_least` and `attackers_at_least`; `static_conditions`
# kinds `graveyard_card_type_count_at_least`, `any_player_cards_in_hand_at_most`.


def _eiganjo_dynastorian() -> list[AbilitySpec]:
    """Vigilance
    Whenever you attack with two or more creatures, this creature becomes
    prepared."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={"event": EventType.PLAYER_ATTACKED, "condition": {"subject": "you"},
                     "attackers_at_least": 2},
        ),
    ]


register("Eiganjo Dynastorian", _eiganjo_dynastorian)
register("Eiganjo Dynastorian // Replenish", _eiganjo_dynastorian)
