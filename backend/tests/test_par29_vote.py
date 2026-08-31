"""PAR-29 — RULE 701.38 Vote (Conspiracy / "Will of the Council").

`RulesEngine.request_vote` runs an APNAP sweep (`vote` pending_choice per
living player), then `_tally_and_apply_vote` resolves the outcome:

* majority — one serialized effect list per option; the strict leader's
  list applies, `tie_index`'s on a tie (RULE 701.38d).
* per_vote — `[{option, effects, scale}]`; each effect's count/amount is
  multiplied by scale × that option's vote total.

`effects.VoteEffect` binds it; `handlers._vote_majority` / `_vote_per_vote`
parse the two "starting with you, each player votes for A or B. …" shapes.

Reference: game/effects.py (`VoteEffect`), game/rules/misc_mixin.py
(`request_vote`/`_advance_vote`/`resolve_vote_choice`/`_tally_and_apply_
vote`), parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle


# --- parse -----------------------------------------------------------------


def test_vote_majority_parse():
    r = match_clause(
        "starting with you, each player votes for carnage or homage. "
        "if carnage gets more votes, sacrifice ~ and destroy all nonland permanents. "
        "if homage gets more votes or the vote is tied, draw a card."
    )
    assert r and r[0].type == "vote"
    assert r[0].params["options"] == ["carnage", "homage"]
    assert r[0].params["tie_index"] == 1
    assert len(r[0].params["majority_specs"]) == 2
    assert r[0].params["majority_specs"][1] == [{"type": "draw", "params": {"count": 1}}]


def test_vote_per_vote_parse():
    r = match_clause(
        "starting with you, each player votes for sprout or harvest. "
        "put 2 +1/+1 counters on ~ for each sprout vote. "
        "you gain 3 life for each harvest vote."
    )
    assert r and r[0].type == "vote"
    pv = r[0].params["per_vote_specs"]
    assert pv[0]["option"] == 0 and pv[0]["effects"][0]["params"]["count"] == 2
    assert pv[1]["option"] == 1 and pv[1]["effects"][0]["params"]["amount"] == 3


def test_vote_adversarial_rejects():
    # 3+ options, permanent-vote, and a carried per-player subject all fail closed
    assert match_clause(
        "starting with you, each player votes for blue, black, red, or green. "
        "~ gains protection from each color with the most votes or tied for most votes."
    ) is None
    assert match_clause(
        "starting with you, each player votes for death or taxes. "
        "each opponent sacrifices a creature of their choice for each death vote "
        "and discards a card for each taxes vote."
    ) is None


def test_real_vote_cards_modeled():
    for name, text in [
        ("Coercive Portal",
         "At the beginning of your upkeep, starting with you, each player votes for "
         "carnage or homage. If carnage gets more votes, sacrifice Coercive Portal and "
         "destroy all nonland permanents. If homage gets more votes or the vote is "
         "tied, draw a card."),
        ("Lieutenants of the Guard",
         "When Lieutenants of the Guard enters, starting with you, each player votes "
         "for strength or numbers. Put a +1/+1 counter on Lieutenants of the Guard "
         "for each strength vote and create a 1/1 white Soldier creature token for "
         "each numbers vote."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Artifact", oracle_text=text)
        assert parse_oracle(c).modeled, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def test_majority_vote_applies_leader_branch():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    src = GameObject(Card(id="s", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)

    eng.rules.request_vote(
        source=src, controller_id="p1", options=["a", "b"],
        majority_specs=[
            [{"type": "gain_life", "params": {"amount": 5}}],   # option a
            [{"type": "draw", "params": {"count": 3}}],          # option b
        ],
        tie_index=1,
    )
    # p1 votes a, p2 votes a -> a leads 2-0
    assert eng.state.pending_choice["kind"] == "vote"
    eng.resolve_pending_choice("0")
    eng.resolve_pending_choice("0")
    assert eng.state.pending_choice is None
    assert p1.life == 25 and len(p1.hand) == 0   # a-branch fired, not b


def test_majority_vote_tie_goes_to_tie_index():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    src = GameObject(Card(id="s", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    # give p1 a library so "draw" is meaningful
    for i in range(3):
        p1.add_to_zone(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Plains", is_land=True),
                                  owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)

    eng.rules.request_vote(
        source=src, controller_id="p1", options=["a", "b"],
        majority_specs=[
            [{"type": "gain_life", "params": {"amount": 5}}],
            [{"type": "draw", "params": {"count": 3}}],
        ],
        tie_index=1,
    )
    eng.resolve_pending_choice("0")   # p1 -> a
    eng.resolve_pending_choice("1")   # p2 -> b   => 1-1 tie
    assert p1.life == 20 and len(p1.hand) == 3   # tie_index=1 -> b-branch (draw 3)


def test_per_vote_scales_by_tally():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    src = GameObject(Card(id="s", name="Src", type_line="Creature — Soldier", is_creature=True,
                          power=1, toughness=1),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)

    eng.rules.request_vote(
        source=src, controller_id="p1", options=["strength", "numbers"],
        per_vote_specs=[
            {"option": 0, "effects": [{"type": "add_counters",
                                       "params": {"count": 1, "kind": "+1/+1"}}], "scale": 1},
            {"option": 1, "effects": [{"type": "gain_life", "params": {"amount": 2}}], "scale": 1},
        ],
    )
    eng.resolve_pending_choice("0")   # p1 -> strength
    eng.resolve_pending_choice("0")   # p2 -> strength   => strength 2, numbers 0
    eng.recompute_continuous_effects()
    assert src.counters.get("+1/+1") == 2   # 1 * 2 strength votes
    assert p1.life == 20                    # 2 * 0 numbers votes -> nothing
