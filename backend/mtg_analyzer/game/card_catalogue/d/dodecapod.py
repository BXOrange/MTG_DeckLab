from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dodecapod() -> list[AbilitySpec]:
    """If a spell or ability an opponent controls causes you to discard this
    card, put it onto the battlefield with two +1/+1 counters on it instead
    of putting it into your graveyard.

    MEC-102 — see `loxodon_smiter.py`'s docstring for the shared mechanism.
    ``counters=2`` stamps the two +1/+1 counters as part of the same event
    that puts it onto the battlefield (`_discard_to_battlefield_
    replacement`).
    """
    return [
        AbilitySpec("replacement", [EffectSpec("discard_to_battlefield", {"counters": 2})]),
    ]


register("Dodecapod", _dodecapod)
