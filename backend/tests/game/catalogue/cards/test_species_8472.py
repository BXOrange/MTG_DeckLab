"""Species 8472 distinguishes artifact abilities from artifact spells."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import ability_target_specs, legal_targets, spell_target_specs
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, enter, RICH
from tests.support.star_trek import advance_to


def board():
    engine = game(players=3, library=20)
    advance_to(engine, 'main1')
    species = card(engine, 'Species 8472')
    return engine, species


def source(engine, owner='p2', artifact=True, triggered=False, zone=Zone.BATTLEFIELD):
    text = ('When this creature enters, destroy target creature.' if triggered
            else '{1}: Destroy target creature.')
    return filler(engine, 'Source', player=owner, type_line='Artifact Creature' if artifact else 'Creature',
                  power=2, toughness=2, oracle_text=text, zone=zone)


def test_fresh_binding():
    engine, species = board()
    a,b = specs_for(species.card),specs_for(species.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(species.triggered_abilities)==1 and len(species.static_effects)==2


@pytest.mark.parametrize('owner,artifact,allowed', [('p1',True,True),('p2',True,False),('p2',False,True),('p3',True,False)])
def test_activation_announcement(owner, artifact, allowed):
    engine, species = board()
    obj = source(engine, owner, artifact)
    player=engine.state.player_by_id(owner)
    player.mana_pool.add_many(RICH)
    spec=ability_target_specs(obj.activated_abilities[0])[0]
    offered={o.get('instance_id') for o in legal_targets(engine.state,owner,spec,source=obj)}
    assert (species.instance_id in offered)==allowed
    if allowed:
        engine.activate_ability(player,obj,0,targets=[species])
        engine.resolve_until_stable()
        assert species.zone==Zone.GRAVEYARD
    else:
        with pytest.raises(ValueError):
            engine.activate_ability(player,obj,0,targets=[species])
        assert species.zone==Zone.BATTLEFIELD


def test_becoming_artifact_in_response_invalidates_ability_target():
    engine,species=board()
    obj=source(engine,artifact=False)
    player=engine.state.player_by_id('p2'); player.mana_pool.add_many(RICH)
    engine.activate_ability(player,obj,0,targets=[species])
    obj.card.type_line='Artifact Creature'
    engine.resolve_until_stable()
    assert species.zone==Zone.BATTLEFIELD


def test_ability_removal_ends_targeting_restriction():
    engine,species=board()
    aura=card(engine,'Darksteel Mutation')
    aura.attached_to=species.instance_id
    engine.recompute_continuous_effects()
    obj=source(engine)
    player=engine.state.player_by_id('p2'); player.mana_pool.add_many(RICH)
    spec=ability_target_specs(obj.activated_abilities[0])[0]
    assert species.instance_id in {o.get('instance_id') for o in legal_targets(engine.state,'p2',spec,source=obj)}


def test_artifact_spell_remains_allowed():
    engine,species=board()
    spell=filler(engine,'Artifact Spell',player='p2',type_line='Artifact',
                 oracle_text='When this artifact enters, draw a card.',zone=Zone.HAND)
    spell.zone=Zone.STACK
    from mtg_analyzer.game.targeting import TargetSpec
    spec=TargetSpec(kind='creature')
    assert species.instance_id in {o.get('instance_id') for o in legal_targets(engine.state,'p2',spec,source=spell)}


def test_artifact_ability_from_stack_is_still_restricted():
    engine,species=board()
    obj=source(engine,zone=Zone.HAND)
    obj.zone=Zone.STACK
    spec=ability_target_specs(obj.activated_abilities[0])[0]
    assert species.instance_id not in {o.get('instance_id') for o in legal_targets(engine.state,'p2',spec,source=obj)}


def test_entry_life_counts_distinct_land_names_you_control():
    engine,species=board()
    card(engine,'Forest'); card(engine,'Forest'); card(engine,'Island')
    card(engine,'Swamp',player='p2')
    player=engine.state.player_by_id('p1'); before=player.life
    enter(engine,species)
    assert player.life==before+2


@pytest.mark.parametrize('artifact', [True, False])
def test_artifact_blocker_restriction(artifact):
    from mtg_analyzer.game import combat
    engine,species=board()
    blocker=source(engine,artifact=artifact)
    assert combat.blocker_allowed(species,blocker,engine.state) is (not artifact)


def test_opposing_artifact_trigger_never_offers_species():
    engine,species=board()
    obj=source(engine,triggered=True)
    enter(engine,obj)
    choice=engine.state.pending_choice
    assert choice is not None
    assert species.instance_id not in {o.get('instance_id') for o in choice['options']}


def test_clone_rechecks_ability_source_quality():
    engine,species=board()
    obj=source(engine,artifact=False)
    player=engine.state.player_by_id('p2'); player.mana_pool.add_many(RICH)
    engine.activate_ability(player,obj,0,targets=[species])
    clone=GameEngine(engine.state.clone())
    clone.state.find_object(obj.instance_id).card.type_line='Artifact Creature'
    clone.resolve_until_stable()
    assert clone.state.find_object(species.instance_id).zone==Zone.BATTLEFIELD



def test_opposing_artifact_aura_spell_can_target_and_resolve():
    engine,species=board()
    aura=filler(engine,'Artifact Aura',player='p1',type_line='Artifact Enchantment — Aura',
                oracle_text='Enchant creature',keywords=['Enchant'],zone=Zone.HAND)
    species.controller_id='p2'
    player=engine.state.player_by_id('p1'); player.mana_pool.add_many(RICH)
    engine.cast_spell(player,aura,targets=[species])
    engine.resolve_until_stable()
    assert aura.zone==Zone.BATTLEFIELD and aura.attached_to==species.instance_id
