"""Real gameplay for the Keen Engineering (Foundations Commander) catalogue entries."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game():
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * 8) for i in range(2)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _card(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None, **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "", **kw)
    obj = GameObject(card, owner_id=player, zone=Zone.BATTLEFIELD)
    obj.controller_id = player
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _upkeep(engine):
    for _ in range(20):
        engine.advance_step()
        if engine.state.current_step == "upkeep":
            return
    raise AssertionError("upkeep not reached")


def test_aetherize_returns_every_attacking_creature_to_its_owners_hand():
    engine = _game()
    p1, p2 = engine.state.players
    mine = _filler(engine, "Mine", power=2, toughness=2)
    mine.summoning_sick = False
    idle = _filler(engine, "Idle", power=2, toughness=2)
    stolen = _filler(engine, "Stolen", player="p1", power=2, toughness=2)
    stolen.owner_id = "p2"
    stolen.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [mine, stolen])
    spell = _card(engine, "Aetherize", player="p2", zone=Zone.HAND)
    p2.mana_pool.add_many({"U": 1, "C": 3})
    engine.cast_spell(p2, spell, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert mine in p1.hand and stolen in p2.hand  # back to the *owner's* hand
    assert idle in engine.state.battlefield


def test_mazemind_tome_exiles_itself_and_gains_four_life_at_four_page_counters():
    engine = _game()
    p1, _ = engine.state.players
    tome = _card(engine, "Mazemind Tome")
    for _ in range(3):
        engine.rules.add_counters(tome, 1, "page")
        engine.resolve_until_stable()
    assert tome in engine.state.battlefield and p1.life == 20
    engine.rules.add_counters(tome, 1, "page")
    engine.resolve_until_stable()
    assert tome in p1.exile and p1.life == 24


def test_scrawling_crawler_each_player_draws_and_the_opponent_loses_life_for_it():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Scrawling Crawler")
    h1, h2 = len(p1.hand), len(p2.hand)
    life2 = p2.life
    _upkeep(engine)
    engine.resolve_until_stable()
    assert len(p1.hand) - h1 >= 1 and len(p2.hand) - h2 >= 1
    assert p2.life == life2 - (len(p2.hand) - h2) and p1.life == 20
    assert p2.life < life2


@pytest.mark.parametrize("opponent_value,draws", [(3, True), (5, True), (6, False)])
def test_padeem_draws_only_with_the_greatest_artifact_mana_value(opponent_value, draws):
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Padeem, Consul of Innovation")
    _filler(engine, "My Rock", "Artifact", mv=5)
    _filler(engine, "Their Rock", "Artifact", "p2", mv=opponent_value)
    before = len(p1.hand)
    _upkeep(engine)
    engine.resolve_until_stable()
    drawn = len(p1.hand) - before
    # the turn's own draw step is not reached yet: only the Padeem draw can have happened
    assert (drawn == 1) == draws


def test_padeem_gives_your_artifacts_hexproof():
    engine = _game()
    _card(engine, "Padeem, Consul of Innovation")
    rock = _filler(engine, "My Rock", "Artifact", mv=2)
    engine.recompute_continuous_effects()
    assert combat.has(rock, "hexproof")


def test_forsaken_monument_adds_an_extra_colorless_when_a_permanent_taps_for_c():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Forsaken Monument")
    sol = _card(engine, "Sol Ring")
    engine.tap_for_mana(p1, sol)
    assert p1.mana_pool.total() == 3  # {C}{C} from the ring plus one additional {C}


def test_forsaken_monument_ignores_coloured_mana_and_pumps_colorless_creatures():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Forsaken Monument")
    forest = _card(engine, "Forest")
    engine.tap_for_mana(p1, forest)
    assert p1.mana_pool.total() == 1
    golem = _filler(engine, "Golem", "Artifact Creature — Golem", power=2, toughness=2)
    green = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2, color_identity={"G"})
    engine.recompute_continuous_effects()
    assert (golem.power, golem.toughness) == (4, 4) and (green.power, green.toughness) == (2, 2)


def test_shimmer_myr_lets_artifact_spells_be_cast_at_instant_speed_only():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Shimmer Myr")
    engine.state.current_step = "declare_attackers"  # not a main phase
    rock = GameObject(Card(id="R", name="Rock", type_line="Artifact", converted_mana_cost=1,
                           mana_cost_string="{1}"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(rock)
    p1.add_to_zone(rock, Zone.HAND)
    sorcery = GameObject(Card(id="S", name="Sorc", type_line="Sorcery", is_sorcery=True, converted_mana_cost=1,
                              mana_cost_string="{1}"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(sorcery)
    p1.add_to_zone(sorcery, Zone.HAND)
    p1.mana_pool.add("C", 2)
    assert engine.can_cast(p1, rock)
    assert not engine.can_cast(p1, sorcery)


def test_all_is_dust_sacrifices_every_colored_permanent_of_every_player():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    green_a = _filler(engine, "Green A", "Creature", power=1, toughness=1, color_identity={"G"})
    green_b = _filler(engine, "Green B", "Creature", power=1, toughness=1, color_identity={"G"})
    red = _filler(engine, "Their Red", "Creature", "p2", power=1, toughness=1, color_identity={"R"})
    rock = _filler(engine, "Rock", "Artifact", mv=1)
    land = _filler(engine, "Land", "Land")
    spell = _card(engine, "All Is Dust", zone=Zone.HAND)
    p1.mana_pool.add("C", 7)
    engine.cast_spell(p1, spell, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert not engine.state.pending_choice
    for gone in (green_a, green_b):
        assert gone in p1.graveyard
    assert red in p2.graveyard
    assert rock in engine.state.battlefield and land in engine.state.battlefield


def _untap_step(engine):
    engine._step_untap()


def test_fall_from_favor_taps_the_creature_makes_you_monarch_and_locks_it_unless_its_controller_is():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    victim = _filler(engine, "Victim", "Creature", "p2", power=2, toughness=2)
    aura = _card(engine, "Fall from Favor", zone=Zone.HAND)
    p1.mana_pool.add_many({"U": 1, "C": 2})
    engine.cast_spell(p1, aura, targets=[victim], target_groups=None)
    engine.resolve_until_stable()
    assert aura.attached_to == victim.instance_id and victim.tapped
    assert engine.state.monarch_id == "p1"
    engine.state.active_player_index = 1  # p2's untap step
    engine._step_untap()
    assert victim.tapped  # not the monarch: stays tapped
    engine.state.monarch_id = "p2"
    engine._step_untap()
    assert not victim.tapped  # the monarch's creature untaps again


def test_steel_hellkite_x_destroys_only_matching_value_permanents_of_damaged_players_once_a_turn():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main2"
    kite = _card(engine, "Steel Hellkite")
    engine.rules.deal_damage(p2, 6, source=kite, combat=True)
    hit = _filler(engine, "Three Drop", "Artifact", "p2", mv=3)
    miss_value = _filler(engine, "Four Drop", "Artifact", "p2", mv=4)
    miss_owner = _filler(engine, "My Three Drop", "Artifact", "p1", mv=3)
    land = _filler(engine, "Their Land", "Land", "p2")
    ability = next(a for a in kite.activated_abilities if a.once_per_turn)
    idx = kite.activated_abilities.index(ability)
    p1.mana_pool.add("C", 6)
    engine.activate_ability(p1, kite, ability_index=idx, x=3)
    engine.resolve_until_stable()
    assert hit in p2.graveyard
    assert miss_value in engine.state.battlefield and land in engine.state.battlefield
    assert miss_owner in engine.state.battlefield  # its controller was never dealt damage
    assert not engine.can_activate(p1, kite, ability, 4)  # only once each turn


def test_graaz_turns_other_creatures_into_5_3_juggernauts_that_must_attack_and_dodge_walls():
    from mtg_analyzer.game import continuous

    engine = _game()
    p1, p2 = engine.state.players
    graaz = _card(engine, "Graaz, Unstoppable Juggernaut")
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    theirs = _filler(engine, "Their Bear", "Creature — Bear", "p2", power=2, toughness=2)
    wall = _filler(engine, "Wall", "Creature — Wall", "p2", power=0, toughness=4)
    engine.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (5, 3) and continuous.has_subtype(bear, "Juggernaut")
    assert (theirs.power, theirs.toughness) == (2, 2)  # only *your* other creatures
    assert combat.has(bear, "attacks_if_able") and combat.has(graaz, "attacks_if_able")
    assert not combat.has(theirs, "attacks_if_able")
    restrictions = combat.combat_restrictions(bear, "cant_be_blocked_by")
    assert restrictions and not combat.matches_object_filter(theirs, restrictions[0].get("filter"))
    assert combat.matches_object_filter(wall, restrictions[0].get("filter"))


def test_graaz_juggernauts_cannot_be_blocked_by_walls_but_by_other_creatures():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Graaz, Unstoppable Juggernaut")
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    bear.summoning_sick = False
    wall = _filler(engine, "Wall", "Creature — Wall", "p2", power=0, toughness=4)
    other = _filler(engine, "Other", "Creature — Bear", "p2", power=2, toughness=2)
    engine.recompute_continuous_effects()
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [bear])
    assert not engine.can_block(p2, wall, bear)
    assert engine.can_block(p2, other, bear)


def test_myr_battlesphere_enters_with_four_myr_and_taps_x_to_pump_and_hit_the_defender():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    sphere = _card(engine, "Myr Battlesphere", zone=Zone.HAND)
    p1.mana_pool.add("C", 7)
    engine.cast_spell(p1, sphere, targets=None, target_groups=None)
    engine.resolve_until_stable()
    myr = [o for o in engine.state.battlefield if o.card.name == "Myr"]
    assert len(myr) == 4
    sphere.summoning_sick = False
    base = sphere.power
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [sphere])
    engine.resolve_until_stable()
    for _ in range(6):  # any number of untapped Myr: pick three
        choice = engine.state.pending_choice
        if not choice:
            break
        picked = len([m for m in myr if m.tapped])
        options = [o for o in choice["options"] if str(o.get("id", "")).isdigit()]
        engine.resolve_pending_choice(str(options[0]["id"]) if picked < 3 else "decline")
        engine.resolve_until_stable()
    tapped = [m for m in myr if m.tapped]
    assert len(tapped) == 3
    assert sphere.power == base + 3 and p2.life == 17


def test_myr_battlesphere_declining_to_tap_does_nothing():
    engine = _game()
    p1, p2 = engine.state.players
    sphere = _card(engine, "Myr Battlesphere")
    sphere.summoning_sick = False
    _filler(engine, "Myr", "Artifact Creature — Myr", power=1, toughness=1)
    base = sphere.power
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [sphere])
    engine.resolve_until_stable()
    if engine.state.pending_choice:
        engine.resolve_pending_choice("decline")
        engine.resolve_until_stable()
    assert sphere.power == base and p2.life == 20


def _three_player_game():
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * 8) for i in range(3)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _signpost_cast_during_attack(engine, step="declare_attackers"):
    p1, p2, p3 = engine.state.players
    attacker = _filler(engine, "Attacker", power=2, toughness=2)
    attacker.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": attacker, "defender": {"kind": "player", "id": "p2", "label": "1"}}])
    engine.state.current_step = step
    signpost = _card(engine, "Misleading Signpost", player="p3", zone=Zone.HAND)
    p3.mana_pool.add_many({"U": 1, "C": 2})
    engine.cast_spell(p3, signpost, targets=None, target_groups=None)
    engine.resolve_until_stable()
    pending = engine.state.pending_choice
    if pending and pending["kind"] == "trigger_target":  # the ETB's own "target attacking creature"
        engine.resolve_pending_choice(str(attacker.instance_id))
        engine.resolve_until_stable()
    return attacker


def test_misleading_signpost_lets_its_controller_redirect_an_attacker_to_another_defender():
    engine = _three_player_game()
    attacker = _signpost_cast_during_attack(engine)
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "reselect_attack" and choice["player_id"] == "p3"
    assert {o["id"] for o in choice["options"]} == {"player:p2", "player:p3", "decline"}
    engine.resolve_pending_choice("player:p3")
    engine.resolve_until_stable()
    assert attacker.combat_defender["id"] == "p3"


def test_misleading_signpost_may_keep_the_current_defender():
    engine = _three_player_game()
    attacker = _signpost_cast_during_attack(engine)
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert attacker.combat_defender["id"] == "p2"


def test_misleading_signpost_does_nothing_outside_the_declare_attackers_step():
    engine = _three_player_game()
    attacker = _signpost_cast_during_attack(engine, step="declare_blockers")
    assert not engine.state.pending_choice
    assert attacker.combat_defender["id"] == "p2"


def test_duplicant_imprints_a_nontoken_creature_and_becomes_its_size_and_types():
    from mtg_analyzer.game import continuous

    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    victim = _filler(engine, "Big Bear", "Creature — Bear Warrior", "p2", power=5, toughness=6)
    token = _filler(engine, "Their Token", "Creature — Goblin", "p2", power=1, toughness=1)
    token.is_token = True
    dup = _card(engine, "Duplicant", zone=Zone.HAND)
    p1.mana_pool.add("C", 6)
    engine.cast_spell(p1, dup, targets=None, target_groups=None)
    engine.resolve_until_stable()
    pending = engine.state.pending_choice
    assert pending  # the optional ETB target
    assert str(token.instance_id) not in {str(o.get("id")) for o in pending["options"]}  # nontoken only
    engine.resolve_pending_choice(str(victim.instance_id))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert victim in p2.exile
    assert (dup.power, dup.toughness) == (5, 6)
    assert continuous.has_subtype(dup, "Bear") and continuous.has_subtype(dup, "Warrior")
    assert continuous.has_subtype(dup, "Shapeshifter")


def test_duplicant_reverts_when_the_imprinted_card_leaves_exile_or_is_not_a_creature():
    engine = _game()
    p1, p2 = engine.state.players
    dup = _card(engine, "Duplicant")
    assert (dup.power, dup.toughness) == (2, 4)  # printed, nothing imprinted
    victim = _filler(engine, "Big Bear", "Creature — Bear", "p2", power=5, toughness=6)
    engine.rules.exile(victim)
    dup.linked_exile_id = victim.instance_id
    engine.recompute_continuous_effects()
    assert (dup.power, dup.toughness) == (5, 6)
    p2.remove_from_zone(victim, Zone.EXILE)
    p2.add_to_zone(victim, Zone.GRAVEYARD)  # it left exile
    engine.recompute_continuous_effects()
    assert (dup.power, dup.toughness) == (2, 4)
