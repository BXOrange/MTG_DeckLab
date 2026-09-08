"""MEC-51b — Word of Command (RULE 720).

"Look at target opponent's hand and choose a card from it. You control that
player until ~ finishes resolving. The player plays that card if able."

`WordOfCommandEffect` opens a `word_of_command` pending choice addressed to
the caster over the target's hand; `GameEngine.resolve_word_of_command_choice`
then has the target play the pick — `play_land`, else `cast_without_paying`
(the effect-driven free-cast primitive cascade/discover use). The RULE 720
mana restriction and target selection are documented simplifications.
"""

from __future__ import annotations

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _deck(n=20):
    return [Card(id=f"L{i}", name="Forest", type_line="Basic Land — Forest",
                 is_land=True) for i in range(n)]


def _engine():
    eng = GameEngine.new_game(
        [("p1", "A", _deck()), ("p2", "B", _deck())], starting_life=20, starting_hand=0
    )
    eng.start()
    eng.state.current_step = "main1"
    return eng, eng.state


def _to_hand(st, pid, card):
    o = GameObject(card, owner_id=pid, zone=Zone.HAND)
    st.player_by_id(pid).hand.append(o)
    return o


def _cast_woc(eng, st, target_id="p2"):
    woc = Card(id="WOC", name="Word of Command", type_line="Instant",
               mana_cost_string="{B}{B}", is_instant=True)
    wo = _to_hand(st, "p1", woc)
    bind_from_catalogue(wo)
    st.player_by_id("p1").mana_pool.add_many({"B": 2})
    eng.cast_spell(st.player_by_id("p1"), wo, targets=[st.player_by_id(target_id)])
    eng.resolve_until_stable()
    return wo


def test_word_of_command_binds_a_spell_effect():
    specs = ac.specs_for(Card(id="x", name="Word of Command", type_line="Instant"))
    assert [(s.ability_kind, [e.type for e in s.effects]) for s in specs] == [
        ("spell_effect", ["word_of_command"])
    ]


def test_resolution_opens_a_pick_addressed_to_the_caster_over_the_targets_hand():
    eng, st = _engine()
    shock = _to_hand(st, "p2", Card(id="SH", name="Shock", type_line="Instant",
                                    mana_cost_string="{R}", is_instant=True))
    bear = _to_hand(st, "p2", Card(id="BR", name="Grizzly Bears",
                                   type_line="Creature — Bear", is_creature=True,
                                   power=2, toughness=2))
    _cast_woc(eng, st)

    pc = st.pending_choice
    assert pc and pc["kind"] == "word_of_command"
    assert pc["player_id"] == "p1"                 # the caster picks
    assert {o["label"] for o in pc["options"]} == {"Shock", "Grizzly Bears"}
    # the target's decisions route to the caster while the window is open
    assert st.decider_for("p2") == "p1"
    assert st.word_of_command["target_id"] == "p2"


def test_caster_makes_the_target_play_the_chosen_creature_for_free():
    eng, st = _engine()
    bear = _to_hand(st, "p2", Card(id="BR", name="Grizzly Bears",
                                   type_line="Creature — Bear", is_creature=True,
                                   power=2, toughness=2))
    _cast_woc(eng, st)
    # the target has no mana at all — the free cast still happens
    assert st.player_by_id("p2").mana_pool.total() == 0

    eng.resolve_pending_choice(str(bear.instance_id))
    eng.resolve_until_stable()

    assert bear.zone == Zone.BATTLEFIELD
    assert bear.controller_id == "p2"
    assert st.word_of_command is None              # window closed


def test_chosen_land_is_played_when_able():
    eng, st = _engine()
    land = _to_hand(st, "p2", Card(id="ISL", name="Island",
                                   type_line="Basic Land — Island", is_land=True))
    # it's p2's own turn so they can legally play a land
    while st.active_player.id != "p2":
        eng.advance_step()
    st.current_step = "main1"
    _cast_woc(eng, st)

    eng.resolve_pending_choice(str(land.instance_id))
    eng.resolve_until_stable()

    assert land.zone == Zone.BATTLEFIELD
    assert land.controller_id == "p2"


def test_empty_hand_fizzles_with_no_choice():
    eng, st = _engine()
    assert st.player_by_id("p2").hand == []
    _cast_woc(eng, st)
    assert st.pending_choice is None
    assert st.word_of_command is None


def test_a_missing_answer_defaults_to_the_first_card():
    eng, st = _engine()
    first = _to_hand(st, "p2", Card(id="A1", name="Ancestral Recall",
                                    type_line="Instant", is_instant=True,
                                    mana_cost_string="{U}"))
    _to_hand(st, "p2", Card(id="B1", name="Black Lotus",
                            type_line="Artifact", mana_cost_string="{0}"))
    _cast_woc(eng, st)

    eng.resolve_pending_choice(None)   # decline / missing → first card
    eng.resolve_until_stable()
    # Ancestral Recall (instant) was cast for free and is now in the graveyard
    assert first.zone in (Zone.GRAVEYARD, Zone.STACK)
    assert st.word_of_command is None
