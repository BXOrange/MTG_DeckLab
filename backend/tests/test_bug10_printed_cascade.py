"""BUG-10: a printed Cascade triggers (RULE 702.85a), and a flag keyword printed several times on its keyword line
("Cascade, cascade", "Prowess, prowess", "Myriad, myriad") is that many instances, each triggering separately
(RULE 113.2c, 702.85c, 702.108b, 702.116b). Before, only *granted* cascade triggered, and Scryfall's de-duplicated
``keywords`` array collapsed repeats into one instance."""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.keywords import parse_keywords

CASCADE_REMINDER = (
    "(When you cast this spell, exile cards from the top of your library until you exile a nonland card that "
    "costs less. You may cast it without paying its mana cost. Put the exiled cards on the bottom in a random order.)"
)


def _creature(name, keywords, oracle_text, power=2, toughness=2, cmc=0):
    return Card(id=name, name=name, type_line="Creature — Elemental", is_creature=True, power=power,
                toughness=toughness, oracle_text=oracle_text, keywords=list(keywords), converted_mana_cost=cmc)


def _filler(name):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
                mana_cost_string="{1}{G}", converted_mana_cost=2)


def _cascader(times=1, cmc=5):
    line = ", ".join(["Cascade"] + ["cascade"] * (times - 1))
    return _creature("Cascader", ["Cascade"], f"{line} {CASCADE_REMINDER}", 5, 5, cmc)


def _engine():
    library = [_filler(f"Filler {i}") for i in range(10)]
    eng = GameEngine.new_game([("p1", "p1", list(library)), ("p2", "p2", list(library))],
                              starting_life=20, starting_hand=0)
    eng.start()
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    return eng


def _cast_paid(eng, card):
    player = eng.state.player_by_id("p1")
    for colour in "WUBRGC":
        player.mana_pool.add(colour, 10)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.hand.append(obj)
    eng.cast_spell(player, obj)
    return obj


def _cascade_offers(eng):
    """Decline every cascade offer; return how many there were."""
    offers = 0
    for _ in range(30):
        eng.resolve_until_stable()
        choice = eng.state.pending_choice
        if not choice:
            return offers
        offers += "Cascade" in str(choice.get("prompt", ""))
        eng.resolve_pending_choice("decline")
    raise AssertionError("choices did not settle")


# -- parser: the instance count rides the keyword spec ------------------------


def _keyword(card, name):
    return next(s.keyword for s in parse_keywords(card) if s.keyword["name"] == name)


def test_repeated_keyword_line_carries_its_instance_count():
    assert _keyword(_cascader(2), "cascade")["instances"] == 2
    assert _keyword(_cascader(4), "cascade")["instances"] == 4


def test_single_keyword_carries_no_instance_count():
    assert "instances" not in _keyword(_cascader(1), "cascade")
    flying = _creature("Bird", ["Flying", "Haste"], "Flying, haste")
    assert "instances" not in _keyword(flying, "flying")


def test_keyword_named_inside_other_text_is_not_an_instance():
    card = _creature("Seer", ["Cascade"], "Cascade\nWhenever you cast a spell with cascade, cascade triggers twice.")
    assert "instances" not in _keyword(card, "cascade")


# -- engine: printed cascade triggers, once per instance ----------------------


def test_printed_cascade_triggers_on_cast():
    eng = _engine()
    _cast_paid(eng, _cascader(1))
    assert _cascade_offers(eng) == 1


def test_cascade_cascade_triggers_twice_and_four_times_four():
    eng = _engine()
    _cast_paid(eng, _cascader(2))
    assert _cascade_offers(eng) == 2
    eng = _engine()
    _cast_paid(eng, _cascader(4))
    assert _cascade_offers(eng) == 4


def test_accepted_cascade_casts_the_hit_for_free():
    eng = _engine()
    _cast_paid(eng, _cascader(1))
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "play_during_resolution"
    hit = eng.state.find_object(choice["instance_ids"][0])
    eng.play_resolution_card(eng.state.player_by_id("p1"), hit)
    eng.resolve_until_stable()
    names = {o.name for o in eng.state.battlefield}
    assert "Cascader" in names and hit.name in names


def test_a_spell_without_cascade_offers_nothing():
    eng = _engine()
    _cast_paid(eng, _creature("Plain", [], "", 5, 5, 5))
    assert _cascade_offers(eng) == 0


def test_instance_count_reaches_keyword_instances():
    eng = _engine()
    obj = GameObject(_cascader(2), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    assert combat.keyword_instances(obj, "cascade") == 2


# -- Prowess / Myriad printed twice --------------------------------------------


def test_prowess_prowess_pumps_twice():
    eng = _engine()
    monk = GameObject(_creature("Monk", ["Prowess"], "Prowess, prowess", 1, 1), owner_id="p1", zone=Zone.BATTLEFIELD)
    monk.summoning_sick = False
    eng.state.add_to_battlefield(monk)
    bind_from_catalogue(monk)
    eng.recompute_continuous_effects()
    _cast_paid(eng, Card(id="Shock", name="Shock", type_line="Instant", is_instant=True))
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert monk.power == 3


def test_myriad_myriad_is_two_instances():
    obj = GameObject(_creature("Squirrels", ["Myriad"], "Myriad, myriad"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    assert combat.keyword_instances(obj, "myriad") == 2
