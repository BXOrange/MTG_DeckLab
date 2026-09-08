"""Tests for RULE 603.1's "Whenever you cast a/an `<subtype>` spell, …"
tribal "spells matter" payoff (Lys Alana Huntmaster-shaped — the single
biggest ranked template blocker in the whole cache on its wider "cast a
`<word>` spell" shape) and RULE 118.3's "You may pay `<cost>`. If you do,
`<effect>`." (`pay_cost_then`'s first oracle-text recognizer).

Both share one subtlety: `_peel_optional`'s guard (`_PAY_ENERGY_THEN_PEEL_
GUARD_RE`, widened here from energy-only to any mana cost) must leave "you
may pay `<cost>`. If you do, …" un-peeled, since `AbilitySpec.optional`
means something different (decline the *whole trigger*) from the cost
being the optional part.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body, segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance


def _bear(name="Bear"):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)


# ---------------------------------------------------------------------------
# Parse: subtype-scoped cast trigger
# ---------------------------------------------------------------------------


def test_cast_elf_spell_trigger_is_recognized_as_a_subtype_condition():
    seg = segment_line(
        "whenever you cast an elf spell, you may create a 1/1 green elf warrior creature token.",
        allow_spell_effect=False, provenance=ParserProvenance(),
    )
    assert seg.claimed
    assert seg.spec.trigger == {
        "event": "SPELL_CAST",
        "condition": {"subject": "you"},
        "spell_subtype_any": ["elf"],
    }
    assert seg.spec.optional is True  # a plain "you may <effect>" IS peeled


def test_cast_creature_spell_trigger_still_uses_the_main_type_path():
    # A genuine main-type word must still resolve via `spell_card_types`,
    # not be swallowed by the new subtype fallback.
    seg = segment_line(
        "whenever you cast a creature spell, draw a card.",
        allow_spell_effect=False, provenance=ParserProvenance(),
    )
    assert seg.claimed
    assert seg.spec.trigger["spell_card_types"] == ["creature"]
    assert "spell_subtype_any" not in seg.spec.trigger


def test_cast_unrecognized_word_spell_trigger_stays_unclaimed():
    # Not a real main type, not in the curated subtype whitelist — fails
    # closed rather than guessing.
    seg = segment_line(
        "whenever you cast a sorcery spell, draw a card.",  # "sorcery" IS a main type actually
        allow_spell_effect=False, provenance=ParserProvenance(),
    )
    assert seg.claimed  # sanity: this one IS a real main type
    seg2 = segment_line(
        "whenever you cast a historic spell, draw a card.",
        allow_spell_effect=False, provenance=ParserProvenance(),
    )
    assert not seg2.claimed


def test_lys_alana_huntmaster_is_fully_modeled():
    card = Card(
        id="Lys Alana Huntmaster", name="Lys Alana Huntmaster",
        type_line="Creature — Elf Archer", is_creature=True, power=2, toughness=2,
        oracle_text="Whenever you cast an Elf spell, you may create a 1/1 "
                     "green Elf Warrior creature token.",
    )
    assert parse_oracle(card).coverage == MODELED


# ---------------------------------------------------------------------------
# Parse: pay_cost_then ("you may pay <cost>. If you do, draw a card.")
# ---------------------------------------------------------------------------


def test_pay_cost_then_draw_is_recognized_as_one_clause():
    (spec,) = parse_effect_body("you may pay {g}. if you do, draw a card")
    assert spec.type == "pay_cost_then"
    assert spec.params == {
        "cost": "{g}",
        "effects": [{"type": "draw", "params": {"count": 1}}],
    }


def test_leaf_crowned_visionary_is_fully_modeled_with_no_double_optional():
    seg = segment_line(
        "whenever you cast an elf spell, you may pay {g}. if you do, draw a card.",
        allow_spell_effect=False, provenance=ParserProvenance(),
    )
    assert seg.claimed
    assert seg.spec.optional is False  # the trigger itself is mandatory
    assert seg.spec.trigger == {
        "event": "SPELL_CAST",
        "condition": {"subject": "you"},
        "spell_subtype_any": ["elf"],
    }
    (effect,) = seg.spec.effects
    assert effect.type == "pay_cost_then"


# ---------------------------------------------------------------------------
# Engine: end-to-end
# ---------------------------------------------------------------------------


def test_lys_alana_huntmaster_end_to_end_offers_a_token_when_an_elf_spell_is_cast():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1})

    huntmaster_card = Card(
        id="Lys Alana Huntmaster", name="Lys Alana Huntmaster",
        type_line="Creature — Elf Archer", is_creature=True, power=2, toughness=2,
        oracle_text="Whenever you cast an Elf spell, you may create a 1/1 "
                     "green Elf Warrior creature token.",
    )
    huntmaster = GameObject(huntmaster_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(huntmaster)
    eng.state.add_to_battlefield(huntmaster)

    elf_spell = GameObject(
        Card(id="Elvish Mystic", name="Elvish Mystic", type_line="Creature — Elf Druid",
             is_creature=True, power=1, toughness=1, mana_cost_string="{G}", converted_mana_cost=1),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(elf_spell)
    p1.hand.append(elf_spell)

    eng.cast_spell(p1, elf_spell)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1  # Lys Alana Huntmaster's own trigger fired
