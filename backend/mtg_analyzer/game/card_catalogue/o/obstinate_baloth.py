from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _obstinate_baloth() -> list[AbilitySpec]:
    """When this creature enters, you gain 4 life.
    If a spell or ability an opponent controls causes you to discard this
    card, put it onto the battlefield instead of putting it into your
    graveyard.

    MEC-102 — see `l/loxodon_smiter.py`'s docstring for the shared
    replacement mechanism. The ETB gain-life trigger already parsed on its
    own (`parse_oracle` claims it fine in isolation — only the replacement
    clause was unclaimed); reproduced verbatim here since hand-authoring a
    card is all-or-nothing (`card_registry.specs_for`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 4})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec("replacement", [EffectSpec("discard_to_battlefield", {})]),
    ]


register("Obstinate Baloth", _obstinate_baloth)
