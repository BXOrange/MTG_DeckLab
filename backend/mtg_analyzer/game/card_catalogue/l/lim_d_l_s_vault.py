from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lim_duls_vault() -> list[AbilitySpec]:
    """Look at the top five cards of your library. As many times as you
    choose, you may pay 1 life, put those cards on the bottom of your
    library in any order, then look at the top five cards of your library.
    Then shuffle and put the last cards you looked at this way on top in any
    order.

    — Lim-Dûl's Vault. The engine's only **open-ended** loop: every other
    repetition has a fixed count or a hard cap, whereas here the player
    decides after each iteration whether to go again. Driven by a
    `pending_choice` that re-opens itself (the same self-re-opening shape a
    multi-card search already uses) with no counter running down.

    It is still bounded, by the card's own payment rather than a safety
    valve bolted on: each iteration costs 1 life and the choice simply isn't
    offered once the player couldn't survive another (RULE 118.4).

    Stopping shuffles **first** and puts the last batch back on top
    afterwards — RULE 701.19e's ordering, the same one `_finish_search`
    already uses for a library destination; the other order would scatter
    the very cards the card promises to leave on top.

    **Documented simplification**: "in any order" isn't an interactive
    five-card reorder — the batch keeps its relative order. The card is
    played to *find* something, and the top card is what the next draw takes
    either way.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("look_top_pay_life_loop", {"count": 5, "life_cost": 1})],
        ),
    ]


register("Lim-Dûl's Vault", _lim_duls_vault)
