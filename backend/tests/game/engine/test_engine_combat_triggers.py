"""Tests for the rules engine + game engine.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.*/R4.*,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md, mtg_analyzer/game/.
"""


from mtg_analyzer.game.binding.core import bind_from_catalogue


from engine_test_helpers import land, creature, make_engine, obj_on_battlefield, _to_declare_attackers, _attack_then_blockers_step, _rampage_attacker


def test_annihilator_makes_defending_player_sacrifice_permanents():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state,
        eng,
        creature(
            power=2,
            toughness=2,
            keywords=["Annihilator"],
            oracle_text="Annihilator 2 (Whenever this creature attacks, "
            "defending player sacrifices two permanents.)",
        ),
    )
    bind_from_catalogue(attacker)
    for _ in range(3):
        obj_on_battlefield(eng.state, eng, creature(), controller="p2")

    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.resolve_until_stable()

    # RULE 601.2c-style choice (ENG-2): three permanents, only two must be
    # sacrificed, so the defending player picks rather than the engine
    # auto-choosing.
    choice = eng.state.pending_choice
    assert choice is not None and choice["action"] == "sacrifice"
    first_pick = choice["options"][0]["instance_id"]
    eng.rules.resolve_choice(first_pick)
    assert eng.state.pending_choice is not None  # one more to pick
    second_pick = eng.state.pending_choice["options"][0]["instance_id"]
    eng.rules.resolve_choice(second_pick)
    eng.resolve_until_stable()

    remaining = [o for o in eng.state.battlefield if o.controller_id == "p2"]
    assert len(remaining) == 1


def test_afflict_causes_defending_player_to_lose_life_on_block():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state,
        eng,
        creature(
            power=2,
            toughness=2,
            keywords=["Afflict"],
            oracle_text="Afflict 3 (Whenever this creature becomes blocked, "
            "defending player loses 3 life.)",
        ),
    )
    bind_from_catalogue(attacker)
    blocker = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])
    eng.resolve_until_stable()

    assert eng.state.player_by_id("p2").life == 17


def test_bushido_pumps_the_blocker_when_it_blocks():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(eng.state, eng, creature(power=3, toughness=3))
    blocker = obj_on_battlefield(
        eng.state,
        eng,
        creature(
            power=1,
            toughness=1,
            keywords=["Bushido"],
            oracle_text="Bushido 1 (Whenever this creature blocks or becomes "
            "blocked, it gets +1/+1 until end of turn.)",
        ),
        controller="p2",
    )
    bind_from_catalogue(blocker)
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])
    eng.resolve_until_stable()

    assert blocker.power == 2
    assert blocker.toughness == 2


def test_rampage_does_not_trigger_with_only_one_blocker():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = _rampage_attacker(eng)
    bind_from_catalogue(attacker)
    blocker = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])
    eng.resolve_until_stable()

    assert attacker.power == 2  # "beyond the first" — a single blocker adds nothing
    assert attacker.toughness == 2


def test_rampage_pumps_once_per_blocker_beyond_the_first():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = _rampage_attacker(eng, n=2)
    bind_from_catalogue(attacker)
    blocker1 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    blocker2 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    blocker3 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(
        p2,
        [
            {"blocker": blocker1, "attacker": attacker},
            {"blocker": blocker2, "attacker": attacker},
            {"blocker": blocker3, "attacker": attacker},
        ],
    )
    eng.resolve_until_stable()

    # Three blockers, two "beyond the first" — +2/+2 twice.
    assert attacker.power == 6
    assert attacker.toughness == 6


def test_rampage_goes_on_the_stack_as_a_real_triggered_ability():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = _rampage_attacker(eng)
    bind_from_catalogue(attacker)
    blocker1 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    blocker2 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(
        p2,
        [
            {"blocker": blocker1, "attacker": attacker},
            {"blocker": blocker2, "attacker": attacker},
        ],
    )

    assert len(eng.state.stack) == 1  # a real stack object, not an inline effect
    top = eng.state.stack[-1]
    assert top.controller_id == "p1"  # RULE 603.3a: the attacker's own controller
    assert attacker.power == 2  # not yet resolved

    eng.resolve_until_stable()
    assert attacker.power == 4
