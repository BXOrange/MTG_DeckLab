"""Tests for the counterspell family (docs/09 processing list).

Covers the previously-unclaimed templates:

* "counter target noncreature spell." / "… target instant or sorcery spell."
  / "… target spell with mana value N." — a structured filter on *which*
  spells are legal targets (RULE 601.2c/115), threaded through
  `targeting.legal_targets`.
* "counter target spell unless its controller pays {N}." (RULE 601, the
  "Mana Leak" template) — an interactive `counter_unless_pays` choice.
* "This spell can't be countered." (RULE 118-area) — a marker effect the
  counter machinery refuses to act on.

Reference: mtg_analyzer/parser/oracle/catalogue/{handlers,static_handlers,
subgrammars}.py, mtg_analyzer/game/{effects,rules_engine,targeting}.py.
"""

from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import CantBeCounteredEffect, CounterSpellEffect, DrawCardEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.catalogue.subgrammars import resolve_spell_filter
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec

# ---------------------------------------------------------------------------
# Card factories + fixtures (mirrors tests/test_targeting.py's style)
# ---------------------------------------------------------------------------


def instant(name, cost="{0}", oracle_text=""):
    return Card(
        id=name,
        name=name,
        type_line="Instant",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_instant=True,
        oracle_text=oracle_text,
    )


def sorcery(name, cost="{0}", oracle_text=""):
    return Card(
        id=name,
        name=name,
        type_line="Sorcery",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_sorcery=True,
        oracle_text=oracle_text,
    )


def creature(name="Grizzly Bears", cost="{1}{G}", oracle_text=""):
    return Card(
        id=name,
        name=name,
        type_line="Creature — Bear",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=True,
        power=2,
        toughness=2,
        oracle_text=oracle_text,
    )


def two_player_engine():
    filler = instant("Filler")
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler] * 5), ("p2", "Bob", [filler] * 5)],
        starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def push_spell(eng, player, card, effects=None):
    """Put ``card`` directly onto the stack as ``player``'s spell.

    Bypasses casting/payment (like `test_game_engine.
    test_counter_spell_removes_it_from_the_stack`) — the counter family's
    own mechanics are what's under test, not casting.
    """
    obj = GameObject(card, owner_id=player.id, zone=Zone.STACK)
    obj.spell_effects = effects or []
    for e in obj.spell_effects:
        e.source = obj
    item = StackItem(
        kind="spell",
        controller_id=player.id,
        obj=obj,
        description=card.name,
        effects=obj.spell_effects,
    )
    eng.state.stack.append(item)
    return obj


# ---------------------------------------------------------------------------
# Parser: template recognition, each → its expected EffectSpec(s)
# ---------------------------------------------------------------------------


def test_bare_counter_target_spell_still_claimed():
    assert match_clause("counter target spell") == [EffectSpec("counter", {})]


def test_counter_target_noncreature_spell():
    assert match_clause("counter target noncreature spell") == [
        EffectSpec("counter", {"noncreature": True})
    ]


def test_counter_target_instant_or_sorcery_spell():
    assert match_clause("counter target instant or sorcery spell") == [
        EffectSpec("counter", {"card_types": ["instant", "sorcery"]})
    ]


def test_counter_target_instant_spell_single_type():
    assert match_clause("counter target instant spell") == [
        EffectSpec("counter", {"card_types": ["instant"]})
    ]


def test_counter_target_enchantment_instant_or_sorcery_spell_three_types():
    assert match_clause("counter target enchantment, instant, or sorcery spell") == [
        EffectSpec("counter", {"card_types": ["enchantment", "instant", "sorcery"]})
    ]


def test_counter_target_spell_with_mana_value_n():
    assert match_clause("counter target spell with mana value 2") == [
        EffectSpec("counter", {"mana_value": 2})
    ]


def test_counter_target_spell_unless_its_controller_pays():
    assert match_clause("counter target spell unless its controller pays {1}") == [
        EffectSpec("counter", {"unless_pays": "{1}"})
    ]


def test_counter_target_instant_or_sorcery_spell_unless_pays():
    assert match_clause(
        "counter target instant or sorcery spell unless its controller pays {1}"
    ) == [EffectSpec("counter", {"card_types": ["instant", "sorcery"], "unless_pays": "{1}"})]


def test_counter_target_noncreature_spell_unless_pays():
    assert match_clause(
        "counter target noncreature spell unless its controller pays {2}"
    ) == [EffectSpec("counter", {"noncreature": True, "unless_pays": "{2}"})]


def test_unrecognized_spell_filter_stays_unclaimed():
    # "legendary" isn't a card-type word this grammar knows — fail-closed
    # (docs/09): the clause is left unclaimed rather than guessing.
    assert match_clause("counter target legendary spell") is None
    assert resolve_spell_filter("target legendary spell") is None


def test_resolve_spell_filter_bare_spell_is_the_empty_filter():
    assert resolve_spell_filter("target spell") == {}
    assert resolve_spell_filter("target creature") is None  # not a spell phrase


def test_this_spell_cant_be_countered_via_spell_effect_path():
    # An instant/sorcery's own resolve-time body (allow_spell_effect=True).
    assert match_clause("this spell can't be countered") == [
        EffectSpec("cant_be_countered", {})
    ]


def test_this_spell_cant_be_countered_via_static_path():
    # A permanent's standing line (allow_spell_effect=False) is claimed by
    # the static-clause table instead — same phrase, same spec, so both
    # front-end paths agree.
    assert static_effect_specs("this spell can't be countered") == [
        EffectSpec("cant_be_countered", {})
    ]


def test_full_card_negate_is_modeled():
    card = instant("Negate", oracle_text="Counter target noncreature spell.")
    result = parse_oracle(card)
    assert result.modeled
    spec = result.effect_specs[0]
    assert spec.effects[0].type == "counter"
    assert spec.effects[0].params == {"noncreature": True}


def test_full_card_dovins_veto_claims_both_lines():
    card = instant(
        "Dovin's Veto",
        oracle_text="This spell can't be countered.\nCounter target noncreature spell.",
    )
    result = parse_oracle(card)
    assert result.modeled
    types = [spec.effects[0].type for spec in result.effect_specs]
    assert types == ["cant_be_countered", "counter"]


def test_full_card_toski_cant_be_countered_on_a_creature():
    card = creature(
        "Toski, Bearer of Secrets", cost="{2}{G}{G}",
        oracle_text="This spell can't be countered.",
    )
    result = parse_oracle(card)
    assert result.modeled
    assert result.effect_specs[0].effects[0].type == "cant_be_countered"


# ---------------------------------------------------------------------------
# Targeting: the spell filter is enforced by `legal_targets` (RULE 601.2c/115)
# ---------------------------------------------------------------------------


def test_noncreature_filter_excludes_a_creature_spell():
    eng, p1, p2 = two_player_engine()
    push_spell(eng, p2, creature("Bear"))
    push_spell(eng, p2, instant("Shock"))
    spec = CounterSpellEffect(noncreature=True).target_spec
    opts = targeting.legal_targets(eng.state, p1.id, spec)
    assert {o["name"] for o in opts} == {"Shock"}


def test_card_types_filter_is_an_or_of_the_listed_types():
    eng, p1, p2 = two_player_engine()
    push_spell(eng, p2, instant("Bolt"))
    push_spell(eng, p2, sorcery("Wrath"))
    push_spell(eng, p2, creature("Bear"))
    spec = CounterSpellEffect(card_types=["instant", "sorcery"]).target_spec
    opts = targeting.legal_targets(eng.state, p1.id, spec)
    assert {o["name"] for o in opts} == {"Bolt", "Wrath"}


def test_mana_value_filter_is_honored():
    eng, p1, p2 = two_player_engine()
    push_spell(eng, p2, instant("Cheap", cost="{U}"))
    push_spell(eng, p2, instant("Pricey", cost="{2}{U}"))
    spec = CounterSpellEffect(mana_value=1).target_spec
    opts = targeting.legal_targets(eng.state, p1.id, spec)
    assert {o["name"] for o in opts} == {"Cheap"}


def test_bare_counter_has_no_filter_and_targets_any_spell():
    eng, p1, p2 = two_player_engine()
    push_spell(eng, p2, creature("Bear"))
    spec = CounterSpellEffect().target_spec
    opts = targeting.legal_targets(eng.state, p1.id, spec)
    assert {o["name"] for o in opts} == {"Bear"}


# ---------------------------------------------------------------------------
# "Unless its controller pays {N}" (RULE 601) — both branches
# ---------------------------------------------------------------------------


def test_unless_pays_opens_a_choice_when_the_controller_can_pay():
    eng, p1, p2 = two_player_engine()
    target = push_spell(eng, p2, instant("Doomed Bolt"), [DrawCardEffect(1, player=p2)])
    p2.mana_pool.add("U", 2)
    eng.rules.counter_unless_pays(target, "{1}", source=None)
    choice = eng.state.pending_choice
    assert choice is not None
    assert choice["kind"] == "counter_unless_pays"
    assert choice["player_id"] == "p2"


def test_unless_pays_countered_when_declined():
    eng, p1, p2 = two_player_engine()
    target = push_spell(eng, p2, instant("Doomed Bolt"), [DrawCardEffect(1, player=p2)])
    p2.mana_pool.add("U", 2)
    eng.rules.counter_unless_pays(target, "{1}", source=None)
    eng.rules.resolve_choice("decline")
    assert eng.state.pending_choice is None
    assert target not in [item.obj for item in eng.state.stack]
    assert target in p2.graveyard


def test_unless_pays_stays_on_stack_and_deducts_mana_when_paid():
    eng, p1, p2 = two_player_engine()
    target = push_spell(eng, p2, instant("Doomed Bolt"), [DrawCardEffect(1, player=p2)])
    p2.mana_pool.add("U", 2)
    eng.rules.counter_unless_pays(target, "{1}", source=None)
    eng.rules.resolve_choice("pay")
    assert eng.state.pending_choice is None
    assert target in [item.obj for item in eng.state.stack]
    assert p2.mana_pool.total() == 1  # {1} generic paid out of {U}{U}


def test_unless_pays_auto_counters_when_the_controller_cannot_pay():
    # No pending_choice ever opens — the "goldfish dummy has no mana" case:
    # a controller with no legal payment has no real decision to make.
    eng, p1, p2 = two_player_engine()
    target = push_spell(eng, p2, instant("Doomed Bolt"), [DrawCardEffect(1, player=p2)])
    eng.rules.counter_unless_pays(target, "{3}", source=None)
    assert eng.state.pending_choice is None
    assert target not in [item.obj for item in eng.state.stack]
    assert target in p2.graveyard


def test_resolve_pending_choice_dispatches_counter_unless_pays_and_the_spell_resolves():
    # Full GameEngine-level wiring: `resolve_pending_choice` → the
    # `counter_unless_pays` branch → `resolve_until_stable` finishes
    # resolving the saved spell (it draws p2 a card rather than being
    # countered).
    eng, p1, p2 = two_player_engine()
    before_hand = len(p2.hand)
    target = push_spell(eng, p2, instant("Doomed Bolt"), [DrawCardEffect(1, player=p2)])
    p2.mana_pool.add("U", 2)
    eng.rules.counter_unless_pays(target, "{1}", source=None)
    eng.resolve_pending_choice("pay")
    assert eng.state.pending_choice is None
    assert target not in [item.obj for item in eng.state.stack]  # resolved, not countered
    assert target in p2.graveyard
    assert len(p2.hand) == before_hand + 1


def test_unless_pays_with_literal_x_cost_uses_the_counterspells_own_announced_x():
    # Logic Knot's "counter target spell unless its controller pays {X}" ties
    # X to the countering spell's own announced X (RULE 601.2b), stamped on
    # its GameObject at cast time (`RulesEngine.cast_spell`'s `x_paid`).
    eng, p1, p2 = two_player_engine()
    target = push_spell(eng, p2, instant("Doomed Bolt"), [DrawCardEffect(1, player=p2)])
    logic_knot = GameObject(instant("Logic Knot", cost="{X}{U}{U}"), owner_id="p1")
    logic_knot.x_paid = 2
    p2.mana_pool.add("U", 2)
    eng.rules.counter_unless_pays(target, "{X}", source=logic_knot)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "counter_unless_pays"
    eng.rules.resolve_choice("pay")
    assert p2.mana_pool.total() == 0  # paid {2} (X=2) out of {U}{U}


# ---------------------------------------------------------------------------
# "This spell can't be countered." (RULE 118-area)
# ---------------------------------------------------------------------------


def test_cant_be_countered_refuses_a_bare_counter():
    eng, p1, p2 = two_player_engine()
    target = push_spell(
        eng, p2, instant("Unstoppable Bolt"),
        [CantBeCounteredEffect(), DrawCardEffect(1, player=p2)],
    )
    eng.rules.counter_unless_pays(target, None, source=None)
    assert target in [item.obj for item in eng.state.stack]
    assert eng.state.pending_choice is None


def test_cant_be_countered_refuses_an_unless_pays_counter_without_offering_a_choice():
    eng, p1, p2 = two_player_engine()
    target = push_spell(
        eng, p2, instant("Unstoppable Bolt"),
        [CantBeCounteredEffect(), DrawCardEffect(1, player=p2)],
    )
    # No mana at all — if the "can't be countered" check didn't come first,
    # this would auto-counter (unpayable branch).
    eng.rules.counter_unless_pays(target, "{1}", source=None)
    assert target in [item.obj for item in eng.state.stack]
    assert eng.state.pending_choice is None


def test_cant_be_countered_still_resolves_normally():
    eng, p1, p2 = two_player_engine()
    before_hand = len(p2.hand)
    target = push_spell(
        eng, p2, instant("Unstoppable Bolt"),
        [CantBeCounteredEffect(), DrawCardEffect(1, player=p2)],
    )
    eng.rules.counter_unless_pays(target, None, source=None)  # refused, no-op
    eng.rules.resolve_top_of_stack()
    assert target not in eng.state.stack
    assert target in p2.graveyard
    assert len(p2.hand) == before_hand + 1


def test_cant_be_countered_binds_from_a_permanents_static_line():
    # RULE 118 docked via the `static` ability_kind path (a creature's
    # standing line), not just the `spell_effect` path above — both must
    # produce a marker `RulesEngine._is_cant_be_countered` recognises.
    card = creature(
        "Toski, Bearer of Secrets", cost="{2}{G}{G}",
        oracle_text="This spell can't be countered.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(obj)
    eng, _p1, _p2 = two_player_engine()
    assert eng.rules._is_cant_be_countered(obj)
