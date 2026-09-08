"""PAR-29 — RULE 701.36 Populate: a new engine primitive + oracle handler.

`RulesEngine.populate` puts a token onto the battlefield that's a copy of a
creature token the resolving controller controls (701.36a); it does nothing
if they control no creature tokens (701.36b). More than one creature token →
an interactive `populate` `pending_choice` for which one to copy.

Parser: the bare word "populate" (`effects.PopulateEffect`, registered as
``populate``, on the existing `copy_permanent` token-copy path), and
"populate X times" (Full Flowering) — `PopulateEffect.count` rides the
plain ``"x"`` sentinel `RulesEngine._substitute_x` already resolves on any
effect's own ``count`` attribute, repeating the whole procedure that many
times (sequenced via `GameState.deferred_effects` when 2+ repeats each open
a real "which token?" choice).

Reference: game/rules/copies_mixin.py (`populate`), game/effects/core.py
(`PopulateEffect`), parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
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


def test_populate_x_times_parses():
    # Full Flowering.
    assert match_clause("populate x times") == [EffectSpec("populate", {"count": "x"})]


def test_populate_n_times_stays_unclaimed():
    # No real card prints a literal repeat count — only bare "populate" or
    # the dynamic "X times" (Full Flowering) exist, so a plain number here
    # fails closed rather than guessing.
    assert match_clause("populate twice") is None
    assert match_clause("populate 2 times") is None


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


def test_populate_effect_count_x_repeats_the_whole_procedure():
    # Full Flowering with X=3, starting from one creature token: repeat 1 is
    # forced (only one token to copy), but each copy it makes is a second
    # matching token, so repeats 2 and 3 each open a real "which one?"
    # choice (RULE 701.36a doesn't care that the two options are
    # identical) — driven here the same "missing answer defaults to the
    # first offered token" way `test_populate_choice_defaults_to_first_
    # token_on_missing_answer` already establishes for a single populate.
    from mtg_analyzer.game.effects.core import GameContext, PopulateEffect

    eng, state, p1 = _engine()
    eng.rules.create_token("p1", _soldier_token_card(), 1)

    ctx = GameContext(state, eng.rules)
    PopulateEffect(count=3).apply(ctx)

    for _ in range(2):  # repeats 2 and 3's own choices
        assert state.pending_choice is not None
        assert state.pending_choice["kind"] == "populate"
        eng.resolve_pending_choice(None)

    assert state.pending_choice is None
    assert not state.deferred_effects
    assert len([o for o in state.battlefield if o.name == "Soldier"]) == 4  # 1 original + 3 copies


def test_populate_effect_count_x_sequences_real_choices_via_deferred_effects():
    # X=2 with two distinct creature tokens on the board: each of the 2
    # repeats has a real "which token?" decision. Looping both synchronously
    # would silently overwrite the first repeat's still-unanswered prompt
    # with the second's own populate.
    from mtg_analyzer.game.effects.core import GameContext, PopulateEffect

    eng, state, p1 = _engine()
    eng.rules.create_token("p1", _soldier_token_card(), 1)
    eng.rules.create_token(
        "p1",
        Card(id="tok-elf", name="Elf Warrior", type_line="Token Creature — Elf Warrior",
             is_creature=True, power=1, toughness=1),
        1,
    )

    ctx = GameContext(state, eng.rules)
    PopulateEffect(count=2).apply(ctx)

    # First repeat opened a real choice; the second is parked, not run yet.
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "populate"
    assert len(state.deferred_effects) == 1
    before_soldiers = len([o for o in state.battlefield if o.name == "Soldier"])
    before_elves = len([o for o in state.battlefield if o.name == "Elf Warrior"])
    assert before_soldiers + before_elves == 2  # nothing populated yet

    # `GameEngine.resolve_pending_choice` ends with `resolve_until_stable`,
    # which drains `deferred_effects` on its own — answering repeat 1's
    # choice both finishes repeat 1 *and* runs repeat 2 far enough to open
    # its own fresh choice, all in this one call.
    elf = next(o for o in state.battlefield if o.name == "Elf Warrior")
    eng.resolve_pending_choice(str(elf.instance_id))
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "populate"
    assert not state.deferred_effects  # nothing left queued behind repeat 2

    another = next(o for o in state.battlefield if o.name in ("Soldier", "Elf Warrior"))
    eng.resolve_pending_choice(str(another.instance_id))

    assert state.pending_choice is None
    assert not state.deferred_effects
    total_after = len([o for o in state.battlefield if o.name in ("Soldier", "Elf Warrior")])
    assert total_after == 4  # 2 originals + 2 populated copies


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
