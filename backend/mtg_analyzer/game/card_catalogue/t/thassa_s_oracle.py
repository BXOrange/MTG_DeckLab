from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _thassas_oracle() -> list[AbilitySpec]:
    """When this creature enters, look at the top X cards of your library,
    where X is your devotion to blue. Put up to one of them on top of your
    library and the rest on the bottom of your library in a random order.
    If X is greater than or equal to the number of cards in your library,
    you win the game.

    — Thassa's Oracle. Needed the **devotion** count selector (RULE 202.2f):
    `Card.mana_cost` already tallies symbols per colour *and* already counts
    a hybrid pip toward both of its colours, which is precisely devotion's
    definition, so `continuous.count_selector`'s ``devotion_to_<colour>``
    entries read it directly with no cost re-parse.

    The win check (RULE 104.2a) is evaluated *before* anything moves and
    routes through `RulesEngine.player_wins`, the same choke point Jace,
    Wielder of Mysteries uses — so a "you can't win the game" effect would
    stop both in one place. Note X >= 0 wins on an empty library even with
    devotion 0, which is correct and is the actual cEDH line (Oracle after
    Demonic Consultation).

    **Documented simplification**: the dig itself is non-interactive —
    the top card stays on top, the rest go to the bottom. In every real line
    the card is cast to *win*, not to filter, so the choice is a formality;
    this matches the non-interactive auto-pick the engine already makes for
    sacrifice/discard costs.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("look_top_keep_one_on_top", {
                "count_selector": "devotion_to_blue",
                "win_if_count_at_least_library": True,
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
        ),
    ]


register("Thassa's Oracle", _thassas_oracle)
