from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ojer_taq_deepest_foundation() -> list[AbilitySpec]:
    """Vigilance
    If one or more creature tokens would be created under your control,
    three times that many of those tokens are created instead.
    When Ojer Taq dies, return it to the battlefield tapped and
    transformed under its owner's control.

    — Ojer Taq, Deepest Foundation, Ojer Axonil's cycle-mate: same
    hand-authored bug fix (the whole card was `UNMODELED` — the parser
    can't claim either of these two clauses — so *nothing* bound at all,
    including the death trigger every real game needs). The token clause
    reuses `double_tokens` (Doubling Season/Parallel Lives) with its new
    ``multiplier`` param (default 2, kept backward-compatible) set to 3 for
    Ojer Taq's own "three times" rather than "twice". The death trigger is
    the exact same `return_self_from_graveyard_untargeted` shape as Ojer
    Axonil's own — see that entry's docstring for the ``tapped`` dormant-bug
    fix this also benefits from.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_tokens", {"multiplier": 3})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_self_from_graveyard_untargeted", {
                "destination": "battlefield", "tapped": True, "transformed": True,
            })],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
        ),
    ]


register("Ojer Taq, Deepest Foundation // Temple of Civilization", _ojer_taq_deepest_foundation)
