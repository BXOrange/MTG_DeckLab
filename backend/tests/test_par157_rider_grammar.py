"""The same target, timing and entry axes compose across real flicker texts."""
import pytest
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.models.game.game_object import Zone
from test_par136_delayed_blink import _engine, _bf, _card, _cast, _end_step


@pytest.mark.parametrize('text', [
 "exile target creature you control, then return that card to the battlefield under its owner's control with a +1/+1 counter on it.",
 "exile target artifact or creature, then return that card to the battlefield under its owner's control with a +1/+1 counter on it.",
 "exile target creature. at the beginning of the next end step, return that card to the battlefield under its owner's control with a +1/+1 counter on it.",
 "exile any number of target creatures and/or planeswalkers you control. at the beginning of the next end step, return each of them to the battlefield under its owner's control. each of them enters with an additional +1/+1 counter on it if it's a creature and an additional loyalty counter on it if it's a planeswalker.",
 "exile up to 1 target creature you control without flying. return it to the battlefield under its owner's control with a flying counter on it at the beginning of the next end step.",
 "exile target attacking creature an opponent controls. at the beginning of the next end step, return it to the battlefield tapped under its owner's control.",
 "exile any number of other target permanents you control. return those cards to the battlefield under their owner's control at the beginning of the next end step. if a land enters this way, it enters tapped.",
 "exile up to 1 target nontoken artifact or creature, then return that card to the battlefield tapped under its owner's control.",
])
def test_entry_and_schedule_axes_parse_as_one_flicker(text):
    specs = parse_effect_body(text)
    assert specs and len(specs) == 1 and specs[0].type == 'blink'


@pytest.mark.parametrize('tail', ["with a wish counter on it", "under your opponent's control", "with a +1/+1 counter on it, then win the game"])
def test_unrecognized_return_instruction_stays_unclaimed(tail):
    assert parse_effect_body("exile target creature, then return that card to the battlefield under its owner's control " + tail) is None


def test_real_daydream_claims_and_executes_additional_counter_after_fresh_reset():
    text = "Exile target creature you control, then return that card to the battlefield under its owner's control with a +1/+1 counter on it."
    assert parse_oracle(_card('Daydream', 'Sorcery', oracle_text=text)).modeled
    eng, player = _engine(); obj = _bf(eng, _card('Bear'))
    obj.counters['+1/+1'] = 5
    _cast(eng, player, text, [obj])
    assert obj.zone == Zone.BATTLEFIELD and obj.counters == {'+1/+1': 1}


def test_delayed_return_entry_counter_tracks_only_exact_exile_visit():
    text = "Exile target creature. At the beginning of the next end step, return that card to the battlefield under its owner's control with a +1/+1 counter on it."
    eng, player = _engine(); obj = _bf(eng, _card('Bear'))
    _cast(eng, player, text, [obj]); assert obj.zone == Zone.EXILE
    _end_step(eng); assert obj.zone == Zone.BATTLEFIELD and obj.counters == {'+1/+1': 1}


def test_delayed_typed_return_uses_both_current_creature_and_planeswalker_types():
    text = "Exile any number of target creatures and/or planeswalkers you control. At the beginning of the next end step, return each of them to the battlefield under its owner's control. Each of them enters with an additional +1/+1 counter on it if it's a creature and an additional loyalty counter on it if it's a planeswalker."
    eng, player = _engine(); obj = _bf(eng, _card('Creature Walker', 'Creature Planeswalker — Test', loyalty=3))
    _cast(eng, player, text, [obj]); assert obj.zone == Zone.EXILE
    _end_step(eng)
    assert obj.counters == {'loyalty': 4, '+1/+1': 1}


@pytest.mark.parametrize('kind', ['Creature — Bear', 'Planeswalker — Test'])
def test_liliana_faultless_collateral_targets_real_scoped_union_and_pays_cost(kind):
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.game.targeting import legal_targets
    from mtg_analyzer.models.game.game_object import GameObject
    text = "Whenever another creature or planeswalker you control enters, you gain 1 life.\n{1}, {T}, Discard a card: Another target creature or planeswalker you control gains hexproof until end of turn."
    eng, player = _engine()
    source = _bf(eng, _card('Liliana the Faultless', oracle_text=text), bind=True)
    friend = _bf(eng, _card('Friend', kind, loyalty=3 if 'Planeswalker' in kind else None))
    enemy = _bf(eng, _card('Enemy', kind, loyalty=3 if 'Planeswalker' in kind else None), controller='p2')
    protected = _bf(eng, _card('Shrouded Friend'))
    protected.intrinsic_keywords.add('shroud')
    spec = source.activated_abilities[0].effects[0].target_spec
    legal = {x['instance_id'] for x in legal_targets(eng.state, player.id, spec, source)}
    assert friend.instance_id in legal
    assert {source.instance_id, enemy.instance_id, protected.instance_id}.isdisjoint(legal)
    fodder = GameObject(_card('Fodder', 'Instant'), owner_id='p1', zone=Zone.HAND)
    player.add_to_zone(fodder, Zone.HAND)
    player.mana_pool.add('C', 1)
    eng.activate_ability(player, source, 0, targets=[friend], discard_choices=[fodder.instance_id])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert source.tapped and fodder.zone == Zone.GRAVEYARD
    assert player.mana_pool.total() == 0
    assert 'hexproof' in friend.granted_keywords


def test_your_next_upkeep_waits_for_ability_controller_in_three_player_game():
    from mtg_analyzer.game.game_engine import GameEngine
    eng = GameEngine.new_game([('p1','A',[]), ('p2','B',[]), ('p3','C',[])], starting_hand=0)
    eng.begin_turn(); eng.state.current_step = 'main1'
    player = eng.state.player_by_id('p1')
    obj = _bf(eng, _card('Bear'))
    text = "Exile target creature. At the beginning of your next upkeep, return that card to the battlefield under its owner's control with a +1/+1 counter on it."
    _cast(eng, player, text, [obj]); assert obj.zone == Zone.EXILE
    eng.state.active_player_index = 1
    eng._fire_delayed_triggers('upkeep'); eng.resolve_until_stable()
    assert obj.zone == Zone.EXILE
    eng.state.active_player_index = 2
    eng._fire_delayed_triggers('upkeep'); eng.resolve_until_stable()
    assert obj.zone == Zone.EXILE
    eng.state.active_player_index = 0
    eng._fire_delayed_triggers('upkeep'); eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD and obj.counters == {'+1/+1': 1}
