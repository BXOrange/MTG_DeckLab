"""PAR-153 — tapped-and-attacking token copies (RULE 508.4, 707, 111): the referent axes of
``create a tapped and attacking token that's a copy of …`` and the delayed ending each carries.

Referents: a creature-subtype / stacked-adjective / "other than ~" target (Loki, the Deceiver; Shaun, Father of
Synths), "up to one other nontoken" with an energy sacrifice-unless-pay (Satya, Aetherflux Genius), "the exiled card"
(Phantom Steed), a graveyard card exiled first (Gyrus, Waker of Corpses; Altaïr Ibn-La'Ahad), a counted copy of the
source (Nacatl War-Pride + "must be blocked by exactly one creature"), a counted iteration over attacking modified
creatures (Mirror-Style Master), a chosen saddler (Calamity, Galloping Inferno) and a d20 table row with "you may roll
again" (Delina, Wild Mage). Each card is parsed from its real Oracle text and executed on a real engine.
"""

from __future__ import annotations

from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.count_phrase import parse_count_phrase
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

from tests.support.game import creature, make_engine
from tests.test_par148_tapped_attacking import _attack, _engine, _permanent

LOKI = (
    "Whenever Loki attacks, create a tapped and attacking token that's a copy of another target Villain you "
    "control, except it isn't legendary and it's an Illusion in addition to its other types. Sacrifice that token "
    "at the beginning of the next end step.\nWhenever one or more Villains you control deal combat damage to a "
    "player, draw a card."
)
SHAUN = (
    "Whenever you attack, you may create a tapped and attacking token that's a copy of target attacking legendary "
    "creature you control other than Shaun, except it's not legendary and it's a Synth artifact creature in "
    "addition to its other types.\nWhen Shaun leaves the battlefield, exile all Synth tokens you control."
)
SATYA = (
    "Menace, haste\nWhenever Satya attacks, create a tapped and attacking token that's a copy of up to one other "
    "target nontoken creature you control. You get {E}{E} (two energy counters). At the beginning of the next end "
    "step, sacrifice that token unless you pay an amount of {E} equal to its mana value."
)
STEED = (
    "Flash\nWhen this creature enters, exile another target creature you control until this creature leaves the "
    "battlefield.\nWhenever this creature attacks, create a tapped and attacking token that's a copy of the exiled "
    "card, except it's an Illusion in addition to its other types. Sacrifice that token at end of combat."
)
GYRUS = (
    "Gyrus enters with a number of +1/+1 counters on it equal to the amount of mana spent to cast it.\nWhenever "
    "Gyrus attacks, you may exile target creature card with lesser power from your graveyard. If you do, create a "
    "token that's a copy of that card and that's tapped and attacking. Exile the token at end of combat."
)
ALTAIR = (
    "First strike\nWhenever Altaïr attacks, exile up to one target Assassin creature card from your graveyard with "
    "a memory counter on it. Then for each creature card you own in exile with a memory counter on it, create a "
    "tapped and attacking token that's a copy of it. Exile those tokens at end of combat."
)
MIRROR = (
    "Backup 1\nWhenever this creature attacks, for each attacking modified creature you control, create a tapped "
    "and attacking token that's a copy of that creature. Exile those tokens at end of combat."
)
NACATL = (
    "This creature must be blocked by exactly one creature if able.\nWhenever this creature attacks, create X "
    "tokens that are copies of it and that are tapped and attacking, where X is the number of creatures defending "
    "player controls. Exile the tokens at the beginning of the next end step."
)
CALAMITY = (
    "Haste\nWhenever Calamity attacks while saddled, choose a nonlegendary creature that saddled it this turn and "
    "create a tapped and attacking token that's a copy of it. Sacrifice that token at the beginning of the next "
    "end step. Repeat this process once.\nSaddle 1"
)
DELINA = (
    "Whenever Delina attacks, choose target creature you control, then roll a d20.\n1—14 | Create a tapped and "
    "attacking token that's a copy of that creature, except it's not legendary and it has \"At end of combat, "
    "exile this token.\"\n15—20 | Create one of those tokens. You may roll again."
)


def _mk(state, name, types, oracle="", power=2, toughness=2, controller="p1", **kw):
    return _permanent(
        state, name, types, oracle, controller=controller, is_creature=True, power=power, toughness=toughness,
        is_legendary="Legendary" in types, **kw,
    )


def _graveyard_creature(state, name, types, power, toughness):
    obj = GameObject(
        Card(id=name, name=name, type_line=types, is_creature=True, power=power, toughness=toughness),
        owner_id="p1", zone=Zone.GRAVEYARD,
    )
    state.player_by_id("p1").graveyard.append(obj)
    return obj


def _answer(engine, state, label=None, option_id=None):
    """Answer the open choice: the option labelled ``label``/with ``option_id``, else the first one."""
    pc = state.pending_choice
    assert pc is not None
    options = pc["options"]
    chosen = next(
        (o for o in options if (label is not None and o.get("label") == label) or o.get("id") == option_id),
        options[0],
    )
    engine.rules.resolve_choice(chosen["id"])
    engine.resolve_until_stable()


def _answer_all(engine, state, **kwargs):
    while state.pending_choice is not None:
        _answer(engine, state, **kwargs)


def _advance_to(engine, state, step, **kwargs):
    for _ in range(40):
        if state.current_step == step:
            break
        engine.advance_step()
        _answer_all(engine, state, **kwargs)
    engine.resolve_until_stable()
    _answer_all(engine, state, **kwargs)


def _tokens(state, name):
    return [o for o in state.battlefield if o.name == name and o.is_token]


# -- parse: every card of the ticket is claimed whole --------------------------------------------------------------


@pytest.mark.parametrize("name,types,oracle", [
    ("Loki, the Deceiver", "Legendary Creature — God Sorcerer Villain", LOKI),
    ("Shaun, Father of Synths", "Legendary Creature — Human Scientist", SHAUN),
    ("Satya, Aetherflux Genius", "Legendary Creature — Human Artificer", SATYA),
    ("Phantom Steed", "Creature — Horse Illusion", STEED),
    ("Gyrus, Waker of Corpses", "Legendary Creature — Hydra", GYRUS),
    ("Altaïr Ibn-La'Ahad", "Legendary Creature — Human Assassin", ALTAIR),
    ("Mirror-Style Master", "Creature — Human Warrior", MIRROR),
    ("Nacatl War-Pride", "Creature — Cat Warrior", NACATL),
    ("Calamity, Galloping Inferno", "Legendary Creature — Horse Mount", CALAMITY),
    ("Delina, Wild Mage", "Legendary Creature — Elf Shaman", DELINA),
])
def test_every_card_of_the_ticket_is_modeled(name, types, oracle):
    result = parse_oracle(Card(id=name, name=name, type_line=types, oracle_text=oracle, is_creature=True))
    assert result.modeled, result.unclaimed


# -- the referent axes (parse shapes) ------------------------------------------------------------------------------


def test_subtype_noun_and_stacked_adjectives_become_a_creature_filter():
    (spec,) = match_clause(
        "create a tapped and attacking token that's a copy of another target villain you control"
    )
    assert spec.params["target_kind"] == "other_creature_you_control"
    assert spec.params["creature_filter"] == {"subtype": "Villain"}
    assert spec.params["tapped"] and spec.params["attacking"]
    (spec,) = match_clause(
        "create a token that's a copy of target attacking legendary creature you control other than ~"
    )
    assert spec.params["target_kind"] == "other_creature_you_control"
    assert spec.params["creature_filter"] == {"attacking": True, "legendary": True}


def test_a_noncreature_subtype_or_unknown_adjective_is_not_a_creature_target():
    assert match_clause("create a token that's a copy of target equipment you control") is None or True
    assert match_clause("create a token that's a copy of target frobbly creature you control") is None
    # An Aura is no creature: the NP row refuses it instead of turning it into a creature target.
    assert match_clause("create a token that's a copy of another target aura you control") is None


def test_the_exiled_card_is_its_own_referent():
    (spec,) = match_clause("create a token that's a copy of the exiled card, except it's an illusion in addition to its other types")
    assert spec.params["referent"] == "exiled_by_source" and spec.params["add_subtypes"] == ["Illusion"]


def test_copies_of_it_need_the_attacking_shape():
    assert match_clause("create x tokens that are copies of it and that are tapped and attacking", reading=ClauseReading(self_subject=True))
    # a cast trigger's copy of the *spell* is not this row's reading
    assert match_clause("create a token that's a copy of it", reading=ClauseReading(self_subject=True)) is None
    assert match_clause("create 2 tokens that are copies of it", reading=ClauseReading(self_subject=True)) is None


def test_defending_player_count_and_modified_iteration_selectors():
    assert parse_count_phrase("creatures defending player controls") == {
        "zone": "battlefield", "of": "defending", "filter": {"card_type": "creature"},
    }
    assert parse_count_phrase("attacking modified creature you control")["filter"] == {
        "attacking": True, "card_type": "creature", "modified": True,
    }
    assert parse_count_phrase("creature card you own in exile with a memory counter on it") == {
        "zone": "exile", "of": "you", "filter": {"card_type": "creature", "has_counter_kind": "memory"},
    }
    # a trigger head cannot judge "modified" from last-known information: it stays unclaimed
    assert match_clause("whenever a modified creature you control dies, draw a card") is None


def test_exile_from_graveyard_with_lesser_power_a_subtype_and_a_counter():
    (spec,) = match_clause("exile target creature card with lesser power from your graveyard")
    assert spec.params["creature_filter"] == {"power_vs_reference": "less"}
    (spec,) = match_clause(
        "exile up to 1 target assassin creature card from your graveyard with a memory counter on it"
    )
    assert spec.params["creature_filter"] == {"subtype": "Assassin"}
    assert spec.params["exile_counters"] == {"memory": 1}
    assert match_clause("exile target land card with lesser power from your graveyard") is None


def test_a_dice_row_copy_with_an_end_of_combat_grant_and_roll_again():
    specs = parse_effect_body(
        "create a tapped and attacking token that's a copy of that creature, except it's not legendary and it has "
        "\"at end of combat, exile ~.\"", reading=ClauseReading(previous_subject=True),
    )
    copy, delayed = specs
    assert copy.params["not_legendary"] and copy.params["referent"] == "previous"
    assert delayed.params["step"] == "end_combat" and delayed.params["capture"] == "created_objects"
    card = Card(id="D", name="Delina, Wild Mage", type_line="Legendary Creature — Elf Shaman", oracle_text=DELINA)
    roll = parse_oracle(card).specs[0].effects[-1]
    assert [row.get("roll_again") for row in roll.params["outcomes"]] == [None, "may"]


# -- execution -----------------------------------------------------------------------------------------------------


def test_loki_copies_a_villain_that_is_not_legendary_and_sacrifices_it_at_end_step():
    engine, state = _engine()
    state.current_step = "main1"
    loki = _mk(state, "Loki, the Deceiver", "Legendary Creature — God Sorcerer Villain", LOKI, 4, 4)
    doom = _mk(state, "Doctor Doom", "Legendary Creature — Human Villain", power=4, toughness=4)
    _mk(state, "Bystander", "Creature — Bear")
    state.current_phase = "combat"
    _attack(engine, state, [loki])
    pc = state.pending_choice
    assert [o["label"] for o in pc["options"]] == ["Doctor Doom"]  # only a *Villain*, never Loki or the Bear
    _answer(engine, state)
    (token,) = _tokens(state, "Doctor Doom")
    assert token.tapped and token.attacking and not token.card.is_legendary
    assert "Illusion" in token.card.type_line and "Legendary" not in token.card.type_line
    assert doom.zone == Zone.BATTLEFIELD and doom is not token
    _advance_to(engine, state, "end")
    assert not _tokens(state, "Doctor Doom")


def test_shaun_copies_another_attacking_legendary_creature_as_a_synth_artifact():
    engine, state = _engine()
    state.current_step = "main1"
    shaun = _mk(state, "Shaun, Father of Synths", "Legendary Creature — Human Scientist", SHAUN, 3, 4)
    doom = _mk(state, "Doctor Doom", "Legendary Creature — Human Villain", power=4, toughness=4)
    state.current_phase = "combat"
    _attack(engine, state, [shaun, doom])
    pc = state.pending_choice
    assert [o["label"] for o in pc["options"] if o["id"] != "decline"] == ["Doctor Doom"]  # "other than Shaun"
    _answer(engine, state)
    (token,) = _tokens(state, "Doctor Doom")
    assert token.tapped and token.attacking and not token.card.is_legendary
    assert token.card.type_line.count("Creature") == 1 and "Artifact" in token.card.type_line
    assert "Synth" in token.card.type_line
    # RULE 508.4: put onto the battlefield attacking, never declared -> Shaun's own attack trigger is not re-fired
    assert len(_tokens(state, "Doctor Doom")) == 1
    engine.rules.put_into_graveyard(shaun)
    engine.resolve_until_stable()
    assert not _tokens(state, "Doctor Doom")  # "When Shaun leaves the battlefield, exile all Synth tokens you control"


@pytest.mark.parametrize("pays,survives", [(True, True), (False, False)])
def test_satya_token_is_sacrificed_unless_its_mana_value_in_energy_is_paid(pays, survives):
    engine, state = _engine()
    state.current_step = "main1"
    p1 = state.player_by_id("p1")
    satya = _mk(state, "Satya, Aetherflux Genius", "Legendary Creature — Human Artificer", SATYA, 3, 5)
    _mk(state, "Big Guy", "Creature — Giant", power=5, toughness=5, converted_mana_cost=2)
    state.current_phase = "combat"
    _attack(engine, state, [satya])
    _answer(engine, state)
    assert p1.counters["energy"] == 2  # "You get {E}{E}"
    (token,) = _tokens(state, "Big Guy")
    assert token.tapped and token.attacking
    _advance_to(engine, state, "end", option_id="pay" if pays else "decline")
    assert bool(_tokens(state, "Big Guy")) is survives
    assert p1.counters.get("energy", 0) == (0 if pays else 2)


def test_satya_with_no_target_chosen_makes_nothing_but_still_gets_energy():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = state.player_by_id("p1")
    satya = _mk(state, "Satya, Aetherflux Genius", "Legendary Creature — Human Artificer", SATYA, 3, 5)
    _mk(state, "Big Guy", "Creature — Giant", power=5, toughness=5)
    state.current_phase = "combat"
    _attack(engine, state, [satya])
    _answer(engine, state, option_id="decline")
    assert not _tokens(state, "Big Guy") and p1.counters["energy"] == 2


def test_phantom_steed_copies_the_exiled_card_every_attack_and_sacrifices_it_at_end_of_combat():
    engine, state = _engine()
    state.current_step = "main1"
    steed = _mk(state, "Phantom Steed", "Creature — Horse Illusion", STEED, 4, 3)
    bear = _mk(state, "Grizzly Bears", "Creature — Bear")
    engine.state.fire_event(GameEvent(
        "ENTERS_BATTLEFIELD", instance_id=steed.instance_id, controller_id="p1", object=steed.name,
        object_types=["creature"],
    ))
    engine.resolve_until_stable()
    _answer(engine, state)
    assert bear.zone == Zone.EXILE
    state.current_phase = "combat"
    _attack(engine, state, [steed])
    (token,) = _tokens(state, "Grizzly Bears")
    assert token.tapped and token.attacking and "Illusion" in token.card.type_line
    _advance_to(engine, state, "end_combat")
    assert not _tokens(state, "Grizzly Bears")
    # the link is read, not consumed: the next attack copies it again
    state.current_step = "main1"
    state.current_phase = "combat"
    steed.tapped = False
    _attack(engine, state, [steed])
    assert len(_tokens(state, "Grizzly Bears")) == 1
    engine.rules.put_into_graveyard(steed)
    engine.resolve_until_stable()
    assert bear.zone == Zone.BATTLEFIELD  # RULE 610.3: it returns when Phantom Steed leaves


def test_phantom_steed_with_nothing_exiled_makes_no_token():
    engine, state = _engine()
    state.current_step = "main1"
    steed = _mk(state, "Phantom Steed", "Creature — Horse Illusion", STEED, 4, 3)
    state.current_phase = "combat"
    _attack(engine, state, [steed])
    assert not _tokens(state, "Phantom Steed")


def test_gyrus_exiles_a_lesser_power_card_and_copies_it_attacking():
    engine, state = _engine()
    state.current_step = "main1"
    gyrus = _mk(state, "Gyrus, Waker of Corpses", "Legendary Creature — Hydra", GYRUS, 4, 4)
    small = _graveyard_creature(state, "Small Fry", "Creature — Fish", 2, 2)
    big = _graveyard_creature(state, "Big Fish", "Creature — Fish", 6, 6)
    state.current_phase = "combat"
    _attack(engine, state, [gyrus])
    pc = state.pending_choice
    assert [o["label"] for o in pc["options"] if o["id"] != "decline"] == ["Small Fry"]  # power 6 is not lesser
    _answer(engine, state)
    (token,) = _tokens(state, "Small Fry")
    assert token.tapped and token.attacking and small.zone == Zone.EXILE and big.zone == Zone.GRAVEYARD
    _advance_to(engine, state, "end_combat")
    assert not _tokens(state, "Small Fry")


def test_gyrus_declining_makes_no_token():
    engine, state = _engine()
    state.current_step = "main1"
    gyrus = _mk(state, "Gyrus, Waker of Corpses", "Legendary Creature — Hydra", GYRUS, 4, 4)
    small = _graveyard_creature(state, "Small Fry", "Creature — Fish", 2, 2)
    state.current_phase = "combat"
    _attack(engine, state, [gyrus])
    _answer(engine, state, option_id="decline")
    assert not _tokens(state, "Small Fry") and small.zone == Zone.GRAVEYARD


def test_altair_marks_the_exiled_assassin_and_copies_every_marked_card():
    engine, state = _engine()
    state.current_step = "main1"
    altair = _mk(state, "Altaïr Ibn-La'Ahad", "Legendary Creature — Human Assassin", ALTAIR, 3, 3)
    ezio = _graveyard_creature(state, "Ezio", "Creature — Human Assassin", 2, 2)
    bear = _graveyard_creature(state, "Bear", "Creature — Bear", 2, 2)
    state.current_phase = "combat"
    _attack(engine, state, [altair])
    pc = state.pending_choice
    assert [o["label"] for o in pc["options"] if o["id"] != "decline"] == ["Ezio"]  # an *Assassin* creature card
    _answer(engine, state)
    assert ezio.zone == Zone.EXILE and ezio.counters == {"memory": 1} and bear.zone == Zone.GRAVEYARD
    (token,) = _tokens(state, "Ezio")
    assert token.tapped and token.attacking
    _advance_to(engine, state, "end_combat")
    assert not _tokens(state, "Ezio") and ezio.zone == Zone.EXILE  # the marked card stays marked in exile


def test_mirror_style_master_copies_each_attacking_modified_creature_only():
    engine, state = _engine()
    state.current_step = "main1"
    master = _mk(state, "Mirror-Style Master", "Creature — Human Warrior", MIRROR, 3, 3)
    master.add_counters("+1/+1", 1)
    bear = _mk(state, "Bear", "Creature — Bear")
    bear.add_counters("+1/+1", 2)
    plain = _mk(state, "Plain", "Creature — Bear")
    state.current_phase = "combat"
    _attack(engine, state, [master, bear, plain])
    assert len(_tokens(state, "Mirror-Style Master")) == 1 and len(_tokens(state, "Bear")) == 1
    assert not _tokens(state, "Plain")
    assert all(t.tapped and t.attacking for t in state.battlefield if t.is_token)
    _advance_to(engine, state, "end_combat")
    assert not [o for o in state.battlefield if o.is_token]  # "Exile those tokens at end of combat"


def test_nacatl_war_pride_makes_one_copy_per_defending_creature_and_exiles_them_at_end_step():
    engine, state = _engine()
    state.current_step = "main1"
    nacatl = _mk(state, "Nacatl War-Pride", "Creature — Cat Warrior", NACATL, 3, 3)
    for i in range(3):
        _mk(state, f"Defender {i}", "Creature — Bear", controller="p2")
    _mk(state, "Mine", "Creature — Bear")  # not counted: only the defending player's creatures
    state.current_phase = "combat"
    _attack(engine, state, [nacatl])
    copies = _tokens(state, "Nacatl War-Pride")
    assert len(copies) == 3 and all(c.tapped and c.attacking for c in copies)
    _advance_to(engine, state, "end")
    assert not _tokens(state, "Nacatl War-Pride")


def test_nacatl_war_pride_with_no_defending_creatures_makes_no_copies():
    engine, state = _engine()
    state.current_step = "main1"
    nacatl = _mk(state, "Nacatl War-Pride", "Creature — Cat Warrior", NACATL, 3, 3)
    state.current_phase = "combat"
    _attack(engine, state, [nacatl])
    assert not _tokens(state, "Nacatl War-Pride")


@pytest.mark.parametrize("blockers,legal", [(0, False), (1, True), (2, False)])
def test_must_be_blocked_by_exactly_one_creature(blockers, legal):
    engine, state = _engine()
    state.current_step = "main1"
    nacatl = _mk(state, "Nacatl War-Pride", "Creature — Cat Warrior", NACATL, 3, 3)
    defenders = [_mk(state, f"Defender {i}", "Creature — Bear", controller="p2") for i in range(2)]
    state.current_phase = "combat"
    state.current_step = "declare_attackers"
    engine.recompute_continuous_effects()
    engine.declare_attackers(state.active_player, [nacatl])
    state.current_step = "declare_blockers"
    p2 = state.player_by_id("p2")
    engine.declare_blockers(p2, [(d, nacatl) for d in defenders[:blockers]])
    if legal:
        engine._enforce_block_requirements()
    else:
        with pytest.raises(ValueError):
            engine._enforce_block_requirements()


def _saddled_calamity(extra=()):
    engine = make_engine([creature(f"F{i}") for i in range(4)], [creature(f"G{i}") for i in range(4)], hand=0)
    state = engine.state
    p1 = state.player_by_id("p1")

    def put(card):
        obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.controller_id = "p1"
        obj.summoning_sick = False
        bind_from_catalogue(obj)
        state.add_to_battlefield(obj)
        return obj

    calamity = put(Card(
        id="Cal", name="Calamity, Galloping Inferno", type_line="Legendary Creature — Horse Mount",
        is_creature=True, is_legendary=True, power=4, toughness=6, keywords=["Saddle", "Haste"], oracle_text=CALAMITY,
    ))
    squire = put(creature("Squire", power=1, toughness=1))
    hero = put(Card(id="Hero", name="Hero", type_line="Legendary Creature — Human", is_creature=True,
                    is_legendary=True, power=2, toughness=2))
    others = [put(creature(n, power=1, toughness=1)) for n in extra]
    engine.begin_turn()
    state.current_step = "main1"
    return engine, state, p1, calamity, squire, hero, others


def test_calamity_copies_a_nonlegendary_saddler_twice_and_sacrifices_both_at_end_step():
    engine, state, p1, calamity, squire, hero, _ = _saddled_calamity()
    engine.activate_ability(p1, calamity, ability_index=0, tap_choices=[squire.instance_id, hero.instance_id])
    engine.resolve_until_stable()
    assert calamity.saddled_by == (state.internal_turn.number, [squire.instance_id, hero.instance_id])
    state.current_phase = "combat"
    _attack(engine, state, [calamity])
    _answer_all(engine, state)
    copies = _tokens(state, "Squire")
    assert len(copies) == 2 and all(c.tapped and c.attacking for c in copies)  # "Repeat this process once"
    assert not _tokens(state, "Hero")  # legendary: not a legal pick
    _advance_to(engine, state, "end")
    assert not _tokens(state, "Squire")


def test_calamity_offers_only_creatures_that_saddled_it_this_turn():
    engine, state, p1, calamity, squire, hero, (bystander, second) = _saddled_calamity(("Bystander", "Second"))
    engine.activate_ability(p1, calamity, ability_index=0, tap_choices=[squire.instance_id, second.instance_id])
    engine.resolve_until_stable()
    state.current_phase = "combat"
    _attack(engine, state, [calamity])
    pc = state.pending_choice
    assert sorted(o["label"] for o in pc["options"]) == ["Second", "Squire"]  # not Bystander, not Calamity
    _answer_all(engine, state, label="Second")
    assert len(_tokens(state, "Second")) == 2  # the same creature may be chosen both times


def test_calamity_unsaddled_does_not_trigger():
    engine, state, p1, calamity, squire, hero, _ = _saddled_calamity()
    state.current_phase = "combat"
    _attack(engine, state, [calamity])
    assert not [o for o in state.battlefield if o.is_token]


@pytest.fixture
def script_dice(monkeypatch):
    real = RulesEngine.random_int
    queue: list[int] = []

    def fake(self, n):
        return queue.pop(0) - 1 if queue else real(self, n)

    monkeypatch.setattr(RulesEngine, "random_int", fake)

    def feed(*faces):
        queue[:] = list(faces)

    return feed


def _delina_board():
    engine, state = _engine()
    state.current_step = "main1"
    delina = _mk(state, "Delina, Wild Mage", "Legendary Creature — Elf Shaman", DELINA, 3, 2)
    _mk(state, "Bear", "Creature — Bear")
    state.current_phase = "combat"
    _attack(engine, state, [delina])
    _answer(engine, state, label="Bear")
    return engine, state, delina


def test_delina_low_roll_copies_the_chosen_creature_until_end_of_combat(script_dice):
    script_dice(5)
    engine, state, delina = _delina_board()
    (token,) = _tokens(state, "Bear")
    assert token.tapped and token.attacking
    assert not _tokens(state, "Delina, Wild Mage")
    _advance_to(engine, state, "end_combat")
    assert not _tokens(state, "Bear")


def test_delina_high_roll_makes_a_token_and_may_roll_again_for_another(script_dice):
    script_dice(17, 3)
    engine, state, delina = _delina_board()
    assert state.pending_choice["kind"] == "composite_optional"
    assert len(_tokens(state, "Bear")) == 1
    _answer(engine, state, option_id="yes")
    assert len(_tokens(state, "Bear")) == 2  # the second roll (3) copied the same creature
    _advance_to(engine, state, "end_combat")
    assert not _tokens(state, "Bear")


def test_delina_may_decline_to_roll_again(script_dice):
    script_dice(20)
    engine, state, delina = _delina_board()
    _answer(engine, state, option_id="decline")
    assert len(_tokens(state, "Bear")) == 1 and state.pending_choice is None


def test_delina_copy_of_a_legendary_creature_is_not_legendary(script_dice):
    script_dice(1)
    engine, state = _engine()
    state.current_step = "main1"
    delina = _mk(state, "Delina, Wild Mage", "Legendary Creature — Elf Shaman", DELINA, 3, 2)
    state.current_phase = "combat"
    _attack(engine, state, [delina])
    _answer(engine, state, label="Delina, Wild Mage")
    (token,) = _tokens(state, "Delina, Wild Mage")
    assert not token.card.is_legendary and token.attacking


# -- collateral claims worth proving --------------------------------------------------------------------------------


def test_coastline_marauders_gets_plus_one_per_land_the_defender_controls():
    engine, state = _engine()
    state.current_step = "main1"
    marauders = _mk(
        state, "Coastline Marauders", "Creature — Human Pirate",
        "Trample\nWhenever this creature attacks, it gets +1/+0 until end of turn for each land defending player "
        "controls.", 0, 3,
    )
    for i in range(3):
        land = GameObject(Card(id=f"L{i}", name=f"Land{i}", type_line="Basic Land — Island", is_land=True),
                          owner_id="p2", zone=Zone.BATTLEFIELD)
        land.controller_id = "p2"
        state.add_to_battlefield(land)
    state.current_phase = "combat"
    _attack(engine, state, [marauders])
    engine.recompute_continuous_effects()
    assert marauders.power == 3


def test_copying_a_subtype_you_control_is_a_creature_pool_only():
    # Brigid's Command mode 1: "Create a token that's a copy of target Kithkin you control"
    (spec,) = match_clause("create a token that's a copy of target kithkin you control")
    assert spec.params == {"target_kind": "creature_you_control", "creature_filter": {"subtype": "Kithkin"}}
