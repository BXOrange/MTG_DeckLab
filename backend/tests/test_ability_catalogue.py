"""Tests for the bind-on-load pipeline: catalogue → binder → live abilities,
enters-tapped (RULE 614.1), and activated abilities surfaced as actions."""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game import ability_catalogue
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.services.game_session import GameSessionManager, build_goldfish_engine


def forest():
    return Card(id="Forest", name="Forest", type_line="Basic Land — Forest",
                is_land=True, oracle_text="({T}: Add {G}.)")


def evolving_wilds():
    return Card(id="EW", name="Evolving Wilds", type_line="Land", is_land=True,
                oracle_text="{T}, Sacrifice Evolving Wilds: Search your library "
                            "for a basic land card, put it onto the battlefield "
                            "tapped, then shuffle.")


def tranquil_cove():
    return Card(id="TC", name="Tranquil Cove", type_line="Land", is_land=True,
                oracle_text="Tranquil Cove enters the battlefield tapped.\n"
                            "{T}: Add {W} or {U}.")


def shock_land():
    return Card(id="SV", name="Steam Vents", type_line="Land — Island Mountain", is_land=True,
                oracle_text="As Steam Vents enters the battlefield, you may pay 2 life. "
                            "If you don't, it enters tapped.")


# -- Catalogue & enters-tapped ----------------------------------------------


def test_specs_for_known_card():
    specs = ability_catalogue.specs_for(evolving_wilds())
    assert len(specs) == 1 and specs[0].ability_kind == "activated"


def test_specs_for_unknown_card_is_empty():
    assert ability_catalogue.specs_for(forest()) == []


def test_specs_are_fresh_copies_each_call():
    a = ability_catalogue.specs_for(evolving_wilds())[0]
    b = ability_catalogue.specs_for(evolving_wilds())[0]
    assert a is not b  # binding mutates specs, so each object needs its own


def test_enters_tapped_plain_tapland():
    assert ability_catalogue.enters_tapped(tranquil_cove()) is True


def test_enters_tapped_ignores_conditional_lands():
    # Shock land: "you may pay 2 life" — the choice isn't modeled, stays untapped.
    assert ability_catalogue.enters_tapped(shock_land()) is False


def test_enters_tapped_false_for_normal_land():
    assert ability_catalogue.enters_tapped(forest()) is False


# -- Binding on load --------------------------------------------------------


def test_bind_from_catalogue_attaches_ability():
    obj = GameObject(evolving_wilds(), owner_id="p1", zone=Zone.LIBRARY)
    assert obj.activated_abilities == []
    bind_from_catalogue(obj)
    assert len(obj.activated_abilities) == 1


def test_build_engine_binds_library_and_command():
    engine = build_goldfish_engine([evolving_wilds()], commanders=[evolving_wilds()],
                                   starting_hand=0)
    p1 = engine.state.active_player
    assert p1.library[0].activated_abilities  # bound in the library
    assert p1.command[0].activated_abilities  # and in the command zone


# -- Keyword abilities: catalogue → binder → combat -------------------------


def flyer(keywords=("Flying",), oracle=""):
    return Card(id="CS", name="Cloud Sprite", type_line="Creature — Faerie",
                is_creature=True, power=1, toughness=1,
                keywords=list(keywords), oracle_text=oracle)


def bear():
    return Card(id="B", name="Bear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2, keywords=[])


def test_specs_for_folds_in_keyword_specs():
    specs = ability_catalogue.specs_for(flyer())
    assert [s.keyword["name"] for s in specs if s.ability_kind == "keyword"] == ["flying"]


def test_bind_from_catalogue_docks_flag_keyword():
    obj = GameObject(flyer(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    assert "flying" in obj.intrinsic_keywords


def test_bound_keyword_reaches_combat_recognition():
    from mtg_analyzer.game import combat

    # Card with no Scryfall keyword array — only the bound spec can make combat
    # see flying, so this proves the binder path, not combat's own card scan.
    obj = GameObject(flyer(keywords=[], oracle="Flying"), owner_id="p1", zone=Zone.BATTLEFIELD)
    assert combat.has_flying(obj) is True  # recognized off oracle text already
    obj2 = GameObject(bear(), owner_id="p2", zone=Zone.BATTLEFIELD)
    assert combat.has_flying(obj2) is False

    from mtg_analyzer.game.effect_binder import attach_keyword
    from mtg_analyzer.parser.oracle.spec import AbilitySpec

    attach_keyword(obj2, AbilitySpec(ability_kind="keyword", keyword={"name": "flying"}))
    assert combat.has_flying(obj2) is True
    assert combat.can_block(obj2, GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)) is False


def test_parametric_keyword_is_docked_with_its_parameter():
    # Parametric keywords now bind: they don't join the flag set
    # `intrinsic_keywords`, but their parameter is kept on `parametric_keywords`
    # for the cost/combat-math consumers.
    from mtg_analyzer.game.effect_binder import attach_keyword
    from mtg_analyzer.parser.oracle.spec import AbilitySpec

    obj = GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
    docked = attach_keyword(obj, AbilitySpec(ability_kind="keyword",
                                             keyword={"name": "annihilator", "n": 2}))
    assert docked is True
    assert obj.intrinsic_keywords == set()
    assert obj.parametric_keywords == {"annihilator": {"n": 2}}


def test_landwalk_keyword_binds_to_combat_recognizable_slug():
    from mtg_analyzer.game import combat
    from mtg_analyzer.game.effect_binder import attach_keyword
    from mtg_analyzer.parser.oracle.spec import AbilitySpec

    obj = GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
    attach_keyword(obj, AbilitySpec(ability_kind="keyword",
                                    keyword={"name": "landwalk", "quality": "island"}))
    assert "islandwalk" in obj.intrinsic_keywords
    assert combat.landwalk_subtypes(obj) == frozenset({"island"})


def test_docked_keyword_survives_snapshot_restore():
    import copy

    obj = GameObject(flyer(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    restored = copy.deepcopy(obj)  # how GameState.clone snapshots the board
    assert restored.intrinsic_keywords == {"flying"}


# -- Enters-tapped on the battlefield ---------------------------------------


def test_played_tapland_enters_tapped():
    engine = build_goldfish_engine([tranquil_cove()], starting_hand=1)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.active_player
    land = p1.hand[0]
    engine.play_land(p1, land)
    assert land in engine.state.battlefield and land.tapped is True


def test_played_normal_land_enters_untapped():
    engine = build_goldfish_engine([forest()], starting_hand=1)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.active_player
    land = p1.hand[0]
    engine.play_land(p1, land)
    assert land.tapped is False


# -- Activated ability surfaced as an action --------------------------------


def test_fetch_land_offers_activate_action_and_resolves_tapped():
    mgr = GameSessionManager()
    # Evolving Wilds on top (end of the list is "top"), forests below to fetch.
    session = mgr.create_goldfish(library=[forest()] * 20 + [evolving_wilds()],
                                  starting_hand=1)
    state = session.engine.state
    session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
    for _ in range(20):
        if state.current_step == "main1" and state.turn_number == 1:
            break
        session.apply_action({"type": "advance_step"})
    ew = next(o for o in state.active_player.hand if o.name == "Evolving Wilds")
    session.apply_action({"type": "play_land", "instance_id": ew.instance_id})

    offers = [a for a in session.legal_actions()
              if a.get("type") == "activate_ability" and a.get("instance_id") == ew.instance_id]
    assert offers, "fetch land should offer an activate_ability action"
    assert "{T}" in offers[0]["cost_label"]

    session.apply_action({"type": "activate_ability", "instance_id": ew.instance_id,
                          "ability_index": 0})
    session.apply_action({"type": "pass_priority"})  # resolve → opens the search
    pending = state.pending_choice
    assert pending, "activating the fetch should open a search choice"
    opt = next(o for o in pending["options"] if o["id"] != "decline")
    session.apply_action({"type": "choose", "option_id": opt["id"],
                          "instance_id": opt.get("instance_id")})

    fetched = [o for o in state.battlefield if o.name == "Forest"]
    assert fetched and fetched[0].tapped is True  # fetched onto battlefield tapped
    assert not any(o.name == "Evolving Wilds" for o in state.battlefield)  # sacrificed


# -- "Become a copy" (RULE 706/707): catalogue spec shape --------------------


def test_clever_impersonator_specs_shape():
    card = Card(id="CI", name="Clever Impersonator", type_line="Creature — Illusion",
                is_creature=True, power=3, toughness=3)
    [spec] = ability_catalogue.specs_for(card)
    assert spec.ability_kind == "triggered"
    assert spec.trigger["event"] == "ENTERS_BATTLEFIELD"
    assert spec.effects[0].type == "become_copy"
    assert spec.effects[0].params["target_kind"] == "permanent"


def test_phantasmal_image_carries_the_illusion_subtype_override():
    card = Card(id="PI", name="Phantasmal Image", type_line="Creature — Illusion",
                is_creature=True, power=0, toughness=2)
    [spec] = ability_catalogue.specs_for(card)
    assert spec.effects[0].params["add_subtypes"] == ["Illusion"]


def test_copy_artifact_carries_the_enchantment_type_override():
    card = Card(id="CA", name="Copy Artifact", type_line="Enchantment")
    [spec] = ability_catalogue.specs_for(card)
    assert spec.effects[0].params["add_types"] == ["Enchantment"]
