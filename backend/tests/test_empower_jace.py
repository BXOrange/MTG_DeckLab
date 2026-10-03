"""MEC-110 / VIS-11: Empower Jace, token loyalty and shared board views."""
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.token_database import jace_token_card
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.services.game_session import GameSession
from mtg_analyzer.services.replay import serialize_replay, build_replay_engine
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult
import pytest


def _game():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    source = GameObject(Card(id="empower", name="Test Action", type_line="Sorcery",
                             is_sorcery=True, oracle_text="Empower Jace 3."),
                        owner_id="p1", zone=Zone.STACK)
    return engine.rules, source


def _empower(engine, source, count=3):
    effect = EffectRegistry.create("empower_jace", {"count": count})
    effect.source = source
    effect.apply(engine.context)


def test_empower_creates_blue_nonlegendary_planeswalker_with_live_loyalty_abilities():
    engine, source = _game()
    _empower(engine, source)
    token, = engine.state.battlefield
    assert token.is_token and token.is_planeswalker and not token.card.is_legendary
    assert token.card.color_identity == {"U"}
    assert token.loyalty == 3
    assert len(token.activated_abilities) == 2
    assert token.to_dict()["loyalty"] == 3
    _empower(engine, source, 2)
    assert engine.state.battlefield == [token]
    assert token.loyalty == 5


def test_only_own_jace_planeswalker_tokens_qualify_including_copies():
    engine, source = _game()
    printed = GameObject(Card(id="printed", name="Jace", type_line="Planeswalker — Jace", loyalty=4),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(printed)
    opponent = engine.create_token("p2", jace_token_card())[0]
    opponent.counters["loyalty"] = 4
    impostor = engine.create_token("p1", Card(id="bear", name="Jace", type_line="Creature — Bear",
                                            is_creature=True, power=2, toughness=2))[0]
    _empower(engine, source)
    assert printed.loyalty == opponent.loyalty == 4
    assert "loyalty" not in impostor.counters
    own = [o for o in engine.state.battlefield if o.is_planeswalker and o.is_token and o.controller_id == "p1"]
    assert len(own) == 1 and own[0].loyalty == 3


def test_multiple_tokens_offer_untargeted_choice_and_apply_only_to_the_pick():
    engine, source = _game()
    first, second = engine.create_token("p1", jace_token_card(), 2)
    first.counters["loyalty"] = second.counters["loyalty"] = 1
    _empower(engine, source, 2)
    choice = engine.state.pending_choice
    assert choice["kind"] == "choose_objects"
    assert {o["instance_id"] for o in choice["options"]} == {first.instance_id, second.instance_id}
    engine.resolve_choice(str(second.instance_id))
    assert first.loyalty == 1 and second.loyalty == 3


def test_zero_still_creates_a_token_that_dies_at_the_next_sba():
    engine, source = _game()
    _empower(engine, source, 0)
    assert len(engine.state.battlefield) == 1
    engine.check_state_based_actions()
    assert not engine.state.battlefield


def test_parser_claims_standalone_and_triggered_empower():
    for text in ("Empower Jace 2.", "When this creature enters, empower Jace 2."):
        card = Card(id="parse", name="Student", type_line="Sorcery", is_sorcery=True,
                    oracle_text=text)
        result = parse_oracle(card)
        assert not result.unclaimed
        assert any(e.type == "empower_jace" for s in result.specs for e in s.effects)


def test_token_copy_of_named_jace_is_reused():
    engine, source = _game()
    token = engine.create_token("p1", Card(id="copy", name="Jace, Copy",
                                         type_line="Legendary Planeswalker — Jace", loyalty=2))[0]
    _empower(engine, source, 4)
    assert engine.state.battlefield == [token]
    assert token.loyalty == 6


def test_doublers_create_multiple_tokens_then_double_counters_on_only_the_pick():
    engine, source = _game()
    for name in ("Doubling Season", "Parallel Lives"):
        obj = GameObject(Card(id=name, name=name, type_line="Enchantment"),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
        bind_from_catalogue(obj)
        engine.state.add_to_battlefield(obj)
    _empower(engine, source, 2)
    assert engine.state.pending_choice["kind"] == "replacement_order"
    engine.resolve_choice(0)
    tokens = [o for o in engine.state.battlefield if o.is_token]
    assert len(tokens) == 4
    assert engine.state.pending_choice["kind"] == "choose_objects"
    engine.resolve_choice(str(tokens[-1].instance_id))
    assert [o.loyalty for o in tokens] == [0, 0, 0, 4]
    engine.check_state_based_actions()
    assert [o for o in engine.state.battlefield if o.is_token] == [tokens[-1]]


@pytest.mark.parametrize("mode", ["goldfish", "replay", "multiplayer"])
def test_shared_board_view_exposes_token_loyalty_and_both_actions(mode):
    rules, source = _game()
    _empower(rules, source)
    engine = GameEngine(rules.state)
    session = GameSession(engine, mode=mode)
    view = session.view(perspective="p1")
    token = view["state"]["battlefield"][0]
    assert token["is_planeswalker"] and token["is_token"] and token["loyalty"] == 3
    actions = [a for a in view["legal_actions"] if a["type"] == "activate_ability"]
    assert len(actions) == 2


def test_replay_round_trip_preserves_token_abilities_and_loyalty():
    rules, source = _game()
    _empower(rules, source, 5)

    class Loader:
        def load_cards(self, names):
            return LoadCardsResult(cards={}, not_found=[])

    engine = build_replay_engine(serialize_replay(rules.state), Loader())
    token, = engine.state.battlefield
    assert token.loyalty == 5 and token.is_token and token.is_planeswalker
    assert len(token.activated_abilities) == 2


def test_loyalty_draw_cost_is_paid_and_last_loyalty_kills_token_before_resolution():
    rules, source = _game()
    _empower(rules, source, 3)
    engine = GameEngine(rules.state)
    player = engine.state.player_by_id("p1")
    card = Card(id="draw", name="Drawn", type_line="Land", is_land=True)
    player.library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))
    token, = engine.state.battlefield
    engine.activate_ability(player, token, ability_index=1)
    engine.resolve_until_stable()
    assert not engine.state.battlefield
    assert player.hand[-1].name == "Drawn"


def test_where_x_counts_own_creatures_at_resolution():
    rules, source = _game()
    source.card.oracle_text = "Empower Jace X, where X is the number of creatures you control."
    from mtg_analyzer.game.binding.core import build_effects
    for i in range(2):
        rules.create_token("p1", Card(id=f"bear{i}", name="Bear", type_line="Creature — Bear",
                                     is_creature=True, power=2, toughness=2))
    result = parse_oracle(source.card)
    assert not result.unclaimed
    for spec in result.specs:
        for effect in build_effects(spec.effects, source):
            effect.apply(rules.context)
    assert next(o for o in rules.state.battlefield if o.is_planeswalker).loyalty == 2


def test_token_surveillance_is_a_live_interactive_loyalty_action():
    rules, source = _game()
    _empower(rules, source, 2)
    engine = GameEngine(rules.state)
    player = engine.state.player_by_id("p1")
    player.library.append(GameObject(Card(id="top", name="Top", type_line="Land", is_land=True),
                                     owner_id="p1", zone=Zone.LIBRARY))
    token, = engine.state.battlefield
    engine.activate_ability(player, token, ability_index=0)
    engine.resolve_until_stable()
    assert token.loyalty == 1
    assert engine.state.pending_choice["kind"] == "surveil"
    assert not any(a["type"] == "activate_ability" for a in engine.legal_actions(player))


def test_spell_with_all_illegal_targets_does_not_empower():
    rules, _ = _game()
    engine = GameEngine(rules.state)
    engine.interactive_priority = True
    player = engine.state.player_by_id("p1")
    victim = rules.create_token("p2", Card(id="bear", name="Bear", type_line="Creature — Bear",
                                          is_creature=True, power=2, toughness=2))[0]
    spell = GameObject(Card(id="ascent", name="Academic Ascent", type_line="Instant", is_instant=True,
                           oracle_text="Target creature gets +2/+2 and gains flying until end of turn.\nEmpower Jace 2."),
                       owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.hand.append(spell)
    engine.cast_spell(player, spell, targets=[victim])
    rules.exile(victim)
    engine.resolve_until_stable()
    assert not any(o.is_planeswalker for o in engine.state.battlefield)


@pytest.mark.parametrize("text", ["Empower Jace 2.",
                                 "Empower Jace X, where X is the number of creatures you control."])
def test_empower_token_is_enumerated_for_deck_art_preloading(text):
    from mtg_analyzer.services.deck_tokens import producible_tokens
    tokens = producible_tokens([Card(id="empower", name="Action", type_line="Sorcery", is_sorcery=True,
                                    oracle_text=text)])
    assert len(tokens) == 1 and tokens[0].is_planeswalker
