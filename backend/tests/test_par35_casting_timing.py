"""PAR-35 — restricted combat casts and the two paid/cleanup Flash shapes."""

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle


def _engine():
    cards = [Card(id=f"f{i}", name=f"F{i}", type_line="Creature", is_creature=True) for i in range(12)]
    return GameEngine.new_game([("p1", "One", cards[:6]), ("p2", "Two", cards[6:])], starting_hand=0)


def _hand(player, card):
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    player.add_to_zone(obj, Zone.HAND)
    bind_from_catalogue(obj)
    return obj


def test_declare_attackers_restriction_parses_and_requires_an_attack_on_you():
    card = Card(
        id="cv", name="Champion's Victory", type_line="Instant", is_instant=True,
        mana_cost_string="{U}", converted_mana_cost=1,
        oracle_text="Cast this spell only during the declare attackers step and only if you've been attacked this step.",
    )
    assert parse_oracle(card).coverage == MODELED
    engine = _engine()
    p1, p2 = engine.state.players
    spell = _hand(p1, card)
    p1.mana_pool.add("U", 1)
    engine.state.current_step = "declare_attackers"
    assert not engine.can_cast(p1, spell)

    attacker = GameObject(Card(id="a", name="Attacker", type_line="Creature", is_creature=True), p2.id, Zone.BATTLEFIELD)
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": p1.id}
    engine.state.add_to_battlefield(attacker)
    assert engine.can_cast(p1, spell)
    engine.state.current_step = "declare_blockers"
    assert not engine.can_cast(p1, spell)


def test_paid_flash_adds_its_mana_only_outside_a_sorcery_window():
    card = Card(
        id="gf", name="Ghitu Fire", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{R}", converted_mana_cost=1,
        oracle_text="You may cast this spell as though it had flash if you pay {2} more to cast it.",
    )
    assert parse_oracle(card).coverage == MODELED
    engine = _engine()
    p1 = engine.state.active_player
    spell = _hand(p1, card)
    p1.mana_pool.add("R", 1)
    engine.state.current_step = "main1"
    assert engine.can_cast(p1, spell)
    engine.state.current_step = "combat_damage"
    assert not engine.can_cast(p1, spell)
    p1.mana_pool.add("C", 2)
    assert engine.can_cast(p1, spell)
    assert engine.effective_cast_cost(p1, spell).converted_mana_cost == 3


def test_flash_cleanup_rider_is_a_real_conditional_delayed_trigger():
    card = Card(
        id="at", name="Armor of Thorns", type_line="Enchantment — Aura",
        oracle_text=("You may cast this spell as though it had flash. If you cast it any time a sorcery couldn't have "
                     "been cast, the controller of the permanent it becomes sacrifices it at the beginning of the next cleanup step."),
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    [spec] = specs_for(card)
    assert spec.conditional_flash == {"unconditional": True}
    assert spec.effects[0].type == "create_delayed_trigger"
    assert spec.effects[0].condition == {"cast_outside_sorcery_speed": True}


def test_combat_damage_discard_that_many_reads_the_damage_event():
    card = Card(id="ds", name="Dreamstealer", type_line="Creature", is_creature=True,
                oracle_text="Whenever this creature deals combat damage to a player, that player discards that many cards.")
    result = parse_oracle(card)
    assert result.coverage == MODELED
    effect = result.specs[0].effects[0]
    assert effect.params == {"count": 0, "previous_subject": True,
                             "count_from_trigger_event": "amount"}
