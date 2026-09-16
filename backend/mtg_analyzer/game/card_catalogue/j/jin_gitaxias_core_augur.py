from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jin_gitaxias_core_augur() -> list[AbilitySpec]:
    """Flash
    At the beginning of your end step, draw seven cards.
    Each opponent's maximum hand size is reduced by seven.

    — MEC-43 round 4B. Flash folds in via the ordinary keyword catalogue.
    The end-step trigger already parses on its own — reproduced verbatim
    (registering this card makes `specs_for` skip the parser wholesale for
    it, so the parser-claimed half needs reproducing rather than being
    left to fall through, The Wise Mothman's own precedent). The
    hand-size clause is `hand_size_modifier` (new — the numeric sibling of
    the shipped boolean `no_max_hand_size`, `continuous.
    hand_size_modifier_for`), ``affects="opponents"``. ``amount`` is a
    non-negative magnitude — `EffectSpec._clamp_params` floors a literal
    negative int at 0 — with the default (no ``increase`` flag) meaning
    "reduced by," matching `cost_reduction`'s own magnitude+flag
    convention.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 7})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("hand_size_modifier", {"amount": 7, "affects": "opponents"})],
        ),
    ]


register("Jin-Gitaxias, Core Augur", _jin_gitaxias_core_augur)
