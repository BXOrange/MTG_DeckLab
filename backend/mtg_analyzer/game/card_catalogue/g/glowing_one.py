from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# RULE 728 Rad counters — "whenever ~ deals combat damage to a player, they
# get N rad counters" cards whose *damaged player* varies per firing (the
# oracle-text parser has no such per-firing grammar; see
# `AbilitySpec.rad_counters_on_combat_damage`, `RulesEngine._collect_rad_
# counter_damage_triggers`, `game/effects/core.py`'s `AddPlayerCountersEffect`).
# Each card's *other*, unrelated ability is a "whenever a player/an opponent
# mills a nonland card, ..."/"whenever one or more nonland cards are milled,
# ..." trigger (RULE 701.13) — now modeled too, off `EventType.MILL_CARD`
# (`RulesEngine.mill`, fired once per nonland card, never for a land) and its
# `effect_binder`-level "group" subject scoping, the same generic machinery
# `LIBRARY_SEARCHED`'s "an opponent searches" trigger already uses. Both
# clauses are hand-authored per card below — a 3-card family, same "narrow,
# real-card-driven" bar the oracle-text parser front-end itself uses before
# it's worth generalizing a whole new segmenter grammar for one, rather than
# building genuine parser recognition — so printed RULE 702 keywords
# (Deathtouch/Flying) are still picked up automatically regardless of
# registration (`specs_for`'s unconditional keyword fold-in), but nothing
# else on these cards falls through to the oracle-text parser.
# ---------------------------------------------------------------------------


def _glowing_one() -> list[AbilitySpec]:
    """Deathtouch
    Whenever this creature deals combat damage to a player, they get four
    rad counters.
    Whenever a player mills a nonland card, you gain 1 life.

    — Glowing One. The mill trigger is an ordinary bind-once
    `TriggeredAbility` off `EventType.MILL_CARD` with an unscoped ``"group"``
    subject (no ``controller`` key — any player's mill counts, including
    your own).
    """
    return [
        AbilitySpec(
            "static",
            [],
            rad_counters_on_combat_damage={"count": 4},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 1})],
            trigger={"event": EventType.MILL_CARD, "condition": {"subject": "group"}},
        ),
    ]


register("Glowing One", _glowing_one)
