from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nova_pentacle() -> list[AbilitySpec]:
    """{3}, {T}: The next time a source of your choice would deal damage to you this turn, that damage is dealt to
    target creature of an opponent's choice instead.

    RULE 616.1c redirection, MEC-118's opponent-chosen target (RULE 601.2c): the chosen opponent picks the creature as
    the ability is put on the stack (any creature, "it doesn't have to be a creature that opponent controls" -- the
    ruling), and the activator then picks the source as it resolves.  `request_redirect_damage_source` with
    ``recipient="target"`` rewrites only damage headed for the activator (``only_to_you``).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_redirect_damage_source", {
                "once": True,
                "amount": "all", "recipient": "target", "only_to_you": True, "target_chooser": "opponent",
            })],
            cost={"text": "{3}, {T}"},
        ),
    ]


register("Nova Pentacle", _nova_pentacle)
