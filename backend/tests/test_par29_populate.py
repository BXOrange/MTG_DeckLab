"""PAR-29 — RULE 701.36 Populate: a new engine primitive + oracle handler.

`RulesEngine.populate` puts a token onto the battlefield that's a copy of a
creature token the resolving controller controls (701.36a); it does nothing
if they control no creature tokens (701.36b). More than one creature token →
an interactive `populate` `pending_choice` for which one to copy.

Parser: the bare word "populate" (`effects.PopulateEffect`, registered as
``populate``, on the existing `copy_permanent` token-copy path). "Populate X
times" (Full Flowering) stays unclaimed — a dynamic repeat count.

Reference: game/rules/copies_mixin.py (`populate`), game/effects.py
(`PopulateEffect`), parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse ---------------------------------------------------------------


def test_populate_parses():
    assert match_clause("populate") == [EffectSpec("populate", {})]


def test_populate_x_times_stays_unclaimed():
    # Full Flowering — a dynamic repeat count PopulateEffect can't take yet.
    assert match_clause("populate x times") is None
    assert match_clause("populate twice") is None


def test_real_populate_card_is_modeled_end_to_end():
    card = Card(
        id="Wake", name="Wake the Reflections", type_line="Sorcery", is_sorcery=True,
        oracle_text="Populate. (Create a token that's a copy of a creature token you control.)",
    )
    result = parse_oracle(card)
    assert result.modeled
    assert [e.type for e in result.effect_specs[0].effects] == ["populate"]


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state, eng.state.player_by_id("p1")


def _soldier_token_card():
    return Card(id="tok-sol", name="Soldier", type_line="Token Creature — Soldier",
                is_creature=True, power=1, toughness=1)


def _treasure_token_card():
    return Card(id="tok-tr", name="Treasure", type_line="Token Artifact — Treasure")


def test_populate_with_no_creature_tokens_does_nothing():
    eng, state, p1 = _engine()
    before = len(state.battlefield)

    eng.rules.populate(p1)

    assert state.pending_choice is None
    assert len(state.battlefield) == before


def test_populate_with_a_noncreature_token_only_does_nothing():
    eng, state, p1 = _engine()
    eng.rules.create_token("p1", _treasure_token_card(), 1)
    before = len(state.battlefield)

    eng.rules.populate(p1)

    assert state.pending_choice is None
    assert len(state.battlefield) == before  # Treasure isn't a creature token


def test_populate_with_exactly_one_creature_token_copies_it_no_choice():
    eng, state, p1 = _engine()
    eng.rules.create_token("p1", _soldier_token_card(), 1)

    made = eng.rules.populate(p1)

    assert state.pending_choice is None
    assert len(made) == 1
    soldiers = [o for o in state.battlefield if o.name == "Soldier"]
    assert len(soldiers) == 2
    assert all(o.is_token for o in soldiers)


def test_populate_with_two_creature_tokens_opens_a_choice():
    eng, state, p1 = _engine()
    eng.rules.create_token("p1", _soldier_token_card(), 1)
    eng.rules.create_token(
        "p1",
        Card(id="tok-elf", name="Elf Warrior", type_line="Token Creature — Elf Warrior",
             is_creature=True, power=1, toughness=1),
        1,
    )

    eng.rules.populate(p1)

    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "populate"
    labels = {opt["label"] for opt in choice["options"]}
    assert labels == {"Soldier", "Elf Warrior"}

    elf = next(o for o in state.battlefield if o.name == "Elf Warrior")
    eng.resolve_pending_choice(str(elf.instance_id))

    assert state.pending_choice is None
    assert len([o for o in state.battlefield if o.name == "Elf Warrior"]) == 2
    assert len([o for o in state.battlefield if o.name == "Soldier"]) == 1


def test_populate_choice_defaults_to_first_token_on_missing_answer():
    eng, state, p1 = _engine()
    eng.rules.create_token("p1", _soldier_token_card(), 2)  # two identical tokens

    eng.rules.populate(p1)
    assert state.pending_choice["kind"] == "populate"

    eng.resolve_pending_choice(None)  # mandatory — defaults, doesn't skip

    assert state.pending_choice is None
    assert len([o for o in state.battlefield if o.name == "Soldier"]) == 3


def test_populate_only_copies_own_tokens():
    eng, state, p1 = _engine()
    eng.rules.create_token("p2", _soldier_token_card(), 1)  # opponent's token
    before = len(state.battlefield)

    eng.rules.populate(p1)

    assert state.pending_choice is None
    assert len(state.battlefield) == before


def test_real_card_populates_on_resolution_via_binder():
    eng, state, p1 = _engine()
    eng.rules.create_token("p1", _soldier_token_card(), 1)

    card = Card(id="LFW", name="Life Finds a Way", type_line="Enchantment",
                oracle_text="When this enchantment enters, populate.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id="p1", object_types=sorted(obj.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert len([o for o in state.battlefield if o.name == "Soldier"]) == 2
