"""Anje: self-or-Vampire entry batches once per turn, plus precise sacrifice costs."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card,cast,filler,game


def board():
    engine=game(players=3,library=30)
    source=card(engine,'Anje, Maid of Dishonor')
    return engine,source


def bloods(engine):
    return [obj for obj in engine.state.battlefield if obj.name=='Blood']


def enter(engine,name='Vampire',player='p1',kind='Creature — Vampire'):
    obj=filler(engine,name,player=player,type_line=kind,zone=Zone.GRAVEYARD,
               **({'power':2,'toughness':2} if 'Creature' in kind else {}))
    engine.rules.return_from_graveyard(obj,'battlefield')
    return obj


def activate(engine,source,victim):
    engine.state.players[0].mana_pool.add('C',2)
    engine.activate_ability(engine.state.players[0],source,0,sacrifice_choice=victim.instance_id)


def test_fresh_specs_and_binding():
    engine,source=board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.triggered_abilities)==len(source.activated_abilities)==1


def test_actual_cast_self_entry_creates_one_blood():
    engine=game(library=30)
    source=card(engine,'Anje, Maid of Dishonor',zone=Zone.HAND)
    cast(engine,source)
    token,=bloods(engine)
    assert token.is_token and token.is_artifact and len(token.activated_abilities)==1


def test_simultaneous_other_vampires_create_one_blood():
    engine,source=board()
    with engine.state.simultaneous():
        enter(engine,'First');enter(engine,'Second')
    engine.resolve_until_stable()
    assert len(bloods(engine))==1


def test_simultaneous_self_and_other_entries_create_one_blood():
    engine,source=board()
    engine.rules.put_into_graveyard(source)
    with engine.state.simultaneous():
        engine.rules.return_from_graveyard(source,'battlefield')
        enter(engine,'First');enter(engine,'Second')
    engine.resolve_until_stable()
    assert len(bloods(engine))==1


def test_separate_batches_still_only_trigger_once_each_turn():
    engine,source=board()
    enter(engine,'First');engine.resolve_until_stable()
    enter(engine,'Second');engine.resolve_until_stable()
    assert len(bloods(engine))==1


def test_opponents_vampire_and_nonvampire_do_not_trigger():
    engine,source=board()
    enter(engine,player='p2')
    enter(engine,'Elf',kind='Creature — Elf')
    engine.resolve_until_stable()
    assert not bloods(engine)


def test_noncreature_vampire_permanent_triggers():
    engine,source=board()
    enter(engine,'Kindred Vampire',kind='Kindred Artifact — Vampire')
    engine.resolve_until_stable()
    assert len(bloods(engine))==1


def test_countered_trigger_still_consumes_once_per_turn_limit():
    engine,source=board()
    enter(engine,'First')
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_ability(engine.state.stack[-1])
    enter(engine,'Second');engine.resolve_until_stable()
    assert not bloods(engine)


def test_next_turn_allows_a_new_trigger():
    engine,source=board()
    enter(engine,'First');engine.resolve_until_stable()
    engine.begin_turn()
    enter(engine,'Second');engine.resolve_until_stable()
    assert len(bloods(engine))==2


def test_other_creature_is_sacrificed_before_opponents_lose_life():
    engine,source=board()
    victim=filler(engine,'Other creature',power=2,toughness=2)
    activate(engine,source,victim)
    assert victim.zone==Zone.GRAVEYARD and [p.life for p in engine.state.players]==[20,20,20]
    engine.resolve_until_stable()
    assert [p.life for p in engine.state.players]==[22,18,18]


def test_anje_cannot_pay_the_other_creature_branch():
    engine,source=board()
    with pytest.raises(ValueError):activate(engine,source,source)
    assert source.zone==Zone.BATTLEFIELD


def test_blood_token_can_pay():
    engine,source=board()
    enter(engine);engine.resolve_until_stable()
    token,=bloods(engine)
    activate(engine,source,token)
    engine.resolve_until_stable()
    assert not bloods(engine) and engine.state.players[0].life==22


def test_nontoken_blood_permanent_cannot_pay():
    engine,source=board()
    victim=filler(engine,'Not a token',type_line='Artifact — Blood')
    with pytest.raises(ValueError):activate(engine,source,victim)
    assert victim.zone==Zone.BATTLEFIELD


def test_source_departure_does_not_stop_pending_life_effects():
    engine,source=board()
    victim=filler(engine,'Victim',power=2,toughness=2)
    activate(engine,source,victim)
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert [p.life for p in engine.state.players]==[22,18,18]


def test_clone_pending_trigger_retains_limit():
    engine,source=board()
    enter(engine,'First')
    restored=GameEngine(engine.state.clone())
    restored.resolve_until_stable()
    enter(restored,'Second');restored.resolve_until_stable()
    assert len(bloods(restored))==1 and not bloods(engine)


def test_blood_token_source_can_pay_blood_branch_despite_other_creature_exclusion():
    engine,source=board()
    source.is_token=True
    source.card.type_line='Token Legendary Creature — Vampire Blood'
    engine.recompute_continuous_effects()
    activate(engine,source,source)
    engine.resolve_until_stable()
    assert [p.life for p in engine.state.players]==[22,18,18]


def test_reentering_source_is_a_new_ability_with_a_fresh_limit():
    engine,source=board()
    enter(engine);engine.resolve_until_stable()
    engine.rules.put_into_graveyard(source)
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert len(bloods(engine))==2


def test_controller_change_updates_entry_filter_and_blood_controller():
    engine,source=board()
    source.controller_id='p2'
    enter(engine,'Not yours',player='p1')
    engine.resolve_until_stable()
    assert not bloods(engine)
    enter(engine,'Yours',player='p2')
    engine.resolve_until_stable()
    token,=bloods(engine)
    assert token.controller_id=='p2'


def test_countered_activation_keeps_sacrifice_paid_without_life_changes():
    engine,source=board()
    victim=filler(engine,'Victim',power=2,toughness=2)
    activate(engine,source,victim)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert victim.zone==Zone.GRAVEYARD and [p.life for p in engine.state.players]==[20,20,20]


def test_created_blood_has_its_printed_draw_ability():
    engine,source=board()
    enter(engine);engine.resolve_until_stable()
    blood,=bloods(engine)
    discarded=filler(engine,'Discard',type_line='Instant',zone=Zone.HAND)
    player=engine.state.players[0]
    player.mana_pool.add('C',1)
    engine.activate_ability(player,blood,0,discard_choices=[discarded.instance_id])
    assert discarded.zone==Zone.GRAVEYARD
    engine.resolve_until_stable()
    assert not bloods(engine) and len(player.hand)==1


def test_changeling_entry_qualifies_as_a_vampire():
    engine,source=board()
    obj=filler(engine,'Changeling',type_line='Creature — Shapeshifter',power=1,toughness=1,
               keywords=['Changeling'],zone=Zone.GRAVEYARD)
    engine.rules.return_from_graveyard(obj,'battlefield')
    engine.resolve_until_stable()
    assert len(bloods(engine))==1
