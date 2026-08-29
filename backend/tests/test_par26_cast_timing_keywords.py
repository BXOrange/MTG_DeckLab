"""PAR-26 — the cast-alternative/timing keyword family that was
parser-recognised but implemented nowhere.

Covered here so far:

* **Backup N** (702.165) — ETB "put N +1/+1 counters on target creature"
  (may target itself); the "lends its other abilities" clause is a
  documented simplification.
* **Dash** (702.109) — an alternative cast cost (`obj.alt_cast_cost` +
  `dash` marker): haste on enter, returned to hand at the next end step.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost


def _card(name, cost="{2}{R}", keywords=None, type_line="Creature — Goblin",
          power=2, toughness=2, oracle_text="", is_creature=True):
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=is_creature,
        power=power if is_creature else None, toughness=toughness if is_creature else None,
        keywords=list(keywords or []), oracle_text=oracle_text,
    )


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _hand(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).add_to_zone(obj, Zone.HAND)
    return obj


def _to_main(eng):
    eng.start()
    while eng.state.current_step != "main1":
        eng.advance_step()


# -- Backup (RULE 702.165) ---------------------------------------------


def _enter_backer(eng, name, n, extra_creatures=()):
    state = eng.state
    others = [
        _bf(state, _card(nm, power=1, toughness=1, type_line="Creature — Bear"))
        for nm in extra_creatures
    ]
    backer = _hand(
        state,
        _card(name, cost="{1}", keywords=["Backup"], power=2, toughness=2,
              oracle_text=f"Backup {n} (When this creature enters, put {n} +1/+1 "
                          f"counters on target creature. ...)"),
    )
    _to_main(eng)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, backer)
    eng.resolve_until_stable()  # spell resolves, ETB fires, trigger opens its target choice
    return backer, others


def test_backup_puts_counters_on_another_creature():
    eng = _engine()
    backer, (ally,) = _enter_backer(eng, "Bola Slinger", 2, extra_creatures=["Ally"])
    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice(ally.instance_id)
    eng.resolve_until_stable()

    assert ally.counters.get("+1/+1", 0) == 2


def test_backup_can_target_itself_when_alone():
    eng = _engine()
    backer, _ = _enter_backer(eng, "Solo Backer", 1)
    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice(backer.instance_id)
    eng.resolve_until_stable()

    assert backer.counters.get("+1/+1", 0) == 1  # targeted itself


# -- Dash (RULE 702.109) ---------------------------------------------


def test_dash_grants_haste_and_bounces_at_end_step():
    eng = _engine()
    state = eng.state
    goblin_card = _card("Zurgo Bellstriker", cost="{3}{R}{R}", power=2, toughness=2,
                        keywords=["Dash"],
                        oracle_text="Dash {1}{R} (You may cast this spell for its dash cost. "
                                    "If you do, it gains haste, and it's returned to its "
                                    "owner's hand at the beginning of the next end step.)")
    goblin = _hand(state, goblin_card)
    assert getattr(goblin, "dash", False) and goblin.alt_cast_cost is not None

    _to_main(eng)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"R": 1, "C": 1})  # the dash cost {1}{R}
    eng.cast_spell(p1, goblin, alt_cost=True)
    eng.resolve_until_stable()

    assert goblin.zone == Zone.BATTLEFIELD
    continuous.recompute(state)
    assert "haste" in goblin.granted_keywords or "haste" in goblin.temp_keywords
    assert any("Dash" in dt.description for dt in state.delayed_triggers)

    while state.current_step != "end":
        eng.advance_step()
    eng.advance_step()
    eng.resolve_until_stable()
    assert goblin.zone == Zone.HAND


# -- Madness (RULE 702.35) -----------------------------------------


def _madness_card(cost="{1}{R}", madness="{R}"):
    return Card(
        id="Fiery Temper", name="Fiery Temper", type_line="Creature — Lizard",
        mana_cost_string=cost, converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=True, power=1, toughness=1, keywords=["Madness"],
        oracle_text=f"Madness {madness} (If you discard this card, exile it instead of "
                    f"putting it into your graveyard, then you may cast it by paying "
                    f"{madness} rather than putting it into your graveyard.)",
    )


def test_madness_exiles_on_discard_and_is_castable_for_the_madness_cost():
    eng = _engine()
    state = eng.state
    card = _madness_card()
    obj = _hand(state, card)
    _to_main(eng)
    p1 = state.player_by_id("p1")

    p1.mana_pool.add_many({"R": 1})  # enough for the madness cost, not the printed {1}{R}
    eng.rules.discard(p1, 1)
    assert obj.zone == Zone.EXILE and obj in p1.exile

    casts = [a for a in eng.legal_actions(p1)
             if a.get("type") == "cast_spell" and a.get("instance_id") == obj.instance_id]
    assert len(casts) == 1 and casts[0].get("alt_cost") is True  # only the madness-cost offer

    eng.cast_spell(p1, obj, alt_cost=True)
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD


def test_madness_card_goes_to_graveyard_if_not_cast_by_end_of_turn():
    eng = _engine()
    state = eng.state
    obj = _hand(state, _madness_card())
    _to_main(eng)
    p1 = state.player_by_id("p1")

    eng.rules.discard(p1, 1)
    assert obj.zone == Zone.EXILE

    while state.current_step != "end":
        eng.advance_step()
    eng.advance_step()  # fire the delayed "to graveyard" trigger
    eng.resolve_until_stable()
    assert obj.zone == Zone.GRAVEYARD
    assert obj in p1.graveyard


# -- Miracle (RULE 702.94) ----------------------------------------


def _miracle_card(cost="{6}{R}", miracle="{R}"):
    return Card(
        id="Bonfire", name="Bonfire of the Damned", type_line="Sorcery",
        mana_cost_string=cost, converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=False, is_sorcery=True, keywords=["Miracle"],
        oracle_text=f"Miracle {miracle} (You may cast this card for its miracle cost "
                    f"when you draw it if it's the first card you've drawn this turn.)",
    )


def test_miracle_offers_the_miracle_cost_only_on_the_first_draw_of_the_turn():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    # library: [other, miracle] — the miracle card is drawn first (list end = top).
    for c in (_card("Filler", cost="{1}", type_line="Creature — Bear"), _miracle_card()):
        o = GameObject(c, owner_id="p1", zone=Zone.LIBRARY)
        bind_from_catalogue(o)
        p1.add_to_zone(o, Zone.LIBRARY)
    _to_main(eng)
    p1.mana_pool.add_many({"R": 1})

    eng.rules.draw(p1, 1)  # draws the miracle card (first this turn)
    miracle_obj = next(o for o in p1.hand if getattr(o, "miracle", False))
    assert miracle_obj.miracle_armed

    casts = [a for a in eng.legal_actions(p1)
             if a.get("type") == "cast_spell" and a.get("instance_id") == miracle_obj.instance_id]
    assert any(a.get("alt_cost") for a in casts)  # miracle-cost offer present

    # a *second* draw this turn does not arm the next card
    eng.rules.draw(p1, 1)
    filler = next(o for o in p1.hand if not getattr(o, "miracle", False))
    assert not getattr(filler, "miracle_armed", False)


def test_miracle_window_closes_at_cleanup():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    o = GameObject(_miracle_card(), owner_id="p1", zone=Zone.LIBRARY)
    bind_from_catalogue(o)
    p1.add_to_zone(o, Zone.LIBRARY)
    _to_main(eng)
    eng.rules.draw(p1, 1)
    assert o.miracle_armed

    while state.current_step != "cleanup":
        eng.advance_step()
    eng.advance_step()
    assert not o.miracle_armed
    assert o.instance_id not in state.miracle_armed_ids


# -- Ninjutsu (RULE 702.49) ---------------------------------------


def test_ninjutsu_swaps_an_unblocked_attacker_for_a_ninja():
    eng = _engine()
    state = eng.state
    rat = _bf(state, _card("Rat", power=1, toughness=1, type_line="Creature — Rat"))
    ninja = _hand(state, _card("Ninja of the Deep Hours", cost="{2}{U}",
                               type_line="Creature — Human Ninja", keywords=["Ninjutsu"],
                               oracle_text="Ninjutsu {1}{U} ({1}{U}, Return an unblocked "
                                           "attacker you control to hand: Put this card onto "
                                           "the battlefield from your hand tapped and attacking.)"))
    assert getattr(ninja, "ninjutsu_cost", None) is not None

    eng.start()
    while state.current_step != "declare_attackers":
        eng.advance_step()
    eng.declare_attackers(state.active_player, [rat])
    eng.advance_step()  # → declare_blockers
    assert state.current_step == "declare_blockers"

    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"U": 1, "C": 1})
    ninjutsu_actions = [a for a in eng.legal_actions(p1) if a.get("type") == "ninjutsu"]
    assert ninjutsu_actions and ninjutsu_actions[0]["returned_attacker_id"] == rat.instance_id

    eng.ninjutsu(p1, ninja, rat)

    assert rat.zone == Zone.HAND and rat in p1.hand
    assert ninja.zone == Zone.BATTLEFIELD
    assert ninja.tapped and ninja.attacking


def test_ninjutsu_refused_for_a_blocked_attacker():
    eng = _engine()
    state = eng.state
    rat = _bf(state, _card("Rat", power=1, toughness=1, type_line="Creature — Rat"))
    blocker = _bf(state, _card("Wall", power=0, toughness=4, type_line="Creature — Wall"),
                  controller="p2")
    ninja = _hand(state, _card("Ninja", cost="{2}{U}", type_line="Creature — Ninja",
                               keywords=["Ninjutsu"],
                               oracle_text="Ninjutsu {1}{U} ({1}{U}, Return an unblocked "
                                           "attacker you control to hand: ...)"))
    eng.start()
    while state.current_step != "declare_attackers":
        eng.advance_step()
    eng.declare_attackers(state.active_player, [rat])
    eng.advance_step()
    defender = state.player_by_id("p2")
    eng.declare_blockers(defender, [{"blocker": blocker, "attacker": rat}])

    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"U": 1, "C": 1})
    assert not [a for a in eng.legal_actions(p1) if a.get("type") == "ninjutsu"]
    import pytest
    with pytest.raises(ValueError):
        eng.ninjutsu(p1, ninja, rat)
