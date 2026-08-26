"""Two layer-effect families the RULE 613 engine was missing entirely.

**Standing granted protection (RULE 702.16, layer 6).** `combat.
is_protected_from` read only printed text plus `temp_protections` — a
*resolve-time* "until end of turn" grant (Mother of Runes). There was no
continuously-re-derived concept at all, so "Cats you control have protection
from Rats" (Hungry Lynx), "All creatures have protection from black"
(Absolute Grace/Absolute Law), "White creatures you control have protection
from black" (Righteous War) and "~/Enchanted creature has protection from the
chosen color" (Voice of All/Flickering Ward) were all unmodeled. Now a
`grant_protection` `StaticAbility` stamps `GameObject._granted_protections`
every `continuous.recompute`, which `is_protected_from` unions in — so it
stops applying on its own the moment its source leaves (RULE 613.6), with no
teardown code.

The quality words are normalized **engine-side** (`continuous.
_protection_qualities` → `combat.protections_of_text`): the parser front end
can't do it, since it must stay free of `game/` imports.

**Type grants past the battlefield (RULE 613.4a, layer 4).** The layer engine
only ever walks battlefield permanents, so Arcane Adaptation/Leyline of
Transformation's "The same is true for creature spells you control and
creature cards you own that aren't on the battlefield" and Ashes of the
Fallen's "Each creature card in your graveyard has the chosen creature type
in addition to its other types" had nowhere to land. `continuous.
_apply_off_battlefield_types` is a dedicated pass over the controller's
non-battlefield zones + their spells on the stack; because those objects
never see `reset_derived`, the pass tracks what it stamped on the state and
clears it first — that's what makes the grant vanish with its source.

Reference: mtg_analyzer/game/{combat,continuous,effects}.py,
mtg_analyzer/parser/oracle/catalogue/static_handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.combat import is_protected_from
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _card(name, type_line, oracle_text="", **kw):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text, **kw)


def _creature(name, type_line="Creature — Bear", oracle_text="", colors=None):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=2, toughness=2, oracle_text=oracle_text, color_identity=list(colors or []),
    )


def _state():
    p1, p2 = Player(id="p1", life=20), Player(id="p2", life=20)
    return GameState(players=[p1, p2]), p1, p2


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# -- protection: parse side ---------------------------------------------------


def test_tribal_protection_grant_is_recognized():
    (spec,) = static_effect_specs("cats you control have protection from rats")
    assert spec.type == "grant_protection_static"
    assert spec.params == {
        "affects": "creatures_you_control", "subtype": "Cat", "protections": ["rats"],
    }


def test_global_protection_grant_is_recognized():
    (spec,) = static_effect_specs("all creatures have protection from black")
    assert spec.params == {"affects": "all_creatures", "protections": ["black"]}


def test_colour_scoped_protection_grant_is_recognized():
    (spec,) = static_effect_specs("white creatures you control have protection from black")
    assert spec.params["color"] == ["W"]
    assert spec.params["protections"] == ["black"]


def test_chosen_colour_protection_grant_is_dynamic():
    (spec,) = static_effect_specs("enchanted creature has protection from the chosen color")
    assert spec.params == {
        "affects": "attached_permanent", "protection_from_chosen_color": True,
    }


def test_multi_quality_protection_grant_splits_on_and_from():
    (spec,) = static_effect_specs("enchanted creature has protection from red and from blue")
    assert spec.params["protections"] == ["red", "blue"]


def test_computed_protection_quality_stays_unclaimed():
    # Rebbec's "protection from each mana value among artifacts you control"
    # is a per-source *computed* quality, not a fixed one — fail-closed.
    assert static_effect_specs(
        "artifacts you control have protection from each mana value among artifacts you control"
    ) is None


def test_righteous_war_and_absolute_grace_are_modeled():
    for card in (
        _card("Righteous War", "Enchantment",
              "White creatures you control have protection from black.\n"
              "Black creatures you control have protection from white."),
        _card("Absolute Grace", "Enchantment", "All creatures have protection from black."),
    ):
        result = parse_oracle(card)
        assert result.coverage != UNMODELED, card.name
        assert result.unclaimed == [], card.name


def test_voice_of_all_self_chosen_colour_is_modeled():
    card = _creature(
        "Voice of All", "Creature — Angel",
        "Flying\nAs Voice of All enters, choose a color.\n"
        "Voice of All has protection from the chosen color.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


# -- protection: engine side --------------------------------------------------


def test_tribal_protection_grant_actually_protects_and_wears_off():
    state, p1, p2 = _state()
    cat = _bf(state, _creature("Kitty", "Creature — Cat"))
    rat = _bf(state, _creature("Ratty", "Creature — Rat"), controller="p2")
    lynx = _bf(
        state,
        _creature("Hungry Lynx", "Creature — Cat",
                  "Cats you control have protection from Rats."),
    )

    continuous.recompute(state)
    assert cat.granted_protections == {"rats"}
    assert is_protected_from(cat, rat)
    assert not is_protected_from(rat, cat)

    # RULE 613.6 — the grant is re-derived from scratch, so removing its
    # source removes it with no teardown code.
    state.battlefield.remove(lynx)
    continuous.recompute(state)
    assert cat.granted_protections == set()
    assert not is_protected_from(cat, rat)


def test_colour_protection_grant_matches_a_sources_colour():
    state, p1, p2 = _state()
    white = _bf(state, _creature("White Knight", colors=["W"]))
    black = _bf(state, _creature("Black Knight", colors=["B"]), controller="p2")
    _bf(state, _card("Righteous War", "Enchantment",
                     "White creatures you control have protection from black."))

    continuous.recompute(state)
    assert white.granted_protections == {"B"}
    assert is_protected_from(white, black)


def test_chosen_colour_protection_reads_the_choice_live():
    state, p1, p2 = _state()
    host = _bf(state, _creature("Bear"))
    red = _bf(state, _creature("Red Bear", colors=["R"]), controller="p2")
    blue = _bf(state, _creature("Blue Bear", colors=["U"]), controller="p2")
    ward = _bf(
        state,
        _card("Flickering Ward", "Enchantment — Aura",
              "Enchant creature\nEnchanted creature has protection from the chosen color."),
    )
    ward.attached_to = host.instance_id

    # No choice made yet — nothing is granted (the same safe fallback every
    # other `*_from_source` selector gets).
    continuous.recompute(state)
    assert host.granted_protections == set()

    ward.chosen_color = "R"
    continuous.recompute(state)
    assert is_protected_from(host, red)
    assert not is_protected_from(host, blue)

    # Re-choosing (Replay/Puzzle mode) updates the board rather than being
    # baked in once.
    ward.chosen_color = "U"
    continuous.recompute(state)
    assert is_protected_from(host, blue)
    assert not is_protected_from(host, red)


def test_standing_protection_shows_on_the_board_badges():
    state, p1, p2 = _state()
    cat = _bf(state, _creature("Kitty", "Creature — Cat"))
    _bf(state, _creature("Hungry Lynx", "Creature — Cat",
                         "Cats you control have protection from Rats."))
    continuous.recompute(state)
    assert "Protection: rats" in cat.to_dict()["keywords"]


# -- type extension past the battlefield: parse side --------------------------


def test_group_chosen_type_grant_is_recognized():
    (spec,) = static_effect_specs(
        "each creature you control is the chosen type in addition to its other types"
    )
    assert spec.type == "type_change"
    assert spec.params == {
        "affects": "creatures_you_control", "add_subtypes_from_source": True,
    }


def test_arcane_adaptation_tail_becomes_an_off_battlefield_param():
    (spec,) = static_effect_specs(
        "creatures you control are the chosen type in addition to their other types. "
        "the same is true for creature spells you control and creature cards you own "
        "that aren't on the battlefield"
    )
    assert spec.params["off_battlefield"] == "cards_you_own"
    assert spec.params["affects"] == "creatures_you_control"


def test_ashes_of_the_fallen_has_no_battlefield_half():
    (spec,) = static_effect_specs(
        "each creature card in your graveyard has the chosen creature type "
        "in addition to its other types"
    )
    assert spec.params["off_battlefield"] == "your_graveyard"
    assert spec.params["affects"] == "off_battlefield_only"


def test_lands_you_control_chosen_type_is_recognized():
    (spec,) = static_effect_specs(
        "lands you control are the chosen type in addition to their other types"
    )
    assert spec.params["affects"] == "lands_you_control"


def test_tribal_narrowed_chosen_type_keeps_its_subtype_filter():
    # Lifecraft Engine's "Vehicle creatures you control …".
    (spec,) = static_effect_specs(
        "vehicle creatures you control are the chosen creature type "
        "in addition to their other types"
    )
    assert spec.params["subtype"] == "Vehicle"


def test_xenograft_and_arcane_adaptation_are_modeled():
    for card in (
        _card("Xenograft", "Enchantment",
              "As Xenograft enters, choose a creature type.\n"
              "Each creature you control is the chosen type in addition to its other types."),
        _card("Arcane Adaptation", "Enchantment",
              "As Arcane Adaptation enters, choose a creature type.\n"
              "Creatures you control are the chosen type in addition to their other "
              "types. The same is true for creature spells you control and creature "
              "cards you own that aren't on the battlefield."),
        _card("Ashes of the Fallen", "Artifact",
              "As Ashes of the Fallen enters, choose a creature type.\n"
              "Each creature card in your graveyard has the chosen creature type "
              "in addition to its other types."),
    ):
        result = parse_oracle(card)
        assert result.coverage != UNMODELED, card.name
        assert result.unclaimed == [], card.name


# -- type extension past the battlefield: engine side -------------------------


def _graveyard_card(player, card):
    obj = GameObject(card, owner_id=player.id, zone=Zone.GRAVEYARD)
    player.graveyard.append(obj)
    return obj


def test_ashes_of_the_fallen_types_a_graveyard_creature_card():
    state, p1, p2 = _state()
    bear = _graveyard_card(p1, _creature("Graveyard Bear"))
    land = _graveyard_card(p1, _card("Graveyard Land", "Land"))
    theirs = _graveyard_card(p2, _creature("Their Bear"))
    ashes = _bf(
        state,
        _card("Ashes of the Fallen", "Artifact",
              "Each creature card in your graveyard has the chosen creature type "
              "in addition to its other types."),
    )
    ashes.chosen_type = "Zombie"

    continuous.recompute(state)
    assert continuous.has_subtype(bear, "Zombie")
    assert not continuous.has_subtype(land, "Zombie")  # creature *cards* only
    assert not continuous.has_subtype(theirs, "Zombie")  # your graveyard only

    # RULE 613.6 again: these objects never see `reset_derived`, so the pass
    # has to clear what it stamped — otherwise the type would stick forever.
    state.battlefield.remove(ashes)
    continuous.recompute(state)
    assert not continuous.has_subtype(bear, "Zombie")


def test_arcane_adaptation_types_cards_in_every_zone_you_own():
    state, p1, p2 = _state()
    in_hand = GameObject(_creature("Hand Bear"), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(in_hand)
    in_library = GameObject(_creature("Library Bear"), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(in_library)
    in_graveyard = _graveyard_card(p1, _creature("Dead Bear"))
    on_battlefield = _bf(state, _creature("Live Bear"))

    adaptation = _bf(
        state,
        _card("Arcane Adaptation", "Enchantment",
              "Creatures you control are the chosen type in addition to their other "
              "types. The same is true for creature spells you control and creature "
              "cards you own that aren't on the battlefield."),
    )
    adaptation.chosen_type = "Sliver"

    continuous.recompute(state)
    for obj in (in_hand, in_library, in_graveyard, on_battlefield):
        assert continuous.has_subtype(obj, "Sliver"), obj.name


def test_sword_cycle_compound_anthem_plus_protection_is_recognized():
    # "Equipped creature gets +2/+2 and has protection from red and from
    # blue." — the whole Sword-of-X-and-Y cycle. Needs its own row: the
    # ordinary anthem's "and has <keywords>" tail runs through
    # `_flag_keywords`, which rejects protection (not a flag keyword) and
    # would fail the whole clause closed.
    anthem, protection = static_effect_specs(
        "equipped creature gets +2/+2 and has protection from red and from blue"
    )
    assert anthem.type == "anthem"
    assert anthem.params == {"power": 2, "toughness": 2, "affects": "attached_permanent"}
    assert protection.params["protections"] == ["red", "blue"]


def test_group_compound_anthem_plus_protection_keeps_its_scope():
    # Feline Sovereign/Haytham Kenway.
    anthem, protection = static_effect_specs(
        "other cats you control get +1/+1 and have protection from dogs"
    )
    assert anthem.params["affects"] == "other_creatures_you_control"
    assert protection.params["affects"] == "other_creatures_you_control"
    assert protection.params["subtype"] == "Cat"


def test_plain_keyword_anthem_tail_still_works():
    # Regression: the compound protection rows sit before the ordinary
    # anthem, so make sure they didn't shadow it.
    anthem, grant = static_effect_specs("equipped creature gets +2/+2 and has trample")
    assert anthem.type == "anthem"
    assert grant.type == "grant_keyword"


def test_sword_cycle_card_with_a_modelable_trigger_body_is_modeled():
    # Sword-shaped end to end: the compound anthem+protection line *plus*
    # the attached-subject damage trigger (RULE 303.4/301.5's
    # `attached_permanent` subject, which `_DAMAGE_TRIGGER_RE` gained
    # alongside the group one). The real Swords' own trigger bodies
    # ("*that player* discards a card") reference the damaged player — an
    # indirect referent the parser can't model — so this uses a Rogue's
    # Gloves-shaped body instead.
    card = _card(
        "Sword of Draw and Protect",
        "Artifact — Equipment",
        "Equipped creature gets +2/+2 and has protection from black and from green.\n"
        "Whenever equipped creature deals combat damage to a player, draw a card.\n"
        "Equip {2}",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_attached_subject_damage_trigger_fires_for_the_host():
    from mtg_analyzer.game import continuous
    from mtg_analyzer.game.game_engine import GameEngine

    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    host = _bf(state, _creature("Bear"))
    bystander = _bf(state, _creature("Bystander"))
    # Deliberately *not* a real card name: the real Rogue's Gloves is
    # hand-authored in `ability_catalogue.py` (as an optional "you may
    # draw"), which would exercise that entry rather than this batch's new
    # oracle-text recognition.
    gloves = _bf(
        state,
        _card("Scribe's Gloves", "Artifact — Equipment",
              "Whenever equipped creature deals combat damage to a player, draw a card.\n"
              "Equip {2}"),
    )
    gloves.attached_to = host.instance_id
    p1 = state.player_by_id("p1")
    p1.library.append(GameObject(_creature("Library Bear"), owner_id="p1", zone=Zone.LIBRARY))
    continuous.recompute(state)

    eng.rules.deal_damage(state.player_by_id("p2"), 2, source=bystander, combat=True)
    assert eng.rules.put_triggers_on_stack() == 0

    eng.rules.deal_damage(state.player_by_id("p2"), 2, source=host, combat=True)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert len(p1.hand) == 1


# -- PAR-6: RULE 702.16n/p's "this effect doesn't remove ~" exemption --------
# Black Ward &c grant their own host protection from a colour they themselves
# are — without this exemption, RULE 704.5m would detach the Aura the very
# next SBA pass. Parser side: `_PROTECTION_SELF_EXEMPT_TAIL` on the
# attached-permanent protection rows. Engine side: a new
# `GameObject._protection_self_exempt` flag, set on the *granting* object
# (not its host) by `continuous.py`'s layer-6 pass, read by
# `_attachment_legal` (shared by both initial attach and
# `_revalidate_attachments`).


def test_self_exempt_tail_is_recognized_on_a_bare_protection_grant():
    (spec,) = static_effect_specs(
        "enchanted creature has protection from black. this effect doesn't remove ~"
    )
    assert spec.type == "grant_protection_static"
    assert spec.params == {
        "affects": "attached_permanent", "protections": ["black"],
        "exempt_own_attachment": True,
    }


def test_self_exempt_tail_is_recognized_on_a_compound_anthem_protection_grant():
    # Tattoo Ward/Spectra Ward's "+N/+N and protection" shape.
    anthem, protection = static_effect_specs(
        "enchanted creature gets +1/+1 and has protection from enchantments. "
        "this effect doesn't remove ~"
    )
    assert anthem.type == "anthem"
    assert protection.params == {
        "affects": "attached_permanent", "protections": ["enchantments"],
        "exempt_own_attachment": True,
    }


def test_bare_protection_grant_without_the_tail_has_no_exemption():
    # Regression: the tail is optional — an ordinary Aura with no such
    # sentence (most of them) must not pick up the flag.
    (spec,) = static_effect_specs("enchanted creature has protection from black")
    assert spec.params == {"affects": "attached_permanent", "protections": ["black"]}


def test_each_color_quality_folds_to_all_colors():
    # Spectra Ward's own wording ("protection from each color") rather than
    # the more common "protection from all colors".
    anthem, protection = static_effect_specs(
        "enchanted creature gets +2/+2 and has protection from each color. "
        "this effect doesn't remove auras"
    )
    assert anthem.params["power"] == 2
    assert protection.params["protections"] == ["all colors"]
    assert protection.params["exempt_own_attachment"] is True


def test_computed_quality_with_the_tail_still_stays_unclaimed():
    # Pledge of Loyalty: "protection from the colors of permanents you
    # control" is a per-board computed quality, not a fixed one — the tail
    # must not make this half-modeled.
    assert static_effect_specs(
        "enchanted creature has protection from the colors of permanents you "
        "control. this effect doesn't remove ~"
    ) is None


def test_chosen_type_protection_quality_is_recognized():
    # Riders of Gavony's "protection from creatures of the chosen type" — the
    # creature-type sibling of the already-shipped chosen-*colour* dynamic.
    (spec,) = static_effect_specs(
        "human creatures you control have protection from creatures of the chosen type"
    )
    assert spec.params["protection_from_chosen_type"] is True


def test_black_ward_and_friends_are_fully_modeled():
    for card in (
        _card("Black Ward", "Enchantment — Aura",
              "Enchant creature\nEnchanted creature has protection from black. "
              "This effect doesn't remove this Aura."),
        _card("Benevolent Blessing", "Enchantment — Aura",
              "Flash\nEnchant creature\nAs this Aura enters, choose a color.\n"
              "Enchanted creature has protection from the chosen color. This "
              "effect doesn't remove Auras and Equipment you control that are "
              "already attached to it."),
        _card("Spectra Ward", "Enchantment — Aura",
              "Enchant creature\nEnchanted creature gets +2/+2 and has "
              "protection from each color. This effect doesn't remove Auras."),
    ):
        result = parse_oracle(card)
        assert result.coverage != UNMODELED, card.name
        assert result.unclaimed == [], card.name


def test_pledge_of_loyalty_stays_unmodeled():
    # The one real card in this family whose quality genuinely can't be
    # expressed — confirms the tail fix didn't half-model it.
    card = _card(
        "Pledge of Loyalty", "Enchantment — Aura",
        "Enchant creature\nEnchanted creature has protection from the colors "
        "of permanents you control. This effect doesn't remove ~.",
    )
    result = parse_oracle(card)
    assert result.coverage == UNMODELED


def test_self_exempt_aura_stays_attached_when_its_own_grant_would_detach_it():
    # Black Ward is itself black and grants its host protection from black —
    # without RULE 702.16n's exemption, that would make Black Ward's own
    # attachment illegal (RULE 704.5m) the very next SBA pass.
    state, p1, p2 = _state()
    engine = RulesEngine(state)
    host = _bf(state, _creature("Bear"))
    ward = _bf(
        state,
        _card("Black Ward", "Enchantment — Aura",
              "Enchant creature\nEnchanted creature has protection from black. "
              "This effect doesn't remove this Aura.",
              color_identity=["B"]),
    )
    engine.attach_to_target(ward, host)
    assert ward.attached_to == host.instance_id

    continuous.recompute(state)
    assert is_protected_from(host, ward)

    assert engine.check_state_based_actions() is False
    assert ward.attached_to == host.instance_id
    assert ward in state.battlefield


def test_without_the_exemption_flag_the_aura_detaches_as_normal():
    # Same shape as above but with `exempt_own_attachment` left off — this is
    # what RULE 704.5m does by default, and it must still fire for any Aura
    # that doesn't carry the "doesn't remove" text.
    state, p1, p2 = _state()
    engine = RulesEngine(state)
    host = _bf(state, _creature("Bear"))
    ward = _bf(
        state,
        _card("Not Actually Exempt", "Enchantment — Aura",
              "Enchant creature\nEnchanted creature has protection from black.",
              color_identity=["B"]),
    )
    engine.attach_to_target(ward, host)
    assert ward.attached_to == host.instance_id

    continuous.recompute(state)
    assert is_protected_from(host, ward)

    assert engine.check_state_based_actions() is True
    assert ward.attached_to is None
    assert ward not in state.battlefield
    assert ward in p1.graveyard
