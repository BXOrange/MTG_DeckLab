"""MEC-88 — Banding (RULE 702.22). `game/combat.py` had zero Banding logic
before this ticket. The behavioural payoff is RULE 702.22j's damage-
assignment reroute: when Banding is involved on either side of a block,
the defending player's order (modeled here as an even split, no trample-
favouring) replaces the attacker's own lethal-first-then-trample order —
`game/engine/combat_mixin.py`'s `_assign_blocked_attacker`.

RULE 702.22c's interactive attacking-*band* declaration is deliberately
out of scope (no MODELED Commander-legal card exercises it); "bands with
other `<quality>`" collapses to plain Banding throughout.
"""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, keywords=None, power=2, toughness=2, oracle_text=""):
    return Card(
        id=name, name=name, type_line="Creature — Human", is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []),
    )


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_banding_still_parses_as_a_flag_keyword():
    card = _creature("Bander", keywords=["Banding"])
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    assert "banding" in combat._obj_keywords(obj)


def test_quoted_bands_with_other_grant_collapses_to_plain_banding():
    card = Card(
        id="Cathedral of Serra", name="Cathedral of Serra", type_line="Land",
        oracle_text='White legendary creatures you control have "bands with other legendary creatures."',
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    effect = result.specs[0].effects[0]
    assert effect.type == "grant_keyword"
    assert effect.params["keywords"] == ["banding"]


def test_lose_banding_grant_until():
    card = Card(
        id="Shelkin Brownie", name="Shelkin Brownie", type_line="Creature — Faerie",
        is_creature=True, power=1, toughness=1,
        oracle_text='{T}: Target creature loses all "bands with other" abilities until end of turn.',
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    effect = result.specs[0].effects[0]
    assert effect.type == "grant_until"
    assert effect.params["static"]["type"] == "remove_keyword"
    assert effect.params["static"]["params"]["keywords"] == ["banding"]
    assert effect.params["duration"] == "end_of_turn"


def test_master_of_the_hunt_hand_authored():
    from mtg_analyzer.game.ability_catalogue.core import specs_for

    card = Card(
        id="Master of the Hunt", name="Master of the Hunt",
        type_line="Creature — Human", is_creature=True, power=2, toughness=2,
        oracle_text=(
            '{2}{G}{G}: Create a 1/1 green Wolf creature token named Wolves '
            'of the Hunt. It has "bands with other creatures named Wolves '
            'of the Hunt."'
        ),
    )
    specs = specs_for(card)
    assert specs is not None
    activated = [s for s in specs if s.ability_kind == "activated"]
    assert len(activated) == 1
    effect = activated[0].effects[0]
    assert effect.type == "create_token"
    assert effect.params["token_name"] == "Wolves of the Hunt"
    assert effect.params["keywords"] == ["banding"]


# -- RULE 702.22j: the damage-assignment reroute ----------------------------


def _combat_damage_amounts(blocker_keywords_for_second):
    """The (b1_amount, b2_amount) combat-damage split the attacker's
    power gets divided into, read off the DAMAGE events fired during the
    combat-damage step (both blockers die from either split at these
    stats, so post-SBA `damage_marked` can't distinguish them — the
    objects are also reset to a *new* object identity on leaving the
    battlefield, RULE 400.7, which zeroes it anyway)."""
    eng = _engine()
    state = eng.state
    attacker = _put(state, _creature("Big Attacker", power=6, toughness=6))
    b1 = _put(state, _creature("Chump A", power=2, toughness=2), controller="p2")
    b2 = _put(
        state,
        _creature("Chump B", power=2, toughness=2, keywords=blocker_keywords_for_second),
        controller="p2",
    )
    eng.recompute_continuous_effects()
    eng.start()
    while state.current_step != "declare_attackers":
        eng.advance_step()
    eng.declare_attackers(state.active_player, [attacker])
    eng.advance_step()
    defender = state.player_by_id("p2")
    eng.declare_blockers(defender, [
        {"blocker": b1, "attacker": attacker},
        {"blocker": b2, "attacker": attacker},
    ])
    seen: list = []
    state.subscribe(lambda e: seen.append(e))
    for _ in range(8):
        eng.advance_step()
        if state.current_step == "end_combat":
            break
    hits = {
        e.data["target_id"]: e.data["amount"]
        for e in seen
        if e.type == "DAMAGE" and e.data.get("source_id") == attacker.instance_id
    }
    return hits.get(b1.instance_id, 0), hits.get(b2.instance_id, 0)


def test_banding_blocker_reroutes_damage_assignment_to_an_even_split():
    # A 6-power attacker blocked by two 2/2s, one with Banding: RULE
    # 702.22j reroutes the order to the defending player — modeled as an
    # even split (3/3) rather than the ordinary lethal-first order (which
    # would have been 2 to the first blocker, 4 dumped on the second).
    b1_amount, b2_amount = _combat_damage_amounts(["Banding"])
    assert (b1_amount, b2_amount) == (3, 3)


def test_no_banding_uses_the_ordinary_lethal_first_order():
    # Baseline (no Banding involved): lethal (2) to the first blocker,
    # the remainder (4) dumped on the last — unchanged from before this
    # ticket, confirming the reroute is strictly additive.
    b1_amount, b2_amount = _combat_damage_amounts([])
    assert (b1_amount, b2_amount) == (2, 4)
