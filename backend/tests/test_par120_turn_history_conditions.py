"""PAR-120: threshold histories read the player who actually lost life/drew cards."""

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.continuous import count_selector, self_cost_reduction_for
from mtg_analyzer.game.static_conditions import condition_holds
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition


def test_life_loss_thresholds_distinguish_any_player_from_you():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    engine.begin_turn()
    any_player = static_condition("a player lost 4 or more life this turn")
    you = static_condition("you lost 2 or more life this turn")
    assert any_player == {"kind": "life_lost_this_turn", "scope": "any", "min": 4}
    assert you == {"kind": "life_lost_this_turn", "scope": "you", "min": 2}
    engine.rules.lose_life(state.player_by_id("p2"), 4)
    assert condition_holds(any_player, state, controller_id="p1")
    assert not condition_holds(you, state, controller_id="p1")
    engine.rules.lose_life(state.player_by_id("p1"), 2)
    assert condition_holds(you, state, controller_id="p1")


def test_opponent_draw_threshold_reads_each_opponent_separately():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    for pid in ("p1", "p2", "p3"):
        player = state.player_by_id(pid)
        for index in range(6):
            player.library.append(GameObject(
                Card(id=f"{pid}-{index}", name=f"Card {index}", type_line="Land"),
                owner_id=pid, zone=Zone.LIBRARY,
            ))
    engine.begin_turn()
    condition = static_condition("an opponent has drawn four or more cards this turn")
    assert condition == {"kind": "drawn_cards_at_least", "scope": "opponents", "amount": 4}
    engine.rules.draw(state.player_by_id("p1"), 5)
    engine.rules.draw(state.player_by_id("p2"), 2)
    engine.rules.draw(state.player_by_id("p3"), 2)
    assert not condition_holds(condition, state, controller_id="p1")
    engine.rules.draw(state.player_by_id("p3"), 2)
    assert condition_holds(condition, state, controller_id="p1")


def test_gwaihir_cost_reduction_reads_draw_threshold_with_word_number():
    card = Card(id="gwaihir", name="Gwaihir the Windlord",
                type_line="Legendary Creature — Bird Noble", is_creature=True,
                mana_cost_string="{4}{W}",
                oracle_text="This spell costs {2} less to cast as long as you've drawn two or more cards this turn.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    source = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(source)
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    assert self_cost_reduction_for(source, state, caster_id="p1")[0] == 0
    state.fire_event(GameEvent(EventType.DRAW, player_id="p1", count=2))
    assert self_cost_reduction_for(source, state, caster_id="p1")[0] == 2


def test_even_the_score_reduces_blue_pips_only_after_opponent_draws_four():
    card = Card(id="even-score", name="Even the Score", type_line="Instant", is_instant=True,
                mana_cost_string="{X}{U}{U}{U}",
                oracle_text=("This spell costs {U}{U}{U} less to cast if an opponent "
                             "has drawn four or more cards this turn.\n"
                             "Draw X cards."))
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    source = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(source)
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    player = state.player_by_id("p1")
    cost = ManaCost.parse("{X}{U}{U}{U}").with_x(2)
    assert engine._adjust_cost(cost, player, source).render() == "{X}{U}{U}{U}"
    state.fire_event(GameEvent(EventType.DRAW, player_id="p2", count=4))
    assert engine._adjust_cost(cost, player, source).render() == "{X}"
    assert ManaCost.parse("{U/B}{U}{W}").reduce_colored("U", 3).render() == "{U/B}{W}"


def test_kami_of_jealous_thirst_activation_cost_uses_draw_history():
    card = Card(id="kami-thirst", name="Kami of Jealous Thirst",
                type_line="Creature — Spirit", is_creature=True,
                oracle_text=("Deathtouch\n{4}{B}: Each opponent loses 2 life and you gain 2 life. "
                             "This ability costs {4}{B} less to activate if you've drawn three "
                             "or more cards this turn. Activate only once each turn."))
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(source)
    assert len(source.activated_abilities) == 1
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    mana = ManaCost.parse("{4}{B}")
    cost = source.activated_abilities[0].cost
    assert engine._reduced_activation_mana(source, mana, cost).render() == "{4}{B}"
    state.fire_event(GameEvent(EventType.DRAW, player_id="p1", count=3))
    assert engine._reduced_activation_mana(source, mana, cost).render() == ""


def test_knight_of_the_ebon_legion_claims_intervening_if():
    card = Card(id="knight-ebon", name="Knight of the Ebon Legion",
                type_line="Creature — Vampire Knight", is_creature=True,
                oracle_text=("{2}{B}: Knight of the Ebon Legion gets +3/+3 and gains deathtouch until end of turn.\n"
                             "At the beginning of your end step, if a player lost 4 or more life this turn, "
                             "put a +1/+1 counter on Knight of the Ebon Legion."))
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    assert any(effect.condition and effect.condition.get("kind") == "life_lost_this_turn"
               for ability in result.specs for effect in ability.effects)
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(source)
    assert len(source.triggered_abilities) == 1


def test_rowdy_research_discount_counts_distinct_declared_attackers():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    engine.begin_turn()
    spell = GameObject(Card(
        id="rowdy", name="Rowdy Research", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{5}{U}",
        oracle_text="This spell costs {1} less to cast for each creature that attacked this turn.\nDraw three cards.",
    ), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    assert self_cost_reduction_for(spell, state, caster_id="p1")[0] == 0
    for instance_id, declared in ((101, True), (101, True), (102, False), (103, True)):
        state.fire_event(GameEvent(EventType.ATTACKS, instance_id=instance_id,
                                   object_types=["creature"], declared=declared, player_id="p2"))
    assert count_selector(state, "p1", "creatures_attacked_this_turn") == 2
    assert self_cost_reduction_for(spell, state, caster_id="p1")[0] == 2


def test_diregraf_rebirth_reuses_died_count_for_discount():
    card = Card(id="diregraf", name="Diregraf Rebirth", type_line="Sorcery", is_sorcery=True,
                oracle_text="This spell costs {1} less to cast for each creature that died this turn.\n"
                            "Return target creature card from your graveyard to the battlefield.\n"
                            "Flashback {5}{B}{G}")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    assert any(effect.type == "cost_reduction" and effect.params.get("per") == "creatures_died_this_turn"
               for ability in result.specs for effect in ability.effects)


def test_life_lost_last_turn_uses_immediately_previous_turn_only():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    condition = static_condition("you lost life last turn")
    assert condition == {"kind": "life_lost_last_turn", "scope": "you", "min": 1}
    engine.begin_turn()
    engine.rules.lose_life(state.player_by_id("p1"), 2)
    assert not condition_holds(condition, state, controller_id="p1")
    engine.begin_turn()
    assert condition_holds(condition, state, controller_id="p1")
    assert condition_holds(static_condition("an opponent lost life last turn"), state,
                           controller_id="p2")
    engine.begin_turn()
    assert not condition_holds(condition, state, controller_id="p1")


def test_source_damage_history_checks_source_and_opponent():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    engine.begin_turn()
    source = GameObject(Card(id="outlaw", name="Dunerider Outlaw", type_line="Creature",
                             is_creature=True), owner_id="p1", zone=Zone.BATTLEFIELD)
    other = GameObject(Card(id="other", name="Other", type_line="Creature",
                            is_creature=True), owner_id="p1", zone=Zone.BATTLEFIELD)
    condition = static_condition("~ dealt damage to an opponent this turn")
    assert condition == {"kind": "source_dealt_damage_to_opponent_this_turn"}
    state.fire_event(GameEvent(EventType.DAMAGE, source_id=other.instance_id,
                               source_controller_id="p1", target_id="p2", is_player=True, amount=2))
    assert not condition_holds(condition, state, source=source, controller_id="p1")
    state.fire_event(GameEvent(EventType.DAMAGE, source_id=source.instance_id,
                               source_controller_id="p1", target_id="p1", is_player=True, amount=1))
    assert not condition_holds(condition, state, source=source, controller_id="p1")
    state.fire_event(GameEvent(EventType.DAMAGE, source_id=source.instance_id,
                               source_controller_id="p1", target_id="p2", is_player=True, amount=1))
    assert condition_holds(condition, state, source=source, controller_id="p1")
    engine.begin_turn()
    assert not condition_holds(condition, state, source=source, controller_id="p1")


def test_corrupted_cost_reduction_reads_one_opponents_poison_count():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    condition = static_condition("an opponent has three or more poison counters")
    assert condition == {"kind": "opponent_poison_at_least", "amount": 3}
    state.player_by_id("p2").poison = 2
    state.player_by_id("p3").poison = 2
    assert not condition_holds(condition, state, controller_id="p1")
    state.player_by_id("p3").poison = 3
    assert condition_holds(condition, state, controller_id="p1")
    card = Card(id="curiosity", name="Distorted Curiosity", type_line="Sorcery", is_sorcery=True,
                oracle_text="Corrupted — This spell costs {2} less to cast if an opponent has three or more poison counters.\nDraw two cards.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    assert any(effect.type == "cost_reduction" and effect.params.get("active_if") == condition
               for ability in result.specs for effect in ability.effects)


def test_zubera_damage_threshold_uses_dealt_damage_history():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    engine.begin_turn()
    source = GameObject(Card(id="zubera", name="Rushing-Tide Zubera", type_line="Creature",
                             is_creature=True), owner_id="p1", zone=Zone.GRAVEYARD)
    condition = static_condition("4 or more damage was dealt to it this turn")
    assert condition == {"kind": "source_damage_received_this_turn", "min": 4}
    state.fire_event(GameEvent(EventType.DAMAGE, target_id=source.instance_id,
                               is_player=False, amount=2))
    assert not condition_holds(condition, state, source=source, controller_id="p1")
    state.fire_event(GameEvent(EventType.DAMAGE, target_id=source.instance_id,
                               is_player=False, amount=2))
    assert condition_holds(condition, state, source=source, controller_id="p1")
    card = Card(id="zubera-actual", name="Rushing-Tide Zubera", type_line="Creature — Zubera",
                is_creature=True, oracle_text="When Rushing-Tide Zubera dies, if 4 or more damage was dealt to it this turn, draw three cards.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_rushing_tide_zubera_draws_after_four_damage_and_dying():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    player = state.player_by_id("p1")
    for index in range(5):
        player.library.append(GameObject(Card(id=f"land-{index}", name=f"Land {index}", type_line="Land"),
                                         owner_id="p1", zone=Zone.LIBRARY))
    card = Card(id="zubera-live", name="Rushing-Tide Zubera", type_line="Creature — Zubera",
                is_creature=True, power=3, toughness=3,
                oracle_text="When Rushing-Tide Zubera dies, if 4 or more damage was dealt to it this turn, draw three cards.")
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(source)
    bind_from_catalogue(source)
    engine.begin_turn()
    engine.rules.deal_damage(source, 4)
    engine.rules.check_state_based_actions()
    assert source.zone == Zone.GRAVEYARD
    assert engine.rules.put_triggers_on_stack() == 1
    engine.rules.resolve_top_of_stack()
    assert len(player.hand) == 3


def test_essence_anchor_combines_turn_and_graveyard_exit_gate():
    card = Card(id="anchor", name="Essence Anchor", type_line="Artifact",
                oracle_text="{T}: Create a 2/2 black Zombie Druid creature token. "
                            "Activate only during your turn and only if a card left your graveyard this turn.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    assert any(effect.params.get("condition") == {
        "kind": "all", "conditions": [
            {"kind": "your_turn"}, {"kind": "card_left_graveyard_this_turn"},
        ],
    } for ability in result.specs for effect in ability.effects
        if effect.type == "activation_condition_marker")


def test_hired_hexblade_records_actual_treasure_mana_payment():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    engine.begin_turn()
    state.current_step = "main1"
    player = state.player_by_id("p1")
    player.library.append(GameObject(Card(id="drawn", name="Drawn Land", type_line="Land"),
                                     owner_id="p1", zone=Zone.LIBRARY))
    card = Card(id="hexblade", name="Hired Hexblade", type_line="Creature — Human Warlock",
                is_creature=True, power=2, toughness=2, mana_cost_string="{1}{B}",
                oracle_text="When Hired Hexblade enters, if mana from a Treasure was spent to cast it, you draw a card and you lose 1 life.")
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    player.hand.append(spell)
    bind_from_catalogue(spell)
    assert parse_oracle(card).modeled
    condition = static_condition("mana from a Treasure was spent to cast it")
    assert condition == {"kind": "treasure_mana_spent_to_cast"}
    assert not condition_holds(condition, state, source=spell, controller_id="p1")
    player.mana_pool.add("B", 1, source_kind="treasure")
    player.mana_pool.add("C", 1)
    engine.cast_spell(player, spell)
    assert spell.mana_spent_to_cast_treasure == 1
    assert condition_holds(condition, state, source=spell, controller_id="p1")
    engine.rules.resolve_top_of_stack()
    assert engine.rules.put_triggers_on_stack() == 1
    engine.rules.resolve_top_of_stack()
    assert len(player.hand) == 1
    assert player.life == 19
