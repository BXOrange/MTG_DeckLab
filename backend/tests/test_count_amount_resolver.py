"""RULE 613.7c's "X is the number of `<noun phrase>` you control" general
count-amount resolver (MEC-12's own gap — 446 cards solo-blocked on this
single template, `parser_probe.py blocked "where x is the number of"`).

The engine-side primitives already existed for the common noun phrases
(`continuous.count_selector`'s ``creatures_you_control``/``attacking_
creatures_you_control``/``tapped_creatures_you_control``/``creatures_you_
control_of_type_<x>``/``legendary_creatures_you_control``, …) — the real
gap was purely parser-side: every amount-suffix handler that already knew
how to read "your devotion to `<colour>`" had no way to read the far more
common "the number of `<phrase>` you control" instead. Folding the new
reading into the *same* `subgrammars.DEVOTION` fragment (not a sibling
constant) means every handler that already embeds `{DEVOTION}` — the
target/group/negative pump family, damage-to-players, life-loss, the
devotion-scaled token count — picks it up for free with no per-handler
change; this batch adds one more embedding, the devotion-scaled sibling of
`_pump_self_subject`'s fixed-int "it gets +N/+N" self-buff-on-attack row
(Bag End Porter/Angelic Exaltation-adjacent), which previously had none.

Deliberately narrow, matching the fragment's own docstring: only the plain
noun phrases a `count_selector` entry already exists for, plus (since
MEC-27) two qualified shapes — "creatures you control with power N or
less/greater" and "tapped `<type>`[ and/or `<type>`] you control". A
two-word subtype phrase, or any other qualifier (toughness, "with power N
or less" on anything but bare "creatures"), still stays unclaimed rather
than guessed.

MEC-27 also widened the amount-suffix side: the "draw"/"you gain life"/"you
lose life" verb families now embed `{DEVOTION}` too (previously only
damage/life-loss-to-each-opponent/counters/pump/tokens did), plus three
combined "draw and gain/lose life"/"lose and gain life" templates that share
one `{DEVOTION}` amount across two effects in printed order.
"""

from __future__ import annotations

import re

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.subgrammars import DEVOTION, devotion_selector
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def creature(name, power=2, toughness=2, oracle_text="", keywords=None):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []),
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# -- the shared fragment itself -----------------------------------------------


def _resolve(phrase: str):
    pat = re.compile(DEVOTION, re.IGNORECASE)
    m = pat.fullmatch(phrase)
    return devotion_selector(m) if m else None


def test_bare_creatures_you_control():
    assert _resolve("the number of creatures you control") == "creatures_you_control"


def test_attacking_creatures_you_control():
    assert _resolve("the number of attacking creatures you control") == "attacking_creatures_you_control"


def test_bare_attacking_creatures():
    assert _resolve("the number of attacking creatures") == "attacking_creatures"


def test_tapped_creatures_you_control():
    assert _resolve("the number of tapped creatures you control") == "tapped_creatures_you_control"


def test_a_single_subtype_word():
    assert _resolve("the number of zombies you control") == "creatures_you_control_of_type_zombie"


def test_legendary_creatures_compound():
    assert _resolve("the number of legendary creatures you control") == "legendary_creatures_you_control"


def test_devotion_still_resolves_after_the_widening():
    assert _resolve("your devotion to blue") == "devotion_to_blue"


# -- MEC-27: the qualifier grammar --------------------------------------------


def test_power_qualifier_less():
    assert (
        _resolve("the number of creatures you control with power 2 or less")
        == "creatures_you_control_with_power_le_2"
    )


def test_power_qualifier_greater():
    assert (
        _resolve("the number of creatures you control with power 4 or greater")
        == "creatures_you_control_with_power_ge_4"
    )


def test_toughness_qualifier_still_stays_unresolved():
    # Only power is built (real printed cards use power, never toughness, in
    # this exact template) — still fail-closed on the untouched dimension.
    assert _resolve("the number of creatures you control with toughness 2 or less") is None


def test_tapped_creatures_you_control_unchanged_after_generalizing():
    # The old creatures-only literal branch is gone, folded into the general
    # "tapped <type>[ and/or <type>] you control" one — must still resolve to
    # the exact same name every existing caller/test expects.
    assert _resolve("the number of tapped creatures you control") == "tapped_creatures_you_control"


def test_tapped_bare_word_you_control():
    assert _resolve("the number of tapped artifacts you control") == "tapped_artifacts_you_control"


def test_tapped_subtype_you_control():
    assert _resolve("the number of tapped assassins you control") == "tapped_type_assassin_you_control"


def test_tapped_and_or_two_bare_words():
    assert (
        _resolve("the number of tapped artifacts and/or creatures you control")
        == "tapped_artifacts_and_or_creatures_you_control"
    )


def test_noncreature_subtype_word_stays_unresolved():
    # "Bobbleheads"/"Shrines" are real cards' artifact-/enchantment-subtype
    # noun phrases, not creature types — the bare `count_subtype` catch-all
    # must not guess `creatures_you_control_of_type_bobblehead` (always 0)
    # for them. Found while sizing MEC-27's draw-verb widening: Charisma/
    # Strength Bobblehead had been silently mis-modeled this way since the
    # counter/token devotion rows shipped, always creating/counting 0.
    assert _resolve("the number of bobbleheads you control") is None
    assert _resolve("the number of shrines you control") is None


# -- an existing target-pump handler picks up the new reading for free -----


def test_target_pump_with_count_phrase_is_modeled():
    card = Card(
        id="Test Pump Spell", name="Test Pump Spell", type_line="Instant", is_instant=True,
        mana_cost_string="{1}{G}", converted_mana_cost=2,
        oracle_text="Target creature gets +X/+X until end of turn, where X "
                    "is the number of creatures you control.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


# -- new self-subject devotion-scaled pump row -------------------------------


def test_self_subject_count_phrase_pump_parses():
    effects = parse_effect_body(
        "it gets +x/+x until end of turn, where x is the number of creatures you control",
        self_subject=True,
    )
    assert effects is not None
    assert len(effects) == 1
    assert effects[0].type == "pump"
    assert effects[0].params.get("amount_from_count_selector") == "creatures_you_control"


def test_bag_end_porter_is_modeled():
    card = creature(
        "Bag End Porter", power=3, toughness=3,
        oracle_text="Whenever this creature attacks, it gets +X/+X until end of turn, "
                    "where X is the number of legendary creatures you control.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_bag_end_porter_scales_with_legendary_creatures_you_control():
    eng = make_engine("p1", "p2")
    porter = put(eng.state, creature(
        "Bag End Porter", power=3, toughness=3,
        oracle_text="Whenever this creature attacks, it gets +X/+X until end of turn, "
                    "where X is the number of legendary creatures you control.",
    ))
    legend = creature("A Legend", power=1, toughness=1)
    legend.type_line = "Legendary Creature — Human"
    legend.is_legendary = True
    put(eng.state, legend)

    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(eng.state.active_player, [porter])
    eng.resolve_until_stable()

    assert (porter.power, porter.toughness) == (4, 4)


# -- MEC-27: the counter family gains the same devotion-amount reading -------


def test_add_counters_devotion_clause_parses():
    effects = parse_effect_body(
        # "goblins" (regular plural) rather than "elves" (irregular) — the
        # `_singularize` gap only strips a trailing "s", a documented,
        # pre-existing limitation this test isn't about.
        "put x +1/+1 counters on target creature you control, where x is the number of goblins you control"
    )
    assert effects is not None
    assert len(effects) == 1
    assert effects[0].type == "add_counters"
    assert effects[0].params.get("amount_from_count_selector") == "creatures_you_control_of_type_goblin"
    assert effects[0].params.get("target_kind") == "creature_you_control"


def test_leyline_invocation_is_modeled():
    card = Card(
        id="Leyline Invocation", name="Leyline Invocation", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{4}{G}{U}", converted_mana_cost=6,
        oracle_text="Create a 0/0 green and blue Fractal creature token. Put X +1/+1 "
                    "counters on it, where X is the number of lands you control.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_add_counters_devotion_scales_with_lands_you_control():
    eng = make_engine("p1", "p2")
    for i in range(3):
        put(eng.state, Card(
            id=f"Land {i}", name=f"Land {i}", type_line="Basic Land — Forest", is_land=True,
        ))
    source = put(eng.state, creature("Counter Source", oracle_text=(
        "When this creature enters, put x +1/+1 counters on it, "
        "where x is the number of lands you control."
    )))

    from mtg_analyzer.models.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", instance_id=source.instance_id,
        object=source.name, object_types=sorted(source.type_words),
    ))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    # base 2/2 + 3 lands' worth of +1/+1 counters = 5/5.
    assert (source.power, source.toughness) == (5, 5)


# -- MEC-27: create_token's "where x is" tail widened past subtype/attacking


def test_create_token_xx_where_reads_bare_devotion_phrase():
    effects = parse_effect_body(
        "create x 1/1 white soldier creature tokens, where x is the number of creatures you control"
    )
    assert effects is not None
    assert len(effects) == 1
    assert effects[0].type == "create_token"
    assert effects[0].params.get("count_selector") == "creatures_you_control"


def test_create_token_xx_where_still_reads_attacking_creatures():
    # The pre-widening phrasing (Galadhrim Ambush-shaped) must keep working —
    # `attacking_creatures` is one of `DEVOTION`'s own bare-phrase readings.
    effects = parse_effect_body(
        "create x 1/1 green elf warrior creature tokens, where x is the number of attacking creatures"
    )
    assert effects is not None
    assert effects[0].params.get("count_selector") == "attacking_creatures"


def test_create_token_bare_devotion_scales_with_creatures_you_control():
    eng = make_engine("p1", "p2")
    put(eng.state, creature("Ally One"))
    source = put(eng.state, creature("Token Source", oracle_text=(
        "When this creature enters, create x 1/1 white Soldier creature "
        "tokens, where x is the number of creatures you control."
    )))

    from mtg_analyzer.models.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", instance_id=source.instance_id,
        object=source.name, object_types=sorted(source.type_words),
    ))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    # 2 creatures on the board when the trigger resolves (Ally One + Token
    # Source itself) → 2 Soldier tokens created.
    soldiers = [o for o in eng.state.battlefield if o.name == "Soldier"]
    assert len(soldiers) == 2


# -- MEC-27: the draw/gain-life/lose-life verb families -----------------------


def test_draw_devotion_parses():
    effects = parse_effect_body("draw x cards, where x is the number of creatures you control")
    assert effects is not None
    assert len(effects) == 1
    assert effects[0].type == "draw"
    assert effects[0].params.get("amount_from_count_selector") == "creatures_you_control"


def test_gain_life_devotion_parses():
    effects = parse_effect_body("you gain x life, where x is the number of creatures you control")
    assert effects is not None
    assert len(effects) == 1
    assert effects[0].type == "gain_life"
    assert effects[0].params.get("count_selector") == "creatures_you_control"


def test_lose_life_self_devotion_parses():
    effects = parse_effect_body("you lose x life, where x is the number of creatures you control")
    assert effects is not None
    assert len(effects) == 1
    assert effects[0].type == "lose_life"
    assert effects[0].params.get("amount_from_count_selector") == "creatures_you_control"


def test_champion_of_dusk_is_modeled():
    card = creature(
        "Champion of Dusk", power=3, toughness=3,
        oracle_text="When this creature enters, you draw X cards and you lose X life, "
                    "where X is the number of Vampires you control.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_draw_devotion_scales_with_creatures_you_control():
    eng = make_engine("p1", "p2")
    put(eng.state, creature("Ally One"))
    source = put(eng.state, creature("Draw Source", oracle_text=(
        "When this creature enters, you draw x cards and you lose x life, "
        "where x is the number of creatures you control."
    )))
    p1 = eng.state.player_by_id("p1")
    for i in range(10):
        p1.library.append(GameObject(
            Card(id=f"Filler {i}", name=f"Filler {i}", type_line="Instant", is_instant=True),
            owner_id="p1", zone=Zone.LIBRARY,
        ))

    from mtg_analyzer.models.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", instance_id=source.instance_id,
        object=source.name, object_types=sorted(source.type_words),
    ))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    before_life = eng.state.player_by_id("p1").life
    eng.resolve_until_stable()

    # 2 creatures on the board when the trigger resolves (Ally One + Draw
    # Source itself) → draw 2, lose 2 life.
    assert len(eng.state.player_by_id("p1").hand) == 2
    assert eng.state.player_by_id("p1").life == before_life - 2


def test_lose_life_and_gain_life_devotion_parses():
    # Mishra, Claimed by Gix-shaped drain — must be claimed as *one* clause,
    # not left to the generic " and " connector split (which would hand the
    # first half's literal "x" to the plain `_lose_life_selector` row's
    # {X}-announcement sentinel — never substituted for a triggered ability
    # with no X cost — and crash comparing a string to 0).
    effects = parse_effect_body(
        "each opponent loses x life and you gain x life, where x is the number of attacking creatures"
    )
    assert effects is not None
    assert len(effects) == 2
    assert effects[0].type == "lose_life"
    assert effects[0].params.get("amount_from_count_selector") == "attacking_creatures"
    assert effects[0].params.get("selector") == "each_opponent"
    assert effects[1].type == "gain_life"
    assert effects[1].params.get("count_selector") == "attacking_creatures"


def test_lose_life_and_gain_life_devotion_resolves_without_crashing():
    # Before this handler existed, the generic " and " connector split would
    # have handed the first half's literal "x" to the plain
    # `_lose_life_selector` row, whose `amount="x"` is only ever substituted
    # for an announced-{X} spell/ability — never for this ability — so
    # `LoseLifeEffect.apply`'s `amount <= 0` would crash comparing a string
    # to an int. Exercised directly through `GameContext`/`build_effects`
    # rather than a real trigger firing, since this is about the effect
    # *list* resolving correctly, not trigger-condition recognition.
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import GameContext

    eng = make_engine("p1", "p2")
    attacker = put(eng.state, creature("Attacker One", power=2, toughness=2))
    attacker.attacking = True

    specs = parse_effect_body(
        "each opponent loses x life and you gain x life, where x is the number of attacking creatures"
    )
    effects = build_effects(specs, source=attacker)

    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    before_p1, before_p2 = p1.life, p2.life
    ctx = GameContext(eng.state, eng.rules)
    for effect in effects:
        effect.apply(ctx)

    assert p2.life == before_p2 - 1
    assert p1.life == before_p1 + 1
