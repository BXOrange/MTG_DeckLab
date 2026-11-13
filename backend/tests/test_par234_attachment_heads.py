"""PAR-234 -- attachment-scoped trigger heads.

* Enchanted-player Curses: "whenever enchanted player draws a card", "when enchanted player loses the game", "whenever a
  <permanent> enchanted player controls enters / dies" (RULE 303.4m: "enchanted [player]" is whatever the Aura is attached to).
* "when enchanted <land | artifact | land type> is put into a graveyard" (RULE 700.4 / 603.10a: the host's `DIES`, seen while
  the Aura is still attached).
* "whenever an Aura [you control] becomes attached to ~ / a creature you control" (RULE 701.3b).
* Equipped / enchanted creature variants: "becomes blocked by a creature" (RULE 509.3d), "deals combat damage to defending
  player", "transforms", and the trailing "that's enchanted [or equipped]" noun-phrase tail.

Parse tests pin the grammar and what it refuses; execute tests run real cards on a real `GameEngine`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.combat import matches_object_filter
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.characteristic_phrase import parse_object_phrase
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head

from tests.test_par119_object_trigger_head import _named

# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


def test_enchanted_player_actor_scopes_to_the_aura_host():
    head = parse_object_trigger_head("enchanted player draws a card")
    assert head is not None and head.event == "DRAW"
    assert head.condition == {"subject": "player", "scope": "enchanted"}
    opponent = parse_object_trigger_head("enchanted opponent draws a card")
    assert opponent is not None and opponent.condition == head.condition


def test_enchanted_player_loses_the_game():
    head = parse_object_trigger_head("enchanted player loses the game")
    assert head is not None and head.event == "PLAYER_LOST"


@pytest.mark.parametrize(
    "cond, event, extra",
    [
        ("a land enchanted player controls enters", "ENTERS_BATTLEFIELD", {"card_type": "land"}),
        ("a creature enchanted player controls enters", "ENTERS_BATTLEFIELD", {"card_type": "creature"}),
        ("a nontoken creature enchanted player controls dies", "DIES", {"card_type": "creature", "nontoken": True}),
    ],
)
def test_object_enchanted_player_controls(cond, event, extra):
    head = parse_object_trigger_head(cond)
    assert head is not None and head.event == event
    assert head.condition["controller"] == "enchanted"
    for key, value in extra.items():
        assert head.condition.get("filter", {}).get(key, head.condition.get(key)) == value


@pytest.mark.parametrize(
    "cond",
    [
        "a land enchanted opponent controls enters",  # only "enchanted player" is printed
        "a land enchanted player owns enters",
        "enchanted players draws a card",
        "enchanted player draws two cards",
    ],
)
def test_near_misses_are_not_claimed(cond):
    head = parse_object_trigger_head(cond)
    assert head is None or head.condition.get("controller") != "enchanted"
    if head is not None:
        assert head.condition != {"subject": "player", "scope": "enchanted"}


@pytest.mark.parametrize("land", ["forest", "island", "swamp", "mountain", "plains", "land", "artifact"])
def test_enchanted_permanent_graveyard_head(land):
    head = parse_object_trigger_head(f"enchanted {land} is put into a graveyard")
    assert head is not None and head.event == "DIES"
    assert head.condition == {"subject": "attached_permanent"}


@pytest.mark.parametrize(
    "cond",
    ["enchanted creature is put into a graveyard from your library", "enchanted forest is put into a library",
     "enchanted forest is put into exile"],
)
def test_graveyard_head_refuses_other_zones(cond):
    head = parse_object_trigger_head(cond)
    assert head is None or head.event != "DIES" or head.condition != {"subject": "attached_permanent"}


def test_aura_attached_heads():
    own = parse_object_trigger_head("an aura becomes attached to ~")
    assert own is not None and own.event == "ATTACHED_TO_CREATURE"
    assert own.trigger == {"attach_host": {"self": True}} and own.condition["controller"] == "any"
    yours = parse_object_trigger_head("an aura you control becomes attached to a creature you control")
    assert yours is not None and yours.trigger == {"attach_host": {"controller": "you"}}
    assert yours.condition["controller"] == "you"
    assert parse_object_trigger_head("an aura becomes attached to a creature an opponent controls") is None


def test_that_is_enchanted_tail():
    assert parse_object_phrase("creature you control that's enchanted") == (
        {"card_type": "creature", "enchanted": True}, "you")
    assert parse_object_phrase("creature you control that's enchanted or equipped") == (
        {"card_type": "creature", "any_of": [{"enchanted": True}, {"equipped": True}]}, "you")
    assert parse_object_phrase("creature you control that's frobnicated") is None


def test_equipped_blocked_by_head_reads_the_per_blocker_event():
    head = parse_object_trigger_head("equipped creature becomes blocked by a creature")
    assert head is not None and head.event == "BLOCKS"
    assert head.condition["filter"] == {"card_type": "creature", "blocking_attached_host": True}


def test_other_attached_heads():
    transforms = parse_object_trigger_head("equipped creature transforms")
    assert transforms is not None and transforms.event == "TRANSFORMED"
    assert transforms.condition == {"subject": "attached_permanent"}
    damage = parse_object_trigger_head("enchanted creature deals combat damage to defending player")
    assert damage is not None and damage.event == "DAMAGE"
    assert damage.trigger["filter"] == {"combat": True, "is_player": True}


@pytest.mark.parametrize(
    "name",
    [
        "Curse of Fool's Wisdom", "Psychic Possession", "Curse of Vengeance", "Curse of Clinging Webs",
        "Curse of the Restless Dead", "Trespasser's Curse", "Genju of the Cedars", "Genju of the Falls",
        "Genju of the Fens", "Genju of the Realm", "Genju of the Spires", "Tezzeret's Touch", "Viridian Harvest",
        "Bramble Elemental", "Siona, Captain of the Pyleas", "Beastmaster's Magemark", "Dogmeat, Ever Loyal",
        "Reyav, Master Smith", "Infiltration Lens", "Latulla's Orders", "Electryte", "Neglected Heirloom // Ashmouth Blade",
    ],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Execution (three players: only the enchanted one counts)
# ---------------------------------------------------------------------------


def _game():
    players = [Player(id=f"p{i}", name=f"P{i}", life=20) for i in (1, 2, 3)]
    state = GameState(players=players)
    engine = GameEngine(state)
    for player in players:
        for i in range(8):
            player.library.append(GameObject(Card(id=f"{player.id}L{i}", name=f"L{i}", type_line="Land"),
                                             owner_id=player.id, zone=Zone.LIBRARY))
    return engine, state


def _from_card(state, name, owner="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(_named(name), owner_id=owner, zone=zone)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    return obj


def _custom(state, oracle, name="Thing", types="Enchantment — Aura", owner="p1", **kw):
    card = Card(id=name, name=name, type_line=types, oracle_text=oracle,
                is_creature="Creature" in types, power=2 if "Creature" in types else None,
                toughness=2 if "Creature" in types else None, **kw)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _enter(engine, state, obj):
    """Fire the entry event `add_to_battlefield` alone does not (RULE 603.6a)."""
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id, card_id=obj.card.id, object=obj.name,
        instance_id=obj.instance_id, object_types=sorted(obj.type_words),
    ))
    engine.resolve_until_stable()


def _settle(engine, state):
    """Resolve the stack, accepting every optional ("you may") ability."""
    engine.resolve_until_stable()
    for _ in range(10):
        if not state.pending_choice:
            return
        engine.rules.resolve_choice("do")
        engine.resolve_until_stable()


def _creature(state, name="Bear", owner="p1", types="Creature — Bear"):
    card = Card(id=name + owner, name=name, type_line=types, is_creature=True, power=2, toughness=2)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    state.add_to_battlefield(obj)
    obj.summoning_sick = False
    return obj


def test_curse_of_fool_wisdom_only_triggers_for_the_enchanted_player():
    engine, state = _game()
    curse = _from_card(state, "Curse of Fool's Wisdom")
    curse.attached_to = "p2"
    engine.rules.draw(state.player_by_id("p3"), 1)
    engine.resolve_until_stable()
    assert (state.player_by_id("p2").life, state.player_by_id("p1").life) == (20, 20)
    engine.rules.draw(state.player_by_id("p2"), 1)
    engine.resolve_until_stable()
    assert (state.player_by_id("p2").life, state.player_by_id("p1").life) == (18, 22)


def test_curse_follows_its_live_host_when_reattached():
    engine, state = _game()
    curse = _from_card(state, "Curse of Fool's Wisdom")
    curse.attached_to = "p2"
    curse.attached_to = "p3"
    engine.rules.draw(state.player_by_id("p2"), 1)
    engine.resolve_until_stable()
    assert state.player_by_id("p2").life == 20
    engine.rules.draw(state.player_by_id("p3"), 1)
    engine.resolve_until_stable()
    assert state.player_by_id("p3").life == 18


def test_psychic_possession_draws_only_for_enchanted_opponent():
    engine, state = _game()
    aura = _from_card(state, "Psychic Possession")
    aura.attached_to = "p3"
    p1 = state.player_by_id("p1")
    before = len(p1.hand)
    engine.rules.draw(state.player_by_id("p2"), 1)
    _settle(engine, state)
    assert len(p1.hand) == before
    engine.rules.draw(state.player_by_id("p3"), 1)
    _settle(engine, state)
    assert len(p1.hand) == before + 1  # the optional draw


def test_trespassers_curse_counts_only_the_enchanted_players_creatures():
    engine, state = _game()
    curse = _from_card(state, "Trespasser's Curse")
    curse.attached_to = "p2"
    _enter(engine, state, _creature(state, "Theirs", owner="p3"))
    assert (state.player_by_id("p3").life, state.player_by_id("p1").life) == (20, 20)
    _enter(engine, state, _creature(state, "Hers", owner="p2"))
    assert (state.player_by_id("p2").life, state.player_by_id("p1").life) == (19, 21)


def test_curse_of_the_restless_dead_counts_lands_of_the_enchanted_player():
    engine, state = _game()
    curse = _from_card(state, "Curse of the Restless Dead")
    curse.attached_to = "p2"

    def land(owner):
        obj = GameObject(Card(id="land" + owner, name="Forest", type_line="Basic Land — Forest", is_land=True),
                         owner_id=owner, zone=Zone.BATTLEFIELD)
        obj.controller_id = owner
        state.add_to_battlefield(obj)
        _enter(engine, state, obj)

    tokens = lambda: [o for o in state.battlefield if "Zombie" in (o.card.type_line or "")]
    land("p3")
    assert not tokens()
    land("p2")
    assert len(tokens()) == 1 and tokens()[0].controller_id == "p1"  # the Curse's controller gets the Zombie


def test_curse_of_clinging_webs_exiles_only_the_enchanted_players_nontoken_creature():
    engine, state = _game()
    curse = _from_card(state, "Curse of Clinging Webs")
    curse.attached_to = "p2"
    other = _creature(state, "Other", owner="p3")
    engine.rules.destroy(other)
    engine.resolve_until_stable()
    assert other.zone == Zone.GRAVEYARD
    assert not [o for o in state.battlefield if "Spider" in (o.card.type_line or "")]
    mine = _creature(state, "Mine", owner="p2")
    engine.rules.destroy(mine)
    engine.resolve_until_stable()
    assert mine.zone == Zone.EXILE
    spiders = [o for o in state.battlefield if "Spider" in (o.card.type_line or "")]
    assert len(spiders) == 1 and spiders[0].controller_id == "p1"


def test_curse_of_vengeance_pays_off_when_the_enchanted_player_loses():
    engine, state = _game()
    curse = _from_card(state, "Curse of Vengeance")
    curse.attached_to = "p2"
    curse.counters["spite"] = 3
    p1 = state.player_by_id("p1")
    before_hand, before_life = len(p1.hand), p1.life
    engine.rules.concede(state.player_by_id("p2"))
    _settle(engine, state)
    assert p1.life == before_life + 3 and len(p1.hand) == before_hand + 3


def test_curse_of_vengeance_ignores_another_player_losing():
    engine, state = _game()
    curse = _from_card(state, "Curse of Vengeance")
    curse.attached_to = "p2"
    curse.counters["spite"] = 3
    p1 = state.player_by_id("p1")
    engine.rules.concede(state.player_by_id("p3"))
    _settle(engine, state)
    assert (len(p1.hand), p1.life) == (0, 20)


@pytest.mark.parametrize(
    "text, host_types, expected_zone",
    [
        ("When enchanted land is put into a graveyard, you gain 3 life.", "Land — Forest", Zone.GRAVEYARD),
    ],
)
def test_enchanted_land_put_into_a_graveyard_triggers_once(text, host_types, expected_zone):
    engine, state = _game()
    host = GameObject(Card(id="host", name="Host", type_line=host_types, is_land=True), owner_id="p2",
                      zone=Zone.BATTLEFIELD)
    host.controller_id = "p2"
    state.add_to_battlefield(host)
    aura = _custom(state, "Enchant land\n" + text, name="Grace")
    aura.attached_to = host.instance_id
    other = GameObject(Card(id="o", name="Other", type_line="Land — Forest", is_land=True), owner_id="p2",
                       zone=Zone.BATTLEFIELD)
    other.controller_id = "p2"
    state.add_to_battlefield(other)
    life = state.player_by_id("p1").life
    engine.rules.destroy(other)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == life  # not the enchanted land
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    assert host.zone == expected_zone and state.player_by_id("p1").life == life + 3


def test_genju_returns_from_the_graveyard_when_its_forest_dies():
    engine, state = _game()
    forest = GameObject(Card(id="f", name="Forest", type_line="Basic Land — Forest", is_land=True), owner_id="p1",
                        zone=Zone.BATTLEFIELD)
    forest.controller_id = "p1"
    state.add_to_battlefield(forest)
    genju = _from_card(state, "Genju of the Cedars")
    genju.attached_to = forest.instance_id
    engine.rules.destroy(forest)
    engine.rules.check_state_based_actions()
    assert genju.zone == Zone.GRAVEYARD  # the Aura falls off after the host's departure (RULE 704.5m)
    engine.rules.put_triggers_on_stack()
    _settle(engine, state)
    assert genju.zone == Zone.HAND  # "you may return this card from your graveyard to your hand"


def test_genju_ignores_a_land_that_is_not_its_host():
    engine, state = _game()
    forest = GameObject(Card(id="f", name="Forest", type_line="Basic Land — Forest", is_land=True), owner_id="p1",
                        zone=Zone.BATTLEFIELD)
    forest.controller_id = "p1"
    state.add_to_battlefield(forest)
    other = GameObject(Card(id="g", name="Forest", type_line="Basic Land — Forest", is_land=True), owner_id="p1",
                       zone=Zone.BATTLEFIELD)
    other.controller_id = "p1"
    state.add_to_battlefield(other)
    genju = _from_card(state, "Genju of the Cedars")
    genju.attached_to = forest.instance_id
    engine.rules.destroy(other)
    _settle(engine, state)
    assert genju.zone == Zone.BATTLEFIELD


def test_tezzerets_touch_returns_the_artifact_to_its_owners_hand():
    engine, state = _game()
    artifact = GameObject(Card(id="a", name="Rock", type_line="Artifact"), owner_id="p2", zone=Zone.BATTLEFIELD)
    artifact.controller_id = "p2"
    state.add_to_battlefield(artifact)
    touch = _from_card(state, "Tezzeret's Touch")
    touch.attached_to = artifact.instance_id
    engine.rules.destroy(artifact)
    engine.resolve_until_stable()
    assert artifact.zone == Zone.HAND and artifact.owner_id == "p2"


def test_viridian_harvest_gains_life_when_both_die_together():
    engine, state = _game()
    artifact = GameObject(Card(id="a", name="Rock", type_line="Artifact"), owner_id="p2", zone=Zone.BATTLEFIELD)
    artifact.controller_id = "p2"
    state.add_to_battlefield(artifact)
    harvest = _from_card(state, "Viridian Harvest")
    harvest.attached_to = artifact.instance_id
    life = state.player_by_id("p1").life
    engine.rules.destroy(artifact)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == life + 6


def test_aura_attached_to_self_triggers_for_any_aura_only_on_the_source():
    engine, state = _game()
    elemental = _from_card(state, "Bramble Elemental")
    other = _creature(state, "Other")
    aura = _custom(state, "Enchant creature", name="Plain Aura")
    count = lambda: len([o for o in state.battlefield if "Saproling" in (o.card.type_line or "")])
    engine.rules.attach_to_target(aura, other)
    engine.resolve_until_stable()
    assert count() == 0
    engine.rules.attach_to_target(aura, elemental)
    engine.resolve_until_stable()
    assert count() == 2
    engine.rules.attach_to_target(aura, elemental)  # already attached: no event (RULE 701.3b)
    engine.resolve_until_stable()
    assert count() == 2


def test_siona_triggers_only_for_my_auras_on_my_creatures():
    engine, state = _game()
    siona = _from_card(state, "Siona, Captain of the Pyleas")
    mine = _creature(state, "Mine")
    theirs = _creature(state, "Theirs", owner="p2")
    their_aura = _custom(state, "Enchant creature", name="Their Aura", owner="p2")
    my_aura = _custom(state, "Enchant creature", name="My Aura")
    humans = lambda: len([o for o in state.battlefield if o.is_token and "Human" in (o.card.type_line or "")])
    engine.rules.attach_to_target(their_aura, mine, check_control=False)
    engine.resolve_until_stable()
    assert humans() == 0  # not an Aura I control
    engine.rules.attach_to_target(my_aura, theirs, check_control=False)
    engine.resolve_until_stable()
    assert humans() == 0  # not a creature I control
    engine.rules.attach_to_target(my_aura, mine)
    engine.resolve_until_stable()
    assert humans() == 1
    assert siona.zone == Zone.BATTLEFIELD


def test_enchanted_or_equipped_attacker_filter():
    engine, state = _game()
    plain = _creature(state, "Plain")
    dressed = _creature(state, "Dressed")
    equipment = _custom(state, "Equip {1}", name="Sword", types="Artifact — Equipment")
    equipment.attached_to = dressed.instance_id
    filt, _ = parse_object_phrase("creature you control that's enchanted or equipped")
    assert matches_object_filter(dressed, filt, reference=plain, state=state)
    assert not matches_object_filter(plain, filt, reference=plain, state=state)


def test_equipped_creature_blocked_trigger_fires_per_blocker():
    engine, state = _game()
    host = _creature(state, "Host")
    stranger = _creature(state, "Stranger")
    lens = _from_card(state, "Infiltration Lens")
    lens.attached_to = host.instance_id
    blockers = [_creature(state, f"B{i}", owner="p2") for i in range(2)]
    p1 = state.player_by_id("p1")
    before = len(p1.hand)
    state.current_step = "declare_blockers"
    host.attacking = stranger.attacking = True
    host.combat_defender = stranger.combat_defender = {"kind": "player", "id": "p2"}
    engine.declare_blockers(state.player_by_id("p2"), [(blockers[0], host), (blockers[1], host)])
    _settle(engine, state)
    assert len(p1.hand) == before + 4  # two blockers, two triggers, two cards each (RULE 509.3d)
    extra = _creature(state, "B2", owner="p2")
    engine.declare_blockers(state.player_by_id("p2"), [(extra, stranger)])
    _settle(engine, state)
    assert len(p1.hand) == before + 4  # a blocker of some other attacker does not count


def test_transform_of_the_equipped_creature_transforms_the_equipment():
    engine, state = _game()
    host = _creature(state, "Host")
    heirloom = _from_card(state, "Neglected Heirloom // Ashmouth Blade")
    heirloom.attached_to = host.instance_id
    other = _creature(state, "Other")
    state.fire_event(GameEvent(EventType.TRANSFORMED, instance_id=other.instance_id, controller_id="p1",
                               object="Other", face_name="Other"))
    engine.resolve_until_stable()
    assert not heirloom.transformed
    state.fire_event(GameEvent(EventType.TRANSFORMED, instance_id=host.instance_id, controller_id="p1",
                               object="Host", face_name="Host"))
    engine.resolve_until_stable()
    assert heirloom.transformed


def test_latullas_orders_destroys_an_artifact_of_the_damaged_player_only():
    engine, state = _game()
    host = _creature(state, "Host")
    orders = _from_card(state, "Latulla's Orders")
    orders.attached_to = host.instance_id
    rocks = {}
    for owner in ("p2", "p3"):
        rock = GameObject(Card(id="rock" + owner, name="Rock", type_line="Artifact"), owner_id=owner,
                          zone=Zone.BATTLEFIELD)
        rock.controller_id = owner
        state.add_to_battlefield(rock)
        rocks[owner] = rock
    stranger = _creature(state, "Stranger")
    engine.rules.deal_damage(state.player_by_id("p3"), 2, source=stranger, combat=True)
    engine.rules.deal_damage(state.player_by_id("p3"), 2, source=host, combat=False)
    engine.resolve_until_stable()
    assert state.pending_choice is None  # neither an unenchanted creature nor noncombat damage triggers it
    engine.rules.deal_damage(state.player_by_id("p2"), 2, source=host, combat=True)
    engine.resolve_until_stable()
    options = {o["id"] for o in state.pending_choice["options"]}
    assert str(rocks["p2"].instance_id) in options and str(rocks["p3"].instance_id) not in options  # "that player"
    engine.rules.resolve_choice(str(rocks["p2"].instance_id))
    engine.resolve_until_stable()
    assert rocks["p2"].zone == Zone.GRAVEYARD and rocks["p3"].zone == Zone.BATTLEFIELD


def test_reyav_triggers_for_an_equipped_attacker_only():
    engine, state = _game()
    _from_card(state, "Reyav, Master Smith")
    plain = _creature(state, "Plain")
    dressed = _creature(state, "Dressed")
    sword = _custom(state, "Equip {1}", name="Sword", types="Artifact — Equipment")
    sword.attached_to = dressed.instance_id
    state.current_step = "declare_attackers"
    p1 = state.player_by_id("p1")
    engine.declare_attackers(p1, [{"attacker": plain, "defender": state.player_by_id("p2")},
                                  {"attacker": dressed, "defender": state.player_by_id("p2")}])
    assert len(engine.rules.pending_triggers) == 1  # only the equipped attacker
    _settle(engine, state)
    assert "double_strike" in dressed.temp_keywords  # "that creature gains double strike until end of turn"
    assert "double_strike" not in plain.temp_keywords


def test_beastmasters_magemark_pumps_per_blocker_of_an_enchanted_creature():
    engine, state = _game()
    magemark = _from_card(state, "Beastmaster's Magemark")
    enchanted = _creature(state, "Enchanted")
    plain = _creature(state, "Plain")
    magemark.attached_to = enchanted.instance_id
    blockers = [_creature(state, f"B{i}", owner="p2") for i in range(3)]
    state.current_step = "declare_blockers"
    for attacker in (enchanted, plain):
        attacker.attacking = True
        attacker.combat_defender = {"kind": "player", "id": "p2"}
    engine.declare_blockers(state.player_by_id("p2"),
                            [(blockers[0], enchanted), (blockers[1], enchanted), (blockers[2], plain)])
    _settle(engine, state)
    engine.recompute_continuous_effects()
    # Its own anthem (+1/+1 to enchanted creatures) plus +1/+1 for each of the two blockers.
    assert (enchanted.power, enchanted.toughness) == (2 + 1 + 2, 2 + 1 + 2)
    assert (plain.power, plain.toughness) == (2, 2)
