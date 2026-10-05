"""PAR-120 — "at the beginning of each opponent's/each player's `<step>`, if
that player has `<N>` or fewer/no cards in hand, `<effect>`." (RULE
502.1/603.4) — the "hellbent punisher" cluster (Davriel, Rogue Shadowmage;
Hellfire Mongrel; Lavaborn Muse; Paupers' Cage; Shrieking Affliction;
Hollowborn Barghest; Ghirapur Orrery; Asylum Visitor).

"That player"/"they" is whoever's step just began (RULE 502.1's active
player), not this ability's own controller — a referent only this surface
(a per-player phase trigger) carries, deliberately kept out of the shared
`static_condition()` table an activated ability's own, differently-scoped
"that player" (a previously targeted opponent, Nezumi Shortfang) also
reaches, which would otherwise be silently misread.

No new engine primitive for the *effect* bodies: `effect_operands.
PLAYER_SCOPES`'s existing ``"active_player"`` scope string already resolves
generically through `DrawCardEffect.player`/`LoseLifeEffect.player`'s
ENG-37 operand path (`_PHASE_DAMAGE_TO_THEM_RE`'s damage shape already used
the same referent by a different route). Only the *condition* needed a new
`static_conditions.py` kind, `active_player_cards_in_hand_at_most` — the
existing `cards_in_hand_at_most` always reads the ability's own controller,
which is the wrong player for this per-opponent trigger shape.

`parser_probe.py diff`: +8, 0 regressed. Nezumi Shortfang (a previous-target
referent, not this one) and Quest for the Nihil Stone (an AND of this
condition with a counter-count check) stay UNMODELED — confirmed via
`parser_probe.py card`, out of scope here.
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
# PARSER: end-to-end, real cards (the condition itself is phase-trigger-only,
# so it's not reachable through `static_condition()` directly — see the
# module docstring)
# ---------------------------------------------------------------------------


def test_static_condition_does_not_claim_this_phrase():
    # Deliberately NOT in the shared table — an activated ability's own
    # "that player" (Nezumi Shortfang) means something else entirely, and
    # a shared row here would silently misread it.
    assert static_condition("that player has no cards in hand") is None


def test_real_cards_become_modeled():
    for name in (
        "Asylum Visitor", "Davriel, Rogue Shadowmage", "Ghirapur Orrery",
        "Hellfire Mongrel", "Hollowborn Barghest", "Lavaborn Muse",
        "Paupers' Cage", "Shrieking Affliction",
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


def test_nezumi_shortfangs_own_previous_target_referent_stays_unmodeled():
    card = _db().get_card("Nezumi Shortfang // Stabwhisker the Odious")
    assert not parse_oracle(card).modeled


# ---------------------------------------------------------------------------
# ENGINE: end-to-end, real board
# ---------------------------------------------------------------------------


def test_hollowborn_barghest_drains_the_opponent_only_while_hellbent():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    state = eng.state

    barghest = GameObject(_db().get_card("Hollowborn Barghest"), owner_id="p1", zone=Zone.BATTLEFIELD)
    barghest.controller_id = "p1"
    bind_from_catalogue(barghest)
    state.add_to_battlefield(barghest)

    p2 = state.players[1]
    p2.hand.append(GameObject(
        Card(id="c0", name="C0", type_line="Plains", is_land=True),
        owner_id="p2", zone=Zone.HAND,
    ))

    from mtg_analyzer.models.game.events import EventType, GameEvent

    def _fire_p2_upkeep():
        state.active_player_index = 1  # p2's own turn/upkeep
        state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))

    # p2 has a card in hand — RULE 603.4's intervening "if" means the
    # trigger doesn't go on the stack at all.
    _fire_p2_upkeep()
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0
    assert p2.life == 20

    # p2 empties their hand — now hellbent.
    p2.hand.clear()
    _fire_p2_upkeep()
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert p2.life == 18
