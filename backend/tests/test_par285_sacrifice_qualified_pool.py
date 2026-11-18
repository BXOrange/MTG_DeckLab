"""PAR-285: the controller's own sacrifice of a qualified pool (RULE 701.17a).

"sacrifice a nontoken creature", "sacrifice another creature or land", "sacrifice a noncreature artifact" used to stay
unclaimed because the controller row knew only the four bare type words and the "you may <cost>. If you do" antecedent
knew only a single word after the article. Both now read the shared edict pool vocabulary / the permanent phrase
`continuous.matches_permanent_word` evaluates. Tests run parser -> binder -> engine on the real cards' text."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_par285_sequential_another_target import _card, _put, _session


def _real_card(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _effects(name: str):
    result = parse_oracle(_real_card(name))
    assert result.modeled is True, name
    return [e for ab in result.specs if ab.effects for e in ab.effects]


def test_controller_row_carries_the_pool_and_the_source_exclusion():
    (spec,) = match_clause("sacrifice another creature or land")
    assert spec.type == "sacrifice"
    assert spec.params["selector"] == "controller" and spec.params["exclude_source"] is True
    assert spec.params["object_filter"] == {"card_type_any": ["creature", "land"]}
    (plain,) = match_clause("sacrifice a creature")
    assert plain.params == {"selector": "controller", "what": "creature", "count": 1}
    (nontoken,) = match_clause("sacrifice a nontoken creature")
    assert nontoken.params["what"] == "nontoken_creature"


def test_optional_antecedent_takes_a_qualified_pool():
    (spec,) = match_clause("you may sacrifice a noncreature artifact. if you do, draw a card.")
    assert spec.type == "pay_cost_then" and spec.params["cost"] == "sacrifice a noncreature artifact"


@pytest.mark.parametrize("name", ["Morkrut Necropod", "Feed the Pack", "Dredge", "Joo Dee, One of Many"])
def test_real_cards_are_modeled(name):
    _effects(name)


def test_another_creature_or_land_never_offers_the_source_or_other_types():
    _, engine, state = _session()
    necropod = _put(state, _card("Morkrut Necropod", "Creature — Slug"))
    bear = _put(state, _card("Bear", "Creature — Bear"))
    forest = _put(state, _card("Forest", "Land"))
    rock = _put(state, _card("Rock", "Artifact"))
    foe = _put(state, _card("Foe", "Creature — Bear"), "p2")
    engine.rules._apply_effect_specs([e.to_dict() for e in _effects("Morkrut Necropod")], necropod, [])
    choice = state.pending_choice
    assert choice["kind"] == "choose_objects" and choice["action"] == "sacrifice"
    offered = {int(o["id"]) for o in choice["options"]}
    assert offered == {bear.instance_id, forest.instance_id}, (offered, necropod.instance_id, rock.instance_id, foe.instance_id)


def test_nontoken_sacrifice_cost_spares_the_token_and_sizes_the_payoff_by_the_victim():
    session, engine, state = _session()
    pack = _put(state, _card("Feed the Pack", "Enchantment"))
    # The token enters first: an unfiltered pick would take it before the nontoken creature.
    token = _put(state, _card("Goblin Token", "Creature — Goblin", toughness=5))
    token.is_token = True
    ox = _put(state, _card("Ox", "Creature — Ox", toughness=3))
    engine.rules._apply_effect_specs([e.to_dict() for e in _effects("Feed the Pack")], pack, [])
    assert state.pending_choice["kind"] == "pay_cost_then"
    session.apply_action({"type": "choose", "option_id": "pay"}, "p1")
    engine.resolve_until_stable()
    assert ox.zone == Zone.GRAVEYARD and token.zone == Zone.BATTLEFIELD
    assert [o.name for o in state.battlefield].count("Wolf") == 3  # X = the sacrificed creature's toughness
