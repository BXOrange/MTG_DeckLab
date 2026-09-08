"""Secrets of Strixhaven — playability batch, wave 82 (PAR-60).

Animist's Awakening — new `animists_awakening` effect (fixed-X reveal,
take all lands tapped, rest bottom random; spell mastery untap).
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.effect_binder import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _aa_card():
    return Card(id="aa", name="Animist's Awakening", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{X}{G}",
                oracle_text=("Reveal the top X cards of your library. Put all land cards "
                             "from among them onto the battlefield tapped and the rest "
                             "on the bottom of your library in a random order.\nSpell "
                             "mastery — If there are two or more instant and/or sorcery "
                             "cards in your graveyard, untap those lands."))


def test_registered_and_binds():
    assert is_registered("Animist's Awakening")
    spec = _REGISTRY["animist's awakening"]()[0]
    spec.validate()
    assert spec.effects[0].type == "animists_awakening"
    assert spec.effects[0].params["count"] == "x"
    src = GameObject(_aa_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_aa_card())


def _run(eng, x, spell_mastery=False):
    p1 = eng.state.player_by_id("p1")
    # top of library = end of list; stack 3 lands + 2 nonlands among top 5
    deck = [
        ("L1", True), ("N1", False), ("L2", True), ("N2", False), ("L3", True),
    ]
    for name, is_land in deck:
        c = Card(id=name, name=name,
                 type_line="Basic Land — Forest" if is_land else "Sorcery",
                 is_land=is_land, is_sorcery=not is_land)
        p1.add_to_zone(GameObject(c, owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    if spell_mastery:
        for i in range(2):
            p1.add_to_zone(GameObject(Card(id=f"g{i}", name=f"g{i}", type_line="Instant",
                                           is_instant=True), owner_id="p1",
                                      zone=Zone.GRAVEYARD), Zone.GRAVEYARD)
    src = GameObject(_aa_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    src.x_paid = x
    eng.rules._apply_effect_specs(
        [{"type": "animists_awakening", "params": {"count": x}}], src,
    )
    eng.resolve_until_stable()
    return p1


def test_puts_all_revealed_lands_tapped_rest_to_bottom():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1 = _run(eng, x=5)
    lands = [o for o in eng.state.battlefield
             if o.controller_id == "p1" and o.card.is_land]
    assert len(lands) == 3
    assert all(o.tapped for o in lands)
    assert len(p1.library) == 2  # the two nonlands went to the bottom


def test_spell_mastery_untaps_the_lands():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1 = _run(eng, x=5, spell_mastery=True)
    lands = [o for o in eng.state.battlefield
             if o.controller_id == "p1" and o.card.is_land]
    assert len(lands) == 3
    assert all(not o.tapped for o in lands)
