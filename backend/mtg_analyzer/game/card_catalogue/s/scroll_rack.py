from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scroll_rack() -> list[AbilitySpec]:
    """{1}, {T}: Exile any number of cards from your hand face down. Put
    that many cards from the top of your library into your hand. Then
    look at the exiled cards and put them on top of your library in any
    order.

    — MEC-43 round 4F. RULE 701.20a-adjacent: reuses `GameObject.
    face_down_in_exile` (Beseech the Mirror's own face-down exile),
    `RulesEngine._request_choose_objects`'s ``track_exiled_with`` (MEC-21)
    for the "any number" pick, and the scry/surveil two-phase "order the
    rest back on top" machinery (`RulesEngine._LOOK_TOP_KINDS`) for the
    final ordering step — the only genuinely new piece is putting cards
    that started in *exile* back onto the library instead of reordering
    cards already there (`_finish_look_top`'s new ``"scroll_rack"``
    branch, `RulesEngine.open_scroll_rack_order_choice`). Built as two
    chained effects (`scroll_rack_exile`/`scroll_rack_finish`,
    `ScrollRackEffect`/`ScrollRackFinishEffect`) rather than one, since
    "how many cards to draw and which need reordering" is only known once
    the exile-any-number choice actually resolves (``then_specs``).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("scroll_rack_exile", {})],
            cost={"text": "{1}", "taps_self": True},
        ),
    ]


register("Scroll Rack", _scroll_rack)
