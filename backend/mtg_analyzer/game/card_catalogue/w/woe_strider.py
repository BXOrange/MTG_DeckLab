from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Woe Strider ("escapes with counters") — PAR-60
# ===========================================================================
# New `GameObject.cast_via_escape` flag (stamped at the Escape cast site,
# like ``cast_via_flashback``) + a ``cast_via_escape`` condition key. The
# "enters with N +1/+1 counters" rider is modeled as an ETB add_counters


def _woe_strider() -> list[AbilitySpec]:
    """Escape—{3}{B}{B}, Exile four other cards from your graveyard (folds in
    from the RULE 702 keyword catalogue).
    When this creature enters, create a 0/1 white Goat creature token.
    Sacrifice another creature: Scry 1.
    This creature escapes with two +1/+1 counters on it."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 0, "toughness": 1, "colors": ["W"],
                "subtypes": ["Goat"], "keywords": [], "token_name": "Goat"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "+1/+1", "amount": 2},
                        condition={"cast_via_escape": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("scry", {"count": 1})],
            cost={"text": "Sacrifice another creature"},
        ),
    ]


register("Woe Strider", _woe_strider)
