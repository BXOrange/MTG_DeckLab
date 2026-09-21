"""PAR-119 pilot — the composed cast-trigger head (`spell_phrase` +
`characteristic_phrase`), its `spell_filter` binder predicate and the new
`matches_object_filter` characteristics.

Parse tests pin the grammar (including that it fails closed); execute tests
build a real listener from oracle text, cast/fire real `SPELL_CAST` events and
watch the life total, because parse-only families have shipped crashes before.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.combat import matches_object_filter
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.catalogue.characteristic_phrase import (
    parse_characteristic_phrase,
)
from mtg_analyzer.parser.oracle.catalogue.spell_phrase import parse_spell_phrase
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase, expected",
    [
        ("a multicolored spell", {"spell_filter": {"multicolored": True}}),
        ("a colorless spell", {"spell_filter": {"colorless": True}}),
        ("a legendary spell", {"spell_filter": {"legendary": True}}),
        ("a kicked spell", {"spell_filter": {"kicked": True}}),
        ("a blue or black spell", {"spell_filter": {"color_any": ["U", "B"]}}),
        ("a wizard spell", {"spell_filter": {"subtype": "wizard"}}),
        ("a wizard or warrior spell", {"spell_filter": {"subtype_any": ["wizard", "warrior"]}}),
        ("an artifact creature spell", {"spell_filter": {"card_type_all": ["artifact", "creature"]}}),
        ("a noncreature spell with mana value 3 or greater",
         {"spell_filter": {"without_card_type": "creature", "min_mana_value": 3}}),
        ("a creature spell with mana value 3 or less",
         {"spell_filter": {"card_type": "creature", "max_mana_value": 3}}),
        ("a creature spell with power 4 or greater",
         {"spell_filter": {"card_type": "creature", "min_power": 4}}),
        ("a spell with cascade", {"spell_filter": {"keyword": "cascade"}}),
        ("a spell of the chosen color", {"spell_filter": {"color_from_source": True}}),
        ("a spell from anywhere other than your hand", {"spell_not_cast_from_hand": True}),
        ("a spell from your graveyard", {"spell_cast_from": ["graveyard"]}),
        ("a spell from a graveyard", {"spell_cast_from": ["graveyard"]}),
        ("a spell you don't own", {"spell_not_owned": True}),
        ("a spell during your turn", {"phase_relation": "you"}),
        ("a spell during an opponent's turn", {"phase_relation": "not_you"}),
        ("an instant or sorcery spell that targets a creature",
         {"spell_filter": {"card_type_any": ["instant", "sorcery"]},
          "spell_targets": {"card_type": "creature"}}),
        ("a spell that targets a creature you control",
         {"spell_targets": {"card_type": "creature", "you_control": True}}),
    ],
)
def test_phrase_parses(phrase, expected):
    assert parse_spell_phrase(phrase) == expected


@pytest.mark.parametrize(
    "phrase",
    [
        "a frobnicator spell",                     # not a word in any vocabulary
        "a creature spell that has an adventure",  # unknown tail
        "your first spell",                        # ordinal: not a phrase this grammar owns
        "a spell from mars",
        "a red blue spell",                        # two colours in one object phrase
        "a creature creature spell",               # a repeated type word
        "a spell with mana value 3 or greater with mana value 5 or less",  # repeated key
        "a spell from your graveyard from exile",  # repeated context key
    ],
)
def test_phrase_fails_closed(phrase):
    assert parse_spell_phrase(phrase) is None


def test_characteristic_phrase_is_shared_and_never_guesses():
    assert parse_characteristic_phrase("legendary creature") == {"legendary": True, "card_type": "creature"}
    # `static_handlers.object_filter` reads "multicolored" as a *subtype*; this must not.
    assert parse_characteristic_phrase("multicolored creature") == {"multicolored": True, "card_type": "creature"}
    assert parse_characteristic_phrase("frobnicated creature") is None


def test_when_reads_like_whenever_including_a_modal_header():
    # "When you cast a spell, choose one —" is the same RULE 603.1 event as
    # "whenever"; the composed head accepts both words.
    from mtg_analyzer.parser.oracle import parse_oracle as parse

    card = Card(
        id="M", name="M", type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
        oracle_text="When you cast a spell, choose one —\n• Deal 3 damage to any target.\n• Draw 2 cards.",
    )
    result = parse(card)
    assert result.modeled
    assert result.specs[0].trigger["event"] == "SPELL_CAST"


def _named(name):
    return CardDatabase(DB_PATH).get_card(name)


@pytest.mark.parametrize(
    "name",
    [
        "Hero of Precinct One",       # multicolored
        "Roost of Drakes",            # kicked
        "Kozilek's Sentinel",         # colorless
        "Vega, the Watcher",          # from anywhere other than your hand
        "Ash Zealot",                 # a player casts … from a graveyard
        "Lecturing Scornmage",        # instant/sorcery that targets a creature
        "Kurgadon",                   # creature spell with mana value N or greater
        "Snake Pit",                  # an opponent casts a blue or black spell
    ],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Engine: matches_object_filter's new characteristics
# ---------------------------------------------------------------------------


def _obj(colors=(), mv=0, types="Creature", **card_kwargs):
    card = Card(
        id="X", name="X", type_line=types, converted_mana_cost=mv,
        color_identity=set(colors), **card_kwargs,
    )
    return GameObject(card, owner_id="p1", zone=Zone.STACK)


def test_filter_multicolored_and_colorless():
    assert matches_object_filter(_obj("RG"), {"multicolored": True})
    assert not matches_object_filter(_obj("R"), {"multicolored": True})
    assert matches_object_filter(_obj(""), {"colorless": True})
    assert not matches_object_filter(_obj("R"), {"colorless": True})


def test_filter_mana_value_bounds_and_type_or():
    five = _obj("R", mv=5, types="Creature")
    assert matches_object_filter(five, {"min_mana_value": 5})
    assert not matches_object_filter(five, {"max_mana_value": 4})
    assert matches_object_filter(five, {"card_type_any": ["instant", "creature"]})
    assert not matches_object_filter(five, {"card_type_any": ["instant", "sorcery"]})


def test_filter_kicked_reads_kicker_count():
    spell = _obj("R")
    assert not matches_object_filter(spell, {"kicked": True})
    spell.kicker_count = 1
    assert matches_object_filter(spell, {"kicked": True})


# ---------------------------------------------------------------------------
# Engine: real listeners, real SPELL_CAST events
# ---------------------------------------------------------------------------


def _engine():
    p1 = Player(id="p1", name="Alice", life=20)
    p2 = Player(id="p2", name="Bob", life=20)
    state = GameState(players=[p1, p2])
    return GameEngine(state), state


def _listener(state, oracle, controller="p1", chosen_color=None):
    card = Card(id="Listener", name="Listener", type_line="Enchantment", oracle_text=oracle)
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.chosen_color = chosen_color
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _spell(state, controller="p1", colors="R", mv=2, types="Instant", zone=Zone.HAND, **kw):
    card = Card(
        id="Spell", name="Spell", type_line=types, converted_mana_cost=mv,
        color_identity=set(colors), is_instant=types == "Instant", **kw,
    )
    obj = GameObject(card, owner_id=controller, zone=zone)
    state.player_by_id(controller).hand.append(obj)
    return obj


def _cast_event(engine, state, spell, caster="p1", *, from_zone="hand", targets=(), **extra):
    """Fire the `SPELL_CAST` event `cast_spell` would (same payload keys)."""
    state.fire_event(GameEvent(
        EventType.SPELL_CAST, player_id=caster, card_id=spell.card.id, spell=spell.name,
        instance_id=spell.instance_id, object_types=sorted(spell.type_words),
        mana_value=spell.card.converted_mana_cost, from_hand=from_zone == "hand",
        from_zone=from_zone, target_instance_ids=list(targets), **extra,
    ))
    engine.resolve_until_stable()


def _life_after(oracle, make_spell, *, controller="p1", caster="p1", **event_kwargs):
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, oracle, controller=controller, chosen_color=event_kwargs.pop("chosen_color", None))
    spell = make_spell(state)
    before = state.player_by_id(controller).life
    _cast_event(engine, state, spell, caster=caster, **event_kwargs)
    return state.player_by_id(controller).life - before


GAIN = "you gain 1 life."


def test_multicolored_trigger_fires_only_for_multicolored_spells():
    oracle = f"Whenever you cast a multicolored spell, {GAIN}"
    assert _life_after(oracle, lambda s: _spell(s, colors="RG")) == 1
    assert _life_after(oracle, lambda s: _spell(s, colors="R")) == 0


def test_mana_value_threshold_on_a_typed_spell():
    oracle = f"Whenever you cast a creature spell with mana value 4 or greater, {GAIN}"
    assert _life_after(oracle, lambda s: _spell(s, types="Creature", mv=5)) == 1
    assert _life_after(oracle, lambda s: _spell(s, types="Creature", mv=2)) == 0
    assert _life_after(oracle, lambda s: _spell(s, types="Instant", mv=5)) == 0


def test_cast_from_zone_and_not_from_hand():
    from_gy = f"Whenever you cast a spell from your graveyard, {GAIN}"
    not_hand = f"Whenever you cast a spell from anywhere other than your hand, {GAIN}"
    assert _life_after(from_gy, lambda s: _spell(s), from_zone="graveyard") == 1
    assert _life_after(from_gy, lambda s: _spell(s), from_zone="hand") == 0
    assert _life_after(not_hand, lambda s: _spell(s), from_zone="exile") == 1
    assert _life_after(not_hand, lambda s: _spell(s), from_zone="hand") == 0


def test_spell_targets_a_creature_you_control():
    oracle = f"Whenever you cast a spell that targets a creature you control, {GAIN}"

    def run(target_controller):
        engine, state = _engine()
        state.current_step = "main1"
        _listener(state, oracle)
        bear = GameObject(
            Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True,
                 power=2, toughness=2),
            owner_id=target_controller, zone=Zone.BATTLEFIELD,
        )
        state.add_to_battlefield(bear)
        spell = _spell(state)
        before = state.player_by_id("p1").life
        _cast_event(engine, state, spell, targets=[bear.instance_id])
        return state.player_by_id("p1").life - before

    assert run("p1") == 1
    assert run("p2") == 0


def test_of_the_chosen_color_reads_the_source_choice():
    oracle = f"Whenever you cast a spell of the chosen color, {GAIN}"
    assert _life_after(oracle, lambda s: _spell(s, colors="R"), chosen_color="R") == 1
    assert _life_after(oracle, lambda s: _spell(s, colors="U"), chosen_color="R") == 0


def test_opponents_spell_scope_still_applies():
    oracle = f"Whenever an opponent casts a blue or black spell, {GAIN}"
    assert _life_after(oracle, lambda s: _spell(s, controller="p2", colors="U"), caster="p2") == 1
    assert _life_after(oracle, lambda s: _spell(s, controller="p2", colors="R"), caster="p2") == 0
    assert _life_after(oracle, lambda s: _spell(s, controller="p1", colors="U"), caster="p1") == 0


def test_during_turn_qualifier_is_relative_to_the_ability_controller():
    # RULE 102.2: "an opponent's turn" is a turn of an opponent *of the ability's
    # controller* (p1 here, who is the active player in a fresh state).
    mine = f"Whenever an opponent casts a blue spell during your turn, {GAIN}"
    theirs = f"Whenever an opponent casts a blue spell during an opponent's turn, {GAIN}"
    blue_from_p2 = lambda s: _spell(s, controller="p2", colors="U")  # noqa: E731
    assert _life_after(mine, blue_from_p2, caster="p2") == 1
    assert _life_after(theirs, blue_from_p2, caster="p2") == 0


def test_real_cast_stamps_the_zone_it_came_from():
    engine, state = _engine()
    engine.begin_turn()
    state.current_step = "main1"
    spell = _spell(state, colors="R", mv=1)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("R", 1)
    spell.card.mana_cost_string = "{R}"
    engine.cast_spell(p1, spell, targets=None)
    cast = [e for e in state.event_log if e.type == EventType.SPELL_CAST][-1]
    assert cast.get("from_zone") == "hand"


def test_subtype_spell_trigger_reads_the_cast_objects_subtypes():
    oracle = f"Whenever you cast a Wizard spell, {GAIN}"
    wizard = lambda s: _spell(s, types="Creature — Wizard")  # noqa: E731
    bear = lambda s: _spell(s, types="Creature — Bear")  # noqa: E731
    assert _life_after(oracle, wizard) == 1
    assert _life_after(oracle, bear) == 0
