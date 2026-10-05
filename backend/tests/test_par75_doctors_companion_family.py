"""PAR-75: "Doctor's companion" referenced by another card (RULE 702.124m,
Doctor Who) — the keyword itself (a plain FLAG, deck-construction-only)
shipped in PAR-69; this closes the two real cards that reference it as a
*card-quality filter* rather than printing it on themselves:

* An Unearthly Child's Saga chapter — "reveal cards from the top of your
  library until you reveal a Doctor card, a card with doctor's companion,
  or a Vehicle card" — a three-way OR predicate over `dig_until`'s
  `criteria`. `card_query`'s existing `"or"` key composes the three arms;
  the only new piece is a `has_keyword` criterion (`Card.keywords`
  membership, case-insensitive) generalized past this one keyword.
* Rose Noble's cast trigger — "whenever you cast a Doctor spell or creature
  spell with doctor's companion, draw a card." — an OR of two *structurally
  different* cast-trigger filters (a subtype match vs. a type + keyword
  match) no single AND-combined `trigger` dict can express. Modeled as two
  independent triggered abilities sharing the same effects
  (`Segment.extra_specs`), safe because a real Doctor card and a real
  companion card are never the same physical card (RULE 702.124m's two
  Time Lord partner halves) — the two conditions can never both fire off
  one cast.

Reference: docs/implementation-state/Done_Backend.md's "Oracle-Text Parser
Front-End" PAR-75 entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.cards.card_query import matches as card_matches
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body, segment_line
from mtg_analyzer.parser.oracle.spec import EffectSpec, ParserProvenance


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


def _hand(player, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.add_to_zone(obj, Zone.HAND)
    return obj


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


# ---------------------------------------------------------------------------
# Real cards: full MODELED verdict
# ---------------------------------------------------------------------------


def test_an_unearthly_child_modeled():
    card = _card(
        "An Unearthly Child", type_line="Enchantment — Saga",
        oracle_text=(
            "(As this Saga enters and after your draw step, add a lore "
            "counter. Sacrifice after III.)\n"
            "I, II, III — Reveal cards from the top of your library until "
            "you reveal a Doctor card, a card with doctor's companion, or "
            "a Vehicle card. Put that card into your hand and the rest on "
            "the bottom of your library in a random order."
        ),
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_rose_noble_modeled():
    card = _card(
        "Rose Noble", type_line="Legendary Creature — Human",
        oracle_text=(
            "Ward {2}\n"
            "Whenever you cast a Doctor spell or creature spell with "
            "doctor's companion, draw a card.\n"
            "Doctor's companion (You can have two commanders if the other "
            "is the Doctor.)"
        ),
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


# ---------------------------------------------------------------------------
# card_query: the new has_keyword criterion, alone and composed with "or"
# ---------------------------------------------------------------------------


def test_has_keyword_criterion_matches_case_insensitively():
    companion = _card("Test Companion", keywords=["Doctor's Companion"])
    plain = _card("Test Plain")
    assert card_matches(companion, {"has_keyword": "doctor's companion"})
    assert not card_matches(plain, {"has_keyword": "doctor's companion"})


def test_dig_until_doctor_companion_vehicle_parses():
    assert parse_effect_body(
        "reveal cards from the top of your library until you reveal a "
        "doctor card, a card with doctor's companion, or a vehicle card. "
        "put that card into your hand and the rest on the bottom of your "
        "library in a random order"
    ) == [EffectSpec("dig_until", {
        "criteria": {"or": [
            {"type": "Doctor"}, {"has_keyword": "Doctor's Companion"}, {"type": "Vehicle"},
        ]},
        "hit_destination": "hand", "rest_destination": "library_bottom_random",
    })]


def test_an_unearthly_child_digs_to_the_companion_card_not_the_filler():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test Unearthly Child", type_line="Enchantment",
        oracle_text=(
            "Reveal cards from the top of your library until you reveal a "
            "doctor card, a card with doctor's companion, or a vehicle "
            "card. Put that card into your hand and the rest on the "
            "bottom of your library in a random order."
        ),
    ))
    filler = _card("Filler One")
    companion = _card("Test Companion Card", keywords=["Doctor's Companion"])
    for c in (filler, companion):
        p1.library.append(GameObject(c, owner_id="p1", zone=Zone.LIBRARY))

    eng.rules.dig_until(
        p1, {"or": [{"type": "Doctor"}, {"has_keyword": "Doctor's Companion"}, {"type": "Vehicle"}]},
        hit_destination="hand", rest_destination="library_bottom_random",
    )

    assert any(o.name == "Test Companion Card" for o in p1.hand)
    assert not any(o.name == "Test Companion Card" for o in p1.library)
    assert any(o.name == "Filler One" for o in p1.library)


# ---------------------------------------------------------------------------
# Rose Noble's two independent triggered abilities
# ---------------------------------------------------------------------------


def test_rose_noble_segments_into_two_independent_abilities():
    prov = ParserProvenance(source="test", version=1)
    seg = segment_line(
        "whenever you cast a doctor spell or creature spell with doctor's "
        "companion, draw a card.",
        allow_spell_effect=False, provenance=prov,
    )
    assert seg.claimed
    conditions = [seg.spec.trigger] + [s.trigger for s in seg.extra_specs]
    assert {"event": "SPELL_CAST", "condition": {"subject": "you"}, "spell_subtype_any": ["doctor"]} in conditions
    assert {
        "event": "SPELL_CAST", "condition": {"subject": "you"},
        "spell_card_types": ["creature"], "spell_has_keyword": "Doctor's Companion",
    } in conditions
    assert all(s.effects == seg.spec.effects for s in seg.extra_specs)


def test_rose_noble_draws_once_for_a_doctor_creature_spell():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test Rose Noble", is_creature=True,
        oracle_text=(
            "Whenever you cast a Doctor spell or creature spell with "
            "doctor's companion, draw a card."
        ),
    ))
    p1.library.append(GameObject(_card("Filler"), owner_id="p1", zone=Zone.LIBRARY))
    doctor_spell = _hand(p1, _card(
        "Test Doctor", "Legendary Creature — Doctor", cost="{1}", cmc=1,
    ))

    p1.mana_pool.add_many({"C": 1})
    eng.rules.cast_spell(p1, doctor_spell)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert any(o.name == "Filler" for o in p1.hand)
    assert not p1.library


def test_rose_noble_draws_once_for_a_companion_creature_spell():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test Rose Noble", is_creature=True,
        oracle_text=(
            "Whenever you cast a Doctor spell or creature spell with "
            "doctor's companion, draw a card."
        ),
    ))
    p1.library.append(GameObject(_card("Filler"), owner_id="p1", zone=Zone.LIBRARY))
    companion_spell = _hand(p1, _card(
        "Test Companion", "Creature — Human", cost="{1}", cmc=1,
        keywords=["Doctor's Companion"],
    ))

    p1.mana_pool.add_many({"C": 1})
    eng.rules.cast_spell(p1, companion_spell)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert any(o.name == "Filler" for o in p1.hand)
    assert not p1.library


def test_rose_noble_does_not_double_draw_for_an_unrelated_creature_spell():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test Rose Noble", is_creature=True,
        oracle_text=(
            "Whenever you cast a Doctor spell or creature spell with "
            "doctor's companion, draw a card."
        ),
    ))
    p1.library.append(GameObject(_card("Filler"), owner_id="p1", zone=Zone.LIBRARY))
    plain_spell = _hand(p1, _card("Test Plain Bear", cost="{1}", cmc=1))

    p1.mana_pool.add_many({"C": 1})
    eng.rules.cast_spell(p1, plain_spell)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert not any(o.name == "Filler" for o in p1.hand)
    assert p1.library
