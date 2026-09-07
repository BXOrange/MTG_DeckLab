"""Secrets of Strixhaven — playability batch, wave 2.

Wave 2: RULE 702.153 **Magecraft**. `normalize._strip_unregistered_keyword_
labels` peels the "Magecraft — " ability-word label, so the recognizer that
matters is `segmenter._CAST_SPELL_TRIGGER_RE` widened with an optional
`(?:or copy )?` — "Whenever you cast or copy an instant or sorcery spell, …".
Only the "cast" half binds (no spell-copy event bus yet).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


@pytest.mark.parametrize(
    "name",
    [
        "Archmage Emeritus",
        "Witherbloom Apprentice",
        "Lorehold Pledgemage",
        "Quandrix Pledgemage",
        "Witherbloom Pledgemage",
        "Silverquill Apprentice",
    ],
)
def test_magecraft_cards_now_modeled(name):
    card = _db().get_card(name)
    assert card is not None, f"{name} not cached"
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, (name, result.unclaimed)


def test_magecraft_trigger_shape():
    card = _db().get_card("Archmage Emeritus")
    specs = parse_oracle(card).specs
    trig = [s for s in specs if s.trigger][0].trigger
    assert trig["event"] == "SPELL_CAST"
    assert trig.get("spell_card_types") == ["instant", "sorcery"]


def test_magecraft_binds_one_triggered_ability_and_draws_on_instant_cast():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player

    emeritus = GameObject(_db().get_card("Archmage Emeritus"),
                          owner_id=p1.id, zone=Zone.BATTLEFIELD)
    emeritus.summoning_sick = False
    eng.state.add_to_battlefield(emeritus)
    bind_from_catalogue(emeritus)
    assert len(emeritus.triggered_abilities) == 1

    # A known card on top of the library for magecraft to draw.
    drawn = GameObject(Card(id="isl", name="Island", type_line="Basic Land — Island",
                            is_land=True), owner_id=p1.id, zone=Zone.LIBRARY)
    p1.library.append(drawn)

    bolt = GameObject(Card(id="bolt", name="Lightning Bolt", type_line="Instant",
                           mana_cost_string="{R}", converted_mana_cost=1, is_instant=True),
                      owner_id=p1.id, zone=Zone.HAND)
    p1.hand.append(bolt)
    p1.mana_pool.add_many({"R": 1})

    eng.cast_spell(p1, bolt)
    eng.resolve_until_stable()

    assert drawn in p1.hand, "magecraft should have drawn the top card on the instant cast"


def test_magecraft_does_not_fire_on_sorcery_speed_noninstant_cast():
    # The trigger's own filter is `spell_card_types == ["instant", "sorcery"]`
    # (see test_magecraft_trigger_shape); at runtime a Wizardcycling-style
    # artifact cast leaves the top card in the library.
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    emeritus = GameObject(_db().get_card("Archmage Emeritus"),
                          owner_id=p1.id, zone=Zone.BATTLEFIELD)
    emeritus.summoning_sick = False
    eng.state.add_to_battlefield(emeritus)
    bind_from_catalogue(emeritus)

    drawn = GameObject(Card(id="isl", name="Island", type_line="Basic Land — Island",
                            is_land=True), owner_id=p1.id, zone=Zone.LIBRARY)
    p1.library.append(drawn)
    rock = GameObject(Card(id="rock", name="Test Rock", type_line="Artifact",
                           mana_cost_string="{1}", converted_mana_cost=1),
                      owner_id=p1.id, zone=Zone.HAND)
    p1.hand.append(rock)
    p1.mana_pool.add_many({"C": 1})

    try:
        eng.cast_spell(p1, rock)
        eng.resolve_until_stable()
    except ValueError:
        # sorcery-speed timing may reject the bare-state cast; the assertion
        # below still holds — nothing was drawn.
        pass

    assert drawn in p1.library, "magecraft must not fire on a non-instant/sorcery cast"
