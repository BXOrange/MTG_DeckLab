"""Face-down spells and permanents (RULE 708): morph, megamorph, disguise,
manifest and cloak.

Reference: CR 708, 702.37 (Morph/Megamorph), 702.168 (Disguise), 701.40
(Manifest), 701.58 (Cloak). The narrative lives in
`docs/implementation-state/Done_Backend.md` ("Face-down permanents").
"""

import pytest

from mtg_analyzer.game import face_down
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import bind_from_catalogue


MORPH_REMINDER = (
    "(You may cast this card face down as a 2/2 creature for {3}. "
    "Turn it face up any time for its morph cost.)"
)


def morph_card(name="Willbender", cost="{1}{U}", keyword="Morph", text=""):
    return Card(
        id=name,
        name=name,
        type_line="Creature — Shapeshifter",
        is_creature=True,
        power=1,
        toughness=2,
        mana_cost_string="{1}{U}",
        converted_mana_cost=2,
        color_identity={"U"},
        oracle_text=f"{keyword} {cost} {MORPH_REMINDER}" + (f"\n{text}" if text else ""),
        keywords=[keyword],
    )


def plain_creature(name="Bear", cost="{1}{G}"):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=2, toughness=2, mana_cost_string=cost, converted_mana_cost=2,
    )


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _in_hand(eng, card, player_id="p1"):
    player = eng.state.player_by_id(player_id)
    obj = GameObject(card, owner_id=player_id, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.add_to_zone(obj, Zone.HAND)
    return obj


def _main_phase(eng):
    eng.state.current_phase, eng.state.current_step = "precombat_main", "main1"


def _mana(eng, player_id="p1", **pips):
    pool = eng.state.player_by_id(player_id).mana_pool
    for color, amount in pips.items():
        pool.add(color.upper(), amount)


# -- Casting face down (RULE 702.37c) --------------------------------------


def test_morph_card_offers_a_face_down_cast_for_three():
    eng = make_engine()
    _main_phase(eng)
    obj = _in_hand(eng, morph_card())
    _mana(eng, C=3)
    actions = eng.legal_actions(eng.state.player_by_id("p1"))
    face_down_casts = [
        a for a in actions if a["type"] == "cast_spell" and a.get("face") == "face_down"
    ]
    assert len(face_down_casts) == 1
    assert face_down_casts[0]["cost_label"] == "{3}"
    assert face_down_casts[0]["face_down_kind"] == "morph"
    assert obj.instance_id == face_down_casts[0]["instance_id"]


def test_a_card_without_morph_is_never_castable_face_down():
    eng = make_engine()
    _main_phase(eng)
    obj = _in_hand(eng, plain_creature())
    _mana(eng, C=9)
    assert eng.can_cast(eng.state.player_by_id("p1"), obj, face="face_down") is False


def test_casting_face_down_resolves_as_a_nameless_2_2(monkeypatch):
    eng = make_engine()
    _main_phase(eng)
    obj = _in_hand(eng, morph_card())
    _mana(eng, C=3)
    eng.cast_spell(eng.state.player_by_id("p1"), obj, face="face_down")
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD
    assert obj.face_down is True
    assert obj.face_down_kind == "morph"
    assert (obj.power, obj.toughness) == (2, 2)
    assert obj.name == face_down.FACE_DOWN_NAME
    # RULE 708.2a: no subtypes, and (RULE 707/708) mana value 0.
    assert obj.card.type_line == "Creature"
    assert obj.card.converted_mana_cost == 0
    # RULE 708.2/708.3: no text at all, so no printed ability functions.
    assert obj.triggered_abilities == []
    assert obj.parametric_keywords == {}


def test_face_down_cast_is_sorcery_speed_even_with_flash():
    """RULE 708.4: the spell is turned face down before it hits the stack, so
    the face-up card's own Flash isn't among its characteristics."""
    eng = make_engine()
    card = morph_card()
    card.keywords = ["Morph", "Flash"]
    obj = _in_hand(eng, card)
    _mana(eng, C=3)
    eng.state.current_phase, eng.state.current_step = "beginning", "upkeep"
    assert eng.can_cast(eng.state.player_by_id("p1"), obj, face="face_down") is False


def test_failed_face_down_cast_leaves_the_card_face_up_in_hand():
    eng = make_engine()
    _main_phase(eng)
    obj = _in_hand(eng, morph_card())
    # No mana in the pool: the cast is rejected, and the rollback must undo
    # the turn-face-down that happens before the cast body runs.
    with pytest.raises(ValueError):
        eng.cast_spell(eng.state.player_by_id("p1"), obj, face="face_down")
    assert obj.face_down is False
    assert obj.name == "Willbender"
    assert obj.zone == Zone.HAND


# -- Turning face up (RULE 702.37e / 116.2b) --------------------------------


def _face_down_on_battlefield(eng, card, kind="morph", player_id="p1"):
    obj = GameObject(card, owner_id=player_id, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.rules.turn_face_down(obj, kind)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def test_turn_face_up_pays_the_morph_cost_and_restores_the_card():
    eng = make_engine()
    obj = _face_down_on_battlefield(eng, morph_card(cost="{1}{U}"))
    _mana(eng, C=1, U=1)
    player = eng.state.player_by_id("p1")
    actions = eng.turn_face_up_actions(player, obj)
    assert [a["cost_label"] for a in actions] == ["{1}{U}"]
    eng.turn_face_up(player, obj, actions[0]["option_index"])
    assert obj.face_down is False
    assert obj.name == "Willbender"
    assert (obj.power, obj.toughness) == (1, 2)
    assert player.mana_pool.total() == 0


def test_turn_face_up_is_not_offered_without_the_mana():
    eng = make_engine()
    obj = _face_down_on_battlefield(eng, morph_card(cost="{4}{U}"))
    _mana(eng, C=1)
    assert eng.turn_face_up_actions(eng.state.player_by_id("p1"), obj) == []


def test_turning_face_up_fires_the_turned_face_up_event():
    eng = make_engine()
    obj = _face_down_on_battlefield(eng, morph_card())
    _mana(eng, C=1, U=1)
    seen = []
    eng.state.subscribe(lambda e: seen.append(e))
    eng.turn_face_up(eng.state.player_by_id("p1"), obj, 0)
    turned = [e for e in seen if e.type == EventType.TURNED_FACE_UP]
    assert len(turned) == 1
    assert turned[0].get("instance_id") == obj.instance_id


def test_megamorph_adds_a_plus_one_counter_as_it_turns_face_up():
    """RULE 702.37b: only the megamorph cost being paid adds the counter."""
    eng = make_engine()
    obj = _face_down_on_battlefield(eng, morph_card(keyword="Megamorph", cost="{2}{G}"))
    _mana(eng, C=2, G=1)
    eng.turn_face_up(eng.state.player_by_id("p1"), obj, 0)
    assert obj.counters.get("+1/+1") == 1
    assert (obj.power, obj.toughness) == (2, 3)


def test_a_face_down_permanent_cannot_be_turned_face_down_again():
    """RULE 708.2b."""
    eng = make_engine()
    obj = _face_down_on_battlefield(eng, morph_card())
    eng.rules.turn_face_down(obj, "manifest")
    assert obj.face_down_kind == "morph"


# -- Disguise (RULE 702.168) ------------------------------------------------


def test_disguise_face_down_permanent_has_ward_two():
    eng = make_engine()
    card = morph_card(name="Fugitive Codebreaker", keyword="Disguise", cost="{2}{R}")
    card.keywords = ["Disguise"]
    obj = _face_down_on_battlefield(eng, card, kind="disguise")
    assert obj.parametric_keywords.get("ward") == {"cost": "{2}"}
    assert "ward" in obj.intrinsic_keywords


# -- Manifest / cloak (RULE 701.40 / 701.58) --------------------------------


def _library(eng, cards, player_id="p1"):
    player = eng.state.player_by_id(player_id)
    for card in cards:
        obj = GameObject(card, owner_id=player_id, zone=Zone.LIBRARY)
        bind_from_catalogue(obj)
        player.add_to_zone(obj, Zone.LIBRARY)
    return player


def test_manifest_puts_the_top_card_onto_the_battlefield_as_a_2_2():
    eng = make_engine()
    player = _library(eng, [plain_creature("Bottom"), plain_creature("Top")])
    made = eng.rules.manifest(player, 1)
    assert len(made) == 1
    assert made[0].face_down is True
    assert made[0].face_down_kind == "manifest"
    assert (made[0].power, made[0].toughness) == (2, 2)
    assert made[0].zone == Zone.BATTLEFIELD
    assert [o.name for o in player.library] == ["Bottom"]


def test_a_manifested_creature_turns_face_up_for_its_mana_cost():
    eng = make_engine()
    player = _library(eng, [plain_creature("Grizzly", cost="{1}{G}")])
    obj = eng.rules.manifest(player, 1)[0]
    _mana(eng, C=1, G=1)
    actions = eng.turn_face_up_actions(player, obj)
    assert [a["cost_label"] for a in actions] == ["{1}{G}"]
    eng.turn_face_up(player, obj, 0)
    assert obj.name == "Grizzly"
    assert obj.face_down is False


def test_a_manifested_noncreature_cannot_be_turned_face_up():
    """RULE 701.40b: only a creature card may be turned face up this way."""
    eng = make_engine()
    land = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    player = _library(eng, [land])
    obj = eng.rules.manifest(player, 1)[0]
    _mana(eng, C=9)
    assert eng.turn_face_up_actions(player, obj) == []


def test_a_manifested_morph_card_may_use_either_route():
    """RULE 701.40c: morph's own cost stays available on a manifested card."""
    eng = make_engine()
    player = _library(eng, [morph_card(cost="{1}{U}")])
    obj = eng.rules.manifest(player, 1)[0]
    _mana(eng, C=2, U=2)
    kinds = {a["kind"] for a in eng.turn_face_up_actions(player, obj)}
    assert kinds == {"morph", "manifest"}


def test_cloak_grants_ward_two():
    eng = make_engine()
    player = _library(eng, [plain_creature("Cloaked")])
    obj = eng.rules.manifest(player, 1, kind="cloak")[0]
    assert obj.face_down_kind == "cloak"
    assert obj.parametric_keywords.get("ward") == {"cost": "{2}"}


def test_manifest_dread_asks_which_of_the_top_two_to_manifest():
    eng = make_engine()
    player = _library(
        eng, [plain_creature("Deep"), plain_creature("Second"), plain_creature("Top")]
    )
    eng.rules.request_manifest_dread(player)
    choice = eng.state.pending_choice
    assert choice["kind"] == "manifest_dread"
    assert [o["label"] for o in choice["options"]] == ["Top", "Second"]
    second_id = choice["options"][1]["instance_id"]
    eng.rules.resolve_manifest_dread_choice(second_id)
    assert [o.name for o in eng.state.battlefield] == [face_down.FACE_DOWN_NAME]
    assert eng.state.battlefield[0].instance_id == second_id
    assert [o.name for o in player.graveyard] == ["Top"]
    assert [o.name for o in player.library] == ["Deep"]


# -- Zone changes reveal (RULE 708.9) ---------------------------------------


def test_a_face_down_permanent_is_revealed_when_it_leaves_the_battlefield():
    eng = make_engine()
    obj = _face_down_on_battlefield(eng, morph_card())
    eng.rules.put_into_graveyard(obj)
    assert obj.face_down is False
    assert obj.name == "Willbender"
    assert obj.zone == Zone.GRAVEYARD


def test_the_wire_view_never_ships_a_face_down_card_identity():
    """RULE 708.5: nobody but its controller may look — and the payload
    simply doesn't carry the identity, for any viewer."""
    eng = make_engine()
    obj = _face_down_on_battlefield(eng, morph_card())
    data = obj.to_dict()
    assert data["face_down"] is True
    assert data["name"] == face_down.FACE_DOWN_NAME
    assert data["card_id"] == face_down.FACE_DOWN_CARD_ID
    assert "Willbender" not in str(data)


# -- Parser recognition ------------------------------------------------------


def test_parser_recognizes_manifest_and_cloak_clauses():
    from mtg_analyzer.parser.oracle.gate import parse_oracle

    card = Card(
        id="m", name="Manifester", type_line="Creature — Human",
        is_creature=True, power=2, toughness=2,
        oracle_text="When this creature enters, manifest the top card of your library.",
    )
    result = parse_oracle(card)
    assert result.coverage == "MODELED"
    effects = [e for spec in result.specs for e in spec.effects]
    assert [(e.type, e.params.get("count"), e.params.get("kind")) for e in effects] == [
        ("manifest", 1, "manifest")
    ]


def test_parser_recognizes_manifest_dread():
    from mtg_analyzer.parser.oracle.gate import parse_oracle

    card = Card(
        id="d", name="Dreader", type_line="Creature — Human",
        is_creature=True, power=2, toughness=2,
        oracle_text="When this creature dies, manifest dread.",
    )
    result = parse_oracle(card)
    assert result.coverage == "MODELED"
    assert [e.type for spec in result.specs for e in spec.effects] == ["manifest_dread"]


# -- Replay export round trip ------------------------------------------------


def test_replay_export_round_trips_a_face_down_permanent():
    """The Replay/Puzzle descriptor keeps *which* card it is (the front face
    is untouched by the swap) and that it is face down, so re-opening a saved
    board doesn't silently reveal a morph."""
    from mtg_analyzer.services import replay

    eng = make_engine()
    obj = _face_down_on_battlefield(eng, morph_card(name="Willbender", cost="{1}{U}"))
    data = replay.serialize_replay(eng.state)
    entry = data["battlefield"][0]
    assert entry["name"] == "Willbender"
    assert (entry["face_down"], entry["face_down_kind"]) == (True, "morph")

    rebuilt = replay.build_object(
        entry, owner_id="p1", controller_id="p1",
        cards_by_name={"Willbender": morph_card(name="Willbender", cost="{1}{U}")},
    )
    assert rebuilt.face_down is True
    assert rebuilt.name == face_down.FACE_DOWN_NAME
    assert (rebuilt.power, rebuilt.toughness) == (2, 2)
    # …and it can still be turned face up, i.e. the stashed bundle is real.
    assert [o["kind"] for o in face_down.turn_face_up_options(rebuilt)] == ["morph"]
