from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _liliana_dreadhorde_general() -> list[AbilitySpec]:
    """Whenever a creature you control dies, draw a card.
    +1: Create a 2/2 black Zombie creature token.
    −4: Each player sacrifices two creatures of their choice.
    −9: Each opponent chooses a permanent they control of each permanent
    type and sacrifices the rest.

    — Liliana, Dreadhorde General. The first three abilities are exactly
    what the oracle-text parser already claims (`author_card.py reuse`) —
    pasted as-is. Only the -9 needed a hand-written spec: reframed as
    "sacrifice all but one of each type, one type at a time" —
    `EffectSpec("sacrifice", {"selector": "each_opponent", "what": <type>,
    "count": "all_but_one"})`, `effects.SacrificeEffect`'s dynamic
    ``"all_but_one"`` count sentinel (`RulesEngine.sacrifice`) — six
    separate top-level effects, one per RULE 300-ish permanent type,
    relying on `_apply_effects_partitioned`'s existing "suspend the rest
    when one effect opens a pending_choice" sequencing (RULE 608.2) to run
    them one at a time rather than a bespoke chaining structure.

    Documented simplification: real Liliana lets the *same* multi-typed
    permanent (an artifact creature, say) count as the kept pick for two
    different types in one settling; processing types independently in
    sequence here means a permanent spared by an earlier type's cut can
    still be swept by a later type's own cut if a *different* permanent is
    kept for that type instead. Unobservable for the overwhelming majority
    of real boards (single-typed permanents), and still strictly a choice
    each affected player makes themselves, never an auto-pick.
    """
    types = ["battle", "planeswalker", "creature", "land", "artifact", "enchantment"]
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "group", "type": "creature", "controller": "you", "other": False},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 2, "toughness": 2, "colors": ["B"],
                "subtypes": ["Zombie"], "keywords": [], "token_name": "Zombie",
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("sacrifice", {"selector": "each_player", "what": "creature", "count": 2})],
            cost={"loyalty": -4},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("sacrifice", {"selector": "each_opponent", "what": t, "count": "all_but_one"})
                for t in types
            ],
            cost={"loyalty": -9},
        ),
    ]


register("Liliana, Dreadhorde General", _liliana_dreadhorde_general)
