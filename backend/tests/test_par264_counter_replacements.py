"""PAR-264 -- counter placement and entering-counter replacements (RULE 614.1a/614.1c, 122.6, 616.1).

* Deanna Troi: "Other creatures you control enter with an additional +1/+1 counter on them." (`extra_etb_counter`,
  plural "other <phrase> you control enter" form).
* Dr. Joseph M'Benga: "If you would put one or more counters on a creature you control, put twice that many of each of
  those kinds of counters on that creature instead." (`double_counters`, causer-scoped, creature recipient).
* Lt. Cmdr. Geordi La Forge / Optimization Annex: the same replacement narrowed to charge counters on an artifact you
  control, "twice" and "that many plus one" (`double_counters` ``kind`` + the new ``artifact_you_control`` recipient).
* Dr. McCoy, Surly Surgeon: "If another creature you control with a +1/+1 counter on it would be destroyed, instead
  remove all +1/+1 counters from it and all damage already dealt to it is healed." (`destroy_remove_counters`, a
  DESTROY replacement, RULE 614.1a / 701.69a).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase

DEANNA = "Other creatures you control enter with an additional +1/+1 counter on them."
MBENGA = ("If you would put one or more counters on a creature you control, put twice that many of each of those "
          "kinds of counters on that creature instead.")
GEORDI = ("If you would put one or more charge counters on an artifact you control, put twice that many charge "
          "counters on that artifact instead.")
ANNEX = ("If one or more charge counters would be put on an artifact you control, that many plus one charge counters "
         "are put on it instead.")
MCCOY = ("If another creature you control with a +1/+1 counter on it would be destroyed, instead remove all +1/+1 "
         "counters from it and all damage already dealt to it is healed.")


def _card(name, oracle="", type_line="Creature — Bear", **kw):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, is_creature=creature,
                power=2 if creature else None, toughness=2 if creature else None, **kw)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _bf(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _enter(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    obj.controller_id = controller
    eng.rules._put_searched_card(eng.state.player_by_id(controller), obj, "battlefield")
    return obj


def _real(name):
    if not DEFAULT_DB_PATH.exists():
        pytest.skip("card cache not present in this environment")
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not in the local card cache")
    return card


@pytest.mark.parametrize("name", [
    "Deanna Troi, Psychic Counsel", "Dr. Joseph M'Benga", "Lt. Cmdr. Geordi La Forge", "Optimization Annex",
    "Dr. McCoy, Surly Surgeon",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True


# --- Deanna Troi ----------------------------------------------------------------------------------------------


def test_deanna_gives_other_creatures_an_entry_counter():
    eng = _engine()
    deanna = _bf(eng, _card("Deanna", DEANNA))
    mine = _enter(eng, _card("Mine"))
    assert mine.plus_one_counters == 1  # RULE 614.1c: present as it enters
    assert _enter(eng, _card("Theirs"), controller="p2").plus_one_counters == 0
    assert deanna.plus_one_counters == 0  # "other"
    assert _enter(eng, _card("Relic", type_line="Artifact")).plus_one_counters == 0  # creatures only


def test_two_deannas_stack():
    eng = _engine()
    _bf(eng, _card("Deanna A", DEANNA))
    _bf(eng, _card("Deanna B", DEANNA))
    assert _enter(eng, _card("Mine")).plus_one_counters == 2


# --- Dr. Joseph M'Benga -----------------------------------------------------------------------------------------


def test_mbenga_doubles_every_kind_on_my_creatures_only_when_i_put_them():
    eng = _engine()
    doc = _bf(eng, _card("Doc", MBENGA))
    mine = _bf(eng, _card("Mine"))
    theirs = _bf(eng, _card("Theirs"), controller="p2")
    relic = _bf(eng, _card("Relic", type_line="Artifact"))
    eng.rules.add_counters(mine, 2, "+1/+1", source=doc)
    eng.rules.add_counters(mine, 1, "flying", source=doc)
    assert mine.counters.get("+1/+1") == 4 and mine.counters.get("flying") == 2
    eng.rules.add_counters(theirs, 2, "+1/+1", source=doc)
    assert theirs.counters.get("+1/+1") == 2  # not "a creature you control"
    eng.rules.add_counters(relic, 1, "charge", source=doc)
    assert relic.counters.get("charge") == 1  # not a creature
    eng.rules.add_counters(mine, 1, "+1/+1")  # nobody's effect of mine is putting it
    assert mine.counters.get("+1/+1") == 5


# --- Geordi / Optimization Annex ----------------------------------------------------------------------------------


def test_geordi_doubles_charge_counters_on_my_artifacts():
    eng = _engine()
    geordi = _bf(eng, _card("Geordi", GEORDI))
    relic = _bf(eng, _card("Relic", type_line="Artifact"))
    foes = _bf(eng, _card("Foe Relic", type_line="Artifact"), controller="p2")
    bear = _bf(eng, _card("Bear"))
    eng.rules.add_counters(relic, 2, "charge", source=geordi)
    eng.rules.add_counters(relic, 2, "+1/+1", source=geordi)  # other kind
    eng.rules.add_counters(foes, 2, "charge", source=geordi)
    eng.rules.add_counters(bear, 2, "charge", source=geordi)  # a non-artifact creature
    assert relic.counters.get("charge") == 4 and relic.counters.get("+1/+1") == 2
    assert foes.counters.get("charge") == 2
    assert bear.counters.get("charge") == 2


def test_optimization_annex_adds_one_charge_counter_whoever_puts_them():
    eng = _engine()
    _bf(eng, _card("Annex", ANNEX, type_line="Artifact Creature — Borg"))
    relic = _bf(eng, _card("Relic", type_line="Artifact"))
    foes = _bf(eng, _card("Foe Relic", type_line="Artifact"), controller="p2")
    eng.rules.add_counters(relic, 2, "charge")
    eng.rules.add_counters(relic, 2, "+1/+1")
    eng.rules.add_counters(foes, 2, "charge")
    assert relic.counters.get("charge") == 3 and relic.counters.get("+1/+1") == 2
    assert foes.counters.get("charge") == 2


# --- Dr. McCoy ----------------------------------------------------------------------------------------------------


def test_mccoy_saves_another_creature_with_a_counter_from_destruction():
    eng = _engine()
    _bf(eng, _card("McCoy", MCCOY, type_line="Legendary Creature — Human Doctor"))
    pal = _bf(eng, _card("Pal"))
    eng.rules.add_counters(pal, 2, "+1/+1")
    eng.rules.add_counters(pal, 1, "flying")
    pal.damage_marked = 3
    eng.rules.destroy(pal)
    assert pal.zone == Zone.BATTLEFIELD
    assert pal.plus_one_counters == 0 and pal.counters.get("flying") == 1  # only +1/+1 counters go
    assert pal.damage_marked == 0  # RULE 701.69a: healed


def test_mccoy_saves_a_creature_from_lethal_damage_sba():
    eng = _engine()
    _bf(eng, _card("McCoy", MCCOY, type_line="Legendary Creature — Human Doctor"))
    pal = _bf(eng, _card("Pal"))
    eng.rules.add_counters(pal, 1, "+1/+1")
    pal.damage_marked = 3  # toughness 3 with the counter
    eng.rules.check_state_based_actions()
    assert pal.zone == Zone.BATTLEFIELD and pal.damage_marked == 0 and pal.plus_one_counters == 0


def test_mccoy_does_not_protect_itself_countless_or_opposing_creatures():
    eng = _engine()
    mccoy = _bf(eng, _card("McCoy", MCCOY, type_line="Legendary Creature — Human Doctor"))
    bare = _bf(eng, _card("Bare"))
    foe = _bf(eng, _card("Foe"), controller="p2")
    eng.rules.add_counters(mccoy, 1, "+1/+1")
    eng.rules.add_counters(foe, 1, "+1/+1")
    for obj in (mccoy, bare, foe):
        eng.rules.destroy(obj)
    assert mccoy.zone == Zone.GRAVEYARD  # "another"
    assert bare.zone == Zone.GRAVEYARD   # no +1/+1 counter on it
    assert foe.zone == Zone.GRAVEYARD    # not "you control"


def test_mccoy_replacement_is_used_up_per_destruction():
    eng = _engine()
    _bf(eng, _card("McCoy", MCCOY, type_line="Legendary Creature — Human Doctor"))
    pal = _bf(eng, _card("Pal"))
    eng.rules.add_counters(pal, 1, "+1/+1")
    eng.rules.destroy(pal)
    assert pal.zone == Zone.BATTLEFIELD
    eng.rules.destroy(pal)  # no counter left: the second destroy is not replaced
    assert pal.zone == Zone.GRAVEYARD
