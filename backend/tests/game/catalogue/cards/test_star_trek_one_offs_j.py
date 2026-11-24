"""Georgiou's life-only exemption and The Immortal Sun's loyalty-only lock."""
import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import advance_to, cast, game, stock_library, vanilla


def _card(name):
    if name == "Georgiou, Terran Emperor":
        return Card(id="georgiou", name=name, type_line="Legendary Creature — Human Rogue Noble",
                    is_creature=True, is_legendary=True, power=4, toughness=6,
                    mana_cost_string="{4}{B}{B}", converted_mana_cost=6,
                    oracle_text="You don't lose the game for having 0 or less life.\n"
                    "At the beginning of your end step, you lose 3 life and draw a card. Then if your life total is 0 or less, create ten 1/1 red Officer creature tokens.")
    assert name == "The Immortal Sun"
    return Card(id="sun", name=name, type_line="Legendary Artifact", is_legendary=True,
                mana_cost_string="{6}", converted_mana_cost=6,
                oracle_text="Players can't activate planeswalkers' loyalty abilities.\n"
                "At the beginning of your draw step, draw an additional card.\n"
                "Spells you cast cost {1} less to cast.\nCreatures you control get +1/+1.")


def _put(engine, card, zone=Zone.BATTLEFIELD, player="p1"):
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        engine.state.add_to_battlefield(obj)
        engine.recompute_continuous_effects()
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


@pytest.mark.parametrize("name", ["Georgiou, Terran Emperor", "The Immortal Sun"])
def test_specs_are_fresh_valid_and_bind(name):
    first, second = specs_for(_card(name)), specs_for(_card(name))
    assert first and first[0] is not second[0] and first[0].effects[0] is not second[0].effects[0]
    for spec in first:
        spec.validate()
    engine, _, _ = game()
    obj = _put(engine, _card(name))
    assert obj.static_effects and obj.triggered_abilities


@pytest.mark.parametrize("life,officers", [(4, 0), (3, 10), (2, 10)])
def test_georgiou_actual_cast_and_end_step_loses_draws_then_checks_life(life, officers):
    engine, p1, _ = game(via_steps=True)
    obj = _put(engine, _card("Georgiou, Terran Emperor"), Zone.HAND)
    cast(engine, p1, obj)
    p1.life = life
    hand = len(p1.hand)
    advance_to(engine, "end")
    engine.resolve_until_stable()
    assert p1.life == life - 3 and not p1.has_lost and len(p1.hand) == hand + 1
    tokens = [o for o in engine.state.battlefield if o.is_token]
    assert len(tokens) == officers
    assert all((o.power, o.toughness, o.colors) == (1, 1, {"R"}) and o.has_subtype("Officer") for o in tokens)


@pytest.mark.parametrize("clone", [False, True])
def test_georgiou_prevents_life_loss_at_zero_and_negative_totals_but_not_opponent_loss(clone):
    engine, p1, p2 = game()
    _put(engine, _card("Georgiou, Terran Emperor"))
    if clone:
        engine = GameEngine(engine.state.clone())
        p1, p2 = engine.state.players
    for life in (0, -5):
        p1.life = life
        engine.rules.check_state_based_actions()
        assert not p1.has_lost and not engine.state.game_over
    assert continuous.player_cant_lose(engine.state, p1, "life")
    assert not continuous.player_cant_lose(engine.state, p1)
    p2.life = 0
    engine.rules.check_state_based_actions()
    assert p2.has_lost and not p1.has_lost


@pytest.mark.parametrize("reason", ["poison", "draw_from_empty", "commander_damage", "effect", "conceded"])
@pytest.mark.parametrize("life", [20, -2])
def test_georgiou_does_not_prevent_other_losses_even_when_life_is_also_nonpositive(reason, life):
    engine, p1, p2 = game()
    _put(engine, _card("Georgiou, Terran Emperor"))
    p1.life = life
    if reason == "poison":
        engine.rules.add_player_counters(p1, 10)
    elif reason == "draw_from_empty":
        engine.rules.draw(p1, 1)
    elif reason == "commander_damage":
        p1.commander_damage["Opposing Commander"] = {"amount": 21}
    elif reason == "conceded":
        engine.rules.concede(p1)
    else:
        doom = _put(engine, Card(id="doom", name="Doom", type_line="Instant", is_instant=True))
        engine.rules._apply_effect_specs([{"type": "lose_game", "params": {}}], doom)
    engine.rules.check_state_based_actions()
    assert p1.has_lost
    assert p1.loss_reason == reason


@pytest.mark.parametrize("mode", ["destroy", "phase_out", "lose_abilities"])
def test_georgiou_exemption_stops_when_source_leaves_or_loses_abilities(mode):
    engine, p1, p2 = game()
    obj = _put(engine, _card("Georgiou, Terran Emperor"))
    p1.life = -1
    if mode == "destroy":
        engine.rules.destroy(obj)
    elif mode == "phase_out":
        obj.phased_out = True
    else:
        _put(engine, Card(id="humility", name="Humility", type_line="Enchantment",
                          oracle_text="All creatures lose all abilities and have base power and toughness 1/1."))
    engine.rules.check_state_based_actions()
    assert p1.has_lost and p1.loss_reason == "life"


def test_blanket_cannot_lose_still_protects_every_state_based_loss():
    engine, p1, p2 = game()
    herald = _put(engine, Card(id="herald", name="Herald of Eternal Dawn", type_line="Creature — Angel",
                              is_creature=True, power=6, toughness=6,
                              oracle_text="Flying\nYou can't lose the game and your opponents can't win the game."))
    p1.life = -1
    p1.poison = 10
    p1.attempted_draw_from_empty = True
    engine.rules.check_state_based_actions()
    assert not p1.has_lost and continuous.player_cant_lose(engine.state, p1)
    engine.rules.destroy(herald)
    engine.rules.check_state_based_actions()
    assert p1.has_lost


def _walker(engine, player="p1", type_line="Planeswalker — Test"):
    return _put(engine, Card(id="walker", name="Walker", type_line=type_line,
                loyalty=3 if "Planeswalker" in type_line else None,
                oracle_text="+1: You gain 1 life.\n{0}: You gain 2 life."), player=player)


@pytest.mark.parametrize("player_id", ["p1", "p2"])
def test_sun_blocks_only_planeswalker_loyalty_abilities_for_every_player(player_id):
    engine, p1, p2 = game()
    _put(engine, _card("The Immortal Sun"))
    walker = _walker(engine, player_id)
    engine.state.active_player_index = 0 if player_id == "p1" else 1
    player = engine.state.player_by_id(player_id)
    loyalty, ordinary = walker.activated_abilities
    assert not engine.can_activate(player, walker, loyalty)
    assert engine.can_activate(player, walker, ordinary)
    before = walker.counters["loyalty"]
    with pytest.raises(ValueError):
        engine.activate_ability(player, walker, ability_index=0)
    assert walker.counters["loyalty"] == before
    offers = [a for a in engine.legal_actions(player) if a.get("instance_id") == walker.instance_id
              and a["type"] == "activate_ability"]
    assert all(a["ability_index"] != 0 for a in offers)
    assert any(a["ability_index"] == 1 for a in offers)
    life = player.life
    engine.activate_ability(player, walker, ability_index=1)
    engine.resolve_until_stable()
    assert player.life == life + 2


def test_sun_does_not_block_loyalty_abilities_of_nonplaneswalker_permanents():
    engine, p1, p2 = game()
    _put(engine, _card("The Immortal Sun"))
    artifact = _walker(engine, type_line="Artifact")
    engine.activate_ability(p1, artifact, ability_index=0)
    engine.resolve_until_stable()
    assert artifact.counters["loyalty"] == 1 and p1.life == 21


def test_sun_uses_current_planeswalker_type_when_luxior_is_equipped():
    engine, p1, p2 = game()
    _put(engine, _card("The Immortal Sun"))
    walker = _walker(engine)
    luxior = _put(engine, Card(id="luxior", name="Luxior, Giada's Gift", type_line="Legendary Artifact — Equipment",
        keywords=["Equip"], oracle_text="Equipped creature gets +1/+1 for each counter on it.\n"
        "Equipped permanent isn't a planeswalker and is a creature in addition to its other types. (Loyalty abilities can still be activated.)\n"
        "Equip planeswalker {1}\nEquip {3}"))
    p1.mana_pool.add("C", 1)
    engine.activate_ability(p1, luxior, ability_index=0, targets=[walker])
    engine.resolve_until_stable()
    assert walker.is_creature and not walker.is_planeswalker
    engine.activate_ability(p1, walker, ability_index=0)
    engine.resolve_until_stable()
    assert p1.life == 21 and walker.counters["loyalty"] == 4


def test_sun_leaving_restores_activation_and_does_not_counter_already_activated_ability():
    engine, p1, p2 = game()
    walker = _walker(engine)
    engine.activate_ability(p1, walker, ability_index=0)
    sun = _put(engine, _card("The Immortal Sun"))
    engine.resolve_until_stable()
    assert p1.life == 21
    walker.activated_loyalty_this_turn = False
    assert not engine.can_activate(p1, walker, walker.activated_abilities[0])
    engine.rules.destroy(sun)
    engine.resolve_until_stable()
    assert engine.can_activate(p1, walker, walker.activated_abilities[0])


def test_sun_anthem_and_cost_reduction_are_controller_only():
    engine, p1, p2 = game()
    mine, theirs = vanilla(engine, "p1"), vanilla(engine, "p2")
    sun = _put(engine, _card("The Immortal Sun"), Zone.HAND)
    cast(engine, p1, sun)
    assert (mine.power, mine.toughness) == (3, 3) and (theirs.power, theirs.toughness) == (2, 2)
    for player_id, expected in [("p1", 2), ("p2", 3)]:
        spell = _put(engine, Card(id=player_id, name=player_id, type_line="Instant", is_instant=True,
                                  mana_cost_string="{3}", converted_mana_cost=3), Zone.HAND, player_id)
        cost = engine.effective_cast_cost(engine.state.player_by_id(player_id), spell)
        assert cost.converted_mana_cost == expected


def test_sun_draws_extra_only_in_its_controllers_draw_step():
    engine, p1, p2 = game(via_steps=True)
    _put(engine, _card("The Immortal Sun"))
    for player in (p1, p2):
        stock_library(engine, player.id, 6)
    before = len(p2.hand)
    advance_to(engine, "draw")
    engine.resolve_until_stable()
    assert engine.state.active_player.id == "p2" and len(p2.hand) == before + 1
    engine.advance_step()
    before = len(p1.hand)
    advance_to(engine, "draw")
    engine.resolve_until_stable()
    assert engine.state.active_player.id == "p1" and len(p1.hand) == before + 2
