"""BUG-31: ninjutsu is an activated ability (RULE 702.49a/602/117) that
resolves from the stack, legal from declare blockers through end of combat."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.models.mana.mana_cost import ManaCost

NINJA_TEXT = ("Ninjutsu {1}{U} ({1}{U}, Return an unblocked attacker you control to hand: "
              "Put this card onto the battlefield from your hand tapped and attacking.)")


def _card(name, cost="{1}", type_line="Creature — Rat", keywords=None, oracle="", creature=True):
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=creature, power=1 if creature else None, toughness=1 if creature else None,
        keywords=list(keywords or []), oracle_text=oracle,
    )


def _setup():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    st = eng.state
    rat = GameObject(_card("Rat"), owner_id="p1", zone=Zone.BATTLEFIELD)
    rat.summoning_sick = False
    bind_from_catalogue(rat)
    st.add_to_battlefield(rat)
    ninja = GameObject(_card("Ninja", "{2}{U}", "Creature — Human Ninja", ["Ninjutsu"], NINJA_TEXT),
                       owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(ninja)
    st.player_by_id("p1").add_to_zone(ninja, Zone.HAND)
    eng.start()
    while st.current_step != "declare_attackers":
        eng.advance_step()
    return eng, st, rat, ninja


def _to_blockers(eng, st, rat):
    eng.declare_attackers(st.active_player, [rat])
    eng.advance_step()
    assert st.current_step == "declare_blockers"
    # RULE 509.1h: the defender declares (no) blockers before anything counts as unblocked
    assert not _offers(eng, st.active_player)
    eng.declare_blockers(st.player_by_id("p2"), [])


def _offers(eng, p):
    return [a for a in eng.legal_actions(p) if a.get("type") == "ninjutsu"]


def _fund(st):
    p1 = st.player_by_id("p1")
    p1.mana_pool.add_many({"U": 1, "C": 1})
    return p1


def test_costs_paid_then_stack_then_resolves_attacking_same_defender():
    eng, st, rat, ninja = _setup()
    _to_blockers(eng, st, rat)
    defender = rat.combat_defender
    p1 = _fund(st)
    eng.ninjutsu(p1, ninja, rat)
    # RULE 602.2b: costs are paid on activation.
    assert rat in p1.hand and not p1.mana_pool.can_pay(ManaCost.parse("{1}"))
    assert ninja.zone == Zone.HAND and len(st.stack) == 1
    assert st.stack[0].category == "activated_ability"
    # RULE 117.3c: the activator holds priority; the opponent may then respond.
    assert st.priority_player is p1
    eng.rules.resolve_top_of_stack()
    assert ninja.zone == Zone.BATTLEFIELD and ninja.tapped and ninja.attacking
    assert ninja.combat_defender == defender  # RULE 702.49d


@pytest.mark.parametrize("step", ["combat_damage", "end_combat"])
def test_legal_after_combat_damage_and_in_end_of_combat(step):
    eng, st, rat, ninja = _setup()
    _to_blockers(eng, st, rat)
    while st.current_step != step:
        eng.advance_step()
    assert rat.attacking  # BUG-30: combat state kept until end of combat is left
    p1 = _fund(st)
    assert _offers(eng, p1)
    eng.ninjutsu(p1, ninja, rat)
    eng.rules.resolve_top_of_stack()
    assert ninja.zone == Zone.BATTLEFIELD and ninja.attacking


def test_illegal_before_blockers_and_without_unblocked_attacker():
    eng, st, rat, ninja = _setup()
    p1 = _fund(st)
    eng.declare_attackers(st.active_player, [rat])
    assert st.current_step == "declare_attackers"
    assert not _offers(eng, p1)
    with pytest.raises(ValueError):
        eng.ninjutsu(p1, ninja, rat)
    eng.advance_step()
    rat.blocked_by = [999]  # blocked attacker is not unblocked
    assert not _offers(eng, p1)
    with pytest.raises(ValueError):
        eng.ninjutsu(p1, ninja, rat)


def test_illegal_under_split_second():
    eng, st, rat, ninja = _setup()
    _to_blockers(eng, st, rat)
    p1 = _fund(st)
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    # Legolas's Quick Reflexes: a real split-second spell (RULE 702.61a).
    spell = GameObject(CardDatabase(DB_PATH).get_card("Legolas's Quick Reflexes"),
                       owner_id="p2", zone=Zone.STACK)
    bind_from_catalogue(spell)
    st.stack.append(StackItem(kind="spell", controller_id="p2", obj=spell, effects=[]))
    assert not _offers(eng, p1)
    with pytest.raises(ValueError):
        eng.ninjutsu(p1, ninja, rat)


def test_ninja_leaving_hand_in_response_enters_nothing():
    eng, st, rat, ninja = _setup()
    _to_blockers(eng, st, rat)
    p1 = _fund(st)
    eng.ninjutsu(p1, ninja, rat)
    p1.remove_from_zone(ninja, Zone.HAND)  # e.g. discarded in response
    p1.add_to_zone(ninja, Zone.GRAVEYARD)
    eng.rules.resolve_top_of_stack()
    assert ninja.zone == Zone.GRAVEYARD and ninja not in st.battlefield
