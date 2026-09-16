from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ajani_nacatl_pariah() -> list[AbilitySpec]:
    """Ajani, Nacatl Pariah // Ajani, Nacatl Avenger (Legendary Creature —
    Cat Warrior, {1}{W})

    "When Ajani enters, create a 2/1 white Cat Warrior creature token.
    Whenever one or more other Cats you control die, you may exile Ajani,
    then return him to the battlefield transformed under his owner's
    control."

    The ETB token is already parser-claimable as-is. The transform trigger
    reuses `ExileReturnTransformedEffect` (RULE 400.7/712.8, built for
    Ayara/Clive/Jin-Gitaxias) completely unchanged — untargeted and always
    self, exactly this shape. **Documented simplification**: a group DIES
    trigger fires once per dying Cat rather than once per simultaneous
    batch (RULE 603.3b's stricter "one or more" reading isn't modeled),
    self-limiting in practice since the first firing exiles Ajani, and
    every further firing that turn finds no source left to act on.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "create_token",
                    {"count": 1, "power": 2, "toughness": 1, "colors": ["W"],
                     "subtypes": ["Cat", "Warrior"], "keywords": [], "token_name": "Cat Warrior"},
                )
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_return_transformed", {})],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "group", "controller": "you", "subtypes": ["cat"]},
            },
            optional=True,
        ),
    ]


register("Ajani, Nacatl Pariah", _ajani_nacatl_pariah)
