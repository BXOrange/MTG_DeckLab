"""Batch 9 (docs/implementation-state/BACKLOG.md): "Saga /
conditional transform" — a new `exile_return_transformed` effect for the
"exile ~, then return it to the battlefield transformed under its owner's
control" wording (RULE 400.7 + RULE 712.8 combined), covering both:

* a transforming Saga's own final chapter (Fable of the Mirror-Breaker-
  shaped — `catalogue/saga.py`'s existing `SAGA_CHAPTER` trigger grammar
  needed no changes, just a new effect-body handler for chapter III's text);
* an activated ability that phrases its own flip this way instead of a bare
  "transform ~" (Ayara/Clive/Jin-Gitaxias/Huatli-shaped — reuses the
  already-shipped `sorcery_speed_marker` machinery from Batch 1 unchanged).

Unlike a plain `TransformEffect` (an in-place face swap on the same
`GameObject`), this is a genuine RULE 400.7 zone change: `RulesEngine.
exile_return_transformed` exiles the permanent, resets it to a new object
(RULE 400.7 — counters/attachments/until-end-of-turn effects fall off), then
flips it onto its back face and re-enters it on the battlefield (fresh ETB,
summoning sickness). The old Saga instance is simply gone from the
battlefield by the time RULE 704.5x's sacrifice SBA would otherwise apply,
so no changes were needed there either.

Investigated and deliberately left unclaimed (fail-closed): the legacy
pre-2021 non-daybound werewolf template ("at the beginning of each upkeep,
if no spells were cast last turn, transform ~") — already flagged in
docs/implementation-state/BACKLOG.md as superseded by RULE 731
day/night and intentionally not built, confirmed still true by sampling the
32 real cards using that exact wording (none use the newer template); and
Delver of Secrets-style "look at the top card... if it's an instant/sorcery,
transform" (ToDo_EdgeCases #16), a genuinely different reveal+conditional
shape.

Reference: mtg_analyzer/parser/oracle/catalogue/{handlers,saga}.py,
mtg_analyzer/game/{effects,rules_engine,effect_binder}.py.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.effects import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, UNMODELED, parse_oracle


def _saga(name="Fable Test"):
    return Card(
        id=name, name=name, type_line="Enchantment — Saga",
        oracle_text=(
            "(As this Saga enters and after your draw step, add a lore counter.)\n"
            "I — Create a 2/2 red Goblin Shaman creature token.\n"
            "II — Draw a card.\n"
            "III — Exile this Saga, then return it to the battlefield transformed under your control."
        ),
        layout="transform",
        back_name=f"{name} Back", back_type_line="Enchantment Creature — Goblin Shaman",
        back_power=2, back_toughness=2,
        back_oracle_text="{1}, {T}: Create a token that's a copy of another target creature you control.",
    )


def _flip_creature(name="Flip Test", extra_ability=""):
    body = (
        f"{extra_ability}\n" if extra_ability else ""
    ) + "{2}{U}: Exile ~, then return it to the battlefield transformed under its owner's control. Activate only as a sorcery."
    return Card(
        id=name, name=name, type_line="Legendary Creature — Human Wizard",
        is_creature=True, power=2, toughness=2,
        oracle_text=body,
        layout="transform",
        back_name=f"{name} Back", back_type_line="Legendary Creature — Human Wizard",
        back_power=5, back_toughness=5,
    )


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0,
    )


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _saga_in_play(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, controller_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# Parse-side coverage
# ---------------------------------------------------------------------------


def test_transforming_saga_final_chapter_is_modeled():
    result = parse_oracle(_saga())
    assert result.coverage == MODELED
    chapter3 = next(
        s for s in result.specs
        if s.ability_kind == "triggered" and s.trigger.get("chapter") == [3]
    )
    assert [e.type for e in chapter3.effects] == ["exile_return_transformed"]


def test_activated_exile_return_transformed_is_modeled():
    card = Card(
        id="Ayara Test", name="Ayara Test", type_line="Legendary Creature — Elf Shaman",
        is_creature=True, power=1, toughness=1,
        oracle_text="{2}{U}: Exile ~, then return it to the battlefield transformed under its owner's control. Activate only as a sorcery.",
        layout="transform", back_name="Ayara Test Back", back_type_line="Legendary Creature — Elf Shaman",
        back_power=4, back_toughness=4,
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    activated = next(s for s in result.specs if s.ability_kind == "activated")
    assert [e.type for e in activated.effects] == ["exile_return_transformed", "sorcery_speed_marker"]


def test_gendered_pronoun_variants_are_modeled():
    for pronoun, possessive in (("him", "his"), ("her", "her"), ("it", "its")):
        card = Card(
            id=f"Pronoun {pronoun}", name=f"Pronoun {pronoun}", type_line="Legendary Planeswalker",
            oracle_text=(
                f"{{3}}{{u}}: exile ~, then return {pronoun} to the battlefield transformed "
                f"under {possessive} owner's control. activate only as a sorcery."
            ),
            layout="transform", back_name=f"Pronoun {pronoun} Back", back_type_line="Legendary Planeswalker",
        )
        result = parse_oracle(card)
        activated = next(s for s in result.specs if s.ability_kind == "activated")
        assert [e.type for e in activated.effects] == ["exile_return_transformed", "sorcery_speed_marker"], pronoun


def test_jin_gitaxias_shaped_extra_condition_is_now_modeled():
    """PAR-10 closed this: "activate only as a sorcery and only if you have
    seven or more cards in hand" is a recognized compound activation
    condition (`catalogue.handlers.ACTIVATION_CONDITION_MARKER`), so the
    trailing condition on the sorcery-speed marker no longer drops the
    whole clause. Was a fail-closed regression guard before PAR-10; now
    guards the opposite direction — this must stay modeled."""
    card = Card(
        id="Jin Test", name="Jin Test", type_line="Legendary Creature — Phyrexian",
        is_creature=True, power=1, toughness=1,
        oracle_text=(
            "{3}{u}: exile ~, then return it to the battlefield transformed under its "
            "owner's control. activate only as a sorcery and only if you have 7 or more cards in hand."
        ),
        layout="transform", back_name="Jin Test Back", back_type_line="Legendary Creature — Phyrexian",
        back_power=7, back_toughness=7,
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_legacy_werewolf_no_spells_cast_stays_unclaimed():
    """Deliberately deferred (ToDo_EdgeCases): superseded by RULE 731
    day/night, only the new mechanic is built."""
    card = Card(
        id="Werewolf Test", name="Werewolf Test", type_line="Creature — Werewolf",
        is_creature=True, power=2, toughness=2,
        oracle_text="At the beginning of each upkeep, if no spells were cast last turn, transform ~.",
        layout="transform", back_name="Werewolf Test Back", back_type_line="Creature — Werewolf",
        back_power=3, back_toughness=3,
    )
    result = parse_oracle(card)
    assert result.coverage == UNMODELED


# ---------------------------------------------------------------------------
# Execute: Saga final chapter
# ---------------------------------------------------------------------------


def test_saga_final_chapter_exiles_and_returns_transformed_end_to_end():
    eng = make_engine()
    eng.begin_turn()
    saga = _saga_in_play(eng, _saga())  # chapter I on ETB
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    assert saga.lore == 1

    eng.rules.advance_sagas(eng.state.active_player)  # chapter II
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    assert saga.lore == 2

    eng.rules.advance_sagas(eng.state.active_player)  # chapter III
    assert saga.lore == 3
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    # RULE 400.7: the same instance re-enters already transformed.
    assert saga in eng.state.battlefield
    assert saga.transformed is True
    assert saga.name == "Fable Test Back"
    assert (saga.power, saga.toughness) == (2, 2)
    assert saga.summoning_sick is True
    assert saga.lore == 0  # RULE 400.7: counters don't survive the zone change

    # RULE 704.5x's sacrifice SBA must not also fire (the object is no
    # longer a Saga at all — is_saga reads the new, transformed face).
    eng.rules.check_state_based_actions()
    assert saga in eng.state.battlefield


# ---------------------------------------------------------------------------
# Execute: activated ability
# ---------------------------------------------------------------------------


def test_activated_exile_return_transformed_end_to_end_via_registry():
    eng = make_engine()
    obj = _put(eng, _flip_creature())
    effect = EffectRegistry.create("exile_return_transformed", {})
    effect.source = obj
    effect.apply(eng.rules.context, targets=None)

    assert obj in eng.state.battlefield
    assert obj.transformed is True
    assert obj.name == "Flip Test Back"
    assert (obj.power, obj.toughness) == (5, 5)
    assert obj.summoning_sick is True


def test_exile_return_transformed_is_noop_without_a_back_face():
    eng = make_engine()
    card = Card(
        id="Vanilla", name="Vanilla", type_line="Creature — Bear",
        is_creature=True, power=2, toughness=2,
    )
    obj = _put(eng, card)
    assert eng.rules.exile_return_transformed(obj) is False
    assert obj in eng.state.battlefield
    assert obj.transformed is False


def test_exile_return_transformed_drops_counters_and_attachments():
    eng = make_engine()
    obj = _put(eng, _flip_creature())
    obj.counters["+1/+1"] = 3
    assert eng.rules.exile_return_transformed(obj) is True
    assert obj.counters == {}
    assert obj.transformed is True
