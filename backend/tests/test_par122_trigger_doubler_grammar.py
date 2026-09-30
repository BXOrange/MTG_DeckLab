"""PAR-122 — trigger doublers ("… triggers an additional time", RULE 603.2d).

One `trigger_doubler` spec built from two composed halves: a *cause* (a
trigger-shaped dict — the gerund "a creature you control attacking" is the head
"a creature you control attacks") and a *subject* (a `matches_object_filter`
dict on the doubled permanent, plus "another"/"attached"). Parse tests pin the
grammar and that it fails closed; execute tests put a real doubler on a real
board and count how many times a real trigger is placed.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _fire_enter, _named

TAIL = ", that ability triggers an additional time."


def _params(text):
    specs = static_effect_specs(text)
    assert specs is not None and len(specs) == 1 and specs[0].type == "trigger_doubler", text
    return specs[0].params


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("if a triggered ability of a legendary creature you control triggers" + TAIL,
         {"subject": {"filter": {"legendary": True, "card_type": "creature"}}}),
        ("if an ability of another wolf or battle you control triggers" + TAIL,
         {"subject": {"filter": {"any_of": [{"subtype": "wolf"}, {"card_type": "battle"}]},
                      "other": True}}),
        ("if a triggered ability of a permanent you control but don't own triggers" + TAIL,
         {"subject": {"filter": {"not_owned_by_you": True}}}),
        ("if an ability of equipped creature triggers" + TAIL, {"subject": {"attached": True}}),
        ("if a triggered ability of another elemental you control triggers, it triggers an additional time.",
         {"subject": {"filter": {"subtype": "elemental"}, "other": True}}),
        ("if an artifact or creature entering causes a triggered ability of a permanent you control to trigger" + TAIL,
         {"cause": {"event": "ENTERS_BATTLEFIELD",
                    "condition": {"subject": "group", "controller": "any", "other": False,
                                  "type": ["artifact", "creature"]}}}),
        ("if a creature you control attacking causes a triggered ability of a permanent you control to trigger" + TAIL,
         {"cause": {"event": "ATTACKS",
                    "condition": {"subject": "group", "controller": "you", "other": False,
                                  "type": "creature"}}}),
        ("if a creature you control dealing combat damage to a player causes a triggered ability of a permanent you control to trigger" + TAIL,
         {"cause": {"event": "DAMAGE",
                    "condition": {"subject": "group", "controller": "you", "other": False,
                                  "filter": {"card_type": "creature"}},
                    "filter": {"combat": True, "is_player": True}}}),
        # the passive gerunds (Valiant Emberkin / Wayta) and "turning … face up" (Panoptic Projektor)
        ("if a creature you control becoming the target of a spell or ability causes a triggered ability of a permanent you control to trigger" + TAIL,
         {"cause": {"event": "BECOMES_TARGET",
                    "condition": {"subject": "group", "controller": "you", "other": False,
                                  "filter": {"card_type": "creature"}}}}),
        ("if a creature you control being dealt damage causes a triggered ability of a permanent you control to trigger" + TAIL,
         {"cause": {"event": "DAMAGE",
                    "condition": {"subject": "group", "controller": "you", "other": False,
                                  "filter": {"card_type": "creature"}, "recipient": True},
                    "filter": {}}}),
        ("if turning a face-down permanent face up causes a triggered ability of a permanent you control to trigger" + TAIL,
         {"cause": {"event": "TURNED_FACE_UP",
                    "condition": {"subject": "group", "controller": "any", "other": False,
                                  "filter": {"face_down": True}}}}),
        # a compound subject (Cloud) and a "while" gate (Sanctum of All)
        ("if a triggered ability of ~ or an equipment attached to it triggers" + TAIL,
         {"subject": {"any_of": [{"self": True},
                                 {"filter": {"subtype": "equipment"}, "attached_to_doubler": True}]}}),
        ("if a triggered ability of another shrine you control triggers while you control 6 or more shrines" + TAIL,
         {"subject": {"filter": {"subtype": "shrine"}, "other": True},
          "active_if": {"kind": "control_count",
                        "selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "shrine"}},
                        "min": 6}}),
    ],
)
def test_doubler_parses(text, expected):
    assert _params(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "if a triggered ability of a creature an opponent controls triggers" + TAIL,  # only your own
        "if a triggered ability of a frobnicator you control triggers" + TAIL,
        "if a frobnicator entering causes a triggered ability of a permanent you control to trigger" + TAIL,
        "if a creature exploring causes a triggered ability of a permanent you control to trigger" + TAIL,
        "if a triggered ability of a creature you control triggers, that ability triggers twice.",
        "if a triggered ability of ~ or a frobnicator attached to it triggers" + TAIL,
        "if a triggered ability of ~ or an equipment attached to it triggers while you frobnicate" + TAIL,
    ],
)
def test_doubler_fails_closed(text):
    assert static_effect_specs(text) is None


def test_as_long_as_wrapper_gates_the_whole_doubler():
    params = _params(
        "as long as you have an enduring story, if an ability of a dwarf you control triggers" + TAIL
    )
    assert params["active_if"] == {"kind": "has_enduring_story"}
    assert params["subject"] == {"filter": {"subtype": "dwarf"}}


@pytest.mark.parametrize(
    "name",
    [
        "Panharmonicon", "Ancient Greenwarden", "Naban, Dean of Iteration", "Starfield Vocalist",
        "Teysa Karlov", "Isshin, Two Heavens as One", "Wulfgar of Icewind Dale",
        "Felix Five-Boots", "Annie Joins Up", "Chief of the Wilds", "Jabs, Mistress of Mockery",
        "Katara, the Fearless", "Splinter, Radical Rat", "Twinflame Travelers",
        "Wizard's Staff", "Bifur, Melodic Rider", "Valiant Emberkin",
        "Krang, the All-Powerful", "Echoes of Eternity", "The Fish Brewer", "The Masamune",
    ],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Engine: doubling a real trigger
# ---------------------------------------------------------------------------

ETB = "When ~ enters, you gain 1 life."


def _put(state, name="Doubler", oracle="", owner="p1", types="Enchantment", **kw):
    card = Card(id=name, name=name, type_line=types, oracle_text=oracle,
                is_creature="Creature" in types,
                power=1 if "Creature" in types else None,
                toughness=1 if "Creature" in types else None, **kw)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _doubler(state, cause_or_subject_text):
    return _put(state, "Doubler", cause_or_subject_text + TAIL)


def _etb_gain(doubler_text, entering_types, owner="p1", doubler_owner="p1", **kw):
    engine, state = _engine()
    state.current_step = "main1"
    _doubler(state, doubler_text)
    entering = _put(state, "Entering", ETB, owner=owner, types=entering_types, **kw)
    life = state.player_by_id("p1").life
    _fire_enter(engine, state, entering)
    return state.player_by_id("p1").life - life


def test_cause_scopes_which_event_doubles():
    text = "if an artifact or creature entering causes a triggered ability of a permanent you control to trigger"
    assert _etb_gain(text, "Creature — Bear") == 2
    assert _etb_gain(text, "Artifact") == 2
    assert _etb_gain(text, "Enchantment") == 1


def test_cause_subject_carries_the_controller_scope():
    text = "if a wizard you control entering causes a triggered ability of a permanent you control to trigger"
    assert _etb_gain(text, "Creature — Wizard") == 2
    assert _etb_gain(text, "Creature — Bear") == 1


def test_subject_scopes_whose_ability_doubles():
    text = "if a triggered ability of a legendary creature you control triggers"
    assert _etb_gain(text, "Legendary Creature — Bear", is_legendary=True) == 2
    assert _etb_gain(text, "Creature — Bear") == 1


def test_another_excludes_the_doubler_itself():
    engine, state = _engine()
    state.current_step = "main1"
    oracle = ("If a triggered ability of another elemental you control triggers, "
              "it triggers an additional time.\n" + ETB)
    doubler = _put(state, "Elemental Twin", oracle, types="Creature — Elemental")
    life = state.player_by_id("p1").life
    _fire_enter(engine, state, doubler)          # its own ETB: not "another"
    assert state.player_by_id("p1").life - life == 1
    other = _put(state, "Other", ETB, types="Creature — Elemental")
    life = state.player_by_id("p1").life
    _fire_enter(engine, state, other)
    assert state.player_by_id("p1").life - life == 2


def test_you_control_but_dont_own():
    engine, state = _engine()
    state.current_step = "main1"
    _doubler(state, "if a triggered ability of a permanent you control but don't own triggers")
    mine = _put(state, "Mine", ETB, types="Creature — Bear")
    borrowed = _put(state, "Borrowed", ETB, types="Creature — Bear")
    borrowed.owner_id = "p2"          # p1 controls it (Threaten-style) but does not own it

    def gained(obj):
        life = state.player_by_id("p1").life
        _fire_enter(engine, state, obj)
        return state.player_by_id("p1").life - life

    assert gained(mine) == 1
    assert gained(borrowed) == 2


def test_a_dies_cause_doubles_the_watching_trigger():
    engine, state = _engine()
    state.current_step = "main1"
    _doubler(state, "if a creature dying causes a triggered ability of a permanent you control to trigger")
    _put(state, "Watcher", "Whenever a creature dies, you gain 1 life.")
    victim = _put(state, "Victim", types="Creature — Bear")
    life = state.player_by_id("p1").life
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life - life == 2


def test_an_active_if_gate_switches_the_whole_doubler_off():
    engine, state = _engine()
    state.current_step = "main1"
    doubler = _put(state, "Doubler", "If a triggered ability of a creature you control triggers" + TAIL,
                   types="Creature — Bear")
    effect = next(e for e in doubler.static_effects if type(e).__name__ == "TriggerDoublerEffect")
    entering = _put(state, "Entering", ETB, types="Creature — Bear")
    life = state.player_by_id("p1").life
    _fire_enter(engine, state, entering)
    assert state.player_by_id("p1").life - life == 2
    effect.active_if = {"kind": "never"}     # an unknown gate never holds (fail closed)
    life = state.player_by_id("p1").life
    _fire_enter(engine, state, entering)
    assert state.player_by_id("p1").life - life == 1


def test_a_doubler_only_doubles_its_own_controllers_permanents():
    engine, state = _engine()
    state.current_step = "main1"
    _doubler(state, "if a triggered ability of a creature you control triggers")
    theirs = _put(state, "Theirs", ETB, owner="p2", types="Creature — Bear")
    life = state.player_by_id("p2").life
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p2", card_id=theirs.card.id,
        object=theirs.name, instance_id=theirs.instance_id, object_types=sorted(theirs.type_words),
    ))
    engine.resolve_until_stable()
    assert state.player_by_id("p2").life - life == 1


def test_a_being_dealt_damage_cause_doubles_the_watching_trigger():
    """Wayta's "a creature you control being dealt damage" (passive gerund)."""
    engine, state = _engine()
    state.current_step = "main1"
    _doubler(state, "if a creature you control being dealt damage causes a triggered ability of a permanent you control to trigger")
    _put(state, "Watcher", "Whenever a creature you control is dealt damage, you gain 1 life.")
    victim = _put(state, "Victim", types="Creature — Bear")
    victim.card.toughness = 9
    life = state.player_by_id("p1").life
    engine.rules.deal_damage(victim, 1, victim)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life - life == 2


def test_a_compound_subject_doubles_the_doubler_itself_and_its_attachment():
    """Cloud: "a triggered ability of ~ or an Equipment attached to it"."""
    engine, state = _engine()
    state.current_step = "main1"
    cloud = _put(state, "Cloud", "If a triggered ability of ~ or an Equipment attached to it triggers" + TAIL
                 + "\n" + ETB, types="Creature — Soldier")
    bystander = _put(state, "Bystander", ETB, types="Creature — Bear")
    sword = _put(state, "Sword", ETB, types="Artifact — Equipment")
    loose = _put(state, "Loose", ETB, types="Artifact — Equipment")

    def gained(obj, attach=False):
        # attach right before the event: the trigger is doubled as it is put on the stack, and
        # this fixture's bare Equipment is unattached by a later state-based-action pass
        sword.attached_to = cloud.instance_id if attach else None
        life = state.player_by_id("p1").life
        _fire_enter(engine, state, obj)
        return state.player_by_id("p1").life - life

    assert gained(bystander) == 1        # neither Cloud nor its attachment
    assert gained(loose) == 1            # an Equipment attached to nothing
    assert gained(sword, attach=True) == 2   # attached to Cloud
    assert gained(cloud) == 2            # the doubler itself


def test_a_while_gate_doubles_only_once_the_count_is_met():
    """Sanctum of All: "… triggers while you control six or more Shrines"."""
    engine, state = _engine()
    state.current_step = "main1"
    _put(state, "Sanctum", "If a triggered ability of another shrine you control triggers while you "
                            "control 3 or more shrines" + TAIL, types="Enchantment — Shrine")
    first = _put(state, "First", ETB, types="Enchantment — Shrine")

    def gained(obj):
        life = state.player_by_id("p1").life
        _fire_enter(engine, state, obj)
        return state.player_by_id("p1").life - life

    assert gained(first) == 1            # two shrines: the gate is closed
    _put(state, "Third", "", types="Enchantment — Shrine")
    assert gained(first) == 2            # three: open


def test_a_player_draw_cause_parses():
    """Krang, the All-Powerful: a player-event cause ("a player drawing a card")."""
    assert _params(
        "if a player drawing a card causes a triggered ability of a permanent you control to trigger" + TAIL
    ) == {"cause": {"event": "DRAW", "condition": {"subject": "player", "scope": "any"}}}


def test_a_player_draw_cause_doubles_the_watching_trigger():
    engine, state = _engine()
    state.current_step = "main1"
    _doubler(state, "if a player drawing a card causes a triggered ability of a permanent you control to trigger")
    _put(state, "Watcher", "Whenever a player draws a card, you gain 1 life.")
    p2 = state.player_by_id("p2")
    p2.library.append(GameObject(Card(id="L", name="L", type_line="Instant"), owner_id="p2", zone=Zone.LIBRARY))
    life = state.player_by_id("p1").life
    engine.rules.draw(p2, 1)   # an opponent's draw is "a player"
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life - life == 2


# ---------------------------------------------------------------------------
# The last doubler shapes: a spell's own triggers, an emblem's, a granted doubler, a paid one
# ---------------------------------------------------------------------------

ECHOES = ("if a triggered ability of a colorless spell you control or another colorless permanent "
          "you control triggers" + TAIL)


def _cast(engine, state, oracle, colors=(), owner="p1"):
    """Cast a real spell whose oracle text is ``oracle`` from ``owner``'s hand."""
    card = Card(id="Cast", name="Cast", type_line="Sorcery", oracle_text=oracle,
                color_identity=set(colors), converted_mana_cost=0, is_sorcery=True)
    spell = GameObject(card, owner_id=owner, zone=Zone.HAND)
    bind_from_catalogue(spell)
    state.player_by_id(owner).hand.append(spell)
    engine.cast_spell(state.player_by_id(owner), spell, targets=None)
    engine.resolve_until_stable()


def _gain_from_cast(doubler_text, spell_oracle, colors=()):
    engine, state = _engine()
    engine.begin_turn()
    state.current_step = "main1"
    _put(state, "Echoes", doubler_text, types="Enchantment")
    life = state.player_by_id("p1").life
    _cast(engine, state, spell_oracle, colors)
    return state.player_by_id("p1").life - life


def test_a_spells_own_cast_trigger_is_doubled():
    """Echoes of Eternity: "a colorless spell you control" — its cast trigger (cascade, storm)."""
    when_cast = "When you cast this spell, you gain 1 life."
    assert _gain_from_cast(ECHOES, when_cast) == 2
    assert _gain_from_cast(ECHOES, when_cast, colors=("R",)) == 1


def test_a_permanent_only_doubler_does_not_double_a_spell():
    plain = "if a triggered ability of a permanent you control triggers"
    assert _gain_from_cast(plain, "When you cast this spell, you gain 1 life.") == 1


def test_the_permanent_side_of_a_spell_compound_still_doubles_and_excludes_itself():
    engine, state = _engine()
    state.current_step = "main1"
    _put(state, "Echoes", ECHOES + "\n" + ETB, types="Artifact")
    other = _put(state, "Other", ETB, types="Artifact")
    colored = _put(state, "Colored", ETB, types="Creature — Bear", color_identity={"R"})

    def gained(obj):
        life = state.player_by_id("p1").life
        _fire_enter(engine, state, obj)
        return state.player_by_id("p1").life - life

    assert gained(other) == 2
    assert gained(colored) == 1
    echoes = next(o for o in state.battlefield if o.name == "Echoes")
    assert gained(echoes) == 1           # "another": not Echoes itself


def test_a_cast_copy_trigger_copies_the_spell():
    """Echoes of Eternity's second ability: "whenever you cast a colorless spell, copy it"."""
    engine, state = _engine()
    engine.begin_turn()
    state.current_step = "main1"
    _put(state, "Echoes", "Whenever you cast a colorless spell, copy it. "
                          "You may choose new targets for the copy.", types="Enchantment")
    _cast(engine, state, "You gain 3 life.")
    assert state.player_by_id("p1").life == 26     # the spell and its copy


MASAMUNE = ('Equipped creature has "If a creature dying causes a triggered ability of this creature '
            'or an emblem you own to trigger, that ability triggers an additional time."')


def _equipped(state, sword_oracle=MASAMUNE):
    creature = _put(state, "Bearer", "Whenever a creature dies, you gain 1 life.",
                    types="Creature — Soldier")
    sword = _put(state, "Sword", sword_oracle, types="Artifact — Equipment")
    return creature, sword


def _watch_deaths(engine, state):
    victim = _put(state, "Victim", types="Creature — Bear")
    life = state.player_by_id("p1").life
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    return state.player_by_id("p1").life - life


def test_a_granted_doubler_is_held_by_the_equipped_creature():
    """The Masamune: the creature's own "dies" trigger fires twice only while it is equipped."""
    engine, state = _engine()
    state.current_step = "main1"
    creature, sword = _equipped(state)
    assert _watch_deaths(engine, state) == 1               # not attached yet
    sword.attached_to = creature.instance_id
    assert _watch_deaths(engine, state) == 2


def _emblem_watching_deaths(state, player_id):
    """An emblem "Whenever a creature dies, you gain 1 life." for ``player_id``."""
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec

    spec = AbilitySpec(
        "triggered", [EffectSpec("gain_life", {"amount": 1})],
        trigger={"event": "DIES", "condition": {"subject": "group", "type": "creature", "controller": "any"}},
        raw_text="Whenever a creature dies, you gain 1 life.",
    )
    return spec.to_dict()


def test_a_granted_doubler_covers_an_emblem_you_own_and_only_that_players():
    engine, state = _engine()
    state.current_step = "main1"
    creature, sword = _equipped(state)
    sword.attached_to = creature.instance_id
    creature.triggered_abilities.clear()                   # only the emblems watch
    engine.rules.create_emblem(state.player_by_id("p1"), _emblem_watching_deaths(state, "p1"))
    engine.rules.create_emblem(state.player_by_id("p2"), _emblem_watching_deaths(state, "p2"))
    p1_life, p2_life = state.player_by_id("p1").life, state.player_by_id("p2").life
    victim = _put(state, "Victim", types="Creature — Bear")
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life - p1_life == 2    # my emblem: doubled
    assert state.player_by_id("p2").life - p2_life == 1    # theirs: not "an emblem you own"


def test_the_granted_conditional_keywords_follow_the_equipped_creature_attacking():
    """The Masamune's "as long as equipped creature is attacking, it has first strike and must be
    blocked if able"."""
    engine, state = _engine()
    state.current_step = "main1"
    creature, sword = _equipped(state, "As long as equipped creature is attacking, it has first "
                                       "strike and must be blocked if able.")
    sword.attached_to = creature.instance_id
    engine.recompute_continuous_effects()
    assert "first_strike" not in creature.granted_keywords
    creature.attacking = True
    engine.recompute_continuous_effects()
    assert {"first_strike", "must_be_blocked"} <= set(creature.granted_keywords)


BREWER = ("if another permanent entering the battlefield causes a triggered ability of a permanent "
          "you control to trigger, tap any number of Fish you control. That ability triggers an "
          "additional time for each Fish tapped this way.")


def test_a_paid_doubler_parses_with_its_tap_cost():
    assert _params(BREWER) == {
        "cause": {"event": "ENTERS_BATTLEFIELD",
                  "condition": {"subject": "group", "controller": "any", "other": True,
                                "type": "permanent"}},
        "tap_cost": {"filter": {"subtype": "fish"}},
    }


def _brewer_board(fish=3):
    engine, state = _engine()
    state.current_step = "main1"
    _put(state, "Brewer", BREWER, types="Creature — Human")
    fishes = [_put(state, f"Fish{i}", types="Creature — Fish") for i in range(fish)]
    _put(state, "Watcher", "Whenever another permanent enters, you gain 1 life.")
    return engine, state, fishes


def _enter_and_answer(engine, state, picks):
    """Fire an entering permanent's event; answer the tap choice with ``picks`` (a list of
    permanents, then "done"); return the life gained."""
    entering = _put(state, "Entering", "", types="Artifact")
    life = state.player_by_id("p1").life
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", card_id=entering.card.id,
        object=entering.name, instance_id=entering.instance_id, object_types=sorted(entering.type_words),
    ))
    engine.rules.put_triggers_on_stack()
    for pick in picks:
        assert state.pending_choice["kind"] == "trigger_doubler_tap"
        engine.rules.resolve_choice(str(pick.instance_id))
    if state.pending_choice:     # it closes by itself once nothing is left to tap
        assert state.pending_choice["kind"] == "trigger_doubler_tap"
        engine.rules.resolve_choice("decline")
    assert state.pending_choice is None
    engine.resolve_until_stable()
    return state.player_by_id("p1").life - life


def test_a_paid_doubler_adds_one_copy_per_permanent_tapped():
    engine, state, fishes = _brewer_board()
    assert _enter_and_answer(engine, state, fishes[:2]) == 3
    assert [f.tapped for f in fishes] == [True, True, False]


def test_a_paid_doubler_may_tap_nothing():
    engine, state, fishes = _brewer_board()
    assert _enter_and_answer(engine, state, []) == 1
    assert not any(f.tapped for f in fishes)


def test_a_paid_doubler_offers_only_untapped_permanents_and_stops_when_none_are_left():
    engine, state, fishes = _brewer_board(fish=2)
    fishes[0].tapped = True
    assert _enter_and_answer(engine, state, fishes[1:]) == 2   # the one untapped Fish, then none left
    assert all(f.tapped for f in fishes)


def test_a_paid_doubler_with_nothing_to_tap_never_asks():
    engine, state, fishes = _brewer_board(fish=1)
    fishes[0].tapped = True
    entering = _put(state, "Entering", "", types="Artifact")
    life = state.player_by_id("p1").life
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", card_id=entering.card.id,
        object=entering.name, instance_id=entering.instance_id, object_types=sorted(entering.type_words),
    ))
    engine.resolve_until_stable()
    assert state.pending_choice is None
    assert state.player_by_id("p1").life - life == 1


# ---------------------------------------------------------------------------
# The clauses the residue cards also needed
# ---------------------------------------------------------------------------


def _specs(oracle, type_line="Enchantment"):
    result = parse_oracle(Card(id="X", name="X", type_line=type_line, oracle_text=oracle))
    assert result.modeled, oracle
    return result.specs


def test_an_all_colors_token_carries_the_five_colors():
    (spec,) = _specs("When ~ enters or attacks, create a 1/1 Fish creature token that's all colors.")
    assert spec.effects[0].params["colors"] == ["W", "U", "B", "R", "G"]


def test_an_all_colors_token_enters_with_every_color():
    engine, state = _engine()
    state.current_step = "main1"
    _put(state, "Maker", "Whenever an artifact enters, create a 1/1 Fish creature token that's all colors.")
    entering = _put(state, "Entering", "", types="Artifact")
    _fire_enter(engine, state, entering)
    fish = next(o for o in state.battlefield if o.name == "Fish")
    assert set(fish.card.color_identity) == {"W", "U", "B", "R", "G"}


def test_copy_it_under_a_cast_trigger_copies_the_cast_spell():
    (spec,) = _specs("Whenever you cast an Adventure spell, you may copy it. You may choose new targets for the copy.")
    assert spec.optional is True
    assert spec.effects[0].type == "copy_spell"
    assert spec.effects[0].params == {"spell_from_trigger_event": "instance_id"}


def test_a_conditional_grant_on_the_attached_creature_names_its_state():
    (spec,) = _specs("As long as equipped creature is attacking, it has first strike and must be blocked if able.",
                     "Artifact — Equipment")
    assert spec.effects[0].params == {
        "affects": "attached_permanent", "keywords": ["first_strike", "must_be_blocked"],
        "active_if": {"kind": "source_attacking", "of": "attached"},
    }


def test_an_attached_state_condition_does_not_reach_an_intervening_if():
    """Narcolepsy's "if enchanted creature is untapped, tap it" would tap the Aura, not the host."""
    result = parse_oracle(Card(
        id="X", name="X", type_line="Enchantment — Aura",
        oracle_text="Enchant creature\nAt the beginning of each upkeep, if enchanted creature is untapped, tap it."))
    assert result.modeled is False
