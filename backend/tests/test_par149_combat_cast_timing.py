"""PAR-149: casting restrictions remain mandatory under free/alternate casts."""
import pytest
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.spec import AbilitySpec, SpecValidationError


def game(clause):
    engine = GameEngine.new_game([('p1', 'A', []), ('p2', 'B', [])], starting_hand=0)
    player = engine.state.active_player
    card = Card(id='timing', name='Timing Spell', type_line='Instant', is_instant=True,
                mana_cost_string='{U}', oracle_text=clause + '\nDraw a card.')
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    obj = GameObject(card, player.id, Zone.HAND)
    player.add_to_zone(obj, Zone.HAND)
    bind_from_catalogue(obj)
    return engine, player, obj


@pytest.mark.parametrize('clause,allowed', [
    ('Cast this spell only during combat.', {'begin_combat','declare_attackers','declare_blockers','combat_damage','end_combat'}),
    ('Cast this spell only during combat before blockers are declared.', {'begin_combat','declare_attackers'}),
    ('Cast this spell only during combat after blockers are declared.', {'declare_blockers','combat_damage','end_combat'}),
    ('Cast this spell only during the declare blockers step.', {'declare_blockers'}),
    ('Cast this spell only before blockers are declared.', {'upkeep','draw','main1','begin_combat','declare_attackers'}),
    ('Cast this spell only before combat or during combat before blockers are declared.', {'upkeep','draw','main1','begin_combat','declare_attackers'}),
])
@pytest.mark.parametrize('step', ['upkeep','draw','main1','begin_combat','declare_attackers','declare_blockers','combat_damage','end_combat','main2','end'])
def test_every_timing_boundary_and_free_cast_still_require_the_window(clause, allowed, step):
    engine, player, obj = game(clause)
    engine.state.current_step = step
    engine.state.current_phase = 'combat' if step in {'begin_combat','declare_attackers','declare_blockers','combat_damage','end_combat'} else 'precombat_main'
    player.mana_pool.add('U', 1)
    assert engine.can_cast(player, obj) == (step in allowed)
    engine.state.free_cast_instance_ids.add(obj.instance_id)
    engine.state.free_cast_ignore_timing_instance_ids.add(obj.instance_id)
    assert engine.can_cast(player, obj, free=True) == (step in allowed)
    if step not in allowed:
        with pytest.raises(ValueError):
            engine.cast_spell(player, obj, free=True)
        assert obj in player.hand and not engine.state.stack


@pytest.mark.parametrize('turn,own', [('your', True), ("an opponent's",False)])
@pytest.mark.parametrize('step', ['begin_combat','declare_attackers','declare_blockers','combat_damage','end_combat'])
def test_turn_owner_qualifier_is_preserved(turn, own, step):
    engine, player, obj = game(f'Cast this spell only during combat on {turn} turn.')
    engine.state.current_phase = 'combat';engine.state.current_step = step
    player.mana_pool.add('U', 1)
    assert engine.can_cast(player, obj) == own
    engine.state.active_player_index = 1
    assert engine.can_cast(player, obj) == (not own)


def test_timing_permission_does_not_waive_mana_or_targets():
    engine, player, obj = game('Cast this spell only during combat.')
    engine.state.current_phase='combat';engine.state.current_step='declare_attackers'
    assert not engine.can_cast(player,obj)
    player.mana_pool.add('U',1)
    assert engine.can_cast(player,obj)
    targeted = Card(id='targeted',name='Timing Bounce',is_instant=True,type_line='Instant',mana_cost_string='{U}',
                    oracle_text="Cast this spell only during combat.\nReturn target creature to its owner's hand.")
    spell=GameObject(targeted,player.id,Zone.HAND);player.add_to_zone(spell,Zone.HAND);bind_from_catalogue(spell)
    with pytest.raises(ValueError):
        engine.cast_spell(player,spell,targets=[])
    assert spell in player.hand


@pytest.mark.parametrize('suffix', ['during combat if you control a Dragon', 'during the declare blockers step after blockers are declared', 'during combat on each turn'])
def test_unsupported_qualification_stays_unmodeled(suffix):
    card=Card(id='negative',name='Negative',type_line='Instant',is_instant=True,oracle_text='Cast this spell only '+suffix+'.\nDraw a card.')
    assert not parse_oracle(card).modeled


def test_timing_metadata_rejects_unknown_fields_and_opposing_turns():
    for restriction in [{'phase':'combat','ignore_cost':True},{'phase':'combat','your_turn':True,'opponents_turn':True}]:
        with pytest.raises(SpecValidationError):
            AbilitySpec('spell_effect',effects=[],cast_timing_restriction=restriction).validate()


def test_live_session_cannot_cast_after_blockers_until_defender_finishes_declaration():
    from mtg_analyzer.services.game_session import GameSession, GameActionError
    engine, player, spell = game('Cast this spell only during combat after blockers are declared.')
    attacker=GameObject(Card(id='attacker',name='Attacker',type_line='Creature',is_creature=True,power=2,toughness=2),player.id,Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(attacker)
    engine.start()
    while engine.state.current_step != 'declare_attackers':
        engine.advance_step()
    attacker.summoning_sick=False
    engine.declare_attackers(player,[attacker])
    engine.advance_step()
    player.mana_pool.add('U',1)
    session=GameSession(engine,mode='multiplayer')
    assert not engine.can_cast(player,spell)
    with pytest.raises(GameActionError):
        session.apply_action({'type':'cast_spell','instance_id':spell.instance_id},actor_id=player.id)
    engine=session.engine
    engine.declare_blockers(engine.state.players[1],[])
    engine.state.priority_player_index=0
    session.apply_action({'type':'cast_spell','instance_id':spell.instance_id},actor_id=player.id)
    assert engine.state.stack


def test_unqualified_before_blockers_does_not_reopen_in_an_extra_combat():
    engine,player,spell=game('Cast this spell only before blockers are declared.')
    engine.start()
    while engine.state.current_step != 'declare_attackers':engine.advance_step()
    player.mana_pool.add('U',1)
    assert engine.can_cast(player,spell)
    engine.insert_additional_combat_phase()
    engine.advance_step()
    assert not engine.can_cast(player,spell)
    while engine.state.current_step != 'begin_combat':engine.advance_step()
    player.mana_pool.add('U',1)
    assert not engine.can_cast(player,spell)


def test_skipped_first_combat_closes_unqualified_window_after_main_phase():
    from mtg_analyzer.game.effects.core import StaticEffect
    engine,player,spell=game('Cast this spell only before blockers are declared.')
    engine.start()
    while engine.state.current_step != 'main1':engine.advance_step()
    player.mana_pool.add('U',1)
    assert engine.can_cast(player,spell)
    player.player_effects.append(StaticEffect('skip_phase', {'phase':'combat'}, duration='once'))
    engine.advance_step()
    player.mana_pool.add('U',1)
    assert not engine.can_cast(player,spell)


def test_skipped_blockers_step_does_not_open_after_blockers_window():
    from mtg_analyzer.game.effects.core import StaticEffect
    engine,player,spell=game('Cast this spell only during combat after blockers are declared.')
    engine.start()
    while engine.state.current_step != 'declare_attackers':engine.advance_step()
    player.player_effects.append(StaticEffect('skip_phase', {'phase':'declare_blockers'}, duration='once'))
    engine.advance_step()
    engine.advance_step()
    player.mana_pool.add('U',1)
    assert engine.state.current_step == 'combat_damage'
    assert not engine.can_cast(player,spell)


@pytest.mark.parametrize('name', ['Aleatory','Angelic Favor','Cauldron Dance','Chaotic Strike','Gorilla War Cry','Panic','Savage Beating','Surprise Deployment'])
def test_real_solo_cards_are_fully_modeled_with_a_casting_restriction(name):
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
    if not DEFAULT_DB_PATH.exists():pytest.skip('card cache unavailable')
    card=CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:pytest.skip('card not cached')
    result=parse_oracle(card)
    assert result.modeled,result.unclaimed
    assert any(spec.cast_timing_restriction for spec in result.specs)


@pytest.mark.parametrize('step,allowed', [('main1', False), ('declare_attackers', True), ('declare_blockers', False)])
def test_flashback_retains_the_spell_local_combat_restriction(step,allowed):
    engine,player,spell=game('Cast this spell only during combat before blockers are declared.')
    spell.card.oracle_text += '\nFlashback {U}'
    spell.card.keywords = ['Flashback']
    player.remove_from_zone(spell,Zone.HAND)
    player.add_to_zone(spell,Zone.GRAVEYARD)
    bind_from_catalogue(spell)
    engine.state.current_phase='combat' if step != 'main1' else 'precombat_main'
    engine.state.current_step=step
    player.mana_pool.add('U',1)
    assert engine.can_cast(player,spell) == allowed
