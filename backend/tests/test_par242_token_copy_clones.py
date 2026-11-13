"""PAR-242 -- Progenitor Mimic / Sphinx of False Conclusions: the RULE 603.4 "if ~ isn't a token" token-copy triggers."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.parser.oracle import parse_oracle

from tests.support.game import creature, make_engine, obj_on_battlefield
from tests.test_enter_as_copy_family import _cast, _named


def _prepare(name, mana, two_players=False):
    card = _named(name)
    eng = make_engine([card], [] if two_players else None, hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many(mana)
    obj = p1.hand[0]
    bind_from_catalogue(obj)
    return eng, p1, obj


def _mimic_copying(victim_name="Grizzly Bears", two_players=False):
    eng, p1, mimic = _prepare("Progenitor Mimic", mana={"U": 4, "G": 4, "C": 6}, two_players=two_players)
    original = obj_on_battlefield(eng.state, eng, creature(name=victim_name, cost="{1}{G}"))
    bind_from_catalogue(original)
    _cast(eng, p1, mimic)
    opt = next(o for o in eng.state.pending_choice["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])
    return eng, p1, mimic


def _creatures_named(eng, name):
    return [o for o in eng.state.battlefield if o.name == name]


def _upkeep(eng, p1):
    """Begin ``p1``'s upkeep: fire STEP_BEGIN, stack the triggers, resolve them (RULE 503.1)."""
    from mtg_analyzer.models.game.events import EventType, GameEvent

    eng.state.active_player_index = eng.state.players.index(p1)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    eng.resolve_until_stable()


@pytest.mark.parametrize("name", [
    "Progenitor Mimic", "Sphinx of False Conclusions", "Gigantoplasm", "Callidus Assassin", "Mocking Doppelganger",
])
def test_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


def test_mimic_makes_one_token_copy_each_upkeep_and_the_token_makes_none():
    eng, p1, mimic = _mimic_copying()
    assert mimic.card.name == "Grizzly Bears"
    assert len(mimic.triggered_abilities) == 1
    mimic.summoning_sick = False
    _upkeep(eng, p1)
    bears = _creatures_named(eng, "Grizzly Bears")
    tokens = [o for o in bears if o.is_token and o.controller_id == p1.id]
    assert len(tokens) == 1
    # The token copy has the ability (RULE 707.9a) but, being a token, never makes another.
    assert len(tokens[0].triggered_abilities) == 1
    _upkeep(eng, p1)
    tokens = [o for o in _creatures_named(eng, "Grizzly Bears") if o.is_token]
    assert len(tokens) == 2  # exactly one more, made by the nontoken Mimic only


def test_mimic_token_alone_creates_nothing():
    eng, p1, mimic = _mimic_copying()
    mimic.summoning_sick = False
    _upkeep(eng, p1)
    token = next(o for o in _creatures_named(eng, "Grizzly Bears") if o.is_token)
    eng.state.battlefield.remove(mimic)  # only the token (with the ability) remains
    before = len(_creatures_named(eng, "Grizzly Bears"))
    _upkeep(eng, p1)
    assert len(_creatures_named(eng, "Grizzly Bears")) == before
    assert token in eng.state.battlefield


def test_mimic_does_nothing_on_an_opponents_upkeep():
    eng, p1, mimic = _mimic_copying(two_players=True)
    mimic.summoning_sick = False
    opponent = next(p for p in eng.state.players if p is not p1)
    _upkeep(eng, opponent)
    assert not [o for o in _creatures_named(eng, "Grizzly Bears") if o.is_token]


def _put_sphinx(eng, p1, token):
    from tests.support.game import obj_on_battlefield as put
    sphinx = put(eng.state, eng, _named("Sphinx of False Conclusions"), controller=p1.id)
    bind_from_catalogue(sphinx)
    sphinx.is_token = token
    return sphinx


def test_sphinx_dying_nontoken_leaves_a_token_copy():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    sphinx = _put_sphinx(eng, p1, token=False)
    eng.rules.destroy(sphinx)
    eng.resolve_until_stable()
    copies = [o for o in eng.state.battlefield if o.name == "Sphinx of False Conclusions"]
    assert len(copies) == 1 and copies[0].is_token


def test_sphinx_token_dying_leaves_nothing():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    sphinx = _put_sphinx(eng, p1, token=True)
    eng.rules.destroy(sphinx)
    eng.resolve_until_stable()
    assert not [o for o in eng.state.battlefield if o.name == "Sphinx of False Conclusions"]


# ---------------------------------------------------------------------------
# Callidus Assassin -- enter tapped as a copy, ETB "destroy up to one other target creature with the same name"
# ---------------------------------------------------------------------------


def _callidus_enter(board_names, accept=True):
    eng, p1, callidus = _prepare("Callidus Assassin", mana={"U": 4, "B": 4, "G": 4, "C": 6})
    board = []
    for name in board_names:
        obj = obj_on_battlefield(eng.state, eng, creature(name=name, cost="{1}{G}"))
        bind_from_catalogue(obj)
        board.append(obj)
    _cast(eng, p1, callidus)
    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "enter_as_copy"
    if accept:
        opt = next(o for o in pending["options"] if o.get("label") == board_names[0])
        eng.resolve_pending_choice(opt["id"])
    else:
        eng.resolve_pending_choice("decline")
    return eng, p1, callidus, board


def _trigger_options(eng):
    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "trigger_target"
    return pending["options"]


def test_callidus_enters_tapped_and_only_same_named_others_are_legal_picks():
    eng, p1, callidus, board = _callidus_enter(["Grizzly Bears", "Grizzly Bears", "Hill Giant"])
    assert callidus.card.name == "Grizzly Bears"
    assert callidus.tapped is True
    ids = {o.get("instance_id") for o in _trigger_options(eng)} - {None}  # the "decline" option has no object
    assert ids == {board[0].instance_id, board[1].instance_id}  # not Hill Giant, not the Callidus copy itself


def test_callidus_destroys_the_chosen_same_named_creature_only():
    eng, p1, callidus, board = _callidus_enter(["Grizzly Bears", "Grizzly Bears", "Hill Giant"])
    eng.resolve_pending_choice(str(board[1].instance_id))
    eng.resolve_until_stable()
    assert board[1] not in eng.state.battlefield
    assert board[0] in eng.state.battlefield and board[2] in eng.state.battlefield
    assert callidus in eng.state.battlefield


def test_callidus_may_choose_no_target():
    eng, p1, callidus, board = _callidus_enter(["Grizzly Bears", "Grizzly Bears"])
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert all(o in eng.state.battlefield for o in board)


def test_callidus_copy_of_a_unique_name_has_nothing_to_destroy():
    eng, p1, callidus, board = _callidus_enter(["Grizzly Bears", "Hill Giant"])
    eng.resolve_until_stable()
    assert all(o in eng.state.battlefield for o in board)
    assert callidus in eng.state.battlefield


def test_declining_the_copy_enters_untapped_as_itself_with_no_trigger():
    eng, p1, callidus, board = _callidus_enter(["Grizzly Bears", "Grizzly Bears"], accept=False)
    eng.resolve_until_stable()
    assert callidus.card.name == "Callidus Assassin"
    assert callidus.tapped is False
    assert not eng.state.pending_choice
    assert all(o in eng.state.battlefield for o in board)


# ---------------------------------------------------------------------------
# Mocking Doppelganger -- "other creatures with the same name as ~ are goaded"
# ---------------------------------------------------------------------------


def _doppelganger_copying(opponent_board):
    from mtg_analyzer.game import continuous

    eng, p1, doppel = _prepare("Mocking Doppelganger", mana={"U": 4, "C": 6}, two_players=True)
    p2 = next(p for p in eng.state.players if p is not p1)
    board = []
    for name in opponent_board:
        obj = obj_on_battlefield(eng.state, eng, creature(name=name, cost="{1}{G}"), controller=p2.id)
        bind_from_catalogue(obj)
        board.append(obj)
    _cast(eng, p1, doppel)
    pending = eng.state.pending_choice
    opt = next(o for o in pending["options"] if o.get("label") == opponent_board[0])
    eng.resolve_pending_choice(opt["id"])
    continuous.recompute(eng.state)
    return eng, p1, p2, doppel, board


def test_doppelganger_goads_other_same_named_creatures_for_its_controller():
    from mtg_analyzer.game.combat import goaders

    eng, p1, p2, doppel, board = _doppelganger_copying(["Grizzly Bears", "Grizzly Bears", "Hill Giant"])
    assert doppel.card.name == "Grizzly Bears"
    assert goaders(board[0]) == {p1.id} and goaders(board[1]) == {p1.id}  # goaded by the Doppelganger's controller
    assert not goaders(board[2])  # another name is untouched
    assert not goaders(doppel)  # "other": the Doppelganger itself is not goaded


def test_doppelganger_goad_ends_when_it_leaves_the_battlefield():
    from mtg_analyzer.game import continuous
    from mtg_analyzer.game.combat import goaders

    eng, p1, p2, doppel, board = _doppelganger_copying(["Grizzly Bears", "Grizzly Bears"])
    assert goaders(board[0])
    eng.rules.put_into_graveyard(doppel)
    continuous.recompute(eng.state)
    assert not goaders(board[0]) and not goaders(board[1])


# ---------------------------------------------------------------------------
# Gigantoplasm -- granted "{X}: ~ has base power and toughness X/X." (RULE 613.4b, lasting per RULE 611.2a)
# ---------------------------------------------------------------------------


def _gigantoplasm_copying():
    eng, p1, giga = _prepare("Gigantoplasm", mana={"U": 4, "G": 4, "C": 6})
    original = obj_on_battlefield(eng.state, eng, creature(name="Grizzly Bears", cost="{1}{G}", power=2, toughness=2))
    bind_from_catalogue(original)
    _cast(eng, p1, giga)
    opt = next(o for o in eng.state.pending_choice["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])
    giga.summoning_sick = False
    eng.state.current_step = "main1"
    return eng, p1, giga


def _activate_x(eng, p1, giga, x):
    p1.mana_pool.add_many({"C": x})
    eng.activate_ability(p1, giga, 0, x=x)
    eng.resolve_until_stable()


def test_gigantoplasm_sets_base_pt_to_x_and_keeps_it_past_end_of_turn():
    eng, p1, giga = _gigantoplasm_copying()
    assert giga.card.name == "Grizzly Bears" and (giga.power, giga.toughness) == (2, 2)
    _activate_x(eng, p1, giga, 5)
    eng.recompute_continuous_effects()
    assert (giga.power, giga.toughness) == (5, 5)
    # No duration is stated, so the effect lasts for the rest of the game (RULE 611.2a), not until end of turn.
    eng._step_cleanup()  # RULE 514.2: "until end of turn" effects would end here
    eng.recompute_continuous_effects()
    assert (giga.power, giga.toughness) == (5, 5)


def test_gigantoplasm_latest_activation_wins_by_timestamp():
    eng, p1, giga = _gigantoplasm_copying()
    _activate_x(eng, p1, giga, 5)
    _activate_x(eng, p1, giga, 3)
    eng.recompute_continuous_effects()
    assert (giga.power, giga.toughness) == (3, 3)  # RULE 613.7b: the newer base-P/T effect applies last


def test_gigantoplasm_counters_still_apply_on_top_of_the_set_base():
    eng, p1, giga = _gigantoplasm_copying()
    _activate_x(eng, p1, giga, 4)
    eng.rules.add_counters(giga, 2, kind="+1/+1")
    eng.recompute_continuous_effects()
    assert (giga.power, giga.toughness) == (6, 6)  # RULE 613.4c counters follow layer 7b


def test_gigantoplasm_x_set_effect_does_not_reach_another_creature():
    eng, p1, giga = _gigantoplasm_copying()
    other = obj_on_battlefield(eng.state, eng, creature(name="Grizzly Bears", cost="{1}{G}", power=2, toughness=2))
    _activate_x(eng, p1, giga, 7)
    eng.recompute_continuous_effects()
    assert (other.power, other.toughness) == (2, 2)


def test_gigantoplasm_effect_is_not_inherited_by_a_new_object_of_the_same_card():
    # RULE 400.7: after it dies and returns, the card is a new object and the old X/X no longer applies.
    eng, p1, giga = _gigantoplasm_copying()
    _activate_x(eng, p1, giga, 6)
    eng.recompute_continuous_effects()
    assert (giga.power, giga.toughness) == (6, 6)
    eng.rules.put_into_graveyard(giga)
    eng.state.add_to_battlefield(giga)  # the same card object re-enters as a new object (zone_incarnation advances)
    eng.recompute_continuous_effects()
    assert (giga.power, giga.toughness) != (6, 6)


# ---------------------------------------------------------------------------
# Vesuva (newly claimed by the `enter tapped as a copy` wording) -- a land play, not a cast
# ---------------------------------------------------------------------------


def _vesuva_play(accept):
    from tests.support.game import land

    eng = make_engine([_named("Vesuva")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    forest = obj_on_battlefield(eng.state, eng, land("Forest"))
    vesuva = p1.hand[0]
    bind_from_catalogue(vesuva)
    eng.play_land(p1, vesuva)
    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "enter_as_copy"
    if accept:
        eng.resolve_pending_choice(next(o["id"] for o in pending["options"] if o.get("label") == "Forest"))
    else:
        eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    return eng, vesuva, forest


def test_vesuva_enters_tapped_as_a_copy_of_an_untapped_basic():
    eng, vesuva, forest = _vesuva_play(accept=True)
    assert vesuva in eng.state.battlefield
    assert vesuva.card.name == "Forest"
    assert vesuva.tapped is True  # a copied basic Forest would enter untapped; the replacement taps it (RULE 614.12)


def test_vesuva_declining_the_copy_enters_untapped_as_itself():
    eng, vesuva, forest = _vesuva_play(accept=False)
    assert vesuva.card.name == "Vesuva"
    assert vesuva.tapped is False


# ---------------------------------------------------------------------------
# "other/another target creature [with <quality>]" -- the object-phrase widening also claims these cards
# ---------------------------------------------------------------------------


def test_flensing_raptor_trigger_never_offers_itself_even_though_it_has_toxic():
    card = _named("Flensing Raptor")
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    toxic = obj_on_battlefield(eng.state, eng, card)  # a real second Raptor: toxic is a parametric keyword (bound)
    bind_from_catalogue(toxic)
    plain = obj_on_battlefield(eng.state, eng, creature(name="Plain Bear"))
    raptor = p1.hand[0]
    bind_from_catalogue(raptor)
    eng.recompute_continuous_effects()
    p1.mana_pool.add_many({"W": 3, "C": 6, "U": 3, "B": 3, "R": 3, "G": 3})
    _cast(eng, p1, raptor)
    pending = eng.state.pending_choice
    if pending:
        ids = {o.get("instance_id") for o in pending["options"]} - {None}
        assert ids == {toxic.instance_id}  # not itself (RULE 109.1 "another"), not a creature without toxic
        eng.resolve_pending_choice(str(toxic.instance_id))
        eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert toxic.power == 3 and plain.power == 2 and raptor.power == 2  # only the chosen toxic creature is pumped


def test_ioreth_untaps_two_other_legendary_creatures_and_never_a_non_legendary_one():
    herald_card = _named("Ioreth of the Healing House")
    eng = make_engine([herald_card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    ioreth = obj_on_battlefield(eng.state, eng, herald_card)
    bind_from_catalogue(ioreth)
    ioreth.summoning_sick = False
    legends = []
    for name in ("Legend A", "Legend B"):
        obj = obj_on_battlefield(
            eng.state, eng, creature(name=name, type_line="Legendary Creature — Human", is_legendary=True))
        obj.tapped = True
        legends.append(obj)
    plain = obj_on_battlefield(eng.state, eng, creature(name="Plain Bear"))
    plain.tapped = True
    eng.recompute_continuous_effects()
    assert len(ioreth.activated_abilities) == 2
    eng.activate_ability(p1, ioreth, 1, targets=legends)
    eng.resolve_until_stable()
    assert all(not o.tapped for o in legends)
    assert plain.tapped  # not legendary: never a legal pick for the legendary-only ability
    # The source is excluded ("other"): it is not offered even though it is itself legendary.
    ioreth.tapped = False
    legends[0].tapped = True
    ioreth.summoning_sick = False
    try:
        eng.activate_ability(p1, ioreth, 1, targets=[ioreth, legends[0]])
    except ValueError:
        pass
    assert legends[0].tapped
