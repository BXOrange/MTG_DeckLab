from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _seasoned_tactician() -> list[AbilitySpec]:
    """{3}, Exile the top four cards of your library: The next time a
    source of your choice would deal damage to you this turn, prevent
    that damage.

    — Seasoned Tactician (MEC-30, Phase 8). Otherwise the ordinary Circle
    of Protection template (unqualified ``source_filter``, default
    recipient — "to you"); the cost needed `costs.py`'s
    ``exile_top_of_library`` widened from a bare bool (Thought Lash's
    always-exactly-one) to a real printed count, since
    ``_EXILE_TOP_LIBRARY_RE`` only ever recognized "the top card" —
    checked every existing caller (`game/engine/activation_mixin.py`'s
    legality/payment, `game/mana_potential.py`'s tap-plan simulation)
    before widening so Thought Lash's own behaviour doesn't regress.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"text": "{3}, Exile the top four cards of your library"},
        ),
    ]


register("Seasoned Tactician", _seasoned_tactician)
