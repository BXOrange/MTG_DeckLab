"""The mechanisms that finish the cEDH staples cube (batch 26).

Batch 25 made all 43 cards of the pool playable but left a documented
residue of narrow simplifications behind, each recorded in its card's
`game/ability_catalogue.py` entry. This file covers the mechanisms that
close that residue:

* **Entwine** (RULE 702.42a) as a real priced modal upgrade — Tooth and Nail.
* **Per-card conditional search destinations** — Archdruid's Charm.
* **Face-down exile with a conditional cast window** — Beseech the Mirror.
* **The Ring tempts you** (RULE 701.51) — Boromir, Warden of the Tower.
* **Interactive** replacements for the auto-picks a real game would prompt
  for — Cloudstone Curio, Deadeye Navigator, Tangle Wire, Kinnan, Lim-Dûl's
  Vault, Professor Onyx, Tevesh Szat, Tibalt's Trickery, Possibility Storm.
* **Mutate under the pile** (RULE 702.140b) + its non-Human restriction.
* **Layer-6 ability removal** — Blood Moon.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player


def _engine():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state, p1, p2


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _card(name, type_line="Creature — Bear", cost="", cmc=0, **kw):
    # `Card`'s type booleans are explicit fields, not derived from the type
    # line, so fill them in from it here rather than at every call site.
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _bear(name="Bear"):
    return _card(name, "Creature — Bear", "{1}{G}", 2, is_creature=True, power=2, toughness=2)


def _bf(state, card, controller="p1", obj=None):
    obj = obj or GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _catalogue_obj(state, name, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(_named(name), owner_id=controller, zone=zone)
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    return obj


# ---------------------------------------------------------------------------
# Entwine (RULE 702.42a) — a priced "choose all" upgrade
# ---------------------------------------------------------------------------


def test_entwine_offers_a_separately_priced_both_action():
    engine, state, p1, _ = _engine()
    spell = _catalogue_obj(state, "Tooth and Nail", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 9)

    actions = [a for a in engine.legal_actions(p1) if a["type"] == "cast_spell"]
    both = [a for a in actions if a.get("mode") == "both"]
    assert len(both) == 1
    # RULE 702.42a: priced, unlike RULE 700.2e's free "or both".
    assert both[0]["entwine"] is True
    assert both[0]["entwine_cost"] == "{2}"
    assert not both[0].get("locked")
    # The single-mode offers are unchanged and carry no entwine tag.
    assert sorted(a["mode"] for a in actions if a["mode"] != "both") == [0, 1]
    assert all("entwine" not in a for a in actions if a["mode"] != "both")


def test_entwine_both_offer_is_locked_when_its_cost_is_unaffordable():
    """Tooth and Nail is {5}{G}{G}; entwined it costs {2} more."""
    engine, state, p1, _ = _engine()
    spell = _catalogue_obj(state, "Tooth and Nail", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 7)                      # exactly the printed cost

    both = [
        a for a in engine.legal_actions(p1)
        if a["type"] == "cast_spell" and a.get("mode") == "both"
    ]
    assert both and both[0]["locked"] is True
    assert both[0]["lock_reason"] == "Verflechten-Kosten nicht bezahlbar"


def test_entwine_charges_its_cost_and_resolves_every_mode():
    engine, state, p1, _ = _engine()
    fatty = GameObject(_bear("Fatty"), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(fatty, Zone.HAND)
    library_bear = GameObject(_bear("Library Bear"), owner_id="p1", zone=Zone.LIBRARY)
    p1.add_to_zone(library_bear, Zone.LIBRARY)

    spell = _catalogue_obj(state, "Tooth and Nail", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 9)
    engine.cast_spell(p1, spell, mode="both", entwine=True)
    # {5}{G}{G} + {2} entwine = 9 mana, so the pool is empty.
    assert p1.mana_pool.total() == 0

    engine.resolve_until_stable()
    # Mode 1 (search) resolves first, in printed order — and mode 2's own
    # interactive pick is *suspended* rather than overwriting this prompt.
    assert state.pending_choice["kind"] == "search"
    labels = {o["label"] for o in state.pending_choice["options"] if o["id"] != "decline"}
    assert labels == {"Library Bear"}
    assert state.deferred_effects, "mode 2 must be parked, not dropped"

    engine.resolve_pending_choice(str(library_bear.instance_id))
    engine.resolve_until_stable()

    # Mode 2 now gets its turn — and offers the just-tutored card too, which
    # is the whole point of entwining this particular spell.
    assert state.pending_choice["kind"] == "search"
    offered = {o["label"] for o in state.pending_choice["options"] if o["id"] != "decline"}
    assert offered == {"Fatty", "Library Bear"}
    engine.resolve_pending_choice(str(fatty.instance_id))
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(library_bear.instance_id))
    engine.resolve_until_stable()

    assert {o.name for o in state.battlefield} == {"Fatty", "Library Bear"}
    assert not state.deferred_effects


def test_entwine_both_is_illegal_without_paying_for_it():
    engine, state, p1, _ = _engine()
    spell = _catalogue_obj(state, "Tooth and Nail", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 9)
    with pytest.raises(ValueError, match="entwine"):
        engine.cast_spell(p1, spell, mode="both")


def test_entwine_is_illegal_on_a_spell_without_one():
    """``entwine=True`` isn't a free pass — a spell with no entwine cost
    can't be cast that way at all (RULE 702.42a)."""
    engine, state, p1, _ = _engine()
    bolt = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(bolt, Zone.HAND)
    p1.mana_pool.add("R", 5)
    assert engine.can_cast(p1, bolt, entwine=True) is False


# ---------------------------------------------------------------------------
# Conditional search destinations (RULE 701.19c) — Archdruid's Charm
# ---------------------------------------------------------------------------


def _archdruids_charm(engine, state, p1, *library):
    for card in library:
        p1.add_to_zone(GameObject(card, owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    spell = _catalogue_obj(state, "Archdruid's Charm", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 3)
    engine.cast_spell(p1, spell, mode=0)
    engine.resolve_until_stable()
    return spell


def test_conditional_search_destination_puts_a_land_onto_the_battlefield_tapped():
    engine, state, p1, _ = _engine()
    _archdruids_charm(engine, state, p1, _card("Forest", "Basic Land — Forest"))

    found = next(o for o in state.pending_choice["options"] if o["id"] != "decline")
    engine.resolve_pending_choice(found["id"])
    engine.resolve_until_stable()

    land = next(o for o in state.battlefield if o.name == "Forest")
    assert land.tapped is True
    assert not any(o.name == "Forest" for o in p1.hand)


def test_conditional_search_destination_falls_back_to_hand_for_a_creature():
    engine, state, p1, _ = _engine()
    _archdruids_charm(engine, state, p1, _bear("Elf"))

    found = next(o for o in state.pending_choice["options"] if o["id"] != "decline")
    engine.resolve_pending_choice(found["id"])
    engine.resolve_until_stable()

    assert any(o.name == "Elf" for o in p1.hand)
    assert not any(o.name == "Elf" for o in state.battlefield)


# ---------------------------------------------------------------------------
# Face-down exile + a conditional cast window — Beseech the Mirror
# ---------------------------------------------------------------------------


def _beseech(engine, state, p1, *library, bargained=False):
    for card in library:
        p1.add_to_zone(GameObject(card, owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    if bargained:
        token = _bf(state, _card("Treasure", "Artifact — Treasure", "", 0))
        token.is_token = True
    spell = _catalogue_obj(state, "Beseech the Mirror", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("B", 4)                      # {1}{B}{B}{B}
    engine.cast_spell(p1, spell, bargained=bargained)
    engine.resolve_until_stable()
    found = next(o for o in state.pending_choice["options"] if o["id"] != "decline")
    engine.resolve_pending_choice(found["id"])
    engine.resolve_until_stable()
    return spell


def test_the_tutored_card_is_exiled_face_down_not_put_into_hand():
    engine, state, p1, _ = _engine()
    _beseech(engine, state, p1, _card("Ritual", "Instant", "{B}", 1), bargained=True)

    exiled = next(o for o in p1.exile if o.name == "Ritual")
    # RULE 701.20a: hidden from everyone but its owner.
    assert exiled.face_down_in_exile is True
    assert not any(o.name == "Ritual" for o in p1.hand)


def test_a_bargained_beseech_opens_a_free_cast_window_on_the_exiled_card():
    engine, state, p1, _ = _engine()
    _beseech(engine, state, p1, _card("Ritual", "Instant", "{B}", 1), bargained=True)

    ritual = next(o for o in p1.exile if o.name == "Ritual")
    assert ritual.instance_id in state.free_cast_instance_ids
    # Offered through the ordinary action loop, so it keeps full targeting.
    offered = [
        a for a in engine.legal_actions(p1)
        if a["type"] == "cast_spell" and a["instance_id"] == ritual.instance_id
    ]
    assert offered, "the exiled card must be castable from exile"

    engine.cast_spell(p1, ritual)
    assert ritual.zone == Zone.STACK
    # RULE 400.7: nothing stays face down across a zone change.
    assert ritual.face_down_in_exile is False


def test_an_unbargained_beseech_puts_the_exiled_card_into_hand_at_once():
    engine, state, p1, _ = _engine()
    _beseech(engine, state, p1, _card("Ritual", "Instant", "{B}", 1))

    assert any(o.name == "Ritual" for o in p1.hand)
    assert not p1.exile


def test_a_card_costing_more_than_four_is_never_castable_this_way():
    engine, state, p1, _ = _engine()
    _beseech(engine, state, p1, _card("Titan", "Creature — Giant", "{5}{G}", 6), bargained=True)

    # RULE 118.9: the window is gated on mana value, so this one skips
    # straight to the "put it into your hand" half.
    assert any(o.name == "Titan" for o in p1.hand)
    assert not p1.exile


def test_an_uncast_exiled_card_goes_to_hand_at_the_end_step():
    engine, state, p1, _ = _engine()
    _beseech(engine, state, p1, _card("Ritual", "Instant", "{B}", 1), bargained=True)
    assert any(o.name == "Ritual" for o in p1.exile)

    for _ in range(20):
        if state.current_step == "end":
            break
        engine.advance_step()
    engine.resolve_until_stable()

    assert any(o.name == "Ritual" for o in p1.hand)
    assert not any(o.name == "Ritual" for o in p1.exile)


# ---------------------------------------------------------------------------
# The Ring tempts you (RULE 701.51) — Boromir, Warden of the Tower
# ---------------------------------------------------------------------------


def _tempt(engine, p1, times=1):
    for _ in range(times):
        engine.rules.the_ring_tempts_you(p1)


def test_boromirs_sacrifice_ability_tempts_you_with_the_ring():
    engine, state, p1, _ = _engine()
    boromir = _catalogue_obj(state, "Boromir, Warden of the Tower")
    state.add_to_battlefield(boromir)
    engine.activate_ability(p1, boromir, 0)
    engine.resolve_until_stable()

    assert p1.ring_level == 1
    # Boromir sacrificed himself to pay the cost, so no creature is left to
    # carry the Ring (RULE 701.52a).
    assert p1.ring_bearer_id is None


def test_tempting_levels_the_emblem_up_and_caps_at_four():
    engine, state, p1, _ = _engine()
    _bf(state, _bear("Frodo"))
    _tempt(engine, p1, times=6)
    assert p1.ring_level == 4


def test_a_single_creature_becomes_the_ring_bearer_without_a_prompt():
    engine, state, p1, _ = _engine()
    frodo = _bf(state, _bear("Frodo"))
    _tempt(engine, p1)

    assert state.pending_choice is None
    assert p1.ring_bearer_id == frodo.instance_id


def test_two_creatures_open_a_ring_bearer_choice():
    engine, state, p1, _ = _engine()
    frodo = _bf(state, _bear("Frodo"))
    _bf(state, _bear("Sam"))
    _tempt(engine, p1)

    choice = state.pending_choice
    assert choice["kind"] == "ring_bearer"
    assert {o["label"] for o in choice["options"]} == {"Frodo", "Sam"}
    engine.resolve_pending_choice(str(frodo.instance_id))
    assert p1.ring_bearer_id == frodo.instance_id
    assert state.pending_choice is None


def test_the_ring_bearer_becomes_legendary():
    engine, state, p1, _ = _engine()
    frodo = _bf(state, _bear("Frodo"))
    other = _bf(state, _bear("Sam"))
    _tempt(engine, p1)
    engine.resolve_pending_choice(str(frodo.instance_id))
    engine.recompute_continuous_effects()

    # RULE 205.4 via layer 4 — the printed type line says nothing about it.
    assert frodo.card.is_legendary is False
    assert frodo.is_legendary is True
    assert other.is_legendary is False


def test_the_ring_bearer_cant_be_blocked_by_a_bigger_creature():
    engine, state, p1, p2 = _engine()
    frodo = _bf(state, _bear("Frodo"))                     # 2/2
    _tempt(engine, p1)
    small = _bf(state, _card("Small", "Creature — Rat", "{B}", 1,
                             is_creature=True, power=1, toughness=1), controller="p2")
    big = _bf(state, _card("Big", "Creature — Giant", "{4}{G}", 5,
                           is_creature=True, power=5, toughness=5), controller="p2")
    frodo.attacking = True
    frodo.combat_defender = {"kind": "player", "id": "p2"}

    assert engine.can_block(p2, small, frodo) is True
    assert engine.can_block(p2, big, frodo) is False


def test_the_ring_bearer_designation_drops_when_the_creature_leaves():
    engine, state, p1, _ = _engine()
    frodo = _bf(state, _bear("Frodo"))
    _tempt(engine, p1)
    assert p1.ring_bearer_id == frodo.instance_id

    engine.rules.put_into_graveyard(frodo)
    engine.rules.check_state_based_actions()
    assert p1.ring_bearer_id is None


def test_ring_level_two_draws_and_discards_when_the_bearer_attacks():
    engine, state, p1, _ = _engine()
    frodo = _bf(state, _bear("Frodo"))
    p1.add_to_zone(GameObject(_bear("Deck Bear"), owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    _tempt(engine, p1, times=2)

    state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [frodo])
    engine.resolve_until_stable()

    # Drew one, then discarded one — net zero cards, one card in graveyard.
    assert len(p1.hand) == 0
    assert len(p1.graveyard) == 1


def test_ring_level_three_sacrifices_the_blocker_at_end_of_combat():
    engine, state, p1, p2 = _engine()
    frodo = _bf(state, _bear("Frodo"))
    # Level 3 includes level 2's draw-then-discard on attack, so the library
    # needs a card — drawing from an empty one loses the game (RULE 704.5b).
    p1.add_to_zone(GameObject(_bear("Deck Bear"), owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    _tempt(engine, p1, times=3)
    blocker = _bf(state, _bear("Orc"), controller="p2")

    state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [frodo])
    engine.resolve_until_stable()
    state.current_step = "declare_blockers"
    engine.declare_blockers(p2, [(blocker, frodo)])
    engine.resolve_until_stable()

    # Armed, not executed — "at end of combat" (RULE 603.7).
    assert blocker in state.battlefield
    assert any(d.step == "end_combat" for d in state.delayed_triggers)

    for _ in range(20):
        if state.current_step == "end_combat":
            break
        engine.advance_step()
    engine.resolve_until_stable()
    assert blocker not in state.battlefield


def test_ring_level_four_drains_each_opponent_on_combat_damage():
    engine, state, p1, p2 = _engine()
    frodo = _bf(state, _bear("Frodo"))
    _tempt(engine, p1, times=4)

    engine.rules.deal_damage(p2, 2, source=frodo, combat=True)
    engine.resolve_until_stable()

    # 2 combat damage plus the Ring's own 3-life drain.
    assert p2.life == 15
    assert p1.life == 20


def test_the_rings_triggers_stay_silent_below_their_level():
    engine, state, p1, p2 = _engine()
    frodo = _bf(state, _bear("Frodo"))
    _tempt(engine, p1, times=3)          # level 3: no drain yet

    engine.rules.deal_damage(p2, 2, source=frodo, combat=True)
    engine.resolve_until_stable()
    assert p2.life == 18


# ---------------------------------------------------------------------------
# Interactive choosers replacing the old auto-picks
# ---------------------------------------------------------------------------


def test_tevesh_szats_optional_sacrifice_draws_only_if_you_do():
    engine, state, p1, _ = _engine()
    szat = _catalogue_obj(state, "Tevesh Szat, Doom of Fools")
    szat.add_counters("loyalty", 3)
    state.add_to_battlefield(szat)
    _bf(state, _bear("Fodder"))
    for i in range(4):
        p1.add_to_zone(GameObject(_bear(f"Deck{i}"), owner_id="p1", zone=Zone.LIBRARY),
                       Zone.LIBRARY)

    engine.activate_ability(p1, szat, 1)          # +1
    engine.resolve_until_stable()
    assert state.pending_choice["kind"] == "choose_objects"
    engine.resolve_pending_choice("decline")
    assert p1.hand == []                          # "if you do" never happened


def test_tevesh_szat_draws_an_extra_card_for_a_sacrificed_commander():
    engine, state, p1, _ = _engine()
    szat = _catalogue_obj(state, "Tevesh Szat, Doom of Fools")
    szat.add_counters("loyalty", 3)
    state.add_to_battlefield(szat)
    cmdr = GameObject(_bear("Partner"), owner_id="p1", zone=Zone.BATTLEFIELD,
                      is_commander=True)
    _bf(state, None, obj=cmdr)
    for i in range(4):
        p1.add_to_zone(GameObject(_bear(f"Deck{i}"), owner_id="p1", zone=Zone.LIBRARY),
                       Zone.LIBRARY)

    engine.activate_ability(p1, szat, 1)
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(cmdr.instance_id))

    # Two for "if you do", plus RULE 903's extra card for the commander.
    assert len(p1.hand) == 3


# ---------------------------------------------------------------------------
# Mutate under the pile (RULE 702.140b) and its non-Human target
# ---------------------------------------------------------------------------


def _drakkis(state, p1):
    obj = GameObject(_named("Lore Drakkis"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)
    p1.mana_pool.add("U", 2)
    p1.mana_pool.add("R", 2)
    return obj


def test_mutating_under_keeps_the_hosts_characteristics():
    engine, state, p1, _ = _engine()
    host = _bf(state, _bear("Host"))
    drakkis = _drakkis(state, p1)

    engine.cast_spell(p1, drakkis, targets=[host], mutate=True, mutate_under=True)
    engine.resolve_until_stable()

    # RULE 702.140b: the host stayed on top, so its name and P/T are the pile's.
    assert host.name == "Host"
    assert (host.power, host.toughness) == (2, 2)
    # …but it gained the card that went underneath.
    assert "Lore Drakkis" not in host.name
    assert host.merged_oracle_text


def test_mutating_over_replaces_the_hosts_characteristics():
    engine, state, p1, _ = _engine()
    host = _bf(state, _bear("Host"))
    drakkis = _drakkis(state, p1)

    engine.cast_spell(p1, drakkis, targets=[host], mutate=True)
    engine.resolve_until_stable()

    assert host.name == "Lore Drakkis"


def test_a_human_is_never_a_legal_mutate_host():
    engine, state, p1, _ = _engine()
    human = _bf(state, _card("Soldier", "Creature — Human Soldier", "{W}", 1,
                             is_creature=True, power=1, toughness=1))
    drakkis = _drakkis(state, p1)

    # RULE 702.140a: "target **non-Human** creature you own".
    assert engine.legal_mutate_hosts(p1, drakkis) == []
    assert engine.can_cast(p1, drakkis, mutate=True) is False
    with pytest.raises(ValueError):
        engine.cast_spell(p1, drakkis, targets=[human], mutate=True)


def test_a_creature_you_own_but_dont_control_is_still_a_legal_mutate_host():
    """RULE 108.3: mutate reads *ownership*, not control."""
    engine, state, p1, _ = _engine()
    lent = _bf(state, _bear("Lent"))
    lent.controller_id = "p2"
    drakkis = _drakkis(state, p1)

    assert lent in engine.legal_mutate_hosts(p1, drakkis)


# ---------------------------------------------------------------------------
# RULE 305.7 — setting a land's type strips its printed abilities
# ---------------------------------------------------------------------------


def test_blood_moon_strips_a_nonbasic_lands_own_mana_ability():
    from mtg_analyzer.game import mana_abilities

    engine, state, p1, _ = _engine()
    sea = _bf(state, _card(
        "Underground Sea", "Land — Island Swamp", "", 0,
        oracle_text="({T}: Add {U} or {B}.)",
    ))
    state.add_to_battlefield(_catalogue_obj(state, "Blood Moon"))
    engine.recompute_continuous_effects()

    options = mana_abilities.mana_options_for(sea, state)
    # RULE 305.7: only the Mountain's intrinsic {R} survives.
    assert options == [{"R": 1}]


def test_blood_moon_leaves_a_basic_land_alone():
    from mtg_analyzer.game import mana_abilities

    engine, state, p1, _ = _engine()
    island = _bf(state, _card("Island", "Basic Land — Island", "", 0))
    state.add_to_battlefield(_catalogue_obj(state, "Blood Moon"))
    engine.recompute_continuous_effects()

    assert mana_abilities.mana_options_for(island, state) == [{"U": 1}]


# ---------------------------------------------------------------------------
# The compact inline "A or B" activated ability (RULE 700.2) — Pemmin's Aura
# ---------------------------------------------------------------------------


def test_the_parser_splits_a_compact_gets_a_or_b_activated_ability():
    from mtg_analyzer.parser.oracle.gate import parse_oracle

    card = Card(
        id="pemmin", name="Pemmin's Aura", type_line="Enchantment — Aura",
        oracle_text=(
            "Enchant creature\n"
            "{U}: Untap enchanted creature.\n"
            "{1}: Enchanted creature gets +1/-1 or -1/+1 until end of turn.\n"
            "{1}: Enchanted creature gains flying until end of turn."
        ),
    )
    result = parse_oracle(card)

    assert result.coverage == "MODELED"
    assert result.unclaimed == []
    pumps = [
        spec.effects[0].params
        for spec in result.specs
        if spec.ability_kind == "activated" and spec.effects[0].type == "pump"
        and "power" in spec.effects[0].params
    ]
    # One separately-activatable ability per printed half — choosing which to
    # activate *is* the printed choice.
    assert {(p["power"], p["toughness"]) for p in pumps} == {(1, -1), (-1, 1)}


def test_an_ordinary_or_in_an_effect_body_is_never_split():
    """" or " joining two *nouns* ("target artifact or enchantment") must
    not be mistaken for a modal — the split only ever fires on two full P/T
    clauses, and only after the ordinary parse has already failed."""
    from mtg_analyzer.parser.oracle.segmenter import _inline_pt_modal_bodies

    assert _inline_pt_modal_bodies("exile target artifact or enchantment.") is None
    assert _inline_pt_modal_bodies("add {w} or {u}.") is None
    assert _inline_pt_modal_bodies("destroy target creature or planeswalker.") is None
