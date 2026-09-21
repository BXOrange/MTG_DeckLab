"""PAR-64 — Raid's ``you attacked this turn`` condition outside its ordinary
``if <condition>, <body>`` position."""

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.counters import entry_counters_condition
from tests import turn_history_events as history


def _card(name: str, text: str) -> Card:
    return Card(
        id=name, name=name, type_line="Creature — Human", is_creature=True,
        power=2, toughness=2, oracle_text=text,
    )


def _engine() -> GameEngine:
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)


def test_raid_entry_counter_clause_is_recognized_and_rejects_unknown_tail():
    assert entry_counters_condition("~ enters with a +1/+1 counter on it if you attacked this turn.") == {
        "is_x": False, "count": 1, "counter_type": "+1/+1", "raid_gate": True,
    }
    assert entry_counters_condition(
        "~ enters with a +1/+1 counter on it if you attacked this turn and draw a card."
    ) is None


def test_raid_entry_counter_reads_player_attack_history_at_entry():
    engine = _engine()
    card = _card("Rigging Runner", "~ enters with a +1/+1 counter on it if you attacked this turn.")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    engine.rules._apply_entry_counters(obj)
    assert obj.counters == {}
    history.declared_attack(engine.state, "p1")
    engine.rules._apply_entry_counters(obj)
    assert obj.counters == {"+1/+1": 1}
    assert parse_oracle(card).coverage == MODELED


def test_another_color_spell_unless_entry_counter_is_a_pre_entry_replacement():
    engine = _engine()
    card = _card(
        "Hotheaded Giant",
        "This creature enters with two -1/-1 counters on it unless you've cast another red spell this turn.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    engine.rules._apply_entry_counters(obj)
    assert obj.counters == {"-1/-1": 2}

    # The resolving red creature is already in the per-turn history; a
    # second red spell proves that a distinct prior one was cast.
    history.cast_spell(engine.state, "p1", types=["creature"], colors=["R"], times=2)
    other = GameObject(card, owner_id="p1", zone=Zone.HAND)
    engine.rules._apply_entry_counters(other)
    assert other.counters == {}
    assert parse_oracle(card).coverage == MODELED


def test_another_color_spell_cast_restriction_binds_and_checks_history():
    engine = _engine()
    engine.begin_turn()
    engine.state.current_step = "main1"
    card = _card(
        "Talara's Battalion",
        "Cast this spell only if you've cast another green spell this turn.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    player = engine.state.player_by_id("p1")
    player.hand.append(obj)
    assert obj.cast_condition == {"another_spell_cast_this_turn": {"color": "G"}}
    assert not engine.can_cast(player, obj, assume_mana_available=True)
    history.cast_spell(engine.state, "p1", types=["creature"], colors=["G"])
    assert engine.can_cast(player, obj, assume_mana_available=True)
    assert parse_oracle(card).coverage == MODELED


def test_raid_activation_restriction_binds_and_checks_player_history():
    engine = _engine()
    engine.begin_turn()
    engine.state.current_step = "main1"
    card = _card(
        "Bloodsoaked Champion",
        "{1}{B}: Return this card from your graveyard to the battlefield. Activate only if you attacked this turn.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    ability = obj.activated_abilities[0]
    player = engine.state.player_by_id("p1")
    player.graveyard.append(obj)
    assert ability.cost.activation_condition == {"kind": "you_attacked_this_turn"}
    assert not engine.can_activate(player, obj, ability, assume_mana_available=True)
    history.declared_attack(engine.state, "p1")
    assert engine.can_activate(player, obj, ability, assume_mana_available=True)
    assert parse_oracle(card).coverage == MODELED


def test_source_attacked_this_turn_static_is_live_not_a_raid_history_gate():
    engine = _engine()
    card = _card("Agent Frank Horrigan", "~ has indestructible as long as it attacked this turn.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    from mtg_analyzer.game.combat import has_indestructible

    assert not has_indestructible(obj)
    obj.attacked_this_turn = True
    engine.recompute_continuous_effects()
    assert has_indestructible(obj)
    assert parse_oracle(card).coverage == MODELED


def test_raid_damage_overrides_keep_the_preceding_target_and_rider():
    firecannon = Card(
        id="Firecannon Blast", name="Firecannon Blast", type_line="Sorcery", is_sorcery=True,
        oracle_text="Firecannon Blast deals 3 damage to target creature.\n"
                    "Firecannon Blast deals 6 damage instead if you attacked this turn.",
    )
    arrow = Card(
        id="Arrow Storm", name="Arrow Storm", type_line="Sorcery", is_sorcery=True,
        oracle_text="Arrow Storm deals 4 damage to any target.\n"
                    "If you attacked this turn, instead Arrow Storm deals 5 damage to that permanent or player and the damage can't be prevented.",
    )
    fire_effect = parse_oracle(firecannon).specs[0].effects[0]
    arrow_effect = parse_oracle(arrow).specs[0].effects[0]
    assert fire_effect.params == {"amount": 3, "target_kind": "creature", "amount_if_raid": 6}
    assert arrow_effect.params == {
        "amount": 4, "target_kind": "any", "amount_if_raid": 5, "unpreventable": True,
    }
    assert parse_oracle(firecannon).coverage == MODELED
    assert parse_oracle(arrow).coverage == MODELED


def test_raid_damage_override_reads_controller_declaration_history_on_resolution():
    from mtg_analyzer.game.effects.registry import EffectRegistry

    engine = _engine()
    source = GameObject(
        Card(id="spell", name="Spell", type_line="Sorcery"), owner_id="p1", zone=Zone.STACK
    )
    target = engine.state.player_by_id("p2")
    effect = EffectRegistry.create("damage", {"amount": 3, "target_kind": "player", "amount_if_raid": 6})
    effect.source = source
    effect.apply(engine.rules.context, [target])
    assert target.life == 37
    history.declared_attack(engine.state, "p1")
    effect.apply(engine.rules.context, [target])
    assert target.life == 31
