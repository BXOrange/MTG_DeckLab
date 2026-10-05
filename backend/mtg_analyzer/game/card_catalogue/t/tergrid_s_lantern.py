from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tergrids_lantern() -> list[AbilitySpec]:
    """{T}: Target player loses 3 life unless they sacrifice a nonland
    permanent of their choice or discard a card.
    {3}{B}: Untap Tergrid's Lantern.

    — Tergrid's Lantern, Tergrid's back face (MEC-43 round 4E, registered
    separately — `GameObject.transform` swaps ``card`` to the printed
    back face, whose own ``name`` has no "//" for `specs_for`'s front-face
    fallback to strip, so it needs its own catalogue entry keyed on that
    back name directly).

    "Unless they sacrifice a nonland permanent of their choice or discard
    a card" is a new compound-cost primitive, `ActivationCost.sacrifice_
    or_discard` (confirmed against the cache as a recurring template —
    Starseer Mentor/Thornplate Intimidator/Torment of Scarabs/Torment of
    Venom all print the exact same phrase) — the payer's own choice
    between the two, unlike every other `ActivationCost` field (AND-
    combined). `PayCostThenEffect`'s new ``payer="target"`` mode (this
    round's other new primitive) asks *the targeted player*, not this
    ability's own controller — `_request_pay_cost_then`'s existing "pay or
    decline" choice, "pay" now able to open a further `sacrifice_or_
    discard` sub-choice when the payer genuinely has both options
    available (``_pay_sacrifice_or_discard``/`resolve_sacrifice_or_
    discard_choice`, `game/rules/misc_mixin.py`).

    The untap ability reuses `TapEffect`'s existing ``target_kind=None``
    self-untap mode (Grinding Station-shaped) — no new primitive.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("pay_cost_then", {
                "cost": "", "sacrifice_or_discard": True, "payer": "target",
                "target_kind": "player",
                "else_effects": [{"type": "lose_life", "params": {"amount": 3, "target_kind": "player"}}],
            })],
            cost={"text": "{T}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {"target_kind": None, "untap": True})],
            cost={"text": "{3}{B}"},
        ),
    ]


register("Tergrid's Lantern", _tergrids_lantern)
