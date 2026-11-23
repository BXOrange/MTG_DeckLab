"""PAR-292 M12: the dig whose picked card is exiled and then cast / played ("look at the top N cards of your library.
You may exile a creature card from among them. Put the rest on the bottom of your library ... Until end of turn, you
may cast the exiled card [without paying its mana cost]"), and the "shares a creature type with it / that creature" pick.

Parsed from real oracle wording, then run on a real engine with bystanders: the cards not picked go where the text says,
the window closes when the text says (RULE 611.2), an opponent cannot cast the card, and a face-down exile is hidden from
the opponent (RULE 406.3).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.services.game_session import _redact_face_down_exile

from tests.test_par144_dig_family import _card, _engine, _stock
from tests.test_par157_back_selections import _cached

DJERU = (
    "look at the top 4 cards of your library. you may exile a legendary creature card from among them. "
    "put the rest on the bottom of your library in a random order. until end of turn, you may cast the exiled card "
    "without paying its mana cost."
)
PLAY_LAND = (
    "look at the top 3 cards of your library. you may exile a land card from among them. "
    "put the rest on the bottom of your library in a random order. you may play the exiled card this turn."
)
VIVIEN = (
    "look at the top 3 cards of your library. exile 1 face down and put the rest on the bottom of your library in any "
    "order. for as long as it remains exiled, you may cast it if it's a creature spell."
)


def _modeled(name):
    return parse_oracle(_cached(name)).modeled


@pytest.mark.parametrize("name", ["Djeru and Hazoret", "Vivien, Champion of the Wilds", "Conjurer's Mantle", "Tajuru Paragon"])
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


# --- parse ------------------------------------------------------------------------------------------------------

def test_exile_pick_carries_its_window_as_a_placed_effect():
    (spec,) = match_clause(DJERU)
    assert spec.type == "inspect_top_choose"
    assert spec.params["action"] == "exile" and spec.params["optional"] is True
    assert spec.params["criteria"] == {"all_types": ["legendary", "creature"]}
    assert spec.params["rest_destination"] == "library_bottom_random"
    assert spec.params["placed_effects"] == [{"type": "cast_window_exiled_pool", "params": {
        "only_spells": True, "same_turn_only": True, "free": True, "from_previous": True}}]


def test_face_down_pick_with_a_kind_condition_on_the_cast():
    (spec,) = match_clause(VIVIEN)
    assert spec.params["action"] == "exile_face_down" and spec.params["optional"] is False
    assert spec.params["rest_destination"] == "library_bottom_order"
    assert spec.params["placed_effects"] == [{"type": "cast_window_exiled_pool", "params": {
        "only_spells": True, "standing": True, "from_previous": True, "card_filter": {"card_type": "creature"}}}]


_LOOK = "look at the top 4 cards of your library. "
_REST = " put the rest on the bottom of your library in a random order."


@pytest.mark.parametrize("text", [
    # a pick nothing reads (no window sentence) is not this row's
    _LOOK + "you may exile a creature card from among them." + _REST,
    # a plural pool after a one-card pick
    _LOOK + "you may exile a creature card from among them." + _REST + " you may cast them this turn.",
    # a condition on the cast that is not a spell kind (the "if you don't" half needs an else on the cast offer)
    _LOOK + "exile 1 of them face down and put the rest on the bottom of your library in a random order. "
    "you may cast the exiled card without paying its mana cost if it's an instant spell with mana value 2 or less.",
    # the picked card is not "the other" of a pair, and the window may not be a one-spell cast from "among them"
    _LOOK + "you may exile a creature card from among them." + _REST + " you may cast a spell from among them this turn.",
    # a quality outside the vocabulary
    _LOOK + "you may exile a multicolored card from among them." + _REST + " you may cast the exiled card this turn.",
])
def test_near_misses_stay_unclaimed(text):
    assert match_clause(text) is None


# --- execution --------------------------------------------------------------------------------------------------

def _resolve(eng, player, oracle_text):
    spell = GameObject(
        _card("Dig Spell", "Sorcery", cost="", cmc=0, oracle_text=oracle_text), owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    player.add_to_zone(spell, Zone.HAND)
    eng.rules.cast_spell(player, spell)
    eng.resolve_until_stable()


def _offered(eng):
    return [o["label"] for o in eng.state.pending_choice["options"] if "instance_id" in o]


def _take(eng, name):
    option = next(o for o in eng.state.pending_choice["options"] if o.get("label") == name)
    eng.rules.resolve_choice(option["instance_id"])
    eng.resolve_until_stable()


def _top_down(player):
    return [o.name for o in reversed(player.library)]


def _legend(name="Legend", cmc=3):
    return _card(name, "Legendary Creature — Human", cost="{2}{W}", cmc=cmc)


def _deep():
    return _card("Deep", "Sorcery", cost="", cmc=0)


def test_only_the_named_kind_is_offered_and_the_rest_goes_to_the_bottom():
    eng, p1 = _engine()
    _stock(p1, _legend(), _card("Plain Bear"), _card("A Land", "Land", cost="", cmc=0), _card("Other Bear"), _deep())
    _resolve(eng, p1, DJERU)
    assert _offered(eng) == ["Legend"]
    _take(eng, "Legend")
    exiled = next(o for o in p1.exile if o.name == "Legend")
    # the unchosen looked-at cards sit under the untouched deep card (RULE 401.4 / 401.2); the pick left the library
    assert _top_down(p1)[0] == "Deep" and sorted(_top_down(p1)[1:]) == ["A Land", "Other Bear", "Plain Bear"]
    assert exiled.zone == Zone.EXILE and not exiled.face_down_in_exile


def test_the_free_cast_window_is_for_this_turn_and_only_for_the_digger():
    eng, p1 = _engine()
    p2 = eng.state.players[1]
    _stock(p1, _legend(cmc=5), _deep())
    _resolve(eng, p1, DJERU)
    _take(eng, "Legend")
    card = next(o for o in p1.exile if o.name == "Legend")
    assert eng.can_cast(p1, card) and p1.mana_pool.total() == 0  # RULE 118.9: free, no mana in the pool
    assert not eng.can_cast(p2, card)  # an opponent has no permission
    eng._step_cleanup()
    assert not eng.can_cast(p1, card)  # RULE 611.2: "until end of turn" is over
    assert card.zone == Zone.EXILE  # an uncast card simply stays exiled


def test_declining_the_pick_exiles_nothing_and_grants_no_window():
    eng, p1 = _engine()
    _stock(p1, _legend(), _card("Plain Bear"), _card("Other Bear"), _card("Third Bear"), _deep())
    _resolve(eng, p1, DJERU)
    eng.rules.resolve_choice(None)
    eng.resolve_until_stable()
    assert not p1.exile and not eng.state.temp_play_permissions
    assert _top_down(p1)[0] == "Deep" and len(p1.library) == 5  # every looked-at card went to the bottom, none lost


def test_nothing_of_the_kind_in_the_window_grants_nothing():
    eng, p1 = _engine()
    _stock(p1, _card("Plain Bear"), _card("Other Bear"), _card("Third Bear"), _card("Fourth Bear"), _deep())
    _resolve(eng, p1, DJERU)
    assert eng.state.pending_choice is None and not p1.exile and not eng.state.temp_play_permissions
    assert _top_down(p1)[0] == "Deep"


def test_cards_below_the_looked_at_window_are_not_offered_or_exiled():
    eng, p1 = _engine()
    _stock(p1, _card("Plain Bear"), _card("Other Bear"), _card("A Land", "Land", cost="", cmc=0), _card("Plain Bear 2"),
           _legend("Too Deep"))
    _resolve(eng, p1, DJERU)  # looks at 4; the legend is 5th
    assert eng.state.pending_choice is None and not p1.exile


def test_a_played_land_window_lets_a_land_be_played_this_turn_only():
    eng, p1 = _engine()
    p2 = eng.state.players[1]
    _stock(p1, _card("Forest", "Basic Land — Forest", cost="", cmc=0), _card("Plain Bear"), _deep())
    _resolve(eng, p1, PLAY_LAND)
    _take(eng, "Forest")
    land = next(o for o in p1.exile if o.name == "Forest")
    assert eng.can_play_land(p1, land) and not eng.can_play_land(p2, land)
    eng._step_cleanup()
    assert not eng.can_play_land(p1, land)


def test_face_down_pick_is_hidden_from_the_opponent_and_castable_only_as_the_named_kind():
    eng, p1 = _engine()
    p2 = eng.state.players[1]
    _stock(p1, _card("Plain Bear"), _card("Insight", "Sorcery", cost="{1}", cmc=1), _card("A Land", "Land", cost="", cmc=0))
    _resolve(eng, p1, VIVIEN)
    assert sorted(_offered(eng)) == ["A Land", "Insight", "Plain Bear"]  # the pick is mandatory: "exile 1 face down"
    _take(eng, "Plain Bear")
    assert eng.state.pending_choice["kind"] == "library_bottom"  # "in any order": the player orders the pile (RULE 401.4)
    eng.rules.resolve_choice("decline")
    eng.resolve_until_stable()
    bear = next(o for o in p1.exile if o.name == "Plain Bear")
    assert bear.face_down_in_exile and sorted(_top_down(p1)) == ["A Land", "Insight"]
    state = eng.state.to_dict()
    _redact_face_down_exile(state, "p2")
    seen_by_opponent = next(o for p in state["players"] for o in p["exile"] if o["instance_id"] == bear.instance_id)
    assert seen_by_opponent["name"] == ""  # RULE 406.3
    state = eng.state.to_dict()
    _redact_face_down_exile(state, "p1")
    seen_by_owner = next(o for p in state["players"] for o in p["exile"] if o["instance_id"] == bear.instance_id)
    assert seen_by_owner["name"] == "Plain Bear"
    # a creature spell, with its cost, for as long as it remains exiled (it survives the end of turn, RULE 611.2)
    p1.mana_pool.add("G", 2)
    assert eng.can_cast(p1, bear) and not eng.can_cast(p2, bear)
    eng._step_cleanup()
    p1.mana_pool.add("G", 2)
    assert eng.can_cast(p1, bear)
    eng.cast_spell(p1, bear)
    eng.resolve_until_stable()
    assert bear.zone == Zone.BATTLEFIELD and not bear.face_down_in_exile


def test_face_down_pick_of_another_kind_cannot_be_cast():
    eng, p1 = _engine()
    _stock(p1, _card("Insight", "Sorcery", cost="{1}", cmc=1), _card("Plain Bear"), _card("A Land", "Land", cost="", cmc=0))
    _resolve(eng, p1, VIVIEN)
    _take(eng, "Insight")
    eng.rules.resolve_choice("decline")
    eng.resolve_until_stable()
    insight = next(o for o in p1.exile if o.name == "Insight")
    p1.mana_pool.add("G", 2)
    assert not eng.can_cast(p1, insight)  # "if it's a creature spell": a sorcery is not


# --- shares a creature type with it / that creature ---------------------------------------------------------------

def _creature_type_card(name, types, **kw):
    return _card(name, "Creature — " + types, cost="{1}", cmc=1, **kw)


def _offered_by_real_trigger(eng, card_name, source_types, trigger_creature=None):
    """Apply the real card's dig effect with its source on the battlefield (and the firing creature, if any)."""
    source = GameObject(_cached(card_name), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(source)
    eng.state.add_to_battlefield(source)
    spec = next(e for ability in parse_oracle(_cached(card_name)).specs
                for e in getattr(ability, "effects", []) if e.type == "inspect_top_choose")
    spec = EffectSpec(spec.type, spec.params)  # the kicker's intervening "if" is the trigger's, not this pick's
    eng.rules.context.trigger_event = ({"instance_id": trigger_creature.instance_id} if trigger_creature else {})
    for effect in build_effects([spec], source):
        effect.apply(eng.rules.context, [])
    return source


def test_tajuru_paragon_offers_cards_sharing_a_type_with_itself():
    eng, p1 = _engine()
    _stock(
        p1, _creature_type_card("Cleric Card", "Human Cleric"), _creature_type_card("Bear Card", "Bear"),
        _creature_type_card("Changeling Card", "Shapeshifter", keywords=["Changeling"]),
        _card("A Land", "Land", cost="", cmc=0), _creature_type_card("Wizard Card", "Elf Wizard"), _deep(), _card("Under", "Sorcery", cost="", cmc=0),
    )  # Paragon looks at the top six: the deep card is the 6th, "Under" the untouched 7th
    _offered_by_real_trigger(eng, "Tajuru Paragon", None)
    # "Tajuru Paragon is also a Cleric, Rogue, Warrior, and Wizard": a Cleric, a Wizard and (RULE 702.73a) a changeling
    assert sorted(_offered(eng)) == ["Changeling Card", "Cleric Card", "Wizard Card"]
    _take(eng, "Wizard Card")
    assert [o.name for o in p1.hand] == ["Wizard Card"]
    assert _top_down(p1)[0] == "Under"


def test_conjurers_mantle_reads_the_attacking_creature_not_the_equipment():
    eng, p1 = _engine()
    attacker = GameObject(_creature_type_card("Goblin Attacker", "Goblin Warrior"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(attacker)
    _stock(
        p1, _creature_type_card("Goblin Card", "Goblin Shaman"), _creature_type_card("Elf Card", "Elf"),
        _card("Bear Spell", "Sorcery", cost="{1}", cmc=1), _deep(), _deep(), _deep(),
    )
    _offered_by_real_trigger(eng, "Conjurer's Mantle", None, trigger_creature=attacker)
    assert _offered(eng) == ["Goblin Card"]  # the Equipment itself has no creature type to share
    _take(eng, "Goblin Card")
    assert [o.name for o in p1.hand] == ["Goblin Card"]


def test_a_creature_with_no_types_in_common_offers_nothing():
    eng, p1 = _engine()
    attacker = GameObject(_creature_type_card("Lone Wolf", "Wolf"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(attacker)
    _stock(p1, _creature_type_card("Elf Card", "Elf"), _card("A Land", "Land", cost="", cmc=0), _deep(), _deep(),
           _deep(), _deep())
    _offered_by_real_trigger(eng, "Conjurer's Mantle", None, trigger_creature=attacker)
    assert eng.state.pending_choice is None and not p1.hand


def test_the_shared_type_placeholder_needs_a_trigger_to_name_its_creature():
    # the same wording on a spell has no "it" / "that creature" to compare with
    spell = Card(
        id="Probe", name="Probe", type_line="Sorcery", is_sorcery=True, mana_cost_string="{1}", converted_mana_cost=1,
        oracle_text="Look at the top six cards of your library. You may reveal a card that shares a creature type with "
                    "that creature from among them and put it into your hand. Put the rest on the bottom of your "
                    "library in a random order.",
    )
    assert parse_oracle(spell).modeled is False


def test_unresolved_placeholder_matches_no_card():
    from mtg_analyzer.models.cards import card_query

    elf = _creature_type_card("Elf Card", "Elf")
    assert not card_query.matches(elf, {"shares_creature_type_with": "source"})
    assert card_query.matches(elf, {"shares_creature_type_with": ["elf", "wizard"]})
    assert not card_query.matches(elf, {"shares_creature_type_with": ["goblin"]})
    assert not card_query.matches(elf, {"shares_creature_type_with": []})
    # only creature types count (an Aura or a Saga is not a creature type)
    assert not card_query.matches(_card("Aura Card", "Enchantment — Aura"), {"shares_creature_type_with": ["aura"]})
