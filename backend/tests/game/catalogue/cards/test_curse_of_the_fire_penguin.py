"""Fire Penguin overlays a host, then returns its Aura after that host dies."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, cast
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    host=filler(engine,'Base',player='p2',power=1,toughness=1)
    aura=card(engine,'Curse of the Fire Penguin',zone=Zone.HAND)
    other=filler(engine,'Other',player='p3',power=2,toughness=2)
    return engine,aura,host,other


def _attach(engine,aura,host):
    # Use an ordinary creature as the initial target before testing layers.
    cast(engine,aura,targets=[host])
    engine.recompute_continuous_effects()


def _pick(engine,target):
    choice=engine.state.pending_choice
    assert choice['kind']=='fire_penguin_return'
    engine.resolve_pending_choice(str(target.instance_id))
    engine.resolve_until_stable()


def test_fresh_specs_and_overlay_preserves_name_cost_color():
    engine,aura,_,other=_board()
    host=card(engine,'Solemn Simulacrum',player='p2')
    original=(host.name,host.mana_value,host.colors)
    _attach(engine,aura,host)
    a,b=specs_for(aura.card),specs_for(aura.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert (host.name,host.mana_value,host.colors)==original
    assert host.power==6 and host.toughness==5 and combat.has(host,'trample')
    assert host.is_creature and not host.is_artifact
    assert host.has_subtype('Penguin') and not host.has_subtype('Golem')
    assert host.loses_all_abilities and len(host.granted_triggered_abilities)==1
    assert host.printing_metadata=={'set_code':'unh','artist':'Matt Thompson','rarity':'rare'}
    assert aura.is_enchantment and not aura.is_creature and not aura.flipped


def test_overlay_removes_legendary_supertype_and_original_keywords():
    engine,aura,_,other=_board()
    host=card(engine,'Isamaru, Hound of Konda',player='p2')
    _attach(engine,aura,host)
    assert not host.is_legendary and 'legendary' not in host.type_words
    assert host.has_subtype('Penguin') and not host.has_subtype('Dog')
    assert host.power==6 and host.toughness==5


@pytest.mark.parametrize('change',['exile_aura','move_aura'])
def test_overlay_ends_when_aura_leaves_or_moves(change):
    engine,aura,_,other=_board()
    host=card(engine,'Serra Angel',player='p2')
    _attach(engine,aura,host)
    assert not combat.has(host,'flying') and not combat.has(host,'vigilance')
    if change=='exile_aura':
        engine.rules.exile(aura)
    else:
        assert engine.rules.attach_to_target(aura,other,check_control=False)
    engine.recompute_continuous_effects()
    assert host.power==4 and host.toughness==4 and combat.has(host,'flying')
    assert not host.has_subtype('Penguin')


def test_host_dies_returns_aura_attached_to_new_creature():
    engine,aura,_,other=_board()
    host=filler(engine,'First',player='p2',power=1,toughness=1)
    _attach(engine,aura,host)
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    assert host.zone==Zone.GRAVEYARD and aura.zone==Zone.GRAVEYARD
    _pick(engine,other)
    assert aura.zone==Zone.BATTLEFIELD and aura.attached_to==other.instance_id
    assert other.power==6 and other.toughness==5 and combat.has(other,'trample')


@pytest.mark.parametrize('change',['clone','aura_exiled','aura_new_visit'])
def test_return_choice_follows_exact_aura_graveyard_visit(change):
    engine,aura,_,other=_board()
    host=filler(engine,'First',player='p2',power=1,toughness=1)
    _attach(engine,aura,host)
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    if change=='clone':
        engine=GameEngine(engine.state.clone())
        aura=engine.state.find_object(aura.instance_id)
        other=engine.state.find_object(other.instance_id)
    else:
        engine.rules.exile(aura)
        if change=='aura_new_visit':
            engine.rules.return_from_graveyard(aura,'hand')
            engine.state.players[0].remove_from_zone(aura,Zone.HAND)
            engine.rules.put_into_graveyard(aura)
    _pick(engine,other)
    assert aura.zone==(Zone.BATTLEFIELD if change=='clone' else Zone.EXILE if change=='aura_exiled' else Zone.GRAVEYARD)


def test_exiling_host_does_not_trigger_return():
    engine,aura,_,other=_board()
    host=filler(engine,'First',player='p2',power=1,toughness=1)
    _attach(engine,aura,host)
    engine.rules.exile(host)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and aura.zone==Zone.GRAVEYARD


def test_original_death_trigger_is_removed_and_aura_can_repeat_cycle():
    engine,aura,_,other=_board()
    host=card(engine,'Solemn Simulacrum',player='p2')
    before=len(engine.state.players[1].hand)
    _attach(engine,aura,host)
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    assert len(engine.state.players[1].hand)==before
    _pick(engine,other)
    replacement=filler(engine,'Next',power=1,toughness=1)
    engine.rules.destroy(other)
    engine.resolve_until_stable()
    _pick(engine,replacement)
    assert aura.attached_to==replacement.instance_id and replacement.power==6


def test_aura_destruction_does_not_return_it():
    engine,aura,host,other=_board()
    _attach(engine,aura,host)
    engine.rules.destroy(aura)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and aura.zone==Zone.GRAVEYARD
    assert host.power==1 and not combat.has(host,'trample')


def test_aura_return_stays_in_graveyard_without_legal_creature():
    engine,aura,host,other=_board()
    _attach(engine,aura,host)
    engine.rules.exile(other)
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    assert aura.zone==Zone.GRAVEYARD and engine.state.pending_choice is None


def test_token_host_death_also_returns_the_aura():
    engine,aura,_,other=_board()
    token=filler(engine,'Token host',power=1,toughness=1)
    token.is_token=True
    _attach(engine,aura,token)
    engine.rules.destroy(token)
    engine.resolve_until_stable()
    _pick(engine,other)
    assert aura.attached_to==other.instance_id


def test_counters_and_later_pump_apply_on_top_of_six_five():
    engine,aura,host,other=_board()
    host.counters['+1/+1']=2
    _attach(engine,aura,host)
    assert host.power==8 and host.toughness==7


def test_clone_before_host_dies_retains_aura_anchor():
    engine,aura,host,other=_board()
    _attach(engine,aura,host)
    engine=GameEngine(engine.state.clone())
    host=engine.state.find_object(host.instance_id)
    other=engine.state.find_object(other.instance_id)
    aura=engine.state.find_object(aura.instance_id)
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    _pick(engine,other)
    assert aura.attached_to==other.instance_id and other.power==6


def test_return_attachment_does_not_target_hexproof_creature():
    engine,aura,host,other=_board()
    bogle=card(engine,'Slippery Bogle',player='p3')
    _attach(engine,aura,host)
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    _pick(engine,bogle)
    assert aura.attached_to==bogle.instance_id and bogle.power==6


def test_overlay_printing_facts_are_removed_with_aura():
    engine,aura,host,other=_board()
    _attach(engine,aura,host)
    assert host.printing_metadata['artist']=='Matt Thompson'
    engine.rules.exile(aura)
    engine.recompute_continuous_effects()
    assert host.printing_metadata=={'set_code':host.card.set_code or ''}
