"""BUG-57, milestone 2: a plain "target <X>" may be the ability's own source; "another"/"other" never is.

RULE 115.1: any object that fits the description is a legal choice. RULE 603.3d: when the source is the only legal
choice the trigger must still be put on the stack with it. RULE 109.5 ("another"/"other") is the parser's
``excludes_source`` marker, read per requirement. Auras (RULE 303.4d), Equipment (RULE 301.5c) and Fortifications
(RULE 301.6, 702.67a) keep refusing themselves, and reconfigure (RULE 702.151a) says "another" outright. Real
oracle text, a real `GameEngine`, and `GameSession.apply_action` for the flows.
"""

from __future__ import annotations

from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameSession

TAP_ETB = "When this creature enters, tap target creature."
KARGAN = (
    "Cowards can't block Warriors.\n{1}: Choose one that hasn't been chosen this turn —\n"
    "• This creature gets +1/+1 until end of turn.\n"
    "• Target creature becomes a Coward until end of turn.\n"
    "• Target Warrior gains trample until end of turn."
)
BREYA = (
    "When this creature enters, create a 1/1 colorless Thopter artifact creature token with flying.\n"
    "{T}, Sacrifice an artifact: Choose one —\n• Exile the top card of your library. Until the end of your next turn, "
    "you may play that card.\n• Target creature gets +2/+0 until end of turn."
)
TORALF = (
    "Trample\nWhenever a creature or planeswalker an opponent controls is dealt excess noncombat damage, "
    "Toralf deals damage equal to the excess to any target other than that permanent."
)
BLASTER = "{R}: ~ deals 6 damage to target creature."
RAZIA = "Flying, vigilance, haste\n{T}: The next 3 damage that would be dealt to target creature you control this turn is dealt to another target creature instead."
TRACKER = "{1}{G}, {T}: Target creature you control fights another target creature."
FACELESS = "Shadow\nWhen this creature enters, exile another target creature with shadow."
TIDEFORCE = "{U}, {T}: You may tap or untap another target creature."
AEGIS = "Flying\nWhen this creature enters, another target permanent gains indestructible for as long as you control this creature."
ICONIC_SHIELD = (
    'Equipped creature gets +1/+2 and has "Whenever this creature attacks, another target attacking creature gains '
    'indestructible until end of turn."\nEquip {3}'
)


def _card(name, type_line, oracle="", power=2, toughness=2, **kw):
    creature = "creature" in type_line.lower()
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, mana_cost_string="{1}",
                converted_mana_cost=1, is_creature=creature, power=power if creature else None,
                toughness=toughness if creature else None, **kw)


def _session():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return GameSession(engine, starting_hand=0), engine, engine.state


def _put(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _enter(engine, state, obj):
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id, card_id=obj.card.id, object=obj.name,
        instance_id=obj.instance_id, object_types=sorted(obj.type_words),
    ))
    engine.resolve_until_stable()


def _offered(pending):
    return {o.get("instance_id", o.get("id")) for o in pending["options"]}


def _specs(obj, index=0):
    """The requirements of ``obj``'s ``index``-th activated/triggered ability, as the engine announces them."""
    ability = (list(obj.activated_abilities) + list(obj.triggered_abilities))[index]
    return targeting.ability_target_specs(ability)


def _can_target(state, spec, source, who):
    return who.instance_id in {d["instance_id"] for d in targeting.legal_targets(state, "p1", spec, source=source)}


# -- the ticket's three reproductions ---------------------------------------------------------------------


def test_etb_tap_target_creature_offers_the_source_through_the_session():
    # RULE 115.1: "target creature" fits the entering creature itself.
    session, engine, state = _session()
    bear = _put(state, _card("Bear", "Creature — Bear"), "p2")
    tapper = _put(state, _card("Tapper", "Creature — Bear", TAP_ETB))
    _enter(engine, state, tapper)
    pending = state.pending_choice
    assert pending["kind"] == "trigger_target"
    assert _offered(pending) == {tapper.instance_id, bear.instance_id}
    chooses = [a for a in session.legal_actions("p1") if a.get("type") == "choose"]
    assert {str(tapper.instance_id), str(bear.instance_id)} <= {str(a["option_id"]) for a in chooses}
    session.apply_action({"type": "choose", "option_id": str(tapper.instance_id)}, "p1")
    engine.resolve_until_stable()
    assert tapper.tapped and not bear.tapped


def test_the_source_as_the_only_legal_target_still_goes_on_the_stack_targeting_itself():
    # RULE 603.3d: a trigger with a legal choice is put on the stack; here the source is the only one.
    session, engine, state = _session()
    tapper = _put(state, _card("Tapper", "Creature — Bear", TAP_ETB))
    _enter(engine, state, tapper)
    pending = state.pending_choice
    assert pending["kind"] == "trigger_target" and _offered(pending) == {tapper.instance_id}  # not dropped
    session.apply_action({"type": "choose", "option_id": str(tapper.instance_id)}, "p1")
    engine.resolve_until_stable()
    assert tapper.tapped


def test_kargan_intimidators_coward_and_trample_modes_can_target_itself():
    # Mode 1 "target creature" and mode 2 "target Warrior": Kargan is a Human Warrior, so both fit it.
    session, engine, state = _session()
    kargan = _put(state, _card("Kargan Intimidator", "Creature — Human Warrior", KARGAN))
    state.player_by_id("p1").mana_pool.add_many({"C": 2})
    # Trample first: "becomes a Coward" replaces Kargan's creature types, after which he is no Warrior.
    for mode in (2, 1):
        session.apply_action({"type": "activate_ability", "instance_id": kargan.instance_id, "ability_index": 0,
                              "mode": mode, "targets": [{"instance_id": kargan.instance_id}]}, "p1")
        engine.resolve_until_stable()
    assert "trample" in kargan.temp_keywords
    offers = [a for a in session.legal_actions("p1") if a.get("type") == "activate_ability"
              and a["instance_id"] == kargan.instance_id]
    assert all(a.get("mode") != 1 and a.get("mode") != 2 for a in offers)  # both chosen this turn


def test_breyas_apprentice_targets_itself_when_it_is_the_only_creature():
    session, engine, state = _session()
    apprentice = _put(state, _card("Breya's Apprentice", "Artifact Creature — Human Artificer", BREYA, 2, 2))
    fodder = _put(state, _card("Fodder", "Artifact"))
    assert [o for o in state.battlefield if o.is_creature] == [apprentice]
    session.apply_action({"type": "activate_ability", "instance_id": apprentice.instance_id, "ability_index": 0,
                          "mode": 1, "targets": [{"instance_id": apprentice.instance_id}],
                          "sacrifice_choice": fodder.instance_id}, "p1")
    engine.resolve_until_stable()
    assert apprentice.power == 4


def test_toralf_can_hit_himself_but_never_the_damaged_permanent():
    # RULE 115.1: "any target" fits Toralf; "other than that permanent" (RULE 109.2) leaves out the damaged one.
    session, engine, state = _session()
    toralf = _put(state, _card("Toralf, God of Fury", "Legendary Creature — God", TORALF, 5, 4))
    maker = _put(state, _card("Blaster", "Creature — Goblin", BLASTER))
    victim = _put(state, _card("Victim", "Creature — Bear", "", 2, 4), "p2")
    state.player_by_id("p1").mana_pool.add("R", 1)
    session.apply_action({"type": "activate_ability", "instance_id": maker.instance_id, "ability_index": 0,
                          "targets": [{"instance_id": victim.instance_id}]}, "p1")
    engine.resolve_until_stable()
    offered = _offered(state.pending_choice)
    assert toralf.instance_id in offered and victim.instance_id not in offered
    session.apply_action({"type": "choose", "option_id": str(toralf.instance_id)}, "p1")
    engine.resolve_until_stable()
    assert toralf.damage_marked == 2  # 6 damage on 4 toughness: the excess is 2


# -- per requirement ---------------------------------------------------------------------------------------


def test_razia_can_be_the_first_target_but_not_the_other_one():
    _, engine, state = _session()
    razia = _put(state, _card("Razia, Boros Archangel", "Legendary Creature — Angel", RAZIA, 3, 4))
    _put(state, _card("Bear", "Creature — Bear"))
    first, second = _specs(razia)
    assert _can_target(state, first, razia, razia)       # "target creature you control": Razia herself
    assert not _can_target(state, second, razia, razia)  # "another target creature"


def test_ulvenwald_tracker_can_fight_with_itself_but_the_second_target_is_another_creature():
    _, engine, state = _session()
    tracker = _put(state, _card("Ulvenwald Tracker", "Creature — Human Shaman", TRACKER))
    first, second = _specs(tracker)
    assert _can_target(state, first, tracker, tracker)
    assert not _can_target(state, second, tracker, tracker)
    assert second.distinct_from_others  # and never the first pick either (RULE 115.3 / existing constraint)


# -- "another" still refuses its source (triggered, activated, quoted/granted) -----------------------------


def test_another_target_etb_never_offers_its_source():
    session, engine, state = _session()
    shadow = _put(state, _card("Shadow Pal", "Creature — Nightmare", "Shadow"), "p2")
    devourer = _put(state, _card("Faceless Devourer", "Creature — Nightmare Horror", FACELESS))
    _enter(engine, state, devourer)
    pending = state.pending_choice
    # The Devourer's own text has the shadow keyword, so it fits "creature with shadow": RULE 109.5 keeps it out.
    assert devourer.instance_id not in (_offered(pending) if pending else set())
    assert pending is None or shadow.instance_id in _offered(pending)


def test_another_target_activated_never_offers_its_source():
    _, engine, state = _session()
    elemental = _put(state, _card("Tideforce Elemental", "Creature — Elemental", TIDEFORCE))
    bear = _put(state, _card("Bear", "Creature — Bear"))
    [spec] = _specs(elemental)
    assert spec.exclude_source
    assert not _can_target(state, spec, elemental, elemental) and _can_target(state, spec, elemental, bear)


def test_another_target_permanent_etb_never_offers_its_source():
    _, engine, state = _session()
    angel = _put(state, _card("Aegis Angel", "Creature — Angel", AEGIS))
    ring = _put(state, _card("Ring", "Artifact"))
    [spec] = _specs(angel)
    assert not _can_target(state, spec, angel, angel) and _can_target(state, spec, angel, ring)


def test_a_quoted_granted_another_target_never_offers_the_creature_it_is_granted_to():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.gate import parse_oracle
    from mtg_analyzer.parser.oracle.spec import EffectSpec

    _, engine, state = _session()
    shield = _card("Iconic Shield", "Artifact — Equipment", ICONIC_SHIELD)
    static = next(s for s in parse_oracle(shield).specs if s.ability_kind == "static")
    granted = next(e for e in static.effects if e.type == "grant_triggered_ability").params["grant_effects"]
    [effect] = build_effects([EffectSpec.from_dict(g) for g in granted])
    carrier = _put(state, _card("Carrier", "Creature — Bear"))
    fellow = _put(state, _card("Fellow", "Creature — Bear"))
    carrier.attacking = fellow.attacking = True
    assert not _can_target(state, effect.target_spec, carrier, carrier)
    assert _can_target(state, effect.target_spec, carrier, fellow)


# -- attachments keep refusing themselves ------------------------------------------------------------------


def test_an_equipment_creature_cannot_equip_itself_and_an_aura_cannot_enchant_itself():
    # RULE 301.5c / 303.4d / 301.6 / 702.151a: the attach abilities never offer their own source, even when the
    # Equipment/Aura is itself a creature on the battlefield (a plain `permanent` requirement).
    _, engine, state = _session()
    equipment = _put(state, _card("Living Blade", "Artifact Creature — Equipment", "Equip {1}", keywords=["Equip"]))
    bear = _put(state, _card("Bear", "Creature — Bear"))
    plain = targeting.TargetSpec(kind="permanent")
    assert not _can_target(state, plain, equipment, equipment) and _can_target(state, plain, equipment, bear)

    aura = _put(state, _card("Odd Aura", "Enchantment Creature — Aura", "Enchant creature", keywords=["Enchant"]))
    assert not _can_target(state, plain, aura, aura) and _can_target(state, plain, aura, bear)


def test_reconfigure_and_fortify_keep_refusing_their_own_source():
    # RULE 702.151a: reconfigure attaches "to another target creature you control"; RULE 702.67a / 301.6: a
    # Fortification attaches to a land (an animated one still cannot fortify itself).
    _, engine, state = _session()
    plain = targeting.TargetSpec(kind="permanent")
    reconf = _put(state, _card("Lizard Blades", "Artifact Creature — Equipment", "Reconfigure {2}", keywords=["Reconfigure"]))
    bear = _put(state, _card("Bear", "Creature — Bear"))
    assert reconf.parametric_keywords and "reconfigure" in reconf.parametric_keywords
    assert not _can_target(state, plain, reconf, reconf) and _can_target(state, plain, reconf, bear)

    fort = _put(state, _card("Living Bastion", "Artifact Land — Fortification", "Fortify {1}", keywords=["Fortify"]))
    land = _put(state, _card("Plains", "Basic Land — Plains", is_land=True))
    assert not _can_target(state, plain, fort, fort) and _can_target(state, plain, fort, land)


# -- clone / undo ------------------------------------------------------------------------------------------


def test_rewinding_restores_the_offer_that_includes_the_source():
    session, engine, state = _session()
    kargan = _put(state, _card("Kargan Intimidator", "Creature — Human Warrior", KARGAN))
    state.player_by_id("p1").mana_pool.add_many({"C": 1})
    session.apply_action({"type": "activate_ability", "instance_id": kargan.instance_id, "ability_index": 0,
                          "mode": 1, "targets": [{"instance_id": kargan.instance_id}]}, "p1")
    session.rewind(1)
    kargan = next(o for o in session.engine.state.battlefield if o.name == "Kargan Intimidator")
    offers = [a for a in session.legal_actions("p1") if a.get("type") == "activate_ability"
              and a["instance_id"] == kargan.instance_id and a.get("mode") == 1]
    assert offers


# -- cards activated from a graveyard ------------------------------------------------------------------------


def _in_graveyard(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.GRAVEYARD)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    state.player_by_id(owner).graveyard.append(obj)
    return obj


def _slimefoot_second_target_options(state, slimefoot):
    ability = next(a for a in slimefoot.activated_abilities if a.target_spec is not None
                   or targeting.ability_target_specs(a))
    spec = targeting.ability_target_specs(ability)[0]
    return {d["instance_id"] for d in targeting.legal_targets(state, "p1", spec, source=slimefoot)}


def test_slimefoot_and_squee_never_offers_itself_as_the_other_creature_card():
    # RULE 109.5: "up to one OTHER target creature card from your graveyard" -- the source card is in that graveyard,
    # so the graveyard branch must honour the marker (RULE 115.1 would otherwise let the card pick itself).
    _, engine, state = _session()
    slimefoot = _in_graveyard(state, _card("Slimefoot and Squee", "Legendary Creature — Fungus Saproling"))
    other = _in_graveyard(state, _card("Dead Bear", "Creature — Bear"))
    assert _slimefoot_second_target_options(state, slimefoot) == {other.instance_id}
    state.player_by_id("p1").graveyard.remove(other)
    assert _slimefoot_second_target_options(state, slimefoot) == set()  # optional target stays empty
