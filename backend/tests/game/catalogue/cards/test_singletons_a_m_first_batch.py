"""Runtime coverage for the first independently authored singleton batch."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.card_registry import _REGISTRY
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.effect_conditions import condition_state
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.game.continuous import has_subtype
from tests.support.catalogue import battlefield_object, two_player_game


def authored(engine, player, name, type_line='Creature', **kwargs):
    obj = battlefield_object(engine, player.id, name, type_line, **kwargs)
    bind_from_catalogue(obj)
    return obj


def apply(engine, source, index=0, targets=None):
    context = GameContext(state=engine.state, engine=engine.rules)
    for effect in build_effects(_REGISTRY[source.name.lower()]()[index].effects, source):
        effect.apply(context, targets or [])


@pytest.mark.parametrize('life,power,menace', [(20,4,False),(21,5,True),(29,5,True),(30,10,True)])
def test_elenda_life_thresholds(life, power, menace):
    engine, p = two_player_game()
    obj = authored(engine,p,'Elenda, Saint of Dusk',is_creature=True,power=4,toughness=4)
    p.life = life
    engine.recompute_continuous_effects()
    assert (obj.power,obj.toughness) == (power,power)
    assert ('menace' in obj.granted_keywords) is menace


def test_essence_pulse_includes_life_just_gained_and_all_creatures():
    engine,p = two_player_game()
    spell = authored(engine,p,'Essence Pulse','Sorcery')
    ally = battlefield_object(engine,p.id,'Ally','Creature',is_creature=True,power=5,toughness=5)
    enemy = battlefield_object(engine,'p2','Enemy','Creature',is_creature=True,power=6,toughness=6)
    engine.rules.gain_life(p, 1)
    apply(engine,spell)
    engine.recompute_continuous_effects()
    assert p.life == 23
    assert (ally.power,enemy.power) == (2,3)


def test_leyline_colors_nonlands_and_grants_basic_types_to_lands():
    engine,p = two_player_game()
    authored(engine,p,'Leyline of the Guildpact','Enchantment')
    ally = battlefield_object(engine,p.id,'Ally','Artifact')
    land = battlefield_object(engine,p.id,'Land','Land',is_land=True)
    enemy = battlefield_object(engine,'p2','Enemy','Artifact')
    engine.recompute_continuous_effects()
    assert set(ally.colors) == set('WUBRG')
    assert not land.colors and not enemy.colors
    assert all(has_subtype(land,t) for t in ('plains','island','swamp','mountain','forest'))


@pytest.mark.parametrize('origin,count', [('hand',5),('graveyard',10),('exile',5)])
def test_increasing_devotion_uses_actual_cast_origin(origin,count):
    engine,p = two_player_game()
    spell = authored(engine,p,'Increasing Devotion','Sorcery')
    spell.cast_from_zone = origin
    apply(engine,spell)
    tokens = [o for o in engine.state.battlefield if o.is_token]
    assert len(tokens) == count
    assert all(o.power == 1 and o.toughness == 1 and o.name == 'Human' for o in tokens)


def test_cast_origin_condition_missing_source_is_unknown():
    engine,_ = two_player_game()
    assert condition_state({'kind':'source_cast_from_zone','zone':'graveyard'},GameContext(engine.state,engine.rules)) is None


def test_fatestitcher_excludes_self_and_offers_resolution_choice():
    engine,p = two_player_game()
    source = authored(engine,p,'Fatestitcher',is_creature=True,power=1,toughness=2)
    target = battlefield_object(engine,p.id,'Rock','Artifact')
    effect = build_effects(_REGISTRY['fatestitcher']()[0].effects,source)[0]
    legal = legal_targets(engine.state,p.id,effect.target_spec,source)
    assert source.instance_id not in [o.get('instance_id') for o in legal]
    assert target.instance_id in [o.get('instance_id') for o in legal]
    effect.apply(GameContext(engine.state,engine.rules),[target])
    assert engine.state.pending_choice['kind'] == 'tap_or_untap'
    engine.rules.resolve_choice('tap')
    assert target.tapped


@pytest.mark.parametrize('name,text,keywords,kind', [
    ('Elenda, Saint of Dusk','Lifelink, hexproof from instants\nAs long as your life total is greater than your starting life total, Elenda gets +1/+1 and has menace. Elenda gets an additional +5/+5 as long as your life total is at least 10 greater than your starting life total.', ['Lifelink','Hexproof from','Hexproof'],'static_effects'),
    ('Essence Pulse','You gain 2 life. Each creature gets -X/-X until end of turn, where X is the amount of life you gained this turn.',[],'spell_effects'),
    ('Leyline of the Guildpact','If this card is in your opening hand, you may begin the game with it on the battlefield.\nEach nonland permanent you control is all colors.\nLands you control are every basic land type in addition to their other types.',[],'static_effects'),
    ('Increasing Devotion','Create five 1/1 white Human creature tokens. If this spell was cast from a graveyard, create ten of those tokens instead.\nFlashback {7}{W}{W} (You may cast this card from your graveyard for its flashback cost. Then exile it.)',['Flashback'],'spell_effects'),
    ('Fatestitcher','{T}: You may tap or untap another target permanent.\nUnearth {U} ({U}: Return this card from your graveyard to the battlefield. It gains haste. Exile it at the beginning of the next end step or if it would leave the battlefield. Unearth only as a sorcery.)',['Unearth'],'activated_abilities'),
])
def test_real_oracle_keywords_and_fresh_catalogue_specs(name,text,keywords,kind):
    from mtg_analyzer.game.card_registry import specs_for, opening_hand_battlefield_permission
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject,Zone
    card = Card(id=name,name=name,type_line='Creature' if name in ('Fatestitcher','Elenda, Saint of Dusk') else 'Enchantment',oracle_text=text,keywords=keywords)
    first,second = specs_for(card),specs_for(card)
    assert first and len(first) == len(second)
    assert all(a is not b for a,b in zip(first,second))
    obj = GameObject(card=card,owner_id='p1',zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    assert getattr(obj,kind)
    if name == 'Elenda, Saint of Dusk':
        assert 'lifelink' in obj.intrinsic_keywords
        assert 'menace' not in obj.intrinsic_keywords
    elif name == 'Leyline of the Guildpact':
        assert opening_hand_battlefield_permission(card)
    elif name == 'Increasing Devotion':
        assert any(s.keyword and s.keyword.get('name') == 'flashback' for s in first)
    elif name == 'Fatestitcher':
        assert len(obj.activated_abilities) >= 2


def test_elenda_hexproof_protects_from_enemy_instants_only():
    engine,p = two_player_game()
    source = authored(engine,p,'Elenda, Saint of Dusk',is_creature=True,power=4,toughness=4,oracle_text='Lifelink, hexproof from instants',keywords=['Lifelink','Hexproof from','Hexproof'])
    from mtg_analyzer.game.targeting import TargetSpec
    instant = battlefield_object(engine,'p2','Instant','Instant',is_instant=True)
    sorcery = battlefield_object(engine,'p2','Sorcery','Sorcery',is_sorcery=True)
    own_instant = battlefield_object(engine,p.id,'Own instant','Instant',is_instant=True)
    engine.recompute_continuous_effects()
    def can_target(spell):
        return source.instance_id in [t.get('instance_id') for t in legal_targets(engine.state,spell.controller_id,TargetSpec(kind='creature'),spell)]
    assert not can_target(instant)
    assert can_target(sorcery)
    assert can_target(own_instant)
    source.temp_keywords.add('hexproof')
    assert not can_target(sorcery)
