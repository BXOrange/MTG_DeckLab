"""PAR-265: copy exceptions, recipients, target counts and entry choices."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game import combat
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import game, on_battlefield, cast, advance_to

CARDS = ['Blastoneuron', 'Dominion Infiltration', 'Fractured Identity', 'Mirror Universe Intrusion',
         'Reg Barclay, Fidgety Fantasist', 'Tasha Yar, Out of Time', 'Dominion Saboteur',
         'Ezri Dax, Newly Joined', 'Voq, Torchbearer']


@pytest.mark.parametrize('name', CARDS)
def test_real_cards_fully_modeled(name):
    card = get_cached_card(name)
    assert card is not None
    result = parse_oracle(card)
    assert result.modeled and result.specs, result.unclaimed


def put(eng, name, pid='p1', zone=Zone.GRAVEYARD):
    card = get_cached_card(name)
    assert card is not None
    obj = GameObject(card, pid, zone)
    bind_from_catalogue(obj)
    eng.state.player_by_id(pid).add_to_zone(obj, zone)
    return obj


def tokens(eng, pid='p1'):
    return [o for o in eng.state.battlefield if o.is_token and o.controller_id == pid]


def finish_choices(eng, target):
    choice = eng.state.pending_choice
    assert choice
    option = next(o for o in choice['options'] if o.get('instance_id') == target.instance_id)
    eng.resolve_pending_choice(option['id'])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()


def test_blastoneuron_copies_exiled_card_grants_haste_and_sacrifices_token_only():
    eng, player, opponent = game('Blastoneuron', via_steps=True)
    card = put(eng, 'Grizzly Bears')
    high = put(eng, 'Colossal Dreadmaw')
    life = player.life
    cast(eng, player, player.hand[0])
    choice = eng.state.pending_choice
    assert choice and any(o.get('instance_id') == card.instance_id for o in choice['options'])
    assert not any(o.get('instance_id') == high.instance_id for o in choice['options'])
    finish_choices(eng, card)
    token, = tokens(eng)
    assert token.name == 'Grizzly Bears' and card.zone == Zone.EXILE
    assert combat.has(token, 'haste')
    assert player.life == life + 1 and opponent.life == 19
    advance_to(eng, 'end')
    eng.resolve_until_stable()
    assert token not in eng.state.battlefield
    assert card in player.exile and high in player.graveyard


def test_dominion_infiltration_exact_x_copies_all_targets_and_cleanup_survives_clone():
    eng, player, _ = game('Dominion Infiltration', via_steps=True)
    a = on_battlefield(eng, 'p2', 'Grizzly Bears')
    b = on_battlefield(eng, 'p2', 'Llanowar Elves')
    spell = player.hand[0]
    cast(eng, player, spell, x=2, targets=[a, b])
    made = tokens(eng)
    assert {o.name for o in made} == {a.name, b.name}
    assert all(combat.has(o, 'haste') and combat.has(o, 'changeling') for o in made)
    assert all(o.has_subtype('Wizard') and o.has_subtype('Trill') for o in made)
    copied = eng.rules.copy_permanent('p1', made[0])[0]
    assert combat.has(copied, 'changeling')
    assert not combat.has(copied, 'haste')  # "gain haste" is not a copy exception
    restored = GameEngine(eng.state.clone())
    advance_to(restored, 'end')
    restored.resolve_until_stable()
    assert {o.instance_id for o in tokens(restored)} == {copied.instance_id}


def test_dominion_infiltration_rejects_fewer_than_x_targets():
    eng, player, _ = game('Dominion Infiltration')
    a = on_battlefield(eng, 'p2', 'Grizzly Bears')
    player.mana_pool.add_many({'C': 20, 'U': 10})
    with pytest.raises(ValueError):
        eng.cast_spell(player, player.hand[0], x=2, targets=[a])


@pytest.mark.parametrize('kicked', [0, 1])
def test_mirror_universe_uses_only_the_chosen_branch_targets(kicked):
    eng, player, other = game('Mirror Universe Intrusion')
    a = on_battlefield(eng, 'p2', 'Grizzly Bears')
    b = on_battlefield(eng, 'p2', 'Llanowar Elves')
    cast(eng, player, player.hand[0], kicked=kicked, targets=[other if kicked else a])
    made = tokens(eng)
    assert len(made) == (2 if kicked else 1)
    assert all(combat.has(o, 'menace') for o in made)
    assert combat.has(eng.rules.copy_permanent('p1', made[0])[0], 'menace')


def test_fractured_identity_uses_departing_copy_values_and_excludes_actual_controller():
    eng, player, other = game('Fractured Identity')
    original = on_battlefield(eng, 'p1', 'Grizzly Bears')
    original.controller_id = 'p2'
    original.counters['+1/+1'] = 3
    cast(eng, player, player.hand[0], targets=[original])
    token, = tokens(eng)
    assert token.name == 'Grizzly Bears' and not token.counters
    assert not tokens(eng, 'p2')
    assert original in player.exile


def test_reg_barclay_copy_keeps_copiable_exceptions_and_only_original_expires():
    eng, player, _ = game(via_steps=True)
    source = on_battlefield(eng, 'p1', 'Reg Barclay, Fidgety Fantasist')
    original = on_battlefield(eng, 'p1', 'Isamaru, Hound of Konda')
    eng.rules.draw(player, 2)
    eng.resolve_until_stable()
    finish_choices(eng, original)
    token, = tokens(eng)
    assert not token.card.is_legendary and token.is_artifact and token.has_subtype('Illusion')
    assert combat.has(token, 'haste')
    other = eng.rules.copy_permanent('p1', token)[0]
    assert not other.card.is_legendary and other.is_artifact and other.has_subtype('Illusion')
    assert combat.has(other, 'haste')
    advance_to(eng, 'end')
    eng.resolve_until_stable()
    assert token not in eng.state.battlefield and other in eng.state.battlefield
    assert original in eng.state.battlefield and source in eng.state.battlefield


def test_tasha_graveyard_cost_and_delayed_sacrifice():
    eng, player, _ = game(via_steps=True)
    source = put(eng, 'Tasha Yar, Out of Time')
    player.mana_pool.add_many({'C': 2, 'R': 1})
    eng.activate_ability(player, source)
    eng.resolve_until_stable()
    token, = tokens(eng)
    assert source in player.exile and token.name == source.name
    assert combat.has(token, 'haste')
    advance_to(eng, 'end')
    eng.resolve_until_stable()
    assert token not in eng.state.battlefield and source in player.exile


def test_dominion_saboteur_copies_counter_kinds_as_entry_counters():
    eng, player, _ = game('Dominion Saboteur')
    original = on_battlefield(eng, 'p2', 'Grizzly Bears')
    original.counters.update({'+1/+1': 2, 'shield': 1})
    spell = player.hand[0]
    cast(eng, player, spell)
    restored = GameEngine(eng.state.clone())
    finish_choices(restored, restored.state.find_object(original.instance_id))
    copied = restored.state.find_object(spell.instance_id)
    assert copied.name == original.name and copied.counters == original.counters
    assert spell.name == 'Dominion Saboteur'


def test_ezri_pool_requires_the_exact_graveyard_visit_and_keeps_name_and_legendary_trill():
    eng, player, _ = game('Ezri Dax, Newly Joined')
    old = put(eng, 'Llanowar Elves')
    died = on_battlefield(eng, 'p1', 'Grizzly Bears')
    eng.rules.destroy(died)
    opponent = on_battlefield(eng, 'p2', 'Grizzly Bears')
    eng.rules.destroy(opponent)
    spell = player.hand[0]
    cast(eng, player, spell)
    choice = eng.state.pending_choice
    ids = {o.get('instance_id') for o in choice['options']}
    assert died.instance_id in ids and old.instance_id not in ids and opponent.instance_id not in ids
    finish_choices(eng, died)
    assert spell.name == 'Ezri Dax, Newly Joined' and spell.card.is_legendary
    assert spell.has_subtype('Trill') and spell.power == 2 and spell.toughness == 2
    copied = eng.rules.copy_permanent('p2', spell)[0]
    assert copied.name == spell.name and copied.card.is_legendary and copied.has_subtype('Trill')


def test_voqs_opponents_graveyard_pool_and_copiable_menace():
    eng, player, _ = game('Voq, Torchbearer')
    original = put(eng, 'Grizzly Bears', 'p2')
    spell = player.hand[0]
    cast(eng, player, spell)
    finish_choices(eng, original)
    assert spell.has_subtype('Klingon') and spell.has_subtype('Spy')
    assert combat.has(spell, 'menace')
    assert combat.has(eng.rules.copy_permanent('p2', spell)[0], 'menace')


@pytest.mark.parametrize('text', [
    "create a token that's a copy of target creature, except it has frobnication",
    "create a token that's a copy of this card, except it does not exist",
    "choose x target creatures your opponents control. for each of them, create a token that's a copy of that creature, except it has nonsense",
])
def test_unknown_exception_stays_unclaimed(text):
    assert parse_effect_body(text) is None


def test_dominion_x_zero_has_no_targets_or_tokens():
    eng, player, _ = game('Dominion Infiltration')
    cast(eng, player, player.hand[0], x=0)
    assert not tokens(eng) and eng.state.pending_choice is None


def test_dominion_partially_illegal_targets_copy_only_survivors():
    eng, player, _ = game('Dominion Infiltration')
    a = on_battlefield(eng, 'p2', 'Grizzly Bears')
    b = on_battlefield(eng, 'p2', 'Llanowar Elves')
    player.mana_pool.add_many({'C': 20, 'W': 10, 'U': 10, 'B': 10, 'R': 10, 'G': 10})
    eng.cast_spell(player, player.hand[0], x=2, targets=[a, b])
    eng.rules.exile(a)
    eng.resolve_until_stable()
    assert [o.name for o in tokens(eng)] == [b.name]


def test_dominion_copied_counters_are_doubled_at_entry():
    eng, player, _ = game('Dominion Saboteur')
    on_battlefield(eng, 'p1', 'Doubling Season')
    original = on_battlefield(eng, 'p2', 'Isamaru, Hound of Konda')
    original.counters.update({'+1/+1': 2, 'shield': 1})
    spell = player.hand[0]
    cast(eng, player, spell)
    finish_choices(eng, original)
    assert spell.counters == {'+1/+1': 4, 'shield': 2}
    assert not spell.card.is_legendary


def test_ezri_ignores_an_earlier_graveyard_visit_of_the_same_card():
    eng, player, _ = game('Ezri Dax, Newly Joined')
    original = on_battlefield(eng, 'p1', 'Grizzly Bears')
    eng.rules.destroy(original)
    eng.rules.return_to_hand(original)
    eng.rules.discard_specific(original)
    spell = player.hand[0]
    cast(eng, player, spell)
    assert eng.state.pending_choice is None
    assert spell.name == 'Ezri Dax, Newly Joined'


def test_entry_choice_can_copy_shroud_and_can_decline():
    eng, player, _ = game('Dominion Saboteur')
    original = on_battlefield(eng, 'p2', 'Grizzly Bears')
    original.temp_keywords.add('shroud')
    spell = player.hand[0]
    cast(eng, player, spell)
    assert any(o.get('instance_id') == original.instance_id for o in eng.state.pending_choice['options'])
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    assert spell.name == 'Dominion Saboteur' and not spell.counters


def test_fractured_identity_copies_departing_copiable_face_before_zone_reset():
    from mtg_analyzer.game.copy_mechanics import become_copy

    eng, player, _ = game('Fractured Identity')
    bear = on_battlefield(eng, 'p1', 'Grizzly Bears')
    clone = on_battlefield(eng, 'p2', 'Clone')
    become_copy(clone, bear, add_keywords=['Menace'])
    cast(eng, player, player.hand[0], targets=[clone])
    assert clone.zone == Zone.EXILE
    token, = tokens(eng)
    assert token.name == 'Grizzly Bears' and combat.has(token, 'menace')


def test_fractured_identity_multiplayer_creators_include_caster_and_other_players():
    eng = GameEngine.new_game([('p1', 'A', []), ('p2', 'B', []), ('p3', 'C', [])], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = 'main1'
    player = eng.state.player_by_id('p1')
    spell = put(eng, 'Fractured Identity', zone=Zone.HAND)
    original = on_battlefield(eng, 'p2', 'Grizzly Bears')
    cast(eng, player, spell, targets=[original])
    assert len(tokens(eng, 'p1')) == len(tokens(eng, 'p3')) == 1
    assert not tokens(eng, 'p2')


def test_reg_token_replacement_order_retains_created_sink_and_delayed_exile_after_clone():
    eng, player, _ = game(via_steps=True)
    on_battlefield(eng, 'p1', 'Reg Barclay, Fidgety Fantasist')
    original = on_battlefield(eng, 'p1', 'Grizzly Bears')
    on_battlefield(eng, 'p1', 'Doubling Season')
    on_battlefield(eng, 'p1', 'Parallel Lives')
    eng.rules.draw(player, 2)
    eng.resolve_until_stable()
    finish_choices(eng, original)
    assert eng.state.pending_choice['kind'] == 'replacement_order'
    restored = GameEngine(eng.state.clone())
    restored.resolve_pending_choice('0')
    restored.resolve_until_stable()
    assert len(tokens(restored)) == 4
    advance_to(restored, 'end')
    restored.resolve_until_stable()
    assert not tokens(restored)


def test_dominion_multiple_token_entry_choices_resume_without_losing_delayed_tail():
    eng, player, _ = game('Dominion Infiltration', via_steps=True)
    original = on_battlefield(eng, 'p2', 'Clone')
    original.counters['+1/+1'] = 1
    other = on_battlefield(eng, 'p2', 'Grizzly Bears')
    cast(eng, player, player.hand[0], x=2, targets=[original, other])
    assert eng.state.pending_choice['kind'] == 'enter_as_copy'
    restored = GameEngine(eng.state.clone())
    finish_choices(restored, restored.state.find_object(other.instance_id))
    assert len(tokens(restored)) == 2
    assert all(combat.has(o, 'haste') for o in tokens(restored))
    advance_to(restored, 'end')
    restored.resolve_until_stable()
    assert not tokens(restored)


def test_incidental_astral_dragon_grants_real_creature_type_not_words_as_subtypes():
    eng, player, _ = game('Astral Dragon')
    land = on_battlefield(eng, 'p1', 'Forest')
    cast(eng, player, player.hand[0])
    finish_choices(eng, land)
    assert len(tokens(eng)) == 2
    for token in tokens(eng):
        assert token.is_creature and token.power == token.toughness == 3
        assert token.has_subtype('Dragon') and combat.has(token, 'flying')
        assert 'addition' not in token.card.type_line.lower()


def test_incidental_impossible_man_keeps_its_name():
    eng, player, _ = game()
    source = on_battlefield(eng, 'p1', 'Impossible Man')
    other = on_battlefield(eng, 'p2', 'Grizzly Bears')
    player.mana_pool.add_many({'C': 2, 'U': 1})
    eng.activate_ability(player, source, targets=[other])
    eng.resolve_until_stable()
    assert source.name == 'Impossible Man' and source.power == source.toughness == 2


def test_incidental_orthion_plural_grant_and_sacrifice_cover_all_copies():
    eng, player, _ = game(via_steps=True)
    source = on_battlefield(eng, 'p1', 'Orthion, Hero of Lavabrink')
    original = on_battlefield(eng, 'p1', 'Grizzly Bears')
    player.mana_pool.add_many({'C': 6, 'R': 3})
    eng.activate_ability(player, source, ability_index=1, targets=[original])
    eng.resolve_until_stable()
    assert len(tokens(eng)) == 5
    assert all(combat.has(o, 'haste') for o in tokens(eng))
    advance_to(eng, 'end')
    eng.resolve_until_stable()
    assert not tokens(eng) and original in eng.state.battlefield


def test_x_target_count_is_not_limited_by_the_static_any_number_sentinel():
    eng, player, _ = game('Dominion Infiltration')
    targets = [on_battlefield(eng, 'p2', 'Grizzly Bears') for _ in range(11)]
    cast(eng, player, player.hand[0], x=len(targets), targets=targets)
    assert len(tokens(eng)) == len(targets)


def test_targeted_controller_count_preserves_announcement_for_independent_body():
    specs = parse_effect_body('for each creature target opponent controls, draw a card')
    assert specs is not None
    assert specs[0].type == 'choose_targets' and specs[0].params['kinds'] == ['opponent']
    assert specs[1].type == 'for_each'


def test_incidental_echoing_deeps_graveyard_land_copy_enters_tapped_after_clone():
    eng, player, _ = game('Echoing Deeps')
    original = put(eng, 'Forest', 'p2')
    battlefield_land = on_battlefield(eng, 'p1', 'Mountain')
    source = player.hand[0]
    eng.play_land(player, source)
    options = eng.state.pending_choice['options']
    assert any(o.get('instance_id') == original.instance_id for o in options)
    assert not any(o.get('instance_id') == battlefield_land.instance_id for o in options)
    restored = GameEngine(eng.state.clone())
    finish_choices(restored, restored.state.find_object(original.instance_id))
    copied = restored.state.find_object(source.instance_id)
    assert copied.name == 'Forest' and copied.has_subtype('Cave') and copied.tapped
