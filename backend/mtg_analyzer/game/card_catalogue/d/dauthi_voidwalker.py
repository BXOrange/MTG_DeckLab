from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dauthi_voidwalker() -> list[AbilitySpec]:
    """Shadow (This creature can block or be blocked by only creatures
    with shadow.)
    If a card would be put into an opponent's graveyard from anywhere,
    instead exile it with a void counter on it.
    {T}, Sacrifice this creature: Choose an exiled card an opponent owns
    with a void counter on it. You may play it this turn without paying
    its mana cost.

    — MEC-42. Shadow is a plain printed evasion keyword, already
    recognized independent of catalogue registration. The graveyard
    redirect is a new standing `void_counter_redirect` static
    (`continuous.void_counter_redirect_controller_for`, the same
    battlefield-static-scan idiom Opposition Agent's `search_redirect`
    already uses), checked from `RulesEngine._move_to_graveyard` — the one
    choke point every graveyard-bound move funnels through — right
    alongside the existing Lurrus/Yawgmoth's Will redirects there;
    `GameState.void_counter_holder` (``instance_id -> holder player_id``)
    is the marker itself, never swept. The activated ability's own
    `ChooseVoidCounterCardEffect` gathers the live candidate pool (every
    opponent's exile zone, filtered to that marker) and reuses MEC-20's
    already-general ``"grant_free_cast"`` chooser action — a same-turn
    free-cast window, exactly what "you may play it this turn without
    paying its mana cost" asks for.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("void_counter_redirect", {})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("choose_void_counter_card", {})],
            cost={"text": "{T}, Sacrifice this creature"},
        ),
    ]


register("Dauthi Voidwalker", _dauthi_voidwalker)
