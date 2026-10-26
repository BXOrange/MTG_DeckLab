"""MEC-134 -- "As ~ enters, choose a card name" and the statics that read the chosen name.

One as-enters choice (`choose_card_name_on_enter`: free text, validated against the printed qualifier, optionally preceded
by a look at an opponent's hand) stamps `GameObject.chosen_card_name`; every static below reads it fresh on each check:

* Meddling Mage / Nevermore / Voidstone Gargoyle / Council of the Absolute / Gideon's Intervention -- "can't be cast"
  (`continuous.cast_prohibited`, RULE 101.2),
* Voidstone Gargoyle / Sorcerous Spyglass -- "activated abilities of sources with the chosen name can't be activated"
  (`continuous.activation_prohibited`, RULE 602.5, with RULE 605's mana-ability carve-out on the Spyglass),
* Council of the Absolute / Anointed Peacekeeper / Curse of Silence -- named spells cost more or less (RULE 601.2f);
  Skyseer's Chariot / Anointed Peacekeeper -- named abilities cost more to activate,
* Silverquill Silencer / Curse of Silence -- "whenever <player> casts a spell with the chosen name",
* Declaration of Naught -- "counter target spell with the chosen name",
* Gideon's Intervention -- prevention of damage from the named sources; Runed Halo -- protection from the name,
* Alpine Moon -- the opponents' named lands lose their land types and abilities and tap for any color.
"""
from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.effects.core import ActivatedAbility, DrawCardEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.game_session import GameSession

ORACLE = {
    "Runed Halo": ("Enchantment", "{W}{W}",
                   "As this enchantment enters, choose a card name.\n"
                   "You have protection from the chosen card name. (You can't be targeted, dealt damage, or enchanted by anything with that name.)"),
    "Alpine Moon": ("Enchantment", "{R}",
                    "As this enchantment enters, choose a nonbasic land card name.\n"
                    "Lands your opponents control with the chosen name lose all land types and abilities, and they gain "
                    "\"{T}: Add one mana of any color.\""),
    "Council of the Absolute": ("Creature — Human Advisor", "{2}{W}{U}",
                                "As this creature enters, choose a noncreature, nonland card name.\n"
                                "Your opponents can't cast spells with the chosen name.\n"
                                "Spells with the chosen name you cast cost {2} less to cast."),
    "Curse of Silence": ("Enchantment — Aura Curse", "{W}",
                         "Enchant player\nAs this Aura enters, choose a card name.\n"
                         "Spells with the chosen name enchanted player casts cost {2} more to cast.\n"
                         "Whenever enchanted player casts a spell with the chosen name, you may sacrifice this Aura. If you do, draw a card."),
    "Declaration of Naught": ("Enchantment", "{U}{U}",
                              "As this enchantment enters, choose a card name.\n{U}: Counter target spell with the chosen name."),
    "Gideon's Intervention": ("Enchantment", "{2}{W}{W}",
                              "As this enchantment enters, choose a card name.\n"
                              "Your opponents can't cast spells with the chosen name.\n"
                              "Prevent all damage that would be dealt to you and permanents you control by sources with the chosen name."),
    "Meddling Mage": ("Creature — Human Wizard", "{W}{U}",
                      "As this creature enters, choose a nonland card name.\nSpells with the chosen name can't be cast."),
    "Nevermore": ("Enchantment", "{1}{W}{W}",
                  "As this enchantment enters, choose a nonland card name.\nSpells with the chosen name can't be cast."),
    "Silverquill Silencer": ("Creature — Human Warlock", "{W}{B}",
                             "As this creature enters, choose a nonland card name.\n"
                             "Whenever an opponent casts a spell with the chosen name, they lose 3 life and you draw a card."),
    "Skyseer's Chariot": ("Artifact — Vehicle", "{1}{W}",
                          "Flying\nAs this Vehicle enters, choose a nonland card name.\n"
                          "Activated abilities of sources with the chosen name cost {2} more to activate.\nCrew 2"),
    "Voidstone Gargoyle": ("Creature — Gargoyle", "{3}{W}{W}",
                           "Flying\nAs this creature enters, choose a nonland card name.\n"
                           "Spells with the chosen name can't be cast.\n"
                           "Activated abilities of sources with the chosen name can't be activated."),
    "Sorcerous Spyglass": ("Artifact", "{2}",
                           "As this artifact enters, look at an opponent's hand, then choose any card name.\n"
                           "Activated abilities of sources with the chosen name can't be activated unless they're mana abilities."),
    "Anointed Peacekeeper": ("Creature — Human Cleric", "{2}{W}",
                             "Vigilance\nAs this creature enters, look at an opponent's hand, then choose any card name.\n"
                             "Spells your opponents cast with the chosen name cost {2} more to cast.\n"
                             "Activated abilities of sources with the chosen name cost {2} more to activate unless they're mana abilities."),
}


def named(name: str) -> Card:
    type_line, cost, oracle = ORACLE[name]
    creature = "Creature" in type_line
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, oracle_text=oracle,
        is_creature=creature,
        power=2 if creature else None, toughness=2 if creature else None,
        keywords=["Flying"] if "Flying" in oracle else (["Vigilance"] if "Vigilance" in oracle else []),
    )


def bolt() -> Card:
    return Card(id="bolt", name="Lightning Bolt", type_line="Instant", mana_cost_string="{R}", converted_mana_cost=1,
                oracle_text="Lightning Bolt deals 3 damage to any target.", is_instant=True)


def shock() -> Card:
    return Card(id="shock", name="Shock", type_line="Instant", mana_cost_string="{R}", converted_mana_cost=1,
                oracle_text="Shock deals 2 damage to any target.", is_instant=True)


def shock_bear() -> Card:
    return Card(id="bear", name="Grizzly Bears", type_line="Creature — Bear", mana_cost_string="{1}{G}",
                converted_mana_cost=2, oracle_text="", is_creature=True, power=2, toughness=2)


def island() -> Card:
    return Card(id="island", name="Island", type_line="Basic Land — Island", is_land=True,
                oracle_text="({T}: Add {U}.)")


def game():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    for player in engine.state.players:
        player.life = 20
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1, p2 = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    return engine, engine.state, p1, p2


def put(engine, printed, player, zone=Zone.HAND):
    obj = GameObject(printed, owner_id=player.id, controller_id=player.id, zone=zone)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        engine.state.add_to_battlefield(obj)
    else:
        player.zones[zone].append(obj)
    bind_from_catalogue(obj)
    return obj


def enter(engine, player, name, answer=None, *answers, targets=None):
    """Cast ``name`` from ``player``'s hand and answer its as-enters choices (``answer`` then ``answers``)."""
    obj = put(engine, named(name), player)
    player.mana_pool.add_many({"W": 4, "U": 4, "B": 4, "R": 4, "G": 4})
    engine.cast_spell(player, obj, targets=targets)
    engine.resolve_until_stable()
    for response in ([answer, *answers] if answer is not None else []):
        assert engine.state.pending_choice is not None, f"no choice left for {response!r}"
        engine.resolve_pending_choice(response)
        engine.resolve_until_stable()
    player.mana_pool.clear() if hasattr(player.mana_pool, "clear") else None
    return obj


# ---------------------------------------------------------------------------
# Parser: the thirteen cards are claimed, with the printed qualifier on the choice
# ---------------------------------------------------------------------------

QUALIFIERS = {
    "Runed Halo": None,
    "Alpine Moon": {"type": "land", "not_basic": True},
    "Council of the Absolute": {"without_type": ["creature", "land"]},
    "Curse of Silence": None,
    "Declaration of Naught": None,
    "Gideon's Intervention": None,
    "Meddling Mage": {"without_type": "land"},
    "Nevermore": {"without_type": "land"},
    "Silverquill Silencer": {"without_type": "land"},
    "Skyseer's Chariot": {"without_type": "land"},
    "Voidstone Gargoyle": {"without_type": "land"},
    "Sorcerous Spyglass": None,
    "Anointed Peacekeeper": None,
}


@pytest.mark.parametrize("name", sorted(QUALIFIERS))
def test_the_card_is_modeled_and_its_choice_carries_the_printed_qualifier(name):
    result = parse_oracle(named(name))
    assert result.modeled, result.unclaimed
    choice = next(a for a in result.specs if a.ability_kind == "enter_replacement")
    (effect,) = choice.effects
    assert effect.type == "choose_card_name_on_enter"
    assert effect.params.get("card_filter") == QUALIFIERS[name]
    assert bool(effect.params.get("look_at_opponent_hand")) == (name in ("Sorcerous Spyglass", "Anointed Peacekeeper"))


def test_a_keyword_name_is_not_a_card_name():
    # Pithing Spyglass names a keyword ability, not a card: a different mechanic that stays unclaimed.
    spyglass = Card(id="ps", name="Pithing Spyglass", type_line="Artifact", mana_cost_string="{2}",
                    oracle_text="As ~ enters, name a keyword ability or ability word.\n"
                                "All cards in all zones lose that keyword ability or ability word and all text tied to that ability.",
                    )
    assert not parse_oracle(spyglass).modeled


# ---------------------------------------------------------------------------
# The as-enters choice itself
# ---------------------------------------------------------------------------


def test_meddling_mage_pauses_before_entering_and_a_named_spell_cannot_be_cast_by_anyone():
    engine, state, p1, p2 = game()
    put(engine, island(), p2, Zone.BATTLEFIELD)
    spell_p2 = put(engine, bolt(), p2)
    spell_p1 = put(engine, bolt(), p1)
    other = put(engine, shock_bear(), p1)
    p2.mana_pool.add_many({"R": 2})
    p1.mana_pool.add_many({"R": 2, "G": 2})
    assert engine.can_cast(p2, spell_p2)

    mage = put(engine, named("Meddling Mage"), p1)
    p1.mana_pool.add_many({"W": 1, "U": 1})
    engine.cast_spell(p1, mage)
    engine.resolve_until_stable()

    pending = state.pending_choice
    assert pending["kind"] == "choose_card_name" and pending["free_text"]
    assert pending["card_filter"] == {"without_type": "land"}
    assert mage not in state.battlefield  # RULE 614.12: chosen before it enters
    # A land the game knows is no legal "nonland card name": nothing is named.
    assert "Island" not in {o["id"] for o in pending["options"]}

    engine.resolve_pending_choice("lightning bolt")  # case-insensitive
    engine.resolve_until_stable()

    assert mage in state.battlefield and mage.chosen_card_name == "lightning bolt"
    assert not engine.can_cast(p2, spell_p2)  # an opponent's
    assert not engine.can_cast(p1, spell_p1)  # and its own controller's: "Spells ... can't be cast"
    assert engine.can_cast(p1, other)  # any other name is fine


def test_a_known_land_is_refused_as_a_nonland_name_and_names_nothing():
    engine, state, p1, p2 = game()
    put(engine, island(), p2, Zone.BATTLEFIELD)
    mage = put(engine, named("Meddling Mage"), p1)
    p1.mana_pool.add_many({"W": 1, "U": 1})
    engine.cast_spell(p1, mage)
    engine.resolve_until_stable()
    engine.resolve_pending_choice("Island")
    engine.resolve_until_stable()
    assert mage in state.battlefield and mage.chosen_card_name == ""


def test_the_name_prohibition_ends_with_its_source():
    engine, state, p1, p2 = game()
    spell = put(engine, bolt(), p2)
    p2.mana_pool.add_many({"R": 1})
    mage = enter(engine, p1, "Meddling Mage", "Lightning Bolt")
    assert not engine.can_cast(p2, spell)
    engine.rules.destroy(mage)
    engine.resolve_until_stable()
    assert engine.can_cast(p2, spell)


# ---------------------------------------------------------------------------
# Activated abilities of sources with the chosen name
# ---------------------------------------------------------------------------


def _draw_ability(engine, obj, player, cost_text="{T}: Draw a card."):
    ability = ActivatedAbility(effects=[DrawCardEffect(1, player=player)], cost=parse_activation_cost(cost_text), source=obj)
    obj.activated_abilities.append(ability)
    return ability


def _library(player, count=4):
    for i in range(count):
        player.library.append(GameObject(island(), owner_id=player.id, zone=Zone.LIBRARY))


def test_voidstone_gargoyle_silences_the_named_permanents_abilities_and_its_spell_casts():
    engine, state, p1, p2 = game()
    bear = put(engine, shock_bear(), p2, Zone.BATTLEFIELD)
    ability = _draw_ability(engine, bear, p2)
    plain = put(engine, shock_bear(), p2, Zone.BATTLEFIELD)
    plain.card = Card(id="plain", name="Plain Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2)
    plain_ability = _draw_ability(engine, plain, p2)
    spell = put(engine, shock_bear(), p2)
    p2.mana_pool.add_many({"G": 2})

    enter(engine, p1, "Voidstone Gargoyle", "Grizzly Bears")

    assert not engine.can_activate(p2, bear, ability)
    assert engine.can_activate(p2, plain, plain_ability)  # a different name keeps its ability
    assert not engine.can_cast(p2, spell)  # "Spells with the chosen name can't be cast" too


def test_the_name_lock_reaches_a_source_that_is_not_on_the_battlefield():
    from mtg_analyzer.game import continuous

    engine, state, p1, p2 = game()
    in_hand = put(engine, shock_bear(), p2)  # e.g. a cycling or channel ability is activated from the hand
    enter(engine, p1, "Voidstone Gargoyle", "Grizzly Bears")
    assert continuous.activation_prohibited(state, in_hand)


def test_sorcerous_spyglass_keeps_the_named_mana_abilities():
    engine, state, p1, p2 = game()
    put(engine, shock_bear(), p2, Zone.BATTLEFIELD)
    elves = put(engine, Card(id="elves", name="Llanowar Elves", type_line="Creature — Elf Druid", is_creature=True,
                             power=1, toughness=1, oracle_text="{T}: Add {G}.", mana_cost_string="{G}",
                             converted_mana_cost=1), p2, Zone.BATTLEFIELD)
    draw = _draw_ability(engine, elves, p2)
    put(engine, bolt(), p2)  # something to look at

    spyglass = enter(engine, p1, "Sorcerous Spyglass", "ok", "Llanowar Elves")

    assert spyglass.chosen_card_name == "Llanowar Elves"
    assert not engine.can_activate(p2, elves, draw)
    assert engine.tap_for_mana(p2, elves).get("G") == 1  # RULE 605: "unless they're mana abilities"


def test_skyseers_chariot_taxes_the_named_ability_but_not_its_mana_ability():
    engine, state, p1, p2 = game()
    bear = put(engine, shock_bear(), p2, Zone.BATTLEFIELD)
    _draw_ability(engine, bear, p2, "{T}: Draw a card.")
    other = put(engine, shock_bear(), p2, Zone.BATTLEFIELD)
    other.card = Card(id="o", name="Other Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2)
    _library(p2)
    enter(engine, p1, "Skyseer's Chariot", "Grizzly Bears")
    p2.mana_pool.add_many({"C": 5})

    engine.activate_ability(p2, bear)
    assert p2.mana_pool.total() == 3  # {2} more to activate
    from mtg_analyzer.game import continuous

    assert continuous.activation_cost_reduction_for(state, bear)[0] == -2
    assert continuous.activation_cost_reduction_for(state, other)[0] == 0
    assert continuous.activation_cost_reduction_for(state, bear, is_mana_ability=True)[0] == -2  # Chariot has no carve-out


# ---------------------------------------------------------------------------
# "Look at an opponent's hand, then choose any card name"
# ---------------------------------------------------------------------------


def _cast_spyglass(engine, player):
    obj = put(engine, named("Sorcerous Spyglass"), player)
    player.mana_pool.add_many({"C": 2})
    engine.cast_spell(player, obj)
    engine.resolve_until_stable()
    return obj


def test_the_hand_is_shown_only_to_the_looking_player_before_the_naming():
    engine, state, p1, p2 = game()
    secret = put(engine, bolt(), p2)
    spyglass = _cast_spyglass(engine, p1)

    look = state.pending_choice
    assert look["kind"] == "look_hand" and look["player_id"] == "p1" and look["owner_id"] == "p2"
    assert [o["instance_id"] for o in look["options"] if "instance_id" in o] == [secret.instance_id]
    assert spyglass not in state.battlefield

    session = GameSession(engine)
    assert session.view(perspective="p1")["state"]["pending_choice"]["kind"] == "look_hand"
    opposing = session.view(perspective="p2")
    assert opposing["state"]["pending_choice"] is None  # RULE 400.2: the looked-at hand is not shown to its owner's view
    assert "Lightning Bolt" not in str(opposing["state"].get("waiting_on_choice"))

    engine.resolve_pending_choice("ok")
    engine.resolve_until_stable()
    naming = state.pending_choice
    assert naming["kind"] == "choose_card_name" and naming["free_text"]
    assert "card_filter" not in naming  # "any card name": no qualifier
    engine.resolve_pending_choice("Sol Ring")  # any card name at all, in the hand or not
    engine.resolve_until_stable()
    assert spyglass in state.battlefield and spyglass.chosen_card_name == "Sol Ring"


def test_nothing_to_look_at_goes_straight_to_the_naming():
    engine, state, p1, p2 = game()
    _cast_spyglass(engine, p1)
    assert state.pending_choice["kind"] == "choose_card_name"


def test_with_several_opponents_the_controller_picks_whose_hand_to_look_at():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    state = engine.state
    p1, p2, p3 = (state.player_by_id(i) for i in ("p1", "p2", "p3"))
    put(engine, bolt(), p2)
    third = put(engine, shock_bear(), p3)
    _cast_spyglass(engine, p1)

    assert state.pending_choice["kind"] == "choose_opponent_on_enter"
    engine.resolve_pending_choice("p3")
    engine.resolve_until_stable()
    look = state.pending_choice
    assert look["kind"] == "look_hand" and look["owner_id"] == "p3"
    assert [o["instance_id"] for o in look["options"] if "instance_id" in o] == [third.instance_id]


def test_anointed_peacekeeper_taxes_only_opposing_named_spells_and_named_non_mana_abilities():
    from mtg_analyzer.game import continuous

    engine, state, p1, p2 = game()
    theirs = put(engine, bolt(), p2)
    mine = put(engine, bolt(), p1)
    elves = put(engine, Card(id="elves", name="Llanowar Elves", type_line="Creature — Elf Druid", is_creature=True,
                             power=1, toughness=1, oracle_text="{T}: Add {G}."), p2, Zone.BATTLEFIELD)
    draw = _draw_ability(engine, elves, p2)
    put(engine, bolt(), p2)
    enter(engine, p1, "Anointed Peacekeeper", "ok", "Lightning Bolt")

    assert continuous.cost_reduction_for(state, p2, theirs)[0] == -2
    assert continuous.cost_reduction_for(state, p1, mine)[0] == 0  # "Spells your opponents cast"
    peacekeeper_name = next(o for o in state.battlefield if o.card.name == "Anointed Peacekeeper")
    peacekeeper_name.chosen_card_name = "Llanowar Elves"
    assert continuous.activation_cost_reduction_for(state, elves)[0] == -2
    assert continuous.activation_cost_reduction_for(state, elves, is_mana_ability=True)[0] == 0
    assert draw in elves.activated_abilities


# ---------------------------------------------------------------------------
# Cost changes and "whenever ... casts a spell with the chosen name"
# ---------------------------------------------------------------------------


def test_council_of_the_absolute_discounts_my_named_spells_and_bars_my_opponents():
    from mtg_analyzer.game import continuous

    engine, state, p1, p2 = game()
    mine = put(engine, bolt(), p1)
    theirs = put(engine, bolt(), p2)
    p1.mana_pool.add_many({"W": 1, "U": 1})
    p2.mana_pool.add_many({"R": 1})
    enter(engine, p1, "Council of the Absolute", "Lightning Bolt")

    assert continuous.cost_reduction_for(state, p1, mine)[0] == 2
    assert not engine.can_cast(p2, theirs)
    p1.mana_pool.add_many({"R": 1})
    assert engine.can_cast(p1, mine)  # the controller keeps casting it, for less


def test_council_of_the_absolute_refuses_a_creature_or_land_name():
    engine, state, p1, p2 = game()
    put(engine, shock_bear(), p2, Zone.BATTLEFIELD)
    council = enter(engine, p1, "Council of the Absolute", "Grizzly Bears")
    assert council.chosen_card_name == ""  # "noncreature, nonland": a known creature card names nothing


def test_curse_of_silence_taxes_the_enchanted_players_named_spells_and_can_be_sacrificed_for_a_card():
    from mtg_analyzer.game import continuous

    engine, state, p1, p2 = game()
    _library(p1)
    theirs = put(engine, bolt(), p2)
    mine = put(engine, bolt(), p1)
    curse = enter(engine, p1, "Curse of Silence", "Lightning Bolt", targets=[p2])  # an Aura enchanting a *player* (RULE 303.4)

    assert curse.attached_to == "p2" and curse.chosen_card_name == "Lightning Bolt"
    assert continuous.cost_reduction_for(state, p2, theirs)[0] == -2
    assert continuous.cost_reduction_for(state, p1, mine)[0] == 0  # only the enchanted player pays

    hand_before = len(p1.hand)
    p2.mana_pool.add_many({"R": 3})
    engine.cast_spell(p2, theirs, targets=[p1])
    engine.resolve_until_stable()
    assert state.pending_choice["kind"] == "trigger_target"  # "you may sacrifice this Aura"
    engine.resolve_pending_choice("do")
    engine.resolve_until_stable()
    assert curse not in state.battlefield and len(p1.hand) == hand_before + 1


def test_curse_of_silence_does_not_trigger_for_an_unnamed_spell():
    engine, state, p1, p2 = game()
    _library(p1)
    other = put(engine, shock(), p2)
    curse = enter(engine, p1, "Curse of Silence", "Lightning Bolt", targets=[p2])
    p2.mana_pool.add_many({"R": 3})
    engine.cast_spell(p2, other, targets=[p1])
    engine.resolve_until_stable()
    assert curse in state.battlefield and not state.pending_choice


def test_silverquill_silencer_punishes_an_opponents_named_spell_only():
    engine, state, p1, p2 = game()
    _library(p1)
    named_spell = put(engine, bolt(), p2)
    other_spell = put(engine, shock(), p2)
    mine = put(engine, bolt(), p1)
    enter(engine, p1, "Silverquill Silencer", "Lightning Bolt")
    life, hand = p2.life, len(p1.hand)

    p2.mana_pool.add_many({"R": 3})
    engine.cast_spell(p2, other_spell, targets=[p1])
    engine.resolve_until_stable()
    assert p2.life == life and len(p1.hand) == hand  # an unnamed spell does nothing
    engine.cast_spell(p2, named_spell, targets=[p1])
    engine.resolve_until_stable()
    assert p2.life == life - 3 and len(p1.hand) == hand + 1

    before, p2_life = len(p1.hand), p2.life
    p1.mana_pool.add_many({"R": 1})
    engine.cast_spell(p1, mine, targets=[p2])
    engine.resolve_until_stable()
    assert len(p1.hand) == before - 1  # "Whenever an opponent casts": its controller's own cast draws nothing
    assert p2.life == p2_life - 3  # (that is only the Bolt itself)


def test_declaration_of_naught_counters_only_a_spell_with_the_chosen_name():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    engine, state, p1, p2 = game()
    named_spell = put(engine, bolt(), p2)
    other_spell = put(engine, shock(), p2)
    declaration = enter(engine, p1, "Declaration of Naught", "Lightning Bolt")
    p2.mana_pool.add_many({"R": 2})
    engine.cast_spell(p2, named_spell, targets=[p1])
    engine.cast_spell(p2, other_spell, targets=[p1])

    ability = next(a for a in declaration.activated_abilities)
    options = legal_targets(state, "p1", ability.effects[0].target_spec, source=declaration)
    assert [o["instance_id"] for o in options] == [named_spell.instance_id]

    # ... and the activation really counters it, while the unnamed spell is no legal target.
    p1.mana_pool.add_many({"U": 1})
    with pytest.raises(Exception):
        engine.activate_ability(p1, declaration, targets=[other_spell])
    engine.activate_ability(p1, declaration, targets=[named_spell])
    engine.resolve_until_stable()
    assert named_spell in p2.graveyard


# ---------------------------------------------------------------------------
# Damage prevention and protection keyed on the name
# ---------------------------------------------------------------------------


def _burn(engine, source, target, amount=3):
    life = getattr(target, "life", None)
    engine.rules.deal_damage(target, amount, source=source)
    return life


def test_gideons_intervention_prevents_damage_from_the_named_source_to_me_and_my_permanents_only():
    engine, state, p1, p2 = game()
    my_bear = put(engine, shock_bear(), p1, Zone.BATTLEFIELD)
    their_bear = put(engine, shock_bear(), p2, Zone.BATTLEFIELD)
    named_source = put(engine, bolt(), p2, Zone.BATTLEFIELD)  # any object called "Lightning Bolt"
    other_source = put(engine, shock(), p2, Zone.BATTLEFIELD)
    gideon = enter(engine, p1, "Gideon's Intervention", "Lightning Bolt")
    assert gideon.chosen_card_name == "Lightning Bolt"

    engine.rules.deal_damage(p1, 3, source=named_source)
    engine.rules.deal_damage(my_bear, 3, source=named_source)
    assert p1.life == 20 and my_bear.damage_marked == 0  # prevented

    engine.rules.deal_damage(p1, 2, source=other_source)
    assert p1.life == 18  # a different name still hurts

    engine.rules.deal_damage(p2, 3, source=named_source)
    engine.rules.deal_damage(their_bear, 3, source=named_source)
    assert p2.life == 17 and their_bear.damage_marked == 3  # "to you and permanents you control" only

    spell = put(engine, bolt(), p2)
    p2.mana_pool.add_many({"R": 1})
    assert not engine.can_cast(p2, spell)  # and the same name can't be cast by opponents


def test_gideons_intervention_does_not_prevent_what_cannot_be_prevented():
    engine, state, p1, p2 = game()
    named_source = put(engine, bolt(), p2, Zone.BATTLEFIELD)
    enter(engine, p1, "Gideon's Intervention", "Lightning Bolt")
    engine.rules.disable_damage_prevention_this_turn()  # RULE 615.12
    engine.rules.deal_damage(p1, 3, source=named_source)
    assert p1.life == 17


def test_runed_halo_gives_its_controller_protection_from_the_name():
    from mtg_analyzer.game import continuous
    from mtg_analyzer.game.combat import protection_qualities_cover

    engine, state, p1, p2 = game()
    named_source = put(engine, bolt(), p2, Zone.BATTLEFIELD)
    other_source = put(engine, shock(), p2, Zone.BATTLEFIELD)
    halo = enter(engine, p1, "Runed Halo", "lightning bolt")

    assert halo.chosen_card_name == "lightning bolt"
    assert continuous.player_protected_from_source(state, p1, named_source)  # RULE 702.16b: can't be targeted
    assert not continuous.player_protected_from_source(state, p1, other_source)
    assert not continuous.player_protected_from_source(state, p2, named_source)  # only its controller
    assert protection_qualities_cover(continuous.player_static_protections(state, p1), named_source)

    engine.rules.deal_damage(p1, 3, source=named_source)
    assert p1.life == 20  # RULE 702.16e: damage prevented
    engine.rules.deal_damage(p1, 2, source=other_source)
    assert p1.life == 18
    # The Halo itself is no permanent with protection: nothing is granted to an object.
    assert not getattr(halo, "granted_protections", None)


def test_runed_halo_protection_blocks_targeting_by_the_named_spell():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    engine, state, p1, p2 = game()
    named_source = put(engine, bolt(), p2, Zone.BATTLEFIELD)
    other_source = put(engine, shock(), p2, Zone.BATTLEFIELD)
    enter(engine, p1, "Runed Halo", "Lightning Bolt")
    spec = TargetSpec(kind="any")
    targets_named = {o.get("player_id") for o in legal_targets(state, "p2", spec, source=named_source)}
    targets_other = {o.get("player_id") for o in legal_targets(state, "p2", spec, source=other_source)}
    assert "p1" not in targets_named and "p1" in targets_other


# ---------------------------------------------------------------------------
# Alpine Moon
# ---------------------------------------------------------------------------


def breeding_pool() -> Card:
    return Card(id="pool", name="Breeding Pool", type_line="Land — Forest Island", is_land=True,
                oracle_text="({T}: Add {G} or {U}.)\nAs Breeding Pool enters, you may pay 2 life. If you don't, it enters tapped.")


def test_alpine_moon_turns_the_opponents_named_nonbasic_land_into_a_plain_any_color_land():
    from mtg_analyzer.game import continuous
    from mtg_analyzer.game.mana_abilities import mana_options_for

    engine, state, p1, p2 = game()
    theirs = put(engine, breeding_pool(), p2, Zone.BATTLEFIELD)
    mine = put(engine, breeding_pool(), p1, Zone.BATTLEFIELD)
    engine.recompute_continuous_effects()
    assert {tuple(o) for o in mana_options_for(theirs, state)} == {("G",), ("U",)}

    moon = enter(engine, p1, "Alpine Moon", "Breeding Pool")
    engine.recompute_continuous_effects()

    assert moon.chosen_card_name == "Breeding Pool"
    assert not continuous.has_subtype(theirs, "Forest") and not continuous.has_subtype(theirs, "Island")  # land types gone
    assert theirs.loses_all_abilities
    assert {tuple(o) for o in mana_options_for(theirs, state)} == {("W",), ("U",), ("B",), ("R",), ("G",)}
    produced = engine.tap_for_mana(p2, theirs)
    assert sum(produced.values()) == 1
    # "Lands your opponents control": the controller's own copy is untouched.
    assert continuous.has_subtype(mine, "Forest") and not mine.loses_all_abilities


def test_alpine_moon_refuses_a_basic_land_name():
    engine, state, p1, p2 = game()
    put(engine, island(), p2, Zone.BATTLEFIELD)
    moon = enter(engine, p1, "Alpine Moon", "Island")
    assert moon.chosen_card_name == ""  # "nonbasic land card name"


def test_alpine_moon_refuses_a_nonland_name():
    engine, state, p1, p2 = game()
    put(engine, bolt(), p2, Zone.BATTLEFIELD)
    moon = enter(engine, p1, "Alpine Moon", "Lightning Bolt")
    assert moon.chosen_card_name == ""


def test_alpine_moon_keeps_a_non_land_subtype_it_does_not_remove():
    from mtg_analyzer.game import continuous

    engine, state, p1, p2 = game()
    dryad = put(engine, Card(id="dryad", name="Dryad Arbor", type_line="Land Creature — Forest Dryad", is_land=True,
                             is_creature=True, power=1, toughness=1, oracle_text="(This card is every land type.)"),
                p2, Zone.BATTLEFIELD)
    enter(engine, p1, "Alpine Moon", "Dryad Arbor")
    engine.recompute_continuous_effects()
    assert continuous.has_subtype(dryad, "Dryad") and not continuous.has_subtype(dryad, "Forest")


# ---------------------------------------------------------------------------
# Session level: clone/undo, bots, and what each seat sees
# ---------------------------------------------------------------------------


def _session_with_mage():
    engine, state, p1, p2 = game()
    spell = put(engine, bolt(), p2)
    mage = put(engine, named("Meddling Mage"), p1)
    p1.mana_pool.add_many({"W": 1, "U": 1})
    session = GameSession(engine, require_setup=False)
    return session, mage, spell


def _cast_through_the_session(session):
    cast = next(a for a in session.legal_actions("p1") if a["type"] == "cast_spell")
    session.apply_action(cast, "p1")
    session.engine.resolve_until_stable()


def test_the_chosen_name_survives_a_state_clone_and_an_undo_of_the_whole_cast():
    session, mage, spell = _session_with_mage()
    _cast_through_the_session(session)
    session.apply_action({"type": "choose", "free_text": True, "option_id": "Lightning Bolt"}, "p1")

    # A clone (what undo/snapshots restore from) keeps the stamped name, so the lock still applies to it.
    clone = session.engine.state.clone()
    cloned_mage = next(o for o in clone.battlefield if o.card.name == "Meddling Mage")
    assert cloned_mage.chosen_card_name == "Lightning Bolt"
    cloned_p2 = clone.player_by_id("p2")
    cloned_p2.mana_pool.add_many({"R": 1})
    assert not GameEngine(clone).can_cast(cloned_p2, cloned_p2.hand[0])

    # Undoing the answer and the cast puts the Mage back in hand with no name; casting it again names afresh.
    session.rewind(2)
    engine = session.engine
    assert not any(o.card.name == "Meddling Mage" for o in engine.state.battlefield)
    hand_mage = next(o for o in engine.state.player_by_id("p1").hand if o.card.name == "Meddling Mage")
    assert hand_mage.chosen_card_name is None
    engine.state.player_by_id("p1").mana_pool.add_many({"W": 1, "U": 1})
    _cast_through_the_session(session)
    session.apply_action({"type": "choose", "free_text": True, "option_id": "Shock"}, "p1")
    entered = next(o for o in session.engine.state.battlefield if o.card.name == "Meddling Mage")
    assert entered.chosen_card_name == "Shock"
    bolt_obj = session.engine.state.player_by_id("p2").hand[0]
    session.engine.state.player_by_id("p2").mana_pool.add_many({"R": 1})
    assert session.engine.can_cast(session.engine.state.player_by_id("p2"), bolt_obj)  # Bolt is free again


def test_a_new_object_has_made_no_naming_choice():
    engine, state, p1, p2 = game()
    mage = enter(engine, p1, "Meddling Mage", "Lightning Bolt")
    assert mage.chosen_card_name == "Lightning Bolt"
    mage.reset_as_new_object()  # RULE 400.7: it left and came back as a new object
    assert mage.chosen_card_name is None


@pytest.mark.parametrize("bot_name", ["Bot", "GreedyBot", "SmartBot"])
def test_bots_answer_the_naming_with_an_opposing_card_the_filter_allows(bot_name):
    from mtg_analyzer.services.bots import Bot, GreedyBot
    from mtg_analyzer.services.bot_policies.smart import SmartBot

    bot_class = {"Bot": Bot, "GreedyBot": GreedyBot, "SmartBot": SmartBot}[bot_name]
    engine, state, p1, p2 = game()
    mage = put(engine, named("Meddling Mage"), p1)
    mine = put(engine, shock_bear(), p1, Zone.BATTLEFIELD)
    mine.card = Card(id="a", name="Aardvark", type_line="Creature — Beast", is_creature=True, power=1, toughness=1)
    put(engine, island(), p2, Zone.BATTLEFIELD)
    theirs = put(engine, shock_bear(), p2, Zone.BATTLEFIELD)
    theirs.card = Card(id="z", name="Zealot", type_line="Creature — Human", is_creature=True, power=1, toughness=1)
    p1.mana_pool.add_many({"W": 1, "U": 1})
    session = GameSession(engine, require_setup=False)
    _cast_through_the_session(session)

    answer = bot_class("p1").answer_choice(session.view("p1"), session.legal_actions("p1"))
    session.apply_action(answer, "p1")
    session.engine.resolve_until_stable()

    entered = next(o for o in session.engine.state.battlefield if o.card.name == "Meddling Mage")
    # The suggestions offer an opposing card first and never the Island ("nonland").
    assert entered.chosen_card_name == "Zealot"


def test_a_bot_walks_the_whole_look_then_name_chain():
    from mtg_analyzer.services.bots import Bot

    engine, state, p1, p2 = game()
    put(engine, bolt(), p2)
    spyglass = put(engine, named("Sorcerous Spyglass"), p1)
    p1.mana_pool.add_many({"C": 2})
    session = GameSession(engine, require_setup=False)
    _cast_through_the_session(session)
    kinds = []
    bot = Bot("p1")
    for _ in range(4):
        pending = session.engine.state.pending_choice
        if pending is None:
            break
        kinds.append(pending["kind"])
        session.apply_action(bot.answer_choice(session.view("p1"), session.legal_actions("p1")), "p1")
        session.engine.resolve_until_stable()
    assert kinds == ["look_hand", "choose_card_name"]
    assert any(o.card.name == "Sorcerous Spyglass" for o in session.engine.state.battlefield)
