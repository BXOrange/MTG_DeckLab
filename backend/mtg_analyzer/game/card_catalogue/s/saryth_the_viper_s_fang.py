from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _saryth_the_vipers_fang() -> list[AbilitySpec]:
    """Other tapped creatures you control have deathtouch.
    Other untapped creatures you control have hexproof.
    {1}, {T}: Untap another target creature or land you control.

    — PLAY-ALL Step 2 (Raggadragga). The two statics are the parser's own
    claims, reproduced verbatim (a registered card never falls back to the
    parser). The activated untap is `tap` with ``untap=True`` on the new
    ``another_creature_or_land_you_control`` target frame
    (`targeting.TARGET_FRAMES`) — "another" keeps Saryth itself out of the
    pool, unlike `creature_or_land_you_control` (Vengeant Earth).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "other_creatures_you_control", "object_filter": {"tapped": True},
                "keywords": ["deathtouch"],
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "other_creatures_you_control", "object_filter": {"tapped": False},
                "keywords": ["hexproof"],
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {"target_kind": "another_creature_or_land_you_control", "untap": True})],
            cost={"text": "{1}, {T}"},
        ),
    ]


register("Saryth, the Viper's Fang", _saryth_the_vipers_fang)
