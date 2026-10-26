"""Tests for the rules engine + game engine.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.*/R4.*,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md, mtg_analyzer/game/.
"""

from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.effects.core import ActivatedAbility

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import DealDamageEffect


from engine_test_helpers import land, creature, make_engine, obj_on_battlefield, _shock_spell


def test_hexproof_creature_cannot_be_targeted_by_an_opponent():
    eng = make_engine([land()], [land()], hand=0)
    hex_creature = obj_on_battlefield(
        eng.state, eng, creature(keywords=["Hexproof"]), controller="p2"
    )
    bind_from_catalogue(hex_creature)
    plain = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    opponent_source = obj_on_battlefield(eng.state, eng, creature(), controller="p1")

    spec = TargetSpec(kind="creature")
    options = legal_targets(eng.state, "p1", spec, source=opponent_source)
    ids = {o["instance_id"] for o in options}
    assert hex_creature.instance_id not in ids
    assert plain.instance_id in ids

    # Hexproof doesn't stop the controller's own spells/abilities.
    own_source = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    own_options = legal_targets(eng.state, "p2", spec, source=own_source)
    assert hex_creature.instance_id in {o["instance_id"] for o in own_options}


def test_ward_pushes_a_real_stack_item_above_the_spell():
    # RULE 603.3: ward is a triggered ability that becomes its own object on
    # the stack — not an inline choice — so both players get a normal
    # priority window to respond to it before it resolves.
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 2})
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "{2}"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])

    assert eng.state.pending_choice is None  # nothing resolved yet
    assert len(eng.state.stack) == 2
    assert eng.state.stack[0].obj is spell  # the spell sits underneath
    top = eng.state.stack[1]
    assert top.category == "triggered_ability"
    assert top.controller_id == "p2"  # RULE 603.3a: the warded permanent's controller
    assert "Ward" in top.description


def test_ward_paid_lets_the_spell_resolve():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 2})
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "{2}"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()  # resolves the ward ability, opening its choice
    choice = eng.state.pending_choice
    assert choice["kind"] == "ward"
    assert choice["player_id"] == "p1"  # the caster decides, not p2

    eng.resolve_pending_choice("pay")
    assert warded not in eng.state.battlefield  # 3 damage killed the 2/2
    assert p1.mana_pool.total() == 0


def test_ward_declined_counters_the_spell():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 2})
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "{2}"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()
    eng.resolve_pending_choice("decline")

    assert warded in eng.state.battlefield  # never took the damage
    assert warded.damage_marked == 0
    assert not eng.state.stack  # the spell was countered, not resolved
    assert spell in p1.graveyard


def test_ward_uncastable_cost_counters_the_spell_without_a_choice():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})  # nothing left over for ward's {2}
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "{2}"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()  # no real decision — the ward ability auto-counters

    assert eng.state.pending_choice is None
    assert not eng.state.stack
    assert warded in eng.state.battlefield


def test_ward_does_not_trigger_against_its_own_controller():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p1")
    warded.parametric_keywords = {"ward": {"cost": "{2}"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])

    assert len(eng.state.stack) == 1  # no ward ability was pushed at all
    eng.resolve_until_stable()
    assert warded not in eng.state.battlefield


def test_ward_triggers_on_a_targeted_activated_ability():
    from mtg_analyzer.game.costs import parse_activation_cost
    from mtg_analyzer.game.effects.core import ActivatedAbility, DealDamageEffect

    eng = make_engine([land()], [], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "{1}"}}
    source = obj_on_battlefield(eng.state, eng, creature(name="Zapper", cost="{1}"))
    source.summoning_sick = False
    source.activated_abilities.append(
        ActivatedAbility(
            effects=[DealDamageEffect(amount=3, target_kind="creature")],
            cost=parse_activation_cost("{T}:"),
            source=source,
        )
    )
    p1.mana_pool.add_many({"C": 1})

    eng.activate_ability(p1, source, 0, targets=[warded])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "ward"

    eng.resolve_pending_choice("decline")
    assert warded in eng.state.battlefield
    assert not eng.state.stack


def test_ward_pay_life_cost():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})
    start_life = p1.life
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "Pay 3 life"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "ward"

    eng.resolve_pending_choice("pay")
    assert p1.life == start_life - 3
    assert warded not in eng.state.battlefield


def test_ward_x_cost_selector_is_recognized_from_the_where_x_is_clause():
    from mtg_analyzer.game.costs import parse_activation_cost

    cost = parse_activation_cost("Pay {X}, where X is the number of creatures you control.")
    assert cost.mana.has_variable
    assert cost.x_selector == "creatures_you_control"


def test_ward_x_cost_unrecognized_selector_leaves_x_unset():
    # RULE 107.3c fallback: an unrecognized "where X is …" phrase (no real
    # card uses this vocabulary word) leaves `x_selector` unset rather than
    # guessed — X then stays 0 at resolution time.
    from mtg_analyzer.game.costs import parse_activation_cost

    cost = parse_activation_cost("Pay {X}, where X is the number of Zombies you control.")
    assert cost.mana.has_variable
    assert cost.x_selector is None


def test_ward_x_cost_resolves_against_the_board_at_resolution_time_not_trigger_time():
    # RULE 702.21b: "This value is determined at the time the ability
    # resolves, not locked in as the ability triggers" — p2 gains a second
    # creature *after* the ward ability is placed on the stack but *before*
    # it resolves; X must reflect the board at resolution (2), not however
    # many creatures p2 controlled when the spell was cast (1).
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 2})
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {
        "ward": {"cost": "Pay {X}, where X is the number of creatures you control."}
    }
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    assert len(eng.state.stack) == 2  # the ward ability sits on top of the spell

    obj_on_battlefield(eng.state, eng, creature(power=1, toughness=1), controller="p2")

    eng.rules.resolve_top_of_stack()  # resolves the ward ability itself
    choice = eng.state.pending_choice
    assert choice["kind"] == "ward"

    eng.resolve_pending_choice("pay")
    assert p1.mana_pool.total() == 0


def test_ward_x_cost_uncastable_counters_the_spell_without_a_choice():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})  # nothing left over for ward's X
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {
        "ward": {"cost": "Pay {X}, where X is the number of creatures you control."}
    }
    obj_on_battlefield(eng.state, eng, creature(power=1, toughness=1), controller="p2")
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()  # no real decision — X=1 isn't payable, auto-countered

    assert eng.state.pending_choice is None
    assert not eng.state.stack
    assert warded in eng.state.battlefield


def test_ward_discard_cost():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})
    filler = GameObject(creature(name="Filler"), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(filler, Zone.HAND)
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "Discard a card"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    hand_before_discard = len(p1.hand)  # the spell itself already left the hand
    eng.resolve_until_stable()
    eng.resolve_pending_choice("pay")

    assert len(p1.hand) == hand_before_discard - 1
    assert filler in p1.graveyard
    assert warded not in eng.state.battlefield


def test_ward_sacrifice_cost():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})
    fodder = obj_on_battlefield(eng.state, eng, creature(name="Fodder"))
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "Sacrifice a creature"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()
    eng.resolve_pending_choice("pay")

    assert fodder not in eng.state.battlefield
    assert warded not in eng.state.battlefield


def test_ward_sacrifice_cost_unpayable_counters_without_a_choice():
    # p1 controls no creature at all, so "Sacrifice a creature" can't be paid.
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "Sacrifice a creature"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()

    assert eng.state.pending_choice is None
    assert not eng.state.stack
    assert warded in eng.state.battlefield


def test_ward_two_simultaneous_wards_each_ask_in_turn():
    # RULE 702.21c: an item targeting two warded permanents triggers two
    # independent ward abilities, each its own stack object, asked one at a
    # time as the stack resolves. Built via `RulesEngine.cast_spell` directly
    # with two targets so `check_ward` sees both, independent of whether the
    # spell's own one-shot effect happens to read more than `targets[0]`.
    from mtg_analyzer.game.effects.core import DealDamageEffect

    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 3})
    a = obj_on_battlefield(eng.state, eng, creature(name="A", power=2, toughness=2), controller="p2")
    a.parametric_keywords = {"ward": {"cost": "{1}"}}
    b = obj_on_battlefield(eng.state, eng, creature(name="B", power=2, toughness=2), controller="p2")
    b.parametric_keywords = {"ward": {"cost": "{2}"}}
    card = Card(
        id="Fake Bolt", name="Fake Bolt", type_line="Sorcery",
        mana_cost_string="{R}", converted_mana_cost=1, is_sorcery=True,
    )
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    spell.spell_effects = [DealDamageEffect(amount=3, target_kind="creature")]

    eng.rules.cast_spell(p1, spell, targets=[a, b])
    assert len(eng.state.stack) == 3  # the spell + a's ward + b's ward

    eng.resolve_until_stable()
    first = eng.state.pending_choice
    assert first["kind"] == "ward"
    eng.resolve_pending_choice("pay")

    second = eng.state.pending_choice
    assert second["kind"] == "ward"
    assert second is not first
    eng.resolve_pending_choice("pay")

    assert not eng.state.stack  # both wards paid — the spell resolved
    assert a not in eng.state.battlefield  # took the 3 damage (targets[0])
    assert b in eng.state.battlefield


def test_ward_one_of_two_simultaneous_wards_declined_counters_the_spell():
    # RULE 702.21c/608.2b: once the spell is countered by the first ward,
    # the second ward's own resolution finds nothing left to counter and
    # simply does nothing — it never asks the caster to pay again.
    from mtg_analyzer.game.effects.core import DealDamageEffect

    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 3})
    a = obj_on_battlefield(eng.state, eng, creature(name="A", power=2, toughness=2), controller="p2")
    a.parametric_keywords = {"ward": {"cost": "{1}"}}
    b = obj_on_battlefield(eng.state, eng, creature(name="B", power=2, toughness=2), controller="p2")
    b.parametric_keywords = {"ward": {"cost": "{2}"}}
    card = Card(
        id="Fake Bolt", name="Fake Bolt", type_line="Sorcery",
        mana_cost_string="{R}", converted_mana_cost=1, is_sorcery=True,
    )
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    spell.spell_effects = [DealDamageEffect(amount=3, target_kind="creature")]

    eng.rules.cast_spell(p1, spell, targets=[a, b])
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "ward"
    eng.resolve_pending_choice("decline")  # counters the spell right away

    assert not eng.state.stack  # the second ward found nothing to counter
    assert eng.state.pending_choice is None
    assert a in eng.state.battlefield
    assert b in eng.state.battlefield
    assert spell in p1.graveyard
