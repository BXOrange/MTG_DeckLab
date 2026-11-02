from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gisa_the_hellraiser() -> list[AbilitySpec]:
    """Ward—{2}, Pay 2 life.
    Skeletons and Zombies you control get +1/+1 and have menace.
    Whenever you commit a crime, create two tapped 2/2 blue and black Zombie Rogue creature tokens. This ability triggers only once each turn. (Targeting opponents, anything they control, and/or cards in their graveyards is a crime.)

    — Commander Cube singleton batch. The crime trigger is the parser's own claim (`CRIME_COMMITTED`, once per turn).
    The anthem is two statics, one per subtype, so a Zombie Skeleton must be buffed once, not twice (RULE 613.7):
    Skeletons through a structured selector with ``without_subtype`` (the Death Baron shape), Zombies through the
    subtype scope. Each static pairs the +1/+1 anthem (RULE 613.1g) with the menace grant (RULE 613.1f).
    """
    skeletons = {"zone": "battlefield", "of": "you", "filter": {
        "card_type": "creature", "subtype": "skeleton", "without_subtype": "zombie"}}
    zombies = {"affects": "creatures_you_control", "subtype": "Zombie"}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 2, "power": 2, "toughness": 2, "colors": ["U", "B"], "subtypes": ["Zombie", "Rogue"], "keywords": [], "token_name": "Zombie Rogue", "tapped": True})],
            trigger={"event": EventType.CRIME_COMMITTED, "condition": {"subject": "you"}, "limit": True},
            raw_text="whenever you commit a crime, create 2 tapped 2/2 blue and black zombie rogue creature tokens. this ability triggers only once each turn.",
        ),
        AbilitySpec("static", [
            EffectSpec("anthem", {"affects": skeletons, "power": 1, "toughness": 1}),
            EffectSpec("grant_keyword", {"affects": skeletons, "keywords": ["menace"]}),
        ]),
        AbilitySpec("static", [
            EffectSpec("anthem", {**zombies, "power": 1, "toughness": 1}),
            EffectSpec("grant_keyword", {**zombies, "keywords": ["menace"]}),
        ]),
    ]


register("Gisa, the Hellraiser", _gisa_the_hellraiser)
