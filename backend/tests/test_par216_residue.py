"""PAR-216 residue: "next time" chosen-source shields, multi-target shields, two-target redirects, the announced-player
source scope, "no +1/+1 counters" and condition-gated "can't be prevented" (RULE 115.1, 115.3, 615, 615.6, 616.1).

Parse tests pin specs and refusals; execution tests resolve the real cards against the real engine.
"""
import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from tests.support.deck_batch import RICH, activate, answer, card, cast, filler, game, main_phase


def _parse(text, type_line="Instant"):
    c = Card(id="x", name="Probe Card", type_line=type_line, oracle_text=text, is_instant="Instant" in type_line,
             is_creature="Creature" in type_line)
    return parse_oracle(c)


def _effects(result):
    return [(e["type"], e["params"]) for s in result.specs for e in s.to_dict()["effects"]]


def _modeled(name):
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
    return parse_oracle(CardDatabase(DEFAULT_DB_PATH).get_card(name)).modeled


def _fund(eng, player="p1"):
    eng.state.player_by_id(player).mana_pool.add_many(RICH)


# --- parse -----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,effect", [
    ("The next time a source of your choice would deal damage to you this turn, prevent half that damage, rounded down.",
     ("request_prevent_damage_source", {"amount": {"half": "down"}, "once": True})),
    ("The next time a red source of your choice would deal damage to you this turn, prevent that damage.",
     ("request_prevent_damage_source", {"amount": "all", "once": True, "source_filter": {"color": "R"}})),
    ("The next time a source of your choice would deal damage to you this turn, that damage is dealt to ~ instead.",
     ("request_redirect_damage_source", {"once": True, "only_to_you": True})),
    ("The next time a source of your choice would deal damage to you this turn, that damage is dealt to target creature "
     "you control instead.",
     ("request_redirect_damage_source",
      {"once": True, "only_to_you": True, "recipient": "target", "target_kind": "creature_you_control"})),
    ("All damage that would be dealt this turn to target creature you control by a source of your choice is dealt to "
     "another target creature instead.",
     ("request_redirect_damage_source",
      {"protected_target_kind": "creature_you_control", "recipient": "target", "target_kind": "creature"})),
    ("Prevent all damage that would be dealt this turn to up to 2 target creatures.",
     ("prevent_damage_shield", {"amount": "all", "target_kind": "creature", "count": 2, "optional": True})),
    ("Prevent all damage 1 or 2 target creatures would deal this turn.",
     ("prevent_damage_from_target", {"target_kind": "creature", "count": 1, "count_max": 2})),
    ("The next 1 damage that would be dealt to target creature this turn is dealt to another target creature instead.",
     ("redirect_damage_shield", {"amount": 1, "protected": "target", "recipient": "target", "target_kind": "creature",
                                 "recipient_target_kind": "creature"})),
    ("The next X damage that would be dealt to target creature, planeswalker, or player this turn is dealt to another "
     "target creature, planeswalker, or player instead.",
     ("redirect_damage_shield",
      {"amount": "x", "protected": "target", "recipient": "target", "target_kind": "creature_planeswalker_or_player",
       "recipient_target_kind": "creature_planeswalker_or_player"})),
    ("Prevent all combat damage that would be dealt this turn by creatures target opponent controls.",
     ("prevent_damage_shield", {"amount": "all", "by_sources_only": True, "combat_only": True,
                                "source_filter": {"creature": True, "controller": "target"}, "target_kind": "opponent"})),
    ("Prevent all combat damage that would be dealt this turn by creatures with no +1/+1 counters on them.",
     ("prevent_damage_shield", {"amount": "all", "by_sources_only": True, "combat_only": True, "source_filter": {
         "object_filter": {"card_type": "creature", "without_counter_kind": "+1/+1"}}})),
])
def test_clause_spec(text, effect):
    result = _parse(text)
    assert result.modeled, result.unclaimed
    assert _effects(result)[0] == effect


@pytest.mark.parametrize("text", [
    # a "next time" form over a source class, or with a recipient that is not a host or creature target
    "The next time a source of your choice would deal damage to you this turn, that damage is dealt to target player instead.",
    # "other"-scoped classes and a target-player scope cannot combine
    "Prevent all combat damage that would be dealt this turn by other creatures target opponent controls.",
    # a target-player class with an unparsed class phrase
    "Prevent all combat damage that would be dealt this turn by gizmos target opponent controls.",
    # two targets with no "another": nothing says they differ
    "The next 1 damage that would be dealt to target creature this turn is dealt to target creature instead.",
    # a multi-target shield over a pool that is not creatures
    "Prevent all damage that would be dealt this turn to up to 2 target lands.",
])
def test_clause_is_not_over_claimed(text):
    assert not _parse(text).modeled


def test_gated_unpreventable_riders_parse():
    banefire = _parse("Probe Card deals X damage to any target.\nIf X is 5 or more, this spell can't be countered and the "
                      "damage can't be prevented.", "Instant")
    assert banefire.modeled
    assert _effects(banefire)[0][1]["unpreventable_if"] == {"kind": "x_paid", "min": 5}
    assert _effects(banefire)[1][0] == "cant_be_countered"
    # a rider with a condition the shared reader cannot read stays unclaimed
    assert not _parse("Probe Card deals X damage to any target.\nIf the moon is full, the damage can't be prevented.",
                      "Instant").modeled


@pytest.mark.parametrize("name", [
    "Beacon of Destiny", "Dark Sphere", "General's Regalia", "Redeem", "Soul Parry", "Serene Sunset", "Carom",
    "Kor Chant", "Kor Dirge", "Captain's Maneuver", "Encircling Fissure", "Hindervines", "Banefire", "Demonfire",
    "Urza's Rage", "Lightning Surge", "Razia, Boros Archangel", "Oracle's Attendants",
])
def test_cards_are_modeled(name):
    assert _modeled(name)


# --- execution: "next time" chosen-source shields --------------------------------------------------------------------------

def test_dark_sphere_halves_only_the_next_hit_of_the_chosen_source():
    eng = game(library=0)
    sphere = card(eng, "Dark Sphere")
    src = filler(eng, "Src", player="p2", power=4, toughness=9)
    me = eng.state.player_by_id("p1")
    life = me.life
    activate(eng, sphere, 0)
    answer(eng)
    eng.rules.deal_damage(me, 5, source=src)  # half of 5, rounded down, is prevented -> 3 get through
    eng.rules.deal_damage(me, 5, source=src)  # the window was the *next* time only
    assert me.life == life - 3 - 5


def test_beacon_of_destiny_redirects_one_hit_then_ends():
    eng = game(library=0)
    beacon = card(eng, "Beacon of Destiny")
    src = filler(eng, "Src", player="p2", power=4, toughness=9)
    me = eng.state.player_by_id("p1")
    life = me.life
    beacon.summoning_sick = False
    activate(eng, beacon, 0)
    answer(eng, pick=lambda c: next(o["id"] for o in c["options"] if "Src" in str(o.get("label", o))))
    eng.rules.deal_damage(me, 3, source=src)
    eng.rules.deal_damage(me, 2, source=src)
    assert beacon.damage_marked == 3 and me.life == life - 2


def test_generals_regalia_redirects_to_the_announced_creature():
    eng = game(library=0)
    regalia = card(eng, "General's Regalia")
    bear = filler(eng, "Bear", power=2, toughness=9)
    src = filler(eng, "Src", player="p2", power=4, toughness=9)
    me = eng.state.player_by_id("p1")
    life = me.life
    _fund(eng)
    activate(eng, regalia, 0, targets=[bear])
    answer(eng, pick=lambda c: next(o["id"] for o in c["options"] if "Src" in str(o.get("label", o))))
    eng.rules.deal_damage(me, 4, source=src)
    assert bear.damage_marked == 4 and me.life == life


# --- execution: multi-target shields -----------------------------------------------------------------------------------------

def test_redeem_shields_both_chosen_creatures():
    eng = game(library=0)
    spell = card(eng, "Redeem", zone=Zone.HAND)
    a = filler(eng, "A", power=2, toughness=3)
    b = filler(eng, "B", power=2, toughness=3)
    c = filler(eng, "C", power=2, toughness=3)
    src = filler(eng, "Src", player="p2", power=4, toughness=9)
    cast(eng, spell, targets=[a, b])
    for victim in (a, b, c):
        eng.rules.deal_damage(victim, 2, source=src)
    assert (a.damage_marked, b.damage_marked, c.damage_marked) == (0, 0, 2)


def test_soul_parry_stops_the_chosen_creatures_damage():
    eng = game(library=0)
    spell = card(eng, "Soul Parry", zone=Zone.HAND)
    a = filler(eng, "A", player="p2", power=2, toughness=3)
    b = filler(eng, "B", player="p2", power=2, toughness=3)
    c = filler(eng, "C", player="p2", power=2, toughness=3)
    me = eng.state.player_by_id("p1")
    life = me.life
    cast(eng, spell, targets=[a, b])
    for dealer in (a, b, c):
        eng.rules.deal_damage(me, 2, source=dealer)
    assert me.life == life - 2


def test_serene_sunset_prevents_only_combat_damage_of_x_creatures():
    eng = game(library=0)
    spell = card(eng, "Serene Sunset", zone=Zone.HAND)
    a = filler(eng, "A", player="p2", power=2, toughness=3)
    me = eng.state.player_by_id("p1")
    life = me.life
    cast(eng, spell, targets=[a], x=1)
    eng.rules.deal_damage(me, 2, source=a, combat=True)
    eng.rules.deal_damage(me, 3, source=a, combat=False)
    assert me.life == life - 3


# --- execution: two-target redirects -------------------------------------------------------------------------------------------

def test_carom_moves_one_damage_to_the_other_creature():
    eng = game(library=3)  # Carom draws a card
    spell = card(eng, "Carom", zone=Zone.HAND)
    a = filler(eng, "A", power=2, toughness=9)
    b = filler(eng, "B", power=2, toughness=9)
    src = filler(eng, "Src", player="p2", power=4, toughness=9)
    cast(eng, spell, targets=[a, b])
    eng.rules.deal_damage(a, 3, source=src)
    assert (a.damage_marked, b.damage_marked) == (2, 1)


def test_kor_chant_moves_all_damage_from_the_chosen_source_only():
    eng = game(library=0)
    spell = card(eng, "Kor Chant", zone=Zone.HAND)
    a = filler(eng, "A", power=2, toughness=9)
    b = filler(eng, "B", power=2, toughness=9)
    src = filler(eng, "Src", player="p2", power=4, toughness=9)
    other = filler(eng, "Other", player="p2", power=4, toughness=9)
    cast(eng, spell, targets=[a, b])
    answer(eng, pick=lambda c: next(o["id"] for o in c["options"] if "Src" in str(o.get("label", o))))
    eng.rules.deal_damage(a, 3, source=src)
    eng.rules.deal_damage(a, 2, source=src)
    eng.rules.deal_damage(a, 1, source=other)
    assert (a.damage_marked, b.damage_marked) == (1, 5)


def test_captains_maneuver_redirects_x_damage_to_a_player():
    eng = game(library=0)
    spell = card(eng, "Captain's Maneuver", zone=Zone.HAND)
    a = filler(eng, "A", power=2, toughness=9)
    foe = eng.state.player_by_id("p2")
    life = foe.life
    src = filler(eng, "Src", player="p2", power=4, toughness=9)
    cast(eng, spell, targets=[a, foe], x=2)
    eng.rules.deal_damage(a, 5, source=src)
    assert a.damage_marked == 3 and foe.life == life - 2


# --- execution: source scope and counters -------------------------------------------------------------------------------------

def test_encircling_fissure_stops_only_the_chosen_opponents_creatures():
    eng = game(library=0)
    spell = card(eng, "Encircling Fissure", zone=Zone.HAND)
    mine = filler(eng, "Mine", power=3, toughness=3)
    theirs = filler(eng, "Theirs", player="p2", power=3, toughness=3)
    me = eng.state.player_by_id("p1")
    foe = eng.state.player_by_id("p2")
    cast(eng, spell, targets=[foe])
    life, foe_life = me.life, foe.life
    eng.rules.deal_damage(me, 3, source=theirs, combat=True)
    eng.rules.deal_damage(foe, 3, source=mine, combat=True)
    eng.rules.deal_damage(me, 2, source=theirs, combat=False)
    assert (me.life, foe.life) == (life - 2, foe_life - 3)


def test_hindervines_spares_creatures_that_carry_a_counter():
    eng = game(library=0)
    spell = card(eng, "Hindervines", zone=Zone.HAND)
    plain = filler(eng, "Plain", player="p2", power=3, toughness=3)
    grown = filler(eng, "Grown", player="p2", power=3, toughness=3)
    grown.counters["+1/+1"] = 1
    me = eng.state.player_by_id("p1")
    life = me.life
    cast(eng, spell)
    eng.rules.deal_damage(me, 3, source=plain, combat=True)
    eng.rules.deal_damage(me, 4, source=grown, combat=True)
    assert me.life == life - 4


# --- execution: gated unpreventable damage ---------------------------------------------------------------------------------------

def _guarded_target(eng):
    """A creature that prevents all damage dealt to it, to see whether a hit goes through anyway."""
    target = filler(eng, "Warded", player="p2", power=1, toughness=20)
    eng.rules.prevent_damage_to_target(target, "all")
    return target


def test_banefire_is_unpreventable_only_at_x_five():
    for x, expected in ((4, 0), (5, 5)):
        eng = game(library=0)
        spell = card(eng, "Banefire", zone=Zone.HAND)
        target = _guarded_target(eng)
        cast(eng, spell, targets=[target], x=x)
        assert target.damage_marked == expected


def test_banefire_x_five_cannot_be_countered_but_x_four_can():
    for x, countered in ((4, True), (5, False)):
        eng = game(library=0)
        spell = card(eng, "Banefire", zone=Zone.HAND)
        target = filler(eng, "T", player="p2", power=1, toughness=20)
        me = eng.state.player_by_id("p1")
        main_phase(eng)
        me.mana_pool.add_many(RICH)
        eng.cast_spell(me, spell, targets=[target], x=x)  # left on the stack: "can't be countered" matters there
        assert eng.rules._is_cant_be_countered(spell) is (not countered)


def test_demonfire_needs_an_empty_hand():
    for hand, expected in ((0, 4), (1, 0)):
        eng = game(library=0)
        spell = card(eng, "Demonfire", zone=Zone.HAND)
        for i in range(hand):
            filler(eng, f"H{i}", type_line="Sorcery", zone=Zone.HAND)
        target = _guarded_target(eng)
        cast(eng, spell, targets=[target], x=4)
        assert target.damage_marked == expected


def test_lightning_surge_threshold_makes_six_unpreventable():
    for gy, expected in ((0, 0), (7, 6)):
        eng = game(library=0)
        spell = card(eng, "Lightning Surge", zone=Zone.HAND)
        me = eng.state.player_by_id("p1")
        for i in range(gy):
            me.graveyard.append(filler(eng, f"G{i}", zone=Zone.GRAVEYARD))
        target = _guarded_target(eng)
        cast(eng, spell, targets=[target])
        assert target.damage_marked == expected


def test_oracles_attendants_takes_the_damage_itself():
    eng = game(library=0)
    attendants = card(eng, "Oracle's Attendants")
    attendants.summoning_sick = False
    ally = filler(eng, "Ally", power=2, toughness=9)
    src = filler(eng, "Src", player="p2", power=4, toughness=9)
    activate(eng, attendants, 0, targets=[ally])
    answer(eng, pick=lambda c: next(o["id"] for o in c["options"] if "Src" in str(o.get("label", o))))
    eng.rules.deal_damage(ally, 4, source=src)
    assert (ally.damage_marked, attendants.damage_marked) == (0, 4)


def test_razia_moves_three_damage_between_two_creatures():
    eng = game(library=0)
    razia = card(eng, "Razia, Boros Archangel")
    razia.summoning_sick = False
    ally = filler(eng, "Ally", power=2, toughness=9)
    other = filler(eng, "Other", power=2, toughness=9)
    src = filler(eng, "Src", player="p2", power=4, toughness=9)
    activate(eng, razia, 0, targets=[ally, other])
    eng.rules.deal_damage(ally, 5, source=src)
    assert (ally.damage_marked, other.damage_marked) == (2, 3)
