"""MEC-29: the two cards MEC-28's own five-card list left open, closed.

- **Balthier and Fran** ("Whenever a Vehicle crewed by ~ this turn attacks,
  …") needed RULE 702.122 Crew as real engine state: `ActivationCost.
  crew_power`, `GameEngine._resolve_crew_cost`/`_crew_pool`, `GameObject.
  crewed_by_ids`, `effect_binder._crew_activated_ability`, and a new
  ``"crewed_by_self"`` RULE 603.1 group-subject trigger-condition key. Crew
  had been parser-*recognized* the whole time (the coverage gate's own
  keyword catalogue) but bound to nothing anywhere in `game/`/`models/` —
  the same "recognized but inert" gap Cycling had before PAR-9. Building it
  surfaced two further, previously-invisible bugs, both covered here too:
  `_ANTHEM_RE`'s `_scope` silently mis-modeling a bare "Vehicles [you
  control]" anthem as ``creatures_you_control`` (a Vehicle isn't a creature
  until crewed), and `Card` never capturing a Vehicle's own printed RULE
  208.1 power/toughness at all — a freshly crewed Vehicle came in 0/0 and
  died to RULE 704.5f the instant the next SBA check ran.
- **Tifa, Martial Artist** ("Whenever one or more creatures you control with
  power 7 or greater deal combat damage to a player, …") needed the "one or
  more" quantifier as a genuine aggregate, once-per-combat-damage-step
  event (`EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`,
  `GameEngine._apply_combat_damage`) rather than reusing the ordinary
  per-creature `DAMAGE` group-subject condition (which already existed for
  "a creature you control deals combat damage to a player" — Bident of
  Thassa/Deepfathom Skulker — contrary to this ticket's own original
  framing) — the same "with one or more creatures" shape `EventType.
  PLAYER_ATTACKED` already exists to solve for declaring attackers. Two
  simultaneous qualifying attackers must trigger this exactly once, not
  twice (this card's own payoff is an extra combat phase, and RULE 508.6/
  509.5 combat damage is simultaneous).
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def make_engine(*player_ids):
    if not player_ids:
        player_ids = ("p1", "p2")
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def put(state, card, controller="p1", tapped=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = tapped
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def bear_card(name="Bear", power=2, toughness=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness,
    )


def vehicle_card(name="Test Vehicle", crew=1, power=3, toughness=3):
    return Card(
        id=name, name=name, type_line="Artifact — Vehicle",
        oracle_text=f"Crew {crew}", keywords=["Crew"],
        vehicle_power=power, vehicle_toughness=toughness,
    )


def _to_declare_attackers(eng):
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"


# -- Crew (RULE 702.122a): the general primitive ----------------------------


def test_card_refuses_power_on_a_noncreature_but_allows_vehicle_power():
    # `vehicle_power`/`vehicle_toughness` are deliberately independent of
    # the creature-only `power`/`toughness` invariant.
    v = vehicle_card()
    assert v.is_creature is False
    assert v.power is None and v.toughness is None
    assert v.vehicle_power == 3 and v.vehicle_toughness == 3


def test_crew_binds_a_real_activated_ability():
    eng = make_engine()
    v = put(eng.state, vehicle_card(crew=2))
    assert len(v.activated_abilities) == 1
    ability = v.activated_abilities[0]
    assert ability.cost.crew_power == 2


def test_crew_too_little_power_is_not_payable():
    eng = make_engine()
    v = put(eng.state, vehicle_card(crew=5))
    small = put(eng.state, bear_card(power=2, toughness=2))
    ability = v.activated_abilities[0]
    p1 = eng.state.player_by_id("p1")
    assert eng.can_activate(p1, v, ability, x=0, tap_choices=[small.instance_id]) is False


def test_crew_becomes_a_creature_with_its_own_printed_pt_and_survives_sba():
    eng = make_engine()
    v = put(eng.state, vehicle_card(crew=1, power=3, toughness=3))
    bear = put(eng.state, bear_card(power=2, toughness=2))
    eng.recompute_continuous_effects()
    assert v.is_creature is False

    ability = v.activated_abilities[0]
    p1 = eng.state.player_by_id("p1")
    eng.activate_ability(p1, v, 0, x=0, tap_choices=[bear.instance_id])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert v.is_creature is True
    assert (v.power, v.toughness) == (3, 3)  # not 0/0 (RULE 208.1)
    assert bear.tapped is True
    assert v.crewed_by_ids == [bear.instance_id]

    eng.rules.check_state_based_actions()
    assert v in eng.state.battlefield  # a 0/0 would have died here


def test_crewed_by_ids_reset_at_untap_step():
    eng = make_engine()
    v = put(eng.state, vehicle_card())
    v.crewed_by_ids = [999]
    eng._step_untap()
    assert v.crewed_by_ids == []


# -- Balthier and Fran --------------------------------------------------


def balthier_card():
    return Card(
        id="Balthier and Fran", name="Balthier and Fran",
        type_line="Legendary Creature — Human Rabbit", is_creature=True,
        power=4, toughness=3, keywords=["Reach"],
        oracle_text=(
            "Reach\nVehicles you control get +1/+1 and have vigilance and "
            "reach.\nWhenever a Vehicle crewed by ~ this turn attacks, if "
            "it's the first combat phase of the turn, you may pay "
            "{1}{R}{G}. If you do, after this phase, there is an "
            "additional combat phase."
        ),
    )


def test_balthier_and_fran_is_registered():
    assert is_registered("Balthier and Fran")


def test_balthier_and_fran_anthem_buffs_vehicles_not_yet_crewed():
    eng = make_engine()
    put(eng.state, balthier_card())
    v = put(eng.state, vehicle_card(power=3, toughness=3))
    eng.recompute_continuous_effects()
    # The Vehicle isn't a creature yet, but the anthem still buffs its
    # (RULE 208.1) printed P/T for whenever it does become one — this is
    # the parser bug fix (`_ARTIFACT_SUBTYPES`/`_vehicle_scope_params`):
    # the anthem must not have been silently scoped to creatures_you_control.
    assert v.is_creature is False
    ability = v.activated_abilities[0]
    p1 = eng.state.player_by_id("p1")
    bear = put(eng.state, bear_card(power=3, toughness=3))
    eng.activate_ability(p1, v, 0, x=0, tap_choices=[bear.instance_id])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (v.power, v.toughness) == (4, 4)  # 3/3 + anthem's +1/+1
    assert "vigilance" in v.granted_keywords
    assert "reach" in v.granted_keywords


def test_balthier_and_fran_grants_extra_combat_when_its_own_crewed_vehicle_attacks():
    eng = make_engine("p1", "p2")
    balthier = put(eng.state, balthier_card())
    v = put(eng.state, vehicle_card(crew=1, power=3, toughness=3))
    p1 = eng.state.player_by_id("p1")

    # Crew ~ with Balthier and Fran itself.
    eng.activate_ability(p1, v, 0, x=0, tap_choices=[balthier.instance_id])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert v.is_creature is True
    assert v.crewed_by_ids == [balthier.instance_id]

    _to_declare_attackers(eng)
    p1.mana_pool.add("R", 1)
    p1.mana_pool.add("G", 1)
    p1.mana_pool.add("C", 1)
    eng.declare_attackers(p1, [v])
    eng.resolve_until_stable()

    assert eng.state.pending_choice is not None
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    eng.rules.resolve_pay_cost_then_choice("pay")
    eng.resolve_until_stable()
    assert eng.state.pending_extra_combats == [False]


def test_balthier_and_fran_does_not_fire_for_a_vehicle_it_never_crewed():
    eng = make_engine("p1", "p2")
    put(eng.state, balthier_card())
    v = put(eng.state, vehicle_card(crew=1, power=3, toughness=3))
    other = put(eng.state, bear_card(power=5, toughness=5))
    p1 = eng.state.player_by_id("p1")

    # crew it with a random creature — not Balthier and Fran itself
    eng.activate_ability(p1, v, 0, x=0, tap_choices=[other.instance_id])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert v.is_creature is True
    assert v.crewed_by_ids == [other.instance_id]

    _to_declare_attackers(eng)
    p1.mana_pool.add("R", 1)
    p1.mana_pool.add("G", 1)
    p1.mana_pool.add("C", 1)
    eng.declare_attackers(p1, [v])
    eng.resolve_until_stable()

    assert eng.state.pending_choice is None  # Balthier's trigger never fired


# -- Tifa, Martial Artist -----------------------------------------------


def tifa_card():
    return Card(
        id="Tifa, Martial Artist", name="Tifa, Martial Artist",
        type_line="Legendary Creature — Human Monk", is_creature=True,
        power=4, toughness=4, keywords=["Melee"],
        oracle_text=(
            "Melee (Whenever this creature attacks, it gets +1/+1 until "
            "end of turn for each opponent you attacked this combat.)\n"
            "Whenever one or more creatures you control with power 7 or "
            "greater deal combat damage to a player, untap all creatures "
            "you control. If it's the first combat phase of your turn, "
            "there is an additional combat phase after this phase."
        ),
    )


def test_tifa_is_registered():
    assert is_registered("Tifa, Martial Artist")


def test_tifa_fires_once_for_two_simultaneous_qualifying_attackers():
    eng = make_engine("p1", "p2")
    put(eng.state, tifa_card())
    big1 = put(eng.state, bear_card("Big One", power=7, toughness=7))
    big2 = put(eng.state, bear_card("Big Two", power=8, toughness=8))
    p1 = eng.state.player_by_id("p1")

    _to_declare_attackers(eng)
    eng.declare_attackers(p1, [big1, big2])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    eng.resolve_until_stable()

    assert big1.tapped is False  # untapped by the trigger
    assert big2.tapped is False
    # Exactly one extra combat phase queued — not two, even though two
    # qualifying creatures dealt damage simultaneously in the same step
    # (the whole reason CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER is a
    # once-per-(controller, target)-pair aggregate rather than reusing the
    # ordinary per-creature DAMAGE event).
    assert eng.state.pending_extra_combats == [False]


def test_tifa_does_not_fire_below_the_power_threshold():
    eng = make_engine("p1", "p2")
    put(eng.state, tifa_card())
    small = put(eng.state, bear_card(power=6, toughness=6))
    other = put(eng.state, bear_card("Tapped Bystander", power=1, toughness=1), tapped=True)
    p1 = eng.state.player_by_id("p1")

    _to_declare_attackers(eng)
    eng.declare_attackers(p1, [small])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    eng.resolve_until_stable()

    assert other.tapped is True  # never untapped — the trigger didn't fire
    assert eng.state.pending_extra_combats == []
