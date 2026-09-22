"""The RULE 9 casual variants: Planechase (901), Archenemy (904) and
Vanguard (902), plus the `GameFormat` record that turns them on.

Reference: CR 901, 902, 904, and CR 8's free-for-all baseline. The narrative
lives in `docs/implementation-state/Done_Backend.md` ("Casual variants").
"""

import pytest

from mtg_analyzer.game import variants
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.decks import formats as game_format
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.decks.formats import get_format
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.variant_card_database import (
    card_for,
    default_variant_card_database,
)


def deck(n=20):
    return [
        Card(id=f"c{i}", name=f"Card {i}", type_line="Creature — Bear",
             is_creature=True, power=2, toughness=2)
        for i in range(n)
    ]


def make_engine(fmt=None, archenemy_id=None):
    return GameEngine.new_game(
        [("p1", "Alice", deck()), ("p2", "Bob", deck())],
        starting_life=20, starting_hand=0,
        game_format=fmt, archenemy_id=archenemy_id,
    )


# -- The format record -------------------------------------------------------


def test_a_format_supplies_the_starting_numbers():
    eng = make_engine("commander")
    assert eng.state.format_name == "commander"
    assert eng.state.player_by_id("p1").life == 40
    assert len(eng.state.player_by_id("p1").hand) == 7


def test_an_unknown_format_falls_back_to_commander_rather_than_erroring():
    assert get_format("no-such-format").name == "commander"
    assert get_format(None).name == "commander"


def test_no_format_leaves_every_existing_caller_untouched():
    """The explicit numbers still win, and no variant state is created."""
    eng = make_engine()
    assert eng.state.planar_deck == []
    assert eng.state.archenemy_id is None
    assert eng.state.player_by_id("p1").life == 20


# -- The committed catalogue -------------------------------------------------


def test_the_catalogue_holds_all_three_variant_card_types():
    db = default_variant_card_database()
    assert len(db.of_kind("plane")) > 100
    assert len(db.of_kind("scheme")) > 50
    assert len(db.of_kind("vanguard")) > 50


def test_a_catalogue_entry_becomes_a_playable_card():
    entry = default_variant_card_database().of_kind("plane")[0]
    card = card_for(entry)
    assert card.type_line.startswith("Plane")
    assert card.oracle_text


# -- Planechase (RULE 901) ---------------------------------------------------


def test_a_planechase_game_starts_with_a_face_up_plane():
    eng = make_engine("planechase")
    assert len(eng.state.planar_deck) == variants.DEFAULT_PLANAR_DECK_SIZE
    plane = variants.active_plane(eng.state)
    # Case-insensitive: the real catalogue includes silver-border/joke
    # printings (e.g. Secret Lair "sAnS mERcY") with scrambled-case text on
    # every field, and classification is layout-based, not text-based
    # (VariantCardDatabase._load), so a plane's type_line casing isn't
    # actually guaranteed.
    assert plane is not None and plane.card.type_line.lower().startswith("plane")
    assert eng.state.to_dict()["active_plane"]["name"] == plane.name


def _plane_object(name, owner_id="p1", text="", type_line="Plane — Dominaria"):
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    obj = GameObject(
        Card(id=name, name=name, type_line=type_line, layout="planar", oracle_text=text),
        owner_id=owner_id, zone=Zone.COMMAND,
    )
    bind_from_catalogue(obj)
    return obj


def test_planeswalking_moves_the_plane_to_the_bottom_and_fires_both_events():
    # A hand-built two-plane deck rather than the random one: a randomly
    # drawn deck can put a *phenomenon* next, and RULE 901.18 would then
    # planeswalk straight on again — correct behaviour, but it's tested on
    # its own below and would make this assertion about the bottom card
    # depend on the shuffle.
    eng = make_engine("planechase")
    eng.state.planar_deck = [_plane_object("Under"), _plane_object("Top")]
    seen = []
    eng.state.subscribe(lambda e: seen.append(e))
    left = variants.active_plane(eng.state)
    arrived = eng.rules.planeswalk(eng.state.player_by_id("p1"))
    assert left.name == "Top" and arrived.name == "Under"
    assert eng.state.planar_deck[0] is left  # bottom of the deck
    kinds = [e.type for e in seen]
    assert kinds.index(EventType.PLANESWALKED_AWAY) < kinds.index(EventType.PLANESWALKED_TO)


def test_the_planar_die_is_free_the_first_time_and_costs_x_after():
    """RULE 901.6b: {X} where X is the number of previous rolls this turn."""
    eng = make_engine("planechase")
    player = eng.state.player_by_id("p1")
    eng.state.active_player_index = 0
    assert eng.planar_die_cost(player).symbols == []
    assert eng.can_roll_planar_die(player) is True
    eng.roll_planar_die(player)
    assert eng.planar_die_cost(player).converted_mana_cost == 1
    assert eng.can_roll_planar_die(player) is False  # no mana in the pool
    player.mana_pool.add("C", 1)
    assert eng.can_roll_planar_die(player) is True


def test_a_roll_a_card_caused_counts_toward_the_next_special_action_cost():
    """RULE 901.6b counts *rolls*, not special actions: the tally is read off the roll events."""
    eng = make_engine("planechase")
    player = eng.state.player_by_id("p1")
    eng.state.active_player_index = 0
    eng.rules.roll_planar_die(player)          # e.g. an effect that rolls it for free
    assert eng.state.planar_die_rolls_this_turn == {"p1": 1}
    assert eng.planar_die_cost(player).converted_mana_cost == 1


def test_the_roll_tally_resets_each_turn():
    eng = make_engine("planechase")
    player = eng.state.player_by_id("p1")
    eng.state.active_player_index = 0
    eng.roll_planar_die(player)
    eng.begin_turn()
    assert eng.state.planar_die_rolls_this_turn == {}


@pytest.mark.parametrize("face", ["chaos", "planeswalk", "blank"])
def test_each_planar_die_face_does_its_thing(monkeypatch, face):
    eng = make_engine("planechase")
    player = eng.state.player_by_id("p1")
    monkeypatch.setattr(eng.rules, "random_choice", lambda options: face)
    before = variants.active_plane(eng.state)
    seen = []
    eng.state.subscribe(lambda e: seen.append(e))
    assert eng.rules.roll_planar_die(player) == face
    chaos_fired = any(e.type == EventType.CHAOS_ENSUED for e in seen)
    walked = variants.active_plane(eng.state) is not before
    assert (chaos_fired, walked) == (face == "chaos", face == "planeswalk")


def test_the_planar_die_has_one_chaos_one_planeswalk_and_four_blanks():
    """RULE 901.6a."""
    faces = variants.PLANAR_DIE_FACES
    assert len(faces) == 6
    assert faces.count("chaos") == 1
    assert faces.count("planeswalk") == 1
    assert faces.count("blank") == 4


def test_a_planes_ability_functions_from_the_command_zone():
    """RULE 901.7 — the face-up plane's own triggered ability fires."""
    eng = make_engine("planechase")
    plane_card = Card(
        id="tp", name="Testplane", type_line="Plane — Dominaria", layout="planar",
        oracle_text="Whenever chaos ensues, you gain 3 life.",
    )
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    plane = GameObject(plane_card, owner_id="p1", zone=Zone.COMMAND)
    bind_from_catalogue(plane)
    eng.state.planar_deck.append(plane)  # top of the deck = face up
    player = eng.state.player_by_id("p1")
    eng.state.fire_event(
        __import__("mtg_analyzer.models.game.events", fromlist=["GameEvent"]).GameEvent(
            EventType.CHAOS_ENSUED, player_id="p1", controller_id="p1"
        )
    )
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert player.life == 23


def test_the_planar_die_is_offered_as_a_legal_action_on_your_own_turn_only():
    eng = make_engine("planechase")
    eng.state.active_player_index = 0
    actions = eng.legal_actions(eng.state.player_by_id("p1"))
    assert any(a["type"] == "roll_planar_die" for a in actions)
    assert not any(
        a["type"] == "roll_planar_die"
        for a in eng.legal_actions(eng.state.player_by_id("p2"))
    )


# -- Archenemy (RULE 904) ----------------------------------------------------


def test_the_archenemy_gets_a_scheme_deck_and_forty_life():
    eng = make_engine("archenemy", archenemy_id="p2")
    archenemy, other = eng.state.player_by_id("p2"), eng.state.player_by_id("p1")
    assert eng.state.archenemy_id == "p2"
    assert len(archenemy.scheme_deck) == variants.DEFAULT_SCHEME_DECK_SIZE
    assert archenemy.life == 40 and other.life == 20
    assert other.scheme_deck == []


def test_setting_a_scheme_in_motion_fires_its_trigger():
    eng = make_engine("archenemy", archenemy_id="p1")
    player = eng.state.player_by_id("p1")
    scheme_card = Card(
        id="s", name="Testscheme", type_line="Scheme", layout="scheme",
        oracle_text="When you set this scheme in motion, you gain 5 life.",
    )
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    scheme = GameObject(scheme_card, owner_id="p1", zone=Zone.COMMAND)
    bind_from_catalogue(scheme)
    player.scheme_deck.append(scheme)
    eng.rules.set_scheme_in_motion(player)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert player.life == 45


def test_a_non_ongoing_scheme_goes_back_under_its_deck():
    """RULE 904.10."""
    eng = make_engine("archenemy", archenemy_id="p1")
    player = eng.state.player_by_id("p1")
    before = len(player.scheme_deck)
    scheme = eng.rules.set_scheme_in_motion(player)
    if "ongoing" not in scheme.card.type_line.lower():
        assert player.ongoing_schemes == []
        assert player.scheme_deck[0] is scheme
        assert len(player.scheme_deck) == before


def test_an_ongoing_scheme_stays_face_up_until_abandoned():
    """RULE 904.9/904.11."""
    eng = make_engine("archenemy", archenemy_id="p1")
    player = eng.state.player_by_id("p1")
    ongoing = GameObject(
        Card(id="o", name="Ongoing Test", type_line="Ongoing Scheme", layout="scheme",
             oracle_text="When you set this scheme in motion, you gain 1 life."),
        owner_id="p1", zone=Zone.COMMAND,
    )
    player.scheme_deck.append(ongoing)
    eng.rules.set_scheme_in_motion(player)
    assert player.ongoing_schemes == [ongoing]
    assert eng.rules.abandon_scheme(player, ongoing) is True
    assert player.ongoing_schemes == []
    assert player.scheme_deck[0] is ongoing


def test_the_archenemys_precombat_main_phase_sets_a_scheme_in_motion():
    """RULE 904.7 — a turn-based action, like the Saga lore counter."""
    eng = make_engine("archenemy", archenemy_id="p1")
    player = eng.state.player_by_id("p1")
    eng.state.active_player_index = 0
    before = len(player.scheme_deck)
    eng._step_main1()
    assert len(player.scheme_deck) + len(player.ongoing_schemes) == before


def test_a_non_archenemy_never_sets_a_scheme_in_motion():
    eng = make_engine("archenemy", archenemy_id="p2")
    eng.state.active_player_index = 0  # Alice, who is not the archenemy
    eng._step_main1()
    assert eng.state.player_by_id("p1").ongoing_schemes == []


# -- Vanguard (RULE 902) -----------------------------------------------------


def test_a_vanguard_game_gives_each_player_an_avatar():
    eng = make_engine("vanguard")
    for player in eng.state.players:
        assert player.vanguard is not None
        assert player.vanguard.card.type_line.startswith("Vanguard")
        assert player.vanguard.zone == Zone.COMMAND


def test_an_avatars_hand_and_life_modifiers_apply(monkeypatch):
    """RULE 902.3/902.4 — Titania is +2 cards / -5 life."""
    monkeypatch.setattr(
        variants, "build_vanguard",
        lambda owner_id, name=None: _named_avatar("Titania", owner_id),
    )
    eng = GameEngine.new_game(
        [("p1", "Alice", deck()), ("p2", "Bob", deck())], game_format="vanguard"
    )
    player = eng.state.player_by_id("p1")
    assert player.hand_size_modifier == 2
    assert len(player.hand) == 9          # 7 + 2 (RULE 902.3)
    assert player.life == 20 - 5          # RULE 902.4


def _named_avatar(name, owner_id):
    entry = default_variant_card_database().get(name)
    obj = GameObject(card_for(entry), owner_id=owner_id, zone=Zone.COMMAND)
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    bind_from_catalogue(obj)
    return obj


def test_an_avatars_static_ability_applies_from_the_command_zone():
    """RULE 902.4 — the avatar's abilities function while it's there."""
    eng = make_engine()
    player = eng.state.player_by_id("p1")
    avatar = GameObject(
        Card(id="av", name="Test Avatar", type_line="Vanguard", layout="vanguard",
             oracle_text="Creatures you control get +1/+1."),
        owner_id="p1", zone=Zone.COMMAND,
    )
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.game import continuous

    bind_from_catalogue(avatar)
    player.vanguard = avatar
    bear = GameObject(deck(1)[0], owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    continuous.recompute(eng.state)
    assert (bear.power, bear.toughness) == (3, 3)


# -- Parser recognition ------------------------------------------------------


def test_parser_recognizes_the_compound_plane_template():
    card = Card(
        id="p", name="Testplane", type_line="Plane — Dominaria", layout="planar",
        oracle_text=(
            "When you planeswalk to Testplane and at the beginning of your upkeep, "
            "you gain 1 life.\nWhenever chaos ensues, draw a card."
        ),
    )
    result = parse_oracle(card)
    assert result.coverage == "MODELED"
    triggers = [s.trigger for s in result.specs]
    assert {"event": "PLANESWALKED_TO"} in triggers
    assert {"event": "STEP_BEGIN", "filter": {"step": "upkeep"}} in triggers
    assert {"event": "CHAOS_ENSUED"} in triggers


def test_parser_recognizes_planeswalking_away_and_scheme_triggers():
    away = parse_oracle(
        Card(id="a", name="Awayplane", type_line="Plane — Dominaria", layout="planar",
             oracle_text="When you planeswalk away from Awayplane, draw a card.")
    )
    assert away.coverage == "MODELED"
    assert away.specs[0].trigger == {"event": "PLANESWALKED_AWAY"}
    scheme = parse_oracle(
        Card(id="s", name="Ascheme", type_line="Scheme", layout="scheme",
             oracle_text="When you set this scheme in motion, draw two cards.")
    )
    assert scheme.coverage == "MODELED"
    assert scheme.specs[0].trigger == {"event": "SCHEME_SET_IN_MOTION"}


def test_real_catalogue_cards_parse_without_crashing():
    """The catalogue is real Scryfall text — most of it is exotic and stays
    `UNMODELED` (fail-closed), but nothing may blow up parsing it."""
    db = default_variant_card_database()
    for kind in ("plane", "scheme", "vanguard"):
        for entry in db.of_kind(kind):
            assert parse_oracle(card_for(entry)).coverage in (
                "MODELED", "UNMODELED", "NEVER_SUPPORTED"
            )


def test_a_phenomenon_planeswalks_the_table_straight_on(monkeypatch):
    """RULE 901.17/901.18: a phenomenon is encountered, then left at once."""
    eng = make_engine("planechase")
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    phenomenon = GameObject(
        Card(id="ph", name="Testphenomenon", type_line="Phenomenon", layout="planar",
             oracle_text="When you encounter Testphenomenon, you gain 2 life."),
        owner_id="p1", zone=Zone.COMMAND,
    )
    bind_from_catalogue(phenomenon)
    # Put the phenomenon directly under the top card, so one planeswalk lands
    # on it and RULE 901.18 must carry the table off it again.
    eng.state.planar_deck.insert(len(eng.state.planar_deck) - 1, phenomenon)
    player = eng.state.player_by_id("p1")
    arrived = eng.rules.planeswalk(player)
    assert arrived is not phenomenon
    assert not variants.is_phenomenon(arrived)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert player.life == 22  # the phenomenon's own ability still resolved


def test_a_planar_deck_holds_at_most_two_phenomena_and_starts_on_a_plane():
    """RULE 901.15/901.9."""
    for _ in range(5):
        deck_objs = variants.build_planar_deck("p1")
        assert len([o for o in deck_objs if variants.is_phenomenon(o)]) <= variants.MAX_PHENOMENA
        assert not variants.is_phenomenon(deck_objs[-1])
