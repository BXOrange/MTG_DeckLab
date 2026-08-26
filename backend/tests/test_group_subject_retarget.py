"""MEC-28: RULE 603.1 "group" subject retarget for a self-acting effect body.

"Whenever a creature you control attacks alone, untap it." (the shape
Raiyuu/A-Raiyuu print, gated behind an intervening-if this file doesn't
need to exercise) — the group-subject sibling of ENG-29's attached_permanent
retarget: there's no static field to repoint (unlike an Aura's own
``attached_to``), since *which* object matched varies every firing, so
`TapEffect` gained a `"trigger_subject"` mode reading `GameContext.
trigger_event` live (`effect_binder._retarget_implicit_subject_effects`,
extended from its ENG-29 shape to also handle ``{"subject": "group"}``).

Also covers the sibling primitive from the same MEC-28 pass: `TapEffect`'s
new ``"attacking_creatures"`` mass selector (Karlach, Fury of Avernus/
Hexplate Wallbreaker/Hellkite Charger-shaped "untap all/each attacking
creature[s]") — reusing `continuous.group_selector_objects`'s existing
``"attacking_creatures"`` branch (already built for Motivated Pony's anthem),
just newly reachable from `TapEffect.selector`.

Neither of MEC-28's two named cards (Karlach, Finest Hour) is modeled by
this pass alone — each has its own *separate* remaining blocker (Karlach's
"They gain first strike" plural-pronoun tail; Finest Hour's "that creature"
phrasing, which needs the same retarget but through a parser-level
``group_subject_only`` gate this pass didn't build, see BACKLOG.md) — so
these tests exercise the primitives directly against minimal synthetic text
that *does* fully parse today, the same "prove the mechanism, not just the
one card" approach `test_intervening_if_first_combat_phase.py` uses.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


GROUP_UNTAP_TEXT = "Whenever a creature you control attacks alone, untap it."


def group_untap_card(name="Test Group Untap"):
    return Card(id=name, name=name, type_line="Enchantment", oracle_text=GROUP_UNTAP_TEXT)


def bear_card(name="Bear"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


def test_group_untap_clause_is_modeled():
    result = parse_oracle(group_untap_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_group_subject_untaps_the_matching_attacker():
    eng = make_engine("p1", "p2")
    put(eng.state, group_untap_card())
    bear = put(eng.state, bear_card())
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"

    eng.declare_attackers(eng.state.active_player, [bear])
    eng._fire_attacks_alone_event()  # RULE 508.1a: fired once combat locks in, not per-declare
    eng.resolve_until_stable()

    assert bear.tapped is False  # untapped by the trigger


def test_group_subject_does_not_fire_when_not_attacking_alone():
    eng = make_engine("p1", "p2")
    put(eng.state, group_untap_card())
    bear = put(eng.state, bear_card("Bear"))
    wolf = put(eng.state, bear_card("Wolf"))
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"

    eng.declare_attackers(eng.state.active_player, [bear, wolf])
    eng._fire_attacks_alone_event()  # two attackers — RULE 508.1a's event never fires
    eng.resolve_until_stable()

    assert bear.tapped is True
    assert wolf.tapped is True


ATTACKING_CREATURES_TEXT = "Whenever this creature attacks, untap all attacking creatures."


def attacking_untap_card(name="Test Attacking Untap"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
                oracle_text=ATTACKING_CREATURES_TEXT)


def test_attacking_creatures_clause_is_modeled():
    result = parse_oracle(attacking_untap_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_attacking_creatures_selector_untaps_every_attacker_not_just_self():
    eng = make_engine("p1", "p2")
    source = put(eng.state, attacking_untap_card())
    ally = put(eng.state, bear_card("Ally"))
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"

    eng.declare_attackers(eng.state.active_player, [source, ally])
    eng.resolve_until_stable()

    assert source.tapped is False
    assert ally.tapped is False


def test_attacking_creatures_selector_does_not_untap_a_non_attacker():
    eng = make_engine("p1", "p2")
    source = put(eng.state, attacking_untap_card())
    bystander = put(eng.state, bear_card("Bystander"))
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"

    eng.declare_attackers(eng.state.active_player, [source])
    eng.resolve_until_stable()

    assert source.tapped is False
    assert bystander.tapped is False  # never attacked, never tapped, stays as-is
