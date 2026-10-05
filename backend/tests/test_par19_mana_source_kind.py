"""PAR-19's own genuinely new primitive: RULE 605.3a's *subtractive*
direction — "Spend only mana produced by Treasures/basic lands/creatures to
cast `<spell>`." (Security Rhox/Imperiosaur/Myr Superion) — the inverse of
the already-shipped *additive* restricted-lot mechanism (`ManaPool.
restricted`/`allows_restriction`, which only ever adds extra usable mana on
top of the ordinary pool, and so has no way to reject perfectly ordinary
pool mana that came from the wrong kind of permanent).

`ManaPool.pool_by_source` is a shadow tally, always kept in exact sync with
``pool`` (every `add()` call with ``restriction=None`` — the only case that
lands in ``pool`` — also lands in the matching `source_kind` bucket, default
bucket ``None``), consulted only when a caller passes the new
``require_source_kind`` param to `can_pay`/`pay` — every pre-existing call
site never does, so this is pure bookkeeping overhead for them, not a
behaviour change (see the regression-free coverage diff this shipped with).
`game/mana_abilities.mana_source_kind_for` classifies a tapped permanent at
the two real mana-production call sites (`GameEngine.tap_for_mana`, `game/
mana_potential.py`'s tap-plan search).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.models.mana.mana_pool import ManaPool
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def put(state, card, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    return obj


def basic_forest(name="A Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def treasure(name="A Treasure"):
    return Card(
        id=name, name=name, type_line="Artifact — Treasure",
        oracle_text="{T}, Sacrifice this artifact: Add one mana of any color.",
    )


def mana_dork(name="A Mana Dork", color="G"):
    return Card(
        id=name, name=name, type_line="Creature — Elf Druid", is_creature=True,
        power=1, toughness=1, oracle_text=f"{{T}}: Add {{{color}}}.",
    )


# -- ManaPool.pool_by_source / require_source_kind: unit-level --------------


def test_add_mirrors_pool_into_the_matching_source_bucket():
    pool = ManaPool()
    pool.add("G", 2, source_kind="basic_land")
    pool.add("R", 1, source_kind="treasure")
    pool.add("W", 1)  # no source_kind: the None/"unknown" bucket

    assert pool.pool == {"C": 0, "W": 1, "U": 0, "B": 0, "R": 1, "G": 2}
    assert pool.pool_by_source["basic_land"]["G"] == 2
    assert pool.pool_by_source["treasure"]["R"] == 1
    assert pool.pool_by_source[None]["W"] == 1


def test_require_source_kind_ignores_everything_else_in_the_pool():
    pool = ManaPool()
    pool.add("G", 3, source_kind="creature")  # plenty of green — wrong kind
    pool.add("G", 1, source_kind="basic_land")  # exactly enough — right kind

    cost = ManaCost.parse("{G}")
    assert pool.can_pay(cost, require_source_kind="creature") is True
    assert pool.can_pay(cost, require_source_kind="basic_land") is True

    two_green = ManaCost.parse("{G}{G}")
    # 3 creature-sourced green alone is plenty, but only 1 basic-land-sourced.
    assert pool.can_pay(two_green, require_source_kind="creature") is True
    assert pool.can_pay(two_green, require_source_kind="basic_land") is False


def test_require_source_kind_rejects_ordinary_untagged_mana():
    pool = ManaPool()
    pool.add("G", 5)  # plain, untagged mana — plenty, but not from a basic land
    cost = ManaCost.parse("{G}")
    assert pool.can_pay(cost) is True  # ordinary payment still works
    assert pool.can_pay(cost, require_source_kind="basic_land") is False


def test_pay_with_require_source_kind_drains_only_the_matching_bucket():
    pool = ManaPool()
    pool.add("G", 1, source_kind="creature")
    pool.add("G", 2, source_kind="basic_land")
    pool.pay(ManaCost.parse("{G}"), require_source_kind="basic_land")

    assert pool.pool["G"] == 2  # 3 - 1
    assert pool.pool_by_source["basic_land"]["G"] == 1
    assert pool.pool_by_source["creature"]["G"] == 1  # untouched


def test_ordinary_pay_drains_the_untagged_bucket_before_a_tagged_one():
    pool = ManaPool()
    pool.add("G", 1)  # untagged
    pool.add("G", 1, source_kind="treasure")
    pool.pay(ManaCost.parse("{G}"))  # no require_source_kind: ordinary payment

    assert pool.pool["G"] == 1
    assert pool.pool_by_source[None]["G"] == 0  # drained first
    assert pool.pool_by_source["treasure"]["G"] == 1  # preserved


def test_empty_clears_pool_by_source_too():
    pool = ManaPool()
    pool.add("G", 1, source_kind="treasure")
    pool.empty()
    assert pool.pool_by_source == {}
    assert pool.can_pay(ManaCost.parse("{G}"), require_source_kind="treasure") is False


# -- mana_source_kind_for: classifying a tapped permanent --------------------


def test_mana_source_kind_for_classifies_treasure_basic_land_creature():
    from mtg_analyzer.game.mana_abilities import mana_source_kind_for

    eng = make_engine("p1", "p2")
    t = put(eng.state, treasure())
    forest = put(eng.state, basic_forest())
    dork = put(eng.state, mana_dork())
    nonbasic = put(eng.state, Card(
        id="Nonbasic", name="Nonbasic", type_line="Land",
        oracle_text="{T}: Add {C}.", is_land=True,
    ))

    assert mana_source_kind_for(t) == "treasure"
    assert mana_source_kind_for(forest) == "basic_land"
    assert mana_source_kind_for(dork) == "creature"
    assert mana_source_kind_for(nonbasic) is None


def test_tap_for_mana_tags_pool_by_source():
    eng = make_engine("p1", "p2")
    forest = put(eng.state, basic_forest())
    p1 = eng.state.active_player

    eng.tap_for_mana(p1, forest)
    assert p1.mana_pool.pool_by_source["basic_land"]["G"] == 1


# -- Imperiosaur / Myr Superion: cast_mana_source_restriction ----------------


def imperiosaur_card():
    return Card(
        id="Imperiosaur", name="Imperiosaur", type_line="Creature — Dinosaur",
        is_creature=True, power=7, toughness=7,
        mana_cost_string="{5}{G}{G}", converted_mana_cost=7,
        oracle_text="Spend only mana produced by basic lands to cast this spell.",
    )


def test_imperiosaur_is_modeled():
    result = parse_oracle(imperiosaur_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_imperiosaur_rejects_creature_produced_mana():
    eng = make_engine("p1", "p2")
    obj = GameObject(imperiosaur_card(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.active_player.hand.append(obj)
    eng.state.current_step = "main1"
    assert getattr(obj, "mana_source_kind_restriction", None) == "basic_land"

    # 7 mana entirely from mana dorks (creatures) — plenty in raw amount,
    # but none of it is basic-land-produced.
    for i in range(7):
        dork = put(eng.state, mana_dork(f"Dork {i}"))
        eng.tap_for_mana(eng.state.active_player, dork)
    assert eng.state.active_player.mana_pool.total() == 7

    assert eng.can_cast(eng.state.active_player, obj) is False


def test_imperiosaur_is_castable_off_basic_land_mana():
    eng = make_engine("p1", "p2")
    obj = GameObject(imperiosaur_card(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.active_player.hand.append(obj)
    eng.state.current_step = "main1"

    for i in range(7):
        forest = put(eng.state, basic_forest(f"Forest {i}"))
        eng.tap_for_mana(eng.state.active_player, forest)
    assert eng.state.active_player.mana_pool.total() == 7

    assert eng.can_cast(eng.state.active_player, obj) is True
    eng.cast_spell(eng.state.active_player, obj)
    assert any(item.obj is obj for item in eng.state.stack)


def myr_superion_card():
    return Card(
        id="Myr Superion", name="Myr Superion", type_line="Artifact Creature — Myr",
        is_creature=True, power=4, toughness=4,
        mana_cost_string="{2}{W}{W}", converted_mana_cost=4,
        oracle_text="Spend only mana produced by creatures to cast this spell.",
    )


def test_myr_superion_is_modeled():
    result = parse_oracle(myr_superion_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_myr_superion_needs_creature_produced_mana():
    eng = make_engine("p1", "p2")
    obj = GameObject(myr_superion_card(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.active_player.hand.append(obj)
    eng.state.current_step = "main1"

    for i in range(4):
        forest = put(eng.state, basic_forest(f"Forest {i}"))
        eng.tap_for_mana(eng.state.active_player, forest)
    assert eng.can_cast(eng.state.active_player, obj) is False

    for i in range(4):
        dork = put(eng.state, mana_dork(f"Dork {i}", color="W"))
        eng.tap_for_mana(eng.state.active_player, dork)
    assert eng.can_cast(eng.state.active_player, obj) is True


# -- Security Rhox: alt_cost's own mana_source_kind --------------------------


def security_rhox_card():
    return Card(
        id="Security Rhox", name="Security Rhox", type_line="Creature — Rhino Soldier",
        is_creature=True, power=5, toughness=5,
        mana_cost_string="{4}{G}{W}", converted_mana_cost=6,
        oracle_text="You may pay {R}{G} rather than pay this spell's mana "
                    "cost. Spend only mana produced by Treasures to cast it "
                    "this way.",
    )


def test_security_rhox_is_modeled():
    result = parse_oracle(security_rhox_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_security_rhox_alt_cost_rejects_ordinary_land_mana():
    eng = make_engine("p1", "p2")
    obj = GameObject(security_rhox_card(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.active_player.hand.append(obj)
    eng.state.current_step = "main1"
    assert obj.alt_cast_cost.mana_source_kind == "treasure"

    mountain = put(eng.state, Card(
        id="A Mountain", name="A Mountain", type_line="Basic Land — Mountain", is_land=True,
    ))
    forest = put(eng.state, basic_forest())
    eng.tap_for_mana(eng.state.active_player, mountain)
    eng.tap_for_mana(eng.state.active_player, forest)

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False


def test_security_rhox_alt_cost_is_payable_from_treasures():
    eng = make_engine("p1", "p2")
    obj = GameObject(security_rhox_card(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.active_player.hand.append(obj)
    eng.state.current_step = "main1"

    t1 = put(eng.state, treasure("Treasure 1"))
    t2 = put(eng.state, treasure("Treasure 2"))
    eng.tap_for_mana(eng.state.active_player, t1, option_index=3)  # {R}
    eng.tap_for_mana(eng.state.active_player, t2, option_index=4)  # {G}

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is True
    eng.cast_spell(eng.state.active_player, obj, alt_cost=True)
    assert any(item.obj is obj for item in eng.state.stack)
