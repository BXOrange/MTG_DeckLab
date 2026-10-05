from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _master_of_the_hunt() -> list[AbilitySpec]:
    """{2}{G}{G}: Create a 1/1 green Wolf creature token named Wolves of
    the Hunt. It has "bands with other creatures named Wolves of the
    Hunt." (Any creatures named Wolves of the Hunt can attack in a band as
    long as at least one has "bands with other creatures named Wolves of
    the Hunt." Bands are blocked as a group. If at least two creatures
    named Wolves of the Hunt you control, one of which has "bands with
    other creatures named Wolves of the Hunt," are blocking or being
    blocked by the same creature, you divide that creature's combat
    damage, not its controller, among any of the creatures it's being
    blocked by or is blocking.)

    — MEC-88. Hand-authored rather than widened into the parser: the
    "create a *named* token, then a follow-up sentence grants a quoted
    ability to that specific token" compound (`create_token`'s inline-
    stats grammar has no "named <X>" tail at all, confirmed via
    `parser_probe.py` — a genuinely separate, ~60-card-wide template
    family, well outside this ticket's Banding scope) is real but
    unbuilt grammar; this is the one Commander-legal card the Banding
    tail needs closed, so it gets the sanctioned singleton escape valve
    instead of new shared grammar built for a card count of one.

    The granted "bands with other creatures named Wolves of the Hunt" is
    modeled as plain Banding (`CreateTokenEffect.keywords`, `game/combat.
    py`'s `has_banding`) — the same "bands with other `<quality>`
    collapses to Banding" simplification `static_handlers.
    _quoted_ability_grant_effects_list`'s own new banding branch uses,
    for the identical reason: the quality restriction (here, "creatures
    named Wolves of the Hunt") only matters for RULE 702.22c's
    interactive attacking-band declaration, which this batch doesn't
    build (no MODELED card exercises it). RULE 702.22j/k's damage-
    assignment reroute (`game/engine/combat_mixin.py`) *is* wired and
    reachable the moment two of these tokens block/are blocked together.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1,
                "colors": ["G"], "subtypes": ["Wolf"],
                "token_name": "Wolves of the Hunt", "keywords": ["banding"],
            })],
            cost={"text": "{2}{G}{G}"},
        ),
    ]


register("Master of the Hunt", _master_of_the_hunt)
