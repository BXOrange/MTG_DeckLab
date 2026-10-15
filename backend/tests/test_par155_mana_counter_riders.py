"""PAR-155: immediate mana counter riders and printed resolution order."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import parse_mana_abilities
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _card(text, name="Counter Rock"):
    return Card(id=name, name=name, type_line="Artifact", oracle_text=text)


def _board(engine, card):
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(obj)
    return obj


def _game():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0)
    return engine, engine.state.players[0]


@pytest.mark.parametrize("text,kind,count", [
    ("{T}: Add {C}{C}. Put two charge counters on Counter Rock.", "charge", 2),
    ("{T}: Add {G}. Put 3 +1/+1 counters on this artifact.", "+1/+1", 3),
    ("{T}: Add one mana of any color. Put a nest counter on this artifact.", "nest", 1),
])
def test_source_counter_count_is_parsed_and_executes_without_stack(text, kind, count):
    card = _card(text)
    [ability] = parse_mana_abilities(card)
    assert ability.source_counters == {kind: count}
    engine, player = _game()
    obj = _board(engine, card)
    produced = engine.tap_for_mana(player, obj)
    assert produced and obj.counters[kind] == count
    assert not engine.state.stack


def test_counter_before_variable_mana_reads_new_count_and_replacement():
    engine, player = _game()
    doubler = _board(engine, Card(id="double", name="Doubling Season", type_line="Enchantment"))
    bind_from_catalogue(doubler)
    rock = _board(engine, _card("{T}: Put a charge counter on this artifact. Add X mana of any one color, "
                                "where X is the number of charge counters on this artifact."))
    assert engine.tap_for_mana(player, rock) == {"W": 2}
    assert rock.counters["charge"] == 2
    rock.tapped = False
    assert engine.tap_for_mana(player, rock) == {"W": 4}
    assert rock.counters["charge"] == 4


@pytest.mark.parametrize("text,count", [
    ("{T}: Add {B} or {G}. You get a poison counter.", 1),
    ("{T}: Add one mana of any color. You get two poison counters.", 2),
])
def test_player_poison_counter_rider_executes_immediately(text, count):
    engine, player = _game()
    rock = _board(engine, _card(text))
    engine.tap_for_mana(player, rock)
    assert player.poison == count


@pytest.mark.parametrize("rider", [
    "When this mana is spent to cast a legendary spell, put a +1/+1 counter on this artifact.",
    "If you control a creature, put a charge counter on this artifact.",
    "When you next cast a spell, put a charge counter on this artifact.",
])
def test_conditional_sentence_is_not_an_immediate_source_counter(rider):
    [ability] = parse_mana_abilities(_card("{T}: Add {G}. " + rider))
    assert ability.source_counters == {}


def test_targeted_counter_ability_is_not_mana_ability():
    assert not parse_mana_abilities(_card("{T}: Add {G}. Put a +1/+1 counter on target creature."))


def test_real_empowered_autogenerator_generic_mana_option_is_available():
    from mtg_analyzer.parser.oracle import parse_oracle
    text = ("This artifact enters tapped.\n{T}: Put a charge counter on this artifact. "
            "Add X mana of any one color, where X is the number of charge counters on this artifact.")
    card = _card(text, "Empowered Autogenerator")
    assert not parse_oracle(card).modeled  # authored coverage does not prove the generic path
    engine, player = _game()
    rock = _board(engine, card)  # deliberately use generic mana path, no authored ability
    actions = engine.legal_actions(player)
    assert any(a['type'] == 'tap_for_mana' and a['instance_id'] == rock.instance_id for a in actions)
    assert engine.tap_for_mana(player, rock) == {'W': 1}


def test_pre_counter_any_combination_keeps_chosen_color_split():
    engine, player = _game()
    rock = _board(engine, _card("{T}: Put a charge counter on this artifact. Add X mana in any combination "
                                "of colors, where X is the number of charge counters on this artifact."))
    rock.counters['charge'] = 2
    assert engine.tap_for_mana(player, rock, color_split={'U': 1, 'G': 2}) == {'U': 1, 'G': 2}


def test_real_mox_poison_is_modeled_and_places_the_poison_rider():
    from mtg_analyzer.parser.oracle import parse_oracle
    card = _card("{T}: Add one mana of any color. You get two poison counters.", "Mox Poison")
    assert parse_oracle(card).modeled
    engine, player = _game()
    rock = _board(engine, card)
    engine.tap_for_mana(player, rock)
    assert player.poison == 2


def test_pre_counter_prohibition_still_resolves_with_zero_mana():
    from mtg_analyzer.game.effects.core import StaticAbility
    engine, player = _game()
    rock = _board(engine, _card("{T}: Put a charge counter on this artifact. Add X mana of any one color, "
                                "where X is the number of charge counters on this artifact."))
    rock.static_effects.append(StaticAbility('counter_placement_prohibition', affects='self', params={'counter_kind': 'all'}, source=rock))
    assert engine.tap_for_mana(player, rock) == {'W': 0}
    assert rock.tapped and not rock.counters


@pytest.mark.parametrize('entry_route', ['token', 'searched', 'graveyard_batch'])
def test_granted_entry_counter_is_applied_once_on_each_external_entry_route(entry_route):
    from mtg_analyzer.game.effects.battlefield_batches import start_battlefield_batch
    engine, player = _game()
    granter = _board(engine, Card(id='grant', name='Entry Grant', type_line='Enchantment',
        oracle_text='Each creature you control enters with an additional +1/+1 counter on it.'))
    bind_from_catalogue(granter)
    engine.recompute_continuous_effects()
    creature = Card(id='entrant', name='Entry Bear', type_line='Creature — Bear',
                    is_creature=True, power=2, toughness=2)
    if entry_route == 'token':
        entrant, = engine.rules.create_token(player.id, creature)
    elif entry_route == 'searched':
        entrant = GameObject(creature, owner_id=player.id, zone=Zone.LIBRARY)
        engine.rules._put_searched_card(player, entrant, 'battlefield')
    else:
        entrant = GameObject(creature, owner_id=player.id, zone=Zone.GRAVEYARD)
        player.add_to_zone(entrant, Zone.GRAVEYARD)
        start_battlefield_batch(engine.rules, [entrant], player.id)
    assert entrant in engine.state.battlefield
    assert entrant.counters.get('+1/+1') == 1
