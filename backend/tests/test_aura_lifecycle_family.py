"""Aura lifecycle triggers — the "when this Aura enters, tap enchanted
permanent" ETB family and the Rancor-shaped "when this Aura dies, return it
to its owner's hand" family (plus its activated sibling, Flickering Ward's
"{W}: Return this Aura to its owner's hand.").

Three pieces, none of which needed a new *engine* primitive so much as a
missing definition and two missing recognitions:

* **RULE 700.4 in `normalize`** — "the term *dies* means 'is put into a
  graveyard from the battlefield'". An exact definitional synonym, so the
  pre-2011 long phrasing is folded to the one-word verb and every existing
  "dies" grammar (self/group/attached subject, tribal subjects, the
  quoted-grant recursion) covers it for free. The narrower "is put into
  **your** graveyard from the battlefield" (Angelic Renewal) is deliberately
  *not* folded — it names a specific player's graveyard, which "dies"
  doesn't express.
* **RULE 700.4 in the engine** — `RulesEngine._move_to_graveyard` only fired
  `EventType.DIES` for a *creature*, so an Aura/enchantment/land dying was
  invisible to any dies-trigger at all. "Dies" isn't creature-scoped; every
  consumer that does mean creatures narrows on the event's own
  ``object_types`` already.
* **`ReturnToHandEffect`'s self form** (``target_kind=None``) — no RULE 115
  target and no player choice, mirroring `TapEffect`'s untargeted mode. It
  resolves against the source wherever it currently is, which for a
  dies-trigger is the *graveyard* (RULE 400.7 — the source moved before the
  ability resolved).

Also covers the widened `_ATTACHED_SUBJECT` ("enchanted permanent"/
"enchanted land", Flood the Engine/Animal Boneyard-shaped).

Reference: mtg_analyzer/parser/oracle/{normalize.py,catalogue/handlers.py},
mtg_analyzer/game/{rules_engine,effects}.py.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _aura(name, oracle_text, type_line="Enchantment — Aura"):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text)


def _creature(name):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


_RANCOR_TEXT = (
    "Enchant creature\n"
    "Enchanted creature gets +2/+0 and has trample.\n"
    "When Rancor is put into a graveyard from the battlefield, return Rancor "
    "to its owner's hand."
)


# -- RULE 700.4 normalization -------------------------------------------------


def test_dies_long_form_folds_to_dies():
    assert "dies" in normalize(
        "When Launch is put into a graveyard from the battlefield, draw a card.", "Launch"
    )


def test_owners_graveyard_long_form_also_folds():
    assert "~ dies," in normalize(
        "When Foo is put into its owner's graveyard from the battlefield, draw a card.", "Foo"
    )


def test_your_graveyard_long_form_is_not_folded():
    # Angelic Renewal-shaped: "your graveyard" is a narrower condition than
    # "dies" and stays unclaimed rather than being silently widened.
    text = normalize(
        "Whenever a creature is put into your graveyard from the battlefield, draw a card.", "Foo"
    )
    assert "dies" not in text
    assert "put into your graveyard" in text


# -- parse-side coverage ------------------------------------------------------


def test_rancor_is_modeled():
    result = parse_oracle(_aura("Rancor", _RANCOR_TEXT))
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_return_self_to_hand_effect_is_recognized():
    (spec,) = parse_effect_body("return ~ to its owner's hand")
    assert spec.type == "return_to_hand"
    assert spec.params == {"target_kind": None}


def test_return_it_to_hand_pronoun_is_recognized():
    (spec,) = parse_effect_body("return it to its owner's hand")
    assert spec.type == "return_to_hand"
    assert spec.params == {"target_kind": None}


def test_flickering_ward_style_activated_self_bounce_is_recognized():
    card = _aura(
        "Bounce Ward",
        "Enchant creature\nEnchanted creature gets +1/+1.\n"
        "{W}: Return this Aura to its owner's hand.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_targeted_bounce_still_parses_as_a_targeted_effect():
    # Regression: the new self form must not steal the ordinary RULE 115
    # bounce ("return target creature to its owner's hand").
    (spec,) = parse_effect_body("return target creature to its owner's hand")
    assert spec.params["target_kind"] == "creature"


def test_aura_etb_tap_enchanted_permanent_is_modeled():
    # Flood the Engine-shaped: the widened `_ATTACHED_SUBJECT` vocabulary.
    (spec,) = parse_effect_body("tap enchanted permanent")
    assert spec.type == "tap"
    assert spec.params == {"target_kind": "attached_permanent", "untap": False}


def test_group_dies_trigger_with_an_article_is_modeled():
    # "**an** enchantment you control dies" — the article alternation had
    # only "a"/"another", so every vowel-initial type word failed closed.
    card = Card(
        id="Ashiok's Reaper", name="Ashiok's Reaper", type_line="Creature — Nightmare",
        is_creature=True, power=2, toughness=2,
        oracle_text=(
            "Whenever an enchantment you control is put into a graveyard from "
            "the battlefield, draw a card."
        ),
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


# -- execute-side (bind → engine) --------------------------------------------


def test_dies_event_now_fires_for_a_noncreature_permanent():
    eng = _engine()
    state = eng.state
    enchantment = _bf(state, _aura("Plain Enchantment", "", type_line="Enchantment"))

    seen: list = []
    state.subscribe(lambda e: seen.append(e))
    eng.rules.destroy(enchantment)

    assert any(str(e.type) == "DIES" for e in seen), [str(e.type) for e in seen]


def test_rancor_returns_itself_from_the_graveyard_to_hand_when_it_dies():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    host = _bf(state, _creature("Bear"))
    rancor = _bf(state, _aura("Rancor", _RANCOR_TEXT))
    rancor.attached_to = host.instance_id

    eng.rules.destroy(rancor)
    # RULE 400.7: by the time the trigger resolves the Aura is already a new
    # object in the graveyard — the self-return effect finds it there.
    assert rancor in p1.graveyard
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert rancor not in p1.graveyard
    assert rancor in p1.hand


def test_activated_self_bounce_returns_the_aura_from_the_battlefield():
    from mtg_analyzer.game.effects import GameContext, ReturnToHandEffect

    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    aura = _bf(state, _aura("Bounce Ward", ""))

    effect = ReturnToHandEffect(source=aura, target_kind=None)
    effect.apply(GameContext(state, eng.rules))

    assert aura not in state.battlefield
    assert aura in p1.hand


def test_aura_etb_taps_the_enchanted_permanent():
    eng = _engine()
    state = eng.state
    host = _bf(state, _creature("Bear"))
    aura = GameObject(
        _aura(
            "Claustrophobia Lite",
            "Enchant creature\nWhen this Aura enters, tap enchanted creature.",
        ),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(aura)
    aura.attached_to = host.instance_id
    state.add_to_battlefield(aura)

    from mtg_analyzer.models.events import EventType, GameEvent

    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, object=aura.name,
            controller_id="p1", instance_id=aura.instance_id,
            object_types=sorted(aura.type_words),
        )
    )
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert host.tapped
