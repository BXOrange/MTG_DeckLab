""""Draw a card at the beginning of the next turn's upkeep" (RULE 603.7
delayed trigger) — Clairvoyance/Balduvian Rage/Carrier Pigeons-shaped,
~46 real cards using this exact clause.

The underlying engine mechanism (`CreateDelayedTriggerEffect`/
`GameState.delayed_triggers`) already existed (Batch 22, built for Mana
Drain's "at the beginning of your next main phase") — this was purely a
missing parser-front-end recognition gap (`docs/implementation-state/BACKLOG.md`), not a
new primitive: the front-end had zero handlers for "at the beginning of the
next `<step>`, `<effect>`" at all before this, so every card using the
mechanism was hand-authored (`ability_catalogue.py`). The new
``draw_next_upkeep`` handler (`catalogue/handlers.py`) emits the same
`create_delayed_trigger` EffectSpec generically, with ``scope="any"``
(RULE 603.7a — no "your" qualifier means the very next such step regardless
of whose turn, unlike Mana Drain's own controller-scoped "your next main
phase").

Deliberately unclaimed (fail-closed): the pronoun-scoped "its controller may
draw..." variant (Arcane Denial's own first sentence) — a different,
indirect-referent grammar shape, same family of gap as Run Away Together's
(`docs/implementation-state/BACKLOG.md`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.gate import MODELED, UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark_db = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present"
)


def _card(name, type_line, oracle_text, **flags):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text, **flags)


# --- Recognition -------------------------------------------------------


def test_bare_draw_next_upkeep_clause_parses():
    card = _card(
        "Test Sorcery", "Sorcery", "Draw a card at the beginning of the next turn's upkeep.",
        is_sorcery=True,
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    (spec,) = result.specs
    (effect,) = spec.effects
    assert effect.type == "create_delayed_trigger"
    assert effect.params == {
        "step": "upkeep", "scope": "any",
        "effects": [{"type": "draw", "params": {"count": 1}}],
    }


def test_you_draw_prefix_and_a_count_greater_than_one():
    card = _card(
        "Test Sorcery 2", "Sorcery",
        "You draw two cards at the beginning of the next turn's upkeep.",
        is_sorcery=True,
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    effect = result.specs[0].effects[0]
    assert effect.params["effects"] == [{"type": "draw", "params": {"count": 2}}]


def test_combines_with_a_second_clause_in_the_same_body():
    """Blessed Wine-shaped: an ordinary effect clause plus the delayed draw,
    split by the segmenter's connector fallback (". ")."""
    card = _card(
        "Test Sorcery 3", "Sorcery",
        "You gain 1 life. Draw a card at the beginning of the next turn's upkeep.",
        is_sorcery=True,
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    types = {e.type for e in result.specs[0].effects}
    assert types == {"gain_life", "create_delayed_trigger"}


def test_triggered_ability_body_carrier_pigeons_shaped():
    card = _card(
        "Test Bird", "Creature — Bird",
        "Flying\nWhen this creature enters, draw a card at the beginning of the next turn's upkeep.",
        is_creature=True, power=1, toughness=1,
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    assert len(triggered) == 1
    assert triggered[0].effects[0].type == "create_delayed_trigger"


def test_pronoun_scoped_its_controller_may_draw_stays_unclaimed():
    """Arcane Denial's own first sentence — a different, indirect-referent
    shape ("its controller", "may", "up to two") this handler doesn't
    attempt; deliberately fail-closed."""
    card = _card(
        "Test Instant", "Instant",
        "Counter target spell. Its controller may draw up to two cards "
        "at the beginning of the next turn's upkeep.",
        is_instant=True,
    )
    result = parse_oracle(card)
    assert result.coverage == UNMODELED


# --- End-to-end: the delayed draw actually fires at the next upkeep -----


def test_resolves_and_fires_at_the_next_upkeep():
    eng = GameEngine.new_game([("p1", "Alice", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    for _ in range(3):
        p1.library.append(GameObject(Card(id="f", name="Forest", type_line="Basic Land — Forest",
                                          is_land=True), owner_id=p1.id, zone=Zone.LIBRARY))

    card = _card(
        "Test Sorcery 4", "Sorcery", "Draw a card at the beginning of the next turn's upkeep.",
        mana_cost_string="{U}",
        converted_mana_cost=ManaCost.parse("{U}").converted_mana_cost,
        is_sorcery=True,
    )
    spell = GameObject(card, owner_id=p1.id, zone=Zone.STACK)
    bind_from_catalogue(spell)
    from mtg_analyzer.models.game_state import StackItem
    eng.state.stack.append(StackItem(
        kind="spell", controller_id=p1.id, obj=spell, description=card.name,
        effects=eng.rules._effects_for_spell(spell),
    ))
    eng.rules.resolve_top_of_stack()

    assert len(eng.state.delayed_triggers) == 1
    hand_before = len(p1.hand)

    # Walk the real step loop until an upkeep has run.
    for _ in range(12):
        ran = eng.advance_step()
        if ran and ran[1] == "upkeep":
            break
    eng.resolve_until_stable()

    assert len(p1.hand) == hand_before + 1
    assert eng.state.delayed_triggers == []


def test_any_scope_draws_for_its_controller_not_whoever_is_active():
    """RULE 603.7a: "the next turn's upkeep" (no "your") fires regardless of
    whose turn it is — but the card is still drawn by the delayed ability's
    *controller* (RULE 109.4), not by whoever happens to be active when it
    fires. Also a regression guard for a real bug this handler's own
    end-to-end testing surfaced: `DrawCardEffect.apply` used to fall back to
    ``context.active_player`` instead of the shared `_controller_of` helper
    every other untargeted effect uses (`GainLifeEffect` etc.) — invisible
    as long as tests only ever resolved effects during their own
    controller's turn, exactly the assumption an "any scope" delayed
    trigger breaks."""
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    eng.begin_turn()  # p1's turn, p1 active
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    for _ in range(3):
        p1.library.append(GameObject(Card(id="f", name="Forest", type_line="Basic Land — Forest",
                                          is_land=True), owner_id=p1.id, zone=Zone.LIBRARY))

    card = _card(
        "Test Sorcery 5", "Sorcery", "Draw a card at the beginning of the next turn's upkeep.",
        is_sorcery=True,
    )
    spell = GameObject(card, owner_id=p1.id, zone=Zone.STACK)
    bind_from_catalogue(spell)
    from mtg_analyzer.models.game_state import StackItem
    eng.state.stack.append(StackItem(
        kind="spell", controller_id=p1.id, obj=spell, description=card.name,
        effects=eng.rules._effects_for_spell(spell),
    ))
    eng.rules.resolve_top_of_stack()
    assert len(eng.state.delayed_triggers) == 1
    assert eng.state.delayed_triggers[0].scope == "any"

    # Simulate the trigger firing during *p2's* upkeep (active player flips).
    eng.state.active_player_index = eng.state.players.index(p2)
    eng._fire_delayed_triggers("upkeep")
    eng.resolve_until_stable()

    assert len(p1.hand) == 1, "the trigger's controller (p1) drew the card"
    assert len(p2.hand) == 0, "not the player who happened to be active"
    assert eng.state.delayed_triggers == []


# --- Real cards -----------------------------------------------------------


@pytestmark_db
@pytest.mark.parametrize("name", [
    "Carrier Pigeons", "Blessed Wine", "Astrolabe", "Barbed Sextant",
    "Burnout", "Mystic Melting",
])
def test_real_card_now_modeled(name):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name} not cached")
    result = parse_oracle(card)
    assert result.coverage == MODELED, f"{name}: {result.unclaimed}"
