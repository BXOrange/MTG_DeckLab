"""Haunted creature targeting and command-zone emblem effects."""
import pytest
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.game_status import HauntEffect
from mtg_analyzer.game.effects.haunted import HauntedCreatureEffect, is_haunted
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.emblem import Emblem


def setup():
    eng = GameEngine.new_game([('p1', 'P1', []), ('p2', 'P2', [])], starting_hand=0, starting_life=20)
    def creature(name, owner='p2'):
        obj = GameObject(Card(id=name, name=name, type_line='Creature', is_creature=True,
                              power=2, toughness=2), owner_id=owner, zone=Zone.BATTLEFIELD)
        eng.state.add_to_battlefield(obj)
        return obj
    host = creature('Host')
    haunter = creature('Haunter', 'p1')
    HauntEffect(source=haunter).apply(eng.rules.context, [host])
    emblem = Emblem('p1')
    eng.state.player_by_id('p1').emblems.append(emblem)
    return eng, host, haunter, emblem, creature


def test_haunted_target_damage_hits_owner_even_when_controller_differs():
    eng, host, _, emblem, creature = setup()
    other = creature('Other')
    host.controller_id = 'p1'
    effect = HauntedCreatureEffect(amount=3, source=emblem)
    targets = legal_targets(eng.state, 'p1', effect.target_spec, emblem)
    assert [t['instance_id'] for t in targets] == [host.instance_id]
    effect.apply(eng.rules.context, [host])
    assert eng.state.player_by_id('p2').life == 17
    assert eng.state.player_by_id('p1').life == 20
    effect.apply(eng.rules.context, [other])
    assert eng.state.player_by_id('p2').life == 17


def test_haunted_target_obeys_hexproof_and_stale_host_link_does_not_reconnect():
    eng, host, haunter, emblem, _ = setup()
    host.intrinsic_keywords.add('hexproof')
    assert not legal_targets(eng.state, 'p1', TargetSpec(kind='haunted_creature'), emblem)
    host.intrinsic_keywords.clear()
    eng.rules._move_to_graveyard(host)
    eng.rules.return_from_graveyard(host)
    assert haunter.zone == Zone.EXILE
    assert not is_haunted(eng.state, host)
    assert not legal_targets(eng.state, 'p1', TargetSpec(kind='haunted_creature'), emblem)


def test_control_ends_when_last_haunter_leaves_and_never_resumes():
    eng, host, haunter, emblem, creature = setup()
    HauntedCreatureEffect(mode='control', source=emblem).apply(eng.rules.context, [host])
    assert host.controller_id == 'p1'
    eng.rules.return_to_hand(haunter)
    eng.rules.check_state_based_actions()
    assert host.controller_id == 'p2'
    assert host.control_change_while_source is None
    new_haunter = creature('New Haunter', 'p1')
    HauntEffect(source=new_haunter).apply(eng.rules.context, [host])
    eng.rules.check_state_based_actions()
    assert host.controller_id == 'p2'


def test_control_persists_while_any_haunter_remains_and_ignores_emblem_removal():
    eng, host, haunter, emblem, creature = setup()
    another = creature('Another Haunter', 'p2')
    HauntEffect(source=another).apply(eng.rules.context, [host])
    HauntedCreatureEffect(mode='control', source=emblem).apply(eng.rules.context, [host])
    eng.state.players[0].emblems.clear()
    eng.rules.return_to_hand(haunter)
    eng.rules.check_state_based_actions()
    assert host.controller_id == 'p1'
    eng.rules.return_to_hand(another)
    eng.rules.check_state_based_actions()
    assert host.controller_id == 'p2'


@pytest.mark.parametrize("control", [False, True])
def test_quoted_kaya_emblem_triggers_from_command_zone(control):
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
    from mtg_analyzer.models.game.events import GameEvent, EventType
    eng, host, _, old_emblem, creature = setup()
    eng.state.players[0].emblems.remove(old_emblem)
    source = creature('Kaya source', 'p1')
    body = ('gain control of target haunted creature for as long as it remains haunted' if control else
            'this emblem deals 3 damage to the owner of target haunted creature')
    specs = match_clause('you get an emblem with "at the beginning of your upkeep, ' + body + '."')
    assert specs is not None
    for effect in build_effects(specs, source=source):
        effect.apply(eng.rules.context)
    eng.rules._move_to_graveyard(source)
    eng.state.active_player_index = 0
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='beginning'))
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'trigger_target'
    eng.resolve_pending_choice(host.instance_id)
    eng.resolve_until_stable()
    assert eng.state.players[1].life == (20 if control else 17)
    assert host.controller_id == ('p1' if control else 'p2')


def test_repeated_upkeep_control_retains_original_controller_and_does_not_restart():
    eng, host, haunter, emblem, creature = setup()
    effect = HauntedCreatureEffect(mode='control', source=emblem)
    effect.apply(eng.rules.context, [host])
    effect.apply(eng.rules.context, [host])
    eng.rules.return_to_hand(haunter)
    # Another haunt in the same resolution does not revive the expired window.
    another = creature('Later haunter', 'p1')
    HauntEffect(source=another).apply(eng.rules.context, [host])
    assert host.controller_id == 'p2'
    assert host.control_change_while_source is None


def test_old_haunt_dies_trigger_does_not_exile_returned_source():
    eng, host, _, _, creature = setup()
    source = creature('Dead haunter', 'p1')
    eng.rules._move_to_graveyard(source)
    graveyard_incarnation = source.zone_incarnation
    eng.rules.return_from_graveyard(source)
    eng.rules.context.trigger_event = {'instance_id': source.instance_id,
                                      'graveyard_incarnation': graveyard_incarnation}
    HauntEffect(source=source).apply(eng.rules.context, [host])
    assert source.zone == Zone.BATTLEFIELD
    assert source.haunting_instance_id is None
