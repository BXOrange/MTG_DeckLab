"""PAR-233 -- trigger-subject filters "another ..." / "other than ~".

* RULE 109.1 / 603.2: "another" and "other than ~" exclude the ability's own source; "~ or another X" includes it.
* Complex subject phrases: a union of whole noun phrases ("nontoken artifact creature or Vehicle"), a trailing
  "with" qualifier that binds to the last alternative ("legendary creature or creature with mana value 1"),
  "named ~", "your team controls" (RULE 810: no teams in this engine, so it is "you control"), "owned by another
  player" (RULE 108.3 / 400.3: the owner, never the controller).
* Cast heads: "another spell that has <keyword>" and "a spell with N or more card types" (RULE 205.2).
* "put a +1/+1 counter on another creature", "a source you control other than ~ deals damage to an opponent",
  "a creature other than ~ is exiled from the battlefield", "~ or another Spirit you control becomes the target
  of a spell".
* RULE 603.8 state trigger "you control no permanents other than ~ and have no cards in hand".

Parse tests pin the grammar and what it refuses; execute tests run real cards on a real `GameEngine`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.combat import matches_object_filter
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.characteristic_phrase import parse_object_phrase, parse_qualifier
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from mtg_analyzer.parser.oracle.catalogue.spell_phrase import parse_spell_phrase

from tests.test_par119_object_trigger_head import _named

# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


def test_union_of_whole_noun_phrases_distributes_nontoken():
    assert parse_object_phrase("nontoken artifact creature or vehicle you control") == (
        {"nontoken": True, "any_of": [{"card_type_all": ["artifact", "creature"]}, {"subtype": "vehicle"}]}, "you")


def test_with_qualifier_binds_to_the_last_alternative():
    # RULE 202.3: only "creature with mana value 1" is restricted; any legendary creature qualifies.
    assert parse_object_phrase("legendary creature or creature with mana value 1") == (
        {"any_of": [{"legendary": True, "card_type": "creature"},
                    {"card_type": "creature", "exact_mana_value": 1}]}, None)


def test_plural_heads_do_not_use_the_union():
    # "artifact or rogue creatures" shares its plural noun in a way the union cannot tell apart (PAR-119's pinned case).
    assert parse_object_phrase("artifact or rogue creatures", plural=True) is None


def test_union_targets_that_may_include_the_source_stay_unclaimed_on_a_source_excluding_kind():
    # Nyx Herald's "target enchanted creature or enchantment creature you control" can name the Herald itself, but the
    # `permanent_you_control` frame excludes the source: unclaimed until a source-inclusive kind exists.
    assert parse_oracle(_named("Nyx Herald")).modeled is False


def test_permanent_you_control_frame_reads_the_quality_filter():
    from mtg_analyzer.game.targeting import TARGET_FRAMES
    assert TARGET_FRAMES["permanent_you_control"].apply_creature_filter
    assert TARGET_FRAMES["permanent_you_dont_control"].apply_creature_filter


@pytest.mark.parametrize(
    "phrase",
    [
        "attacking or blocking creature with power 3 or less",  # one noun, two adjectives: not a union
        "attacking or blocking creature",
        "frobnicated creature or vehicle",
        "creature or frobnicated vehicle",
    ],
)
def test_union_needs_a_noun_on_every_side(phrase):
    assert parse_object_phrase(phrase) is None


def test_team_named_owner_and_keyword_tails():
    assert parse_object_phrase("warrior your team controls") == ({"subtype": "warrior"}, "you")
    assert parse_object_phrase("creature you control named ~") == (
        {"card_type": "creature", "name_reference": {"kind": "source"}}, "you")
    assert parse_object_phrase("creature you control named some other card") is None
    assert parse_object_phrase("permanent owned by another player") == ({"not_owned_by_you": True}, None)
    assert parse_object_phrase("creature you control with flash or haste") == (
        {"card_type": "creature", "keyword_any": ["flash", "haste"]}, "you")
    assert parse_object_phrase("creature you control with toxic") == (
        {"card_type": "creature", "keyword": "toxic"}, "you")
    assert parse_qualifier("flash or frobnicate") is None


@pytest.mark.parametrize(
    "cond, event, subject, other",
    [
        ("another nontoken artifact creature or vehicle you control enters", "ENTERS_BATTLEFIELD", "group", True),
        ("another warrior your team controls enters", "ENTERS_BATTLEFIELD", "group", True),
        ("~ or another warrior your team controls enters", "ENTERS_BATTLEFIELD", "self_or_group", True),
        ("another creature you control named ~ enters", "ENTERS_BATTLEFIELD", "group", True),
        ("another legendary creature or creature with mana value 1 enters the battlefield under your control",
         "ENTERS_BATTLEFIELD", "group", True),
        ("~ or another spirit you control becomes the target of a spell", "BECOMES_TARGET", "self_or_group", True),
        ("~ or another creature you control with flash or haste dies", "DIES", "self_or_group", True),
        ("another creature you control with toxic attacks", "ATTACKS", "group", True),
        ("a permanent other than ~ dies", "DIES", "group", True),
        ("a creature other than ~ is exiled from the battlefield", "LEAVES_BATTLEFIELD", "group", True),
        ("a permanent owned by another player dies", "DIES", "group", False),
        ("a source you control other than ~ deals damage to an opponent", "DAMAGE", "group", True),
        ("you put a +1/+1 counter on another creature", "COUNTER", "group", True),
    ],
)
def test_heads_parse(cond, event, subject, other):
    head = parse_object_trigger_head(cond)
    assert head is not None
    assert head.event == event
    assert head.condition["subject"] == subject
    assert head.condition["other"] is other


def test_exiled_head_reads_the_exile_destination():
    head = parse_object_trigger_head("a creature other than ~ is exiled from the battlefield")
    assert head.trigger == {"to_zone": "exile"}


def test_source_other_than_self_scopes_controller_and_recipient():
    head = parse_object_trigger_head("a source you control other than ~ deals damage to an opponent")
    assert head.condition["controller"] == "you" and head.condition["recipient_is_opponent"] is True


@pytest.mark.parametrize(
    "cond",
    [
        "another nontoken artifact creature or frobnicate you control enters",
        "a creature other than enters",  # "other than" with no operand
        "a creature other than target creature dies",
        "you put a +1/+1 counter on another",
        "a permanent owned by another dies",
        "another creature you control named some other card enters",
    ],
)
def test_near_misses_are_not_claimed(cond):
    assert parse_object_trigger_head(cond) is None


def test_spell_phrase_keyword_and_card_type_count():
    flash = parse_spell_phrase("another spell that has flash")
    assert flash == {"spell_filter": {"keyword": "flash"}}
    assert parse_spell_phrase("another spell that has convoke") == {"spell_filter": {"keyword": "convoke"}}
    assert parse_spell_phrase("another spell with 2 or more card types") == {"spell_filter": {"min_card_types": 2}}
    assert parse_spell_phrase("another spell that has frobnicate") is None


# ---------------------------------------------------------------------------
# Real cards
# ---------------------------------------------------------------------------

#: The cards the ticket's heads unlock directly.
PRIMARY = [
    "Canoptek Spyder", "Captain Marvel, Shooting Star", "Decorated Champion", "General Kudro of Drannith",
    "Gladewalker Ritualist", "Isamaru and Yoshimaru", "Kasla, the Broken Halo", "Knight of Wundagore",
    "Slaughter Singer", "Slitherwisp", "Talon of Pain", "The Cheese Stands Alone", "Thrasher Brute",
    "Kothophed, Soul Hoarder", "Yomiji, Who Bars the Way",
]
#: Claimed as a side effect of the shared grammar (a target phrase, a keyword tail, a counter head ...).
SIDE_EFFECTS = [
    "Ant-Man, Colony Commander", "Banishing Slash", "Barren Glory", "Bumi Bash", "Feast of Dreams",
    "Guerrilla Gorilla", "Iron Spider, Stark Upgrade", "Isolate", "Jedit Ojanen of Efrava", "Kestia, the Cultivator",
    "Plague Nurse", "Purge", "Radiant Purge", "Radiant Strike", "Ray of Ruin",
    "Saint Traft and Rem Karolus", "Sonic the Hedgehog",
]


@pytest.mark.parametrize("name", PRIMARY + SIDE_EFFECTS)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


@pytest.mark.parametrize(
    "name",
    [
        "King of the Oathbreakers",  # head parses; "it phases out" is a separate gap
        "Visitor from Planet Q",  # head parses; the flash-cards-are-instants static is a separate gap
        "Shadow the Hedgehog",  # head parses; the split-second static is a separate gap
        "Last Laugh",  # head parses; the no-creatures state trigger is a separate gap
        "Puncturing Light", "Searing Light", "Sonar Strike", "Skyshooter",  # "attacking or blocking creature with ..."
    ],
)
def test_cards_with_another_gap_stay_unmodeled(name):
    assert parse_oracle(_named(name)).modeled is False


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _game():
    players = [Player(id=f"p{i}", name=f"P{i}", life=20) for i in (1, 2)]
    state = GameState(players=players)
    engine = GameEngine(state)
    for player in players:
        for i in range(10):
            player.library.append(GameObject(Card(id=f"{player.id}L{i}", name=f"L{i}", type_line="Land"),
                                             owner_id=player.id, zone=Zone.LIBRARY))
    return engine, state


def _real(state, name, owner="p1", controller=None):
    obj = GameObject(_named(name), owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller or owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _custom(state, name, type_line, oracle="", owner="p1", controller=None, power=2, toughness=2, **kw):
    is_creature = "Creature" in type_line
    card = Card(id=name + owner, name=name, type_line=type_line, oracle_text=oracle, is_creature=is_creature,
                is_legendary="Legendary" in type_line, is_land="Land" in type_line,
                power=power if is_creature else None, toughness=toughness if is_creature else None, **kw)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller or owner
    obj.summoning_sick = False
    if oracle:
        bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _enter(engine, state, obj, token=False):
    """Fire the entry event `add_to_battlefield` alone does not (RULE 603.6a)."""
    obj.is_token = token
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id, card_id=obj.card.id, object=obj.name,
        instance_id=obj.instance_id, object_types=sorted(obj.type_words), is_token=token,
    ))
    _settle(engine, state)


def _settle(engine, state):
    """Resolve the stack, aiming each target prompt at its first option and accepting every "you may"."""
    engine.resolve_until_stable()
    for _ in range(10):
        choice = state.pending_choice
        if not choice:
            return
        options = choice.get("options") or []
        if choice.get("kind") == "trigger_target" and options:
            engine.resolve_pending_choice(options[0]["id"])
        elif choice.get("kind") == "scry":
            engine.resolve_pending_choice("decline")
        else:
            engine.rules.resolve_choice("do")
        engine.resolve_until_stable()


def _hand(state, pid="p1"):
    return len(state.player_by_id(pid).hand)


def _life(state, pid="p1"):
    return state.player_by_id(pid).life


# -- another X enters --------------------------------------------------------


def test_canoptek_spyder_draws_for_other_nontoken_artifact_creatures_only():
    engine, state = _game()
    spyder = _real(state, "Canoptek Spyder")
    _enter(engine, state, spyder)  # itself: "another" excludes the source (RULE 109.1)
    assert _hand(state) == 0
    _enter(engine, state, _custom(state, "Golem", "Artifact Creature — Golem"))
    assert _hand(state) == 1
    _enter(engine, state, _custom(state, "Ride", "Artifact — Vehicle", power=None, toughness=None))
    assert _hand(state) == 1 + 1  # a nontoken Vehicle also qualifies (it is a Vehicle, RULE 301.7)
    _enter(engine, state, _custom(state, "Token Golem", "Artifact Creature — Golem"), token=True)
    assert _hand(state) == 2  # RULE 111.9: a token never qualifies
    _enter(engine, state, _custom(state, "Bear", "Creature — Bear"))
    assert _hand(state) == 2  # a plain creature is not an artifact
    _enter(engine, state, _custom(state, "Theirs", "Artifact Creature — Golem", owner="p2"))
    assert _hand(state) == 2  # "you control"


def test_decorated_champion_counts_other_warriors_not_itself():
    engine, state = _game()
    champion = _real(state, "Decorated Champion")
    _enter(engine, state, champion)
    assert champion.counters.get("+1/+1", 0) == 0
    _enter(engine, state, _custom(state, "Fighter", "Creature — Human Warrior"))
    assert champion.counters.get("+1/+1", 0) == 1
    _enter(engine, state, _custom(state, "Enemy Fighter", "Creature — Human Warrior", owner="p2"))
    assert champion.counters.get("+1/+1", 0) == 1  # RULE 810 is not modelled: "your team" is just "you"
    _enter(engine, state, _custom(state, "Wizard", "Creature — Human Wizard"))
    assert champion.counters.get("+1/+1", 0) == 1


def test_thrasher_brute_triggers_for_itself_and_other_warriors():
    engine, state = _game()
    brute = _real(state, "Thrasher Brute")
    _enter(engine, state, brute)
    assert (_life(state, "p2"), _life(state)) == (19, 21)
    _enter(engine, state, _custom(state, "Fighter", "Creature — Human Warrior"))
    assert (_life(state, "p2"), _life(state)) == (18, 22)
    _enter(engine, state, _custom(state, "Cleric", "Creature — Human Cleric"))
    assert (_life(state, "p2"), _life(state)) == (18, 22)


def test_general_kudro_triggers_for_itself_and_other_humans_you_control():
    engine, state = _game()
    state.player_by_id("p2").graveyard.append(GameObject(
        Card(id="g1", name="G1", type_line="Creature — Bear"), owner_id="p2", zone=Zone.GRAVEYARD))
    state.player_by_id("p2").graveyard.append(GameObject(
        Card(id="g2", name="G2", type_line="Creature — Bear"), owner_id="p2", zone=Zone.GRAVEYARD))
    kudro = _real(state, "General Kudro of Drannith")
    _enter(engine, state, kudro)
    _settle(engine, state)
    assert len(state.player_by_id("p2").graveyard) == 1  # itself: "General Kudro or another Human"
    _enter(engine, state, _custom(state, "Wizard", "Creature — Elf Wizard"))
    _settle(engine, state)
    assert len(state.player_by_id("p2").graveyard) == 1
    _enter(engine, state, _custom(state, "Human", "Creature — Human Soldier"))
    _settle(engine, state)
    assert len(state.player_by_id("p2").graveyard) == 0


def test_gladewalker_ritualist_counts_other_creatures_with_its_name():
    engine, state = _game()
    ritualist = _real(state, "Gladewalker Ritualist")
    _enter(engine, state, ritualist)
    assert _hand(state) == 0  # itself
    _enter(engine, state, _custom(state, "Bear", "Creature — Bear"))
    assert _hand(state) == 0  # another creature, wrong name
    _enter(engine, state, _real(state, "Gladewalker Ritualist"))
    assert _hand(state) == 1  # the original sees the second copy; the copy sees the original, not itself
    _enter(engine, state, _real(state, "Gladewalker Ritualist", owner="p2"))
    assert _hand(state) == 1  # "you control"


def test_isamaru_and_yoshimaru_matches_legendary_or_mana_value_one():
    engine, state = _game()
    pair = _real(state, "Isamaru and Yoshimaru")
    _enter(engine, state, pair)
    assert pair.counters.get("+1/+1", 0) == 0
    _enter(engine, state, _custom(state, "Hero", "Legendary Creature — Human", converted_mana_cost=5))
    assert pair.counters.get("+1/+1", 0) == 1
    _enter(engine, state, _custom(state, "One Drop", "Creature — Human", converted_mana_cost=1))
    assert pair.counters.get("+1/+1", 0) == 2
    _enter(engine, state, _custom(state, "Two Drop", "Creature — Human", converted_mana_cost=2))
    assert pair.counters.get("+1/+1", 0) == 2  # the qualifier binds to the second alternative only
    _enter(engine, state, _custom(state, "Legendary Land", "Legendary Land", converted_mana_cost=0))
    assert pair.counters.get("+1/+1", 0) == 2  # a legendary non-creature does not qualify


# -- cast heads ---------------------------------------------------------------


def _cast(engine, state, name, type_line, oracle="", keywords=(), pid="p1", **kw):
    card = Card(id=name, name=name, type_line=type_line, oracle_text=oracle, keywords=list(keywords),
                is_instant="Instant" in type_line, is_creature="Creature" in type_line, converted_mana_cost=0, **kw)
    spell = GameObject(card, owner_id=pid, zone=Zone.HAND)
    state.player_by_id(pid).add_to_zone(spell, Zone.HAND)
    bind_from_catalogue(spell)
    state.active_player_index = state.players.index(state.player_by_id(pid))
    state.current_step = "main1"  # RULE 307.1: a sorcery-speed spell needs the caster's empty-stack main phase
    engine.cast_spell(state.player_by_id(pid), spell)
    engine.resolve_until_stable()
    return spell


def test_slitherwisp_triggers_only_on_other_spells_with_flash():
    engine, state = _game()
    _real(state, "Slitherwisp")
    _cast(engine, state, "Plain", "Instant", "You gain 1 life.")
    assert (_hand(state), _life(state, "p2")) == (0, 20)
    _cast(engine, state, "Quick", "Instant", "Flash", keywords=["Flash"])
    assert (_hand(state), _life(state, "p2")) == (1, 19)
    _cast(engine, state, "Their Quick", "Instant", "Flash", keywords=["Flash"], pid="p2")
    assert (_hand(state), _life(state, "p2")) == (1, 19)  # "you cast"


def test_kasla_triggers_on_convoke_spells_even_unpaid():
    engine, state = _game()
    _real(state, "Kasla, the Broken Halo")
    _cast(engine, state, "Plain", "Instant", "You gain 1 life.")
    assert _hand(state) == 0
    _cast(engine, state, "Convoker", "Sorcery", "Convoke", keywords=["Convoke"])
    _settle(engine, state)
    assert _hand(state) == 1


def test_saint_traft_and_rem_karolus_untaps_on_convoke_spell():
    engine, state = _game()
    pair = _real(state, "Saint Traft and Rem Karolus")
    pair.tapped = True
    _cast(engine, state, "Plain", "Instant", "You gain 1 life.")
    assert pair.tapped is True
    _cast(engine, state, "Convoker", "Sorcery", "Convoke", keywords=["Convoke"])
    _settle(engine, state)
    assert pair.tapped is False


def test_card_type_count_filter():
    creature_artifact = GameObject(Card(id="a", name="A", type_line="Artifact Creature — Golem", is_creature=True),
                                   owner_id="p1", zone=Zone.STACK)
    legendary_creature = GameObject(Card(id="b", name="B", type_line="Legendary Creature — Human", is_creature=True),
                                    owner_id="p1", zone=Zone.STACK)
    assert matches_object_filter(creature_artifact, {"min_card_types": 2})
    assert not matches_object_filter(legendary_creature, {"min_card_types": 2})  # RULE 205.4: a supertype is no type
    assert matches_object_filter(legendary_creature, {"min_card_types": 1})


def test_card_type_count_cast_trigger_on_a_real_engine():
    engine, state = _game()
    _custom(state, "Watcher", "Creature — Wizard",
            "Whenever you cast another spell with two or more card types, you gain 3 life.")
    _cast(engine, state, "Plain", "Instant", "You gain 1 life.")
    assert _life(state) == 21
    _cast(engine, state, "Both", "Artifact Creature — Golem")
    assert _life(state) == 24


# -- counters, damage, exile, targeting, death --------------------------------


def test_knight_of_wundagore_counts_counters_on_other_creatures_once_per_turn():
    engine, state = _game()
    knight = _real(state, "Knight of Wundagore")
    other = _custom(state, "Bear", "Creature — Bear")
    engine.rules.add_counters(knight, 1, "+1/+1", source=knight)
    engine.resolve_until_stable()
    assert knight.counters.get("+1/+1", 0) == 1  # itself is not "another creature"
    engine.rules.add_counters(other, 1, "+1/+1", source=knight)
    engine.resolve_until_stable()
    assert knight.counters.get("+1/+1", 0) == 2
    engine.rules.add_counters(other, 1, "+1/+1", source=knight)
    engine.resolve_until_stable()
    assert knight.counters.get("+1/+1", 0) == 2  # "triggers only once each turn"


def test_talon_of_pain_ignores_its_own_damage_and_damage_to_creatures():
    engine, state = _game()
    talon = _custom(state, "Talon of Pain", "Artifact", _named("Talon of Pain").oracle_text)
    mine = _custom(state, "Bear", "Creature — Bear")
    theirs = _custom(state, "Wall", "Creature — Wall", owner="p2", toughness=5)
    p2 = state.player_by_id("p2")
    engine.rules.deal_damage(theirs, 1, source=mine)
    engine.resolve_until_stable()
    assert talon.counters.get("charge", 0) == 0  # a creature recipient
    engine.rules.deal_damage(p2, 1, source=talon)
    engine.resolve_until_stable()
    assert talon.counters.get("charge", 0) == 0  # "other than this artifact"
    engine.rules.deal_damage(state.player_by_id("p1"), 1, source=mine)
    engine.resolve_until_stable()
    assert talon.counters.get("charge", 0) == 0  # damage to you is not damage to an opponent
    engine.rules.deal_damage(p2, 1, source=mine)
    engine.resolve_until_stable()
    assert talon.counters.get("charge", 0) == 1
    engine.rules.deal_damage(p2, 1, source=_custom(state, "Their Bear", "Creature — Bear", owner="p2"))
    engine.resolve_until_stable()
    assert talon.counters.get("charge", 0) == 1  # "a source you control"


def test_captain_marvel_gains_life_for_other_exiled_creatures():
    engine, state = _game()
    marvel = _real(state, "Captain Marvel, Shooting Star")
    victim = _custom(state, "Ogre", "Creature — Ogre", power=3, toughness=3, owner="p2")
    engine.rules.exile(victim)
    engine.resolve_until_stable()
    assert _life(state) == 23  # life equal to its power (RULE 603.10a last-known information)
    engine.rules.exile(_custom(state, "Not A Creature", "Artifact", owner="p2"))
    engine.resolve_until_stable()
    assert _life(state) == 23
    engine.rules.exile(marvel)
    engine.resolve_until_stable()
    assert _life(state) == 23  # "other than Captain Marvel"


def test_king_of_the_oathbreakers_head_fires_for_each_spirit_targeted_by_a_spell():
    engine, state = _game()
    text = "Whenever ~ or another Spirit you control becomes the target of a spell, you gain 1 life."
    king = _custom(state, "King", "Creature — Spirit", text)
    spirit = _custom(state, "Ghost", "Creature — Spirit")
    bear = _custom(state, "Bear", "Creature — Bear")
    theirs = _custom(state, "Their Ghost", "Creature — Spirit", owner="p2")

    def target(obj):
        state.fire_event(GameEvent(
            EventType.BECOMES_TARGET, instance_id=obj.instance_id, target_controller_id=obj.controller_id,
            is_player=False, controller_id="p2", player_id="p2", item_kind="spell"))
        engine.resolve_until_stable()

    target(king)
    assert _life(state) == 21
    target(spirit)
    assert _life(state) == 22
    target(bear)
    target(theirs)
    assert _life(state) == 22


def test_slaughter_singer_pumps_another_creature_with_toxic_when_it_attacks():
    engine, state = _game()
    singer = _real(state, "Slaughter Singer")
    toxic = _custom(state, "Toxic Bear", "Creature — Bear", "Toxic 1", keywords=["Toxic"])
    plain = _custom(state, "Plain Bear", "Creature — Bear")

    def attack(obj):
        state.fire_event(GameEvent(EventType.ATTACKS, instance_id=obj.instance_id, player_id=obj.controller_id))
        engine.resolve_until_stable()

    def power(obj):
        engine.recompute_continuous_effects()
        return obj.power

    attack(singer)  # it has toxic itself but is not "another" (RULE 109.1)
    assert power(singer) == 2
    attack(plain)
    assert power(plain) == 2
    attack(toxic)
    assert power(toxic) == 3


@pytest.mark.parametrize("owner, controller, draws", [
    ("p2", "p2", 1),  # an opponent's own permanent
    ("p2", "p1", 1),  # RULE 400.3: a stolen creature goes to its OWNER's graveyard -- owned by another player
    ("p1", "p1", 0),  # your own
    ("p1", "p2", 0),  # you own it but an opponent controls it: still not "owned by another player"
])
def test_kothophed_reads_the_owner_not_the_controller(owner, controller, draws):
    engine, state = _game()
    _real(state, "Kothophed, Soul Hoarder")
    victim = _custom(state, "Victim", "Creature — Bear", owner=owner, controller=controller)
    engine.rules.destroy(victim)
    _settle(engine, state)
    assert _hand(state) == draws
    assert _life(state) == 20 - draws


def test_yomiji_excludes_itself():
    engine, state = _game()
    yomiji = _real(state, "Yomiji, Who Bars the Way")
    other = _custom(state, "Hero", "Legendary Creature — Human")
    plain = _custom(state, "Bear", "Creature — Bear")
    engine.rules.destroy(plain)
    _settle(engine, state)
    assert other.zone == Zone.BATTLEFIELD and yomiji.zone == Zone.BATTLEFIELD
    engine.rules.destroy(other)
    _settle(engine, state)
    assert other.zone == Zone.HAND  # returned to its owner's hand
    engine.rules.destroy(yomiji)
    _settle(engine, state)
    assert yomiji.zone == Zone.GRAVEYARD  # "other than Yomiji"


def test_permanent_other_than_self_dies_head_on_a_real_engine():
    engine, state = _game()
    watcher = _custom(state, "Watcher", "Creature — Wizard", "Whenever a permanent other than ~ dies, you gain 2 life.")
    engine.rules.destroy(watcher)
    _settle(engine, state)
    assert _life(state) == 20  # the source itself dying does not trigger "other than ~"
    watcher2 = _custom(state, "Watcher2", "Creature — Wizard", "Whenever a permanent other than ~ dies, you gain 2 life.")
    engine.rules.destroy(_custom(state, "Bear", "Creature — Bear", owner="p2"))
    _settle(engine, state)
    assert _life(state) == 22
    assert watcher2.zone == Zone.BATTLEFIELD


def test_sonic_group_keyword_any_filter():
    engine, state = _game()
    _real(state, "Sonic the Hedgehog")
    fast = _custom(state, "Fast", "Creature — Bear", "Haste", keywords=["Haste"])
    flashy = _custom(state, "Flashy", "Creature — Bear", "Flash", keywords=["Flash"])
    slow = _custom(state, "Slow", "Creature — Bear")
    engine.rules.deal_damage(slow, 1, source=None)
    engine.resolve_until_stable()
    treasures = lambda: [o for o in state.battlefield if "Treasure" in (o.card.type_line or "")]
    assert not treasures()
    engine.rules.deal_damage(fast, 1, source=None)
    engine.resolve_until_stable()
    assert len(treasures()) == 1
    engine.rules.deal_damage(flashy, 1, source=None)
    engine.resolve_until_stable()
    assert len(treasures()) == 2


def test_plague_nurse_gives_toxic_only_to_other_toxic_creatures():
    from mtg_analyzer.game.combat import toxic_value
    engine, state = _game()
    nurse = _real(state, "Plague Nurse")
    toxic = _custom(state, "Toxic Bear", "Creature — Bear", "Toxic 1", keywords=["Toxic"])
    plain = _custom(state, "Plain Bear", "Creature — Bear")
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"G": 1, "C": 2})
    engine.activate_ability(p1, nurse)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert toxic_value(toxic) == 2  # toxic 1 + the granted toxic 1 (RULE 702.164b)
    assert toxic_value(nurse) == 2  # "each OTHER creature": the Nurse keeps its printed toxic 2
    assert toxic_value(plain) is None  # no toxic, so no grant


# -- RULE 603.8 state trigger ------------------------------------------------


def test_cheese_stands_alone_wins_only_when_alone_with_an_empty_hand():
    engine, state = _game()
    cheese = _real(state, "The Cheese Stands Alone")
    other = _custom(state, "Bear", "Creature — Bear")
    engine.resolve_until_stable()
    assert not state.player_by_id("p2").has_lost
    engine.rules.destroy(other)
    engine.resolve_until_stable()
    assert cheese.zone == Zone.BATTLEFIELD
    assert state.player_by_id("p2").has_lost


def test_cheese_stands_alone_needs_an_empty_hand_too():
    engine, state = _game()
    _real(state, "The Cheese Stands Alone")
    state.player_by_id("p1").hand.append(GameObject(Card(id="h", name="H", type_line="Land"), owner_id="p1",
                                                    zone=Zone.HAND))
    engine.resolve_until_stable()
    assert not state.player_by_id("p2").has_lost


def test_barren_glory_is_an_intervening_if_over_both_halves():
    # RULE 603.4: the condition is checked on the trigger event and again on resolution.
    engine, state = _game()
    _real(state, "Barren Glory")
    other = _custom(state, "Bear", "Creature — Bear")
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    assert not state.player_by_id("p2").has_lost  # a second permanent
    other.zone = Zone.GRAVEYARD
    state.battlefield.remove(other)
    state.player_by_id("p1").hand.append(GameObject(Card(id="h", name="H", type_line="Land"), owner_id="p1",
                                                    zone=Zone.HAND))
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    assert not state.player_by_id("p2").has_lost  # a card in hand
    state.player_by_id("p1").hand.clear()
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    assert state.player_by_id("p2").has_lost


# -- shared-grammar side effects: target unions, exact mana value, keyword tails --------------------------------------


def _cast_real(engine, state, name, *targets, mode=None):
    """Cast the real card from p1's hand with a full mana pool and resolve it."""
    spell = GameObject(_named(name), owner_id="p1", zone=Zone.HAND)
    state.player_by_id("p1").add_to_zone(spell, Zone.HAND)
    bind_from_catalogue(spell)
    state.player_by_id("p1").mana_pool.add_many({c: 6 for c in "WUBRGC"})
    state.active_player_index = 0
    state.current_step = "main1"
    kwargs = {"mode": mode} if mode is not None else {}
    engine.cast_spell(state.player_by_id("p1"), spell, targets=list(targets), **kwargs)
    engine.resolve_until_stable()
    return spell


def _gone(obj):
    return obj.zone != Zone.BATTLEFIELD


@pytest.mark.parametrize(
    "spell, type_line, extra, legal",
    [
        ("Purge", "Artifact Creature — Golem", {}, True),
        ("Purge", "Creature — Zombie", {"mana_cost_string": "{1}{B}"}, True),
        ("Purge", "Creature — Bear", {}, False),
        ("Ray of Ruin", "Creature — Bear", {}, True),
        ("Ray of Ruin", "Artifact — Vehicle", {}, True),
        ("Ray of Ruin", "Land", {}, True),  # a nonbasic land (no "Basic" supertype)
        ("Ray of Ruin", "Basic Land — Forest", {}, False),
        ("Ray of Ruin", "Artifact", {}, False),
        ("Isolate", "Creature — Bear", {"converted_mana_cost": 1}, True),
        ("Isolate", "Creature — Bear", {"converted_mana_cost": 2}, False),
        ("Radiant Strike", "Artifact", {}, True),
        ("Radiant Strike", "Creature — Bear", {}, False),  # an untapped creature is neither
    ],
)
def test_target_union_and_exact_mana_value_spells(spell, type_line, extra, legal):
    engine, state = _game()
    victim = _custom(state, "Victim", type_line, owner="p2", **extra)
    if not legal:
        with pytest.raises(ValueError, match="no legal target"):
            _cast_real(engine, state, spell, victim)
        assert not _gone(victim)
        return
    _cast_real(engine, state, spell, victim)
    assert _gone(victim)


def test_radiant_strike_hits_a_tapped_creature():
    engine, state = _game()
    victim = _custom(state, "Victim", "Creature — Bear", owner="p2")
    victim.tapped = True
    _cast_real(engine, state, "Radiant Strike", victim)
    assert _gone(victim)
    assert _life(state) == 23


def test_guerrilla_gorilla_destroys_noncreature_artifact_or_enchantment_only():
    engine, state = _game()
    gorilla = _real(state, "Guerrilla Gorilla")
    state.current_step = "main1"
    state.active_player_index = 0
    artifact = _custom(state, "Rock", "Artifact", owner="p2")
    engine.activate_ability(state.player_by_id("p1"), gorilla, targets=[artifact])
    engine.resolve_until_stable()
    assert _gone(artifact) and _gone(gorilla)


@pytest.mark.parametrize(
    "spell, type_line, extra, legal",
    [
        ("Radiant Purge", "Creature — Bear", {"mana_cost_string": "{R}"}, False),
        ("Radiant Purge", "Creature — Bear", {"mana_cost_string": "{R}{G}"}, True),
        ("Radiant Purge", "Enchantment — Aura", {"mana_cost_string": "{R}{G}"}, True),
        ("Radiant Purge", "Artifact", {"mana_cost_string": "{R}{G}"}, False),
        ("Feast of Dreams", "Creature — Bear", {}, False),
        ("Feast of Dreams", "Enchantment Creature — Bear", {}, True),
    ],
)
def test_multicolored_and_enchantment_creature_unions(spell, type_line, extra, legal):
    # One candidate at a time: with a legal alternative on the board the engine would retarget a bad pick.
    engine, state = _game()
    victim = _custom(state, "Victim", type_line, owner="p2", **extra)
    if not legal:
        with pytest.raises(ValueError, match="no legal target"):
            _cast_real(engine, state, spell, victim)
        return
    _cast_real(engine, state, spell, victim)
    assert _gone(victim)


def test_feast_of_dreams_hits_an_enchanted_creature():
    engine, state = _game()
    victim = _custom(state, "Victim", "Creature — Bear", owner="p2")
    aura = _custom(state, "Aura", "Enchantment — Aura", "Enchant creature", owner="p2")
    aura.attached_to = victim.instance_id  # RULE 303.4: it stays attached, so the creature is "enchanted"
    _cast_real(engine, state, "Feast of Dreams", victim)
    assert _gone(victim)


def test_kestia_draws_for_attacking_enchanted_or_enchantment_creature_you_control():
    engine, state = _game()
    _real(state, "Kestia, the Cultivator")
    plain = _custom(state, "Plain", "Creature — Bear")
    ench = _custom(state, "Nyx Bear", "Enchantment Creature — Bear")
    theirs = _custom(state, "Theirs", "Enchantment Creature — Bear", owner="p2")
    for obj in (plain, theirs, ench):
        state.fire_event(GameEvent(EventType.ATTACKS, instance_id=obj.instance_id, player_id=obj.controller_id))
        engine.resolve_until_stable()
    assert _hand(state) == 1


def test_iron_spider_counters_every_artifact_creature_and_vehicle_you_control():
    engine, state = _game()
    spider = _real(state, "Iron Spider, Stark Upgrade")
    golem = _custom(state, "Golem", "Artifact Creature — Golem")
    vehicle = _custom(state, "Ride", "Artifact — Vehicle", power=None, toughness=None)
    bear = _custom(state, "Bear", "Creature — Bear")
    theirs = _custom(state, "Theirs", "Artifact Creature — Golem", owner="p2")
    engine.activate_ability(state.player_by_id("p1"), spider)
    engine.resolve_until_stable()
    assert [o.counters.get("+1/+1", 0) for o in (spider, golem, vehicle, bear, theirs)] == [1, 1, 1, 0, 0]


def test_jedit_ojanen_self_name_folds_and_makes_a_token_on_attack():
    engine, state = _game()
    jedit = _real(state, "Jedit Ojanen of Efrava")
    state.fire_event(GameEvent(EventType.ATTACKS, instance_id=jedit.instance_id, player_id="p1"))
    engine.resolve_until_stable()
    cats = [o for o in state.battlefield if "Cat" in (o.card.type_line or "") and o is not jedit]
    assert len(cats) == 1


def test_ant_man_counts_counters_on_any_creature_once_per_turn():
    engine, state = _game()
    ant = _real(state, "Ant-Man, Colony Commander")
    bear = _custom(state, "Bear", "Creature — Bear")
    tokens = lambda: [o for o in state.battlefield if "Insect" in (o.card.type_line or "")]
    engine.rules.add_counters(bear, 1, "-1/-1", source=ant)
    engine.resolve_until_stable()
    assert not tokens()  # a -1/-1 counter is not a +1/+1 counter
    engine.rules.add_counters(bear, 1, "+1/+1", source=ant)
    engine.resolve_until_stable()
    assert len(tokens()) == 1
    engine.rules.add_counters(bear, 1, "+1/+1", source=ant)
    engine.resolve_until_stable()
    assert len(tokens()) == 1  # "This ability triggers only once each turn."


def test_banishing_slash_target_union_with_tapped_creature():
    engine, state = _game()
    untapped = _custom(state, "Fresh", "Creature — Bear", owner="p2")
    _cast_real(engine, state, "Banishing Slash", untapped)  # "up to one": an untapped creature is no legal target
    assert not _gone(untapped)
    tapped = _custom(state, "Tired", "Creature — Bear", owner="p2")
    tapped.tapped = True
    _cast_real(engine, state, "Banishing Slash", tapped)
    assert _gone(tapped) and not _gone(untapped)


def test_bumi_bash_destroy_mode_hits_land_creatures_and_nonbasic_lands():
    for type_line, legal in (("Land Creature — Forest Dryad", True), ("Land", True),
                             ("Basic Land — Forest", False), ("Creature — Bear", False)):
        engine, state = _game()
        victim = _custom(state, "Victim", type_line, owner="p2")
        spell = None
        try:
            spell = _cast_real(engine, state, "Bumi Bash", victim, mode=1)
        except ValueError:
            assert not legal
            continue
        assert legal and _gone(victim), type_line
