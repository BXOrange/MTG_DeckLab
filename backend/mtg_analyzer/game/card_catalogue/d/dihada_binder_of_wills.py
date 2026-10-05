from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dihada_binder_of_wills() -> list[AbilitySpec]:
    """+2: Up to one target legendary creature gains vigilance, lifelink, and
    indestructible until your next turn.
    −3: Reveal the top four cards of your library. Put any number of legendary
    cards from among them into your hand and the rest into your graveyard.
    Create a Treasure token for each card put into your graveyard this way.
    −11: Gain control of all nonland permanents until end of turn. Untap them.
    They gain haste until end of turn.
    Dihada, Binder of Wills can be your commander.

    — PLAY-ALL Step 2 (SpongeBob). The +2 is the parser's own shape for "target
    creature gains … until your next turn" (`grant_until`, ``your_next_turn``)
    narrowed by ``creature_filter {legendary}`` and made optional ("up to one").
    The −3 is `inspect_top_choose` (the parser's reveal/choose-any-number form)
    with a new ``graveyard_with_treasures`` rest destination:
    `search_mixin._handle_rest_inspected` puts the unchosen cards into the
    graveyard and then makes one Treasure for each. The −11 is Insurrection's
    mass `gain_control_until_eot` over the ``all_nonland_permanents``
    selector (untap and haste are that effect's defaults). Commander text is
    deck-building only.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "grant_keyword", "params": {"keywords": ["vigilance", "lifelink", "indestructible"]}},
                "duration": "your_next_turn", "target_kind": "creature",
                "creature_filter": {"legendary": True}, "optional": True,
            })],
            cost={"loyalty": 2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("inspect_top_choose", {
                "count": 4, "action": "library_to_hand", "max_picks": "all", "optional": True,
                "criteria": {"type": "legendary"}, "rest_destination": "graveyard_with_treasures",
            })],
            cost={"loyalty": -3},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("gain_control_until_eot", {"selector": "all_nonland_permanents"})],
            cost={"loyalty": -11},
        ),
    ]


register("Dihada, Binder of Wills", _dihada_binder_of_wills)
