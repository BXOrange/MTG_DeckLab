from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kalitas_traitor_of_ghet() -> list[AbilitySpec]:
    """Lifelink
    If a nontoken creature an opponent controls would die, instead exile that card and create a 2/2 black Zombie creature token.
    {2}{B}, Sacrifice another Vampire or Zombie: Put two +1/+1 counters on Kalitas.

    — PLAY-ALL Step 2 (Wretched Ranks). Lifelink is a printed keyword; the activation is the parser's own claim.
    The replacement is the standing ``die_to_exile`` (``opponents_control``, as Corpseweaver Prodigy) with the new
    ``nontoken_only`` scope and a ``create_token`` rider the source's controller receives.
    """
    return [
        AbilitySpec("replacement", [EffectSpec("die_to_exile", {
            "subject": "opponents_control", "nontoken_only": True,
            "create_token": {"power": 2, "toughness": 2, "colors": ["B"], "subtypes": ["Zombie"],
                             "token_name": "Zombie"},
        })]),
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"count": 2, "kind": "+1/+1"})],
            cost={"text": "{2}{b}, sacrifice another vampire or zombie"},
        ),
    ]


register("Kalitas, Traitor of Ghet", _kalitas_traitor_of_ghet)
