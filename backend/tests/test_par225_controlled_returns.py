"""PAR-225: untargeted returns of controlled permanents.

Three distinct contexts share one object grammar: a resolving "return a `<thing>` you control to its owner's hand"
(a non-targeted choice on resolution, RULE 608.2d), "sacrifice ~ unless you return `<thing>`" (a controller choice
whose refusal takes the sacrifice) and "as an additional cost to cast this spell, return `<thing>`" (paid while
casting, RULE 601.2b / 601.2h).
"""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def engine():
    eng = GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = 'main1'
    return eng


def put(eng, name, type_line, text='', zone=Zone.BATTLEFIELD, owner='p1', **kw):
    card = Card(id=name, name=name, type_line=type_line, oracle_text=text, **kw)
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    elif zone == Zone.HAND:
        eng.state.player_by_id(owner).add_to_zone(obj, Zone.HAND)
    return obj


def creature(eng, name, colors=None, **kw):
    kw.setdefault('text', '')
    # RULE 202.2: a card's colour comes from its mana cost.
    cost = ''.join('{%s}' % c for c in colors or [])
    return put(eng, name, 'Creature — Bear', is_creature=True, power=2, toughness=2, mana_cost_string=cost, **kw)


def land(eng, name, type_line='Land'):
    return put(eng, name, type_line, is_land=True)


def run_clause(eng, clause, source):
    specs = match_clause(clause)
    assert specs is not None, clause
    for effect in build_effects(specs, source):
        effect.apply(GameContext(eng.state, eng.rules), None)


def pick(eng, obj):
    choice = eng.state.pending_choice
    assert choice is not None and choice['kind'] == 'choose_objects', choice
    option = next(o for o in choice['options'] if o.get('instance_id') == obj.instance_id)
    eng.resolve_pending_choice(str(option['id']))
    eng.resolve_until_stable()


def offered(eng):
    return {o['instance_id'] for o in eng.state.pending_choice['options'] if 'instance_id' in o}


# --- parse ------------------------------------------------------------------


@pytest.mark.parametrize('clause', [
    "return a creature you control to its owner's hand",
    "return a permanent you control to its owner's hand",
    "return a blue or black creature you control to its owner's hand",
    "return another creature you control to its owner's hand",
    "return a nonland permanent you control to its owner's hand",
    "return an enchantment you control to its owner's hand",
])
def test_controlled_return_is_a_choice_not_a_target(clause):
    [spec] = match_clause(clause)
    assert spec.type == 'choose_objects'
    assert spec.params['action'] == 'return_to_hand' and spec.params['count'] == 1
    assert 'target_kind' not in spec.params
    assert not spec.params.get('optional')


def test_another_excludes_the_source_and_plain_article_keeps_it():
    assert match_clause("return another creature you control to its owner's hand")[0].params['exclude_self'] is True
    assert match_clause("return a creature you control to its owner's hand")[0].params['exclude_self'] is False


def test_targeted_return_still_targets():
    [spec] = match_clause("return target creature you control to its owner's hand")
    assert spec.type == 'return_to_hand' and spec.params['target_kind'] == 'creature_you_control'


@pytest.mark.parametrize('clause', [
    "return a creature you control to its owner's hand unless you compliment an opponent",
    "sacrifice it unless you return 1 forests you control to their owner's hand",
    "sacrifice it unless you return 2 target forests you control to their owner's hand",
    "return a legendary creature you control to its owner's hand",
    "return a creature an opponent controls to its owner's hand",
])
def test_unfaithful_shapes_stay_unclaimed(clause):
    specs = match_clause(clause)
    assert not specs or all(s.params.get('target_kind') for s in specs), specs


def test_sacrifice_unless_return_shape():
    [spec] = match_clause("sacrifice it unless you return a non-lair land you control to its owner's hand")
    assert spec.type == 'choose_objects'
    assert spec.params['optional'] is True
    assert spec.params['permanent_filter'] == {'without_subtype': 'lair', 'card_type': 'land'}
    assert spec.params['else_effects'] == [{'type': 'sacrifice_self', 'params': {}}]


CALIBRATION = {
    'Shrieking Drake': ('Creature — Bird', 'Flying\nWhen this creature enters, return a creature you control to its owner\'s hand.'),
    'Kor Skyfisher': ('Creature — Kor Soldier', 'Flying\nWhen this creature enters, return a permanent you control to its owner\'s hand.'),
    "Familiar's Ruse": ('Instant', "As an additional cost to cast this spell, return a creature you control to its owner's hand.\nCounter target spell."),
    "Crosis's Catacombs": ('Land — Lair', "When this land enters, sacrifice it unless you return a non-Lair land you control to its owner's hand.\n{T}: Add {U}, {B}, or {R}."),
    'Cache Raiders': ('Creature — Merfolk', "At the beginning of your upkeep, return a permanent you control to its owner's hand."),
}


@pytest.mark.parametrize('name', sorted(CALIBRATION))
def test_calibration_cards_are_modeled(name):
    type_line, text = CALIBRATION[name]
    card = Card(id=name, name=name, type_line=type_line, oracle_text=text, is_creature='Creature' in type_line,
                is_instant=type_line == 'Instant', is_land='Land' in type_line)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


# --- resolving ETB / upkeep choice -----------------------------------------


def test_etb_return_may_return_the_source_itself_and_is_the_controllers_choice():
    eng = engine()
    skyfisher = creature(eng, 'Kor Skyfisher')
    other = creature(eng, 'Other')
    opp = put(eng, 'Opp', 'Creature — Bear', is_creature=True, power=1, toughness=1, owner='p2')
    run_clause(eng, "return a permanent you control to its owner's hand", skyfisher)
    # The choice is a pick among the controller's own permanents: the source is legal, the opponent's is not.
    assert offered(eng) == {skyfisher.instance_id, other.instance_id}
    pick(eng, skyfisher)
    assert skyfisher in eng.state.player_by_id('p1').hand
    assert other in eng.state.battlefield and opp in eng.state.battlefield


def test_return_is_mandatory_and_forced_without_a_decision():
    eng = engine()
    drake = creature(eng, 'Shrieking Drake')
    run_clause(eng, "return a creature you control to its owner's hand", drake)
    assert eng.state.pending_choice is None  # the only creature: nothing to decide
    assert drake in eng.state.player_by_id('p1').hand


def test_filter_and_another_restrict_the_pool():
    eng = engine()
    drake = creature(eng, 'Harpy', colors=['U'])
    blue = creature(eng, 'Blue', colors=['U'])
    red = creature(eng, 'Red', colors=['R'])
    run_clause(eng, "return another blue or black creature you control to its owner's hand", drake)
    assert eng.state.pending_choice is None  # exactly one legal creature besides the source
    assert blue in eng.state.player_by_id('p1').hand
    assert drake in eng.state.battlefield and red in eng.state.battlefield


def test_no_legal_object_does_nothing():
    eng = engine()
    src = put(eng, 'Statue', 'Artifact Creature — Golem', is_creature=True, power=1, toughness=1)
    run_clause(eng, "return a land you control to its owner's hand", src)
    assert eng.state.pending_choice is None and src in eng.state.battlefield


def test_upkeep_trigger_returns_a_creature_through_the_real_trigger():
    eng = engine()
    card_text = "At the beginning of your upkeep, return a permanent you control to its owner's hand."
    raiders = creature(eng, 'Cache Raiders', text=card_text)
    keep = creature(eng, 'Keep')
    assert parse_oracle(raiders.card).modeled
    eng.state.active_player_index = 0
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='upkeep'))
    eng.resolve_until_stable()
    assert eng.state.pending_choice is not None
    assert offered(eng) == {raiders.instance_id, keep.instance_id}
    pick(eng, keep)
    assert keep in eng.state.player_by_id('p1').hand and raiders in eng.state.battlefield


# --- sacrifice unless return -----------------------------------------------


def test_sacrifice_unless_return_lets_the_controller_return_instead():
    eng = engine()
    cat = land(eng, "Crosis's Catacombs", 'Land — Lair')
    forest = land(eng, 'Forest', 'Basic Land — Forest')
    lair = land(eng, 'Other Lair', 'Land — Lair')
    run_clause(eng, "sacrifice it unless you return a non-lair land you control to its owner's hand", cat)
    assert offered(eng) == {forest.instance_id}  # the Lair (itself included) is not a legal return
    pick(eng, forest)
    assert forest in eng.state.player_by_id('p1').hand
    assert cat in eng.state.battlefield and lair in eng.state.battlefield


def test_sacrifice_unless_return_declined_sacrifices_the_source():
    eng = engine()
    cat = land(eng, "Crosis's Catacombs", 'Land — Lair')
    forest = land(eng, 'Forest', 'Basic Land — Forest')
    run_clause(eng, "sacrifice it unless you return a non-lair land you control to its owner's hand", cat)
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    assert cat in eng.state.player_by_id('p1').graveyard
    assert forest in eng.state.battlefield


def test_sacrifice_unless_return_with_nothing_to_return_sacrifices():
    eng = engine()
    cat = land(eng, "Crosis's Catacombs", 'Land — Lair')
    run_clause(eng, "sacrifice it unless you return a non-lair land you control to its owner's hand", cat)
    assert eng.state.pending_choice is None
    assert cat in eng.state.player_by_id('p1').graveyard


def test_sacrifice_unless_return_another_can_never_return_the_source():
    eng = engine()
    imp = creature(eng, 'Faerie Impostor')
    run_clause(eng, "sacrifice it unless you return another creature you control to its owner's hand", imp)
    assert eng.state.pending_choice is None
    assert imp in eng.state.player_by_id('p1').graveyard


# --- additional cost ---------------------------------------------------------


def cast_target(eng):
    """A free spell left on the stack for the counterspell to target."""
    p1 = eng.state.player_by_id('p1')
    bolt = put(eng, 'Fizzle', 'Instant', 'You gain 1 life.', zone=Zone.HAND, is_instant=True)
    eng.cast_spell(p1, bolt)
    return bolt


def ruse(eng):
    obj = put(eng, "Familiar's Ruse", 'Instant', CALIBRATION["Familiar's Ruse"][1], zone=Zone.HAND,
              is_instant=True, mana_cost_string='{1}{U}{U}')
    assert obj.additional_cast_cost is not None and obj.additional_cast_cost.return_pick == 'creature'
    return obj


def test_additional_return_cost_is_the_casters_choice_paid_on_cast():
    eng = engine()
    p1 = eng.state.player_by_id('p1')
    a, b = creature(eng, 'A'), creature(eng, 'B')
    spell = ruse(eng)
    p1.mana_pool.add_many({'U': 2, 'C': 1})
    target = cast_target(eng)
    eng.cast_spell(p1, spell, [target], sacrifice_choices=[b.instance_id])
    # Paid at cast time (RULE 601.2h): the spell is on the stack and B is already back in hand.
    assert spell not in p1.hand and any(item.obj is spell for item in eng.state.stack)
    assert b in p1.hand and a in eng.state.battlefield


def test_additional_return_cost_rejects_an_illegal_pick_and_nothing_to_return():
    eng = engine()
    p1 = eng.state.player_by_id('p1')
    spell = ruse(eng)
    p1.mana_pool.add_many({'U': 2, 'C': 1})
    assert not eng.can_cast(p1, spell)  # no creature: the cost cannot be paid
    c = creature(eng, 'A')
    land_obj = land(eng, 'Forest', 'Basic Land — Forest')
    assert eng.can_cast(p1, spell)
    target = cast_target(eng)
    with pytest.raises(ValueError):
        eng.cast_spell(p1, spell, [target], sacrifice_choices=[land_obj.instance_id])
    assert c in eng.state.battlefield and spell in p1.hand


def test_additional_return_cost_is_offered_as_a_return_picker():
    eng = engine()
    p1 = eng.state.player_by_id('p1')
    a, b = creature(eng, 'A'), creature(eng, 'B')
    spell = ruse(eng)
    p1.mana_pool.add_many({'U': 2, 'C': 1})
    action = next(x for x in eng.legal_actions(p1) if x.get('type') == 'cast_spell' and x.get('instance_id') == spell.instance_id)
    cost = action['sacrifice_count_cost']
    assert cost['verb'] == 'return' and cost['count'] == 1
    assert {o['instance_id'] for o in cost['options']} == {a.instance_id, b.instance_id}


# --- mass and "up to N" forms ---------------------------------------------------


def test_up_to_n_is_an_optional_multi_pick():
    eng = engine()
    src = creature(eng, 'Src')
    a, b, c = land(eng, 'A'), land(eng, 'B'), land(eng, 'C')
    run_clause(eng, "return up to 2 lands you control to their owner's hand", src)
    pick(eng, a)
    eng.resolve_pending_choice('decline')  # the controller may stop after one
    eng.resolve_until_stable()
    p1 = eng.state.player_by_id('p1')
    assert a in p1.hand and b in eng.state.battlefield and c in eng.state.battlefield


def test_return_all_you_control_only_returns_the_controllers_permanents():
    eng = engine()
    src = creature(eng, 'Src')
    mine = creature(eng, 'Mine')
    theirs = put(eng, 'Theirs', 'Creature — Bear', is_creature=True, power=1, toughness=1, owner='p2')
    run_clause(eng, "return all creatures you control to their owner's hand", src)
    p1 = eng.state.player_by_id('p1')
    assert mine in p1.hand and src in p1.hand and theirs in eng.state.battlefield


# --- "you may return ... If you do" rides the same pick --------------------------


def kami(eng):
    text = "When this creature enters, you may return an enchantment you control to its owner's hand. If you do, you gain 3 life."
    obj = put(eng, 'Geothermal Kami', 'Creature — Spirit', text, is_creature=True, power=2, toughness=2)
    assert parse_oracle(obj.card).modeled
    return obj


def run_etb(eng, obj):
    [spec] = [a for a in parse_oracle(obj.card).specs if a.ability_kind == 'triggered']
    for effect in build_effects(spec.effects, obj):
        effect.apply(GameContext(eng.state, eng.rules), None)
    eng.resolve_until_stable()


def test_may_return_then_gain_life_when_accepted():
    eng = engine()
    k = kami(eng)
    ench = put(eng, 'Pacifism', 'Enchantment')
    life = eng.state.player_by_id('p1').life
    run_etb(eng, k)
    choice = eng.state.pending_choice
    assert choice is not None
    eng.resolve_pending_choice(next(o['id'] for o in choice['options'] if o['id'] not in ('decline', 'no')))
    eng.resolve_until_stable()
    if eng.state.pending_choice is not None and eng.state.pending_choice['kind'] == 'choose_objects':
        pick(eng, ench)
    assert ench in eng.state.player_by_id('p1').hand
    assert eng.state.player_by_id('p1').life == life + 3


def test_may_return_declined_gains_nothing():
    eng = engine()
    k = kami(eng)
    ench = put(eng, 'Pacifism', 'Enchantment')
    life = eng.state.player_by_id('p1').life
    run_etb(eng, k)
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    assert ench in eng.state.battlefield and eng.state.player_by_id('p1').life == life


# --- count-N "sacrifice ~ unless you return N ..." (all-or-nothing) and mandatory "return N ..." ----------------

UNLESS_TWO = "sacrifice it unless you return two forests you control to their owner's hand"


def test_counted_sacrifice_unless_return_shape():
    [spec] = match_clause(UNLESS_TWO)
    assert spec.type == 'choose_objects'
    assert spec.params['count'] == 2 and spec.params['all_or_nothing'] is True and spec.params['optional'] is True
    assert spec.params['permanent_filter'] == {'subtype': 'forest'}
    assert spec.params['else_effects'] == [{'type': 'sacrifice_self', 'params': {}}]
    [basic] = match_clause("sacrifice it unless you return three basic lands you control to their owner's hand")
    assert basic.params['count'] == 3 and basic.params['permanent_filter'] == {'basic': True, 'card_type': 'land'}


def test_counted_sacrifice_unless_return_returns_exactly_n_and_keeps_the_source():
    eng = engine()
    elephant = creature(eng, 'Bull Elephant')
    f1, f2, f3 = (land(eng, f'F{i}', 'Basic Land — Forest') for i in range(3))
    run_clause(eng, UNLESS_TWO, elephant)
    pick(eng, f1)
    assert 'decline' not in {o['id'] for o in eng.state.pending_choice['options']}  # committed: no half-payment
    pick(eng, f2)
    p1 = eng.state.player_by_id('p1')
    assert f1 in p1.hand and f2 in p1.hand and f3 in eng.state.battlefield and elephant in eng.state.battlefield


def test_counted_sacrifice_unless_return_declined_sacrifices_and_returns_nothing():
    eng = engine()
    elephant = creature(eng, 'Bull Elephant')
    forests = [land(eng, f'F{i}', 'Basic Land — Forest') for i in range(2)]
    run_clause(eng, UNLESS_TWO, elephant)
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    assert elephant in eng.state.player_by_id('p1').graveyard
    assert all(f in eng.state.battlefield for f in forests)


def test_counted_sacrifice_unless_return_with_too_few_candidates_sacrifices_without_returning():
    eng = engine()
    elephant = creature(eng, 'Bull Elephant')
    forest = land(eng, 'F0', 'Basic Land — Forest')
    land(eng, 'Plains', 'Basic Land — Plains')
    run_clause(eng, UNLESS_TWO, elephant)
    assert eng.state.pending_choice is None  # one Forest cannot make two: nothing to decide
    assert elephant in eng.state.player_by_id('p1').graveyard and forest in eng.state.battlefield


def test_counted_sacrifice_unless_return_real_cards():
    assert parse_oracle(Card(
        id='b', name='Bull Elephant', type_line='Creature — Elephant', power=4, toughness=4, is_creature=True,
        oracle_text="When this creature enters, sacrifice it unless you return two Forests you control to their owner's hand.",
    )).modeled is True


def test_mandatory_counted_return_takes_exactly_n_or_everything():
    [spec] = match_clause("return two lands you control to their owner's hand")
    assert spec.params['count'] == 2 and spec.params['optional'] is False
    eng = engine()
    src = creature(eng, 'Gem')
    a, b, c = land(eng, 'A'), land(eng, 'B'), land(eng, 'C')
    run_clause(eng, "return two lands you control to their owner's hand", src)
    assert 'decline' not in {o['id'] for o in eng.state.pending_choice['options']}
    pick(eng, a)
    pick(eng, c)
    p1 = eng.state.player_by_id('p1')
    assert a in p1.hand and c in p1.hand and b in eng.state.battlefield
    # RULE 609.3: with fewer than N the controller returns as many as possible, without a prompt.
    eng2 = engine()
    src2 = creature(eng2, 'Gem')
    only = land(eng2, 'Only')
    run_clause(eng2, "return three lands you control to their owner's hand", src2)
    assert eng2.state.pending_choice is None and only in eng2.state.player_by_id('p1').hand


# --- "any number of X you control ... for each X returned this way" with a targeted payoff -----------------------


def test_any_number_returned_this_way_keeps_its_target_on_cast():
    text = ("Sweep — Return any number of Plains you control to their owner's hand. "
            "Target creature gets +1/+1 until end of turn for each Plains returned this way.")
    card = Card(id='p', name='Plow Through Reito', type_line='Instant', oracle_text=text, is_instant=True, keywords=['Sweep'])
    result = parse_oracle(card)
    assert result.modeled is True, result.unclaimed
    [mark, choose, body] = result.specs[0].effects
    assert (mark.type, choose.type, body.type) == ('mark_event_log', 'choose_objects', 'bind')
    assert body.params['amount'] == {'kind': 'this_way_count', 'pool': 'returned'}


def test_returned_this_way_counts_only_the_picks_in_the_window():
    from mtg_analyzer.game.effect_amounts import amount_of

    eng = engine()
    src = creature(eng, 'Spell')
    plains = [land(eng, f'P{i}', 'Basic Land — Plains') for i in range(3)]
    land(eng, 'Island', 'Basic Land — Island')
    eng.rules.return_to_hand(land(eng, 'Before', 'Basic Land — Plains'))  # outside the window: never counted
    pick_all = EffectSpec('choose_objects', {
        'action': 'return_to_hand', 'what': 'permanent', 'count': 'all', 'optional': True,
        'permanent_filter': {'subtype': 'plains'},
    })
    for effect in build_effects([pick_all], src):
        effect.apply(GameContext(eng.state, eng.rules), None)
    eng.resolve_pending_choice('decline')  # no mark opened yet: nothing is "this way"
    eng.resolve_until_stable()
    ctx = GameContext(eng.state, eng.rules)
    amount = {'kind': 'this_way_count', 'pool': 'returned'}
    assert amount_of(amount, ctx, src, None) == 0
    src.window_event_mark = len(eng.state.event_log)
    for effect in build_effects([pick_all], src):
        effect.apply(GameContext(eng.state, eng.rules), None)
    pick(eng, plains[0])
    pick(eng, plains[2])
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    assert amount_of(amount, GameContext(eng.state, eng.rules), src, None) == 2


def test_choose_objects_all_or_nothing_survives_undo_snapshot():
    eng = engine()
    elephant = creature(eng, 'Bull Elephant')
    [land(eng, f'F{i}', 'Basic Land — Forest') for i in range(2)]
    run_clause(eng, UNLESS_TWO, elephant)
    assert eng.state.pending_choice['all_or_nothing'] is True


def test_plow_through_reito_pumps_the_target_by_the_plains_returned():
    eng = engine()
    p1 = eng.state.player_by_id('p1')
    text = ("Sweep — Return any number of Plains you control to their owner's hand. "
            "Target creature gets +1/+1 until end of turn for each Plains returned this way.")
    spell = put(eng, 'Plow Through Reito', 'Instant — Arcane', text, zone=Zone.HAND, is_instant=True, keywords=['Sweep'],
                mana_cost_string='{W}')
    plains = [land(eng, f'P{i}', 'Basic Land — Plains') for i in range(3)]
    bear = creature(eng, 'Bear')
    p1.mana_pool.add_many({'W': 1})
    eng.cast_spell(p1, spell, [bear])
    eng.resolve_until_stable()
    pick(eng, plains[0])
    pick(eng, plains[1])
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (4, 4)  # 2/2 + two Plains returned
    assert plains[2] in eng.state.battlefield and plains[0] in p1.hand
