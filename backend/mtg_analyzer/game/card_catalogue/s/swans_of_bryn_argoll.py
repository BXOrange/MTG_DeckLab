from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-30: carding the standing `prevent_damage` replacement family — the
# irregular/compound cards a generic parser regex can't cleanly cover (see
# `parser/oracle/catalogue/replacements.py` for the regular Sphere/Urza's
# Armor/Shield of the Realm shapes this doesn't repeat).
# ---------------------------------------------------------------------------


def _swans_of_bryn_argoll() -> list[AbilitySpec]:
    """Flying
    If a source would deal damage to this creature, prevent that damage.
    The source's controller draws cards equal to the damage prevented this
    way.

    — Flying is the ordinary RULE 702 keyword fold-in (unaffected by this
    registration). The prevention is a plain `"prevent_damage"` replacement
    (``to="self"``, ``amount="all"``) with the new ``rider`` param —
    ``{"kind": "draw_cards", "recipient": "source_controller"}`` fires
    `RulesEngine.apply_prevent_rider`'s draw once the *actual* prevented
    amount is known, off whichever source dealt the damage (not this
    creature's own controller).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "self", "amount": "all",
                "rider": {"kind": "draw_cards", "recipient": "source_controller"},
            })],
        ),
    ]


register("Swans of Bryn Argoll", _swans_of_bryn_argoll)
