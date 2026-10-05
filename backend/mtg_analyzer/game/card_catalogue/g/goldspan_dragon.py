from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _goldspan_dragon() -> list[AbilitySpec]:
    """Flying, haste
    Whenever this creature attacks or becomes the target of a spell,
    create a Treasure token.
    Treasures you control have "{T}, Sacrifice this artifact: Add two
    mana of any one color."

    — Goldspan Dragon. Flying/haste are keywords, already covered by the
    parser's keyword catalogue. The compound "attacks or becomes the
    target of a spell" trigger is two `AbilitySpec`s (MEC-19's
    `EventType.BECOMES_TARGET` added the second — same "one AbilitySpec
    per event" idiom `_SELF_MULTI_EVENT_RE`/Matoya, Archon Elder's "you
    scry or surveil" use for a compound RULE 603.1 condition), not a
    generalized "attacks or becomes the target of a spell [an opponent
    controls]" parser grammar — only Goldspan Dragon and Tectonic Giant
    print this exact compound (Giggling Skitterspike's own 3-way "attacks,
    blocks, or becomes the target of a spell" is a third, still wider
    shape), too narrow a family to be worth a general regex over two
    hand-authored entries.

    MEC-25 closed this card's own documented simplification: the granted
    ability now upgrades Treasure's printed one-mana version to the real
    printed two — `effects.grant_mana_ability`'s new ``cost`` param
    (`continuous._apply_layer_6_ability`'s ``mana_ability_cost`` handling)
    lets a grant carry a non-``{T}``-only cost and *replace* a matching
    printed ability instead of adding an independent second one (see
    `mana_abilities.mana_abilities_for`'s replace-matching). ``mana`` is
    the same 5-option "any one colour" menu shape `mana_abilities.
    _parse_clause` builds for Treasure's own printed text, just at amount 2.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={
                "event": EventType.BECOMES_TARGET,
                "condition": {"subject": "self"},
                "filter": {"item_kind": "spell"},
            },
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "permanents_you_control",
                "subtype": "Treasure",
                "cost": {"text": "{T}, Sacrifice this artifact"},
                "mana": [{color: 2} for color in ("W", "U", "B", "R", "G")],
            })],
        ),
    ]


register("Goldspan Dragon", _goldspan_dragon)
