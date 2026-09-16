"""MEC-52 — the last three cards of PAR-29's keyword trail (PAR-30
close-out), each blocking on a distinct engine primitive rather than oracle
grammar, so hand-authored in `game/card_registry/special_mechanics.py`.

- **Hunted by The Family** — `FaceVillainousChoiceEffect`
  ``subject="previous_target_controller"``: the RULE 115 targets are the
  creatures, each one's controller gets its own queued `villainous_choice`
  (`_request_villainous_choice(rounds=…)`) with that creature baked in as the
  RULE 608.2 referent, and the option bodies act on the *creature*.
- **Ensnared by the Mara** — `dig_until` ``digger="facing"`` /
  ``caster="controller"`` (dig an opponent's library, *you* get the free
  cast), and the `exile_top_then_damage_by_mv` summed-mana-value damage
  source.
- **Back from the Brink** — `BackFromTheBrinkEffect` /
  `PayCostThenPreviousMvEffect`: a pick-then-price cost modeled as a
  resolution-time flow, plus `_request_pay_cost_then` ``captured_previous``.
"""

from __future__ import annotations

from mtg_analyzer.game import card_registry as ac
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine(players=2, life=20):
    seats = [(f"p{i+1}", chr(65 + i), []) for i in range(players)]
    eng = GameEngine.new_game(seats, starting_life=life, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _bear(name, power=2, toughness=2):
    return Card(id=name[:8], name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def _src(st, name="Src", type_line="Enchantment"):
    o = GameObject(Card(id=name[:6], name=name, type_line=type_line),
                   owner_id="p1", zone=Zone.BATTLEFIELD)
    o.controller_id = "p1"
    st.add_to_battlefield(o)
    return o


def _put_bf(st, card, pid):
    o = GameObject(card, owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    st.add_to_battlefield(o)
    return o


def _lib(st, pid, cards):
    p = st.player_by_id(pid)
    for c in cards:
        p.library.append(GameObject(c, owner_id=pid, zone=Zone.LIBRARY))


# --- the villainous "rounds" generalization ------------------------------------


def test_request_villainous_choice_rounds_are_independent():
    eng = _engine(3)
    st = eng.state
    src = _src(st)
    b2 = _put_bf(st, _bear("P2Bear"), "p2")
    b3 = _put_bf(st, _bear("P3Bear"), "p3")

    eng.rules._request_villainous_choice(
        source=src, controller_id="p1",
        rounds=[
            {"facing_id": "p2",
             "option_a": [{"type": "lose_life", "params": {"amount": 2, "target_kind": "player"}}],
             "option_b": [{"type": "lose_life", "params": {"amount": 9, "target_kind": "player"}}],
             "captured": [b2]},
            {"facing_id": "p3",
             "option_a": [{"type": "lose_life", "params": {"amount": 2, "target_kind": "player"}}],
             "option_b": [{"type": "lose_life", "params": {"amount": 9, "target_kind": "player"}}],
             "captured": [b3]},
        ],
    )
    assert st.pending_choice["player_id"] == "p2"
    eng.resolve_pending_choice("0")          # p2 takes A (−2)
    eng.resolve_until_stable()
    assert st.player_by_id("p2").life == 18
    assert st.pending_choice["player_id"] == "p3"
    eng.resolve_pending_choice("1")          # p3 takes B (−9)
    eng.resolve_until_stable()
    assert st.player_by_id("p3").life == 11
    assert st.pending_choice is None


# --- Hunted by The Family -----------------------------------------------------


def test_hunted_registered_and_returns_fresh_specs():
    card = Card(id="x", name="Hunted by The Family", type_line="Sorcery")
    specs = ac.specs_for(card)
    assert specs is not None and len(specs) == 1
    s = specs[0]
    assert s.ability_kind == "spell_effect"
    assert s.effects[0].type == "face_villainous_choice"
    assert s.effects[0].params["subject"] == "previous_target_controller"
    again = ac.specs_for(card)
    assert again is not specs and again[0] is not s


def _hunted_effect(src):
    spec = ac.specs_for(src.card)[0]
    return build_effects(
        [EffectSpec(e.type, dict(e.params)) for e in spec.effects], src
    )[0]


def test_hunted_option_a_makes_the_creature_a_vanilla_1_1_white_human():
    eng = _engine(2)
    st = eng.state
    src = GameObject(Card(id="H", name="Hunted by The Family", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    victim = _put_bf(st, _bear("Big Bear", 6, 6), "p2")
    # give it an ability so "loses all abilities" is observable
    victim.card.oracle_text = "Flying"
    victim.card.keywords = ["Flying"]

    _hunted_effect(src).apply(eng.rules.context, targets=[victim])
    assert st.pending_choice["player_id"] == "p2"   # that creature's controller
    eng.resolve_pending_choice("0")                 # option A
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert (victim.power, victim.toughness) == (1, 1)
    assert victim.is_creature
    assert "Human" in (victim._derived_subtypes or set())
    assert victim.loses_all_abilities
    assert st.pending_choice is None


def test_hunted_option_b_makes_a_token_copy_under_your_control_per_target():
    eng = _engine(3)
    st = eng.state
    src = GameObject(Card(id="H", name="Hunted by The Family", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    v2 = _put_bf(st, _bear("Golem Two", 3, 3), "p2")
    v3 = _put_bf(st, _bear("Ogre Three", 4, 4), "p3")

    _hunted_effect(src).apply(eng.rules.context, targets=[v2, v3])

    # round 1 — p2 decides about their creature
    assert st.pending_choice["player_id"] == "p2"
    eng.resolve_pending_choice("1")   # option B — you make a copy
    eng.resolve_until_stable()
    # round 2 — p3 decides about theirs
    assert st.pending_choice["player_id"] == "p3"
    eng.resolve_pending_choice("1")
    eng.resolve_until_stable()

    tokens = [o for o in st.battlefield if o.is_token]
    assert sorted(t.card.name for t in tokens) == ["Golem Two", "Ogre Three"]
    assert all(t.controller_id == "p1" for t in tokens)   # "you create"
    assert st.pending_choice is None


def test_hunted_with_no_targets_does_nothing():
    eng = _engine(2)
    st = eng.state
    src = GameObject(Card(id="H", name="Hunted by The Family", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    _hunted_effect(src).apply(eng.rules.context, targets=[])
    assert st.pending_choice is None


# --- Ensnared by the Mara ---------------------------------------------------


def test_ensnared_registered_shape():
    card = Card(id="e", name="Ensnared by the Mara", type_line="Sorcery")
    specs = ac.specs_for(card)
    assert specs and specs[0].effects[0].type == "face_villainous_choice"
    p = specs[0].effects[0].params
    assert p["subject"] == "each_opponent"
    assert p["option_a"][0]["type"] == "dig_until"
    assert p["option_a"][0]["params"]["digger"] == "facing"
    assert p["option_a"][0]["params"]["caster"] == "controller"
    assert p["option_b"][0]["type"] == "seq"


def _ensnared_effect(src):
    spec = ac.specs_for(src.card)[0]
    return build_effects(
        [EffectSpec(e.type, dict(e.params)) for e in spec.effects], src
    )[0]


def test_ensnared_option_b_deals_summed_mana_value_damage():
    eng = _engine(2)
    st = eng.state
    src = GameObject(Card(id="E", name="Ensnared by the Mara", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    # top of library is the *end* of the list — order these so the top 4 are
    # the MV 3/2/5/1 cards (sum 11); the 5th (MV 8) stays.
    _lib(st, "p2", [
        Card(id="keep", name="Deep One", type_line="Creature", converted_mana_cost=8),
        Card(id="d", name="D", type_line="Sorcery", converted_mana_cost=1),
        Card(id="c", name="C", type_line="Instant", converted_mana_cost=5),
        Card(id="b", name="B", type_line="Creature", converted_mana_cost=2),
        Card(id="a", name="A", type_line="Creature", converted_mana_cost=3),
    ])
    _ensnared_effect(src).apply(eng.rules.context, targets=None)

    assert st.pending_choice["player_id"] == "p2"
    eng.resolve_pending_choice("1")   # option B
    eng.resolve_until_stable()

    assert st.player_by_id("p2").life == 20 - 11
    assert len(st.player_by_id("p2").exile) == 4
    assert len(st.player_by_id("p2").library) == 1


def test_ensnared_option_a_you_get_the_free_cast_of_the_opponents_card():
    eng = _engine(2)
    st = eng.state
    src = GameObject(Card(id="E", name="Ensnared by the Mara", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    # dig hits the first nonland from the top: two lands then a spell.
    spell = Card(id="spell", name="Free Spell", type_line="Instant",
                 is_instant=True, converted_mana_cost=3, mana_cost_string="{2}{R}")
    _lib(st, "p2", [
        Card(id="land0", name="Plains0", type_line="Land"),
        spell,
        Card(id="land1", name="Plains1", type_line="Land"),
        Card(id="land2", name="Plains2", type_line="Land"),
    ])
    _ensnared_effect(src).apply(eng.rules.context, targets=None)

    assert st.pending_choice["player_id"] == "p2"
    eng.resolve_pending_choice("0")   # option A — dig until a nonland
    eng.resolve_until_stable()

    spell_obj = next(o for o in st.player_by_id("p2").exile if o.card.name == "Free Spell")
    # RULE 601.3e — you become its controller, and it's a free cast for you
    assert spell_obj.controller_id == "p1"
    assert spell_obj.instance_id in st.free_cast_instance_ids


# --- Back from the Brink ---------------------------------------------------


def test_back_from_the_brink_binds_a_sorcery_speed_activated_ability():
    eng = _engine(2)
    st = eng.state
    o = GameObject(Card(id="BFTB", name="Back from the Brink",
                        type_line="Enchantment", mana_cost_string="{4}{U}{U}"),
                   owner_id="p1", zone=Zone.BATTLEFIELD)
    o.controller_id = "p1"
    st.add_to_battlefield(o)
    bind_from_catalogue(o)
    assert len(o.activated_abilities) == 1
    assert o.activated_abilities[0].cost.sorcery_speed_only is True


def _bftb_effect(src):
    spec = ac.specs_for(src.card)[0]
    return build_effects(
        [EffectSpec(spec.effects[0].type, dict(spec.effects[0].params))], src
    )[0]


def test_back_from_the_brink_pay_makes_a_copy_of_the_exiled_creature():
    eng = _engine(2)
    st = eng.state
    src = GameObject(Card(id="BFTB", name="Back from the Brink", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    dead = GameObject(_bear("Buried Bear", 5, 4), owner_id="p1", zone=Zone.GRAVEYARD)
    dead.card.mana_cost_string = "{1}{G}"
    dead.card.converted_mana_cost = 2
    st.player_by_id("p1").graveyard.append(dead)
    st.player_by_id("p1").mana_pool.add("G", 5)

    _bftb_effect(src).apply(eng.rules.context)
    # only one candidate ⇒ auto-exiled, then the pay-cost-then choice opens
    assert dead.zone == Zone.EXILE
    assert st.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()

    tokens = [o for o in st.battlefield if o.is_token]
    assert len(tokens) == 1 and tokens[0].card.name == "Buried Bear"
    assert tokens[0].controller_id == "p1"


def test_back_from_the_brink_decline_makes_no_token():
    eng = _engine(2)
    st = eng.state
    src = GameObject(Card(id="BFTB", name="Back from the Brink", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    dead = GameObject(_bear("Buried Bear"), owner_id="p1", zone=Zone.GRAVEYARD)
    dead.card.mana_cost_string = "{1}{G}"
    st.player_by_id("p1").graveyard.append(dead)
    st.player_by_id("p1").mana_pool.add("G", 5)

    _bftb_effect(src).apply(eng.rules.context)
    assert st.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert not [o for o in st.battlefield if o.is_token]


def test_back_from_the_brink_empty_graveyard_is_a_no_op():
    eng = _engine(2)
    st = eng.state
    src = GameObject(Card(id="BFTB", name="Back from the Brink", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    _bftb_effect(src).apply(eng.rules.context)
    assert st.pending_choice is None
