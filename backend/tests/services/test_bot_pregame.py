"""Opening-hand permissions use the same choice surface for bots and humans."""
import pytest

from mtg_analyzer.api.solo import _advance_solo_bots, _solo_view
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.bots import BOT_TYPES, create_bot, run_bots
from mtg_analyzer.services.game_session import GameSessionManager


def pregame_session(kind, *, human_cards=()):
    forest = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    caverns = Card(
        id="Gemstone Caverns", name="Gemstone Caverns", type_line="Land", is_land=True,
        oracle_text="If Gemstone Caverns is in your opening hand and you're not the starting player, "
                    "you may begin the game with Gemstone Caverns on the battlefield with a luck counter on it. "
                    "If you do, exile a card from your hand.",
    )
    leyline = Card(
        id="Leyline of the Void", name="Leyline of the Void", type_line="Enchantment",
        oracle_text="If Leyline of the Void is in your opening hand, you may begin the game with it on the battlefield.",
    )
    session = GameSessionManager().create_multiplayer([
        {"player_id": "solo:you", "name": "Du", "library": [forest] * (30-len(human_cards)) + list(human_cards)},
        {"player_id": "bot:1", "name": "Bot", "library": [forest] * 28 + [caverns, leyline]},
    ], mulligan_style="none")
    session._solo_bots = {"bot:1": create_bot(kind, "bot:1")}
    run_bots(session, session._solo_bots, max_actions=1)
    session.apply_action({"type": "keep_hand"}, actor_id="solo:you")
    return session


@pytest.mark.parametrize("kind", BOT_TYPES)
def test_bots_use_all_opening_cards_and_complete_caverns_exile(kind, monkeypatch):
    session = pregame_session(kind)
    if kind == "ai":
        def unexpected_llm_settings():
            pytest.fail("Pregame actions must not request an LLM decision")
        monkeypatch.setattr(session._solo_bots["bot:1"].settings_store, "get", unexpected_llm_settings)
    for _ in range(4):
        assert _solo_view(session)["bot_action_pending"]
        _advance_solo_bots(session)
        if session.engine.state.pending_choice is None:
            break
    state = session.engine.state
    assert state.pending_choice is None
    assert state.current_step == "upkeep"
    assert {o.name for o in state.battlefield} == {"Gemstone Caverns", "Leyline of the Void"}
    caverns = next(o for o in state.battlefield if o.name == "Gemstone Caverns")
    assert caverns.counters["luck"] == 1
    assert len(state.player_by_id("bot:1").exile) == 1
    assert len(state.player_by_id("bot:1").hand) == 4


def test_human_pregame_choice_is_exposed_and_not_answered_by_bot():
    leyline = Card(
        id="Leyline of Sanctity", name="Leyline of Sanctity", type_line="Enchantment",
        oracle_text="If Leyline of Sanctity is in your opening hand, you may begin the game with it on the battlefield.",
    )
    session = pregame_session("smart", human_cards=[leyline])
    view = _solo_view(session)
    assert view["pending_choice"]["kind"] == "opening_hand_battlefield"
    assert {a["type"] for a in view["legal_actions"]} == {"choose", "decline"}
    assert not view["bot_action_pending"]
    _advance_solo_bots(session)
    assert session.engine.state.pending_choice["player_id"] == "solo:you"
    session.apply_action({"type": "choose", "option_id": "battlefield"}, actor_id="solo:you")
    assert any(o.name == leyline.name for o in session.engine.state.battlefield)
    assert _solo_view(session)["bot_action_pending"]
