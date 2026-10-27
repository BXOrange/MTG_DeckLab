"""PAR-209: grammar atoms preserve target, quantity, duration and name semantics."""
import pytest

from mtg_analyzer.game.combat import matches_object_filter
from mtg_analyzer.game.targeting import spell_target_specs, legal_targets
from mtg_analyzer.models.cards.card_query import names_overlap, matches
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.deck_batch import game, card, filler, cast, answer, activate
from tests.test_mec118_opponent_choice import _db_card


@pytest.mark.parametrize('name', [
    'Counterbore', 'Quash', 'Eradicate', 'Splinter', 'Extirpate', 'Surgical Extraction',
    'Abuna Acolyte', 'Alabaster Potion', 'Azorius Ploy',
    'Echoing Calm', 'Echoing Ruin', 'Echoing Courage', 'Echoing Decay', 'Echoing Truth', 'Bile Blight',
])
def test_real_cards_parse(name):
    parsed = parse_oracle(_db_card(name))
    assert parsed.modeled, parsed.unclaimed


@pytest.mark.parametrize('text', [
    'target legendary red creature has base power and toughness 3/4 until your next turn',
    'target artifact creature you control has base power and toughness 2/2 until end of combat',
    'draw a number of cards equal to the number of creatures you control',
    'draw a number of cards equal to your life total',
    'draw x cards, where x is twice the number of artifacts you control',
    'prevent the next x damage that would be dealt to target artifact creature this turn',
])
def test_known_atoms_recombine_without_phrase_rows(text):
    assert parse_effect_body(text)


@pytest.mark.parametrize('text', [
    'target imaginary creature has base power and toughness 3/4 until your next turn',
    'target creature has base power and toughness 3/4 until your third turn',
    'draw a number of cards equal to the number of goats you forgot',
    'draw x cards, where x is the number of imaginary things',
    'prevent the next 3 damage that would be dealt to target imaginary creature this turn',
    'prevent all combat damage target creature deals tomorrow',
    "counter target spell. search its controller's hand for all cards with the same name as that spell and exile them",
])
def test_unknown_atoms_fail_closed(text):
    assert parse_effect_body(text) is None


def test_stacked_adjectives_intersect_in_runtime_filter():
    eng = game()
    good = filler(eng, 'Good', type_line='Legendary Artifact Creature', power=2, toughness=2)
    plain = filler(eng, 'Plain', power=2, toughness=2)
    spec = match_clause('prevent the next 3 damage that would be dealt to target legendary artifact creature this turn')[0]
    filt = spec.params['creature_filter']
    assert matches_object_filter(good, filt, state=eng.state)
    assert not matches_object_filter(plain, filt, state=eng.state)


def test_same_name_relations_include_shared_names_and_exclude_nameless():
    assert names_overlap('Fire // Ice', 'Ice')
    assert names_overlap('Fire', 'Fire // Ice')
    assert not names_overlap('', '')
    assert matches(_db_card('Fire // Ice'), {'same_name_as': 'Ice'})


@pytest.mark.parametrize('spell_name', ['Extirpate', 'Surgical Extraction'])
def test_graveyard_nonbasic_target_restriction(spell_name):
    eng = game()
    basic = filler(eng, 'Basic', type_line='Basic Land — Forest', zone=Zone.GRAVEYARD, player='p2')
    other = filler(eng, 'Other', type_line='Artifact', zone=Zone.GRAVEYARD, player='p2')
    spell = card(eng, spell_name, zone=Zone.HAND)
    spec = spell_target_specs(spell)[0]
    candidates = legal_targets(eng.state, 'p1', spec, source=spell)
    assert other.instance_id in {o['instance_id'] for o in candidates}
    assert basic.instance_id not in {o['instance_id'] for o in candidates}


@pytest.mark.parametrize('spell_name', ['Extirpate', 'Eradicate', 'Splinter'])
def test_all_name_search_forces_public_matches_but_hidden_search_can_decline(spell_name):
    eng = game(library=0)
    zone = Zone.GRAVEYARD if spell_name == 'Extirpate' else Zone.BATTLEFIELD
    kind = 'Artifact Creature'
    seed = filler(eng, 'Shared', type_line=kind, player='p2', power=2, toughness=2, zone=zone)
    public = filler(eng, 'Shared', type_line=kind, player='p2', zone=Zone.GRAVEYARD)
    hidden = filler(eng, 'Shared', type_line=kind, player='p2', zone=Zone.HAND)
    library = filler(eng, 'Shared', type_line=kind, player='p2', zone=Zone.LIBRARY)
    unrelated = filler(eng, 'Other', type_line=kind, player='p2', zone=Zone.GRAVEYARD)
    spell = card(eng, spell_name, zone=Zone.HAND)
    cast(eng, spell, targets=[seed])
    assert public.zone == Zone.GRAVEYARD
    choice = eng.state.pending_choice
    assert choice['kind'] == 'search' and choice['player_id'] == 'p1'
    assert choice['library_owner_id'] == 'p2'
    assert {o['instance_id'] for o in choice['options'] if 'instance_id' in o} == {hidden.instance_id, library.instance_id}
    answer(eng, lambda _: 'decline')
    assert public.zone == Zone.EXILE and seed.zone == Zone.EXILE
    assert hidden.zone == Zone.HAND and library.zone == Zone.LIBRARY
    assert unrelated.zone == Zone.GRAVEYARD


def test_surgical_extraction_may_leave_public_target_in_graveyard():
    eng = game(library=0)
    seed = filler(eng, 'Shared', type_line='Artifact', player='p2', zone=Zone.GRAVEYARD)
    spell = card(eng, 'Surgical Extraction', zone=Zone.HAND)
    cast(eng, spell, targets=[seed])
    assert seed.zone == Zone.GRAVEYARD
    answer(eng, lambda _: 'decline')
    assert seed.zone == Zone.GRAVEYARD


def test_counterbore_counters_then_searches_even_if_countering_is_prevented():
    for uncounterable in (False, True):
        eng = game(library=0)
        victim = filler(eng, 'Shared', type_line='Instant', player='p2', zone=Zone.HAND,
                        oracle_text="This spell can't be countered." if uncounterable else '')
        public = filler(eng, 'Shared', type_line='Sorcery', player='p2', zone=Zone.GRAVEYARD)
        eng.state.current_step = 'main1'
        eng.cast_spell(eng.state.player_by_id('p2'), victim)
        spell = card(eng, 'Counterbore', zone=Zone.HAND)
        cast(eng, spell, targets=[victim])
        answer(eng, lambda _: 'decline')
        assert public.zone == Zone.EXILE
        if not uncounterable:
            assert victim.zone == Zone.EXILE


@pytest.mark.parametrize('spell_name,type_line', [('Echoing Calm', 'Enchantment'), ('Echoing Ruin', 'Artifact'), ('Echoing Truth', 'Creature')])
def test_same_name_group_only_targets_seed_and_applies_to_whole_matching_group(spell_name, type_line):
    eng = game()
    seed = filler(eng, 'Shared', type_line=type_line, player='p2', power=3 if type_line == 'Creature' else None, toughness=3 if type_line == 'Creature' else None)
    sibling = filler(eng, 'Shared', type_line=type_line, power=3 if type_line == 'Creature' else None, toughness=3 if type_line == 'Creature' else None)
    stranger = filler(eng, 'Other', type_line=type_line, power=3 if type_line == 'Creature' else None, toughness=3 if type_line == 'Creature' else None)
    spell = card(eng, spell_name, zone=Zone.HAND)
    assert len(spell_target_specs(spell)) == 1
    cast(eng, spell, targets=[seed])
    expected = Zone.HAND if spell_name == 'Echoing Truth' else Zone.GRAVEYARD
    assert seed.zone == expected and sibling.zone == expected
    assert stranger.zone == Zone.BATTLEFIELD


def test_echoing_courage_applies_pump_once_per_matching_creature():
    eng = game()
    seed = filler(eng, 'Shared', power=3, toughness=3, player='p2')
    sibling = filler(eng, 'Shared', power=3, toughness=3)
    cast(eng, card(eng, 'Echoing Courage', zone=Zone.HAND), targets=[seed])
    eng.recompute_continuous_effects()
    assert seed.power == sibling.power == 5


def test_abuna_acolyte_preserves_artifact_target_filter_and_prevention_bank():
    eng = game()
    protected = filler(eng, 'Artifact', type_line='Artifact Creature', power=5, toughness=5)
    source = card(eng, 'Abuna Acolyte')
    attacker = filler(eng, 'Attacker', player='p2', power=5, toughness=5)
    activate(eng, source, index=1, targets=[protected])
    eng.rules.deal_damage(protected, 3, source=attacker)
    assert protected.damage_marked == 1


def test_azorius_ploy_combat_scope_does_not_prevent_noncombat_damage():
    eng = game()
    protected = filler(eng, 'Protected', power=5, toughness=5)
    attacker = filler(eng, 'Attacker', player='p2', power=5, toughness=5)
    spell = card(eng, 'Azorius Ploy', zone=Zone.HAND)
    cast(eng, spell, targets=[attacker, protected])
    eng.rules.deal_damage(protected, 2, source=attacker, combat=False)
    assert protected.damage_marked == 2
    eng.rules.deal_damage(protected, 2, source=attacker, combat=True)
    assert protected.damage_marked == 2


def test_measured_draw_atom_executes_once_with_live_count():
    eng = game(library=10)
    filler(eng, 'One', power=2, toughness=2)
    filler(eng, 'Two', power=2, toughness=2)
    spell = filler(eng, 'Draw atom', type_line='Sorcery', zone=Zone.HAND,
                   oracle_text='Draw a number of cards equal to the number of creatures you control.')
    cast(eng, spell)
    assert len(eng.state.player_by_id('p1').hand) == 2


def test_base_pt_duration_keeps_filter_and_expires_on_next_own_turn():
    eng = game()
    target = filler(eng, 'Legend', type_line='Legendary Creature', power=2, toughness=2)
    spell = filler(eng, 'Duration atom', type_line='Sorcery', zone=Zone.HAND,
                   oracle_text='Target legendary creature has base power and toughness 5/6 until your next turn.')
    cast(eng, spell, targets=[target])
    eng.recompute_continuous_effects()
    assert (target.power, target.toughness) == (5, 6)
    eng.begin_turn()
    eng.recompute_continuous_effects()
    assert (target.power, target.toughness) == (5, 6)
    eng.begin_turn()
    eng.recompute_continuous_effects()
    assert (target.power, target.toughness) == (2, 2)


def test_source_linked_hand_return_checks_exact_exile_visit():
    eng = game(library=0)
    source = filler(eng, 'Pool', type_line='Artifact',
                    oracle_text='{0}: Return all cards exiled with this artifact to their owners\' hands.')
    linked = filler(eng, 'Linked', type_line='Artifact', player='p2', zone=Zone.EXILE)
    stale = filler(eng, 'Stale', type_line='Artifact', player='p2', zone=Zone.EXILE)
    eng.state.track_exiled_with(source, linked, source.zone_incarnation)
    eng.state.track_exiled_with(source, stale, source.zone_incarnation)
    eng.rules.return_to_hand(stale)
    eng.rules.exile(stale)
    activate(eng, source)
    assert linked.zone == Zone.HAND and linked in eng.state.player_by_id('p2').hand
    assert stale.zone == Zone.EXILE


def test_almost_perfect_sets_attached_base_pt_below_counters():
    eng = game()
    target = filler(eng, 'Host', power=2, toughness=2)
    aura = card(eng, 'Almost Perfect')
    aura.attached_to = target.instance_id
    target.counters['+1/+1'] = 1
    eng.recompute_continuous_effects()
    assert (target.power, target.toughness) == (10, 11)


def test_prevention_source_filter_uses_shared_adjectives_and_caster_controller():
    eng = game()
    protected = filler(eng, 'Protected', power=5, toughness=5, player='p2')
    own_artifact = filler(eng, 'My source', type_line='Legendary Artifact Creature', power=2, toughness=2)
    opposing_artifact = filler(eng, 'Their source', type_line='Legendary Artifact Creature', power=2, toughness=2, player='p2')
    spell = filler(eng, 'Source scope', type_line='Instant', zone=Zone.HAND,
                   oracle_text='Prevent all damage that would be dealt to target creature this turn by legendary artifact creatures you control.')
    assert parse_oracle(spell.card).modeled
    cast(eng, spell, targets=[protected])
    eng.rules.deal_damage(protected, 2, source=own_artifact)
    assert protected.damage_marked == 0
    eng.rules.deal_damage(protected, 2, source=opposing_artifact)
    assert protected.damage_marked == 2


def test_same_name_search_remembers_pre_exile_controller_and_clone_keeps_required_finds():
    from mtg_analyzer.game.game_engine import GameEngine
    eng = game(library=0)
    seed = filler(eng, 'Shared', type_line='Artifact', player='p1')
    seed.controller_id = 'p2'
    public = filler(eng, 'Shared', type_line='Artifact', player='p2', zone=Zone.GRAVEYARD)
    hidden = filler(eng, 'Shared', type_line='Artifact', player='p2', zone=Zone.HAND)
    untouched = filler(eng, 'Shared', type_line='Artifact', player='p1', zone=Zone.HAND)
    cast(eng, card(eng, 'Splinter', zone=Zone.HAND), targets=[seed])
    assert eng.state.pending_choice['library_owner_id'] == 'p2'
    clone = GameEngine(eng.state.clone())
    for engine in (eng, clone):
        answer(engine, lambda _: str(hidden.instance_id))
        assert engine.state.find_object(public.instance_id).zone == Zone.EXILE
        assert engine.state.find_object(hidden.instance_id).zone == Zone.EXILE
        assert engine.state.find_object(untouched.instance_id).zone == Zone.HAND


def test_search_prohibition_checks_searcher_and_still_shuffles_searched_library():
    eng = game(library=0)
    card(eng, 'Stranglehold', player='p2')
    seed = filler(eng, 'Shared', type_line='Artifact', player='p2', zone=Zone.GRAVEYARD)
    cast(eng, card(eng, 'Extirpate', zone=Zone.HAND), targets=[seed])
    assert seed.zone == Zone.GRAVEYARD and eng.state.pending_choice is None


def test_opponents_search_restriction_does_not_block_its_controllers_search_of_opponent_library():
    eng = game(library=0)
    card(eng, 'Stranglehold')
    seed = filler(eng, 'Shared', type_line='Artifact', player='p2', zone=Zone.GRAVEYARD)
    cast(eng, card(eng, 'Extirpate', zone=Zone.HAND), targets=[seed])
    assert eng.state.pending_choice['player_id'] == 'p1'
    answer(eng, lambda _: 'decline')
    assert seed.zone == Zone.EXILE


def test_two_fighter_slots_preserve_each_state_filter():
    eng = game()
    spell = card(eng, 'Dissension in the Ranks', zone=Zone.HAND)
    assert parse_oracle(spell.card).modeled
    specs = spell_target_specs(spell)
    assert len(specs) == 2
    assert all(spec.creature_filter == {'blocking': True} for spec in specs)
    idle = filler(eng, 'Idle', power=5, toughness=5)
    blocker = filler(eng, 'Blocker', power=5, toughness=5)
    attacker = filler(eng, 'Attacker', player='p2', power=1, toughness=1)
    blocker.blocking = attacker.instance_id
    offered = {row['instance_id'] for row in legal_targets(eng.state, 'p1', specs[0], source=spell)}
    assert blocker.instance_id in offered and idle.instance_id not in offered


def test_bomat_courier_returns_linked_cards_after_sacrificing_its_source():
    eng = game(library=0)
    source = card(eng, 'Bomat Courier')
    linked = filler(eng, 'Linked', type_line='Artifact', zone=Zone.EXILE)
    eng.state.track_exiled_with(source, linked, source.zone_incarnation)
    eng.state.player_by_id('p1').mana_pool.add('R', 1)
    activate(eng, source)
    assert source.zone == Zone.GRAVEYARD and linked.zone == Zone.HAND


def test_repeated_adjective_dimension_requires_both_subtypes():
    eng = game()
    both = filler(eng, 'Both', type_line='Creature — Elf Warrior', power=2, toughness=2)
    elf = filler(eng, 'Elf', type_line='Creature — Elf', power=2, toughness=2)
    spec = match_clause('prevent the next 3 damage that would be dealt to target elf warrior creature this turn')[0]
    filt = spec.params['creature_filter']
    assert 'all_of' in filt
    assert matches_object_filter(both, filt, state=eng.state)
    assert not matches_object_filter(elf, filt, state=eng.state)


def test_kindle_binds_arithmetic_and_same_name_graveyard_count_before_damage():
    eng = game()
    card(eng, 'Kindle', zone=Zone.GRAVEYARD, player='p2')
    target = filler(eng, 'Target', power=8, toughness=8, player='p2')
    cast(eng, card(eng, 'Kindle', zone=Zone.HAND), targets=[target])
    assert target.damage_marked == 3


def test_storm_herd_measures_life_total_into_token_count():
    eng = game()
    cast(eng, card(eng, 'Storm Herd', zone=Zone.HAND))
    tokens = [obj for obj in eng.state.battlefield if obj.is_token]
    assert len(tokens) == 20
    assert all(obj.has_subtype('Pegasus') for obj in tokens)


@pytest.mark.parametrize('spell_name', ['Beacon Bolt', 'Serpentine Curve'])
def test_two_zone_quantity_composes_with_damage_or_created_object_counters(spell_name):
    eng = game()
    card(eng, 'Kindle', zone=Zone.GRAVEYARD)
    card(eng, 'Storm Herd', zone=Zone.EXILE)
    target = filler(eng, 'Target', power=8, toughness=8, player='p2')
    spell = card(eng, spell_name, zone=Zone.HAND)
    cast(eng, spell, targets=[target] if spell_name == 'Beacon Bolt' else None)
    if spell_name == 'Beacon Bolt':
        assert target.damage_marked == 2
    else:
        token = next(obj for obj in eng.state.battlefield if obj.is_token)
        assert token.counters['+1/+1'] == 3
        eng.recompute_continuous_effects()
        assert (token.power, token.toughness) == (3, 3)


@pytest.mark.parametrize('name', ['Balduvian Hydra', 'Ethereal Champion', 'Ordruun Commando', 'Revered Elder', 'Ursine Fylgja'])
def test_existing_self_prevention_referents_execute_with_the_general_target_atom(name):
    from tests.support.deck_batch import RICH
    eng = game()
    source = card(eng, name)
    source.counters['+1/+0'] = 1
    source.counters['healing'] = 1
    eng.state.player_by_id('p1').mana_pool.add_many(RICH)
    activate(eng, source)
    eng.rules.deal_damage(source, 2)
    assert source.damage_marked == 1


@pytest.mark.parametrize('name', ['Argivian Blacksmith', 'Eiganjo Castle'])
def test_existing_qualified_target_prevention_executes_with_the_shared_atom(name):
    from tests.support.deck_batch import RICH
    eng = game()
    protected = filler(eng, 'Protected', type_line='Legendary Artifact Creature', power=5, toughness=5)
    source = card(eng, name)
    eng.state.player_by_id('p1').mana_pool.add_many(RICH)
    activate(eng, source, targets=[protected])
    eng.rules.deal_damage(protected, 3)
    assert protected.damage_marked == 1


def test_condemn_keeps_attack_restriction_and_the_following_controller_referent():
    eng = game()
    idle = filler(eng, 'Idle', player='p2', power=3, toughness=4)
    attacking = filler(eng, 'Attacking', player='p2', power=3, toughness=4)
    attacking.attacking = True
    spell = card(eng, 'Condemn', zone=Zone.HAND)
    offered = {row['instance_id'] for row in legal_targets(eng.state, 'p1', spell_target_specs(spell)[0], source=spell)}
    assert attacking.instance_id in offered and idle.instance_id not in offered
    cast(eng, spell, targets=[attacking])
    assert attacking.zone == Zone.LIBRARY
    assert eng.state.player_by_id('p2').life == 24


def test_dissension_fights_two_blockers_with_one_target_for_each():
    eng = game()
    attacker = filler(eng, 'Attacker', power=2, toughness=2)
    one = filler(eng, 'One', power=3, toughness=3)
    two = filler(eng, 'Two', power=3, toughness=3, player='p2')
    one.blocking = two.blocking = attacker.instance_id
    cast(eng, card(eng, 'Dissension in the Ranks', zone=Zone.HAND), targets=[one, two])
    assert one.zone == two.zone == Zone.GRAVEYARD
