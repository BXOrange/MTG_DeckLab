"""PAR-291 M4: the tempting offer ("<X>. Each opponent may <X'>. For each opponent who does, <X''>.").

Real cards on a 3-player engine: each opponent decides in turn order, the opponent performs the body as themself, and the
payoff runs once for each opponent who said yes, after all have answered (RULE 101.4, 608.2c).
"""
import pytest

from test_par320_edict_counts_punishers import _three, _creature, _put, _real, _card
from test_par320_residue import _spell
from mtg_analyzer.game.card_registry import is_card_covered
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

OFFERS = ("Tempt with Glory", "Tempt with Immortality", "Tempt with Reflections", "Tempting Contract")


@pytest.mark.parametrize("name", OFFERS)
def test_real_cards_are_covered(name):
    assert is_card_covered(_real(name))


@pytest.mark.parametrize("text", [
    # the opponent's sentence must be the controller's with only the pronouns turned around
    "Put a +1/+1 counter on each creature you control. Each opponent may draw a card. "
    "For each opponent who does, put a +1/+1 counter on each creature you control.",
    "Put a +1/+1 counter on each creature you control. Each opponent may put a +1/+1 counter on each creature they control. "
    "For each opponent who does, draw a card.",
    "Each opponent may create a Treasure token. For each opponent who does, you create a Food token.",
    "Each opponent may create a Treasure token. For each opponent who does, create two Treasure tokens.",
    "Each opponent may put a +1/+1 counter on each creature they control. For each opponent who does, draw a card.",
])
def test_mismatched_offers_stay_refused(text):
    assert not parse_oracle(_card("Neg", type_line="Sorcery", is_sorcery=True, oracle=text)).modeled


def _decide(eng, answers):
    """Answer each opponent's yes/no in the order asked; returns the players asked."""
    asked = []
    for answer in answers:
        choice = eng.state.pending_choice
        assert choice is not None, "expected another opponent to be asked"
        asked.append(choice["player_id"])
        eng.resolve_pending_choice(answer)
        eng.resolve_until_stable()
    return asked


def _counters(obj):
    return obj.counters.get("+1/+1", 0)


def test_glory_pumps_each_side_by_its_own_creatures_and_the_payoff_counts_acceptors():
    eng = _three()
    mine = _creature(eng, "Mine", "p1")
    p2c = _creature(eng, "Two", "p2")
    p3c = _creature(eng, "Three", "p3")
    _spell(eng, "Tempt with Glory")
    assert _counters(mine) == 1 and _counters(p2c) == 0  # the controller's own counter first
    asked = _decide(eng, ["yes", "decline"])
    assert asked == ["p2", "p3"]  # turn order (RULE 101.4)
    assert eng.state.pending_choice is None
    assert _counters(p2c) == 1 and _counters(p3c) == 0  # only the acceptor is pumped, as themself
    assert _counters(mine) == 2  # one acceptor: one more counter for the caster


def test_glory_all_decline_gives_no_bonus_and_both_accept_gives_two():
    eng = _three()
    mine = _creature(eng, "Mine", "p1")
    _spell(eng, "Tempt with Glory")
    _decide(eng, ["decline", "decline"])
    assert _counters(mine) == 1
    eng = _three()
    mine = _creature(eng, "Mine", "p1")
    theirs = [_creature(eng, "Two", "p2"), _creature(eng, "Three", "p3")]
    _spell(eng, "Tempt with Glory")
    _decide(eng, ["yes", "yes"])
    assert _counters(mine) == 3 and all(_counters(o) == 1 for o in theirs)


def test_tempting_contract_each_acceptor_makes_a_treasure_and_so_does_the_caster():
    eng = _three()
    contract = _put(eng, _real("Tempting Contract"), "p1")
    eng.state.current_step = "upkeep"
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.gate import parse_oracle as parse
    specs = next(s for s in parse(contract.card).specs if s.trigger is not None or s.kind == "triggered")
    for effect in build_effects(list(specs.effects), contract):
        effect.apply(GameContext(eng.state, eng.rules), None)
    eng.resolve_until_stable()
    _decide(eng, ["yes", "decline"])

    def treasures(pid):
        return [o for o in eng.state.battlefield if o.controller_id == pid and o.name == "Treasure"]

    assert len(treasures("p2")) == 1 and not treasures("p3") and len(treasures("p1")) == 1


def test_immortality_returns_a_creature_for_each_side_chosen_by_that_side():
    eng = _three()

    def grave(pid, name):
        obj = GameObject(_card(name, is_creature=True, power=1, toughness=1), owner_id=pid, zone=Zone.GRAVEYARD)
        obj.controller_id = pid
        eng.state.player_by_id(pid).graveyard.append(obj)
        return obj

    mine, two = grave("p1", "MineDead"), grave("p2", "TwoDead")
    grave("p3", "ThreeDead")
    _spell(eng, "Tempt with Immortality")
    for _ in range(6):
        choice = eng.state.pending_choice
        if choice is None:
            break
        pick = "yes" if choice.get("kind") == "composite_optional" and choice["player_id"] == "p2" else None
        if pick is None:
            opts = [o for o in choice["options"] if o["id"] != "decline"]
            pick = "decline" if choice.get("kind") == "composite_optional" else opts[0]["id"]
        eng.resolve_pending_choice(str(pick))
        eng.resolve_until_stable()
    assert mine.zone is Zone.BATTLEFIELD and two.zone is Zone.BATTLEFIELD
    assert two.controller_id == "p2"


def test_reflections_copies_the_chosen_creature_for_the_acceptor_under_their_control():
    eng = _three()
    hero = _creature(eng, "Hero", "p1")
    from mtg_analyzer.services.game_session import GameSession  # noqa: F401  (import guard: the engine path only)
    _spell(eng, "Tempt with Reflections", targets=[hero])
    for _ in range(8):
        choice = eng.state.pending_choice
        if choice is None:
            break
        if choice.get("kind") == "composite_optional":
            eng.resolve_pending_choice("yes" if choice["player_id"] == "p3" else "decline")
        else:
            eng.resolve_pending_choice(str([o for o in choice["options"]][0]["id"]))
        eng.resolve_until_stable()
    copies = [o for o in eng.state.battlefield if o.name == "Hero" and o is not hero]
    assert sorted(o.controller_id for o in copies) == ["p1", "p1", "p3"] or sorted(o.controller_id for o in copies) == ["p1", "p3"]


# -- "you and that player each draw" under a damage head -------------------------------------------------------------

SHARED_DRAWS = ("Black Widow, Intel Expert", "Diviner Spirit", "Sergeant John Benton", "Xyris, the Writhing Storm")


@pytest.mark.parametrize("name", SHARED_DRAWS)
def test_shared_draw_cards_are_covered(name):
    assert is_card_covered(_real(name))


@pytest.mark.parametrize("text", [
    "When you cast that spell, if another player spent mana to cast it, you and that player each draw a card.",
    "Whenever ~ deals combat damage to a player, you and that player each draw a card, then discard a card.",
    "Whenever ~ attacks, you and defending player each draw a card.",
])
def test_shared_draw_forms_outside_a_damage_head_stay_refused(text):
    card = _card("Neg", type_line="Creature — Test", is_creature=True, power=1, toughness=1, oracle=text)
    assert not parse_oracle(card).modeled


def _library(eng, pid, n):
    for i in range(n):
        obj = GameObject(_card(f"{pid}-{i}", type_line="Land", is_land=True), owner_id=pid, zone=Zone.LIBRARY)
        obj.controller_id = pid
        eng.state.player_by_id(pid).library.append(obj)


@pytest.mark.parametrize("name,damage,drawn", [
    ("Diviner Spirit", 3, 3), ("Sergeant John Benton", 2, 2), ("Xyris, the Writhing Storm", 4, 4),
    ("Black Widow, Intel Expert", 1, 2),
])
def test_both_players_draw_for_the_damaged_player_only(name, damage, drawn):
    eng = _three()
    hero = _put(eng, _real(name), "p1")
    for pid in ("p1", "p2", "p3"):
        _library(eng, pid, 6)
    eng.rules.deal_damage(eng.state.player_by_id("p2"), damage, source=hero, combat=True)
    eng.rules.put_triggers_on_stack()
    while eng.state.stack:
        eng.rules.resolve_top_of_stack()
        eng.resolve_until_stable()
    hand = lambda pid: len(eng.state.player_by_id(pid).hand)  # noqa: E731
    assert hand("p1") == drawn and hand("p2") == drawn and hand("p3") == 0


def test_bots_answer_the_offer_from_their_own_view_and_legal_actions():
    from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.services.bots import create_bot
    from mtg_analyzer.services.game_session import GameSessionManager
    from mtg_analyzer.models.cards.card import Card

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
    opponents = [p.id for p in state.players if p.id != controller]
    mine = _creature(eng, "Mine", controller)
    theirs = {pid: _creature(eng, f"Theirs-{pid}", pid) for pid in opponents}
    spell = GameObject(_real("Tempt with Glory"), owner_id=controller, zone=Zone.STACK)
    spell.controller_id = controller
    bind_from_catalogue(spell)
    for spec in specs_for_spell(spell):
        for effect in build_effects(list(spec.effects), spell):
            effect.apply(GameContext(state, eng.rules), None)
    asked = []
    for _ in range(len(opponents)):
        choice = state.pending_choice
        assert choice is not None
        asker = choice["player_id"]
        asked.append(asker)
        assert asker in opponents
        other = next(p for p in ("p1", "p2", "p3") if p != asker)
        assert not [a for a in session.legal_actions(perspective=other) if a["type"] == "choose"]
        actions = session.legal_actions(perspective=asker)
        assert [a for a in actions if a["type"] in ("choose", "decline", "pass_choice", "choose_none")]
        action = create_bot("greedy", asker).decide(session.view(perspective=asker), actions)
        assert action["type"] in ("choose", "decline")  # a bot may take the offer or turn it down
        session.apply_action(action, actor_id=asker)
    assert asked == opponents  # turn order
    took = sum(_counters(o) for o in theirs.values())
    assert _counters(mine) == 1 + took  # the payoff is exactly the number who accepted


def specs_for_spell(obj):
    return [s for s in parse_oracle(obj.card).specs if s.ability_kind in ("spell", "spell_effect")]
