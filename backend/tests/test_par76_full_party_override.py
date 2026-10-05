"""PAR-76: "Full party" (RULE 700.8/702.129) as a conditional-magnitude
override — "`<base effect>`. If you have a full party, `<bigger effect>`
instead." Generalizes the already-shipped `DealDamageEffect.amount_if_
kicked`/`amount_if_raid` override family (PAR-64) with a new `amount_if_
full_party` field, also added to `AddCountersEffect`, both reading the
already-shipped `"creatures_in_your_party"` count selector (PAR-53/72) as a
live >= 4 threshold rather than a magnitude.

Two real cards:

* The Destined Black Mage — "Whenever you cast a noncreature spell, ~ deals
  1 damage to each opponent. If you have a full party, it deals 3 damage
  to each opponent instead."
* The Destined White Mage — "Whenever you gain life, put a +1/+1 counter on
  target creature you control. If you have a full party, put 3 +1/+1
  counters on that creature instead."

Reference: docs/implementation-state/Done_Backend.md's "Oracle-Text Parser
Front-End" PAR-76 entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _card(name, type_line="Creature — Bear", cost="{1}{G}", cmc=2, **kw):
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
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


def _fill_party(state, controller="p1"):
    for role in ("Cleric", "Rogue", "Warrior", "Wizard"):
        _bf(state, _card(f"Test {role}", f"Creature — Human {role}"), controller=controller)


# ---------------------------------------------------------------------------
# Real cards: full MODELED verdict
# ---------------------------------------------------------------------------


def test_the_destined_black_mage_modeled():
    card = _card(
        "The Destined Black Mage", is_creature=True,
        oracle_text=(
            "Deathtouch\n"
            "{B}, {T}: Another target creature you control gains "
            "deathtouch until end of turn.\n"
            "Whenever you cast a noncreature spell, ~ deals 1 damage to "
            "each opponent. If you have a full party, it deals 3 damage "
            "to each opponent instead."
        ),
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_the_destined_white_mage_modeled():
    card = _card(
        "The Destined White Mage", is_creature=True,
        oracle_text=(
            "Lifelink\n"
            "{W}, {T}: Another target creature you control gains "
            "lifelink until end of turn.\n"
            "Whenever you gain life, put a +1/+1 counter on target "
            "creature you control. If you have a full party, put 3 "
            "+1/+1 counters on that creature instead."
        ),
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


# ---------------------------------------------------------------------------
# Parse-level
# ---------------------------------------------------------------------------


def test_damage_each_opponent_full_party_parses():
    assert parse_effect_body(
        "~ deals 1 damage to each opponent. if you have a full party, it "
        "deals 3 damage to each opponent instead", self_subject=True,
    ) == [EffectSpec("damage", {
        "amount": 1, "selector": "each_opponent", "amount_if_full_party": 3,
    })]


def test_add_counter_target_full_party_parses():
    assert parse_effect_body(
        "put a +1/+1 counter on target creature you control. if you have "
        "a full party, put 3 +1/+1 counters on that creature instead"
    ) == [EffectSpec("add_counters", {
        "kind": "+1/+1", "target_kind": "creature_you_control",
        "amount_if_full_party": 3,
    })]


# ---------------------------------------------------------------------------
# Execute: damage
# ---------------------------------------------------------------------------


def test_damage_deals_base_amount_without_a_full_party():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test Black Mage", is_creature=True,
        oracle_text=(
            "Whenever you cast a spell, ~ deals 1 damage to each "
            "opponent. If you have a full party, it deals 3 damage to "
            "each opponent instead."
        ),
    ))
    spell = GameObject(_card("Test Spell", "Sorcery", cost="{1}", cmc=1), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)

    p1.mana_pool.add_many({"C": 1})
    life_before = p2.life
    eng.rules.cast_spell(p1, spell)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert p2.life == life_before - 1


def test_damage_deals_full_party_amount_with_a_full_party():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test Black Mage", is_creature=True,
        oracle_text=(
            "Whenever you cast a spell, ~ deals 1 damage to each "
            "opponent. If you have a full party, it deals 3 damage to "
            "each opponent instead."
        ),
    ))
    _fill_party(state, "p1")
    spell = GameObject(_card("Test Spell", "Sorcery", cost="{1}", cmc=1), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)

    p1.mana_pool.add_many({"C": 1})
    life_before = p2.life
    eng.rules.cast_spell(p1, spell)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert p2.life == life_before - 3


# ---------------------------------------------------------------------------
# Execute: add_counters
# ---------------------------------------------------------------------------


def test_add_counters_base_amount_without_a_full_party():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test White Mage", is_creature=True,
        oracle_text=(
            "Whenever you gain life, put a +1/+1 counter on target "
            "creature you control. If you have a full party, put 3 "
            "+1/+1 counters on that creature instead."
        ),
    ))
    target = _bf(state, _card("Test Target", is_creature=True, power=2, toughness=2))

    eng.rules.put_triggers_on_stack()
    eng.rules.gain_life(p1, 1)
    eng.rules.put_triggers_on_stack()
    state_choice = state.pending_choice
    assert state_choice is not None and state_choice["kind"] == "trigger_target"
    eng.rules.resolve_choice(str(target.instance_id))
    eng.resolve_until_stable()

    assert target.counters.get("+1/+1", 0) == 1


def test_add_counters_full_party_amount_with_a_full_party():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test White Mage", is_creature=True,
        oracle_text=(
            "Whenever you gain life, put a +1/+1 counter on target "
            "creature you control. If you have a full party, put 3 "
            "+1/+1 counters on that creature instead."
        ),
    ))
    target = _bf(state, _card("Test Target", is_creature=True, power=2, toughness=2))
    _fill_party(state, "p1")

    eng.rules.gain_life(p1, 1)
    eng.rules.put_triggers_on_stack()
    state_choice = state.pending_choice
    assert state_choice is not None and state_choice["kind"] == "trigger_target"
    eng.rules.resolve_choice(str(target.instance_id))
    eng.resolve_until_stable()

    assert target.counters.get("+1/+1", 0) == 3
