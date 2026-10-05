"""MEC-12 (cEDH staples 2) — Helm of the Host's "at the beginning of
combat on your turn, create a token that's a copy of equipped creature,
except the token isn't legendary. That token gains haste."

No new primitive: `CopyPermanentEffect` already supported
`target_kind="attached_permanent"`, `not_legendary`, and `haste`
independently (each shipped for a different card); this is the first card
to combine all three on one effect.

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game.events import EventType, GameEvent

from tests.support.game import creature, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def test_helm_of_the_host_copies_equipped_creature_at_combat():
    eng = make_engine([], [], hand=0)
    p1 = eng.state.player_by_id("p1")
    helm = obj_on_battlefield(eng.state, eng, _named("Helm of the Host"), controller="p1")
    bind_from_catalogue(helm)
    host = obj_on_battlefield(
        eng.state, eng, creature("Legendary Bear", power=3, toughness=3, is_legendary=True),
        controller="p1",
    )
    eng.rules.attach_to_target(helm, host)

    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat"))
    eng.resolve_until_stable()

    tokens = [
        o for o in eng.state.battlefield
        if o is not host and o.card.name == host.card.name and o.is_token
    ]
    assert len(tokens) == 1
    token = tokens[0]
    assert token.controller_id == "p1"
    assert token.is_legendary is False
    assert "haste" in token.temp_keywords
