"""PAR-292 M27: the source together with other objects shuffled into / put on top of *their owners'* libraries
(RULE 400.3: each object to its own owner's library; RULE 701.24a: each affected library shuffled once; RULE 400.7: a
source that already left is not moved again)."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.deck_batch import RICH, activate, card, cast, filler, game
from tests.test_mec118_opponent_choice import _db_card

CARDS = ["Void Stalker", "Gomazoa", "Vortex Elemental", "Serene Remembrance", "Floodpits Drowner", "Elixir of Immortality"]


@pytest.fixture
def shuffles(monkeypatch):
    """The ids of the players whose library was shuffled, in order."""
    from mtg_analyzer.models.game.player import Player
    seen: list[str] = []
    real = Player.shuffle_library
    monkeypatch.setattr(Player, "shuffle_library", lambda self: (seen.append(self.id), real(self))[1])
    return seen


def _block(eng, pairs):
    """Attack with the first listed attackers, then declare the blocks (a real combat, RULE 506-509)."""
    state = eng.state
    while state.current_step != "declare_attackers":
        eng.advance_step()
    defender = eng.legal_defenders_for(state.active_player)[0]
    eng.declare_attackers(state.active_player, [{"attacker": a, "defender": defender} for a in pairs["attackers"]])
    eng.advance_step()
    eng.declare_blockers(state.player_by_id("p2"), [{"blocker": b, "attacker": a} for b, a in pairs["blocks"]])


@pytest.mark.parametrize("name", CARDS)
def test_real_cards_are_modeled(name):
    result = parse_oracle(_db_card(name))
    assert result.modeled, result.unclaimed


def test_void_stalker_sends_each_creature_to_its_owners_library_and_shuffles_each_once(shuffles):
    eng = game(library=4)
    stalker = card(eng, "Void Stalker")
    mine = filler(eng, "Mine", player="p1", power=1, toughness=1)
    theirs = filler(eng, "Theirs", player="p2", power=1, toughness=1)
    eng.state.player_by_id("p1").mana_pool.add_many(RICH)
    activate(eng, stalker, 0, targets=[theirs])
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    assert stalker in p1.library and theirs in p2.library and mine in eng.state.battlefield
    assert stalker.zone == Zone.LIBRARY and theirs.zone == Zone.LIBRARY
    assert sorted(shuffles) == ["p1", "p2"]


def test_a_stolen_creature_goes_to_its_owner_not_its_controller():
    eng = game(library=4)
    stalker = card(eng, "Void Stalker")
    stolen = filler(eng, "Stolen", player="p1", power=1, toughness=1)
    stolen.owner_id = "p2"
    eng.state.player_by_id("p1").mana_pool.add_many(RICH)
    activate(eng, stalker, 0, targets=[stolen])
    assert stolen in eng.state.player_by_id("p2").library and stolen not in eng.state.player_by_id("p1").library


def test_two_objects_with_one_owner_shuffle_that_library_once(shuffles):
    eng = game(library=4)
    stalker = card(eng, "Void Stalker")
    mine = filler(eng, "Mine", player="p1", power=1, toughness=1)
    eng.state.player_by_id("p1").mana_pool.add_many(RICH)
    activate(eng, stalker, 0, targets=[mine])
    assert shuffles == ["p1"]
    assert stalker in eng.state.player_by_id("p1").library and mine in eng.state.player_by_id("p1").library


def test_a_source_that_left_before_resolution_is_not_dragged_back():
    from mtg_analyzer.game.effects.returns_graveyards import ReturnToLibraryEffect
    eng = game(library=4)
    stalker = card(eng, "Void Stalker")
    victim = filler(eng, "Victim", player="p2", power=1, toughness=1)
    eng.rules.destroy(stalker)
    assert stalker.zone == Zone.GRAVEYARD
    eff = ReturnToLibraryEffect(source=stalker, target_kind="creature", position="shuffle", with_source=True)
    from mtg_analyzer.game.effects.core import GameContext
    eff.apply(GameContext(eng.state, eng.rules), [victim])
    assert stalker.zone == Zone.GRAVEYARD and victim in eng.state.player_by_id("p2").library


def test_gomazoa_takes_the_creature_it_blocks_with_it(shuffles):
    eng = game(library=4)
    attacker = filler(eng, "Attacker", player="p1", power=2, toughness=2)
    bystander = filler(eng, "Bystander", player="p1", power=2, toughness=2)
    gomazoa = card(eng, "Gomazoa", player="p2")
    state = eng.state
    _block(eng, {"attackers": [attacker], "blocks": [(gomazoa, attacker)]})
    activate(eng, gomazoa, 0, player="p2")
    assert gomazoa in state.player_by_id("p2").library and attacker in state.player_by_id("p1").library
    assert bystander in state.battlefield
    assert sorted(shuffles) == ["p1", "p2"]


def test_vortex_elemental_takes_blockers_and_blocked_creatures():
    eng = game(library=4)
    attacker = filler(eng, "Attacker", player="p1", power=2, toughness=2)
    vortex = card(eng, "Vortex Elemental", player="p1")
    other = filler(eng, "Other", player="p2", power=2, toughness=2)
    blocker = filler(eng, "Blocker", player="p2", power=2, toughness=2)
    state = eng.state
    _block(eng, {"attackers": [vortex, attacker], "blocks": [(blocker, vortex)]})
    state.player_by_id("p1").mana_pool.add_many(RICH)
    activate(eng, vortex, 0)
    assert vortex.zone == Zone.LIBRARY and blocker in state.player_by_id("p2").library
    assert attacker in state.battlefield and other in state.battlefield


def test_serene_remembrance_shuffles_itself_and_up_to_three_cards_of_one_graveyard(shuffles):
    eng = game(library=4)
    p2 = eng.state.player_by_id("p2")
    dead = [filler(eng, f"Dead{i}", player="p2", zone=Zone.GRAVEYARD) for i in range(3)]
    spell = card(eng, "Serene Remembrance", zone=Zone.HAND)
    cast(eng, spell, targets=dead)
    assert all(d in p2.library and d not in p2.graveyard for d in dead)
    assert spell in eng.state.player_by_id("p1").library
    assert sorted(shuffles) == ["p1", "p2"]


def test_serene_remembrance_with_no_targets_still_shuffles_itself():
    eng = game(library=4)
    spell = card(eng, "Serene Remembrance", zone=Zone.HAND)
    cast(eng, spell, targets=[])
    assert spell in eng.state.player_by_id("p1").library


def test_serene_remembrance_picks_must_share_a_graveyard():
    eng = game(library=4)
    a = filler(eng, "A", player="p1", zone=Zone.GRAVEYARD)
    b = filler(eng, "B", player="p2", zone=Zone.GRAVEYARD)
    spell = card(eng, "Serene Remembrance", zone=Zone.HAND)
    with pytest.raises(Exception):
        cast(eng, spell, targets=[a, b])


@pytest.mark.parametrize("text", [
    "shuffle ~ and each creature you control into their owners' libraries",
    "put ~ and target creature into their owners' libraries",
    "shuffle ~ and target land into their owners' libraries",
])
def test_unrelated_shapes_are_refused(text):
    assert parse_effect_body(text) is None


def test_elixir_of_immortality_shuffles_itself_and_the_graveyard_into_their_library(shuffles):
    eng = game(library=2)
    elixir = card(eng, "Elixir of Immortality")
    dead = [filler(eng, f"Dead{i}", player="p1", zone=Zone.GRAVEYARD) for i in range(2)]
    theirs = filler(eng, "TheirDead", player="p2", zone=Zone.GRAVEYARD)
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many(RICH)
    activate(eng, elixir, 0)
    assert elixir in p1.library and all(d in p1.library for d in dead) and not p1.graveyard
    assert theirs in eng.state.player_by_id("p2").graveyard          # only the controller's graveyard
    assert p1.life == 25
    assert shuffles == ["p1"]                                         # one library, one shuffle


def test_elixir_of_immortality_goes_to_its_own_owners_library_when_stolen(shuffles):
    eng = game(library=2)
    elixir = card(eng, "Elixir of Immortality")
    elixir.owner_id = "p2"
    eng.state.player_by_id("p1").mana_pool.add_many(RICH)
    activate(eng, elixir, 0)
    assert elixir in eng.state.player_by_id("p2").library and sorted(shuffles) == ["p1", "p2"]


def test_floodpits_drowner_needs_a_stunned_target_and_takes_itself_with_it(shuffles):
    eng = game(library=4)
    drowner = card(eng, "Floodpits Drowner")
    stunned = filler(eng, "Stunned", player="p2", power=1, toughness=1)
    stunned.counters["stun"] = 1
    eng.state.player_by_id("p1").mana_pool.add_many(RICH)
    activate(eng, drowner, 0, targets=[stunned])
    assert drowner in eng.state.player_by_id("p1").library and stunned in eng.state.player_by_id("p2").library
    assert sorted(shuffles) == ["p1", "p2"]


def test_floodpits_drowner_rejects_a_creature_without_a_stun_counter():
    eng = game(library=4)
    drowner = card(eng, "Floodpits Drowner")
    plain = filler(eng, "Plain", player="p2", power=1, toughness=1)
    eng.state.player_by_id("p1").mana_pool.add_many(RICH)
    with pytest.raises(Exception):
        activate(eng, drowner, 0, targets=[plain])


# --- choosing graveyard cards to shuffle in: the quantity and the who axes ---------------------------------------

def _pick_all(eng, limit=20):
    """Take the first option of every pending choice until none is left (a graveyard pick offers one card at a time)."""
    for _ in range(limit):
        choice = eng.state.pending_choice
        if choice is None:
            return
        options = choice.get("options") or []
        eng.resolve_pending_choice(str(options[0]["id"]) if options else "done")


@pytest.mark.parametrize("name", ["Loaming Shaman", "Stream of Thought", "Witness the Future"])
def test_graveyard_shuffle_cards_are_modeled(name):
    result = parse_oracle(_db_card(name))
    assert result.modeled, result.unclaimed


def test_loaming_shaman_lets_the_controller_shuffle_any_number_of_the_targets_cards_in_once(shuffles):
    eng = game(library=2)
    dead = [filler(eng, f"Dead{i}", player="p2", zone=Zone.GRAVEYARD) for i in range(5)]
    from tests.support.deck_batch import put_on_battlefield
    shaman = put_on_battlefield(eng, "Loaming Shaman")
    # the ETB trigger targets a player; pick the opponent
    from tests.support.deck_batch import answer
    answer(eng, lambda c: next((str(o["id"]) for o in c.get("options") or [] if "p2" in str(o.get("id")) or "Player 2" in str(o.get("label"))), None))
    _pick_all(eng)
    p2 = eng.state.player_by_id("p2")
    assert not p2.graveyard and all(d in p2.library for d in dead)
    assert shuffles == ["p2"]


def test_stream_of_thought_shuffles_up_to_four_of_your_own_graveyard_with_one_shuffle(shuffles):
    eng = game(library=6)
    own = [filler(eng, f"Own{i}", player="p1", zone=Zone.GRAVEYARD) for i in range(6)]
    spell = card(eng, "Stream of Thought", zone=Zone.HAND)
    cast(eng, spell, targets=[eng.state.player_by_id("p2")])
    _pick_all(eng)
    p1 = eng.state.player_by_id("p1")
    moved = [o for o in own if o in p1.library]
    assert len(moved) == 4                                            # "up to 4", never more
    assert shuffles == ["p1"]                                         # one shuffle for the four cards


def test_stream_of_thought_with_an_empty_graveyard_does_nothing(shuffles):
    eng = game(library=6)
    spell = card(eng, "Stream of Thought", zone=Zone.HAND)
    cast(eng, spell, targets=[eng.state.player_by_id("p2")])
    _pick_all(eng)
    assert shuffles == []


def test_witness_the_future_shuffles_then_looks_at_the_top_four():
    eng = game(library=8)
    dead = filler(eng, "Dead", player="p2", zone=Zone.GRAVEYARD)
    spell = card(eng, "Witness the Future", zone=Zone.HAND)
    cast(eng, spell, targets=[eng.state.player_by_id("p2")])
    _pick_all(eng)
    assert dead in eng.state.player_by_id("p2").library
    assert len(eng.state.player_by_id("p1").hand) == 1                # one of the four taken into the hand


@pytest.mark.parametrize("text", [
    "you shuffle up to 4 target cards from your graveyard into your library and draw a card",
    "target player shuffles any number of cards from their graveyard into their library",
    "each player shuffles up to 4 cards from their graveyard into their library",
])
def test_graveyard_shuffle_neighbours_are_refused(text):
    assert parse_effect_body(text) is None
