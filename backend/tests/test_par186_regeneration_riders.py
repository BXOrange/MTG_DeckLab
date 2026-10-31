"""PAR-186: destruction-scoped regeneration denial with bound object referents."""
import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.effects.registry import EffectRegistry
from mtg_analyzer.game.targeting import legal_targets, spell_target_specs
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.test_mec118_opponent_choice import _engine, _put, _db_card, _vanilla


@pytest.mark.parametrize('name', ['Dripping Dead', 'Mephitic Ooze', 'Spinal Graft', 'Fatal Mutation', 'Befoul', 'Crumble', 'Detonate'])
def test_real_cards_modeled(name):
    assert parse_oracle(_db_card(name)).modeled


@pytest.mark.parametrize('text', [
    "destroy it. it can't be regenerated",
    "destroy that creature. it can't be regenerated",
    "draw a card. it can't be regenerated",
    "destroy target artifact. draw a card. it can't be regenerated",
    "destroy target creature. it can't be regenerated this turn",
    'target creature gains "destroy it. it can\'t be regenerated"',
])
def test_unbound_and_independent_riders_fail_closed(text):
    # A real turn-long ban is intentionally distinct and may parse through its existing effect.
    specs = parse_effect_body(text)
    assert specs is None or all(not e.params.get('can_be_regenerated') is False for e in specs)


def test_plural_rider_only_changes_immediate_sentence():
    specs = parse_effect_body("destroy target artifact. destroy target creature. they can't be regenerated")
    assert specs[0].params.get('can_be_regenerated', True) is True
    assert specs[1].params['can_be_regenerated'] is False
    specs = parse_effect_body("destroy target artifact and target creature. they can't be regenerated")
    assert len(specs) == 2 and all(e.params['can_be_regenerated'] is False for e in specs)


def _cast(eng, name, targets, x=0):
    spell = _put(eng, _db_card(name), 'p1', Zone.HAND)
    eng.state.active_player.mana_pool.add_many({c: 30 for c in 'WUBRG'})
    eng.cast_spell(eng.state.active_player, spell, targets=targets, x=x)
    eng.resolve_until_stable()
    return spell


@pytest.mark.parametrize('indestructible', [False, True])
def test_crumble_real_cast_denies_regen_and_gives_controller_mana_value(indestructible):
    eng = _engine()
    target = _put(eng, Card(id='a', name='Artifact', type_line='Artifact', 
                            converted_mana_cost=4, oracle_text='Indestructible' if indestructible else ''), 'p2')
    eng.rules.regenerate(target)
    _cast(eng, 'Crumble', [target])
    assert (target.zone == Zone.BATTLEFIELD) is indestructible
    assert eng.state.players[1].life == 24
    assert target.temp_cant_be_regenerated is False


def test_befoul_target_union_preserves_black_lands():
    eng = _engine()
    spell = _put(eng, _db_card('Befoul'), 'p1', Zone.HAND)
    black = _put(eng, Card(id='b', name='Black', type_line='Creature', is_creature=True,
                          color_identity={'B'},  power=3, toughness=3), 'p2')
    blackland = _put(eng, Card(id='l', name='Blackland', type_line='Land Creature', is_creature=True,
                              is_land=True, color_identity={'B'},  power=3, toughness=3), 'p2')
    bear = _put(eng, _vanilla('Bear'), 'p2')
    spec = spell_target_specs(spell)[0]
    offered = {t['instance_id'] for t in legal_targets(eng.state, 'p1', spec, source=spell)}
    assert black.instance_id not in offered
    assert {blackland.instance_id, bear.instance_id} <= offered
    eng.rules.regenerate(bear)
    _cast(eng, 'Befoul', [bear])
    assert bear.zone == Zone.GRAVEYARD


def test_detonate_exact_x_announcement_and_damage_after_destruction():
    eng = _engine()
    target = _put(eng, Card(id='a', name='Artifact', type_line='Artifact',  converted_mana_cost=3), 'p2')
    eng.rules.regenerate(target)
    _cast(eng, 'Detonate', [target], x=3)
    assert target.zone == Zone.GRAVEYARD
    assert eng.state.players[1].life == 17


@pytest.mark.parametrize('blink', [False, True])
def test_dripping_dead_damages_recipient_then_trigger_destroys_that_visit(blink):
    eng = _engine()
    source = _put(eng, _db_card('Dripping Dead'), 'p1')
    target = _put(eng, _vanilla('Victim', toughness=10), 'p2')
    eng.rules.regenerate(target)
    eng.rules.deal_damage(target, 1, source=source, combat=True)
    if blink:
        eng.rules.exile(target)
        eng.state.add_to_battlefield(target)
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD
    assert (target.zone == Zone.BATTLEFIELD) is blink


@pytest.mark.parametrize('move_aura', [False, True])
def test_spinal_graft_uses_firing_host_even_if_aura_moves(move_aura):
    eng = _engine()
    old = _put(eng, _vanilla('Old', toughness=10), 'p2')
    new = _put(eng, _vanilla('New', toughness=10), 'p2')
    aura = _put(eng, _db_card('Spinal Graft'), 'p1')
    aura.attached_to = old.instance_id
    continuous.recompute(eng.state)
    eng.rules.regenerate(old)
    spell = _put(eng, Card(id='tap', name='Tap', type_line='Instant', is_instant=True,
                          mana_cost={'U': 1}, oracle_text='Tap target creature.'), 'p1', Zone.HAND)
    eng.state.active_player.mana_pool.add('U', 1)
    eng.cast_spell(eng.state.active_player, spell, targets=[old])
    if move_aura:
        aura.attached_to = new.instance_id
    eng.resolve_until_stable()
    assert old.zone == Zone.GRAVEYARD
    assert new.zone == Zone.BATTLEFIELD

@pytest.mark.parametrize('artifact', [True, False])
def test_topple_condition_survives_previous_destroy_composition(artifact):
    eng = _engine()
    target = _put(eng, Card(id='target', name='Target', type_line='Artifact' if artifact else 'Creature',
                           is_creature=not artifact, power=None if artifact else 2,
                           toughness=None if artifact else 2), 'p2')
    _cast(eng, 'Topple the Statue', [target])
    assert (target.zone == Zone.GRAVEYARD) is artifact
    if not artifact:
        assert target.tapped


@pytest.mark.parametrize('name,expected_life', [('Crumble', 24), ('Detonate', 16)])
def test_controller_tail_uses_destroyed_stolen_artifacts_last_controller(name, expected_life):
    eng = _engine()
    target = _put(eng, Card(id='a', name='Stolen', type_line='Artifact', converted_mana_cost=4), 'p1')
    target.controller_id = 'p2'
    _cast(eng, name, [target], x=4 if name == 'Detonate' else 0)
    assert target.zone == Zone.GRAVEYARD
    assert eng.state.players[1].life == expected_life
    assert eng.state.players[0].life == 20


@pytest.mark.parametrize('name', ['Blight', 'Fatal Mutation', 'Mire Blight'])
def test_attached_triggers_retain_firing_host_after_detachment(name):
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng = _engine()
    host = _put(eng, _vanilla('Host'), 'p2')
    other = _put(eng, _vanilla('Other'), 'p2')
    aura = _put(eng, _db_card(name), 'p1')
    aura.attached_to = host.instance_id
    if name == 'Mire Blight':
        eng.rules.deal_damage(host, 1)
    elif name == 'Blight':
        eng.rules.set_tapped(host)
    else:
        eng.state.fire_event(GameEvent(EventType.TURNED_FACE_UP, instance_id=host.instance_id,
                                       instance_zone_incarnation=host.zone_incarnation))
    aura.attached_to = other.instance_id
    eng.resolve_until_stable()
    assert host.zone == Zone.GRAVEYARD
    assert other.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize('clone', [False, True])
def test_recipient_trigger_clone_retains_exact_zone_visit(clone):
    from mtg_analyzer.game.game_engine import GameEngine
    eng = _engine()
    source = _put(eng, _db_card('Dripping Dead'), 'p1')
    victim = _put(eng, _vanilla('Victim', toughness=10), 'p2')
    eng.rules.deal_damage(victim, 1, source=source, combat=True)
    eng.rules.put_triggers_on_stack()
    if clone:
        eng = GameEngine(eng.state.clone())
        victim = eng.state.find_object(victim.instance_id)
    eng.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD


def test_previous_destroy_without_a_pick_never_falls_back_to_source():
    from mtg_analyzer.game.effects.life_sacrifice import DestroyEffect
    eng = _engine()
    source = _put(eng, _vanilla('Source'), 'p1')
    context = GameContext(state=eng.state, engine=eng.rules)
    DestroyEffect(source=source, previous_subject=True, can_be_regenerated=False).apply(context)
    assert source.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize('name,color', [('Phyrexian Slayer','W'), ('Phyrexian Reaper','G')])
def test_block_relation_riders_destroy_filtered_opposing_creature(name, color):
    eng = _engine()
    source = _put(eng, _db_card(name), 'p1')
    victim = _put(eng, Card(id='v',name='Victim',type_line='Creature', is_creature=True,
                            color_identity={color}, power=1,toughness=10,
                            oracle_text='Flying'), 'p2')
    source.summoning_sick = False
    eng.rules.regenerate(victim)
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.active_player, [source])
    eng.state.current_step = 'declare_blockers'
    eng.declare_blockers(eng.state.players[1], [{'blocker':victim,'attacker':source}])
    eng.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD
    assert source.zone == Zone.BATTLEFIELD


def test_blocker_color_is_captured_when_the_trigger_fires():
    eng = _engine()
    source = _put(eng, _db_card('Phyrexian Slayer'), 'p1')
    white = _put(eng, Card(id='w',name='White',type_line='Creature',is_creature=True,
                           color_identity={'W'},power=1,toughness=10,oracle_text='Flying'), 'p2')
    black = _put(eng, Card(id='b',name='Black',type_line='Creature',is_creature=True,
                           color_identity={'B'},power=1,toughness=10,oracle_text='Flying'), 'p2')
    source.summoning_sick = False
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.active_player, [source])
    eng.state.current_step = 'declare_blockers'
    eng.declare_blockers(eng.state.players[1], [{'blocker':b,'attacker':source} for b in [white,black]])
    white.card.color_identity = {'B'}
    black.card.color_identity = {'W'}
    eng.resolve_until_stable()
    assert white.zone == Zone.GRAVEYARD
    assert black.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize('name', ['Detonate','Molder'])
def test_exact_mana_value_rejects_wrong_cost_targets(name):
    eng = _engine()
    target = _put(eng, Card(id='a',name='Wrong',type_line='Artifact',converted_mana_cost=2), 'p2')
    with pytest.raises(ValueError):
        _cast(eng, name, [target], x=3)
    assert target.zone == Zone.BATTLEFIELD


def test_indestructible_survives_rider_then_regenerates_a_later_destroy():
    eng = _engine()
    target = _put(eng, Card(id='a',name='Tough',type_line='Artifact',oracle_text='Indestructible'), 'p2')
    eng.rules.regenerate(target)
    _cast(eng, 'Crumble', [target])
    target.card.oracle_text = ''
    bind_from_catalogue(target)
    eng.rules.destroy(target)
    assert target.zone == Zone.BATTLEFIELD
    assert target.tapped
