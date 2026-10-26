"""Tests for the rules engine + game engine.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.*/R4.*,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md, mtg_analyzer/game/.
"""


from mtg_analyzer.models.game.game_object import GameObject, Zone


from engine_test_helpers import land, creature, instant, make_engine


def test_commander_tax_adds_two_per_previous_cast():
    # RULE 903.8: {2} more per previous cast from the command zone.
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Cmdr", cost="{G}"), owner_id="p1", is_commander=True)
    p1.add_to_zone(commander, Zone.COMMAND)

    # First cast: no tax → costs {G}.
    assert eng.commander_tax(p1, commander) == 0
    p1.mana_pool.add_many({"G": 1})
    eng.cast_spell(p1, commander)
    eng.resolve_until_stable()


def test_commander_tax_adds_two_per_previous_cast():
    # RULE 903.8: {2} more per previous cast from the command zone.
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Cmdr", cost="{G}"), owner_id="p1", is_commander=True)
    p1.add_to_zone(commander, Zone.COMMAND)

    # First cast: no tax → costs {G}.
    assert eng.commander_tax(p1, commander) == 0
    p1.mana_pool.add_many({"G": 1})
    eng.cast_spell(p1, commander)
    eng.resolve_until_stable()

    # Send it back to the command zone and cast again: now taxed {2}.
    eng.state.remove_from_battlefield(commander)
    p1.add_to_zone(commander, Zone.COMMAND)
    assert eng.commander_tax(p1, commander) == 2
    assert eng.effective_cast_cost(p1, commander).converted_mana_cost == 3  # {2}{G}
    p1.mana_pool.add_many({"G": 1, "C": 2})
    assert eng.can_cast(p1, commander)
    eng.cast_spell(p1, commander)
    eng.state.remove_from_battlefield(commander)
    p1.add_to_zone(commander, Zone.COMMAND)
    assert eng.commander_tax(p1, commander) == 4


def test_commander_dying_offers_command_zone_choice_and_can_move_there():
    # RULE 903.9a: a commander that dies actually reaches the graveyard —
    # unlike a non-commander, its owner is then offered a one-time SBA
    # choice to move it to the command zone instead of leaving it there.
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(
        creature(name="Commander Bear", toughness=1), owner_id="p1", is_commander=True
    )
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.rules.deal_damage(commander, 1)
    eng.rules.check_state_based_actions()

    assert commander not in eng.state.battlefield
    assert commander in p1.graveyard
    assert commander not in p1.command
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "commander_zone"
    assert choice["instance_id"] == commander.instance_id

    eng.rules.resolve_choice("command")

    assert commander in p1.command
    assert commander not in p1.graveyard
    assert eng.state.pending_choice is None


def test_commander_moved_to_the_command_zone_forgets_its_battlefield_state():
    # RULE 400.7 (bug report, 2026-09-04): moving into the command zone is
    # a zone change like any other — the commander must not carry
    # combat/counter state from its previous life on the battlefield into
    # its next one. A commander that died mid-attack once carried a stale
    # `attacking`/`combat_defender` all the way through a same-turn recast,
    # corrupting `attackers()`/every per-attacker aggregate built from it.
    eng = make_engine([land()], [land()], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(
        creature(name="Commander Bear", toughness=1), owner_id="p1", is_commander=True
    )
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [commander])
    assert commander.attacking is True
    assert commander.combat_defender is not None
    commander.counters["+1/+1"] = 3  # toughness 1 -> 4; deal_damage below must match

    eng.rules.deal_damage(commander, 4)
    eng.rules.check_state_based_actions()
    eng.rules.resolve_choice("command")

    assert commander in p1.command
    assert commander.attacking is False
    assert commander.combat_defender is None
    assert commander.counters == {}
    assert commander.damage_marked == 0
    assert commander.summoning_sick is False


def test_commander_dying_choice_declined_stays_in_graveyard():
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(
        creature(name="Commander Bear", toughness=1), owner_id="p1", is_commander=True
    )
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.rules.deal_damage(commander, 1)
    eng.rules.check_state_based_actions()
    eng.rules.resolve_choice("decline")

    assert commander in p1.graveyard
    assert commander not in p1.command
    assert eng.state.pending_choice is None


def test_countered_commander_spell_offers_command_zone_choice():
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Commander Bear"), owner_id="p1", is_commander=True)
    p1.add_to_zone(commander, Zone.COMMAND)
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 1})
    eng.cast_spell(p1, commander)

    eng.rules.counter_spell(commander)

    assert commander in p1.graveyard
    assert commander not in p1.command
    choice = eng.state.pending_choice
    assert choice is None  # counter_spell doesn't itself check SBAs

    eng.rules.check_state_based_actions()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "commander_zone"
    eng.rules.resolve_choice("command")

    assert commander in p1.command
    assert commander not in p1.graveyard


def test_exiled_commander_offers_command_zone_choice():
    # RULE 903.9a covers exile identically to graveyard.
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Commander Bear"), owner_id="p1", is_commander=True)
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.rules.exile(commander)
    eng.rules.check_state_based_actions()

    assert commander in p1.exile
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "commander_zone"

    eng.rules.resolve_choice("command")

    assert commander in p1.command
    assert commander not in p1.exile


def test_bounced_commander_offers_command_zone_choice():
    # RULE 903.9b: hand (unlike graveyard/exile) is a replacement effect —
    # the choice opens immediately, not on the next SBA check.
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Commander Bear"), owner_id="p1", is_commander=True)
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.rules.return_to_hand(commander)

    assert commander in p1.hand
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "commander_zone"
    assert choice["instance_id"] == commander.instance_id

    eng.rules.resolve_choice("command")

    assert commander in p1.command
    assert commander not in p1.hand


def test_bounced_commander_choice_declined_stays_in_hand():
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Commander Bear"), owner_id="p1", is_commander=True)
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.rules.return_to_hand(commander)
    eng.rules.resolve_choice("decline")

    assert commander in p1.hand
    assert commander not in p1.command


def test_non_commander_permanent_never_offers_command_zone_choice():
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    bear = GameObject(creature(name="Plain Bear", toughness=1), owner_id="p1")
    bear.summoning_sick = False
    eng.state.add_to_battlefield(bear)

    eng.rules.deal_damage(bear, 1)
    eng.rules.check_state_based_actions()

    assert bear in p1.graveyard
    assert eng.state.pending_choice is None


def test_instant_can_be_cast_at_instant_speed():
    eng = make_engine([instant()], [land()], hand=1)
    eng.begin_turn()
    eng.state.current_step = "upkeep"  # not a main phase, stack empty
    p1 = eng.state.active_player
    p1.mana_pool.add("R", 1)
    assert eng.can_cast(p1, p1.hand[0])


def test_phyrexian_mana_payment_drains_life():
    # Regression: ManaPool.pay computes the life spent on a Phyrexian pip
    # but cast_spell used to discard it, so paying {R/P} with life never
    # actually cost anything (RULE 119.4).
    eng = make_engine([instant(name="Gut Shot", cost="{R/P}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    assert p1.life == 20
    eng.cast_spell(p1, p1.hand[0])  # empty pool -> must pay 2 life instead
    assert p1.life == 18


def test_x_spell_defaults_to_x_zero():
    eng = make_engine([instant(name="Fireball", cost="{X}{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add("R", 1)  # only enough for X=0
    assert eng.can_cast(p1, p1.hand[0])  # X=0 is always a legal announcement
    eng.cast_spell(p1, p1.hand[0])
    assert eng.state.stack[-1].x == 0
    assert p1.mana_pool.pool["R"] == 0


def test_x_spell_pays_the_announced_value():
    eng = make_engine([instant(name="Fireball", cost="{X}{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 3})
    assert not eng.can_cast(p1, p1.hand[0], x=4)  # only 3 generic available
    assert eng.can_cast(p1, p1.hand[0], x=3)
    eng.cast_spell(p1, p1.hand[0], x=3)
    assert eng.state.stack[-1].x == 3
    assert p1.mana_pool.total() == 0


def test_x_spell_legal_action_reports_max_affordable_x():
    eng = make_engine([instant(name="Fireball", cost="{X}{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 3})
    [cast_action] = [
        a for a in eng.legal_actions(p1) if a["type"] == "cast_spell"
    ]
    assert cast_action["has_x"] is True
    assert cast_action["max_x"] == 3
