"""PAR-23 — cost keywords that were parser-recognised but wired to nothing:

* **Affinity for `<quality>`** (702.41) — a standing self cost reduction,
  synthesized as a `layer="cost"` `StaticAbility` (`effect_binder.
  _attach_affinity_static`) that `continuous.self_cost_reduction_for`
  already knew how to read.
* **Convoke** (702.51) / **Delve** (702.66) / **Improvise** (702.126) — an
  opt-in `help_pay` cast flag: the printed *generic* cost is paid down by
  tapping creatures / exiling graveyard cards / tapping artifacts, minimal
  at the real cast (`GameEngine._consume_cast_help`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost


def _card(name, cost="{4}", keywords=None, type_line="Artifact Creature — Frog",
          is_creature=True, is_instant=False, is_sorcery=False, is_land=False,
          power=2, toughness=2, oracle_text=""):
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=is_creature, is_instant=is_instant, is_sorcery=is_sorcery,
        is_land=is_land,
        power=power if is_creature else None, toughness=toughness if is_creature else None,
        keywords=list(keywords or []), oracle_text=oracle_text,
    )


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, card, controller="p1", tapped=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = tapped
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _hand(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).add_to_zone(obj, Zone.HAND)
    return obj


def _gy(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.GRAVEYARD)
    state.player_by_id(controller).add_to_zone(obj, Zone.GRAVEYARD)
    return obj


def _main(eng):
    eng.state.current_step = "main1"
    eng.state.active_player_index = 0


# -- Affinity (RULE 702.41) --------------------------------------------


def test_affinity_for_artifacts_reduces_cost_per_artifact():
    eng = _engine()
    state = eng.state
    for i in range(3):
        _bf(state, _card(f"Trinket {i}", cost="{1}", type_line="Artifact", is_creature=False))
    frog = _hand(state, _card("Frogmite", cost="{4}", keywords=["Affinity for artifacts"],
                              oracle_text="Affinity for artifacts (This spell costs {1} less "
                                          "to cast for each artifact you control.)"))
    p1 = state.player_by_id("p1")
    assert eng.effective_cast_cost(p1, frog).converted_mana_cost == 1  # {4} - 3 artifacts

    _main(eng)
    p1.mana_pool.add_many({"C": 1})
    assert eng.can_cast(p1, frog)
    eng.cast_spell(p1, frog)
    assert any(i.obj is frog for i in state.stack)


def test_affinity_for_islands_uses_a_land_type_count():
    eng = _engine()
    state = eng.state
    for i in range(2):
        _bf(state, _card(f"Isl {i}", cost="", type_line="Basic Land — Island",
                         is_creature=False, is_land=True))
    spell = _hand(state, _card("Thoughtcast", cost="{4}{U}", type_line="Sorcery",
                               is_creature=False, is_sorcery=True,
                               keywords=["Affinity for Islands"],
                               oracle_text="Affinity for Islands (This spell costs {1} less to "
                                           "cast for each Island you control.)"))
    p1 = state.player_by_id("p1")
    assert eng.effective_cast_cost(p1, spell).converted_mana_cost == 3  # {4}{U} - 2 = {2}{U}


# -- Convoke (RULE 702.51) --------------------------------------------


def test_convoke_taps_creatures_to_pay_generic():
    eng = _engine()
    state = eng.state
    a = _bf(state, _card("Elf A", cost="{G}", type_line="Creature — Elf"))
    b = _bf(state, _card("Elf B", cost="{G}", type_line="Creature — Elf"))
    c = _bf(state, _card("Elf C", cost="{G}", type_line="Creature — Elf"))
    spell = _hand(state, _card("Chord", cost="{3}{G}", type_line="Instant", is_creature=False,
                               is_instant=True, keywords=["Convoke"],
                               oracle_text="Convoke (Your creatures can help cast this spell. ...)"))
    _main(eng)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"G": 1})  # covers the {G}; convoke must cover {3}

    assert eng.can_cast(p1, spell, help_pay=True)
    assert not eng.can_cast(p1, spell)  # not without help
    eng.cast_spell(p1, spell, help_pay=True)

    assert any(i.obj is spell for i in state.stack)
    # 3 creatures tapped to pay the {3}; the {G} pip came from the pool.
    assert sum(1 for e in (a, b, c) if e.tapped) == 3


# -- Delve (RULE 702.66) ---------------------------------------------


def test_delve_exiles_graveyard_cards_to_pay_generic():
    eng = _engine()
    state = eng.state
    for i in range(5):
        _gy(state, _card(f"Junk {i}", cost="{1}", type_line="Instant", is_creature=False, is_instant=True))
    spell = _hand(state, _card("Treasure Cruise", cost="{7}{U}", type_line="Sorcery",
                               is_creature=False, is_sorcery=True, keywords=["Delve"],
                               oracle_text="Delve (Each card you exile from your graveyard "
                                           "while casting this spell pays for {1}.)"))
    _main(eng)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"U": 1, "C": 3})  # {3}{U}; Delve must cover the remaining {4}

    assert eng.can_cast(p1, spell, help_pay=True)
    eng.cast_spell(p1, spell, help_pay=True)

    assert any(i.obj is spell for i in state.stack)
    assert len(p1.exile) == 4  # exactly {4} worth of graveyard cards exiled
    assert len(p1.graveyard) == 1


# -- Improvise (RULE 702.126) --------------------------------------


def test_improvise_taps_artifacts_to_pay_generic():
    eng = _engine()
    state = eng.state
    arts = [_bf(state, _card(f"Mox {i}", cost="{0}", type_line="Artifact", is_creature=False))
            for i in range(3)]
    spell = _hand(state, _card("Reverse Engineer", cost="{3}{U}{U}", type_line="Sorcery",
                               is_creature=False, is_sorcery=True, keywords=["Improvise"],
                               oracle_text="Improvise (Your artifacts can help cast this spell. ...)"))
    _main(eng)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"U": 2})  # {U}{U}; Improvise must cover {3}

    assert eng.can_cast(p1, spell, help_pay=True)
    eng.cast_spell(p1, spell, help_pay=True)

    assert any(i.obj is spell for i in state.stack)
    assert sum(1 for a in arts if a.tapped) == 3


def test_help_pay_rejected_without_the_keyword():
    eng = _engine()
    state = eng.state
    _bf(state, _card("Elf", cost="{G}", type_line="Creature — Elf"))
    spell = _hand(state, _card("Plain Spell", cost="{3}{G}", type_line="Instant",
                               is_creature=False, is_instant=True))
    _main(eng)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"G": 1})
    assert not eng.can_cast(p1, spell, help_pay=True)
