"""Tests for the "wave 3" one-shot effect families (docs/09): bounce
("return target X to its owner's hand"), graveyard recursion (Regrowth/
Reanimate-shaped), an unrestricted tutor + a basic-land-to-battlefield-tapped
fetch (reusing the existing "search" effect), a bare "Add {mana}." spell body
(Dark Ritual-shaped), the damage handler's "it"/"this land" subject, an
Equipment's own ETB self-attach, and selector-based mass damage ("to each
creature/player/opponent").

Each covers **parser recognition** (+ fail-closed negatives) through
`parse_effect_body` directly, then an **engine-level** test driving the bound
effect through a real `RulesEngine`/`GameEngine` — mirroring
`test_effect_families.py`'s and `test_game_engine.py`'s fixture patterns.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.effect_binder import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.effects import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.game.targeting import ALLOWED_TARGET_KINDS, requirements_with_targets
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec


# ---------------------------------------------------------------------------
# Card / fixture factories (mirrors test_effect_families.py / test_game_engine.py)
# ---------------------------------------------------------------------------


def _bear(name="Bear", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def _land(name="Island"):
    return Card(id=name, name=name, type_line="Basic Land — Island", is_land=True)


def _spell(name, oracle, effects, target=None):
    card = Card(id=name, name=name, type_line="Instant", is_instant=True,
                oracle_text=oracle)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, [AbilitySpec(
        ability_kind="spell_effect", effects=effects, target=target, raw_text=oracle,
    )])
    return obj


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _bf(state, card, controller="p1", tapped=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = tapped
    state.add_to_battlefield(obj)
    return obj


def _enter_battlefield(state, obj, controller_id):
    """Add ``obj`` to the battlefield the way a real entry path does — firing
    `ENTERS_BATTLEFIELD` so a bound "when ~ enters" trigger actually queues
    (unlike `_bf`, which is a bare test fixture with no event)."""
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id=controller_id, object=obj.name,
        instance_id=obj.instance_id, object_types=sorted(obj.type_words),
    ))


# ---------------------------------------------------------------------------
# PARSER RECOGNITION
# ---------------------------------------------------------------------------


def test_return_to_hand_recognizes_target_creature_and_controller_restricted_land():
    plain = parse_effect_body("return target creature to its owner's hand")[0]
    assert plain.type == "return_to_hand"
    assert plain.params == {"target_kind": "creature"}

    bounce_land = parse_effect_body("return a land you control to its owner's hand")[0]
    assert bounce_land.type == "return_to_hand"
    assert bounce_land.params == {"target_kind": "land_you_control"}


def test_return_to_hand_fails_closed_on_the_wrong_destination():
    assert parse_effect_body("return target creature to the battlefield") is None


def test_return_from_graveyard_recognizes_battlefield_and_hand_destinations():
    reanimate = parse_effect_body(
        "return target creature card from your graveyard to the battlefield"
    )[0]
    assert reanimate.type == "return_from_graveyard"
    assert reanimate.params == {"target_kind": "graveyard_creature", "destination": "battlefield"}

    regrowth = parse_effect_body(
        "return target creature card from your graveyard to your hand"
    )[0]
    assert regrowth.params == {"target_kind": "graveyard_creature", "destination": "hand"}


def test_return_from_graveyard_recognizes_any_card_type():
    # Generalized (2026-07-16) from a creature-only, own-graveyard-only
    # clause to the full Regrowth/Reanimate/Deathrite-adjacent family —
    # card type × graveyard scope, see game/targeting.py's
    # `_GRAVEYARD_TARGET_KINDS`.
    artifact = parse_effect_body(
        "return target artifact card from your graveyard to the battlefield"
    )[0]
    assert artifact.params == {"target_kind": "graveyard_artifact", "destination": "battlefield"}

    bare_card = parse_effect_body("return target card from your graveyard to your hand")[0]
    assert bare_card.params == {"target_kind": "graveyard_card", "destination": "hand"}

    instant_or_sorcery = parse_effect_body(
        "return target instant or sorcery card from your graveyard to your hand"
    )[0]
    assert instant_or_sorcery.params == {
        "target_kind": "graveyard_instant_or_sorcery", "destination": "hand",
    }

    nonland_permanent = parse_effect_body(
        "return target nonland permanent card from your graveyard to the battlefield"
    )[0]
    assert nonland_permanent.params == {
        "target_kind": "graveyard_nonland_permanent", "destination": "battlefield",
    }


def test_return_from_graveyard_recognizes_any_and_opponent_scope():
    any_scope = parse_effect_body(
        "return target creature card from a graveyard to its owner's hand"
    )[0]
    assert any_scope.params == {"target_kind": "any_graveyard_creature", "destination": "hand"}

    opponent_scope = parse_effect_body(
        "return target land card from an opponent's graveyard to the battlefield"
    )[0]
    assert opponent_scope.params == {
        "target_kind": "opponent_graveyard_land", "destination": "battlefield",
    }


def test_return_from_graveyard_fails_closed_on_an_unrecognized_shape():
    # A qualifier this batch doesn't model (mana value, "nonlegendary", …)
    # correctly stays unclaimed rather than guessed at.
    assert parse_effect_body(
        "return target creature card with mana value 2 from your graveyard to the battlefield"
    ) is None
    assert parse_effect_body(
        "return target nonlegendary creature card from your graveyard to the battlefield"
    ) is None


def test_exile_target_graveyard_recognizes_both_phrasings():
    # Bojuka Bog's "exile target player's graveyard" and Tormod's Crypt's
    # "exile all cards from target player's graveyard" are the same effect.
    bojuka = parse_effect_body("exile target player's graveyard")[0]
    assert bojuka.type == "exile_target_graveyard"
    assert bojuka.params == {"target_kind": "player"}

    tormod = parse_effect_body("exile all cards from target player's graveyard")[0]
    assert tormod.type == "exile_target_graveyard"
    assert tormod.params == {"target_kind": "player"}


def test_return_from_graveyard_transformed_recognizes_self_and_it():
    dies_shape = parse_effect_body(
        "return it to the battlefield transformed under its owner's control"
    )[0]
    assert dies_shape.type == "return_from_graveyard_transformed"
    assert dies_shape.params == {}

    self_shape = parse_effect_body(
        "return ~ to the battlefield transformed under its owner's control"
    )[0]
    assert self_shape.type == "return_from_graveyard_transformed"


def test_put_from_graveyard_under_its_owners_control_reuses_return_from_graveyard():
    # "put … onto the battlefield under its owner's control" (Kenrith) is
    # the same effect as "return … to the battlefield" (Karmic Guide) —
    # both leave the card under its own owner's control.
    kenrith_shape = parse_effect_body(
        "put target creature card from a graveyard onto the battlefield under its owner's control"
    )[0]
    assert kenrith_shape.type == "return_from_graveyard"
    assert kenrith_shape.params == {
        "target_kind": "any_graveyard_creature", "destination": "battlefield",
    }


def test_reanimate_under_your_control_recognizes_the_steal_shape():
    reanimate = parse_effect_body(
        "put target creature card from a graveyard onto the battlefield under your control"
    )[0]
    assert reanimate.type == "return_from_graveyard"
    assert reanimate.params == {
        "target_kind": "any_graveyard_creature",
        "destination": "battlefield",
        "under_your_control": True,
    }

    puppeteer_clique_shape = parse_effect_body(
        "put target creature card from an opponent's graveyard onto the battlefield under your control"
    )[0]
    assert puppeteer_clique_shape.params == {
        "target_kind": "opponent_graveyard_creature",
        "destination": "battlefield",
        "under_your_control": True,
    }


def test_exile_from_graveyard_recognizes_type_and_scope():
    bare = parse_effect_body("exile target card from a graveyard")[0]
    assert bare.type == "exile"
    assert bare.params == {"target_kind": "any_graveyard_card"}

    land = parse_effect_body("exile target land card from a graveyard")[0]
    assert land.params == {"target_kind": "any_graveyard_land"}

    own = parse_effect_body("exile target creature card from your graveyard")[0]
    assert own.params == {"target_kind": "graveyard_creature"}


def test_lose_life_recognizes_plain_and_selector_forms():
    plain = parse_effect_body("you lose 2 life")[0]
    assert plain.type == "lose_life"
    assert plain.params == {"amount": 2}

    # Batch 5: "target player loses N life" now carries a real RULE 115
    # target instead of silently dropping it (see test_modal_and_creature_
    # filter_family.py for the targeting behavior itself).
    targeted = parse_effect_body("target player loses 3 life")[0]
    assert targeted.params == {"amount": 3, "target_kind": "player"}

    each_opponent = parse_effect_body("each opponent loses 2 life")[0]
    assert each_opponent.params == {"amount": 2, "selector": "each_opponent"}

    each_player = parse_effect_body("each player loses 1 life")[0]
    assert each_player.params == {"amount": 1, "selector": "each_player"}


def test_search_handlers_recognize_the_unrestricted_tutor_and_basic_land_fetch():
    tutor = parse_effect_body(
        "search your library for a card, put that card into your hand, then shuffle"
    )[0]
    assert tutor.type == "search"
    assert tutor.params == {"criteria": {}, "destination": "hand"}

    fetch = parse_effect_body(
        "search your library for a basic land card, put it onto the battlefield "
        "tapped, then shuffle"
    )[0]
    assert fetch.type == "search"
    assert fetch.params == {"criteria": {"basic": True}, "destination": "battlefield_tapped"}


def test_search_handler_recognizes_a_mana_value_qualifier():
    # MEC-12 (fifth pass): "with mana value N or less" is now recognized --
    # this card previously documented the gap as fail-closed.
    spec = parse_effect_body(
        "search your library for a card with mana value 2 or less, put that card "
        "into your hand, then shuffle"
    )[0]
    assert spec.params == {"criteria": {"max_mana_value": 2}, "destination": "hand"}


def test_basic_land_fetch_recognizes_an_up_to_n_count():
    # "up to two basic land cards, put them ..." (Explosive Vegetation/
    # Burnished Hart/Blighted Woodland-shaped) — the plural, RULE
    # 115.1a-adjacent count variant of the singular fetch-land shape above;
    # `SearchLibraryEffect.count` already offers a search "up to N" one card
    # at a time, only recognition was missing (Batch 11's A.2/A.7 pass).
    fetch = parse_effect_body(
        "search your library for up to 2 basic land cards, put them onto "
        "the battlefield tapped, then shuffle"
    )[0]
    assert fetch.type == "search"
    assert fetch.params == {
        "criteria": {"basic": True}, "destination": "battlefield_tapped", "count": 2,
    }


def test_add_mana_handler_recognizes_a_pure_symbol_run():
    ritual = parse_effect_body("add {b}{b}{b}")[0]
    assert ritual.type == "add_mana"
    assert ritual.params == {"colors": ["B", "B", "B"]}


def test_add_mana_handler_recognizes_any_color():
    # A genuine resolve-time player choice (RULE 106.4) — recognized as its
    # own clause shape, resolved interactively by the engine
    # (`RulesEngine.add_mana_any_color`), not guessed at by the parser.
    any_color = parse_effect_body("add 1 mana of any color")[0]
    assert any_color.type == "add_mana"
    assert any_color.params == {"colors": ["any"]}
    # Deliberately narrow: a multi-mana "any color" clause is always
    # templated "any *one* color" instead — a different, unclaimed shape.
    assert parse_effect_body("add 2 mana of any color") is None
    assert parse_effect_body("add 2 mana of any one color") is None


def test_gate_claims_a_bare_add_any_color_spell_as_modeled():
    card = Card(id="Test Ritual", name="Test Ritual", type_line="Instant",
                is_instant=True, oracle_text="Add one mana of any color.")
    result = parse_oracle(card)
    assert result.coverage == MODELED
    assert result.unclaimed == []


def test_attach_handler_recognizes_an_equipments_own_etb_self_attach():
    attach = parse_effect_body("attach it to target creature you control")[0]
    assert attach.type == "attach"
    assert attach.params == {"target_kind": "creature_you_control"}
    self_form = parse_effect_body("attach ~ to target creature you control")[0]
    assert self_form.params == {"target_kind": "creature_you_control"}


def test_damage_handler_accepts_it_and_this_land_subjects():
    it_form = parse_effect_body("it deals 2 damage to target opponent")[0]
    assert it_form.type == "damage"
    assert it_form.params == {"amount": 2, "target_kind": "player"}
    land_form = parse_effect_body("this land deals 2 damage to any target")[0]
    assert land_form.params == {"amount": 2, "target_kind": "any"}


def test_damage_selector_handler_recognizes_each_creature_player_and_opponent():
    creatures = parse_effect_body("~ deals 2 damage to each creature")[0]
    assert creatures.params == {"amount": 2, "selector": "each_creature"}
    players = parse_effect_body("~ deals 1 damage to each player")[0]
    assert players.params == {"amount": 1, "selector": "each_player"}
    opponents = parse_effect_body("~ deals 3 damage to each opponent")[0]
    assert opponents.params == {"amount": 3, "selector": "each_opponent"}


def test_new_target_kinds_are_registered_and_each_x_stays_out_of_target_grammar():
    assert {
        "creature_you_control", "land_you_control", "graveyard_creature",
        "graveyard_card", "any_graveyard_creature", "any_graveyard_land",
        "opponent_graveyard_creature", "opponent_graveyard_card",
    } <= ALLOWED_TARGET_KINDS
    # "each opponent"/"each player" are mass selectors, not RULE 115 targets —
    # a generic destroy/exile/tap handler must not (wrongly) accept them as a
    # single chosen "player" target via the shared TARGET grammar.
    assert parse_effect_body("destroy each opponent") is None
    assert parse_effect_body("tap each player") is None


# ---------------------------------------------------------------------------
# ENGINE: bounce (RulesEngine.return_to_hand / ReturnToHandEffect)
# ---------------------------------------------------------------------------


def test_return_to_hand_moves_the_object_and_fires_leaves_battlefield():
    engine, state, p1, p2 = _rules()
    bear = _bf(state, _bear())
    before = len(state.event_log)

    engine.return_to_hand(bear)

    assert bear.zone == Zone.HAND and bear in p1.hand
    assert bear not in state.battlefield
    fired = [e for e in state.event_log[before:] if e.type == EventType.LEAVES_BATTLEFIELD]
    assert fired


def test_return_to_hand_token_ceases_to_exist_via_state_based_action():
    engine, state, p1, p2 = _rules()
    token = engine.create_token("p1", _bear("Squirrel", 1, 1))[0]

    engine.return_to_hand(token)
    assert token in p1.hand  # briefly "in hand"

    engine.check_state_based_actions()  # RULE 704.5d
    assert token not in p1.hand


def test_bounce_land_etb_trigger_offers_only_the_controllers_own_lands():
    engine, state, p1, p2 = _rules()
    my_other_land = _bf(state, _land("Swamp"))
    opp_land = _bf(state, _land("Forest"), controller="p2")
    bounce_card = Card(
        id="Test Karoo", name="Test Karoo", type_line="Land", is_land=True,
        oracle_text="When Test Karoo enters the battlefield, return a land you "
                    "control to its owner's hand.",
    )
    bounce = GameObject(bounce_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(bounce)
    _enter_battlefield(state, bounce, "p1")

    placed = engine.put_triggers_on_stack()
    assert placed == 1  # the queued trigger count — see put_triggers_on_stack
    assert not state.stack  # paused on the trigger_target choice, not placed yet
    choice = state.pending_choice
    assert choice["kind"] == "trigger_target"
    ids = {o["instance_id"] for o in choice["options"]}
    assert my_other_land.instance_id in ids
    assert opp_land.instance_id not in ids  # controller-restricted
    # RULE 109.5: "a land you control" is *not* "another land you control" —
    # a Karoo land really can bounce itself (Azorius Chancery returning
    # itself is a legal, occasionally-correct play). Only a target kind that
    # actually says "another" (`other_creature_you_control`, Giver of Runes)
    # excludes the source.
    assert bounce.instance_id in ids

    option = next(o for o in choice["options"] if o["instance_id"] == my_other_land.instance_id)
    engine.resolve_trigger_target_choice(option["id"])
    engine.resolve_top_of_stack()

    assert my_other_land in p1.hand
    assert my_other_land not in state.battlefield


# ---------------------------------------------------------------------------
# ENGINE: graveyard recursion (RulesEngine.return_from_graveyard)
# ---------------------------------------------------------------------------


def test_return_from_graveyard_to_battlefield_fires_etb_and_summoning_sickness():
    engine, state, p1, p2 = _rules()
    card = Card(
        id="Raised Zombie", name="Raised Zombie", type_line="Creature — Zombie",
        is_creature=True, power=2, toughness=2,
        oracle_text="When Raised Zombie enters the battlefield, draw a card.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.GRAVEYARD)
    p1.library.append(GameObject(_bear("Library Bear"), owner_id="p1", zone=Zone.LIBRARY))

    engine.return_from_graveyard(obj, "battlefield")

    assert obj in state.battlefield and obj.zone == Zone.BATTLEFIELD
    assert obj.summoning_sick is True
    placed = engine.put_triggers_on_stack()
    assert placed == 1  # its own ETB trigger fired — proves ENTERS_BATTLEFIELD fired
    assert len(state.stack) == 1  # untargeted+mandatory: placed immediately, no pause
    engine.resolve_top_of_stack()
    assert len(p1.hand) == 1  # "draw a card" resolved


def test_return_from_graveyard_to_hand_never_touches_the_battlefield():
    engine, state, p1, p2 = _rules()
    obj = GameObject(_bear("Regrown"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(obj, Zone.GRAVEYARD)

    engine.return_from_graveyard(obj, "hand")

    assert obj in p1.hand and obj.zone == Zone.HAND
    assert obj not in p1.graveyard
    assert obj not in state.battlefield


def test_reanimate_spell_end_to_end_targets_a_graveyard_creature():
    engine, state, p1, p2 = _rules()
    dead_obj = GameObject(_bear("Zombie Giant", power=5, toughness=5), owner_id="p1",
                          zone=Zone.GRAVEYARD)
    p1.add_to_zone(dead_obj, Zone.GRAVEYARD)

    reanimate = _spell(
        "Test Reanimate",
        "Return target creature card from your graveyard to the battlefield.",
        [EffectSpec("return_from_graveyard",
                     {"target_kind": "graveyard_creature", "destination": "battlefield"})],
        target={"kind": "graveyard_creature"},
    )
    p1.hand.append(reanimate)

    reqs = requirements_with_targets(state, "p1", reanimate)
    assert reqs[0]["kind"] == "graveyard_creature"
    assert {o["instance_id"] for o in reqs[0]["options"]} == {dead_obj.instance_id}

    engine.cast_spell(p1, reanimate, targets=[dead_obj])
    engine.resolve_top_of_stack()

    assert dead_obj in state.battlefield
    assert dead_obj.summoning_sick is True


def test_reanimate_under_your_control_steals_from_an_opponents_graveyard():
    # RULE 115/701.3: "put target creature card from a graveyard onto the
    # battlefield under your control" — p1 casts it, but the creature was
    # p2's; p1 takes control while p2 stays the owner (RULE 108.4/109.4).
    engine, state, p1, p2 = _rules()
    opp_dead = GameObject(_bear("Opponent's Bear", power=3, toughness=3), owner_id="p2",
                           zone=Zone.GRAVEYARD)
    p2.add_to_zone(opp_dead, Zone.GRAVEYARD)

    reanimate = _spell(
        "Test Reanimate", "Put target creature card from a graveyard onto the "
        "battlefield under your control.",
        [EffectSpec("return_from_graveyard", {
            "target_kind": "any_graveyard_creature", "destination": "battlefield",
            "under_your_control": True,
        })],
        target={"kind": "any_graveyard_creature"},
    )
    p1.hand.append(reanimate)

    reqs = requirements_with_targets(state, "p1", reanimate)
    assert {o["instance_id"] for o in reqs[0]["options"]} == {opp_dead.instance_id}

    engine.cast_spell(p1, reanimate, targets=[opp_dead])
    engine.resolve_top_of_stack()

    assert opp_dead in state.battlefield
    assert opp_dead.controller_id == "p1"  # stolen
    assert opp_dead.owner_id == "p2"  # still p2's card


def test_exile_target_graveyard_end_to_end_empties_only_the_targeted_players_graveyard():
    # Bojuka Bog-shaped: "exile target player's graveyard" — every card in
    # that one graveyard, the other player's untouched.
    engine, state, p1, p2 = _rules()
    p1.add_to_zone(GameObject(_bear("P1 Bear"), owner_id="p1", zone=Zone.GRAVEYARD), Zone.GRAVEYARD)
    p1.add_to_zone(GameObject(_bear("P1 Bear 2"), owner_id="p1", zone=Zone.GRAVEYARD), Zone.GRAVEYARD)
    p2_card = GameObject(_bear("P2 Bear"), owner_id="p2", zone=Zone.GRAVEYARD)
    p2.add_to_zone(p2_card, Zone.GRAVEYARD)

    exile_gy = _spell(
        "Test Bojuka Bog", "Exile target player's graveyard.",
        [EffectSpec("exile_target_graveyard", {"target_kind": "player"})],
        target={"kind": "player"},
    )
    p1.hand.append(exile_gy)

    engine.cast_spell(p1, exile_gy, targets=[p1])
    engine.resolve_top_of_stack()

    # Both bears (present before the cast) are exiled; the spell itself
    # lands in the graveyard afterward, as any resolved instant does.
    assert p1.graveyard == [exile_gy]
    assert p2_card in p2.graveyard  # untouched


def test_return_from_graveyard_transformed_via_registry():
    # RulesEngine.return_from_graveyard(transformed=True) — the Bruce
    # Banner-shaped "return this card to the battlefield transformed"
    # primitive, mirroring exile_return_transformed's flip-on-re-entry.
    engine, state, p1, p2 = _rules()
    card = Card(
        id="Flip Test", name="Flip Test", type_line="Legendary Creature — Human",
        is_creature=True, power=2, toughness=2,
        layout="transform",
        back_name="Flip Test Back", back_type_line="Legendary Creature — Monster",
        back_power=5, back_toughness=5,
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.GRAVEYARD)

    engine.return_from_graveyard(obj, "battlefield", transformed=True)

    assert obj in state.battlefield
    assert obj.transformed is True
    assert obj.name == "Flip Test Back"
    assert (obj.power, obj.toughness) == (5, 5)
    assert obj.summoning_sick is True


def test_return_from_graveyard_transformed_is_noop_without_a_back_face():
    engine, state, p1, p2 = _rules()
    obj = GameObject(_bear("Vanilla"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(obj, Zone.GRAVEYARD)

    engine.return_from_graveyard(obj, "battlefield", transformed=True)

    assert obj in state.battlefield
    assert obj.transformed is False


def test_return_from_graveyard_transformed_dies_trigger_end_to_end():
    # "When ~ dies, return it to the battlefield transformed under its
    # owner's control." (Bruce Banner-shaped) — a real dies trigger firing
    # the new self-only effect off real oracle text via the parser.
    engine, state, p1, p2 = _rules()
    card = Card(
        id="Bruce Test", name="Bruce Test", type_line="Legendary Creature — Human",
        is_creature=True, power=1, toughness=1,
        oracle_text="When Bruce Test dies, return it to the battlefield transformed "
                    "under its owner's control.",
        layout="transform",
        back_name="Bruce Test Back", back_type_line="Legendary Creature — Hulk",
        back_power=8, back_toughness=8,
    )
    obj = GameObject(card, owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)

    engine.put_into_graveyard(obj)
    placed = engine.put_triggers_on_stack()
    assert placed == 1
    engine.resolve_top_of_stack()

    assert obj in state.battlefield
    assert obj.transformed is True
    assert obj.name == "Bruce Test Back"
    assert (obj.power, obj.toughness) == (8, 8)


def test_lose_life_effect_selectors_hit_the_right_players():
    from mtg_analyzer.game.effects import GameContext, LoseLifeEffect

    engine, state, p1, p2 = _rules()
    ctx = GameContext(state, engine)
    source = GameObject(_bear("Drainer"), owner_id="p1", zone=Zone.BATTLEFIELD)

    LoseLifeEffect(amount=2, selector="each_opponent", source=source).apply(ctx)
    assert p1.life == 20 and p2.life == 18  # controller excluded

    LoseLifeEffect(amount=1, selector="each_player", source=source).apply(ctx)
    assert p1.life == 19 and p2.life == 17  # everyone included


# ---------------------------------------------------------------------------
# ENGINE: Deathrite Shaman — full oracle-text end-to-end (RULE 605.1a's
# excluded-from-mana-abilities shape, exercising the graveyard-targeting +
# "add mana of any colour" + lose_life primitives together)
# ---------------------------------------------------------------------------


def test_deathrite_shaman_end_to_end_from_real_oracle_text():
    deathrite_card = Card(
        id="Deathrite Shaman", name="Deathrite Shaman", type_line="Creature — Elf Shaman",
        is_creature=True, power=2, toughness=1,
        oracle_text=(
            "{T}: Exile target land card from a graveyard. Add one mana of any color.\n"
            "{B}, {T}: Exile target instant or sorcery card from a graveyard. "
            "Each opponent loses 2 life.\n"
            "{G}, {T}: Exile target creature card from a graveyard. You gain 2 life."
        ),
    )
    # Fully MODELED end to end: bind_from_catalogue must reach the oracle
    # parser (no hand-authored catalogue entry for this name).
    result = parse_oracle(deathrite_card)
    assert result.coverage == MODELED

    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)

    deathrite = _bf(state, deathrite_card)
    bind_from_catalogue(deathrite)
    assert len(deathrite.activated_abilities) == 3

    dead_land = GameObject(_land("Dead Forest"), owner_id="p2", zone=Zone.GRAVEYARD)
    p2.add_to_zone(dead_land, Zone.GRAVEYARD)
    dead_instant = GameObject(
        Card(id="Dead Bolt", name="Dead Bolt", type_line="Instant", is_instant=True),
        owner_id="p1", zone=Zone.GRAVEYARD,
    )
    p1.add_to_zone(dead_instant, Zone.GRAVEYARD)
    dead_creature = GameObject(_bear("Dead Bear"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(dead_creature, Zone.GRAVEYARD)

    # Ability 0: exile a land from any graveyard, add mana of a chosen colour.
    engine.activate_ability(p1, deathrite, ability_index=0, targets=[dead_land])
    engine.rules.resolve_top_of_stack()
    assert dead_land.zone == Zone.EXILE
    choice = state.pending_choice
    assert choice["kind"] == "add_mana_any_color"
    engine.rules.resolve_add_mana_any_color_choice("G")
    assert p1.mana_pool.pool["G"] == 1

    deathrite.tapped = False  # simulate untapping for the next ability in this test

    # Ability 1: exile an instant/sorcery from your own graveyard, drain opponents.
    p1.mana_pool.add("B", 1)
    engine.activate_ability(p1, deathrite, ability_index=1, targets=[dead_instant])
    engine.rules.resolve_top_of_stack()
    assert dead_instant.zone == Zone.EXILE
    assert p2.life == 18

    deathrite.tapped = False

    # Ability 2: exile a creature from your own graveyard, gain life.
    p1.mana_pool.add("G", 1)
    engine.activate_ability(p1, deathrite, ability_index=2, targets=[dead_creature])
    engine.rules.resolve_top_of_stack()
    assert dead_creature.zone == Zone.EXILE
    assert p1.life == 22


# ---------------------------------------------------------------------------
# ENGINE: search-to-hand (existing "search" effect, new recognition)
# ---------------------------------------------------------------------------


def test_unrestricted_tutor_moves_the_chosen_card_to_hand_and_shuffles():
    engine, state, p1, p2 = _rules()
    wanted = GameObject(_bear("Wanted"), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(wanted)
    p1.library.append(GameObject(_bear("Other"), owner_id="p1", zone=Zone.LIBRARY))

    tutor = _spell(
        "Test Tutor", "Search your library for a card, put that card into your "
        "hand, then shuffle.",
        [EffectSpec("search", {"criteria": {}, "destination": "hand"})],
    )
    p1.hand.append(tutor)
    engine.cast_spell(p1, tutor)
    engine.resolve_top_of_stack()

    choice = state.pending_choice
    assert choice["kind"] == "search"
    engine.resolve_search_choice(wanted.instance_id)

    assert wanted in p1.hand
    assert state.pending_choice is None
    assert any(e.type == EventType.SHUFFLE for e in state.event_log)


def test_basic_land_fetch_activated_ability_recognized_by_the_oracle_parser():
    engine, state, p1, p2 = _rules()
    card = Card(
        id="Trial Fetch", name="Trial Fetch", type_line="Land", is_land=True,
        oracle_text="{T}, Sacrifice Trial Fetch: Search your library for a basic "
                    "land card, put it onto the battlefield tapped, then shuffle.",
    )
    fetch = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(fetch)
    state.add_to_battlefield(fetch)
    p1.library.append(GameObject(Card(
        id="Plains", name="Plains", type_line="Basic Land — Plains", is_land=True,
    ), owner_id="p1", zone=Zone.LIBRARY))

    assert len(fetch.activated_abilities) == 1
    fetch.activated_abilities[0].apply(engine.context)  # cost payment isn't this test's concern

    choice = state.pending_choice
    assert choice["kind"] == "search"
    opt = choice["eligible"][0]
    engine.resolve_search_choice(opt["instance_id"])

    fetched = next(o for o in state.battlefield if o.name == "Plains")
    assert fetched.tapped is True


# ---------------------------------------------------------------------------
# ENGINE: Dark Ritual-shaped bare mana spell (AddManaEffect)
# ---------------------------------------------------------------------------


def test_dark_ritual_end_to_end_adds_black_mana_to_the_pool():
    engine, state, p1, p2 = _rules()
    ritual = _spell("Test Dark Ritual", "Add {B}{B}{B}.",
                     [EffectSpec("add_mana", {"colors": ["B", "B", "B"]})])
    p1.hand.append(ritual)

    engine.cast_spell(p1, ritual)
    engine.resolve_top_of_stack()

    assert p1.mana_pool.pool["B"] == 3


def test_add_mana_any_color_opens_an_interactive_choice():
    engine, state, p1, p2 = _rules()
    spell = _spell("Test Any Color Ritual", "Add 1 mana of any color.",
                    [EffectSpec("add_mana", {"colors": ["any"]})])
    p1.hand.append(spell)

    engine.cast_spell(p1, spell)
    engine.resolve_top_of_stack()

    # Resolving the effect pauses on a mandatory colour choice rather than
    # guessing — nothing is added to the pool yet.
    assert sum(p1.mana_pool.pool.values()) == 0
    choice = state.pending_choice
    assert choice is not None
    assert choice["kind"] == "add_mana_any_color"
    assert choice["player_id"] == "p1"
    assert {opt["id"] for opt in choice["options"]} == {"W", "U", "B", "R", "G"}

    engine.resolve_add_mana_any_color_choice("R")

    assert state.pending_choice is None
    assert p1.mana_pool.pool["R"] == 1


def test_add_mana_any_color_missing_answer_defaults_to_white():
    engine, state, p1, p2 = _rules()
    spell = _spell("Test Any Color Ritual", "Add 1 mana of any color.",
                    [EffectSpec("add_mana", {"colors": ["any"]})])
    p1.hand.append(spell)

    engine.cast_spell(p1, spell)
    engine.resolve_top_of_stack()
    engine.resolve_add_mana_any_color_choice(None)

    assert p1.mana_pool.pool["W"] == 1


# ---------------------------------------------------------------------------
# ENGINE: ETB self-attach (AttachEffect via an Equipment's own trigger)
# ---------------------------------------------------------------------------


def test_etb_self_attach_only_offers_the_controllers_own_creatures_and_attaches():
    engine, state, p1, p2 = _rules()
    my_bear = _bf(state, _bear("My Bear"))
    opp_bear = _bf(state, _bear("Opponent's Bear"), controller="p2")
    equip_card = Card(
        id="Test Sword", name="Test Sword", type_line="Artifact — Equipment",
        oracle_text="When Test Sword enters, attach it to target creature you "
                    "control.\nEquipped creature gets +1/+1.\nEquip {2}",
        keywords=["Equip"],
    )
    equip = GameObject(equip_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(equip)
    _enter_battlefield(state, equip, "p1")

    placed = engine.put_triggers_on_stack()
    assert placed == 1  # the queued trigger count — see put_triggers_on_stack
    assert not state.stack  # paused on the trigger_target choice, not placed yet
    choice = state.pending_choice
    assert choice["kind"] == "trigger_target"
    ids = {o["instance_id"] for o in choice["options"]}
    assert my_bear.instance_id in ids
    assert opp_bear.instance_id not in ids  # controller-restricted

    option = next(o for o in choice["options"] if o["instance_id"] == my_bear.instance_id)
    engine.resolve_trigger_target_choice(option["id"])
    engine.resolve_top_of_stack()

    assert equip.attached_to == my_bear.instance_id


# ---------------------------------------------------------------------------
# ENGINE: selector-based mass damage (DealDamageEffect.selector)
# ---------------------------------------------------------------------------


def test_mass_damage_each_creature_hits_every_creature_and_is_lethal_checked():
    engine, state, p1, p2 = _rules()
    weak = _bf(state, _bear("Weak", power=1, toughness=1))
    strong = _bf(state, _bear("Strong", power=4, toughness=4), controller="p2")
    engine.check_state_based_actions()  # stamp derived P/T

    blast = _spell("Test Blast", "~ deals 2 damage to each creature.",
                    [EffectSpec("damage", {"amount": 2, "selector": "each_creature"})])
    p1.hand.append(blast)
    engine.cast_spell(p1, blast)
    engine.resolve_top_of_stack()
    engine.check_state_based_actions()  # RULE 704.5g lethal damage

    assert weak.zone == Zone.GRAVEYARD  # 1 toughness — lethal
    assert strong.zone == Zone.BATTLEFIELD and strong.damage_marked == 2


def test_mass_damage_each_opponent_excludes_the_sources_own_controller():
    engine, state, p1, p2 = _rules()
    source = _bf(state, _bear("Source"))
    effect = EffectRegistry.create("damage", {"amount": 3, "selector": "each_opponent"})
    effect.source = source

    effect.apply(engine.context)

    assert p2.life == 17
    assert p1.life == 20  # not hit


def test_mass_damage_each_player_hits_everyone_including_the_caster():
    engine, state, p1, p2 = _rules()
    effect = EffectRegistry.create("damage", {"amount": 1, "selector": "each_player"})

    effect.apply(engine.context)

    assert p1.life == 19 and p2.life == 19
