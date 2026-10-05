"""PAR-120 — "you control your commander" as a standing condition (RULE
903.4/613.6/603.4), the "Loyal" Commander-legends cycle's own gate (a
phase-trigger leading "if" here; the same phrase's "as long as" static form
and its compound "gets +N/+N and creatures you control have `<keyword>`"
body shape are a separate, larger gap — a self-pump-plus-group-grant
compound `static_effect_specs` doesn't recognize at all yet — left open,
confirmed via `parser_probe.py card` on Angelic Field Marshal/Demon of
Wailing Agonies/Stormsurge Kraken/Thunderfoot Baloth rather than assumed).

No new condition kind: `control_count` again, the same kind every board
existence/threshold check in this ticket has reused — only `continuous.
count_selector` needed a new selector, `commanders_you_control`. RULE 108.4:
control only applies to a *battlefield* permanent, so a commander sitting in
the command zone deliberately doesn't count — narrower than
`condition_query.free_cast_condition_holds`'s existing, differently-scoped
`"control_commander"` key (whether a commander is available to cast at all,
command zone included), which answers a different question for a different
caller (an alt-cost gate, not this standing condition).

`parser_probe.py diff`: +6 (Loyal Apprentice, Loyal Drake, Loyal Guardian,
Loyal Subordinate, Skyhunter Strike Force, Tyrant's Familiar), 0 regressed.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


# ---------------------------------------------------------------------------
# PARSER: the condition itself
# ---------------------------------------------------------------------------


def test_control_your_commander():
    assert static_condition("you control your commander") == {
        "kind": "control_count", "selector": "commanders_you_control", "min": 1,
    }


def test_an_unrelated_phrase_fails_closed():
    assert static_condition("you control an opponent's commander") is None


# ---------------------------------------------------------------------------
# PARSER: end-to-end, real cards
# ---------------------------------------------------------------------------


def test_real_cards_become_modeled():
    for name in (
        "Loyal Apprentice", "Loyal Drake", "Loyal Guardian",
        "Loyal Subordinate", "Skyhunter Strike Force", "Tyrant's Familiar",
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


# ---------------------------------------------------------------------------
# ENGINE: end-to-end, real board
# ---------------------------------------------------------------------------


def test_loyal_drake_draws_only_while_its_controller_controls_their_commander():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    state = eng.state
    state.active_player_index = 0  # p1's own turn

    drake = GameObject(_db().get_card("Loyal Drake"), owner_id="p1", zone=Zone.BATTLEFIELD)
    drake.controller_id = "p1"
    bind_from_catalogue(drake)
    state.add_to_battlefield(drake)

    from mtg_analyzer.models.game.events import EventType, GameEvent

    def _fire_begin_combat():
        state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", phase="combat"))

    p1 = state.players[0]
    p1.library.append(GameObject(
        Card(id="l0", name="L0", type_line="Plains", is_land=True),
        owner_id="p1", zone=Zone.LIBRARY,
    ))
    p1.library.append(GameObject(
        Card(id="l1", name="L1", type_line="Plains", is_land=True),
        owner_id="p1", zone=Zone.LIBRARY,
    ))

    # No commander on the battlefield yet — the draw is gated off.
    _fire_begin_combat()
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert len(p1.hand) == 0

    # p1's commander enters the battlefield.
    commander = GameObject(
        Card(id="cmd", name="Commander", type_line="Legendary Creature — Human",
             is_creature=True, power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    commander.controller_id = "p1"
    commander.is_commander = True
    state.add_to_battlefield(commander)

    _fire_begin_combat()
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert len(p1.hand) == 1
