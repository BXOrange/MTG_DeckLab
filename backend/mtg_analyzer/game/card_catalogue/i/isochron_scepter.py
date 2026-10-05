from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _isochron_scepter() -> list[AbilitySpec]:
    """Imprint — When this artifact enters, you may exile an instant card
    with mana value 2 or less from your hand.
    {2}, {T}: You may copy the exiled card. If you do, you may cast the
    copy without paying its mana cost.

    — Isochron Scepter, MEC-43 round 4G. The first line is `ImprintEffect`
    (MEC-17, Chrome Mox) widened with two new filter params —
    ``include_card_type="instant"`` (an *inclusion* filter, the opposite
    direction of Chrome Mox's own exclusion list) and ``max_mana_value=2``.
    The repeatable activated ability is the genuinely new part —
    `CopyImprintedCardEffect`: builds a fresh token copy of the imprinted
    card straight into exile (never touching the battlefield, the same
    RULE 722.3c idiom `make_prepared` already uses) and opens its
    `grant_free_cast_window_from_exile` window, the same MEC-20/Beseech
    the Mirror "reaches the ordinary cast action with full targeting"
    idiom — repeatable, since the original imprinted card is never itself
    cast and stays put for the rest of the game.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("imprint", {
                "include_card_type": "instant",
                "max_mana_value": 2,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("copy_imprinted_card", {})],
            cost={"text": "{2}", "taps_self": True},
        ),
    ]


register("Isochron Scepter", _isochron_scepter)
