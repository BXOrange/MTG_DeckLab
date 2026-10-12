"""PAR-147 — dice grammar axes (RULE 706): "roll a die" and what reads its result.

Axes shipped: a die result as an amount ("…equal to the result", "…, where X is the result",
"for each even/odd/different result"), the result as a branch gate ("if the result is 3 or
less", "On a 3 or 4, …", "if you rolled 2, 3, or 12", "if both results are the same"),
the roll-trigger heads ("whenever you roll a die / a 4 or higher / a 1 or 2 / a die's highest
natural result"), "As ~ enters, roll a die … enters with that many counters", the
"roll X dice" count forms, the results-table block with label / pre-effect / modifier
spellings, and the "roll N dice and choose one" Endeavor cycle. Every execute test drives
the real ``RulesEngine.roll_die`` (events included) with a scripted ``random_int``.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import make_engine


@pytest.fixture
def script_dice(monkeypatch):
    """``script_dice(3, 5)`` — the next dice show these faces (``random_int`` is 0-based)."""
    real = RulesEngine.random_int
    queue: list[int] = []

    def fake(self, n):
        if queue:
            return queue.pop(0) - 1
        return real(self, n)

    monkeypatch.setattr(RulesEngine, "random_int", fake)

    def feed(*faces):
        queue[:] = list(faces)
        return queue

    return feed


def _card(name, type_line, text, **kwargs):
    return Card(id=name, name=name, type_line=type_line, oracle_text=text, **kwargs)


def _creature_card(name, text, power=2, toughness=2, type_line="Creature — Test", **kwargs):
    return _card(name, type_line, text, is_creature=True, power=power,
                 toughness=toughness, **kwargs)


def _engine():
    eng = make_engine([_creature_card(f"Filler {i}", "") for i in range(5)],
                      [_creature_card(f"Other {i}", "") for i in range(5)], hand=0)
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _on_battlefield(eng, name, controller=None):
    return [o for o in eng.state.battlefield
            if o.name == name and (controller is None or o.controller_id == controller)]


def _cast(eng, card, **kwargs):
    p1 = eng.state.player_by_id("p1")
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    p1.mana_pool.add_many({"C": 10, "R": 5, "G": 5, "U": 5, "B": 5, "W": 5})
    eng.cast_spell(p1, spell, **kwargs)
    eng.resolve_until_stable()
    return spell


def _roll(eng, player="p1", sides=6, count=1, **kwargs):
    return eng.rules.roll_die(eng.state.player_by_id(player), sides=sides, count=count, **kwargs)


# --- parse: result as an amount -----------------------------------------------


def test_result_amount_sentences_bind_the_die_result():
    cases = {
        "target opponent loses life equal to the result": "lose_life",
        "target player mills x cards, where x is the result": "mill",
        "~ gets +x/+0 until end of turn, where x is the result": "pump",
        "put a number of luck counters on ~ equal to the result": "add_counters",
        "create a number of 1/1 red goblin creature tokens equal to the result": "create_token",
        "scry a number of cards equal to the result": "scry",
    }
    for text, effect in cases.items():
        [spec] = parse_effect_body(text, self_subject=True)
        assert spec.type == "bind", text
        assert spec.params["amount"] == {"kind": "die_result"}, text
        assert spec.params["effects"][0]["type"] == effect, text


def test_result_minus_one_floors_at_zero():
    [spec] = parse_effect_body("~ gets +x/+0 until end of turn, where x is the result minus 1", self_subject=True)
    assert spec.params["amount"] == {"kind": "die_result", "minus": 1, "minimum": 0}


def test_that_result_is_not_read_as_the_sum():
    # "that result" names one chosen die in the Endeavor cycle, never the total of several.
    assert parse_effect_body("draw cards equal to that result") is None or all(
        s.params.get("amount") != {"kind": "die_result"} for s in parse_effect_body("draw cards equal to that result")
    )


# --- parse: result as a gate ----------------------------------------------------


def _gate(text):
    [spec] = parse_effect_body(text, self_subject=True)
    return spec.condition


def test_result_gates():
    assert _gate("if the result is 3 or less, you lose 3 life")["op"] == "le"
    assert _gate("if the result is 3 or less, you lose 3 life")["right"] == {"kind": "fixed", "amount": 3}
    assert _gate("if you roll a 6, you gain 1 life")["op"] == "eq"
    assert _gate("on a 5 or higher, you gain 1 life")["op"] == "ge"
    seven_or_eleven = _gate("if you rolled 7 or 11, you gain 1 life")
    assert seven_or_eleven["kind"] == "any" and len(seven_or_eleven["conditions"]) == 2
    assert _gate("if both results are the same, you gain 1 life") == {"kind": "rolled_doubles"}
    assert _gate("if any of those results was 10 or higher, you gain 1 life") == {
        "kind": "any_die_result", "op": "ge", "value": 10}


def test_otherwise_after_a_result_gate_is_its_negation():
    specs = parse_effect_body("roll a 6-sided die. if the result is 1, you lose 1 life. otherwise, you gain 1 life")
    assert [s.type for s in specs] == ["roll_die", "lose_life", "gain_life"]
    assert specs[2].condition == {"kind": "not", "condition": specs[1].condition}


# --- execute: result as an amount -----------------------------------------------


_BOX = _card(
    "Box of Free-Range Goblins", "Artifact",
    "{T}: Roll a six-sided die. Create a number of 1/1 red Goblin creature tokens equal to the result.",
)


def test_box_of_free_range_goblins_makes_tokens_equal_to_the_roll(script_dice):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    box = _put(eng, _BOX)
    script_dice(4)
    eng.activate_ability(p1, box)
    eng.resolve_until_stable()
    assert len(_on_battlefield(eng, "Goblin")) == 4


_BOA = _creature_card(
    "Big Boa Constrictor",
    "When this creature enters, roll a six-sided die. Target opponent loses life equal to the result.",
)


def _enter(eng, obj):
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id=obj.controller_id,
        object_types=sorted(obj.type_words),
    ))


def test_big_boa_drains_the_chosen_opponent(script_dice):
    eng = _engine()
    boa = _put(eng, _BOA)
    script_dice(5)
    _enter(eng, boa)
    eng.resolve_until_stable()
    eng.resolve_pending_choice("p2")  # the trigger's target is chosen before the roll
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == 15


# --- execute: result as a gate --------------------------------------------------


_CUSTOMER = _creature_card(
    "Dissatisfied Customer",
    "When this creature enters, roll a six-sided die. If the result is 3 or less, you lose that much life.",
)


@pytest.mark.parametrize("face,life", [(1, 19), (3, 17), (4, 20), (6, 20)])
def test_dissatisfied_customer_loses_that_much_only_on_a_low_roll(script_dice, face, life):
    eng = _engine()
    customer = _put(eng, _CUSTOMER)
    script_dice(face)
    _enter(eng, customer)
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p1").life == life


_EGG = _creature_card(
    "Chicken Egg",
    "At the beginning of your upkeep, roll a six-sided die. If you roll a 6, sacrifice this creature and "
    "create a 4/4 red Giant Bird creature token.",
    power=0, toughness=1,
)


def _upkeep(eng):
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))


@pytest.mark.parametrize("face,hatched", [(5, False), (6, True)])
def test_chicken_egg_hatches_only_on_a_six(script_dice, face, hatched):
    eng = _engine()
    egg = _put(eng, _EGG)
    script_dice(face)
    _upkeep(eng)
    eng.resolve_until_stable()
    assert (egg.zone != Zone.BATTLEFIELD) is hatched
    assert bool(_on_battlefield(eng, "Giant Bird")) is hatched


_BOING = _card(
    "Boing!", "Instant",
    "Return target creature to its owner's hand, then roll a six-sided die. If the result is 3 or less, "
    "scry a number of cards equal to the result.",
    is_instant=True,
)


@pytest.mark.parametrize("face,scried", [(2, 2), (3, 3), (4, 0)])
def test_boing_announces_its_target_and_scries_by_the_result(script_dice, face, scried):
    eng = _engine()
    bear = _put(eng, _creature_card("Bear", "", power=2, toughness=2), controller="p2")
    script_dice(face)
    _cast(eng, _BOING, targets=[bear])
    assert bear.zone == Zone.HAND
    pending = eng.state.pending_choice
    assert (len(pending["remaining"]) if pending else 0) == scried


_INHUMANIAC = _creature_card(
    "Inhumaniac",
    "At the beginning of your upkeep, roll a six-sided die. On a 3 or 4, put a +1/+1 counter on this creature. "
    "On a 5 or higher, put two +1/+1 counters on it. On a 1, remove all +1/+1 counters from this creature.",
    power=3, toughness=3,
)


@pytest.mark.parametrize("face,counters", [(2, 5), (3, 6), (4, 6), (5, 7), (6, 7), (1, 0)])
def test_inhumaniac_result_bands(script_dice, face, counters):
    eng = _engine()
    imp = _put(eng, _INHUMANIAC)
    imp.counters["+1/+1"] = 5
    script_dice(face)
    _upkeep(eng)
    eng.resolve_until_stable()
    assert imp.counters.get("+1/+1", 0) == counters


# --- execute: roll-trigger heads ------------------------------------------------


_SUBJECT = _creature_card(
    "Willing Test Subject",
    "Whenever you roll a 4 or higher on a die, put a +1/+1 counter on this creature.",
    power=1, toughness=1,
)


def test_roll_n_or_higher_triggers_once_per_qualifying_die(script_dice):
    eng = _engine()
    subject = _put(eng, _SUBJECT)
    script_dice(3, 4, 6, 1)
    _roll(eng, count=4)
    eng.resolve_until_stable()
    assert subject.counters.get("+1/+1") == 2  # the 4 and the 6, not the 3 or the 1


def test_an_ignored_die_triggers_nothing(script_dice):
    eng = _engine()
    subject = _put(eng, _SUBJECT)
    script_dice(6, 2)
    _roll(eng, count=2, ignore_highest=1)  # RULE 706.6: the ignored 6 never happened
    eng.resolve_until_stable()
    assert not subject.counters.get("+1/+1")


def test_roll_trigger_ignores_the_opponents_dice(script_dice):
    eng = _engine()
    subject = _put(eng, _SUBJECT)
    script_dice(6)
    _roll(eng, player="p2")
    eng.resolve_until_stable()
    assert not subject.counters.get("+1/+1")


_ACROBATS = _creature_card(
    "Atomwheel Acrobats", "Whenever you roll a 1 or 2, put that many +1/+1 counters on this creature.",
    power=1, toughness=1,
)


@pytest.mark.parametrize("face,counters", [(1, 1), (2, 2), (3, 0)])
def test_that_many_counters_is_the_die_result(script_dice, face, counters):
    eng = _engine()
    acrobats = _put(eng, _ACROBATS)
    script_dice(face)
    _roll(eng)
    eng.resolve_until_stable()
    assert acrobats.counters.get("+1/+1", 0) == counters


_PUZZLE_WARD = _creature_card(
    "Netherese Test Ward", "Whenever you roll a die's highest natural result, draw a card.",
)


def test_highest_natural_result_head(script_dice):
    eng = _engine()
    _put(eng, _PUZZLE_WARD)
    p1 = eng.state.player_by_id("p1")
    before = len(p1.hand)
    script_dice(5)
    _roll(eng, sides=6)
    eng.resolve_until_stable()
    assert len(p1.hand) == before
    script_dice(8)
    _roll(eng, sides=8)
    eng.resolve_until_stable()
    assert len(p1.hand) == before + 1


_LUCK = _card(
    "As Luck Test", "Enchantment",
    "Whenever you roll a die, put a number of luck counters on this enchantment equal to the result.",
)


def test_whenever_you_roll_a_die_reads_that_dies_result(script_dice):
    eng = _engine()
    luck = _put(eng, _LUCK)
    script_dice(4, 6)
    _roll(eng, count=2)
    eng.resolve_until_stable()
    assert luck.counters.get("luck") == 10  # one trigger per die, each reading its own result


_DICE_FAN = _card(
    "Vexing Test", "Artifact",
    "Whenever you roll one or more dice, put a number of charge counters on this artifact equal to the result.",
)


def test_one_or_more_dice_head_reads_the_total(script_dice):
    eng = _engine()
    box = _put(eng, _DICE_FAN)
    script_dice(2, 5)
    _roll(eng, count=2)
    eng.resolve_until_stable()
    assert box.counters.get("charge") == 7


# --- execute: as ~ enters, roll --------------------------------------------------


_JAMMER = _creature_card(
    "Hammer Jammer",
    "As this creature enters, roll a six-sided die. This creature enters with a number of +1/+1 counters on it "
    "equal to the result.\nWhenever you roll a die, remove all +1/+1 counters from this creature, then put a "
    "number of +1/+1 counters on it equal to the result.",
    power=0, toughness=0,
)


def test_hammer_jammer_enters_with_counters_equal_to_its_roll(script_dice):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    jammer = GameObject(_JAMMER, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(jammer)
    p1.hand.append(jammer)
    script_dice(5)
    p1.mana_pool.add_many({"C": 5})
    eng.cast_spell(p1, jammer)
    eng.resolve_until_stable()
    assert jammer.counters.get("+1/+1") == 5
    assert (jammer.power, jammer.toughness) == (5, 5)
    script_dice(2)
    _roll(eng)  # "whenever you roll a die": reset to the new result
    eng.resolve_until_stable()
    assert jammer.counters.get("+1/+1") == 2


# --- execute: roll two, choose one (the Endeavor cycle) ----------------------------


_RECKLESS = _card(
    "Reckless Endeavor", "Sorcery",
    "Roll two d12 and choose one result. Reckless Endeavor deals damage equal to that result to each creature. "
    "Then create a number of Treasure tokens equal to the other result.",
    is_sorcery=True,
)


def test_reckless_endeavor_uses_the_chosen_and_the_other_result(script_dice):
    eng = _engine()
    bear = _put(eng, _creature_card("Bear", "", power=2, toughness=9))
    script_dice(3, 7)
    _cast(eng, _RECKLESS)
    pending = eng.state.pending_choice
    assert pending["kind"] == "choose_die_result" and [o["label"] for o in pending["options"]] == ["3", "7"]
    eng.resolve_pending_choice("1")  # choose the 7
    eng.resolve_until_stable()
    assert bear.damage_marked == 7
    assert len(_on_battlefield(eng, "Treasure")) == 3


def test_equal_dice_need_no_choice(script_dice):
    eng = _engine()
    _put(eng, _creature_card("Bear", "", power=2, toughness=9))
    script_dice(4, 4)
    _cast(eng, _RECKLESS)
    assert eng.state.pending_choice is None
    assert len(_on_battlefield(eng, "Treasure")) == 4


_VALIANT = _card(
    "Valiant Endeavor", "Sorcery",
    "Roll two d6 and choose one result. Destroy each creature with power greater than or equal to that result. "
    "Then create a number of 2/2 white Knight creature tokens with vigilance equal to the other result.",
    is_sorcery=True,
)


def test_valiant_endeavor_filters_by_the_chosen_result(script_dice):
    eng = _engine()
    small = _put(eng, _creature_card("Small", "", power=2, toughness=2))
    big = _put(eng, _creature_card("Big", "", power=5, toughness=5))
    script_dice(5, 2)
    _cast(eng, _VALIANT)
    eng.resolve_pending_choice("0")  # choose the 5
    eng.resolve_until_stable()
    assert big.zone == Zone.GRAVEYARD and small.zone == Zone.BATTLEFIELD
    assert len(_on_battlefield(eng, "Knight")) == 2


# --- execute: for each even / odd / different result ------------------------------------


def test_circuits_act_makes_a_token_per_different_result(script_dice):
    eng = _engine()
    script_dice(2, 2, 5)
    _cast(eng, _card(
        "Circuits Act", "Sorcery",
        "Roll three six-sided dice. For each different result, create a 1/1 white Clown Robot artifact creature token.",
        is_sorcery=True,
    ))
    assert len(_on_battlefield(eng, "Clown Robot")) == 2


def test_clown_car_with_no_announced_x_rolls_nothing(script_dice):
    eng = _engine()
    seen = []
    eng.state.subscribe(lambda e: seen.append(e) if e.type == EventType.DICE_ROLLED else None)
    car = _put(eng, _card(
        "Clown Car", "Artifact — Vehicle",
        "When this Vehicle enters, roll X six-sided dice. For each odd result, create a 1/1 white Clown Robot "
        "artifact creature token. For each even result, put a +1/+1 counter on this Vehicle.",
    ))
    _enter(eng, car)
    eng.resolve_until_stable()
    assert not seen and not _on_battlefield(eng, "Clown Robot")


def test_attempted_murder_splits_dice_between_counters_and_birds(script_dice):
    eng = _engine()
    victim = _put(eng, _creature_card("Victim", "", power=5, toughness=9), controller="p2")
    script_dice(2, 3, 4)
    spell = _card(
        "Attempted Murder", "Sorcery",
        "Choose target creature. Roll X six-sided dice. For each even result, put two -1/-1 counters on that "
        "creature. For each odd result, create a 1/2 blue Bird creature token with flying named Storm Crow.",
        is_sorcery=True,
    )
    _cast(eng, spell, targets=[victim], x=3)
    assert victim.counters.get("-1/-1") == 4  # two even dice, two counters each
    assert len(_on_battlefield(eng, "Storm Crow")) == 1


def test_luck_bobblehead_rolls_one_die_per_bobblehead_and_wins_on_seven_sixes(script_dice):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    text = ("{T}: Add one mana of any color.\n{1}, {T}: Roll X six-sided dice, where X is the number of "
            "Bobbleheads you control. Create a tapped Treasure token for each even result. If you rolled 6 "
            "exactly seven times, you win the game.")
    heads = [_put(eng, _card(f"Luck Bobblehead", "Artifact — Bobblehead", text)) for _ in range(7)]
    script_dice(6, 6, 6, 6, 6, 6, 6)
    p1.mana_pool.add_many({"C": 1})
    eng.activate_ability(p1, heads[0], ability_index=0)
    eng.resolve_until_stable()
    assert len(_on_battlefield(eng, "Treasure")) == 7
    assert eng.state.player_by_id("p2").has_lost or eng.state.game_over


# --- execute: results table (RULE 706.3a) ------------------------------------------------


_CHANNELER = _creature_card(
    "Chaos Channeler",
    "Wild Magic Surge — Whenever this creature attacks, roll a d20.\n"
    "1—9 | Exile the top card of your library. You may play it this turn.\n"
    "10—19 | Exile the top two cards of your library. You may play them this turn.\n"
    "20 | Exile the top three cards of your library. You may play them this turn.",
)


@pytest.mark.parametrize("face,exiled", [(9, 1), (10, 2), (20, 3)])
def test_labelled_table_row_by_face(script_dice, face, exiled):
    eng = _engine()
    ch = _put(eng, _CHANNELER)
    p1 = eng.state.player_by_id("p1")
    p1.library[:] = [GameObject(_creature_card(f"Lib {i}", ""), owner_id="p1", zone=Zone.LIBRARY) for i in range(5)]
    script_dice(face)
    eng.state.fire_event(GameEvent(EventType.ATTACKS, instance_id=ch.instance_id, player_id="p1", controller_id="p1"))
    eng.resolve_until_stable()
    assert 5 - len(p1.library) == exiled


_EARTH_CULT = _creature_card(
    "Earth-Cult Elemental",
    "Siege Monster — When this creature enters, roll a d20.\n"
    "1—9 | Each player sacrifices a permanent of their choice.\n"
    "10—19 | Each opponent sacrifices a permanent of their choice.\n"
    "20 | Each opponent sacrifices two permanents of their choice.",
)


def test_header_label_is_parsed_like_any_trigger():
    assert parse_oracle(_EARTH_CULT).modeled


def test_indicated_effect_table_style_parses_and_mana_tables_stay_unmodeled():
    ok = _card("Test Die", "Artifact", "{2}: Roll a six-sided die. This creature has the indicated effect.\n"
               "1 — You lose 1 life.\n2 — You gain 1 life.\n3 — Draw a card.\n4 — You gain 2 life.\n"
               "5 — You lose 2 life.\n6 — You gain 3 life.")
    assert parse_oracle(ok).modeled
    mox = _card("Test Mox", "Artifact", "{T}: Roll a six-sided die. This ability has the indicated effect.\n"
                "1 — Sacrifice this artifact and you lose 5 life.\n2 — Add {W}.\n3 — Add {U}.\n4 — Add {B}.\n"
                "5 — Add {R}.\n6 — Add {G}.")
    assert not parse_oracle(mox).modeled  # a mana ability resolves without the stack (RULE 605.3b)


# --- collateral: "mill X cards, where X is …" ------------------------------------------------


def test_mill_x_binds_the_measured_count():
    [spec] = parse_effect_body("target player mills x cards, where x is the number of lands you control")
    assert spec.type == "bind" and spec.params["effects"][0]["params"]["count"] == "$n"
    assert parse_effect_body("target player mills x cards")[0].params["count"] == "x"


# --- roll modifiers: "roll a d20 and add / subtract <amount>" (RULE 706.4) --------------------------------


_PORTENT = _card(
    "Diviner's Portent", "Instant",
    "Roll a d20 and add the number of cards in your hand.\n1—14 | Draw X cards.\n15+ | Scry X, then draw X cards.",
    mana_cost_string="{X}{U}{U}{U}", is_instant=True,
)


def test_roll_modifier_parses_a_fixed_or_measured_amount():
    [fixed] = parse_effect_body("roll a d20 and add 3")
    assert fixed.params == {"sides": 20, "modifier": 3}
    [measured] = parse_effect_body("roll a d20 and subtract the number of cards in your hand")
    assert measured.params["modifier_subtract"] is True
    assert measured.params["modifier_amount"]["selector"] == {"zone": "hand", "of": "you"}
    assert parse_effect_body("roll two d6 and add 3") is None  # a modifier on several dice is not a printed shape
    assert parse_oracle(_PORTENT).modeled


def _portent_engine(hand_extra):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    for i in range(hand_extra):
        p1.hand.append(GameObject(_creature_card(f"Held {i}", ""), owner_id="p1", zone=Zone.HAND))
    return eng, p1


def test_modified_result_picks_the_table_row_but_the_natural_roll_is_kept(script_dice):
    # natural 9 + 7 held cards = 16 -> the "15+" row (scry X, then draw X).
    eng, p1 = _portent_engine(7)
    script_dice(9)
    _cast(eng, _PORTENT, x=2)
    assert eng.rules._last_die_roll_results == [9]  # RULE 706.4: the natural roll is untouched
    assert eng.rules._last_die_roll_total == 16
    assert eng.state.pending_choice["kind"] == "scry"  # the 15+ row scries X first


def test_modified_result_below_the_threshold_takes_the_low_row(script_dice):
    # natural 9 + 2 held cards = 11 -> "1-14": draw X, no scry.
    eng, p1 = _portent_engine(2)
    before = len(p1.hand)
    script_dice(9)
    _cast(eng, _PORTENT, x=2)
    assert eng.rules._last_die_roll_total == 11
    assert eng.state.pending_choice is None
    assert len(p1.hand) == before + 2


def test_modifier_never_changes_the_highest_natural_result(script_dice):
    eng = _engine()
    _put(eng, _PUZZLE_WARD)
    p1 = eng.state.player_by_id("p1")
    before = len(p1.hand)
    script_dice(3)
    _roll(eng, sides=6, modifier=3)  # the result is 6 but the natural roll is 3
    eng.resolve_until_stable()
    assert len(p1.hand) == before
    script_dice(6)
    _roll(eng, sides=6, modifier=-4)  # the result is 2 but the natural roll is the highest face
    eng.resolve_until_stable()
    assert len(p1.hand) == before + 1


_DECK = _card(
    "Modifier Tester", "Artifact",
    "{T}: Roll a d20 and subtract the number of cards in your hand. If the result is 0 or less, you lose 3 life.",
)


def test_subtracted_result_can_go_to_zero_or_less(script_dice):
    eng, p1 = _portent_engine(5)
    tester = _put(eng, _DECK)
    script_dice(4)
    eng.activate_ability(p1, tester)
    eng.resolve_until_stable()
    assert eng.rules._last_die_roll_total == -1 and eng.rules._last_die_roll_results == [4]
    assert p1.life == 17


# --- the remaining Endeavor halves: Wild (search), Grave (reanimate with counters), Arcane (free cast) -----


def _forest(i):
    return _card(f"Forest {i}", "Basic Land — Forest", "", is_land=True)


_WILD = _card(
    "Wild Endeavor", "Sorcery",
    "Roll two d4 and choose one result. Create a number of 3/3 green Beast creature tokens equal to that result. "
    "Then search your library for a number of basic land cards equal to the other result, put them onto the "
    "battlefield tapped, then shuffle.",
    is_sorcery=True,
)


def test_wild_endeavor_makes_beasts_and_fetches_lands_by_the_two_results(script_dice):
    assert parse_oracle(_WILD).modeled
    eng = make_engine([_forest(i) for i in range(6)], [_creature_card("Other", "")], hand=0)
    eng.state.current_step = "main1"
    script_dice(3, 2)
    _cast(eng, _WILD)
    eng.resolve_pending_choice("0")  # choose the 3: three Beasts, two lands
    for _ in range(4):  # the search offers one card at a time
        if eng.state.pending_choice is None:
            break
        options = eng.state.pending_choice.get("options") or []
        eng.resolve_pending_choice(options[0]["id"] if options else "0")
        eng.resolve_until_stable()
    assert len(_on_battlefield(eng, "Beast")) == 3
    lands = [o for o in eng.state.battlefield if o.card.is_land and o.controller_id == "p1"]
    assert len(lands) == 2 and all(o.tapped for o in lands)


_GRAVE = _card(
    "Grave Endeavor", "Sorcery",
    "Roll two d10 and choose one result. Return a creature card from your graveyard to the battlefield with a "
    "number of +1/+1 counters on it equal to that result. Then each opponent loses X life and you gain X life, "
    "where X is the other result.",
    is_sorcery=True,
)


def test_grave_endeavor_returns_with_the_chosen_result_as_counters(script_dice):
    assert parse_oracle(_GRAVE).modeled
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    corpse = GameObject(_creature_card("Corpse", "", power=1, toughness=1), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(corpse)
    script_dice(4, 9)
    _cast(eng, _GRAVE)
    eng.resolve_pending_choice("1")  # choose the 9
    while eng.state.pending_choice is not None:
        options = eng.state.pending_choice.get("options") or []
        eng.resolve_pending_choice(options[0]["id"] if options else "0")
        eng.resolve_until_stable()
    assert corpse.zone == Zone.BATTLEFIELD and corpse.counters.get("+1/+1") == 9
    assert p2.life == 20 - 4 and p1.life == 20 + 4  # the other result drains


_ARCANE = _card(
    "Arcane Endeavor", "Sorcery",
    "Roll two d8 and choose one result. Draw cards equal to that result. Then you may cast an instant or sorcery "
    "spell with mana value less than or equal to the other result from your hand without paying its mana cost.",
    is_sorcery=True,
)


def test_arcane_endeavor_casts_only_an_instant_or_sorcery_within_the_other_result(script_dice):
    assert parse_oracle(_ARCANE).modeled
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    cheap = GameObject(_card("Cheap Bolt", "Instant", "You gain 1 life.", is_instant=True,
                             converted_mana_cost=2, mana_cost_string="{1}{R}"), owner_id="p1", zone=Zone.HAND)
    pricey = GameObject(_card("Pricey Bolt", "Sorcery", "You gain 1 life.", is_sorcery=True,
                              converted_mana_cost=5, mana_cost_string="{4}{R}"), owner_id="p1", zone=Zone.HAND)
    creature = GameObject(_creature_card("Cheap Bear", "", converted_mana_cost=1), owner_id="p1", zone=Zone.HAND)
    for obj in (cheap, pricey, creature):
        bind_from_catalogue(obj)
        p1.hand.append(obj)
    script_dice(1, 3)
    _cast(eng, _ARCANE)
    eng.resolve_pending_choice("0")  # choose the 1: draw one; the other result is 3
    choice = eng.state.resolution_play_choice
    assert choice is not None and choice["max_mana_value"] is not None
    offered = set(choice["instance_ids"])
    assert cheap.instance_id in offered
    assert pricey.instance_id not in offered and creature.instance_id not in offered


def test_search_and_reanimate_count_words_parse():
    [fixed] = parse_effect_body("search your library for 2 basic land cards, put them onto the battlefield tapped, then shuffle")
    assert fixed.params["count"] == 2
    [announced] = parse_effect_body("search your library for x basic land cards, put them onto the battlefield tapped, then shuffle")
    assert announced.params["count"] == "x"
    [pick] = parse_effect_body("return a creature card from your graveyard to the battlefield with 2 +1/+1 counters on it")
    assert pick.params["pick"] is True and pick.params["then_effects"][0]["params"]["count"] == 2
    [free] = parse_effect_body("you may cast an instant or sorcery spell with mana value 3 or less from your hand without paying its mana cost")
    assert free.params["instant_sorcery_only"] and free.params["max_mana_value"] == 3


# --- collateral: the search count may be an announced X or a fixed number --------------------------------


def _finish_choices(eng):
    for _ in range(12):
        if eng.state.pending_choice is None:
            break
        options = eng.state.pending_choice.get("options") or []
        eng.resolve_pending_choice(options[0]["id"] if options else "0")
        eng.resolve_until_stable()


_REVELATION = _card(
    "Diabolic Revelation", "Sorcery", "Search your library for up to X cards, put those cards into your hand, then shuffle.",
    mana_cost_string="{X}{3}{B}", is_sorcery=True,
)


def test_search_for_up_to_x_cards_finds_the_announced_x():
    assert parse_oracle(_REVELATION).modeled
    eng = make_engine([_forest(i) for i in range(6)], [_creature_card("Other", "")], hand=0)
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    _cast(eng, _REVELATION, x=2)
    _finish_choices(eng)
    assert len(p1.hand) == 2


def test_search_for_a_fixed_number_of_basic_lands_fetches_that_many():
    sac = _card("Fixed Fetch", "Sorcery",
                "Search your library for two basic land cards, put them onto the battlefield tapped, then shuffle.",
                is_sorcery=True)
    assert parse_oracle(sac).modeled
    eng = make_engine([_forest(i) for i in range(6)], [_creature_card("Other", "")], hand=0)
    eng.state.current_step = "main1"
    _cast(eng, sac)
    _finish_choices(eng)
    assert len([o for o in eng.state.battlefield if o.card.is_land and o.tapped]) == 2


def test_enters_trigger_searches_for_the_x_the_creature_was_cast_with():
    chimney = _creature_card(
        "Spore Test", "Defender\nWhen this creature enters, search your library for up to X basic land cards, "
        "put them onto the battlefield tapped, then shuffle.", mana_cost_string="{X}{G}",
    )
    eng = make_engine([_forest(i) for i in range(6)], [_creature_card("Other", "")], hand=0)
    eng.state.current_step = "main1"
    _cast(eng, chimney, x=3)
    _finish_choices(eng)
    assert len([o for o in eng.state.battlefield if o.card.is_land and o.tapped]) == 3


_SWARMING = _creature_card(
    "Swarming Goblins Test",
    "When this creature enters, roll a d20.\n1—9 | Create a 1/1 red Goblin creature token.\n"
    "10—19 | Create two of those tokens.\n20 | Create three of those tokens.",
)


@pytest.mark.parametrize("face,goblins", [(4, 1), (15, 2), (20, 3)])
def test_of_those_tokens_rows_repeat_the_first_rows_token(script_dice, face, goblins):
    assert parse_oracle(_SWARMING).modeled
    eng = _engine()
    obj = _put(eng, _SWARMING)
    script_dice(face)
    _enter(eng, obj)
    eng.resolve_until_stable()
    assert len(_on_battlefield(eng, "Goblin")) == goblins
