"""PAR-208: clause separators and outcome chains, executed against the real engine.

* RULE 608.2c "<action>. If you do, <effect>. Otherwise, <effect>." for a mandatory action (`seq` + ``if_you_do_from``
  + ``else_effects``), and the same ``else_effects`` on `optional` ("you may X. If you do, Y. If you don't, Z.")
* RULE 608.2h "that creature's power" after the ability's own sacrifice
* RULE 608.2c series "A, B, and C" sharing one subject
"""


from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

_DB = CardDatabase(DB_PATH)


def _card(name: str) -> Card:
    card = _DB.get_card(name)
    assert card is not None, name
    return card


def _engine() -> GameEngine:
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _board(eng: GameEngine, name: str, pid: str = "p1", *, bind: bool = True) -> GameObject:
    obj = GameObject(_card(name), owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.controller_id = pid
    obj.summoning_sick = False
    if bind:
        bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _make_card(name: str, type_line: str, power: int = 1, toughness: int = 1) -> Card:
    is_creature = "Creature" in type_line
    return Card(
        id=name, name=name, type_line=type_line, is_creature=is_creature, is_land="Land" in type_line,
        is_instant=type_line.startswith("Instant"), is_sorcery=type_line.startswith("Sorcery"),
        **({"power": power, "toughness": toughness} if is_creature else {}),
    )


def _plain(eng: GameEngine, name: str, pid: str = "p1", power: int = 2, toughness: int = 2,
           type_line: str = "Creature — Bear") -> GameObject:
    obj = GameObject(_make_card(name, type_line, power, toughness), owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.controller_id = pid
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _graveyard(eng: GameEngine, pid: str, names: list[str], type_line: str = "Creature — Bear") -> list[GameObject]:
    out = []
    for name in names:
        obj = GameObject(_make_card(name, type_line), owner_id=pid, zone=Zone.GRAVEYARD)
        eng.state.player_by_id(pid).graveyard.append(obj)
        out.append(obj)
    return out


def _enters(eng: GameEngine, obj: GameObject) -> None:
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id=obj.controller_id,
        object_types=sorted(obj.type_words),
    ))


def _modeled(name: str) -> bool:
    return parse_oracle(_card(name)).coverage == MODELED


def _answer(eng: GameEngine, option: str | None = None) -> None:
    """Answer the open choice with ``option`` (default: the first non-decline option)."""
    choice = eng.state.pending_choice
    assert choice is not None
    pick = option or next(o["id"] for o in choice["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(pick)


def _accept_if_asked(eng: GameEngine) -> None:
    """Answer an optional ability's "do / decline" prompt with "do" when that is what is open."""
    choice = eng.state.pending_choice
    if choice is not None and {o["id"] for o in choice["options"]} == {"do", "decline"}:
        eng.resolve_pending_choice("do")


def _settle(eng: GameEngine) -> None:
    eng.resolve_until_stable()




def _upkeep(eng: GameEngine) -> None:
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep"))
    _settle(eng)


# --- mandatory action + "If you do ... Otherwise ..." -----------------------------------------------------------


def test_charnel_troll_grows_when_it_exiles_a_creature_card():
    eng = _engine()
    troll = _board(eng, "Charnel Troll")
    [fodder] = _graveyard(eng, "p1", ["Fodder"])
    _upkeep(eng)
    if eng.state.pending_choice is not None:
        _answer(eng)
        _settle(eng)
    assert fodder.zone is Zone.EXILE
    assert troll.counters.get("+1/+1") == 1 and troll.zone is Zone.BATTLEFIELD


def test_charnel_troll_is_sacrificed_when_it_has_nothing_to_exile():
    eng = _engine()
    troll = _board(eng, "Charnel Troll")
    _upkeep(eng)
    assert troll.zone is Zone.GRAVEYARD  # RULE 608.2c: "otherwise, sacrifice it"


def _hand(eng: GameEngine, pid: str, count: int) -> list[GameObject]:
    out = []
    for i in range(count):
        obj = GameObject(_make_card(f"Card {i}", "Instant"), owner_id=pid, zone=Zone.HAND)
        eng.state.player_by_id(pid).hand.append(obj)
        out.append(obj)
    return out


def test_thought_gorger_discards_its_hand_only_after_the_counters_went_on():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _hand(eng, "p1", 3)
    gorger = _board(eng, "Thought Gorger")
    _enters(eng, gorger)
    _settle(eng)
    assert gorger.counters.get("+1/+1") == 3 and len(p1.hand) == 0 and len(p1.graveyard) == 3


def test_thought_gorger_with_an_empty_hand_does_nothing():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    gorger = _board(eng, "Thought Gorger")
    _enters(eng, gorger)
    _settle(eng)
    assert not gorger.counters.get("+1/+1") and len(p1.graveyard) == 0


def test_disciple_of_freyalise_gains_and_draws_the_sacrificed_creatures_power():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    for i in range(6):
        p1.library.append(GameObject(_make_card(f"Lib {i}", "Instant"), owner_id="p1", zone=Zone.LIBRARY))
    fodder = _plain(eng, "Fodder", "p1", power=3, toughness=3)
    disciple = _board(eng, "Disciple of Freyalise // Garden of Freyalise")
    _enters(eng, disciple)
    _settle(eng)
    while eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        ids = [o["id"] for o in choice["options"]]
        eng.resolve_pending_choice(fodder.instance_id if fodder.instance_id in ids else
                                   next(i for i in ids if i != "decline"))
        _settle(eng)
    assert fodder.zone is Zone.GRAVEYARD
    assert p1.life == 23 and len(p1.hand) == 3


def _drive(eng: GameEngine, *, choose: GameObject | None = None, accept: bool = True, limit: int = 8) -> None:
    """Answer every open prompt: accept (or decline) the optional, pick ``choose`` when offered."""
    for _ in range(limit):
        choice = eng.state.pending_choice
        if choice is None:
            return
        ids = [o["id"] for o in choice["options"]]
        if choose is not None and str(choose.instance_id) in ids:
            eng.resolve_pending_choice(str(choose.instance_id))
        elif not accept and "decline" in ids:
            eng.resolve_pending_choice("decline")
        else:
            eng.resolve_pending_choice(next(i for i in ids if i != "decline"))
        _settle(eng)


def _crovax(eng: GameEngine) -> GameObject:
    crovax = _board(eng, "Crovax the Cursed")
    crovax.counters["+1/+1"] = 4
    return crovax


def test_crovax_grows_when_a_creature_is_sacrificed():
    eng = _engine()
    crovax = _crovax(eng)
    fodder = _plain(eng, "Fodder", "p1")
    _upkeep(eng)
    _drive(eng, choose=fodder)
    assert fodder.zone is Zone.GRAVEYARD and crovax.counters["+1/+1"] == 5


def test_crovax_shrinks_when_the_sacrifice_is_declined():
    eng = _engine()
    crovax = _crovax(eng)
    fodder = _plain(eng, "Fodder", "p1")
    _upkeep(eng)
    _drive(eng, accept=False)
    assert fodder.zone is Zone.BATTLEFIELD and crovax.counters["+1/+1"] == 3  # RULE 608.2c: "if you don't"


def test_crovax_parses_the_if_you_don_t_branch_as_else_effects():
    specs = match_clause(
        "you may sacrifice a creature. if you do, put a +1/+1 counter on ~. "
        "if you don't, remove a +1/+1 counter from ~", reading=ClauseReading(self_subject=True),
    )
    assert specs is not None and [s.type for s in specs] == ["pay_cost_then"]
    assert [e["type"] for e in specs[0].params["else_effects"]] == ["remove_counters"]


_TAPPER_TEXT = ("When this creature enters, you may tap another untapped creature you control. If you do, draw a card. "
                "If you don't, you gain 2 life.")


def _tapper(eng: GameEngine) -> GameObject:
    card = Card(id="Test Tapper", name="Test Tapper", type_line="Creature — Wizard", oracle_text=_TAPPER_TEXT,
                is_creature=True, power=1, toughness=1)
    assert parse_oracle(card).coverage == MODELED
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    p1 = eng.state.player_by_id("p1")
    p1.library.append(GameObject(_make_card("Top", "Instant"), owner_id="p1", zone=Zone.LIBRARY))
    return obj


def test_optional_outcome_runs_the_follow_up_when_the_action_was_performed():
    eng = _engine()
    other = _plain(eng, "Helper", "p1")
    tapper = _tapper(eng)
    _enters(eng, tapper)
    _settle(eng)
    _drive(eng)
    assert other.tapped and len(eng.state.player_by_id("p1").hand) == 1 and eng.state.player_by_id("p1").life == 20


def test_optional_outcome_runs_the_else_branch_when_the_player_declines():
    eng = _engine()
    other = _plain(eng, "Helper", "p1")
    tapper = _tapper(eng)
    _enters(eng, tapper)
    _settle(eng)
    _drive(eng, accept=False)
    assert not other.tapped and len(eng.state.player_by_id("p1").hand) == 0 and eng.state.player_by_id("p1").life == 22


def test_optional_outcome_runs_the_else_branch_when_the_action_cannot_be_performed():
    eng = _engine()
    tapper = _tapper(eng)  # no other untapped creature: "if you do" cannot come true (RULE 608.2c)
    _enters(eng, tapper)
    _settle(eng)
    _drive(eng)
    assert len(eng.state.player_by_id("p1").hand) == 0 and eng.state.player_by_id("p1").life == 22


def test_optional_outcome_runs_the_else_branch_when_an_accepted_action_changed_nothing():
    eng = _engine()
    card = Card(id="Test Miller", name="Test Miller", type_line="Creature — Wizard", is_creature=True, power=1,
                toughness=1, oracle_text="When this creature enters, you may mill a card. If you do, you gain 1 life. "
                                         "If you don't, you gain 5 life.")
    assert parse_oracle(card).coverage == MODELED
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    p1 = eng.state.player_by_id("p1")
    p1.library.clear()  # accepting is allowed, but there is nothing to mill (RULE 608.2c)
    _enters(eng, obj)
    _settle(eng)
    _drive(eng)
    assert p1.life == 25

    eng2 = _engine()
    obj2 = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj2.controller_id = "p1"
    bind_from_catalogue(obj2)
    eng2.state.add_to_battlefield(obj2)
    eng2.state.player_by_id("p1").library.append(GameObject(_make_card("Top", "Instant"), owner_id="p1", zone=Zone.LIBRARY))
    _enters(eng2, obj2)
    _settle(eng2)
    _drive(eng2)
    assert eng2.state.player_by_id("p1").life == 21


# --- series "A, B, and C" sharing one subject --------------------------------------------------------------------


from tests.support.deck_batch import answer as _answer_all, card as _real_card, cast as _cast, filler as _filler, game as _game


def test_series_splits_commas_only_at_effect_clauses():
    specs = match_clause("target player mills 2 cards, draws 2 cards, and loses 2 life",
                         reading=ClauseReading(self_subject=True))
    # (the clause table alone does not own this: the connector cascade in `parse_effect_body` does)
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    specs = parse_effect_body("target player mills 2 cards, draws 2 cards, and loses 2 life.")
    # Later verbs act on the same earlier-named player (RULE 608.2c), carried by one referent each.
    assert [s.type for s in specs] == ["mill", "trigger_subject_referent", "trigger_subject_referent"]
    assert [s.params["effects"][0]["type"] for s in specs[1:]] == ["draw", "lose_life"]
    # A comma inside a condition or an amount phrase is no boundary.
    assert parse_effect_body("if you control a demon, target player draws a card, and loses 1 life.") is not None
    assert parse_effect_body("draw a card, gain a hat, and scry 1.") is None


def test_atrocious_experiment_mills_draws_and_drains_the_one_target_player():
    eng = _game(library=10)
    p2 = eng.state.player_by_id("p2")
    spell = _real_card(eng, "Atrocious Experiment", zone=Zone.HAND)
    target = p2
    _cast(eng, spell, targets=[target])
    _answer_all(eng)
    assert len(p2.library) == 10 - 2 - 2 and len(p2.graveyard) == 2 and len(p2.hand) == 2
    assert p2.life == 18  # every verb of the list acted on the chosen player, not on the caster
    p1 = eng.state.player_by_id("p1")
    assert p1.life == 20 and len(p1.hand) == 0


def test_intimidation_campaign_drains_and_draws_in_order():
    eng = _game(library=5)
    campaign = _real_card(eng, "Intimidation Campaign")
    _enters(eng, campaign)
    _settle(eng)
    _answer_all(eng)
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    assert p2.life == 19 and p1.life == 21 and len(p1.hand) == 1


def test_funeral_rites_draws_loses_life_then_mills():
    eng = _game(library=8)
    spell = _real_card(eng, "Funeral Rites", zone=Zone.HAND)
    _cast(eng, spell)
    _answer_all(eng)
    p1 = eng.state.player_by_id("p1")
    assert len(p1.hand) == 2 and p1.life == 18 and len(p1.library) == 4 and len(p1.graveyard) == 3  # + the spell


# --- reflexive payoffs measuring the sacrificed creature, remove-counter antecedents, own-graveyard picks ------------


def test_ziatora_deals_damage_equal_to_the_sacrificed_creatures_power_and_makes_treasures():
    eng = _game()
    ziatora = _real_card(eng, "Ziatora, the Incinerator")
    fodder = _filler(eng, "Fodder", type_line="Creature — Bear", power=4, toughness=4)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end"))
    _settle(eng)
    answer_ids = []
    for _ in range(6):
        choice = eng.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice["options"]]
        answer_ids.append(choice["kind"])
        pick = str(fodder.instance_id) if str(fodder.instance_id) in ids else (
            "p2" if "p2" in ids else next(i for i in ids if i != "decline"))
        eng.resolve_pending_choice(pick)
        _settle(eng)
    assert fodder.zone is Zone.GRAVEYARD
    assert eng.state.player_by_id("p2").life == 16, answer_ids
    assert sum(1 for o in eng.state.battlefield if o.name == "Treasure") == 3


def test_clockwork_hydra_pings_only_when_a_counter_was_removed():
    for counters, expected_life in ((1, 19), (0, 20)):
        eng = _game()
        hydra = _real_card(eng, "Clockwork Hydra")
        hydra.counters["+1/+1"] = counters
        eng.state.fire_event(GameEvent(EventType.ATTACKS, instance_id=hydra.instance_id, controller_id="p1"))
        _settle(eng)
        for _ in range(4):
            choice = eng.state.pending_choice
            if choice is None:
                break
            ids = [str(o["id"]) for o in choice["options"]]
            eng.resolve_pending_choice("p2" if "p2" in ids else ids[0])
            _settle(eng)
        assert eng.state.player_by_id("p2").life == expected_life, counters


def test_exemplar_of_strength_gains_life_only_when_a_counter_came_off():
    for counters, expected in ((1, 21), (0, 20)):
        eng = _game()
        exemplar = _real_card(eng, "Exemplar of Strength")
        exemplar.counters["-1/-1"] = counters
        eng.state.fire_event(GameEvent(EventType.ATTACKS, instance_id=exemplar.instance_id, controller_id="p1"))
        _settle(eng)
        assert eng.state.player_by_id("p1").life == expected, counters


def test_forgotten_harvest_exiles_a_land_card_and_grows_a_creature():
    eng = _game()
    harvest = _real_card(eng, "Forgotten Harvest")
    target = _filler(eng, "Bear", type_line="Creature — Bear", power=2, toughness=2)
    land = _filler(eng, "Old Forest", type_line="Basic Land — Forest", zone=Zone.GRAVEYARD)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep"))
    _settle(eng)
    for _ in range(6):
        choice = eng.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice["options"]]
        pick = str(target.instance_id) if str(target.instance_id) in ids else next(i for i in ids if i != "decline")
        eng.resolve_pending_choice(pick)
        _settle(eng)
    assert land.zone is Zone.EXILE and target.counters.get("+1/+1") == 1


# --- life-total comparisons as the "Then if ..." gate ------------------------------------------------------------


def test_pulse_of_the_fields_returns_to_hand_only_while_an_opponent_has_more_life():
    for opp_life, in_hand in ((30, True), (20, False)):  # 20 + 4 = 24: only the 30-life opponent has more
        eng = _game()
        eng.state.player_by_id("p2").life = opp_life
        spell = _real_card(eng, "Pulse of the Fields", zone=Zone.HAND)
        _cast(eng, spell)
        _answer_all(eng)
        assert eng.state.player_by_id("p1").life == 24
        assert (spell.zone is Zone.HAND) == in_hand, opp_life


def test_survival_cache_draws_only_while_you_lead_in_life():
    for opp_life, hand in ((20, 1), (30, 0)):
        eng = _game()
        eng.state.player_by_id("p2").life = opp_life
        spell = _real_card(eng, "Survival Cache", zone=Zone.HAND)
        _cast(eng, spell)
        _answer_all(eng)
        assert eng.state.player_by_id("p1").life == 22
        assert len(eng.state.player_by_id("p1").hand) == hand, opp_life


def test_life_comparison_conditions_parse():
    from mtg_analyzer.parser.oracle.catalogue.clause_hooks import static_condition

    assert static_condition("an opponent has more life than you") == {
        "kind": "opponent_has_more", "selector": "your_life_total"}
    assert static_condition("you have more life than an opponent") == {
        "kind": "opponent_has_fewer", "selector": "your_life_total"}
