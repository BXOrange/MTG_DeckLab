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
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.game.targeting import ALLOWED_TARGET_KINDS, requirements_with_targets
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


def test_return_from_graveyard_fails_closed_on_the_wrong_card_type():
    assert parse_effect_body(
        "return target artifact card from your graveyard to the battlefield"
    ) is None


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


def test_search_handler_fails_closed_on_a_mana_value_qualifier():
    assert parse_effect_body(
        "search your library for a card with mana value 2 or less, put that card "
        "into your hand, then shuffle"
    ) is None


def test_add_mana_handler_recognizes_a_pure_symbol_run_and_rejects_a_choice():
    ritual = parse_effect_body("add {b}{b}{b}")[0]
    assert ritual.type == "add_mana"
    assert ritual.params == {"colors": ["B", "B", "B"]}
    # "add 1 mana of any color" is a player choice, not modeled — fail-closed.
    assert parse_effect_body("add 1 mana of any color") is None


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
    assert {"creature_you_control", "land_you_control", "graveyard_creature"} <= ALLOWED_TARGET_KINDS
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
    assert bounce.instance_id not in ids  # can't return itself (targeting.py convention)

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
