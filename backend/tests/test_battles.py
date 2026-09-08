"""Battles (RULE 310): defense counters, attacking, the protector, and the
Siege defeat/transform cycle.

Reference: CR 310.1-310.11b. The engine-side narrative lives in
`docs/implementation-state/Done_Backend.md` ("Battles").
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.parser.oracle.gate import parse_oracle


def battle(name="Invasion of Testland", defense=3, subtype="Siege", **kw):
    """A battle card. Real battles are transforming DFCs, so a back face is
    given by default — RULE 310.11b's defeat ability needs one."""
    kw.setdefault("layout", "transform")
    kw.setdefault("back_name", f"{name} Reverse")
    kw.setdefault("back_type_line", "Creature — Phyrexian")
    kw.setdefault("back_power", 3)
    kw.setdefault("back_toughness", 3)
    return Card(
        id=name, name=name,
        type_line=f"Battle — {subtype}" if subtype else "Battle",
        defense=defense, **kw,
    )


def creature(name="Bear", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _enter_battle(eng, card, controller="p1", protector="p2"):
    """Put a battle onto the battlefield the way a resolving spell does —
    through the entry-choice pipeline, so RULE 310.8a's protector pick
    happens — and answer that pick if it actually stops to ask."""
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    eng.rules._offer_protector_choice(obj, lambda: None)
    if eng.state.pending_choice:
        eng.rules.resolve_protector_choice(protector)
    eng.state.add_to_battlefield(obj)
    return obj


# -- Card/GameObject model ---------------------------------------------------


def test_battle_card_type_and_subtype_predicates():
    assert battle().is_battle and battle().is_siege
    plain = battle(subtype="")
    assert plain.is_battle and not plain.is_siege
    assert not creature().is_battle


def test_battle_enters_with_defense_counters_equal_to_printed_defense():
    # RULE 310.4b/310.4c.
    eng = make_engine()
    obj = _enter_battle(eng, battle(defense=4))
    assert obj.counters["defense"] == 4
    assert obj.defense == 4


def test_a_battle_with_no_printed_defense_seeds_nothing():
    eng = make_engine()
    obj = _enter_battle(eng, battle(defense=None))
    assert "defense" not in obj.counters


# -- Damage (RULE 310.6) -----------------------------------------------------


def test_damage_to_a_battle_removes_defense_counters():
    eng = make_engine()
    obj = _enter_battle(eng, battle(defense=4))
    eng.rules.deal_damage(obj, 3, source=_put(eng, creature()))
    assert obj.defense == 1
    # …and it is *not* tracked as marked damage the way a creature's is.
    assert obj.damage_marked == 0


def test_noncombat_damage_chips_a_battle_too():
    # RULE 310.6 is unqualified — a burn spell removes counters like an
    # attacker does.
    eng = make_engine()
    obj = _enter_battle(eng, battle(defense=4))
    eng.rules.deal_damage(obj, 2, source=_put(eng, creature()), combat=False)
    assert obj.defense == 2


def test_overkill_damage_floors_defense_at_zero():
    eng = make_engine()
    obj = _enter_battle(eng, battle(defense=2))
    eng.rules.deal_damage(obj, 99, source=_put(eng, creature()))
    assert obj.defense == 0


# -- Protector (RULE 310.8) --------------------------------------------------


def test_a_sieges_protector_must_be_an_opponent():
    # RULE 310.11a.
    eng = make_engine()
    obj = _enter_battle(eng, battle(), controller="p1")
    assert obj.protector_id == "p2"


def test_a_battle_with_no_subtype_is_protected_by_its_own_controller():
    # RULE 310.8a's fallback for a battle with no battle types.
    eng = make_engine()
    obj = _enter_battle(eng, battle(subtype=""), controller="p1")
    assert obj.protector_id == "p1"


def test_the_protector_choice_is_offered_when_several_opponents_qualify():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
        starting_life=20, starting_hand=0,
    )
    obj = GameObject(battle(), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.rules._offer_protector_choice(obj, lambda: None)
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_protector"
    assert {o["id"] for o in choice["options"]} == {"p2", "p3"}
    eng.rules.resolve_protector_choice("p3")
    assert obj.protector_id == "p3"


def test_an_unrecognized_protector_answer_falls_back_to_an_eligible_player():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
        starting_life=20, starting_hand=0,
    )
    obj = GameObject(battle(), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.rules._offer_protector_choice(obj, lambda: None)
    eng.rules.resolve_protector_choice("nobody")
    assert obj.protector_id in ("p2", "p3")


# -- Attacking a battle (RULE 310.5/310.8b) ----------------------------------


def _to_declare_attackers(eng):
    eng.state.current_step = "declare_attackers"


def test_a_battle_is_offered_as_a_defender_to_the_non_protector():
    eng = make_engine()
    obj = _enter_battle(eng, battle(), controller="p1", protector="p2")
    _to_declare_attackers(eng)
    kinds = {(d["kind"], d.get("instance_id")) for d in eng.legal_defenders_for(eng.state.player_by_id("p1"))}
    assert ("battle", obj.instance_id) in kinds


def test_a_siege_can_be_attacked_by_its_own_controller():
    # RULE 310.8b calls this out explicitly — it is the card's whole point.
    eng = make_engine()
    obj = _enter_battle(eng, battle(), controller="p1", protector="p2")
    bear = _put(eng, creature(), controller="p1")
    _to_declare_attackers(eng)
    spec = next(d for d in eng.legal_defenders_for(eng.state.player_by_id("p1"))
                if d["kind"] == "battle")
    eng.declare_attackers(eng.state.player_by_id("p1"), [{"attacker": bear, "defender": spec}])
    assert bear.combat_defender["kind"] == "battle"


def test_the_protector_is_never_offered_its_own_battle_as_a_defender():
    # RULE 310.8b: "a battle's protector can never attack it."
    eng = make_engine()
    _enter_battle(eng, battle(), controller="p1", protector="p2")
    defenders = eng.legal_defenders_for(eng.state.player_by_id("p2"))
    assert not any(d["kind"] == "battle" for d in defenders)


def test_the_defending_player_for_a_battle_is_its_protector():
    # RULE 310.8d.
    eng = make_engine()
    obj = _enter_battle(eng, battle(), controller="p1", protector="p2")
    bear = _put(eng, creature(), controller="p1")
    _to_declare_attackers(eng)
    spec = next(d for d in eng.legal_defenders_for(eng.state.player_by_id("p1"))
                if d["kind"] == "battle")
    eng.declare_attackers(eng.state.player_by_id("p1"), [{"attacker": bear, "defender": spec}])
    assert eng._defending_player(bear.combat_defender).id == "p2"


def test_only_the_protector_may_block_an_attacker_hitting_their_battle():
    # RULE 310.8c.
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
        starting_life=20, starting_hand=0,
    )
    _enter_battle(eng, battle(), controller="p1", protector="p2")
    bear = _put(eng, creature(), controller="p1")
    _to_declare_attackers(eng)
    spec = next(d for d in eng.legal_defenders_for(eng.state.player_by_id("p1"))
                if d["kind"] == "battle")
    eng.declare_attackers(eng.state.player_by_id("p1"), [{"attacker": bear, "defender": spec}])
    eng.state.current_step = "declare_blockers"
    protector_blocker = _put(eng, creature("Wall"), controller="p2")
    bystander = _put(eng, creature("Bystander"), controller="p3")
    assert eng.can_block(eng.state.player_by_id("p2"), protector_blocker, bear)
    assert not eng.can_block(eng.state.player_by_id("p3"), bystander, bear)


def test_combat_damage_to_a_battle_removes_defense_counters():
    eng = make_engine()
    obj = _enter_battle(eng, battle(defense=4), controller="p1", protector="p2")
    bear = _put(eng, creature(power=3), controller="p1")
    _to_declare_attackers(eng)
    spec = next(d for d in eng.legal_defenders_for(eng.state.player_by_id("p1"))
                if d["kind"] == "battle")
    eng.declare_attackers(eng.state.player_by_id("p1"), [{"attacker": bear, "defender": spec}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert obj.defense == 1


# -- Defeat + the RULE 310.7 SBA ---------------------------------------------


def test_a_defeated_siege_puts_its_own_ability_on_the_stack_first():
    # RULE 310.11b fires; RULE 310.7 must *not* bin the battle while that
    # ability is still on the stack.
    eng = make_engine()
    obj = _enter_battle(eng, battle(defense=1))
    eng.rules.deal_damage(obj, 1, source=_put(eng, creature()))
    eng.rules.check_state_based_actions()
    assert any(item.source is obj for item in eng.state.stack)
    assert obj in eng.state.battlefield


def test_the_defeat_ability_only_triggers_once():
    eng = make_engine()
    obj = _enter_battle(eng, battle(defense=1))
    eng.rules.deal_damage(obj, 1, source=_put(eng, creature()))
    for _ in range(4):
        eng.rules.check_state_based_actions()
    assert sum(1 for item in eng.state.stack if item.source is obj) == 1


def test_resolving_the_defeat_ability_exiles_it_transformed_and_castable():
    # RULE 310.11b: "exile it, then you may cast it transformed without
    # paying its mana cost."
    eng = make_engine()
    obj = _enter_battle(eng, battle(defense=1))
    eng.rules.deal_damage(obj, 1, source=_put(eng, creature()))
    eng.rules.check_state_based_actions()
    eng.rules.resolve_top_of_stack()
    assert obj.zone == Zone.EXILE
    assert obj.card.name.endswith("Reverse")          # flipped to the back face
    assert obj.instance_id in eng.state.free_cast_instance_ids
    assert obj not in eng.state.battlefield


def test_the_defeated_backs_own_cost_is_free_not_the_fronts():
    # Regression: `Card.back_face()` used to stamp the *front's*
    # `converted_mana_cost` onto the transformed back face regardless of the
    # back's own (blank, per `battle()`'s fixture default) mana cost string
    # — reusing a nonzero front CMC alongside a blank back cost string made
    # `ManaCost.from_card` reconstruct a fake nonzero generic cost for what
    # should have been a free RULE 310.11b recast. This checks the back
    # face's own cost directly, independent of the free-cast-window bypass
    # `test_resolving_the_defeat_ability_exiles_it_transformed_and_castable`
    # already covers (which would mask this bug, since it never re-checks
    # affordability once that flag is set).
    eng = make_engine()
    # A nonzero front cost is the point: `battle()`'s own default (an unset
    # mana_cost_string/converted_mana_cost, both 0) wouldn't distinguish the
    # bug from correct behaviour, since a stolen front CMC of 0 looks free
    # either way.
    card = battle(defense=1, mana_cost_string="{3}{R}{R}", converted_mana_cost=5)
    obj = _enter_battle(eng, card)
    eng.rules.deal_damage(obj, 1, source=_put(eng, creature()))
    eng.rules.check_state_based_actions()
    eng.rules.resolve_top_of_stack()
    assert obj.zone == Zone.EXILE
    back = card.back_face()
    assert back.mana_cost_string == ""
    assert back.converted_mana_cost == 0


def test_a_non_siege_battle_at_zero_defense_just_goes_to_the_graveyard():
    # RULE 310.7 without RULE 310.11b's Siege-only defeat ability.
    eng = make_engine()
    obj = _enter_battle(eng, battle(subtype="", defense=1), controller="p1")
    eng.rules.deal_damage(obj, 1, source=_put(eng, creature()))
    eng.rules.check_state_based_actions()
    assert obj in eng.state.player_by_id("p1").graveyard


# -- RULE 310.10 / 310.9 -----------------------------------------------------


def test_a_siege_with_no_eligible_protector_is_put_into_the_graveyard():
    # RULE 310.10 — which is also what makes a Siege unplayable in a solo
    # goldfish, where its controller has no opponents at all.
    eng = GameEngine.new_game([("p1", "Solo", [])], starting_life=20, starting_hand=0)
    obj = _enter_battle(eng, battle(), controller="p1", protector=None)
    assert obj.protector_id is None
    eng.rules.check_state_based_actions()
    assert obj in eng.state.player_by_id("p1").graveyard


def test_a_battle_cannot_be_attached_to():
    # RULE 310.9.
    eng = make_engine()
    obj = _enter_battle(eng, battle())
    aura = _put(eng, Card(id="A", name="Aura", type_line="Enchantment — Aura"))
    aura.parametric_keywords = {"enchant": {"what": "permanent"}}
    assert not eng.rules._attachment_legal(aura, obj)


# -- Wire view ---------------------------------------------------------------


def test_the_board_view_carries_defense_and_protector():
    eng = make_engine()
    obj = _enter_battle(eng, battle(defense=3), controller="p1", protector="p2")
    data = obj.to_dict()
    assert data["is_battle"] is True
    assert data["defense"] == 3
    assert data["protector_id"] == "p2"


def test_a_non_battle_reports_no_defense_or_protector():
    eng = make_engine()
    data = _put(eng, creature()).to_dict()
    assert data["is_battle"] is False
    assert data["defense"] is None and data["protector_id"] is None


def test_replay_export_round_trips_defense_and_protector():
    # Defense rides the generic `counters` dict; the protector is per-object
    # state with no card to re-derive it from, so it needs its own field —
    # otherwise RULE 310.10's SBA would silently pick a new one on reload.
    from mtg_analyzer.services.replay import serialize_replay, build_replay_engine

    eng = make_engine()
    obj = _enter_battle(eng, battle(defense=4), controller="p1", protector="p2")
    obj.add_counters("defense", -1)

    payload = serialize_replay(eng.state)
    entry = next(inst for inst in payload["battlefield"] if inst["name"] == obj.name)
    assert entry["protector_id"] == "p2"
    assert entry["counters"]["defense"] == 3


# -- Oracle parser -----------------------------------------------------------


@pytest.mark.parametrize("text", [
    # RULE 310's own reminder text is stripped, and "this Siege"/"this
    # battle" fold to the ordinary self-reference, so a battle's ETB is an
    # ordinary triggered ability.
    "(As a Siege enters, choose an opponent to protect it. You and others can "
    "attack it. When it's defeated, exile it, then cast it transformed.)\n"
    "When this Siege enters, you gain 4 life and draw a card.",
    "When this battle enters, you gain 2 life.",
])
def test_a_battles_own_etb_clause_is_modeled(text):
    card = battle(oracle_text=text)
    assert parse_oracle(card).coverage == "MODELED"


def test_the_self_reference_fold_reaches_a_sieges_own_damage_clause():
    card = battle(oracle_text="When this Siege enters, it deals 3 damage to "
                              "any other target and you gain 3 life.")
    assert parse_oracle(card).coverage == "MODELED"
