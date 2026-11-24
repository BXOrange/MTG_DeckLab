"""PAR-319: non-combat edicts of their choice.

"That player / each opponent / each player / target player sacrifices `<any permanent phrase>` of their choice" on
non-combat heads (upkeep edicts, enters, attack, spells). Each affected player chooses among their *own* permanents
(RULE 701.17a); with several players the choices are made in APNAP order (RULE 101.4); a player with no eligible
permanent is skipped. Every engine case runs three players whose boards differ.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.phases import GamePhase, GameStep
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.bots import create_bot
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
from mtg_analyzer.services.game_session import GameSessionManager

GAINED = (
    "Braids, Cabal Minion", "Call to the Grave", "Defiler of Souls", "Destructive Flow", "Anowon, the Ruin Sage",
    "Demon's Disciple", "Celestial Flare", "Sheoldred's Edict", "Dystopia", "Plaguecrafter", "Vraska's Fall",
)


def _real(name):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _card(name, type_line="Creature — Test", oracle="", **kw):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, **kw)


def _put(eng, card, controller):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _creature(eng, name, controller, **kw):
    return _put(eng, _card(name, is_creature=True, power=2, toughness=2, **kw), controller)


def _three(active="p1"):
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_life=20, starting_hand=0)
    eng.state.active_player_index = next(i for i, p in enumerate(eng.state.players) if p.id == active)
    eng.state.current_step = "main1"
    return eng


def _ids(choice):
    return {o["instance_id"] for o in choice["options"] if "instance_id" in o}


def _answer(eng, obj):
    eng.resolve_pending_choice(str(obj.instance_id))
    eng.resolve_until_stable()


# -- parser -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", GAINED)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True


@pytest.mark.parametrize("clause, what, flt", [
    ("each opponent sacrifices a creature or planeswalker of their choice", "permanent",
     {"card_type_any": ["creature", "planeswalker"]}),
    ("each player sacrifices a non-vampire creature of their choice", "permanent",
     {"without_subtype": "vampire", "card_type": "creature"}),
    ("each opponent sacrifices a nonland permanent of their choice", "permanent", {"without_card_type": "land"}),
    ("target player sacrifices an attacking creature of their choice", "permanent",
     {"attacking": True, "card_type": "creature"}),
    ("target player sacrifices an attacking or blocking creature of their choice", "permanent",
     {"attacking_or_blocking": True, "card_type": "creature"}),
    ("each opponent sacrifices a nontoken artifact of their choice", "nontoken_artifact", None),
    ("each player sacrifices 2 creatures or artifacts of their choice", "permanent",
     {"card_type_any": ["creature", "artifact"]}),
])
def test_edict_pool_phrases_parse_to_what_and_filter(clause, what, flt):
    card = _card("Zed", type_line="Sorcery", is_sorcery=True, oracle=f"{clause[0].upper()}{clause[1:]}.")
    result = parse_oracle(card)
    if what is None:
        assert not result.modeled
        return
    params = result.specs[0].effects[0].params
    assert params["what"] == what and params.get("object_filter") == flt


@pytest.mark.parametrize("text", [
    "Each opponent sacrifices a creature you control of their choice.",   # a controller tail names another pool
    "Each opponent sacrifices a creature with flying of their choice.",  # still the `with <quality>` slot's grammar
    "Each opponent sacrifices a snorkeling creature of their choice.",   # unknown adjective: fail closed
])
def test_pools_outside_the_vocabulary_do_not_claim_the_plain_row(text):
    result = parse_oracle(_card("Zed", type_line="Sorcery", is_sorcery=True, oracle=text))
    for spec in result.specs:
        for eff in spec.effects:
            assert not (eff.type == "sacrifice" and eff.params.get("what") == "permanent" and "snorkeling" in text)


def test_upkeep_that_player_is_the_active_player_in_the_spec():
    card = _real("Call to the Grave")
    effect = [e for s in parse_oracle(card).specs for e in s.effects if e.type == "trigger_subject_referent"][0]
    assert effect.params["referent"] == "active_player"


def test_monocolored_is_exactly_one_colour():
    card = _card("Zed", type_line="Sorcery", is_sorcery=True, oracle="Target player sacrifices a monocolored creature of their choice.")
    assert parse_oracle(card).specs[0].effects[0].params["object_filter"] == {"color_count": 1, "card_type": "creature"}


# -- each opponent: everyone picks their own, in APNAP order ----------------------------------------------------------


def test_each_opponent_chooses_their_own_objects_in_apnap_order_and_none_picks_for_another():
    # p2's turn, p1 controls the edict: opponents p3 (next after p2) and p2; p1 never chooses.
    eng = _three(active="p2")
    mine = _creature(eng, "Mine", "p1")
    p2 = [_creature(eng, f"P2-{i}", "p2") for i in range(2)]
    p3 = [_creature(eng, f"P3-{i}", "p3") for i in range(2)]
    p3_wall = _put(eng, _card("Wall", type_line="Artifact"), "p3")
    spell = _card("Edict", type_line="Sorcery", is_sorcery=True,
                  oracle="Each opponent sacrifices a creature or planeswalker of their choice.")
    assert parse_oracle(spell).modeled
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.player_by_id("p1").hand.append(obj)
    _resolve_spell(eng, obj)
    first = eng.state.pending_choice
    assert first["player_id"] == "p2"  # APNAP: the active player's choice comes first
    assert _ids(first) == {o.instance_id for o in p2}
    _answer(eng, p2[1])
    second = eng.state.pending_choice
    assert second["player_id"] == "p3"
    assert p2[1].zone is Zone.BATTLEFIELD  # RULE 101.4: nothing leaves until every player has chosen
    assert _ids(second) == {o.instance_id for o in p3}  # the artifact is not a creature or planeswalker
    _answer(eng, p3[0])
    assert eng.state.pending_choice is None
    assert (p2[1].zone, p3[0].zone) == (Zone.GRAVEYARD, Zone.GRAVEYARD)
    assert p2[0].zone is p3[1].zone is mine.zone is p3_wall.zone is Zone.BATTLEFIELD


def _resolve_spell(eng, obj):
    """Resolve a sorcery's effects as the ability's controller (no mana needed for the rules under test)."""
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.game.binding.core import build_effects

    specs = [e for s in parse_oracle(obj.card).specs for e in s.effects]
    obj.zone = Zone.STACK
    for effect in build_effects(specs, obj):
        effect.apply(GameContext(eng.state, eng.rules))
    eng.resolve_until_stable()


def test_a_player_with_no_eligible_object_is_skipped_and_the_rest_still_choose():
    eng = _three()
    p2 = [_creature(eng, f"P2-{i}", "p2") for i in range(2)]
    _put(eng, _card("Wall", type_line="Artifact"), "p3")  # p3 has no creature or planeswalker
    spell = _card("Edict", type_line="Sorcery", is_sorcery=True,
                  oracle="Each opponent sacrifices a creature or planeswalker of their choice.")
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    _resolve_spell(eng, obj)
    assert eng.state.pending_choice["player_id"] == "p2"
    _answer(eng, p2[0])
    assert eng.state.pending_choice is None  # p3 was skipped, nothing opened for them
    assert p2[0].zone is Zone.GRAVEYARD and p2[1].zone is Zone.BATTLEFIELD


def test_each_player_includes_the_controller_and_filters_non_matching_permanents():
    eng = _three()
    mine = [_creature(eng, f"Mine-{i}", "p1") for i in range(2)]
    vampire = _creature(eng, "Vamp", "p2", type_line="Creature — Vampire")
    spell = _card("Edict", type_line="Sorcery", is_sorcery=True,
                  oracle="Each player sacrifices a non-vampire creature of their choice.")
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    _resolve_spell(eng, obj)
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p1" and _ids(choice) == {o.instance_id for o in mine}
    _answer(eng, mine[0])
    assert eng.state.pending_choice is None  # p2's only creature is a Vampire: nothing eligible, p3 has none
    assert vampire.zone is Zone.BATTLEFIELD and mine[0].zone is Zone.GRAVEYARD


# -- upkeep: "that player" is the player whose upkeep it is -----------------------------------------------------------


def _upkeep(eng, active):
    eng.state.active_player_index = next(i for i, p in enumerate(eng.state.players) if p.id == active)
    eng._run_step(GamePhase("beginning", []), GameStep("upkeep", gives_priority=True))
    eng.resolve_until_stable()


def test_call_to_the_grave_upkeep_edict_names_the_active_player_with_a_filtered_pool():
    eng = _three()
    _put(eng, _real("Call to the Grave"), "p1")
    zombie = _creature(eng, "Zom", "p2", type_line="Creature — Zombie")
    bear2 = _creature(eng, "Bear2", "p2")
    bear2b = _creature(eng, "Bear2b", "p2")
    bear3 = _creature(eng, "Bear3", "p3")
    bear1 = _creature(eng, "Bear1", "p1")
    _upkeep(eng, "p2")  # p2's upkeep: p2 sacrifices, though p1 controls the enchantment
    choice = eng.state.pending_choice
    assert choice is not None and choice["player_id"] == "p2"
    assert _ids(choice) == {bear2.instance_id, bear2b.instance_id}  # the Zombie is not a legal pick
    _answer(eng, bear2)
    assert bear2.zone is Zone.GRAVEYARD
    assert zombie.zone is bear2b.zone is bear3.zone is bear1.zone is Zone.BATTLEFIELD


def test_destructive_flow_sacrifices_only_a_nonbasic_land_of_the_active_player():
    eng = _three()
    _put(eng, _real("Destructive Flow"), "p1")
    basic = _put(eng, _card("Forest", type_line="Basic Land — Forest", is_land=True), "p3")
    nonbasic = _put(eng, _card("Nook", type_line="Land", is_land=True), "p3")
    other = _put(eng, _card("Other Nook", type_line="Land", is_land=True), "p2")
    _upkeep(eng, "p3")
    assert eng.state.pending_choice is None or eng.state.pending_choice["player_id"] == "p3"
    assert nonbasic.zone is Zone.GRAVEYARD
    assert basic.zone is other.zone is Zone.BATTLEFIELD


def test_upkeep_edict_with_nothing_eligible_does_nothing():
    eng = _three()
    _put(eng, _real("Destructive Flow"), "p1")
    basic = _put(eng, _card("Forest", type_line="Basic Land — Forest", is_land=True), "p2")
    _upkeep(eng, "p2")
    assert eng.state.pending_choice is None and basic.zone is Zone.BATTLEFIELD


# -- a bot chooser answers from its own view --------------------------------------------------------------------------


def test_a_bot_answers_an_each_opponent_edict_from_its_own_view_and_legal_actions():
    land = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    session = GameSessionManager().create_multiplayer(
        [{"player_id": p, "name": p, "library": [land] * 30} for p in ("p1", "p2", "p3")],
        mulligan_style="none", keep_history=False,
    )
    for p in ("p1", "p2", "p3"):
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=p)
    eng = session.engine
    state = eng.state
    controller = state.active_player.id
    victim = "p3" if controller != "p3" else "p2"
    other = "p2" if victim == "p3" else "p3"
    a = _creature(eng, "A", victim)
    b = _creature(eng, "B", victim)
    _put(eng, _card("Wall", type_line="Artifact"), victim)
    elsewhere = _creature(eng, "Other", other)
    spell = _card("Edict", type_line="Sorcery", is_sorcery=True,
                  oracle="Target player sacrifices a creature or planeswalker of their choice.")
    assert parse_oracle(spell).modeled
    obj = GameObject(spell, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import GameContext
    specs = [e for s in parse_oracle(spell).specs for e in s.effects]
    obj.zone = Zone.STACK
    for effect in build_effects(specs, obj):
        effect.apply(GameContext(state, eng.rules), [state.player_by_id(victim)])
    choice = state.pending_choice
    assert choice["player_id"] == victim
    assert not [act for act in session.legal_actions(perspective=other) if act["type"] == "choose"]
    actions = session.legal_actions(perspective=victim)
    assert {act["instance_id"] for act in actions if act["type"] == "choose"} == {a.instance_id, b.instance_id}
    action = create_bot("greedy", victim).decide(session.view(perspective=victim), actions)
    assert action["type"] == "choose"
    session.apply_action(action, actor_id=victim)
    assert sorted(o.zone.value for o in (a, b)) == ["battlefield", "graveyard"]
    assert elsewhere.zone is Zone.BATTLEFIELD
