"""PAR-21 — RULE 701 keyword-action audit: first parser handlers for the two
actions whose engine effect was already shipped but had zero oracle-text
recognition. Widened for PAR-29's "Parser-shaped only" residue (targeting,
previous-subject, and RULE 701.50d's dynamic "connives X" — see
`test_connive_target_and_dynamic_amount.py` for the fuller family and
execute-level coverage of the widened `ConniveEffect`).

* RULE 701.50 **Connive** → `game/effects/core.py` `ConniveEffect` (proven only
  via the hand-authored Ledger Shredder entry until now). The two subjects
  where the conniving permanent is the ability's own source — "~ connives"
  (explicit self) and the "it/he/she" pronoun of a self-subject trigger — a
  `TargetSpec` subject ("target creature you control connives"), the
  previous-clause pronoun, and RULE 701.50d's dynamic "connives X, where X
  is `<count-selector-or-trigger-event-field>`" are all claimed. A bare
  literal "connives N"/"connives x" with no "where X is" explanation still
  stays UNMODELED — no real printed card uses that shape.
* RULE 701.57 **Discover** → `game/effects/core.py` `DiscoverEffect` (Cascade's
  sibling). Literal `discover <n>` only; "discover X, where X is
  <selector>" stays UNMODELED.

Reference: mtg_analyzer/parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_named_self_connive_parses():
    assert match_clause("~ connives") == [EffectSpec("connive", {})]


def test_pronoun_connive_parses_only_with_self_subject():
    # `self_subject_only` — the "it" is the source only inside a self-subject
    # trigger body; a plain match must not claim it.
    assert match_clause("it connives") is None
    assert match_clause("it connives", self_subject=True) == [EffectSpec("connive", {})]
    assert match_clause("he connives", self_subject=True) == [EffectSpec("connive", {})]
    assert match_clause("she connives", self_subject=True) == [EffectSpec("connive", {})]


def test_targeted_connive_parses():
    # PAR-29: `ConniveEffect` now takes a `TargetSpec` subject, so this is
    # claimed — the conniving permanent is whichever creature is targeted,
    # not the ability's own source.
    assert match_clause("target creature you control connives") == [
        EffectSpec("connive", {"target_kind": "creature_you_control"})
    ]


def test_connive_bare_n_stays_unclaimed():
    # A literal "connive N"/"connives 2" with no "where X is <…>" tail never
    # appears on a real card — every printed dynamic connive spells out
    # where the number comes from (RULE 701.50d), so this stays fail-closed
    # rather than guessing what "2" or "x" alone means.
    assert match_clause("~ connives x") is None
    assert match_clause("it connives 2", self_subject=True) is None


def test_connive_dynamic_x_parses():
    # RULE 701.50d "connives X, where X is <count-selector>" — Raffine,
    # Scheming Seer / Spymaster's Vault-shaped.
    assert match_clause(
        "target attacking creature connives x, where x is the number of attacking creatures"
    ) == [EffectSpec("connive", {
        "target_kind": "creature", "times_from_count_selector": "attacking_creatures",
    })]
    assert match_clause(
        "it connives x, where x is the amount of damage it dealt to that player",
        self_subject=True,
    ) == [EffectSpec("connive", {"times_from_trigger_event": "amount"})]


def test_connive_each_x_target_creatures_parses():
    # Change of Plans: "each of X target creatures you control connive."
    assert match_clause("each of x target creatures you control connive") == [
        EffectSpec("connive", {
            "target_kind": "creature_you_control", "count_selector": "source_x_paid",
            "optional": True,
        })
    ]


def test_real_card_enters_trigger_is_modeled_end_to_end():
    # A-Psionic Snoop: "When Psionic Snoop enters, it connives." — a real
    # previously-UNMODELED card, not the hand-authored Ledger Shredder.
    card = Card(
        id="Snoopy", name="Snoopy",
        type_line="Creature — Human Rogue", is_creature=True, power=1, toughness=3,
        oracle_text="When this creature enters, it connives.",
    )
    result = parse_oracle(card)
    assert result.modeled
    spec = result.effect_specs[0]
    assert [e.type for e in spec.effects] == ["connive"]


def test_connive_executes_draws_discards_and_grows_on_nonland():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    p1 = state.player_by_id("p1")

    # Library top is a nonland, so the forced discard (post-draw hand has one
    # card) is that nonland → RULE 701.50a places the +1/+1 counter.
    p1.library.append(
        GameObject(
            Card(id="Bear", name="Bear", type_line="Creature — Bear",
                 is_creature=True, power=2, toughness=2),
            owner_id="p1", zone=Zone.LIBRARY,
        )
    )

    card = Card(
        id="Conniver", name="Conniver", type_line="Creature — Rogue",
        is_creature=True, power=1, toughness=1,
        oracle_text="When this creature enters, it connives.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)

    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
            controller_id="p1", object_types=sorted(obj.type_words),
        )
    )
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    eng.resolve_until_stable()

    assert obj.counters.get("+1/+1", 0) == 1
    assert not p1.library  # the one card was drawn


# --- RULE 701.57 Discover --------------------------------------------------


def test_discover_literal_count_parses():
    assert match_clause("discover 3") == [EffectSpec("discover", {"mana_value": 3})]
    assert match_clause("discover 10") == [EffectSpec("discover", {"mana_value": 10})]


def test_discover_dynamic_amount_stays_unclaimed():
    # "discover X, where X is <count-selector>" (Pantlaza / Aloy) —
    # `DiscoverEffect` takes no dynamic amount, so this fails closed.
    assert match_clause("discover x, where x is the number of creatures you control") is None


def test_real_discover_card_is_modeled_end_to_end():
    # Trumpeting Carnosaur: "When this creature enters, discover 5." — a real
    # previously-UNMODELED card.
    card = Card(
        id="Carno", name="Carno", type_line="Creature — Dinosaur",
        is_creature=True, power=7, toughness=6,
        oracle_text="When this creature enters, discover 5.",
    )
    result = parse_oracle(card)
    assert result.modeled
    spec = result.effect_specs[0]
    assert [e.type for e in spec.effects] == ["discover"]
    assert spec.effects[0].params == {"mana_value": 5}


def test_discover_executes_and_opens_the_choice():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    p1 = state.player_by_id("p1")

    # Top of library: a land (skipped), then a MV-2 nonland (the hit).
    p1.library.append(
        GameObject(
            Card(id="Small", name="Small", type_line="Instant", is_instant=True,
                 mana_cost_string="{1}{R}", converted_mana_cost=2),
            owner_id="p1", zone=Zone.LIBRARY,
        )
    )
    p1.library.append(
        GameObject(
            Card(id="TopLand", name="TopLand", type_line="Basic Land — Mountain",
                 is_land=True),
            owner_id="p1", zone=Zone.LIBRARY,
        )
    )

    card = Card(
        id="Discoverer", name="Discoverer", type_line="Creature — Dinosaur",
        is_creature=True, power=3, toughness=3,
        oracle_text="When this creature enters, discover 3.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)

    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
            controller_id="p1", object_types=sorted(obj.type_words),
        )
    )
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "discover"
    eng.rules.resolve_choice("hand")
    assert any(o.name == "Small" for o in p1.hand)
