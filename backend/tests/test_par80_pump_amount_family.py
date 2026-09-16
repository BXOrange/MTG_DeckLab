"""PAR-80 second increment: "target creature gets +X/+`<N>` until end of
turn, where X is `<referent>`." for referents beyond a plain
`continuous.count_selector` board count.

Reuses ENG-37's general `bind`/`effect_amounts` measurement
(`game/effect_amounts.py`) over the ordinary `pump` effect instead of a new
`PumpEffect.amount_from_*` boolean per referent: the target's own current
power (`of: "target"`), the most recent die-roll result (`die_result`), a
new RULE 706 non-die randomization (`RandomNumberEffect`/`random_result`),
and an existing count-selector plus a flat offset (the ``plus`` modifier
`amount_of` already supports). Two board counts (a "greatest `<metric>`
among `<scope>` you control" family, and a board-wide counter tally) only
needed new `continuous.count_selector` rows, no new amount kind. Two
genuinely separate mechanics get their own small handler rather than a
forced unification: "reveal a card at random from hand" (a second RULE
115 target) and "reveal any number of `<color>` cards" (an interactive
choice whose *count* the pump measures via `GameObject.revealed_with_ids`,
since a `GameContext` tally doesn't survive that choice's own pause).

Reference: docs/implementation-state/Done_Backend.md's "Oracle-Text Parser
Front-End" PAR-80 entry (once closed).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.continuous import count_selector
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _card(name, type_line="Instant", cost="{1}{G}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


# ---------------------------------------------------------------------------
# Parse-level: the phrase table
# ---------------------------------------------------------------------------


def test_target_own_power_parses_as_bind_over_pump():
    assert parse_effect_body(
        "target creature gets +x/+0 until end of turn, where x is its power."
    ) == [EffectSpec("bind", {
        "name": "px",
        "amount": {"kind": "characteristic", "characteristic": "power", "of": "target"},
        "effects": [{"type": "pump", "params": {
            "power": "$px", "toughness": 0, "target_kind": "creature",
        }}],
    })]


def test_thats_creatures_power_phrase_parses():
    assert parse_effect_body(
        "target creature gets +x/+x until end of turn, where x is that "
        "creature's power."
    ) == [EffectSpec("bind", {
        "name": "px",
        "amount": {"kind": "characteristic", "characteristic": "power", "of": "target"},
        "effects": [{"type": "pump", "params": {
            "power": "$px", "toughness": "$px", "target_kind": "creature",
        }}],
    })]


def test_greatest_mana_value_among_permanents_parses():
    assert parse_effect_body(
        "target creature gets +x/+x until end of turn, where x is the "
        "greatest mana value among permanents you control."
    ) == [EffectSpec("bind", {
        "name": "px",
        "amount": {
            "kind": "count_selector",
            "selector": "greatest_mana_value_among_permanents_you_control",
        },
        "effects": [{"type": "pump", "params": {
            "power": "$px", "toughness": "$px", "target_kind": "creature",
        }}],
    })]


def test_offset_plus_count_selector_parses():
    # "3 plus the number of cards named ~ in all graveyards" (Muscle Burst)
    # — the general ``plus`` amount modifier over an existing selector.
    assert parse_effect_body(
        "target creature gets +x/+x until end of turn, where x is 3 plus "
        "the number of cards named ~ in all graveyards."
    ) == [EffectSpec("bind", {
        "name": "px",
        "amount": {
            "kind": "count_selector",
            "selector": "cards_named_source_in_all_graveyards",
            "plus": 3,
        },
        "effects": [{"type": "pump", "params": {
            "power": "$px", "toughness": "$px", "target_kind": "creature",
        }}],
    })]


def test_die_roll_result_two_clause_body_parses():
    assert parse_effect_body(
        "roll a 6-sided die. target creature gets +x/+x until end of turn, "
        "where x is the result."
    ) == [
        EffectSpec("roll_die", {"sides": 6}),
        EffectSpec("bind", {
            "name": "px", "amount": {"kind": "die_result"},
            "effects": [{"type": "pump", "params": {
                "power": "$px", "toughness": "$px", "target_kind": "creature",
            }}],
        }),
    ]


def test_random_number_chosen_at_random_parses():
    assert parse_effect_body(
        "target creature gets +x/+0 until end of turn, where x is a number "
        "from 0 to 6 chosen at random."
    ) == [
        EffectSpec("random_number", {"min": 0, "max": 6}),
        EffectSpec("bind", {
            "name": "px", "amount": {"kind": "random_result"},
            "effects": [{"type": "pump", "params": {
                "power": "$px", "toughness": 0, "target_kind": "creature",
            }}],
        }),
    ]


def test_reveal_random_hand_card_mana_value_parses():
    assert parse_effect_body(
        "target opponent reveals a card at random from their hand. target "
        "creature gets +x/+x until end of turn, where x is the revealed "
        "card's mana value."
    ) == [
        EffectSpec("reveal_random_hand_card", {"target_kind": "opponent"}),
        EffectSpec("bind", {
            "name": "px",
            "amount": {"kind": "characteristic", "characteristic": "mana_value", "of": "revealed"},
            "effects": [{"type": "pump", "params": {
                "power": "$px", "toughness": "$px", "target_kind": "creature",
            }}],
        }),
    ]


def test_reveal_any_number_green_cards_parses():
    assert parse_effect_body(
        "reveal any number of green cards in your hand. target creature "
        "gets +x/+x until end of turn, where x is the number of cards "
        "revealed this way."
    ) == [
        EffectSpec("reveal_any_number_hand_cards", {"colors": ["G"]}),
        EffectSpec("bind", {
            "name": "px",
            "amount": {"kind": "count_selector", "selector": "revealed_with_count"},
            "effects": [{"type": "pump", "params": {
                "power": "$px", "toughness": "$px", "target_kind": "creature",
            }}],
        }),
    ]


def test_self_sacrifice_at_next_end_step_parses_with_self_capture():
    # "Sacrifice ~ at the beginning of the next end step." — an *explicit*
    # self-reference, must NOT fall onto `previous_or_self` (which would
    # sacrifice an earlier clause's own RULE 115 target instead).
    assert parse_effect_body(
        "sacrifice ~ at the beginning of the next end step."
    ) == [EffectSpec("create_delayed_trigger", {
        "step": "end", "scope": "any", "capture": "self",
        "effects": [{"type": "sacrifice_specific", "params": {}}],
    })]


# ---------------------------------------------------------------------------
# End-to-end: real cards
# ---------------------------------------------------------------------------


def test_sample_real_cards_now_modeled():
    for entry in [
        ("Onward Test", "Instant",
         "Target creature gets +X/+0 until end of turn, where X is its power."),
        ("Nantuko Mentor Test", "Creature — Insect Druid",
         "{2}{G}, {T}: Target creature gets +X/+X until end of turn, where "
         "X is that creature's power."),
        ("Accelerated Mutation Test", "Instant",
         "Target creature gets +X/+X until end of turn, where X is the "
         "greatest mana value among permanents you control."),
        ("Hydra Trainer Test", "Creature — Hydra",
         "You may exert this creature as it attacks. When you do, target "
         "creature gets +X/+X until end of turn, where X is the number of "
         "counters on permanents you control.\n{2}{G}: Adapt 2."),
        ("Timberwatch Elf Test", "Creature — Elf",
         "{T}: Target creature gets +X/+X until end of turn, where X is "
         "the number of Elves on the battlefield."),
        ("Viridian Lorebearers Test", "Creature — Elf Shaman",
         "{3}{G}, {T}: Target creature gets +X/+X until end of turn, where "
         "X is the number of artifacts your opponents control."),
        ("Muscle Burst Test", "Sorcery",
         "Target creature gets +X/+X until end of turn, where X is 3 plus "
         "the number of cards named Muscle Burst Test in all graveyards."),
        ("Growth Spurt Test", "Sorcery",
         "Roll a six-sided die. Target creature gets +X/+X until end of "
         "turn, where X is the result."),
        ("Hapato's Might Test", "Instant",
         "Target creature gets +X/+0 until end of turn, where X is a "
         "number from 0 to 6 chosen at random."),
        ("Planeswalker's Favor Test", "Instant",
         "Target opponent reveals a card at random from their hand. "
         "Target creature gets +X/+X until end of turn, where X is the "
         "revealed card's mana value."),
        ("Ivy Seer Test", "Creature — Elf Druid",
         "{2}{G}, {T}: Reveal any number of green cards in your hand. "
         "Target creature gets +X/+X until end of turn, where X is the "
         "number of cards revealed this way."),
        ("Wine of Blood and Iron Test", "Artifact",
         "{4}: Target creature gets +X/+0 until end of turn, where X is "
         "its power. Sacrifice this artifact at the beginning of the next "
         "end step."),
        ("War Dance Test", "Enchantment",
         "At the beginning of your upkeep, you may put a verse counter on "
         "this enchantment.\nSacrifice this enchantment: Target creature "
         "gets +X/+X until end of turn, where X is the number of verse "
         "counters on this enchantment."),
    ]:
        name, type_line, text = entry
        card = _card(name, type_line=type_line, oracle_text=text, keywords=[])
        result = parse_oracle(card)
        assert result.modeled, f"{name} stayed UNMODELED: {result.unclaimed}"


# ---------------------------------------------------------------------------
# Execute: the target's own power is read before its own pump applies
# ---------------------------------------------------------------------------


def test_target_own_power_executes_before_the_pump_applies():
    eng = _engine()
    state = eng.state
    p1, _p2 = state.players
    spell = GameObject(
        _card("Onward Test", oracle_text="Target creature gets +X/+0 until "
              "end of turn, where X is its power."),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    target = _bf(state, _card("Target", type_line="Creature — Bear",
                               is_creature=True, power=3, toughness=3))

    p1.mana_pool.add_many({"G": 2})
    eng.cast_spell(p1, spell, targets=[target])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert target.power == 6  # 3 base + 3 (its own printed power)
    assert target.toughness == 3


def test_greatest_mana_value_among_permanents_reads_live_board_state():
    eng = _engine()
    state = eng.state
    p1, _p2 = state.players
    spell = GameObject(
        _card("Accelerated Mutation Test", oracle_text=(
            "Target creature gets +X/+X until end of turn, where X is the "
            "greatest mana value among permanents you control."
        )),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    target = _bf(state, _card("Target", type_line="Creature — Bear",
                               is_creature=True, power=2, toughness=2))
    _bf(state, _card("Costly Permanent", type_line="Artifact", cmc=5))

    p1.mana_pool.add_many({"G": 2})
    eng.cast_spell(p1, spell, targets=[target])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert target.power == 7  # 2 base + 5 (the costliest permanent p1 controls)
    assert target.toughness == 7


def test_wine_of_blood_and_iron_sacrifices_itself_not_the_pumped_target():
    # The delayed "sacrifice ~" must capture the *source*, not whatever the
    # earlier clause of the same resolution targeted (the pumped creature) —
    # `previous_or_self` would get this wrong; ``capture="self"`` doesn't.
    eng = _engine()
    state = eng.state
    p1, _p2 = state.players
    wine = _bf(state, _card(
        "Wine of Blood and Iron", type_line="Artifact", cmc=3,
        oracle_text=(
            "{4}: Target creature gets +X/+0 until end of turn, where X is "
            "its power. Sacrifice this artifact at the beginning of the "
            "next end step."
        ),
    ))
    target = _bf(state, _card("Target", type_line="Creature — Bear",
                               is_creature=True, power=3, toughness=3),
                 controller="p2")

    p1.mana_pool.add_many({"C": 4})
    ability_index = next(
        i for i, a in enumerate(wine.activated_abilities)
    )
    eng.activate_ability(p1, wine, ability_index, targets=[target])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert target.power == 6
    assert len(state.delayed_triggers) == 1
    delayed = state.delayed_triggers[0]
    captured = delayed.effects[0].objects
    assert captured == [wine]
    assert target not in captured


def test_revealed_with_count_selector_reads_source_reveal_list():
    eng = _engine()
    card = _card("Ivy Seer Test", type_line="Creature — Elf")
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    assert count_selector(eng.state, "p1", "revealed_with_count", source=source) == 0
    source.revealed_with_ids = [10, 11, 12]
    assert count_selector(eng.state, "p1", "revealed_with_count", source=source) == 3
