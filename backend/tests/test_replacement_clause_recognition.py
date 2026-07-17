"""Tests for oracle-text *recognition* of standing replacement-effect
clauses (Batch 11's A.5 item) — the binder side (`game/effects.py`'s
`ReplacementRegistry`) already supported `double_tokens`/`double_counters`/
`additional_damage`/`prevent_damage`/`double_damage`; this covers the new
parser front-end (`parser/oracle/catalogue/replacements.py`) for the first
three, the ones with a single fixed real-card phrasing (Doubling Season/
Anointed Procession's token/counter-doubling lines, Torbran's "plus N
damage" line). `prevent_damage`'s real cards (Riot Control/Thought Lash)
are a different, unmodeled *one-shot spell effect* shape and aren't covered.

Mirrors `test_effect_families_wave3.py`'s parser-then-engine split.
"""

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.replacements import replacement_clause_specs
from mtg_analyzer.parser.oracle.gate import MODELED


def perm(name, text, type_line="Enchantment", **kw):
    return Card(id=name, name=name, type_line=type_line, oracle_text=text, **kw)


def _bound(state, card, controller="p1"):
    """A hand-authored-catalogue-free card, bound and on the battlefield."""
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


# ---------------------------------------------------------------------------
# PARSER RECOGNITION
# ---------------------------------------------------------------------------


def test_double_tokens_clause_is_recognized():
    specs = replacement_clause_specs(
        "If an effect would create 1 or more tokens under your control, "
        "it creates twice that many of those tokens instead."
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "double_tokens" and spec.params == {}


def test_double_counters_clause_is_recognized():
    specs = replacement_clause_specs(
        "If an effect would put 1 or more counters on a permanent you "
        "control, it puts twice that many of those counters on that "
        "permanent instead."
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "double_counters" and spec.params == {}


def test_additional_damage_clause_is_recognized_with_color_and_amount():
    specs = replacement_clause_specs(
        "If a red source you control would deal damage to an opponent or "
        "a permanent an opponent controls, it deals that much damage plus "
        "2 instead."
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "additional_damage"
    assert spec.params == {
        "amount": 2, "your_sources_only": True, "to_opponent_only": True, "color": "R",
    }


def test_mechanized_warfares_compound_color_filter_stays_unclaimed():
    # "a red or artifact source" is a compound OR filter this grammar
    # doesn't attempt — fails closed rather than dropping half the clause.
    assert replacement_clause_specs(
        "If a red or artifact source you control would deal damage to an "
        "opponent or a permanent an opponent controls, it deals that much "
        "damage plus 1 instead."
    ) is None


def test_innkeepers_talent_differently_scoped_counter_clause_stays_unclaimed():
    # "you would put ... on a permanent or player" — a different subject/
    # target shape from the Doubling Season sentence this module claims.
    assert replacement_clause_specs(
        "If you would put 1 or more counters on a permanent or player, "
        "put twice that many of each of those kinds of counters on that "
        "permanent or player instead."
    ) is None


def test_prevent_damage_one_shot_shape_stays_unclaimed_here():
    # Riot Control/Thought Lash-shaped — a one-shot spell effect, not a
    # standing permanent replacement clause; deliberately out of scope.
    assert replacement_clause_specs(
        "Prevent all damage that would be dealt to you this turn."
    ) is None


def test_gate_claims_torban_shaped_card_as_modeled():
    card = perm(
        "Torbran, Thane of Red Fell",
        "If a red source you control would deal damage to an opponent or "
        "a permanent an opponent controls, it deals that much damage plus "
        "2 instead.",
        type_line="Legendary Creature — Dwarf Berserker",
        is_creature=True, power=3, toughness=3,
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    (spec,) = [s for s in result.specs if s.ability_kind == "replacement"]
    assert spec.effects[0].type == "additional_damage"


def test_effect_specs_property_includes_replacement_kind():
    card = perm(
        "Anointed Procession",
        "If an effect would create 1 or more tokens under your control, "
        "it creates twice that many of those tokens instead.",
    )
    result = parse_oracle(card)
    assert result.modeled
    assert any(s.ability_kind == "replacement" for s in result.effect_specs)


# ---------------------------------------------------------------------------
# ENGINE: the bound ReplacementEffect actually replaces the event
# ---------------------------------------------------------------------------


def test_anointed_procession_doubles_token_creation():
    eng = _make_engine()
    card = perm(
        "Anointed Procession",
        "If an effect would create 1 or more tokens under your control, "
        "it creates twice that many of those tokens instead.",
    )
    _bound(eng.state, card)
    token_card = Card(id="Spirit", name="Spirit", type_line="Token Creature — Spirit",
                       is_creature=True, power=1, toughness=1)
    tokens = eng.rules.create_token("p1", token_card, count=1)
    assert len(tokens) == 2


def test_torbran_increases_damage_to_an_opponent_permanent():
    eng = _make_engine()
    card = perm(
        "Torbran, Thane of Red Fell",
        "If a red source you control would deal damage to an opponent or "
        "a permanent an opponent controls, it deals that much damage plus "
        "2 instead.",
        type_line="Legendary Creature — Dwarf Berserker",
        is_creature=True, power=3, toughness=3, color_identity={"R"},
    )
    torbran = _bound(eng.state, card)
    target = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(target)

    eng.rules.deal_damage(target, 3, source=torbran)
    assert target.damage_marked == 5  # 3 + Torbran's +2


def test_torbran_does_not_boost_damage_to_its_own_controller():
    eng = _make_engine()
    card = perm(
        "Torbran, Thane of Red Fell",
        "If a red source you control would deal damage to an opponent or "
        "a permanent an opponent controls, it deals that much damage plus "
        "2 instead.",
        type_line="Legendary Creature — Dwarf Berserker",
        is_creature=True, power=3, toughness=3, color_identity={"R"},
    )
    torbran = _bound(eng.state, card)
    own = GameObject(
        Card(id="OwnBear", name="OwnBear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(own)

    eng.rules.deal_damage(own, 3, source=torbran)
    assert own.damage_marked == 3  # unboosted — not "an opponent or their permanent"
