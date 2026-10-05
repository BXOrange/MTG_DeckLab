"""PAR-51 — Storied (RULE 702.195) and its "enduring story" designation.

The other half of BACKLOG's PAR-51 ("`start` (#12) and `storied` (#9)"):
`start` turned out to be noise — no recurring template survived a fresh
`commander_tail_report.py` run (its only real find, the spurious `Jump`/
`Jump-start` label split, already shipped as `test_par51_keyword_prefix_
normalization.py`) — while `storied` is a real, current keyword (the
Hobbit/Dwarves cluster: Balin, Bifur, Bombur, Dáin, Fíli, Kíli, Ori, Thorin,
Óin) mechanically identical to Ascend/the city's blessing
(`test_mec_12_city_blessing.py`, which this file mirrors): a plain,
idempotent, never-cleared per-player flag (`Player.has_enduring_story`,
RULE 702.195b), granted by a live SBA-cadence board check
(`RulesEngine._sba_check_storied`) once a permanent with storied's
controller controls three or more permanents that are artifacts, Sagas,
and/or legendary (RULE 702.195a) — just a three-way type/subtype/supertype
OR instead of Ascend's flat ten-permanent tally.

Recognizing "storied" also needed `normalize._fold_given_name_prefix`
widened to fold a comma-less legendary's given name before " the "
(Kaalia-of-the-Vast's existing " of " sibling) — Fíli/Óin/Kíli self-refer by
first name in a "<Name> the <Epithet>" title with no comma at all. That
widening is matched case-sensitively (unlike every other fold in the
module) specifically because a common word can share a name's spelling —
"turn" inside "until end of turn" for the real card "Turn the Tide", "start"
inside "Jump-start" for "Start the TARDIS" — and a genuine self-reference is
always printed capitalized while a mid-sentence common word never is.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat, static_conditions
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition, static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine(*player_ids):
    players = [Player(id=pid, life=20) for pid in player_ids]
    state = GameState(players=players)
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state


def _permanent(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _storied_permanent(controller="p1"):
    return Card(
        id=f"Bench Storied Permanent {controller}", name=f"Bench Storied Permanent {controller}",
        type_line="Enchantment", mana_cost_string="{1}", converted_mana_cost=1,
        oracle_text=(
            "Storied (If you control three or more artifacts, legendaries, and/or "
            "Sagas, you have an enduring story for the rest of the game.)"
        ),
        keywords=["Storied"],
    )


# ---------------------------------------------------------------------------
# RulesEngine.get_enduring_story — the shared idempotent primitive
# ---------------------------------------------------------------------------


def test_get_enduring_story_is_idempotent():
    engine, state = _engine("p1")
    p1 = state.players[0]
    assert p1.has_enduring_story is False
    engine.rules.get_enduring_story(p1)
    assert p1.has_enduring_story is True
    engine.rules.get_enduring_story(p1)
    assert p1.has_enduring_story is True


# ---------------------------------------------------------------------------
# Storied keyword recognition + the SBA-cadence board check
# ---------------------------------------------------------------------------


def test_storied_keyword_recognized():
    obj = _permanent(GameState(players=[Player(id="p1", life=20)]), _storied_permanent())
    assert combat.has(obj, "storied")


def test_sba_check_storied_grants_at_three_qualifying_permanents():
    engine, state = _engine("p1", "p2")
    p1, p2 = state.players
    storied_permanent = _permanent(state, _storied_permanent())
    # Two more qualifying permanents (an artifact + a legendary) plus the
    # storied enchantment itself — that enchantment isn't an artifact or
    # legendary, so it doesn't count toward its own threshold.
    _permanent(state, Card(
        id="Bench Artifact", name="Bench Artifact", type_line="Artifact",
        mana_cost_string="{1}", converted_mana_cost=1,
    ))
    _permanent(state, Card(
        id="Bench Legend", name="Bench Legend", type_line="Legendary Creature — Human",
        mana_cost_string="{1}", converted_mana_cost=1, is_creature=True,
        is_legendary=True, power=1, toughness=1,
    ))
    assert p1.has_enduring_story is False
    engine.rules.check_state_based_actions()
    assert p1.has_enduring_story is False  # only 2 qualifying permanents so far

    _permanent(state, Card(
        id="Bench Saga", name="Bench Saga", type_line="Enchantment — Saga",
        mana_cost_string="{1}", converted_mana_cost=1,
    ))
    engine.rules.check_state_based_actions()
    assert p1.has_enduring_story is True
    assert p2.has_enduring_story is False
    assert storied_permanent is not None


def test_sba_check_storied_does_not_grant_below_three():
    engine, state = _engine("p1")
    p1 = state.players[0]
    _permanent(state, _storied_permanent())
    _permanent(state, Card(
        id="Bench Artifact 2", name="Bench Artifact 2", type_line="Artifact",
        mana_cost_string="{1}", converted_mana_cost=1,
    ))
    engine.rules.check_state_based_actions()
    assert p1.has_enduring_story is False


def test_sba_check_storied_is_a_one_time_flip():
    engine, state = _engine("p1")
    p1 = state.players[0]
    _permanent(state, _storied_permanent())
    for i in range(3):
        _permanent(state, Card(
            id=f"Bench Artifact 3-{i}", name=f"Bench Artifact 3-{i}", type_line="Artifact",
            mana_cost_string="{1}", converted_mana_cost=1,
        ))
    engine.rules.check_state_based_actions()
    assert p1.has_enduring_story is True
    assert engine.rules.check_state_based_actions() is False
    assert p1.has_enduring_story is True


# ---------------------------------------------------------------------------
# static_conditions.py: has_enduring_story
# ---------------------------------------------------------------------------


def test_condition_has_enduring_story():
    engine, state = _engine("p1", "p2")
    state.players[0].has_enduring_story = True
    assert static_conditions.condition_holds({"kind": "has_enduring_story"}, state, controller_id="p1") is True
    assert static_conditions.condition_holds({"kind": "has_enduring_story"}, state, controller_id="p2") is False


# ---------------------------------------------------------------------------
# Parser recognition
# ---------------------------------------------------------------------------


def test_static_condition_recognizes_enduring_story_phrase():
    assert static_condition("you have an enduring story") == {"kind": "has_enduring_story"}


def test_trailing_as_long_as_enduring_story_self_anthem():
    specs = static_effect_specs("~ gets +1/+0 as long as you have an enduring story.")
    assert specs is not None
    assert specs[0].type == "anthem"
    assert specs[0].params["active_if"] == {"kind": "has_enduring_story"}


# ---------------------------------------------------------------------------
# normalize.py: comma-less "<Name> the <Epithet>" self-reference folding
# ---------------------------------------------------------------------------


def test_given_name_before_the_folds_to_self():
    assert normalize("Whenever Fíli attacks, draw a card.", "Fíli the Pathfinder") == (
        "whenever ~ attacks, draw a card."
    )


def test_common_word_sharing_a_the_titles_spelling_is_not_folded():
    # "turn" inside "until end of turn" must survive "Turn the Tide" — the
    # word is never printed capitalized mid-sentence, unlike a genuine
    # self-reference.
    assert normalize("Creatures your opponents control get -2/-0 until end of turn.", "Turn the Tide") == (
        "creatures your opponents control get -2/-0 until end of turn."
    )
    assert normalize("Jump-start", "Start the TARDIS", keywords=["Jump-start"]) == "jump-start"


def test_different_title_sharing_a_the_prefix_is_not_folded():
    # By the time this fold runs, the card's own full name is already gone
    # (folded by the primary pass) — a *surviving* "<prefix> the <word>" is
    # always someone else's title (a differently-named token here), not a
    # second mention of the card itself.
    assert normalize(
        "When Tuktuk the Explorer dies, create Tuktuk the Returned, a token.",
        "Tuktuk the Explorer",
    ) == "when ~ dies, create tuktuk the returned, a token."


# ---------------------------------------------------------------------------
# End-to-end: real cached cards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Dáin, Lord of the Iron Hills", "Ori, Keeper of Songs", "Fíli the Pathfinder", "Óin the Brave"])
def test_storied_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed
