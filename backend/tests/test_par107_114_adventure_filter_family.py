"""PAR-107…114 residue batches, part 9 — "a card that has an adventure" (`has_adventure`, a filter key the object
vocabulary already had) as a graveyard-return target (Edgewall Inn), an "as long as you own a card in exile that has
an adventure" static condition (Howling Galefang; also "activate only if you own a card in exile", Dreadlight
Monstrosity) and a group enters-with-counter filter (Mysterious Pathlighter).

Reference: parser/oracle/catalogue/handlers.py (`_RETURN_FROM_GRAVEYARD_RE` ``adv``), count_phrase.py
(`_HAS_ADVENTURE`, `_OWN`), static_handlers.py (`_EXTRA_ETB_COUNTER_RE`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

GALEFANG = "This creature has haste as long as you own a card in exile that has an adventure."
PATHLIGHTER = "Flying\nEach creature you control that has an adventure enters with an additional +1/+1 counter on it."
INN = "{3}, {T}, Sacrifice this artifact: Return target card that has an adventure from your graveyard to your hand."


def _card(name, text, type_line="Creature — Wolf", layout="normal", power=2, toughness=2):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, oracle_text=text, is_creature=creature, layout=layout,
                power=power if creature else None, toughness=toughness if creature else None)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id="p1", zone=zone)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        eng.state.player_by_id("p1").add_to_zone(obj, zone)
    return obj


def test_real_cards_are_modeled():
    for name, text, type_line in [("Howling Galefang", GALEFANG, "Creature — Wolf"),
                                  ("Mysterious Pathlighter", PATHLIGHTER, "Creature — Bird"),
                                  ("Edgewall Inn", INN, "Artifact"),
                                  ("Dreadlight Monstrosity",
                                   "{3}{U}{U}: This creature can't be blocked this turn. Activate only if you own a "
                                   "card in exile.", "Creature — Horror")]:
        result = parse_oracle(_card(name, text, type_line))
        assert result.modeled, (name, result.unclaimed)


def test_a_battlefield_count_phrase_is_not_an_ownership_condition():
    assert not parse_oracle(_card("Probe", "This creature has haste as long as you own a creature.")).modeled


def test_galefang_has_haste_only_while_an_adventure_card_is_in_exile():
    eng = _engine()
    wolf = _put(eng, _card("Howling Galefang", GALEFANG))
    eng.recompute_continuous_effects()
    assert "haste" not in {k.lower() for k in wolf.granted_keywords}
    _put(eng, _card("Bonecache Overseer", "", "Creature — Human", layout="adventure"), zone=Zone.EXILE)
    eng.recompute_continuous_effects()
    assert "haste" in {k.lower() for k in wolf.granted_keywords}


def test_galefang_ignores_a_plain_card_in_exile():
    eng = _engine()
    wolf = _put(eng, _card("Howling Galefang", GALEFANG))
    _put(eng, _card("Plain", "", "Creature — Human"), zone=Zone.EXILE)
    eng.recompute_continuous_effects()
    assert "haste" not in {k.lower() for k in wolf.granted_keywords}


def test_edgewall_inn_only_offers_adventure_cards_from_the_graveyard():
    from mtg_analyzer.game.targeting import legal_targets

    eng = _engine()
    inn = _put(eng, _card("Edgewall Inn", INN, "Artifact"))
    adventure = _put(eng, _card("Brazen Borrower", "", "Creature — Faerie", layout="adventure"), zone=Zone.GRAVEYARD)
    _put(eng, _card("Plain", "", "Creature — Human"), zone=Zone.GRAVEYARD)
    spec = inn.activated_abilities[0].effects[0].target_specs[0]
    offered = legal_targets(eng.state, "p1", spec, source=inn)
    assert [o["instance_id"] for o in offered] == [adventure.instance_id]


def _enter(eng, card):
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    obj.controller_id = "p1"
    eng.rules._put_searched_card(eng.state.player_by_id("p1"), obj, "battlefield")
    return obj


def test_pathlighter_gives_a_counter_to_an_adventure_creature_entering():
    eng = _engine()
    _put(eng, _card("Mysterious Pathlighter", PATHLIGHTER, "Creature — Bird"))
    entering = _enter(eng, _card("Brazen Borrower", "", "Creature — Faerie", layout="adventure"))
    plain = _enter(eng, _card("Plain", "", "Creature — Human"))
    assert entering.plus_one_counters == 1
    assert plain.plus_one_counters == 0
