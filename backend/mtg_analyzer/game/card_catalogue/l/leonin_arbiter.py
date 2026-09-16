from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _leonin_arbiter() -> list[AbilitySpec]:
    """Players can't search libraries. Any player may pay {2} for that
    player to ignore this effect until end of turn.

    — MEC-35. Two pieces. (1) The already-shipped `grant_search_
    prohibited` (Stranglehold's own effect type) gained a new `scope`
    param: `"opponents"` (the pre-existing default, matching Stranglehold's
    "**your opponents** can't…") vs. `"all"` (this card's own unqualified
    "**Players** can't…", which also restricts its own controller). (2)
    "Any player may pay {2}… to ignore this effect until end of turn" is a
    genuine RULE 116.2a special action — no stack, no timing restriction,
    repeatable (paying twice just wastes {2}, same as the real card) —
    `GameEngine.pay_search_exemption`/`pay_search_exemption_actions`,
    mirroring `turn_face_up`'s own established "offered only when payable,
    reclaims priority for its taker" shape exactly. `GameState.search_
    exempt_until_turn` is the same "stops matching once the turn advances,
    no cleanup bookkeeping needed" idiom `temp_flash_until_turn` already
    uses. The exemption is read as "ignore every current search
    prohibition," not just this one specific effect (the printed wording
    says "this effect") — no shipped card yet combines Leonin Arbiter with
    a second, independent prohibition source, so the simpler reading costs
    nothing today; narrow it if that ever changes.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_search_prohibited", {"scope": "all"})],
        ),
    ]


register("Leonin Arbiter", _leonin_arbiter)
