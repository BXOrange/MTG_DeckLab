"""Real gameplay for the Eternal Might (Aetherdrift Commander) catalogue entries."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * 8) for i in range(players)],
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


def _filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None,
            zone=Zone.BATTLEFIELD, **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "", **kw)
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _enter(engine, obj, from_cast=False):
    """Announce ``obj`` entering (the fillers are placed without the ENTERS_BATTLEFIELD event)."""
    obj.was_cast = from_cast
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object_types=sorted(obj.type_words),
                                      object=obj.name))
    engine.resolve_until_stable()


def _cast(engine, card, pool, **kw):
    p1 = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many(pool)
    engine.cast_spell(p1, card, targets=None, target_groups=None, **kw)
    engine.resolve_until_stable()


def test_accursed_duneyard_regenerates_only_the_listed_creature_types():
    engine = _game()
    p1, _ = engine.state.players
    duneyard = _card(engine, "Accursed Duneyard")
    zombie = _filler(engine, "Zed", "Creature — Zombie", power=2, toughness=2)
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    from mtg_analyzer.game.targeting import legal_targets, TargetSpec

    spec = duneyard.activated_abilities[0].effects[0].target_spec
    offered = {t.get("instance_id") for t in legal_targets(engine.state, "p1", spec, source=duneyard)}
    assert zombie.instance_id in offered and bear.instance_id not in offered


def test_unholy_grotto_puts_a_zombie_card_from_the_graveyard_on_top_of_the_library():
    engine = _game()
    p1, _ = engine.state.players
    grotto = _card(engine, "Unholy Grotto")
    zombie = _filler(engine, "Zed", "Creature — Zombie", power=2, toughness=2, zone=Zone.GRAVEYARD)
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2, zone=Zone.GRAVEYARD)
    from mtg_analyzer.game.targeting import legal_targets

    spec = grotto.activated_abilities[0].effects[0].target_spec
    offered = {t.get("instance_id") for t in legal_targets(engine.state, "p1", spec, source=grotto)}
    assert zombie.instance_id in offered and bear.instance_id not in offered


def test_lord_of_the_accursed_gives_every_zombie_menace_including_opponents():
    engine = _game()
    lord = _card(engine, "Lord of the Accursed")
    lord.summoning_sick = False
    mine = _filler(engine, "Mine", "Creature — Zombie", power=2, toughness=2)
    theirs = _filler(engine, "Theirs", "Creature — Zombie", player="p2", power=2, toughness=2)
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    continuous.recompute(engine.state)
    assert (mine.power, mine.toughness) == (3, 3) and (theirs.power, theirs.toughness) == (2, 2)  # "other Zombies you control"
    engine.state.current_step = "main1"
    engine.state.player_by_id("p1").mana_pool.add_many({"B": 1, "C": 1})
    engine.activate_ability(engine.state.player_by_id("p1"), lord, 0)
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert combat.has(mine, "menace") and combat.has(theirs, "menace") and combat.has(lord, "menace")
    assert not combat.has(bear, "menace")


def test_commence_the_endgame_amasses_zombies_by_the_hand_size_after_drawing():
    engine = _game()
    p1, _ = engine.state.players
    spell = _card(engine, "Commence the Endgame", zone=Zone.HAND)
    for i in range(2):
        _filler(engine, f"H{i}", "Sorcery", zone=Zone.HAND)
    p1.mana_pool.add_many({"U": 2, "C": 4})
    engine.state.current_step = "main1"
    engine.cast_spell(p1, spell, targets=None, target_groups=None)
    engine.resolve_until_stable()
    armies = [o for o in engine.state.battlefield if "Army" in o.card.type_line]
    assert len(armies) == 1 and armies[0].plus_one_counters == 4  # 2 in hand + 2 drawn (the spell itself has left)


def test_champion_of_wits_draws_its_power_then_discards_two_only_if_you_do():
    engine = _game()
    p1, _ = engine.state.players
    champion = _card(engine, "Champion of Wits")
    _enter(engine, champion)
    choice = engine.state.pending_choice
    assert choice is not None, "the 'you may' is offered"
    hand = len(p1.hand)
    engine.rules.resolve_choice("do")
    engine.resolve_until_stable()
    while engine.state.pending_choice:  # pick the discards
        engine.rules.resolve_choice(str(engine.state.pending_choice["options"][0]["id"]))
        engine.resolve_until_stable()
    assert len(p1.hand) == hand + champion.power - 2


def test_dread_summons_makes_a_tapped_zombie_per_creature_card_milled_by_everyone():
    engine = _game()
    p1, p2 = engine.state.players
    for pid, cards in (("p1", [("A", "Creature — Bear"), ("B", "Sorcery")]), ("p2", [("C", "Creature — Elf"), ("D", "Creature — Elf")])):
        player = engine.state.player_by_id(pid)
        player.library.clear()
        for name, tl in cards:
            _filler(engine, f"{pid}{name}", tl, player=pid, power=1 if "Creature" in tl else None,
                    toughness=1 if "Creature" in tl else None, zone=Zone.LIBRARY)
    spell = _card(engine, "Dread Summons", zone=Zone.HAND)
    p1.mana_pool.add_many({"B": 2, "C": 2})
    engine.state.current_step = "main1"
    engine.cast_spell(p1, spell, x=2, targets=None, target_groups=None)
    engine.resolve_until_stable()
    zombies = [o for o in engine.state.battlefield if o.name == "Zombie" and o.controller_id == "p1"]
    assert len(zombies) == 3 and all(z.tapped for z in zombies)  # 1 of mine + 2 of theirs


def test_corpse_augur_draws_and_loses_life_equal_to_creature_cards_in_the_chosen_graveyard():
    engine = _game()
    p1, p2 = engine.state.players
    augur = _card(engine, "Corpse Augur")
    for i in range(3):
        _filler(engine, f"Dead{i}", "Creature — Elf", player="p2", power=1, toughness=1, zone=Zone.GRAVEYARD)
    _filler(engine, "Spell", "Sorcery", player="p2", zone=Zone.GRAVEYARD)
    hand, life = len(p1.hand), p1.life
    engine.rules.destroy(augur)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice is not None, "the target player is chosen"
    engine.rules.resolve_choice(str(next(o["id"] for o in choice["options"] if "p2" in str(o))))
    engine.resolve_until_stable()
    assert len(p1.hand) == hand + 3 and p1.life == life - 3


def test_prophet_of_the_scarab_draws_the_greater_of_zombies_controlled_and_zombie_cards_in_the_graveyard():
    for graveyard_zombies, battlefield_zombies, drawn in ((4, 0, 4), (1, 2, 3)):  # the Prophet itself is a Zombie
        engine = _game()
        p1, _ = engine.state.players
        for i in range(graveyard_zombies):
            _filler(engine, f"G{i}", "Creature — Zombie", power=1, toughness=1, zone=Zone.GRAVEYARD)
        for i in range(battlefield_zombies):
            _filler(engine, f"B{i}", "Creature — Zombie", power=1, toughness=1)
        prophet = _card(engine, "Prophet of the Scarab")
        hand = len(p1.hand)
        _enter(engine, prophet)
        assert len(p1.hand) == hand + max(graveyard_zombies, battlefield_zombies + 1), (graveyard_zombies, drawn)


def test_forgotten_creation_replaces_the_whole_hand_at_upkeep():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Forgotten Creation")
    for i in range(3):
        _filler(engine, f"H{i}", "Sorcery", zone=Zone.HAND)
    engine.state.active_player_index = 0
    engine.state.current_step = "upkeep"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id=p1.id, controller_id=p1.id))
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "composite_optional"  # "you may"
    engine.rules.resolve_choice("yes")
    engine.resolve_until_stable()
    assert len(p1.hand) == 3 and not any(c.name.startswith("H") for c in p1.hand)
    assert sum(1 for c in p1.graveyard if c.name.startswith("H")) == 3


def test_gempalm_polluter_cycling_drains_a_player_by_the_zombies_on_the_battlefield():
    engine = _game()
    p1, p2 = engine.state.players
    polluter = _card(engine, "Gempalm Polluter", zone=Zone.GRAVEYARD)  # cycling's discard put it here
    for i in range(3):
        _filler(engine, f"Z{i}", "Creature — Zombie", player="p2" if i else "p1", power=1, toughness=1)
    engine.state.fire_event(GameEvent(EventType.CYCLED, instance_id=polluter.instance_id, controller_id="p1"))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice is not None
    engine.rules.resolve_choice(str(next(o["id"] for o in choice["options"] if "p2" in str(o))))
    engine.resolve_until_stable()
    assert p2.life == 17


def test_rot_hulk_returns_up_to_one_zombie_per_opponent():
    engine = _game(3)  # two opponents
    p1, _, _ = engine.state.players
    zombies = [_filler(engine, f"Z{i}", "Creature — Zombie", power=1, toughness=1, zone=Zone.GRAVEYARD) for i in range(3)]
    hulk = _card(engine, "Rot Hulk")
    _enter(engine, hulk)
    for _ in range(3):
        choice = engine.state.pending_choice
        if not choice:
            break
        engine.rules.resolve_choice(str(next(o["id"] for o in choice["options"] if o.get("instance_id"))))
        engine.resolve_until_stable()
    assert sum(1 for z in zombies if z.zone == Zone.BATTLEFIELD) == 2


def test_wizened_mentor_makes_a_zombie_on_the_first_opponent_activation_each_turn_only():
    engine = _game()
    _card(engine, "Wizened Mentor")
    tokens = lambda: [o for o in engine.state.battlefield if o.name == "Zombie" and o.is_token]

    def activate(controller):
        engine.state.fire_event(GameEvent(EventType.ACTIVATED_ABILITY, controller_id=controller, object_types=["creature"]))
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()

    activate("p1")
    assert not tokens()  # only opponents' activations
    activate("p2")
    activate("p2")
    assert len(tokens()) == 1


def test_priest_of_the_crossing_counts_only_creatures_that_died_under_your_control():
    engine = _game()
    p1, _ = engine.state.players
    priest = _card(engine, "Priest of the Crossing")
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=3)
    mine = _filler(engine, "Mine", "Creature — Elf", power=1, toughness=1)
    theirs = _filler(engine, "Theirs", "Creature — Elf", player="p2", power=1, toughness=1)
    engine.rules.destroy(mine)
    engine.rules.destroy(theirs)
    engine.resolve_until_stable()
    engine.state.current_step = "end"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p2", controller_id="p2"))  # each end step
    engine.resolve_until_stable()
    assert priest.plus_one_counters == 1 and bear.plus_one_counters == 1


def test_on_wings_of_gold_buffs_zombies_and_tokens_once_each():
    engine = _game()
    _card(engine, "On Wings of Gold", zone=Zone.BATTLEFIELD)
    zombie = _filler(engine, "Zed", "Creature — Zombie", power=2, toughness=2)
    token = _filler(engine, "Pest", "Token Creature — Pest", power=1, toughness=1)
    token.is_token = True
    token_zombie = _filler(engine, "Zed Token", "Token Creature — Zombie", power=2, toughness=2)
    token_zombie.is_token = True
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    theirs = _filler(engine, "Theirs", "Creature — Zombie", player="p2", power=2, toughness=2)
    continuous.recompute(engine.state)
    assert (zombie.power, zombie.toughness) == (3, 3) and combat.has(zombie, "flying")
    assert (token.power, token.toughness) == (2, 2) and combat.has(token, "flying")
    assert (token_zombie.power, token_zombie.toughness) == (3, 3)  # once, not twice
    assert (bear.power, bear.toughness) == (2, 2) and not combat.has(bear, "flying")
    assert (theirs.power, theirs.toughness) == (2, 2)


def test_lost_monarch_grants_afflict_and_returns_a_creature_after_a_zombie_connects():
    engine = _game()
    p1, _ = engine.state.players
    monarch = _card(engine, "Lost Monarch of Ifnir")
    zombie = _filler(engine, "Zed", "Creature — Zombie", power=2, toughness=2)
    continuous.recompute(engine.state)
    assert zombie._granted_parametric_keywords.get("afflict") == 3  # "other Zombies you control have afflict 3"
    assert "afflict" not in monarch._granted_parametric_keywords  # ...and only the others (the Monarch prints its own)
    dead = _filler(engine, "Dead Elf", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    engine.state.active_player_index = 0

    def second_main():
        engine.state.current_step = "main2"
        engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="main2", player_id="p1", controller_id="p1"))
        engine.resolve_until_stable()

    second_main()
    assert dead.zone == Zone.GRAVEYARD and engine.state.pending_choice is None  # nobody was hit by a Zombie
    engine.state.fire_event(GameEvent(EventType.DAMAGE, amount=2, is_player=True, target_id="p2", combat=True,
                                      source_id=zombie.instance_id, source_controller_id="p1"))
    second_main()
    choice = engine.state.pending_choice
    assert choice is not None
    engine.rules.resolve_choice(str(next(o["id"] for o in choice["options"] if o.get("instance_id") == dead.instance_id)))
    engine.resolve_until_stable()
    assert dead.zone == Zone.HAND
    assert len(p1.graveyard) >= 3  # three cards were milled first


def test_gate_to_the_afterlife_needs_six_creature_cards_in_the_graveyard_and_fetches_the_gift():
    engine = _game()
    p1, _ = engine.state.players
    gate = _card(engine, "Gate to the Afterlife")
    gift = _filler(engine, "God-Pharaoh's Gift", "Artifact", zone=Zone.LIBRARY)
    for i in range(5):
        _filler(engine, f"D{i}", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    p1.mana_pool.add_many({"C": 2})
    engine.state.current_step = "main1"
    ability = gate.activated_abilities[0]
    assert not engine.can_activate(p1, gate, ability)
    _filler(engine, "D5", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    assert engine.can_activate(p1, gate, ability)
    engine.activate_ability(p1, gate, 0)
    engine.resolve_until_stable()
    while engine.state.pending_choice:
        choice = engine.state.pending_choice
        engine.rules.resolve_choice(str(next(o["id"] for o in choice["options"] if o.get("instance_id") == gift.instance_id)))
        engine.resolve_until_stable()
    assert gift.zone == Zone.BATTLEFIELD and gate.zone == Zone.GRAVEYARD


def test_vizier_of_many_faces_copies_any_creature_and_an_embalmed_token_is_a_white_zombie():
    engine = _game()
    giant = _filler(engine, "Their Giant", "Creature — Giant", player="p2", power=6, toughness=6)
    vizier = _card(engine, "Vizier of Many Faces", zone=Zone.HAND)
    _cast(engine, vizier, {"U": 2, "C": 2})
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "enter_as_copy"
    engine.rules.resolve_choice(str(giant.instance_id))
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert vizier.name == "Their Giant" and (vizier.power, vizier.toughness) == (6, 6)
    assert not continuous.has_subtype(vizier, "Zombie")  # a hard cast gets no embalm "except"
    # the same replacement on a token (an Embalm token copy of the Vizier)
    token_card = CardDatabase(DB_PATH).get_card("Vizier of Many Faces")
    token = GameObject(token_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    token.controller_id = "p1"
    token.is_token = True
    bind_from_catalogue(token)
    engine.rules._offer_enter_as_copy(token, lambda: engine.state.add_to_battlefield(token))
    engine.rules.resolve_choice(str(giant.instance_id))
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert continuous.has_subtype(token, "Zombie") and continuous.has_subtype(token, "Giant")
    assert token.colors == {"W"} or set(token.colors) == {"W"}
