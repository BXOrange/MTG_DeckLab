"""The *qualified* combat-restriction family (RULE 508.1a / 509.1b).

The sibling of `test_combat_restriction_family.py`, which covers the plain
flag forms ("~ can't attack."). Everything here carries a **parameter** those
flags can't hold, and so rides a different mechanism:

* a blocker **filter** — "~ can't be blocked by creatures with power 2 or
  less" / "…except by Walls" / "…by more than one creature" / "…except by two
  or more creatures", plus the resolve-time "…this turn" variant;
* an **unless** condition — "~ can't attack unless defending player controls
  an Island", over a closed board/turn-state vocabulary
  (`GameEngine._COMBAT_CONDITIONS`);
* **"…alone"** — both the restriction ("~ can't attack alone.") and the
  trigger ("Whenever ~ attacks alone, …", `EventType.ATTACKS_ALONE`);
* the RULE 605.1a **"unless they're mana abilities"** carve-out on an
  activation prohibition;
* the resolve-time "**target creature can't block this turn**" one-shot —
  the family's largest half, and an ordinary effect rather than a static.

Each test drives real oracle text through `parse_oracle` (asserting the card
is fully `MODELED`) **and** binds + exercises it against a real
`GameEngine`, per the project's "parse-only verification has masked real
runtime bugs" lesson.

Reference: mtg_analyzer/parser/oracle/catalogue/{static_handlers,handlers}.py,
mtg_analyzer/game/{combat,continuous,effects,game_engine}.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, oracle_text="", power=2, toughness=2, keywords=None,
              type_line="Creature — Dragon"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []),
    )


def _land(name, type_line="Land — Island"):
    return Card(id=name, name=name, type_line=type_line, is_land=True, oracle_text="")


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _modeled(card):
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    assert result.unclaimed == []
    return result


def _attack(attacker, defender_id="p2"):
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": defender_id, "label": defender_id}


# -- Blocking filters (RULE 509.1b) ------------------------------------------


def test_cant_be_blocked_by_power_filter():
    card = _creature("Amrou Kithkin", "~ can't be blocked by creatures with power 3 or greater.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    weak = _put(state, _creature("Squire", power=1, toughness=1), controller="p2")
    strong = _put(state, _creature("Ogre", power=4, toughness=4), controller="p2")
    continuous.recompute(state)
    _attack(attacker)

    defender = state.player_by_id("p2")
    assert eng.can_block(defender, weak, attacker) is True
    assert eng.can_block(defender, strong, attacker) is False


def test_cant_be_blocked_except_by_subtype():
    card = _creature("Gate Guard", "~ can't be blocked except by Walls.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    wall = _put(state, _creature("Stone Wall", type_line="Creature — Wall"), controller="p2")
    bear = _put(state, _creature("Bear"), controller="p2")
    continuous.recompute(state)
    _attack(attacker)

    defender = state.player_by_id("p2")
    assert eng.can_block(defender, wall, attacker) is True
    assert eng.can_block(defender, bear, attacker) is False


def test_cant_be_blocked_by_creatures_with_greater_power_is_relative():
    # The one *relative* filter: greater than the attacker's own power, so it
    # has to be re-evaluated per blocker rather than baked in at parse time.
    card = _creature("Ant-Man", "~ can't be blocked by creatures with greater power.", power=3)
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    equal = _put(state, _creature("Peer", power=3, toughness=3), controller="p2")
    bigger = _put(state, _creature("Giant", power=5, toughness=5), controller="p2")
    continuous.recompute(state)
    _attack(attacker)

    defender = state.player_by_id("p2")
    assert eng.can_block(defender, equal, attacker) is True
    assert eng.can_block(defender, bigger, attacker) is False


def test_max_blockers_caps_the_whole_block():
    card = _creature("Bristling Boar", "~ can't be blocked by more than one creature.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    a = _put(state, _creature("Bear A"), controller="p2")
    b = _put(state, _creature("Bear B"), controller="p2")
    continuous.recompute(state)
    eng.start()
    _attack(attacker)
    state.current_step = "declare_blockers"

    assert combat.max_blockers(attacker) == 1
    defender = state.player_by_id("p2")
    with pytest.raises(ValueError):
        eng.declare_blockers(defender, [{"blocker": a, "attacker": attacker},
                                        {"blocker": b, "attacker": attacker}])
    # State untouched by the rejected declaration — a legal single block still works.
    eng.declare_blockers(defender, [{"blocker": a, "attacker": attacker}])
    assert attacker.blocked_by == [a.instance_id]


def test_min_blockers_printed_in_full_raises_the_menace_floor():
    card = _creature(
        "Kraken", "~ can't be blocked except by three or more creatures.", power=6, toughness=6
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    blockers = [_put(state, _creature(f"Bear {i}"), controller="p2") for i in range(3)]
    continuous.recompute(state)
    eng.start()
    _attack(attacker)
    state.current_step = "declare_blockers"

    assert combat.min_blockers(attacker) == 3
    defender = state.player_by_id("p2")
    with pytest.raises(ValueError):
        eng.declare_blockers(
            defender, [{"blocker": b, "attacker": attacker} for b in blockers[:2]]
        )
    eng.declare_blockers(defender, [{"blocker": b, "attacker": attacker} for b in blockers])
    assert len(attacker.blocked_by) == 3


def test_attached_grant_plus_restriction_in_one_clause():
    # Alpha Authority-shaped: a keyword grant and a blocking restriction share
    # one printed sentence, which the plain `has <keyword>` grant regex can't
    # `fullmatch` on its own.
    aura = Card(
        id="Alpha Authority", name="Alpha Authority", type_line="Enchantment — Aura",
        oracle_text="Enchant creature\n"
                    "Enchanted creature has hexproof and can't be blocked by "
                    "more than one creature.",
    )
    _modeled(aura)

    eng = _engine()
    state = eng.state
    host = _put(state, _creature("Bear"))
    enchantment = _put(state, aura)
    enchantment.attached_to = host.instance_id
    continuous.recompute(state)

    assert combat.has_hexproof(host) is True
    assert combat.max_blockers(host) == 1


# -- The same two set shapes, printed on the blocker (RULE 509.1a) -----------


def test_can_block_only_creatures_with_flying():
    # Flying on the blocker too, or RULE 702.9b's evasion check would reject
    # the flying attacker before this restriction is even reached.
    card = _creature("Wall of Air", "~ can block only creatures with flying.",
                     type_line="Creature — Wall", keywords=["Flying"])
    _modeled(card)

    eng = _engine()
    state = eng.state
    blocker = _put(state, card, controller="p2")
    flier = _put(state, _creature("Drake", keywords=["Flying"]))
    ground = _put(state, _creature("Bear"))
    continuous.recompute(state)
    _attack(flier)
    _attack(ground)

    defender = state.player_by_id("p2")
    assert eng.can_block(defender, blocker, flier) is True
    assert eng.can_block(defender, blocker, ground) is False


def test_cant_block_creatures_with_power_filter():
    card = _creature("Timid Guard", "~ can't block creatures with power 3 or greater.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    blocker = _put(state, card, controller="p2")
    small = _put(state, _creature("Bear", power=2, toughness=2))
    big = _put(state, _creature("Ogre", power=4, toughness=4))
    continuous.recompute(state)
    _attack(small)
    _attack(big)

    defender = state.player_by_id("p2")
    assert eng.can_block(defender, blocker, small) is True
    assert eng.can_block(defender, blocker, big) is False


def test_inverted_phrasing_restricts_the_attacker_not_the_blocker():
    # Sedge Troll-shaped: the printed *subject* is the blocker set and the
    # ability's own source is the object ("… can't block it"), but the rule
    # is the same `cant_be_blocked_by` restriction on the source.
    card = _creature(
        "Sedge Troll", "Creatures with power less than ~'s power can't block it.",
        power=3, toughness=3,
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    weaker = _put(state, _creature("Squire", power=1, toughness=1), controller="p2")
    equal = _put(state, _creature("Peer", power=3, toughness=3), controller="p2")
    continuous.recompute(state)
    _attack(attacker)

    defender = state.player_by_id("p2")
    assert eng.can_block(defender, weaker, attacker) is False
    assert eng.can_block(defender, equal, attacker) is True


# -- The resolve-time "…this turn" sibling -----------------------------------


def test_cant_be_blocked_by_filter_this_turn_is_cleared_at_cleanup():
    card = _creature(
        "Cavern Stomper",
        "{3}{G}: ~ can't be blocked by creatures with power 2 or less this turn.",
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    small = _put(state, _creature("Squire", power=1, toughness=1), controller="p2")
    continuous.recompute(state)
    _attack(attacker)
    defender = state.player_by_id("p2")
    assert eng.can_block(defender, small, attacker) is True

    ability = attacker.activated_abilities[0]
    ability.effects[0].apply(eng.rules, None)
    assert eng.can_block(defender, small, attacker) is False

    # RULE 514.2: unlike the standing static, this one wears off.
    eng._step_cleanup()
    assert attacker.temp_combat_restrictions == []
    _attack(attacker)  # cleanup also ends combat; re-declare to re-ask the question
    assert eng.can_block(defender, small, attacker) is True


# -- "unless <condition>" (RULE 508.1a / 509.1a) -----------------------------


def test_cant_attack_unless_defending_player_controls_a_land_type():
    card = _creature("Armored Galleon", "~ can't attack unless defending player controls an Island.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    continuous.recompute(state)

    active = state.active_player
    assert eng._can_attack(active, attacker) is False
    _put(state, _land("Island"), controller="p2")
    continuous.recompute(state)
    assert eng._can_attack(active, attacker) is True


def test_cant_attack_unless_condition_is_checked_against_the_chosen_defender():
    # A three-player-shaped check in two: the condition is about the player
    # actually being attacked, so an offer-time "could attack somebody" pass
    # isn't enough — `declare_attackers` re-checks the assigned defender.
    card = _creature("Armored Galleon", "~ can't attack unless defending player controls an Island.")
    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    continuous.recompute(state)
    eng.start()
    while state.current_step != "declare_attackers":
        eng.advance_step()

    with pytest.raises(ValueError):
        eng.declare_attackers(state.active_player, [attacker])


def test_cant_attack_or_block_unless_you_control_another_subtype():
    card = _creature(
        "Blind-Spot Giant", "~ can't attack or block unless you control another Giant.",
        type_line="Creature — Giant",
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    obj = _put(state, card)
    opponent_attacker = _put(state, _creature("Raider"), controller="p2")
    continuous.recompute(state)
    _attack(opponent_attacker, defender_id="p1")

    active = state.active_player
    defender = state.player_by_id("p1")
    assert eng._can_attack(active, obj) is False
    assert eng.can_block(defender, obj, opponent_attacker) is False

    # "another" — the restricted creature can't satisfy its own condition.
    _put(state, _creature("Fellow Giant", type_line="Creature — Giant"))
    continuous.recompute(state)
    assert eng._can_attack(active, obj) is True
    assert eng.can_block(defender, obj, opponent_attacker) is True


def test_cant_attack_unless_a_creature_died_this_turn_reads_turn_history():
    card = _creature(
        "Bontu the Glorified",
        "~ can't attack or block unless a creature died under your control this turn.",
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    obj = _put(state, card)
    victim = _put(state, _creature("Doomed Bear"))
    continuous.recompute(state)

    active = state.active_player
    assert eng._can_attack(active, obj) is False

    eng.rules.destroy(victim)
    assert state.creatures_died_this_turn.get("p1", 0) == 1
    assert eng._can_attack(active, obj) is True

    # RULE 700.4 history is per turn — a new turn clears it.
    eng.begin_turn()
    assert state.creatures_died_this_turn == {}


def test_cant_block_unless_you_control_another_of_two_subtypes():
    card = _creature(
        "Howlpack Wolf", "~ can't block unless you control another Wolf or Werewolf.",
        type_line="Creature — Wolf",
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    blocker = _put(state, card, controller="p2")
    attacker = _put(state, _creature("Raider"))
    continuous.recompute(state)
    _attack(attacker)

    defender = state.player_by_id("p2")
    assert eng.can_block(defender, blocker, attacker) is False
    _put(state, _creature("Pack Mate", type_line="Creature — Werewolf"), controller="p2")
    continuous.recompute(state)
    assert eng.can_block(defender, blocker, attacker) is True


def test_unrecognised_condition_fails_closed_toward_cant_attack():
    # A `combat_restriction` whose condition kind isn't in the whitelist must
    # keep the restriction biting, never silently evaporate it.
    eng = _engine()
    state = eng.state
    obj = _put(state, _creature("Mystery Beast"))
    obj._combat_restrictions = [
        {"kind": "cant_attack_unless", "condition": {"kind": "invented_condition"}}
    ]
    assert eng._can_attack(state.active_player, obj) is False


# -- "…alone" (RULE 508.1a / 506.5) ------------------------------------------


def test_cant_attack_alone_is_enforced_over_the_whole_declared_attack():
    card = _creature("Lone Wolf", "~ can't attack alone.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    loner = _put(state, card)
    friend = _put(state, _creature("Bear"))
    continuous.recompute(state)
    eng.start()
    while state.current_step != "declare_attackers":
        eng.advance_step()

    # Declaring it alone is legal *per creature* — the restriction is about
    # the finished attack, so it bites as the step closes.
    eng.declare_attackers(state.active_player, [loner])
    with pytest.raises(ValueError):
        eng.advance_step()

    eng.declare_attackers(state.active_player, [friend])
    eng.advance_step()
    assert loner.attacking and friend.attacking


def test_cant_be_blocked_while_attacking_alone():
    card = _creature("Gutter Skulker", "~ can't be blocked as long as it's attacking alone.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    blocker = _put(state, _creature("Bear"), controller="p2")
    continuous.recompute(state)
    _attack(attacker)

    defender = state.player_by_id("p2")
    assert eng.can_block(defender, blocker, attacker) is False

    # A second attacker makes it blockable again — a conditional evasion,
    # re-asked per block rather than stamped on at recompute time.
    companion = _put(state, _creature("Bear Two"))
    _attack(companion)
    continuous.recompute(state)
    assert eng.can_block(defender, blocker, attacker) is True


def test_attacks_alone_trigger_fires_once_and_only_when_alone():
    card = _creature("Sunhome Stalwart", "Whenever ~ attacks alone, ~ gets +1/+1 until end of turn.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    obj = _put(state, card)
    continuous.recompute(state)
    eng.start()
    while state.current_step != "declare_attackers":
        eng.advance_step()
    eng.declare_attackers(state.active_player, [obj])
    eng.advance_step()

    continuous.recompute(state)
    assert obj.power == 3  # the +1/+1 resolved


def test_attacks_alone_trigger_stays_silent_with_a_second_attacker():
    eng = _engine()
    state = eng.state
    obj = _put(
        state,
        _creature("Sunhome Stalwart", "Whenever ~ attacks alone, ~ gets +1/+1 until end of turn."),
    )
    companion = _put(state, _creature("Bear"))
    continuous.recompute(state)
    eng.start()
    while state.current_step != "declare_attackers":
        eng.advance_step()
    # Declared one at a time, exactly as the UI does — the first call must not
    # momentarily look "alone" (the reason `ATTACKS_ALONE` is an aggregate
    # event fired as the step closes, not per declaration).
    eng.declare_attackers(state.active_player, [obj])
    eng.declare_attackers(state.active_player, [companion])
    eng.advance_step()

    continuous.recompute(state)
    assert obj.power == 2


# -- "target creature can't block this turn" (RULE 509.1a, resolve-time) -----


def test_target_creature_cant_block_this_turn():
    card = Card(
        id="Falter", name="Falter", type_line="Sorcery", is_sorcery=True,
        oracle_text="Target creature can't block this turn.",
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, _creature("Raider"))
    blocker = _put(state, _creature("Bear"), controller="p2")
    source = _put(state, _creature("Source"))
    continuous.recompute(state)
    _attack(attacker)

    defender = state.player_by_id("p2")
    assert eng.can_block(defender, blocker, attacker) is True

    from mtg_analyzer.game.effects.core import EffectRegistry

    EffectRegistry.create("cant_block_this_turn", {}).apply(eng.rules, [blocker])
    assert blocker.temp_cant_block is True
    assert eng.can_block(defender, blocker, attacker) is False

    eng._step_cleanup()  # RULE 514.2
    assert blocker.temp_cant_block is False


def test_mass_cant_block_this_turn_honours_its_filter():
    card = Card(
        id="Kwende", name="Kwende", type_line="Sorcery", is_sorcery=True,
        oracle_text="Creatures without flying can't block this turn.",
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    source = _put(state, _creature("Source"))
    grounded = _put(state, _creature("Bear"), controller="p2")
    flier = _put(state, _creature("Drake", keywords=["Flying"]), controller="p2")
    continuous.recompute(state)

    from mtg_analyzer.game.effects.core import EffectRegistry

    effect = EffectRegistry.create(
        "cant_block_this_turn", {"selector": "all_creatures", "filter": {"without_keyword": "flying"}}
    )
    effect.source = source
    effect.apply(eng.rules, None)

    assert grounded.temp_cant_block is True
    assert flier.temp_cant_block is False


def test_up_to_two_target_creatures_cant_block_this_turn_parses_as_multi():
    card = Card(
        id="Abandon the Post", name="Abandon the Post", type_line="Sorcery", is_sorcery=True,
        oracle_text="Up to two target creatures can't block this turn.",
    )
    result = _modeled(card)
    spec = result.specs[0].effects[0]
    assert spec.type == "cant_block_this_turn"
    assert spec.params["count"] == 2
    assert spec.params["optional"] is True


# -- "…unless they're mana abilities" (RULE 605.1a) --------------------------


def test_activation_prohibition_mana_ability_carve_out():
    aura = Card(
        id="Kasmina's Transmutation", name="Kasmina's Transmutation",
        type_line="Enchantment — Aura",
        oracle_text="Enchant creature\n"
                    "Enchanted creature can't attack or block, and its activated "
                    "abilities can't be activated unless they're mana abilities.",
    )
    _modeled(aura)

    eng = _engine()
    state = eng.state
    host = _put(state, _creature("Llanowar Elves", "{T}: Add {G}."))
    enchantment = _put(state, aura, controller="p2")
    enchantment.attached_to = host.instance_id
    continuous.recompute(state)

    assert continuous.activation_prohibited(state, host) is True
    assert continuous.activation_prohibited(state, host, is_mana_ability=True) is False
    # …and the mana ability really is still usable through the engine.
    assert eng.tap_for_mana(state.active_player, host) == {"G": 1}


def test_unqualified_activation_prohibition_also_silences_mana_abilities():
    # RULE 602/605.1a: a mana ability *is* an activated ability, so a
    # prohibition without the carve-out stops it too (Null Rod's whole point).
    eng = _engine()
    state = eng.state
    # The prohibition is artifact-scoped, so the mana source has to be one.
    host = _put(state, _creature("Llanowar Elves", "{T}: Add {G}.",
                                 type_line="Artifact Creature — Elf"))
    _put(
        state,
        Card(id="Null Rod", name="Null Rod", type_line="Artifact",
             oracle_text="Activated abilities of artifacts can't be activated."),
    )
    continuous.recompute(state)

    assert continuous.activation_prohibited(state, host, is_mana_ability=True) is True
    with pytest.raises(ValueError):
        eng.tap_for_mana(state.active_player, host)
