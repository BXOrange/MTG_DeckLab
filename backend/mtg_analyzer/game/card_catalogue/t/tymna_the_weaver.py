from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tymna_the_weaver() -> list[AbilitySpec]:
    """Lifelink
    At the beginning of each of your postcombat main phases, you may pay
    X life, where X is the number of opponents that were dealt combat
    damage this turn. If you do, draw X cards.
    Partner (You can have two commanders if both have partner.)

    — MEC-42. Lifelink/Partner are plain printed keywords, recognized
    independent of catalogue registration (Partner is a legality flag
    `services/commander_legality.py` reads, not a gameplay ability with
    anything to bind). The trigger's own X needed a genuine new count
    selector — `continuous.count_selector`'s new
    ``"opponents_dealt_combat_damage_this_turn"``, aggregating `GameState.
    combat_damage_to_players_this_turn` (RULE 120.3, previously only ever
    read per-source) across every source that hit this turn, unlike that
    field's own keyed-by-source shape. The pay-X-draw-X body is the new
    `PayLifeEqualToOpponentsCombatDamagedDrawThatManyEffect` — computes X
    once, then opens the already-general `RulesEngine.request_pay_cost_
    then` choice with a dynamically built cost/effect pair, since neither
    the printed cost text nor the effect amount is a fixed value.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_life_equal_to_opponents_combat_damaged_draw_that_many", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "main2"}, "phase_relation": "you"},
        ),
    ]


register("Tymna the Weaver", _tymna_the_weaver)
