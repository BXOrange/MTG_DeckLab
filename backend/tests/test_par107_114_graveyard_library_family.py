"""PAR-107…114 residue batches, part 1 — graveyard / library / exile shapes (and the sacrificed-creature axis).

New axes (each measured over the whole card cache, 0 regressed):

* "put it into its owner's library third from the top" — `return_to_library`'s ``depth`` (RULE 401.7), the self
  form ("put ~ / it …"), and `search`'s ``library_third`` destination (Long-Term Plans);
* "counter target spell unless its controller pays {1} for each card in your graveyard";
* "target player exiles a card from their graveyard" — `exile_hand_card`'s ``zone`` (the player chooses);
* "exile target permanent with mana value 4 or greater" — `TargetSpec.min_mana_value`;
* "return all artifact and enchantment cards from your graveyard to the battlefield";
* "look at the top N cards of target player's library, then put them back in any order" —
  `look_reorder_top` (scry without the bottom option), X from a "where x is …" between two parts of the sentence;
* "the sacrificed creature's power / toughness / mana value" as an amount (a cost's or an effect's own sacrifice).

Reference: parser/oracle/catalogue/handlers.py, count_phrase.py, segmenter.py, game/rules/*_mixin.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _card(name, type_line="Creature — Bear", oracle_text="", **kw):
    kw.setdefault("converted_mana_cost", 2)
    creature = "Creature" in type_line
    kw.setdefault("power", 2 if creature else None)
    kw.setdefault("toughness", 2 if creature else None)
    return Card(
        id=name, name=name, type_line=type_line, oracle_text=oracle_text, is_creature=creature,
        is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
        is_land="Land" in type_line, **kw,
    )


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    player = eng.state.player_by_id(controller)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        player.add_to_zone(obj, zone)
    return obj


def _fill_library(eng, controller, n):
    player = eng.state.player_by_id(controller)
    cards = []
    for i in range(n):
        obj = GameObject(_card(f"{controller}-lib{i}", "Instant"), owner_id=controller, zone=Zone.LIBRARY)
        player.library.append(obj)
        cards.append(obj)
    return cards


def _parse(text):
    return parse_effect_body(normalize(text))


def _cast(eng, name, type_line, text, targets=None, controller="p1", cmc=0):
    player = eng.state.player_by_id(controller)
    spell = GameObject(_card(name, type_line, text, converted_mana_cost=cmc), owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.add_to_zone(spell, Zone.HAND)
    eng.cast_spell(player, spell, targets=targets or [])
    return spell


# --- Nth from the top ---------------------------------------------------------------------------------


def test_nth_from_top_parses_for_every_put_shape():
    [spec] = _parse("Put it into its owner's library third from the top.") or [None]
    assert spec is None  # a bare "it" names nobody without a self-subject trigger
    [spec] = _parse("Put ~ into its owner's library third from the top.")
    assert spec.type == "return_to_library"
    assert spec.params == {"target_kind": None, "position": "top", "depth": 3}
    [spec] = _parse("Put target creature into its owner's library second from the top.")
    assert spec.params == {"target_kind": "creature", "position": "top", "depth": 2}
    [spec] = _parse("Put ~ on the bottom of its owner's library.")
    assert spec.params == {"target_kind": None, "position": "bottom"}
    # "on top" has no depth key at all
    [spec] = _parse("Put target creature on top of its owner's library.")
    assert "depth" not in spec.params


@pytest.mark.parametrize("depth, library_size, expected_index", [
    (3, 6, -3),   # two cards stay above it
    (2, 6, -2),
    (3, 2, 0),    # RULE 401.7: fewer than N cards puts it on the bottom
    (3, 0, 0),
])
def test_return_to_library_depth_places_the_card_nth_from_the_top(depth, library_size, expected_index):
    eng = _engine()
    _fill_library(eng, "p1", library_size)
    obj = _put(eng, _card("Sphinx"))
    eng.rules.return_to_library(obj, "top", depth)
    library = eng.state.player_by_id("p1").library
    assert library[expected_index] is obj
    assert len(library) == library_size + 1


def test_god_eternal_goes_third_from_the_top_when_it_dies():
    text = ("When ~ dies or is put into exile from the battlefield, you may put it into its owner's "
            "library third from the top.")
    card = _card("God-Eternal Test", "Creature — Zombie God", text)
    assert parse_oracle(card).modeled
    eng = _engine()
    _fill_library(eng, "p1", 5)
    god = _put(eng, card)
    eng.rules.put_into_graveyard(god)
    eng.resolve_until_stable()
    while eng.state.pending_choice:
        eng.resolve_pending_choice("do")
    library = eng.state.player_by_id("p1").library
    assert library[-3] is god and god.zone == Zone.LIBRARY


def test_fell_horseman_goes_to_the_bottom():
    card = _card("Horseman Test", "Creature — Zombie Knight", "When ~ dies, put it on the bottom of its owner's library.")
    assert parse_oracle(card).modeled
    eng = _engine()
    _fill_library(eng, "p1", 4)
    horse = _put(eng, card)
    eng.rules.put_into_graveyard(horse)
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p1").library[0] is horse


def test_long_term_plans_search_lands_third_from_the_top():
    card = _card("Plans Test", "Instant",
                 "Search your library for a card, then shuffle and put that card third from the top.")
    assert parse_oracle(card).modeled
    [spec] = _parse("Search your library for a card, then shuffle and put that card third from the top.")
    assert spec.params["destination"] == "library_third"
    eng = _engine()
    cards = _fill_library(eng, "p1", 6)
    _cast(eng, "Plans Test", "Instant", card.oracle_text)
    eng.resolve_until_stable()
    assert eng.state.pending_choice is not None
    chosen = cards[0]
    eng.resolve_pending_choice(chosen.instance_id)
    library = eng.state.player_by_id("p1").library
    assert library[-3] is chosen
    assert len(library) == 6


# --- counter unless … for each card in your graveyard --------------------------------------------------


def test_circular_logic_tax_is_one_per_graveyard_card():
    text = "Counter target spell unless its controller pays {1} for each card in your graveyard."
    [spec] = _parse(text)
    assert spec.type == "counter"
    assert spec.params["unless_pays"] == "{0}"
    assert spec.params["unless_pays_extra_selector"] == "cards_in_your_graveyard"
    # only a {1} unit is a graveyard tax; another cost is a different card
    assert not _parse("Counter target spell unless its controller pays {2} for each card in your graveyard.")

    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext

    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    logic = _put(eng, _card("Circular Logic", "Instant", text), zone=Zone.HAND)
    effect = EffectRegistry.create("counter", dict(spec.params))
    effect.source = logic
    ctx = GameContext(eng.state, eng.rules)
    assert effect._unless_pays_cost(ctx) == "{0}"  # empty graveyard: nothing to pay
    for i in range(3):
        _put(eng, _card(f"Dead{i}", "Instant"), zone=Zone.GRAVEYARD)
    assert len(p1.graveyard) == 3
    assert effect._unless_pays_cost(ctx) == "{3}"


# --- target player exiles a card from their graveyard --------------------------------------------------


def test_exile_a_card_from_their_graveyard_parses_and_lets_the_player_choose():
    [spec] = _parse("Target player exiles a card from their graveyard.")
    assert spec.type == "exile_hand_card"
    assert spec.params == {"count": 1, "target_kind": "player", "zone": "graveyard"}
    # the hand form is unchanged
    [spec] = _parse("Target opponent exiles a card from their hand.")
    assert "zone" not in spec.params

    eng = _engine()
    first = _put(eng, _card("First", "Instant"), controller="p2", zone=Zone.GRAVEYARD)
    second = _put(eng, _card("Second", "Instant"), controller="p2", zone=Zone.GRAVEYARD)
    bonegnawer = _put(eng, _card(
        "Merrow Test", "Creature — Merfolk", "{T}: Target player exiles a card from their graveyard."))
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    eng.activate_ability(p1, bonegnawer, 0, targets=[p2])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["player_id"] == "p2"
    eng.resolve_pending_choice(second.instance_id)
    assert second in p2.exile and first in p2.graveyard


# --- exile target permanent with mana value N or greater ----------------------------------------------


def test_exile_by_mana_value_floor_and_ceiling():
    [spec] = _parse("Exile target permanent with mana value 4 or greater.")
    assert spec.type == "exile" and spec.params == {"target_kind": "permanent", "min_mana_value": 4}
    [spec] = _parse("Exile target nonland permanent with mana value 3 or less.")
    assert spec.params == {"target_kind": "nonland_permanent", "max_mana_value": 3}
    [spec] = _parse("Destroy target creature with mana value 5 or greater.")
    assert spec.type == "destroy" and spec.params["min_mana_value"] == 5


def test_despark_only_offers_permanents_at_or_above_the_floor():
    eng = _engine()
    cheap = _put(eng, _card("Cheap", "Creature — Bear", converted_mana_cost=3), controller="p2")
    dear = _put(eng, _card("Dear", "Creature — Bear", converted_mana_cost=4), controller="p2")
    despark = GameObject(
        _card("Despark", "Instant", "Exile target permanent with mana value 4 or greater.", converted_mana_cost=0),
        owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(despark)
    spec = targeting.TargetSpec(kind="permanent", min_mana_value=4)
    legal = targeting.legal_targets(eng.state, "p1", spec, source=despark)
    ids = {t["instance_id"] for t in legal}
    assert dear.instance_id in ids and cheap.instance_id not in ids
    eng.state.player_by_id("p1").add_to_zone(despark, Zone.HAND)
    eng.cast_spell(eng.state.player_by_id("p1"), despark, targets=[dear])
    eng.resolve_until_stable()
    assert dear in eng.state.player_by_id("p2").exile and cheap in eng.state.battlefield


# --- return all artifact and enchantment cards from your graveyard -------------------------------------


def test_brilliant_restoration_returns_only_artifacts_and_enchantments():
    text = "Return all artifact and enchantment cards from your graveyard to the battlefield."
    assert parse_oracle(_card("Brilliant Test", "Sorcery", text)).modeled
    eng = _engine()
    rock = _put(eng, _card("Rock", "Artifact"), zone=Zone.GRAVEYARD)
    aura = _put(eng, _card("Pacifism", "Enchantment — Aura"), zone=Zone.GRAVEYARD)
    bear = _put(eng, _card("Bear", "Creature — Bear"), zone=Zone.GRAVEYARD)
    _cast(eng, "Brilliant Test", "Sorcery", text)
    eng.resolve_until_stable()
    assert rock in eng.state.battlefield and aura in eng.state.battlefield
    assert bear not in eng.state.battlefield and bear.zone == Zone.GRAVEYARD


# --- look at the top N cards of [target player's] library, put them back in any order -------------------


def test_look_reorder_top_parses_own_target_and_x_forms():
    [spec] = _parse("Look at the top 3 cards of your library, then put them back in any order.")
    assert spec.type == "look_reorder_top" and spec.params == {"count": 3}
    [spec] = _parse("Look at the top 3 cards of target player's library, then put them back in any order.")
    assert spec.params == {"count": 3, "target_kind": "player"}
    [spec] = _parse("Look at the top x cards of your library, where x is the number of cards in your hand, "
                    "then put them back in any order.")
    assert spec.type == "bind" and spec.params["effects"][0]["type"] == "look_reorder_top"
    assert spec.params["effects"][0]["params"]["count"] == "$n"


def test_looking_at_an_opponents_library_reorders_it_and_cannot_bottom_cards():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    cards = _fill_library(eng, "p2", 5)  # top is the list end: cards[4] is on top
    augury = _put(eng, _card(
        "Augury Test", "Creature — Elemental",
        "{3}: Look at the top 3 cards of target player's library, then put them back in any order."))
    p1.mana_pool.add_many({"C": 3})
    eng.activate_ability(p1, augury, 0, targets=[p2])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "reorder_top" and choice["player_id"] == "p1"
    assert choice["library_owner_id"] == "p2" and choice["phase"] == "order"
    # no way to send a card away: the only options are the three cards and "keep the order"
    ids = [o["instance_id"] for o in choice["options"] if "instance_id" in o]
    assert ids == [cards[4].instance_id, cards[3].instance_id, cards[2].instance_id]
    eng.resolve_pending_choice(cards[2].instance_id)  # becomes the new top
    eng.resolve_pending_choice(None)                  # keep the rest as they were
    # top first: the picked card, then the other two in the order they were already in
    assert [o.instance_id for o in reversed(p2.library[-3:])] == [
        cards[2].instance_id, cards[4].instance_id, cards[3].instance_id]
    assert len(p2.library) == 5


# --- the sacrificed creature's power ------------------------------------------------------------------


def test_sacrificed_creature_amounts_parse_as_one_axis():
    for what, selector in (("power", "sacrificed_cost_power"), ("toughness", "sacrificed_cost_toughness"),
                           ("mana value", "sacrificed_cost_mana_value")):
        [spec] = _parse(f"Create X 1/1 white Spirit creature tokens, where X is the sacrificed creature's {what}.")
        assert spec.type == "bind"
        assert spec.params["amount"] == {"kind": "count_selector", "selector": selector}
    [spec] = _parse("~ deals damage equal to the sacrificed creature's power to any target.")
    assert spec.params["amount"]["selector"] == "sacrificed_cost_power"
    assert spec.params["effects"][0]["params"]["amount"] == "$n"


def test_fling_deals_damage_equal_to_the_sacrificed_creatures_power():
    fling_text = ("As an additional cost to cast this spell, sacrifice a creature.\n"
                  "~ deals damage equal to the sacrificed creature's power to any target.")
    assert parse_oracle(_card("Fling", "Instant", fling_text, converted_mana_cost=2)).modeled
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    victim = _put(eng, _card("Brute", "Creature — Ogre", power=5, toughness=4))
    spell = GameObject(_card("Fling", "Instant", fling_text, converted_mana_cost=0), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    eng.state.player_by_id("p1").add_to_zone(spell, Zone.HAND)
    eng.cast_spell(eng.state.player_by_id("p1"), spell, targets=[p2], sacrifice_choice=victim.instance_id)
    eng.resolve_until_stable()
    assert victim not in eng.state.battlefield
    assert p2.life == 15


def test_an_activated_sacrifice_scales_a_token_count_by_toughness():
    text = ("{B}, {T}, Sacrifice another creature: Create X 2/2 black Zombie creature tokens, "
            "where X is the sacrificed creature's toughness.")
    assert parse_oracle(_card("Gisa Test", "Creature — Human Wizard", text)).modeled
    eng = _engine()
    gisa = _put(eng, _card("Gisa Test", "Creature — Human Wizard", text))
    victim = _put(eng, _card("Wall", "Creature — Wall", power=0, toughness=4))
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"B": 1})
    eng.activate_ability(p1, gisa, 0, sacrifice_choice=victim.instance_id)
    eng.resolve_until_stable()
    zombies = [o for o in eng.state.battlefield if o.card.name == "Zombie"]
    assert len(zombies) == 4


def test_an_effects_own_sacrifice_also_stamps_the_victim():
    text = ("Whenever ~ attacks, you may sacrifice another creature. When you do, "
            "~ deals damage equal to the sacrificed creature's power to any target.")
    card = _card("Flinger Test", "Creature — Giant", text)
    # "when you do" after an optional effect sacrifice is its own reflexive family; what matters for this axis
    # is that the effect-driven sacrifice records the victim exactly like a cost does
    eng = _engine()
    flinger = _put(eng, card)
    victim = _put(eng, _card("Brute", "Creature — Ogre", power=6, toughness=3))
    eng.rules._request_choose_objects(
        eng.state.player_by_id("p1"), [victim], "sacrifice", count=1, source=flinger)
    eng.resolve_pending_choice(victim.instance_id) if eng.state.pending_choice else None
    assert flinger.sacrificed_cost_power == 6
    assert flinger.sacrificed_cost_toughness == 3
    assert flinger.sacrificed_cost_mana_value == 2
