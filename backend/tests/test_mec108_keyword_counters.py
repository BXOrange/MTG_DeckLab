"""MEC-108: keyword counters (RULE 122.1b).

A `flying`/`first strike`/`double strike`/`deathtouch`/`haste`/`hexproof`/
`indestructible`/`lifelink`/`menace`/`reach`/`shadow`/`trample`/`vigilance`
counter makes its permanent gain that keyword. Covers the layer-6 reader
(`continuous.KEYWORD_COUNTER_SLUGS`), the parser rows that reach it (single and
compound "put …", "your choice of …", "remove a … counter", enters-with,
return-with) and the two interactive choices (`counter_kind`,
`choose_enter_counter`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.catalogue import counters as counter_grammar
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.static_handlers import enter_choice_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec

#: counter kind → the `combat.has_*` predicate that must flip when one is present.
KEYWORD_PREDICATES = {
    "flying": combat.has_flying,
    "first strike": combat.has_first_strike,
    "double strike": combat.has_double_strike,
    "deathtouch": combat.has_deathtouch,
    "haste": combat.has_haste,
    "hexproof": combat.has_hexproof,
    "indestructible": combat.has_indestructible,
    "lifelink": combat.has_lifelink,
    "menace": combat.has_menace,
    "reach": combat.has_reach,
    "shadow": combat.has_shadow,
    "trample": combat.has_trample,
    "vigilance": combat.has_vigilance,
}


def _engine() -> GameEngine:
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(name: str = "Bear", text: str = "", power: int = 2, toughness: int = 2) -> Card:
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness, oracle_text=text,
    )


def _put(eng: GameEngine, card: Card, owner: str = "p1", bind: bool = False) -> GameObject:
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    if bind:
        bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _resolve(eng: GameEngine) -> None:
    eng.resolve_until_stable()


# ---------------------------------------------------------------------------
# The layer-6 reader
# ---------------------------------------------------------------------------


def test_parser_and_engine_agree_on_the_keyword_counter_kinds():
    assert set(counter_grammar.KEYWORD_COUNTER_KINDS) == set(continuous.KEYWORD_COUNTER_SLUGS)
    assert set(KEYWORD_PREDICATES) == set(continuous.KEYWORD_COUNTER_SLUGS)


@pytest.mark.parametrize("kind", sorted(KEYWORD_PREDICATES))
def test_a_keyword_counter_grants_its_keyword(kind):
    eng = _engine()
    bear = _put(eng, _creature())
    predicate = KEYWORD_PREDICATES[kind]
    eng.recompute_continuous_effects()
    assert not predicate(bear)

    eng.rules.add_counters(bear, 1, kind)
    eng.recompute_continuous_effects()
    assert predicate(bear)
    assert continuous.KEYWORD_COUNTER_SLUGS[kind] in bear.granted_keywords
    # the derived-state trace names the source, like every other layer-6 grant
    assert any("Keyword counter" in str(line) for line in bear.static_trace)

    eng.rules.add_counters(bear, -1, kind)
    eng.recompute_continuous_effects()
    assert not predicate(bear)  # last counter gone -> keyword gone (no cleanup needed)


def test_two_counters_do_not_stack_and_one_removal_keeps_the_keyword():
    eng = _engine()
    bear = _put(eng, _creature())
    eng.rules.add_counters(bear, 2, "flying")
    eng.rules.add_counters(bear, -1, "flying")
    eng.recompute_continuous_effects()
    assert combat.has_flying(bear)
    assert bear.counters["flying"] == 1


def test_a_flying_counter_changes_blocking():
    eng = _engine()
    attacker = _put(eng, _creature("Drake"))
    blocker = _put(eng, _creature("Wall"), owner="p2")
    eng.recompute_continuous_effects()
    assert combat.can_block(attacker, blocker)
    eng.rules.add_counters(attacker, 1, "flying")
    eng.recompute_continuous_effects()
    assert not combat.can_block(attacker, blocker)


def test_counters_that_are_not_keyword_counters_grant_nothing():
    eng = _engine()
    bear = _put(eng, _creature())
    eng.rules.add_counters(bear, 1, "charge")
    eng.rules.add_counters(bear, 1, "decayed")  # RULE 122.1b lists it, but it's no combat keyword here
    eng.recompute_continuous_effects()
    assert bear.granted_keywords == set()


def test_a_keyword_counter_is_not_retained_across_a_zone_change():
    eng = _engine()
    bear = _put(eng, _creature())
    eng.rules.add_counters(bear, 1, "flying")
    eng.recompute_continuous_effects()
    assert combat.has_flying(bear)
    # RULE 122.2: counters aren't retained when the object changes zones
    eng.rules.put_into_graveyard(bear)
    eng.rules.return_from_graveyard(bear, "battlefield")
    eng.recompute_continuous_effects()
    assert bear in eng.state.battlefield
    assert not bear.counters.get("flying") and not combat.has_flying(bear)


# ---------------------------------------------------------------------------
# Parser: put / compound / choice / remove
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(KEYWORD_PREDICATES))
def test_put_a_keyword_counter_on_self_parses(kind):
    assert match_clause(f"put a {kind} counter on ~") == [
        EffectSpec("add_counters", {"count": 1, "kind": kind})
    ]


def test_put_a_keyword_counter_on_target_parses():
    assert match_clause("put a flying counter on target creature you control") == [
        EffectSpec("add_counters", {"count": 1, "kind": "flying", "target_kind": "creature_you_control"})
    ]


def test_put_a_keyword_counter_on_each_creature_parses():
    [spec] = match_clause("put a flying counter on each creature you control")
    assert spec.params["kind"] == "flying" and spec.params["group"]["filter"] == {"card_type": "creature"}


def test_compound_list_on_a_target_reads_the_target_back_for_later_kinds():
    assert match_clause("put a +1/+1 counter and a lifelink counter on target creature you control") == [
        EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "target_kind": "creature_you_control"}),
        EffectSpec("add_counters", {"count": 1, "kind": "lifelink", "previous_subject": True}),
    ]


def test_compound_list_on_self_and_three_items():
    assert match_clause("put 2 +1/+1 counters, a first strike counter, and a flying counter on ~") == [
        EffectSpec("add_counters", {"count": 2, "kind": "+1/+1"}),
        EffectSpec("add_counters", {"count": 1, "kind": "first strike"}),
        EffectSpec("add_counters", {"count": 1, "kind": "flying"}),
    ]


def test_compound_list_with_an_unknown_kind_stays_unclaimed():
    # `age` is read by name (cumulative upkeep) and stays reserved; an open tracker kind now parses (PAR-135).
    assert match_clause("put a flying counter and an age counter on ~") is None


def test_choice_of_counter_kinds_parses_into_kind_options():
    assert match_clause("put your choice of a +1/+1, first strike, or trample counter on target creature you control") == [
        EffectSpec("add_counters", {
            "kind_options": [
                {"kind": "+1/+1", "count": 1},
                {"kind": "first strike", "count": 1},
                {"kind": "trample", "count": 1},
            ],
            "target_kind": "creature_you_control",
        })
    ]


def test_choice_options_carry_their_own_amount():
    [spec] = match_clause("put your choice of a +1/+1 counter or 2 charge counters on ~")
    assert spec.params["kind_options"] == [
        {"kind": "+1/+1", "count": 1}, {"kind": "charge", "count": 2},
    ]


def test_remove_a_keyword_counter_parses():
    assert match_clause("remove a menace counter from ~") == [
        EffectSpec("remove_counters", {"self_only": True, "kind": "menace", "count": 1})
    ]
    assert match_clause("remove a counter from ~") is None  # no kind named -> not this row


def test_enters_with_your_choice_is_an_enter_replacement():
    assert enter_choice_specs("~ enters with your choice of a flying counter or a first strike counter on it.") == [
        EffectSpec("choose_enter_counter", {"options": [
            {"kind": "flying", "count": 1}, {"kind": "first strike", "count": 1},
        ]})
    ]
    assert enter_choice_specs("~ enters with your choice of a flying counter or a banana counter on it.") is None


def test_entry_counter_shapes():
    cond = counter_grammar.entry_counters_condition
    assert cond("~ enters with a first strike counter on it.") == {
        "is_x": False, "count": 1, "counter_type": "first strike",
    }
    assert cond("~ enters with 2 +1/+1 counters and a lifelink counter on it.") == {
        "is_x": False, "count": 2, "counter_type": "+1/+1",
        "extra_counters": [{"counter_type": "lifelink", "count": 1}],
    }
    assert cond("~ enters with your choice of a flying counter or a lifelink counter on it.") is None


def test_return_from_graveyard_with_a_keyword_counter_parses():
    [spec] = match_clause("return target creature card from your graveyard to the battlefield with a lifelink counter on it")
    assert spec.params["extra_counters"] == {"kind": "lifelink", "count": 1}
    # the existing persist-style -1/-1 rider is unchanged
    [old] = match_clause("return target creature card from your graveyard to the battlefield with a -1/-1 counter on it")
    assert old.params["extra_counters"] == {"kind": "-1/-1", "count": 1}


@pytest.mark.parametrize("name,text", [
    ("Nezumi Prowler", "When Nezumi Prowler enters, put a deathtouch counter and a lifelink counter on target creature you control."),
    ("Boot Nipper", "Boot Nipper enters with your choice of a deathtouch counter or a lifelink counter on it."),
    ("Avenging Huntbonder", "Whenever Avenging Huntbonder attacks, put a double strike counter on another target attacking creature."),
    ("Helica Glider", "Flying\nHelica Glider enters with your choice of a flying counter or a first strike counter on it."),
])
def test_real_card_text_is_modeled(name, text):
    card = _creature(name, text)
    assert parse_oracle(card).modeled, name


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def test_etb_compound_on_self_executes():
    eng = _engine()
    card = _creature("Hoarder", "When ~ enters, put a +1/+1 counter and a lifelink counter on ~.")
    obj = _put(eng, card, bind=True)
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id="p1",
        object=obj.name, object_types=sorted(obj.type_words),
    ))
    eng.rules.put_triggers_on_stack()
    _resolve(eng)
    eng.recompute_continuous_effects()
    assert obj.counters.get("lifelink") == 1 and obj.plus_one_counters == 1
    assert combat.has_lifelink(obj) and obj.power == 3


def test_compound_on_a_target_puts_every_kind_on_that_target():
    eng = _engine()
    ally = _put(eng, _creature("Ally"))
    card = _creature("Prowler", "When ~ enters, put a deathtouch counter and a lifelink counter on target creature you control.")
    obj = _put(eng, card, bind=True)
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id="p1",
        object=obj.name, object_types=sorted(obj.type_words),
    ))
    eng.rules.put_triggers_on_stack()
    # a target-choosing trigger may ask first; answer with whatever it offers for the ally
    choice = eng.state.pending_choice
    if choice:
        opts = [o for o in choice["options"] if str(o.get("instance_id")) == str(ally.instance_id)]
        eng.resolve_pending_choice(opts[0]["id"] if opts else choice["options"][0]["id"])
    _resolve(eng)
    eng.recompute_continuous_effects()
    landed = [o for o in (ally, obj) if o.counters.get("deathtouch")]
    assert len(landed) == 1
    target = landed[0]
    assert target.counters.get("lifelink") == 1  # same creature got both kinds
    assert combat.has_deathtouch(target) and combat.has_lifelink(target)


def test_your_choice_of_counter_kind_opens_a_choice_and_places_the_pick():
    eng = _engine()
    card = _creature("Trainer", "When ~ enters, put your choice of a flying counter or a lifelink counter on ~.")
    obj = _put(eng, card, bind=True)
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id="p1",
        object=obj.name, object_types=sorted(obj.type_words),
    ))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    choice = eng.state.pending_choice
    assert choice and choice["kind"] == "counter_kind"
    assert [o["label"] for o in choice["options"]] == ["flying", "lifelink"]
    assert not obj.counters  # nothing is placed until the pick
    eng.resolve_pending_choice("1")
    eng.recompute_continuous_effects()
    assert obj.counters == {"lifelink": 1}
    assert combat.has_lifelink(obj) and not combat.has_flying(obj)


def test_counter_kind_choice_defaults_to_the_first_option_on_a_bad_answer():
    eng = _engine()
    card = _creature("Trainer", "When ~ enters, put your choice of a flying counter or a lifelink counter on ~.")
    obj = _put(eng, card, bind=True)
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id="p1",
        object=obj.name, object_types=sorted(obj.type_words),
    ))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_pending_choice("not-an-option")
    assert obj.counters == {"flying": 1}


def _enter_engine(card: Card) -> GameEngine:
    return GameEngine.new_game([("p1", "Alice", [card])], starting_life=20, starting_hand=1)


def _hard_cast_creature(name: str, text: str) -> Card:
    return Card(
        id=name, name=name, type_line="Creature — Beast", mana_cost_string="{1}{G}",
        converted_mana_cost=ManaCost.parse("{1}{G}").converted_mana_cost,
        is_creature=True, power=2, toughness=2, oracle_text=text,
    )


def test_enters_with_your_choice_asks_before_entering_and_places_the_pick():
    card = _hard_cast_creature(
        "Glider", "~ enters with your choice of a flying counter or a first strike counter on it."
    )
    eng = _enter_engine(card)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player = eng.state.active_player
    player.mana_pool.add_many({"G": 1, "C": 1})
    bind_from_catalogue(player.hand[0])
    eng.cast_spell(player, player.hand[0])
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice and choice["kind"] == "choose_enter_counter"
    assert not any(o.name == "Glider" for o in eng.state.battlefield)  # still an "as it enters" pick

    eng.resolve_pending_choice("1")
    eng.resolve_until_stable()
    glider = next(o for o in eng.state.battlefield if o.name == "Glider")
    eng.recompute_continuous_effects()
    assert glider.counters == {"first strike": 1}
    assert combat.has_first_strike(glider) and not combat.has_flying(glider)


def test_enters_with_a_compound_places_every_counter():
    card = _hard_cast_creature("Brute", "~ enters with 2 +1/+1 counters and a lifelink counter on it.")
    eng = _enter_engine(card)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player = eng.state.active_player
    player.mana_pool.add_many({"G": 1, "C": 1})
    bind_from_catalogue(player.hand[0])
    eng.cast_spell(player, player.hand[0])
    eng.resolve_until_stable()
    brute = next(o for o in eng.state.battlefield if o.name == "Brute")
    eng.recompute_continuous_effects()
    assert brute.plus_one_counters == 2 and brute.counters.get("lifelink") == 1
    assert brute.power == 4 and combat.has_lifelink(brute)


def test_enters_with_a_first_strike_counter_grants_first_strike():
    card = _hard_cast_creature("Duelist", "~ enters with a first strike counter on it.")
    eng = _enter_engine(card)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player = eng.state.active_player
    player.mana_pool.add_many({"G": 1, "C": 1})
    bind_from_catalogue(player.hand[0])
    eng.cast_spell(player, player.hand[0])
    eng.resolve_until_stable()
    duelist = next(o for o in eng.state.battlefield if o.name == "Duelist")
    eng.recompute_continuous_effects()
    assert combat.has_first_strike(duelist)


def test_remove_a_keyword_counter_effect_executes_and_takes_the_keyword_back():
    eng = _engine()
    card = _creature("Monk", "When ~ enters, remove a menace counter from ~.")
    obj = _put(eng, card, bind=True)
    eng.rules.add_counters(obj, 2, "menace")
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id="p1",
        object=obj.name, object_types=sorted(obj.type_words),
    ))
    eng.rules.put_triggers_on_stack()
    _resolve(eng)
    eng.recompute_continuous_effects()
    assert obj.counters.get("menace") == 1 and combat.has_menace(obj)  # exactly one removed, not all

    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id="p1",
        object=obj.name, object_types=sorted(obj.type_words),
    ))
    eng.rules.put_triggers_on_stack()
    _resolve(eng)
    eng.recompute_continuous_effects()
    assert not obj.counters.get("menace") and not combat.has_menace(obj)


def test_remove_with_no_such_counter_is_a_no_op():
    eng = _engine()
    card = _creature("Monk", "When ~ enters, remove a menace counter from ~.")
    obj = _put(eng, card, bind=True)
    eng.rules.add_counters(obj, 1, "charge")
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id="p1",
        object=obj.name, object_types=sorted(obj.type_words),
    ))
    eng.rules.put_triggers_on_stack()
    _resolve(eng)
    assert obj.counters == {"charge": 1}
