"""PAR-217: type- and characteristic-changing "becomes", parsed and executed against a real engine."""
from __future__ import annotations

import pytest

from mtg_analyzer.game.mana_abilities import mana_abilities_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import creature, land
from tests.test_par210_object_phrases import cast
from tests.test_par210_player_references import DB, board, game


def artifact(name: str, mana_value: int = 0, **kwargs) -> Card:
    return Card(id=name, name=name, type_line=kwargs.pop('type_line', 'Artifact'),
                mana_cost_string=f'{{{mana_value}}}', converted_mana_cost=mana_value, **kwargs)


def enchantment(name: str) -> Card:
    return Card(id=name, name=name, type_line='Enchantment', mana_cost_string='{2}', converted_mana_cost=2)


def refresh(eng):
    eng.recompute_continuous_effects()


def end_turn(eng):
    eng._step_cleanup()
    refresh(eng)


def pick(eng, answer):
    """Answer the open choice (the `choose_for_source` pick) and let the rest of the resolution run."""
    choice = eng.state.pending_choice
    assert choice is not None and answer in [o['id'] for o in choice['options']]
    eng.resolve_pending_choice(answer)
    eng.resolve_until_stable()


# --- colour -----------------------------------------------------------------------------------------------------

def test_fixed_colour_replaces_colours_until_the_clock_ends():
    eng = game()
    victim = board(eng, creature('Green Bear'), 'p2')
    cast(eng, 'Target creature becomes blue until end of turn.', [victim])
    refresh(eng)
    assert victim.colors == {'U'}
    end_turn(eng)
    assert victim.colors == {'G'}


def test_colorless_and_all_colors():
    eng = game()
    victim = board(eng, creature('Green Bear'), 'p2')
    cast(eng, 'Target creature becomes colorless until end of turn.', [victim])
    refresh(eng)
    assert victim.colors == set()
    other = board(eng, creature('Bear'), 'p2')
    cast(eng, 'Target creature becomes all colors until end of turn.', [other])
    refresh(eng)
    assert other.colors == set('WUBRG')


def test_colour_of_your_choice_freezes_the_pick_into_the_effect():
    eng = game()
    first = board(eng, creature('First'), 'p2')
    second = board(eng, creature('Second'), 'p2')
    cast(eng, 'Target creature becomes the color of your choice.', [first])
    pick(eng, 'R')
    cast(eng, 'Target creature becomes the color of your choice.', [second])
    pick(eng, 'B')
    refresh(eng)
    # the second pick must not rewrite the first effect (the answer is stamped into each created effect)
    assert first.colors == {'R'} and second.colors == {'B'}


def test_self_colour_choice_ends_with_the_turn():
    eng = game()
    kavu = board(eng, creature('Kavu', oracle_text='{G}: ~ becomes the color of your choice until end of turn.'))
    assert parse_oracle(kavu.card).modeled
    specs = parse_effect_body('~ becomes the color of your choice until end of turn.')
    assert [s.type for s in specs] == ['choose_for_source', 'seq']


# --- land types -------------------------------------------------------------------------------------------------

def test_land_becomes_a_basic_type_and_reverts():
    eng = game()
    forest = board(eng, land('Forest', 'Forest'))
    cast(eng, 'Target land becomes an Island until end of turn.', [forest])
    refresh(eng)
    assert forest.has_subtype('Island') and not forest.has_subtype('Forest') and forest.is_land
    # RULE 305.6/305.7: the Island's intrinsic mana replaces the Forest's
    assert [o for a in mana_abilities_for(forest, eng.state) for o in a.options] == [{'U': 1}]
    end_turn(eng)
    assert forest.has_subtype('Forest') and not forest.has_subtype('Island')
    assert [o for a in mana_abilities_for(forest, eng.state) for o in a.options] == [{'G': 1}]


def test_land_type_replacement_keeps_an_animated_lands_creature_types():
    eng = game()
    dryad = board(eng, Card(id='Dryad', name='Dryad', type_line='Land Creature — Forest Dryad', is_land=True,
                            is_creature=True, power=1, toughness=1))
    cast(eng, 'Target land becomes a Swamp until end of turn.', [dryad])
    refresh(eng)
    assert dryad.has_subtype('Swamp') and dryad.has_subtype('Dryad') and not dryad.has_subtype('Forest')


def test_basic_land_type_of_your_choice():
    eng = game()
    forest = board(eng, land('Forest', 'Forest'))
    cast(eng, 'Target land becomes the basic land type of your choice until end of turn.', [forest])
    pick(eng, 'Mountain')
    refresh(eng)
    assert forest.has_subtype('Mountain') and not forest.has_subtype('Forest')
    assert [o for a in mana_abilities_for(forest, eng.state) for o in a.options] == [{'R': 1}]
    end_turn(eng)
    assert forest.has_subtype('Forest')


def test_a_land_type_body_needs_a_land_subject():
    assert parse_effect_body('target creature becomes an island until end of turn.') is None
    assert parse_effect_body('target permanent becomes the basic land type of your choice.') is None


# --- artifact creatures (RULE 205.1a) -----------------------------------------------------------------------------

def test_noncreature_artifact_becomes_creature_with_power_equal_to_its_mana_value():
    eng = game()
    big = board(eng, artifact('Big Rock', 4))
    bystander = board(eng, artifact('Small Rock', 1))
    cast(eng, 'Target noncreature artifact becomes an artifact creature with power and toughness each equal to its '
              'mana value until end of turn.', [big])
    refresh(eng)
    assert big.is_creature and big.is_artifact and (big.power, big.toughness) == (4, 4)
    assert not bystander.is_creature
    end_turn(eng)
    assert not big.is_creature and big.is_artifact


def test_animation_replaces_the_other_card_types_of_a_noncreature():
    eng = game()
    wonder = board(eng, enchantment('Opal Thing'))
    cast(eng, 'Target enchantment becomes a 4/4 Beast creature.', [wonder])
    refresh(eng)
    # RULE 205.1a: the card type is replaced, so it is a creature and no longer an enchantment
    assert wonder.is_creature and not wonder.is_enchantment and (wonder.power, wonder.toughness) == (4, 4)
    assert wonder.has_subtype('Beast')


def test_still_a_planeswalker_keeps_the_card_type():
    eng = game()
    walker = board(eng, Card(id='Gid', name='Gid', type_line='Legendary Planeswalker — Gideon',
                             mana_cost_string='{2}{W}{W}', converted_mana_cost=4, loyalty=5))
    cast(eng, 'Target permanent becomes a 5/5 Human Soldier creature that\'s still a planeswalker until end of turn.',
         [walker])
    refresh(eng)
    assert walker.is_creature and walker.is_planeswalker and (walker.power, walker.toughness) == (5, 5)


def test_vehicle_keeps_its_printed_power_and_toughness():
    eng = game()
    wagon = board(eng, Card(id='Wagon', name='Wagon', type_line='Artifact — Vehicle', mana_cost_string='{3}',
                            converted_mana_cost=3, vehicle_power=4, vehicle_toughness=3))
    cast(eng, 'Target vehicle becomes an artifact creature until end of turn.', [wagon])
    refresh(eng)
    assert wagon.is_creature and (wagon.power, wagon.toughness) == (4, 3)
    end_turn(eng)
    assert not wagon.is_creature


# --- creature types with base power and toughness (RULE 613.4b) ------------------------------------------------------

def test_becomes_a_coloured_creature_type_with_base_power_and_toughness():
    eng = game()
    victim = board(eng, creature('Big', power=6, toughness=6, cost='{1}{R}', type_line='Creature — Giant'), 'p2')
    victim.counters['+1/+1'] = 1
    cast(eng, 'Target creature becomes a blue serpent with base power and toughness 5/5 until end of turn.', [victim])
    refresh(eng)
    assert victim.colors == {'U'} and victim.has_subtype('Serpent') and not victim.has_subtype('Giant')
    assert (victim.power, victim.toughness) == (6, 6)  # base 5/5 plus its +1/+1 counter (RULE 613.4b, then 613.4c)
    end_turn(eng)
    assert victim.colors == {'R'} and victim.has_subtype('Giant')
    assert (victim.power, victim.toughness) == (7, 7)


def test_a_later_base_set_wins_by_timestamp():
    eng = game()
    victim = board(eng, creature('Bear'), 'p2')
    cast(eng, 'Target creature becomes a frog with base power and toughness 1/1 until end of turn.', [victim])
    cast(eng, 'Target creature becomes a dragon with base power and toughness 4/4 until end of turn.', [victim])
    refresh(eng)
    assert (victim.power, victim.toughness) == (4, 4) and victim.has_subtype('Dragon')


def test_loses_all_abilities_then_gains_flying_keeps_the_grant():
    eng = game()
    victim = board(eng, creature('Trampler', oracle_text='Trample'), 'p2')
    cast(eng, 'Target creature becomes a dragon with base power and toughness 4/4, loses all abilities, and gains '
              'flying until end of turn.', [victim])
    refresh(eng)
    assert 'flying' in victim.granted_keywords and victim.loses_all_abilities
    end_turn(eng)
    assert 'flying' not in victim.granted_keywords and not victim.loses_all_abilities


def test_self_becomes_with_leading_duration_and_x():
    eng = game()
    src = board(eng, Card(id='Staff', name='Staff', type_line='Artifact', mana_cost_string='{2}', converted_mana_cost=2,
                          oracle_text='{X}: ~ becomes an X/X Construct artifact creature until end of turn.'))
    assert parse_oracle(src.card).modeled
    specs = parse_effect_body('until end of turn, ~ becomes a rhino with base power and toughness 4/4 and gains trample.')
    assert specs and specs[0].params['duration'] == 'end_of_turn' and specs[0].params['self_subject']


def test_plural_group_and_pronoun_operands_compose():
    eng = game()
    theirs = [board(eng, creature(f'Theirs {i}'), 'p2') for i in range(2)]
    mine = board(eng, creature('Mine'))
    cast(eng, 'Each creature your opponents control becomes red until end of turn.')
    refresh(eng)
    assert all(c.colors == {'R'} for c in theirs) and mine.colors == {'G'}
    cast(eng, 'All creatures become black until end of turn.')  # the plural verb agrees with the plural operand
    refresh(eng)
    assert all(c.colors == {'B'} for c in [*theirs, mine])


def test_pronoun_follow_up_binds_the_previous_target():
    eng = game()
    target = board(eng, creature('Target'), 'p2')
    bystander = board(eng, creature('Bystander'), 'p2')
    cast(eng, 'Tap target creature. It becomes black until end of turn.', [target])
    refresh(eng)
    assert target.colors == {'B'} and bystander.colors == {'G'}


# --- fail-closed ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('text', [
    'Target creature becomes a blorp with base power and toughness 2/2 until end of turn.',  # unknown type word
    'Target creature becomes blue and isn\'t an artifact until end of turn.',
    'Target creature becomes a copy of target artifact.',
])
def test_unrecognised_bodies_stay_unclaimed(text):
    assert parse_effect_body(text) is None


# --- real cards ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('name', [
    'Karn, Silver Golem', 'Serpentine Ambush', 'Dragonshift', 'Dream Thrush', 'Cerulean Wisps', 'Caldera Kavu',
    'Chimeric Staff', 'Opal Caryatid', 'Hidden Stag', 'Skilled Animator', 'Tide Shaper', 'Streambed Aquitects',
])
def test_real_cards_are_modeled(name):
    card = DB.get_card(name)
    assert card is not None and parse_oracle(card).modeled


def test_opal_caryatid_trigger_turns_the_enchantment_into_a_creature():
    eng = game()
    card = DB.get_card('Opal Caryatid')
    opal = board(eng, card)
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    spell = GameObject(creature('Cast Me', oracle_text='Flash'), owner_id='p2', zone=Zone.HAND)
    bind_from_catalogue(spell)
    eng.state.active_player_index = 1  # p2's own main phase, so the creature spell is castable
    caster = eng.state.player_by_id('p2')
    caster.hand.append(spell)
    caster.mana_pool.add_many({'G': 2, 'C': 2})
    eng.cast_spell(caster, spell)
    eng.resolve_until_stable()
    refresh(eng)
    assert opal.is_creature and not opal.is_enchantment and (opal.power, opal.toughness) == (2, 2)
    assert opal.has_subtype('Soldier')


# --- real cards, activated against the engine ------------------------------------------------------------------------

def activate(eng, obj, index=0, x=0, targets=None):
    p1 = eng.state.player_by_id('p1')
    p1.mana_pool.add_many({'W': 9, 'U': 9, 'B': 9, 'R': 9, 'G': 9, 'C': 9})
    obj.summoning_sick = False
    eng.activate_ability(p1, obj, index, x=x, targets=targets or [])
    eng.resolve_until_stable()
    refresh(eng)


def test_figure_of_destiny_levels_up_permanently_and_conditionally():
    eng = game()
    figure = board(eng, DB.get_card('Figure of Destiny'))
    assert figure.has_subtype('Kithkin')
    activate(eng, figure, 0)
    assert figure.has_subtype('Spirit') and (figure.power, figure.toughness) == (2, 2)
    end_turn(eng)
    assert (figure.power, figure.toughness) == (2, 2)  # no clock: it stays
    activate(eng, figure, 1)
    assert figure.has_subtype('Warrior') and (figure.power, figure.toughness) == (4, 4)


def test_figure_of_destiny_second_level_needs_the_spirit_type():
    eng = game()
    figure = board(eng, DB.get_card('Figure of Destiny'))
    activate(eng, figure, 1)  # "if ~ is a Spirit" does not hold yet
    assert not figure.has_subtype('Warrior') and (figure.power, figure.toughness) == (1, 1)


def test_karn_animates_a_noncreature_artifact_and_it_ends_with_the_turn():
    eng = game()
    karn = board(eng, DB.get_card('Karn, Silver Golem'))
    rock = board(eng, artifact('Rock', 3))
    karn.summoning_sick = False
    activate(eng, karn, 0, targets=[rock])
    assert rock.is_creature and (rock.power, rock.toughness) == (3, 3)
    end_turn(eng)
    assert not rock.is_creature


def test_dream_thrush_choice_changes_the_land_until_end_of_turn():
    eng = game()
    thrush = board(eng, DB.get_card('Dream Thrush'))
    forest = board(eng, land('Forest', 'Forest'))
    p1 = eng.state.player_by_id('p1')
    thrush.summoning_sick = False
    eng.activate_ability(p1, thrush, 0, targets=[forest])
    eng.resolve_until_stable()
    pick(eng, 'Swamp')
    refresh(eng)
    assert forest.has_subtype('Swamp') and not forest.has_subtype('Forest')


def test_tyrite_sanctum_adds_a_type_and_the_counter_follows_the_same_target():
    eng = game()
    sanctum = board(eng, DB.get_card('Tyrite Sanctum'))
    legend = board(eng, creature('Legend', type_line='Legendary Creature — Human', is_legendary=True))
    other = board(eng, creature('Other'))
    activate(eng, sanctum, 0, targets=[legend])
    assert legend.has_subtype('God') and legend.counters.get('+1/+1') == 1
    assert not other.counters


def test_lurking_evil_stops_being_an_enchantment():
    eng = game()
    evil = board(eng, DB.get_card('Lurking Evil'))
    p1 = eng.state.player_by_id('p1')
    evil.summoning_sick = False
    eng.activate_ability(p1, evil, 0)
    eng.resolve_until_stable()
    refresh(eng)
    assert evil.is_creature and not evil.is_enchantment and (evil.power, evil.toughness) == (4, 4)
    assert evil.has_subtype('Horror') and 'flying' in evil.granted_keywords


def test_chimeric_staff_takes_x_from_the_activation():
    eng = game()
    staff = board(eng, DB.get_card('Chimeric Staff'))
    activate(eng, staff, 0, x=3)
    assert staff.is_creature and staff.is_artifact and (staff.power, staff.toughness) == (3, 3)
    assert staff.has_subtype('Construct')
    end_turn(eng)
    assert not staff.is_creature


def test_vehicles_you_control_group_is_locked_when_it_resolves():
    eng = game()
    wagon = board(eng, Card(id='Wagon', name='Wagon', type_line='Artifact — Vehicle', mana_cost_string='{3}',
                            converted_mana_cost=3, vehicle_power=4, vehicle_toughness=3))
    rock = board(eng, artifact('Rock', 2))
    theirs = board(eng, Card(id='Cart', name='Cart', type_line='Artifact — Vehicle', mana_cost_string='{2}',
                             converted_mana_cost=2, vehicle_power=2, vehicle_toughness=2), 'p2')
    cast(eng, 'Vehicles you control become artifact creatures until end of turn.')
    late = board(eng, Card(id='Late', name='Late', type_line='Artifact — Vehicle', mana_cost_string='{2}',
                           converted_mana_cost=2, vehicle_power=1, vehicle_toughness=1))
    refresh(eng)
    assert wagon.is_creature and (wagon.power, wagon.toughness) == (4, 3)
    assert not rock.is_creature and not theirs.is_creature and not late.is_creature
    end_turn(eng)
    assert not wagon.is_creature


def test_ebony_fly_is_optional_and_uses_the_roll_result():
    eng = game()
    fly = board(eng, DB.get_card('Ebony Fly'))
    p1 = eng.state.player_by_id('p1')
    p1.mana_pool.add_many({'C': 9, 'U': 9})
    eng.activate_ability(p1, fly, 0)
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'composite_optional'  # "you may have ~ become"
    eng.resolve_pending_choice('yes')
    eng.resolve_until_stable()
    refresh(eng)
    assert fly.is_creature and fly.is_artifact and 1 <= fly.power <= 6 and fly.power == fly.toughness


def test_cloudform_becomes_an_aura_and_attaches_to_the_manifested_creature():
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    eng = game()
    p1 = eng.state.player_by_id('p1')
    spell = GameObject(DB.get_card('Cloudform'), owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    p1.mana_pool.add_many({'U': 4, 'C': 4})
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    refresh(eng)
    assert spell.has_subtype('Aura') and spell.parametric_keywords['enchant']['quality'] == 'creature'
    host = next(o for o in eng.state.battlefield if o.instance_id == spell.attached_to)
    assert host.is_creature and 'flying' in host.granted_keywords and 'hexproof' in host.granted_keywords


def test_artifact_creature_animation_retains_land_type_and_subtypes():
    eng = game()
    citadel = board(eng, Card(id='Citadel', name='Citadel', type_line='Land Artifact — Gate', is_land=True,
                              mana_cost_string='{0}', converted_mana_cost=0))
    cast(eng, 'Target noncreature artifact becomes an artifact creature with base power and toughness 3/3 until end of turn.',
         [citadel])
    refresh(eng)
    # RULE 205.1b: artifact-creature animation retains prior card types and subtypes.
    assert citadel.is_creature and citadel.is_artifact and citadel.is_land
    assert citadel.has_subtype('Gate')
    end_turn(eng)
    assert citadel.is_land and not citadel.is_creature and citadel.has_subtype('Gate')


def test_pending_land_choice_and_selected_value_survive_clone():
    from mtg_analyzer.game.game_engine import GameEngine
    eng = game()
    thrush = board(eng, DB.get_card('Dream Thrush'))
    forest = board(eng, land('Forest', 'Forest'))
    activate(eng, thrush, targets=[forest])
    assert eng.state.pending_choice is not None
    clone = GameEngine(eng.state.clone())
    pick(clone, 'Swamp')
    refresh(clone)
    twin = clone.state.find_object(thrush.instance_id)
    assert twin.chosen_land_type == 'Swamp'
    assert clone.state.find_object(forest.instance_id).has_subtype('Swamp')
    assert thrush.chosen_land_type is None and eng.state.pending_choice is not None
    restored = GameEngine(clone.state.clone())
    assert restored.state.find_object(thrush.instance_id).chosen_land_type == 'Swamp'
    end_turn(restored)
    assert restored.state.find_object(forest.instance_id).has_subtype('Forest')


def test_still_a_type_retains_previous_creature_types():
    eng = game()
    dryad = board(eng, Card(id='Dryad', name='Dryad', type_line='Land Creature — Forest Dryad',
                            is_land=True, is_creature=True, power=1, toughness=1))
    cast(eng, "Target land becomes a 4/4 Elemental creature that's still a land until end of turn.", [dryad])
    refresh(eng)
    assert all(dryad.has_subtype(t) for t in ('Forest', 'Dryad', 'Elemental'))
    assert dryad.is_land and dryad.is_creature


def test_artifact_creature_with_creature_types_replaces_only_creature_types():
    eng = game()
    dryad = board(eng, Card(id='Dryad', name='Dryad', type_line='Land Creature — Forest Dryad',
                            is_land=True, is_creature=True, power=1, toughness=1))
    cast(eng, 'Target permanent becomes a 4/4 Construct artifact creature until end of turn.', [dryad])
    refresh(eng)
    assert dryad.is_land and dryad.is_artifact and dryad.is_creature
    assert dryad.has_subtype('Forest') and dryad.has_subtype('Construct') and not dryad.has_subtype('Dryad')


def test_previous_artifact_with_leading_duration_gains_haste():
    eng = game()
    wagon = board(eng, Card(id='Wagon', name='Wagon', type_line='Artifact — Vehicle',
                            vehicle_power=4, vehicle_toughness=3))
    cast(eng, 'Tap target artifact. Until end of turn, it becomes an artifact creature and gains haste.', [wagon])
    refresh(eng)
    assert wagon.is_creature and (wagon.power, wagon.toughness) == (4, 3)
    assert 'haste' in wagon.granted_keywords
    end_turn(eng)
    assert not wagon.is_creature and 'haste' not in wagon.granted_keywords


def test_chimeric_sphere_loses_flying_only_for_the_duration():
    eng = game()
    sphere = board(eng, DB.get_card('Chimeric Sphere'))
    activate(eng, sphere, 0)
    assert (sphere.power, sphere.toughness) == (2, 1) and 'flying' in sphere.granted_keywords
    activate(eng, sphere, 1)
    assert (sphere.power, sphere.toughness) == (3, 2)
    from mtg_analyzer.game.combat import keywords_of
    assert 'flying' not in keywords_of(sphere)
    end_turn(eng)
    assert not sphere.is_creature


def test_multicolor_choice_freezes_all_colors_and_clones_independently():
    from mtg_analyzer.game.game_engine import GameEngine
    eng = game()
    first = board(eng, creature('First'), 'p2')
    spell = cast(eng, 'Target creature becomes the color or colors of your choice until end of turn.', [first])
    assert len(eng.state.pending_choice['options']) == 31
    assert spell.to_dict()['chosen_colors'] == []
    clone = GameEngine(eng.state.clone())
    pick(clone, 'UR')
    refresh(clone)
    assert clone.state.find_object(first.instance_id).colors == {'U', 'R'}
    assert clone.state.find_object(spell.instance_id).chosen_colors == ['U', 'R']
    pick(eng, 'B')
    refresh(eng)
    assert first.colors == {'B'}
    end_turn(clone)
    assert clone.state.find_object(first.instance_id).colors == {'G'}


def test_named_legendary_animation_is_reversible_and_does_not_rewrite_the_card():
    eng = game()
    forest = board(eng, land('Forest', 'Forest'))
    cast(eng, 'Target land becomes a legendary 4/4 Elemental creature with haste named Vitu-Ghazi until end of turn.', [forest])
    refresh(eng)
    assert forest.name == 'Vitu-Ghazi' and forest.names == ('Vitu-Ghazi',)
    assert forest.card.name == 'Forest' and forest.is_legendary and forest.has_subtype('Elemental')
    end_turn(eng)
    assert forest.name == 'Forest' and not forest.is_legendary


def test_name_before_loses_all_abilities():
    eng = game()
    victim = board(eng, creature('Old', oracle_text='Flying'), 'p2')
    cast(eng, 'Target creature becomes a 6/6 legendary Horror creature named Fenric and loses all abilities.', [victim])
    refresh(eng)
    assert victim.name == 'Fenric' and victim.is_legendary and victim.loses_all_abilities
    assert (victim.power, victim.toughness) == (6, 6)


def test_quoted_trigger_is_granted_and_expires():
    eng = game()
    victim = board(eng, artifact('Rock', 2))
    cast(eng, 'Target artifact becomes a 3/3 Construct artifact creature with "Whenever ~ attacks, draw a card." until end of turn.', [victim])
    refresh(eng)
    assert victim.is_creature
    from mtg_analyzer.models.game.events import EventType, GameEvent
    p1 = eng.state.player_by_id('p1')
    before = len(p1.hand)
    eng.state.fire_event(GameEvent(EventType.ATTACKS, instance_id=victim.instance_id, controller_id='p1'))
    eng.resolve_until_stable()
    assert len(p1.hand) == before + 1
    end_turn(eng)
    eng.state.fire_event(GameEvent(EventType.ATTACKS, instance_id=victim.instance_id, controller_id='p1'))
    eng.resolve_until_stable()
    assert len(p1.hand) == before + 1


def test_one_or_more_targets_change_together_and_never_include_bystanders():
    eng = game()
    first = board(eng, creature('First'), 'p2')
    second = board(eng, creature('Second'), 'p2')
    third = board(eng, creature('Third'), 'p2')
    cast(eng, 'One or more target creatures become red until end of turn.', [first, second])
    refresh(eng)
    assert first.colors == second.colors == {'R'} and third.colors == {'G'}
    end_turn(eng)
    assert first.colors == second.colors == {'G'}


def test_stack_spell_or_permanent_color_target_and_instant_sorcery_filter():
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    from mtg_analyzer.game.targeting import legal_targets
    eng = game()
    creature_spell = GameObject(creature('Stack Bear'), owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(creature_spell)
    p1 = eng.state.player_by_id('p1')
    p1.hand.append(creature_spell)
    p1.mana_pool.add_many({'G': 9})
    eng.cast_spell(p1, creature_spell)
    seer = board(eng, DB.get_card('Blind Seer'))
    p1.mana_pool.add_many({'U': 9, 'C': 9})
    eng.activate_ability(p1, seer, 0, targets=[creature_spell])
    eng.rules.resolve_top_of_stack()
    eng.resolve_pending_choice('R')
    eng.rules.resume_deferred_effects()
    refresh(eng)
    assert creature_spell.colors == {'R'}
    eng.resolve_until_stable()
    refresh(eng)
    assert creature_spell.colors == {'R'}
    second_spell = GameObject(creature('Second Stack Bear'), owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(second_spell)
    p1.hand.append(second_spell)
    p1.mana_pool.add_many({'G': 9})
    eng.cast_spell(p1, second_spell)
    mystic = board(eng, DB.get_card('Vodalian Mystic'))
    spec = mystic.activated_abilities[0].effects[-1].target_specs[0]
    assert second_spell.instance_id not in {o['instance_id'] for o in legal_targets(eng.state, 'p1', spec, mystic)}


def test_measured_base_stats_capture_revealed_card_before_it_changes():
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading, REVEALED_REFERENT
    eng = game()
    source = board(eng, creature('Amplifier'))
    donor = board(eng, creature('Revealed', power=3, toughness=4), 'p2')
    specs = match_clause("until your next turn, ~'s base power becomes twice that card's power and its base toughness becomes twice that card's toughness",
                         reading=ClauseReading(referents=(REVEALED_REFERENT,)))
    assert specs
    ctx = GameContext(eng.state, eng.rules)
    ctx.revealed_card = donor
    effect = EffectRegistry.create(specs[0].type, specs[0].params)
    effect.source = source
    effect.apply(ctx)
    refresh(eng)
    assert (source.power, source.toughness) == (6, 8)
    cast(eng, 'Target creature gets +2/+2 until end of turn.', [donor])
    refresh(eng)
    assert (source.power, source.toughness) == (6, 8)
    assert parse_effect_body("~'s base power becomes twice that card's power and its base toughness becomes twice that card's toughness.") is None


@pytest.mark.parametrize('name', ['Amplifire', 'Awakening of Vitu-Ghazi', 'Chimeric Sphere', 'Quickchange',
    'Blind Seer', 'Vodalian Mystic', 'Dwarven Song', "Shade's Breath", 'Veiled Apparition'])
def test_residue_real_cards_are_modeled(name):
    assert parse_oracle(DB.get_card(name)).modeled


def test_amplifire_reveals_through_noncreatures_and_bottoms_the_entire_batch():
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    eng = game()
    source = board(eng, DB.get_card('Amplifire'))
    p1 = eng.state.player_by_id('p1')
    hit = GameObject(creature('Hit', power=3, toughness=5), owner_id='p1', zone=Zone.LIBRARY)
    miss = GameObject(land('Forest', 'Forest'), owner_id='p1', zone=Zone.LIBRARY)
    untouched = GameObject(creature('Untouched'), owner_id='p1', zone=Zone.LIBRARY)
    p1.library[:] = [untouched, hit, miss]
    from mtg_analyzer.models.game.events import GameEvent, EventType
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', player_id='p1'))
    eng.resolve_until_stable()
    refresh(eng)
    assert (source.power, source.toughness) == (6, 10)
    assert set(o.instance_id for o in p1.library[:2]) == {hit.instance_id, miss.instance_id}
    assert p1.library[-1] is untouched and not p1.exile


def test_awakened_named_land_keeps_its_land_subtype_and_nine_counters():
    eng = game()
    forest = board(eng, land('Forest', 'Forest'))
    cast(eng, DB.get_card('Awakening of Vitu-Ghazi').oracle_text, [forest])
    refresh(eng)
    assert forest.name == 'Vitu-Ghazi' and forest.has_subtype('Forest') and forest.has_subtype('Elemental')
    assert forest.is_land and forest.is_creature and forest.is_legendary
    assert (forest.power, forest.toughness) == (9, 9)


def test_named_equipment_body_replaces_other_card_types_and_subtypes():
    eng = game()
    victim = board(eng, creature('Old', type_line='Enchantment Creature — Human Shrine'))
    cast(eng, "Target permanent becomes a legendary Equipment artifact named Everflame, Heroes' Legacy until end of turn.", [victim])
    refresh(eng)
    assert victim.name == "Everflame, Heroes' Legacy" and victim.has_subtype('Equipment')
    assert not victim.has_subtype('Human') and not victim.has_subtype('Shrine')
    assert victim.is_artifact and not victim.is_creature and not victim.is_enchantment
    end_turn(eng)
    assert victim.name == 'Old' and victim.is_creature and victim.has_subtype('Human')


@pytest.mark.parametrize('text', [
    'Target creature becomes a 3/3 Construct creature with "Destroy the moon." until end of turn.',
    'Target spell becomes an artifact creature until end of turn.',
    'Target creature becomes the color of your choice and loses flying until end of turn.',
    'Target creature becomes a 4/4 Aura creature until end of turn.',
    'Target land becomes an Island with flying until end of turn.',
    'Target land becomes an Island and loses flying until end of turn.',
])
def test_residue_unrecognized_parts_never_disappear(text):
    assert parse_effect_body(text) is None


def test_resolving_mana_value_animation_captures_value_once():
    eng = game()
    rock = board(eng, artifact('Rock', 3))
    cast(eng, 'Target artifact becomes an artifact creature with power and toughness each equal to its mana value until end of turn.', [rock])
    assert (rock.power, rock.toughness) == (3, 3)
    # A later copy changes the printed mana value; the resolving animation has already measured its P/T.
    rock.card = artifact('Copied Rock', 7)
    refresh(eng)
    assert rock.mana_value == 7 and (rock.power, rock.toughness) == (3, 3)


@pytest.mark.parametrize('name', ['Prismatic Lace', 'Prismwake Merrow', 'Quickchange', 'Scuttlemutt', 'Swirling Spriggan'])
def test_color_subset_specs_bind_including_deferred_bodies(name):
    from tests.test_bug12_modeled_cards_bind import _bind_everything
    _bind_everything(DB.get_card(name))
