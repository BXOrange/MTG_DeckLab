"""RULE 118.9 alt_cost siblings beyond Snuff Out's own board-conditioned
pay-life (already shipped): a board condition paired with a *non-mana*
payment component instead (Dark Triumph's "if you control a Swamp, you may
sacrifice a creature…", Angelic Favor's "…you may tap an untapped creature
you control…"), a combined mana-plus-return-to-hand cost (the Borderpost
cycle's "you may pay {1} and return a basic land you control…"), and a
counted sacrifice generalized beyond "one" (the Odyssey-block "you may
sacrifice N `<land type>`s…").

None of these needed new *payment* machinery — `_can_pay_alt_cast_cost`/
`_pay_alt_cast_cost` already read `mana`/`sacrifice`/`sacrifice_count`/
`return_to_hand_count` independently of each other, so pairing two of them
in one `alt_cost` dict just works. The one genuine gap was `tap_others`
(RULE 602.1's "Tap N untapped `<type>`s you control" cost, previously only
ever paid on an *activated* ability, never an alt-cast one) — now wired
into both methods — and `_tap_others_pool` matching a bare main type
("creature") as well as a real subtype, since Angelic Favor doesn't name a
creature *type*.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def land(name, type_line="Basic Land — Swamp"):
    return Card(id=name, name=name, type_line=type_line, is_land=True)


def creature(name, power=2, toughness=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness,
    )


def put(state, card, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    return obj


# -- Dark Triumph: condition + sacrifice -------------------------------------


def dark_triumph_card():
    return Card(
        id="Dark Triumph", name="Dark Triumph", type_line="Instant", is_instant=True,
        mana_cost_string="{4}{B}", converted_mana_cost=5,
        oracle_text="If you control a Swamp, you may sacrifice a creature "
                    "rather than pay this spell's mana cost.\n"
                    "Creatures you control get +2/+0 until end of turn.",
    )


def test_dark_triumph_is_modeled():
    result = parse_oracle(dark_triumph_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_dark_triumph_alt_cost_needs_a_swamp_and_a_creature_to_sacrifice():
    eng = make_engine("p1", "p2")
    card = dark_triumph_card()
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.active_player.hand.append(obj)
    eng.state.current_step = "main1"

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False

    put(eng.state, land("My Swamp"))
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False

    victim = put(eng.state, creature("Fodder"))
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is True

    eng.cast_spell(eng.state.active_player, obj, alt_cost=True)
    assert victim not in eng.state.battlefield
    assert any(item.obj is obj for item in eng.state.stack)


# -- Angelic Favor: condition + tap_others -----------------------------------


def angelic_favor_card():
    return Card(
        id="Angelic Favor", name="Angelic Favor", type_line="Instant", is_instant=True,
        mana_cost_string="{3}{W}", converted_mana_cost=4,
        oracle_text="If you control a Plains, you may tap an untapped "
                    "creature you control rather than pay this spell's "
                    "mana cost.",
    )


def test_angelic_favor_alt_cost_line_is_claimed():
    result = parse_oracle(angelic_favor_card())
    assert not any("rather than pay" in line for line in result.unclaimed)


def test_angelic_favor_alt_cost_taps_a_creature_instead_of_paying():
    eng = make_engine("p1", "p2")
    card = angelic_favor_card()
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.active_player.hand.append(obj)
    eng.state.current_step = "main1"
    put(eng.state, land("My Plains", type_line="Basic Land — Plains"))

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False

    tapper = put(eng.state, creature("Ready Creature"))
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is True

    eng.cast_spell(eng.state.active_player, obj, alt_cost=True)
    assert tapper.tapped is True


# -- Borderpost cycle: mana + return_to_hand_count("basic land") ------------


def fieldmist_borderpost_card():
    return Card(
        id="Fieldmist Borderpost", name="Fieldmist Borderpost", type_line="Artifact",
        mana_cost_string="{1}{W}{U}", converted_mana_cost=3,
        oracle_text="You may pay {1} and return a basic land you control "
                    "to its owner's hand rather than pay this spell's mana cost.\n"
                    "This artifact enters tapped.\n"
                    "{T}: Add {W} or {U}.",
    )


def test_fieldmist_borderpost_is_modeled():
    result = parse_oracle(fieldmist_borderpost_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_borderpost_alt_cost_pays_generic_and_returns_a_basic_land():
    eng = make_engine("p1", "p2")
    card = fieldmist_borderpost_card()
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.active_player.hand.append(obj)
    eng.state.current_step = "main1"

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False

    a_land = put(eng.state, land("A Forest", type_line="Basic Land — Forest"))
    eng.rules.add_mana(eng.state.active_player, "C", 1)
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is True

    eng.cast_spell(eng.state.active_player, obj, alt_cost=True)
    assert a_land not in eng.state.battlefield
    assert a_land in eng.state.active_player.hand


# -- counted sacrifice --------------------------------------------------------


def sacrifice_mountains_card():
    return Card(
        id="Test Mountain Sac Spell", name="Test Mountain Sac Spell", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{4}{R}{R}", converted_mana_cost=6,
        oracle_text="You may sacrifice 3 mountains rather than pay this "
                    "spell's mana cost.",
    )


def test_sacrifice_count_alt_cost_is_modeled():
    result = parse_oracle(sacrifice_mountains_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_sacrifice_count_alt_cost_needs_three_mountains():
    eng = make_engine("p1", "p2")
    card = sacrifice_mountains_card()
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.active_player.hand.append(obj)
    eng.state.current_step = "main1"

    put(eng.state, land("M1", type_line="Basic Land — Mountain"))
    put(eng.state, land("M2", type_line="Basic Land — Mountain"))
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False

    put(eng.state, land("M3", type_line="Basic Land — Mountain"))
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is True

    eng.cast_spell(eng.state.active_player, obj, alt_cost=True)
    mountains_left = [o for o in eng.state.battlefield if "Mountain" in o.card.type_line]
    assert len(mountains_left) == 0


# -- PAR-19: Lethargy Trap-shaped combat-count condition + mana payment -----


def lethargy_trap_card():
    return Card(
        id="Lethargy Trap", name="Lethargy Trap", type_line="Instant", is_instant=True,
        mana_cost_string="{3}{U}", converted_mana_cost=4,
        oracle_text="If 3 or more creatures are attacking, you may pay {U} "
                    "rather than pay this spell's mana cost.\n"
                    "Attacking creatures get -3/-0 until end of turn.",
    )


def test_lethargy_trap_is_modeled():
    result = parse_oracle(lethargy_trap_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_lethargy_trap_alt_cost_needs_three_attacking_creatures():
    eng = make_engine("p1", "p2")
    card = lethargy_trap_card()
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.active_player.hand.append(obj)
    eng.state.current_step = "main1"

    attackers = [put(eng.state, creature(f"Attacker {i}")) for i in range(2)]
    for a in attackers:
        a.attacking = True
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False

    third = put(eng.state, creature("Attacker 3"))
    third.attacking = True
    eng.rules.add_mana(eng.state.active_player, "U", 1)
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is True

    eng.cast_spell(eng.state.active_player, obj, alt_cost=True)
    assert any(item.obj is obj for item in eng.state.stack)


def test_attacking_creatures_pump_debuffs_only_attackers():
    eng = make_engine("p1", "p2")
    attacker = put(eng.state, creature("Attacker", power=4, toughness=4))
    attacker.attacking = True
    bystander = put(eng.state, creature("Bystander", power=4, toughness=4))
    # A real Lethargy Trap-shaped spell always has a real, controlled
    # source (the stack object); a sourceless effect isn't a shape this
    # engine casts in practice, but `PumpEffect.apply`'s ``attacking_
    # creatures`` branch does read `self.source.controller_id` on the way
    # in (`group_selector_objects`'s ``elif controller_id is None`` guard
    # sits ahead of the unscoped selector branches) — the same lookup
    # `_pump_selector`'s own bound-ability callers always satisfy for free.
    caster = put(eng.state, creature("Caster", power=1, toughness=1))

    from mtg_analyzer.game.effects.core import GameContext, PumpEffect

    effect = PumpEffect(power=-3, toughness=0, selector="attacking_creatures", source=caster)
    context = GameContext(eng.state, eng.rules)
    effect.apply(context)
    eng.recompute_continuous_effects()

    assert (attacker.power, attacker.toughness) == (1, 4)
    assert (bystander.power, bystander.toughness) == (4, 4)
