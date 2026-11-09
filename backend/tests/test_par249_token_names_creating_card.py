"""PAR-249 (RULE 201.5): a token's quoted ability that names the card that created it.

Deathpact Angel, Rekindling Phoenix, Sengir Nosferatu and Sound the Call use their exact Oracle text. Inside the
quotes two ``~`` have different referents: ``sacrifice this token`` / ``This token gets`` is the token, while
``named <Card>`` is the creating card's printed name. `normalize` therefore keeps that name as a ``<<literal>>``
(data, never code) and the token carries it in its own rules text. Every flow here creates the token by really
causing its creation, then uses the token's own ability on a real `GameEngine` (`GameSession.apply_action` for the
activations).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.services.game_session import GameSession

ANGEL = (
    "Flying\nWhen this creature dies, create a 1/1 white and black Cleric creature token. It has "
    '"{3}{W}{B}{B}, {T}, Sacrifice this token: Return a card named Deathpact Angel from your graveyard to the '
    'battlefield."'
)
PHOENIX = (
    "Flying\nWhen this creature dies, create a 0/1 red Elemental creature token with \"At the beginning of your "
    "upkeep, sacrifice this token and return target card named Rekindling Phoenix from your graveyard to the "
    'battlefield. It gains haste until end of turn."'
)
NOSFERATU = (
    "Flying\n{1}{B}, Exile this creature: Create a 1/2 black Bat creature token with flying. It has \"{1}{B}, "
    "Sacrifice this token: Return an exiled card named Sengir Nosferatu to the battlefield under its owner's "
    'control."'
)
SOUND = 'Create a 1/1 green Wolf creature token. It has "This token gets +1/+1 for each card named Sound the Call in each graveyard."'
CLONE = "You may have this creature enter as a copy of any creature on the battlefield."
CLONE_NAME = "Clone"


def _card(name, type_line, oracle, cost="{3}{W}{B}{B}", power=5, toughness=5):
    creature = "creature" in type_line.lower()
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, mana_cost_string=cost,
                converted_mana_cost=6, is_creature=creature, is_sorcery=type_line == "Sorcery", power=power if creature else None,
                toughness=toughness if creature else None)


def _session():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return GameSession(engine, starting_hand=0), engine, engine.state


def _put(state, card, owner="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    player = state.player_by_id(owner)
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    elif zone == Zone.GRAVEYARD:
        player.graveyard.append(obj)
    elif zone == Zone.EXILE:
        player.exile.append(obj)
    return obj


def _tokens(state):
    return [o for o in state.battlefield if o.is_token]


def _activate(session, engine, obj, owner="p1"):
    session.apply_action({"type": "activate_ability", "instance_id": obj.instance_id, "ability_index": 0}, owner)
    engine.resolve_until_stable()


def _mana(state, **pool):
    for color, amount in pool.items():
        state.player_by_id("p1").mana_pool.add(color.upper(), amount)


def _angel_token(session, engine, state):
    angel = _put(state, _card("Deathpact Angel", "Creature — Angel", ANGEL))
    engine.rules.destroy(angel)
    engine.resolve_until_stable()
    [token] = _tokens(state)
    token.summoning_sick = False  # the token's {T} needs it under control since the turn began (RULE 302.6)
    return angel, token


# --- parsing and normalization -------------------------------------------------------------------------------

@pytest.mark.parametrize("name,type_line,text", [
    ("Deathpact Angel", "Creature — Angel", ANGEL),
    ("Rekindling Phoenix", "Creature — Elemental Phoenix", PHOENIX),
    ("Sengir Nosferatu", "Creature — Vampire", NOSFERATU),
    ("Sound the Call", "Sorcery", SOUND),
])
def test_the_four_cards_are_modeled(name, type_line, text):
    assert parse_oracle(_card(name, type_line, text)).coverage == MODELED


def test_normalize_keeps_the_creating_cards_name_as_a_literal_only_inside_quotes():
    text = normalize(SOUND, "Sound the Call")
    assert "named <<sound the call>>" in text and text.count("~") == 1  # the token stays ``~``
    # Outside quotes "named <this card>" still means the card itself (Rite of Flame-style).
    assert "named ~" in normalize("Add {R} for each card named Rite of Flame in each graveyard.", "Rite of Flame")


def test_the_token_carries_the_name_not_the_creating_card():
    [spec] = [s for s in parse_oracle(_card("Sound the Call", "Sorcery", SOUND)).specs]
    [effect] = spec.effects
    assert "<<sound the call>>" in effect.params["oracle_text"] and "named ~" not in effect.params["oracle_text"]
    assert effect.params["token_name"] == "Wolf"  # the token is not renamed to the card


def test_a_name_with_unsafe_characters_is_not_claimed():
    # Fail closed: the literal grammar only reads a plain name, so anything else stays UNMODELED.
    text = 'Create a 1/1 green Wolf creature token. It has "This token gets +1/+1 for each card named Wolf; Pack in each graveyard."'
    assert parse_oracle(_card("Wolf; Pack", "Sorcery", text)).coverage != MODELED


# --- Deathpact Angel -----------------------------------------------------------------------------------------

def test_deathpact_angel_token_returns_a_card_named_deathpact_angel_paying_its_own_costs():
    session, engine, state = _session()
    angel, token = _angel_token(session, engine, state)
    assert angel.zone == Zone.GRAVEYARD and token.name == "Cleric"
    _mana(state, w=1, b=2, c=3)
    _activate(session, engine, token)
    assert angel.zone == Zone.BATTLEFIELD and angel in state.battlefield
    assert token not in state.battlefield  # the token itself was sacrificed (the cost's ``~``)
    assert state.player_by_id("p1").mana_pool.total() == 0


def test_deathpact_angel_ability_can_return_a_different_copy_and_refuses_other_names():
    session, engine, state = _session()
    angel, token = _angel_token(session, engine, state)
    # The creating card leaves the graveyard before the token is used (RULE 400.7); the name still decides.
    engine.rules.exile(angel)
    other = _put(state, _card("Deathpact Angel", "Creature — Angel", ANGEL), zone=Zone.GRAVEYARD)
    similar = _put(state, _card("Deathpact Angelic Host", "Creature — Angel", ""), zone=Zone.GRAVEYARD)
    elsewhere = _put(state, _card("Deathpact Angel", "Creature — Angel", ANGEL), owner="p2", zone=Zone.GRAVEYARD)
    _mana(state, w=1, b=2, c=3)
    _activate(session, engine, token)
    assert other.zone == Zone.BATTLEFIELD
    assert similar.zone == Zone.GRAVEYARD and elsewhere.zone == Zone.GRAVEYARD and angel.zone == Zone.EXILE


def test_deathpact_angel_with_no_matching_card_still_pays_but_returns_nothing():
    session, engine, state = _session()
    angel, token = _angel_token(session, engine, state)
    engine.rules.exile(angel)
    similar = _put(state, _card("Deathpact Angelic Host", "Creature — Angel", ""), zone=Zone.GRAVEYARD)
    _mana(state, w=1, b=2, c=3)
    _activate(session, engine, token)
    assert similar.zone == Zone.GRAVEYARD and token not in state.battlefield


def test_deathpact_angel_token_ability_is_undone_by_rewind():
    session, engine, state = _session()
    angel, token = _angel_token(session, engine, state)
    _mana(state, w=1, b=2, c=3)
    _activate(session, engine, token)
    session.rewind(1)
    state = session.engine.state
    assert any(o.is_token and o.name == "Cleric" for o in state.battlefield)
    assert [o.name for o in state.player_by_id("p1").graveyard] == ["Deathpact Angel"]


def test_a_clone_of_deathpact_angel_names_deathpact_angel():
    session, engine, state = _session()
    p1 = state.player_by_id("p1")
    _put(state, _card("Deathpact Angel", "Creature — Angel", ANGEL))
    clone_card = Card(id="clone", name=CLONE_NAME, type_line="Creature — Shapeshifter", oracle_text=CLONE,
                      is_creature=True, power=0, toughness=0, mana_cost_string="{3}{U}")
    clone = GameObject(clone_card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(clone)
    p1.hand.append(clone)
    p1.mana_pool.add_many({"U": 2, "C": 6})
    engine.cast_spell(p1, clone)
    engine.resolve_until_stable()
    option = next(o for o in state.pending_choice["options"] if o["id"] != "decline")
    engine.resolve_pending_choice(option["id"])
    assert clone.card.name == "Deathpact Angel"
    engine.rules.destroy(clone)
    engine.resolve_until_stable()
    [token] = [o for o in _tokens(state)]
    # RULE 707.2: the copy has the original's copiable name, so the token names "Deathpact Angel", never "Clone".
    assert "<<deathpact angel>>" in token.card.oracle_text and "clone" not in token.card.oracle_text


# --- Rekindling Phoenix --------------------------------------------------------------------------------------

def _phoenix_token(engine, state):
    phoenix = _put(state, _card("Rekindling Phoenix", "Creature — Elemental Phoenix", PHOENIX, "{2}{R}{R}", 4, 3))
    engine.rules.destroy(phoenix)
    engine.resolve_until_stable()
    [token] = _tokens(state)
    return phoenix, token


def _upkeep(engine, state):
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    engine.resolve_until_stable()
    while state.pending_choice and state.pending_choice.get("kind") == "trigger_target":
        engine.resolve_pending_choice(state.pending_choice["options"][0]["id"])  # RULE 603.3d: announce the target
        engine.resolve_until_stable()


def test_rekindling_phoenix_token_sacrifices_itself_and_returns_the_phoenix_with_haste():
    _, engine, state = _session()
    phoenix, token = _phoenix_token(engine, state)
    assert (token.power, token.toughness) == (0, 1)
    _upkeep(engine, state)
    assert token not in state.battlefield
    assert phoenix.zone == Zone.BATTLEFIELD
    engine.recompute_continuous_effects()
    assert "haste" in phoenix.granted_keywords  # "It" is the returned card


def test_rekindling_phoenix_haste_goes_to_the_returned_card_only():
    _, engine, state = _session()
    phoenix, token = _phoenix_token(engine, state)
    other = _put(state, _card("Bystander", "Creature — Bear", "", "{1}", 2, 2))
    _upkeep(engine, state)
    engine.recompute_continuous_effects()
    assert "haste" in phoenix.granted_keywords
    assert "haste" not in token.granted_keywords and "haste" not in other.granted_keywords
    # The token's ability is "sacrifice this token and return ..., it gains haste": the haste rides the returned card
    [spec] = [s for s in parse_oracle(_card("Rekindling Phoenix", "Creature — Elemental Phoenix", PHOENIX)).specs
              if s.ability_kind == "triggered"]
    [create] = spec.effects
    assert "gains haste" in create.params["oracle_text"] and "<<rekindling phoenix>>" in create.params["oracle_text"]


def test_rekindling_phoenix_token_does_nothing_without_a_card_named_phoenix_in_your_graveyard():
    _, engine, state = _session()
    phoenix, token = _phoenix_token(engine, state)
    engine.rules.exile(phoenix)
    decoy = _put(state, _card("Rekindling Phoenix Egg", "Creature — Bird", "", "{1}", 1, 1), zone=Zone.GRAVEYARD)
    foreign = _put(state, _card("Rekindling Phoenix", "Creature — Elemental Phoenix", PHOENIX, "{2}{R}{R}", 4, 3),
                   owner="p2", zone=Zone.GRAVEYARD)
    _upkeep(engine, state)
    # RULE 603.3d-style: no legal target, so the ability is not put on the stack and nothing is sacrificed.
    assert token in state.battlefield and decoy.zone == Zone.GRAVEYARD and foreign.zone == Zone.GRAVEYARD


def test_rekindling_phoenix_token_returns_another_card_with_that_name():
    _, engine, state = _session()
    phoenix, token = _phoenix_token(engine, state)
    engine.rules.exile(phoenix)  # the creating card changed zones before the upkeep
    second = _put(state, _card("Rekindling Phoenix", "Creature — Elemental Phoenix", PHOENIX, "{2}{R}{R}", 4, 3),
                  zone=Zone.GRAVEYARD)
    _upkeep(engine, state)
    assert second.zone == Zone.BATTLEFIELD and token not in state.battlefield and phoenix.zone == Zone.EXILE


# --- Sengir Nosferatu ----------------------------------------------------------------------------------------

def _bat(session, engine, state):
    nosferatu = _put(state, _card("Sengir Nosferatu", "Creature — Vampire", NOSFERATU, "{3}{B}{B}", 4, 4))
    _mana(state, b=2, c=0)
    session.apply_action({"type": "activate_ability", "instance_id": nosferatu.instance_id, "ability_index": 0}, "p1")
    engine.resolve_until_stable()
    [bat] = _tokens(state)
    return nosferatu, bat


def test_sengir_nosferatu_bat_returns_the_exiled_nosferatu_under_its_owners_control():
    session, engine, state = _session()
    nosferatu, bat = _bat(session, engine, state)
    assert nosferatu.zone == Zone.EXILE and (bat.power, bat.toughness) == (1, 2)
    bat.summoning_sick = False
    _mana(state, b=2)
    _activate(session, engine, bat)
    assert nosferatu.zone == Zone.BATTLEFIELD and bat not in state.battlefield
    assert nosferatu.controller_id == "p1" and nosferatu.owner_id == "p1"


def test_sengir_nosferatu_bat_chooses_among_exiled_copies_and_returns_one_to_its_owner():
    session, engine, state = _session()
    mine, bat = _bat(session, engine, state)
    theirs = _put(state, _card("Sengir Nosferatu", "Creature — Vampire", NOSFERATU, "{3}{B}{B}", 4, 4),
                  owner="p2", zone=Zone.EXILE)
    similar = _put(state, _card("Sengir Nosferatu's Heir", "Creature — Vampire", "", "{1}", 1, 1), zone=Zone.EXILE)
    bat.summoning_sick = False
    _mana(state, b=2)
    _activate(session, engine, bat)
    # The ruling: the returned card need not be the one that made the Bat, nor owned by the same player.
    pending = state.pending_choice
    assert pending["kind"] == "choose_objects"
    assert {o["instance_id"] for o in pending["options"]} == {mine.instance_id, theirs.instance_id}
    engine.resolve_pending_choice(next(o["id"] for o in pending["options"] if o["instance_id"] == theirs.instance_id))
    engine.resolve_until_stable()
    assert theirs.zone == Zone.BATTLEFIELD and theirs.controller_id == "p2"  # under its owner's control
    assert mine.zone == Zone.EXILE and similar.zone == Zone.EXILE and bat not in state.battlefield


def test_sengir_nosferatu_bat_ignores_a_face_down_exiled_card_and_a_misnamed_one():
    session, engine, state = _session()
    nosferatu, bat = _bat(session, engine, state)
    engine.rules.return_from_exile(nosferatu, nosferatu.zone_incarnation)
    engine.rules.exile(nosferatu)
    nosferatu.face_down_in_exile = True
    wrong = _put(state, _card("Sengir Vampire", "Creature — Vampire", "", "{1}", 1, 1), zone=Zone.EXILE)
    bat.summoning_sick = False
    _mana(state, b=2)
    _activate(session, engine, bat)
    assert nosferatu.zone == Zone.EXILE and wrong.zone == Zone.EXILE


def test_sengir_nosferatu_bat_activation_is_undone_by_rewind():
    session, engine, state = _session()
    nosferatu, bat = _bat(session, engine, state)
    bat.summoning_sick = False
    _mana(state, b=2)
    _activate(session, engine, bat)
    assert nosferatu.zone == Zone.BATTLEFIELD
    session.rewind(1)
    state = session.engine.state
    assert [o.name for o in state.player_by_id("p1").exile] == ["Sengir Nosferatu"]
    assert any(o.is_token and o.name == "Bat" for o in state.battlefield)


# --- Sound the Call ------------------------------------------------------------------------------------------

def test_sound_the_call_wolf_counts_cards_named_sound_the_call_in_every_graveyard():
    session, engine, state = _session()
    spell = _put(state, _card("Sound the Call", "Sorcery", SOUND, "{2}{G}"), zone=Zone.HAND)
    state.player_by_id("p1").hand.append(spell)
    state.player_by_id("p1").mana_pool.add_many({"G": 1, "C": 2})
    engine.cast_spell(state.player_by_id("p1"), spell)
    engine.resolve_until_stable()
    [wolf] = _tokens(state)
    engine.recompute_continuous_effects()
    # The resolved spell is in p1's graveyard, so the Wolf is 2/2 (the official ruling).
    assert spell.zone == Zone.GRAVEYARD and wolf.name == "Wolf" and (wolf.power, wolf.toughness) == (2, 2)
    _put(state, _card("Sound the Call", "Sorcery", SOUND, "{2}{G}"), owner="p2", zone=Zone.GRAVEYARD)
    _put(state, _card("Sound the Calls", "Sorcery", "", "{2}{G}"), zone=Zone.GRAVEYARD)
    _put(state, _card("Wolf", "Creature — Wolf", "", "{1}", 1, 1), zone=Zone.GRAVEYARD)
    engine.recompute_continuous_effects()
    assert (wolf.power, wolf.toughness) == (3, 3)


def test_sound_the_call_wolf_is_not_counting_a_card_named_wolf():
    session, engine, state = _session()
    spell = _put(state, _card("Sound the Call", "Sorcery", SOUND, "{2}{G}"), zone=Zone.HAND)
    state.player_by_id("p1").hand.append(spell)
    state.player_by_id("p1").mana_pool.add_many({"G": 1, "C": 2})
    engine.cast_spell(state.player_by_id("p1"), spell)
    engine.resolve_until_stable()
    [wolf] = _tokens(state)
    # A second Wolf token's own name never matches "Sound the Call", and the count survives the spell leaving.
    spell_card = spell
    engine.rules.exile(spell_card)
    engine.recompute_continuous_effects()
    assert (wolf.power, wolf.toughness) == (1, 1)


# --- the one other card the normalizer change touched --------------------------------------------------------

FOOD_FIGHT = (
    'Artifacts you control have "{2}, Sacrifice this artifact: It deals damage to any target equal to 1 plus the '
    'number of permanents named Food Fight you control."'
)


def test_food_fight_now_counts_permanents_named_food_fight_not_the_granted_artifact():
    # Before PAR-249 the quoted ``named ~`` read as the artifact the ability is granted to (a wrong referent).
    from mtg_analyzer.game import continuous

    result = parse_oracle(_card("Food Fight", "Enchantment", FOOD_FIGHT))
    assert result.coverage == MODELED
    [grant] = result.specs[0].effects
    [bound] = grant.params["grant_effects"]
    selector = bound["params"]["amount"]["selector"]
    assert selector == {"terms": [{"zone": "battlefield", "of": "you", "filter": {"name": "food fight"}}], "plus": 1}
    _, _, state = _session()
    _put(state, _card("Food Fight", "Enchantment", FOOD_FIGHT))
    _put(state, _card("Food Fight", "Enchantment", FOOD_FIGHT))
    _put(state, _card("Treasure Idol", "Artifact", "", "{1}"))
    assert continuous.count_selector(state, "p1", selector) == 3


# --- the <<name>> marker never reaches a player ---------------------------------------------------------------

def _strings(value, path="root"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{path}/{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")


def _assert_clean(session):
    """Walk the whole wire view and every legal action (all seats): no string may carry the marker."""
    for seat in ("p1", "p2"):
        for payload in (session.view(seat), session.legal_actions(seat)):
            for path, text in _strings(payload):
                assert "<<" not in text and ">>" not in text, (path, text)
    for path, text in _strings(session.observer_view()):
        assert "<<" not in text and ">>" not in text, (path, text)


def test_marker_is_hidden_for_deathpact_angel_at_every_moment():
    session, engine, state = _session()
    _, token = _angel_token(session, engine, state)
    _mana(state, w=1, b=2, c=3)
    _assert_clean(session)  # token on the battlefield, its activation offered
    offered = [a for a in session.legal_actions("p1") if a.get("instance_id") == token.instance_id]
    assert offered and "named deathpact angel" in offered[0]["description"]
    session.apply_action({"type": "activate_ability", "instance_id": token.instance_id, "ability_index": 0}, "p1")
    _assert_clean(session)  # ability on the stack
    assert "named deathpact angel" in session.view("p1")["state"]["stack"][0]["description"]
    assert "<<deathpact angel>>" in token.card.oracle_text  # the engine copy (used for re-parsing) is untouched


def test_marker_is_hidden_for_rekindling_phoenix_with_a_pending_trigger_target():
    session, engine, state = _session()
    _, token = _phoenix_token(engine, state)
    _assert_clean(session)
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    engine.resolve_until_stable()
    assert state.pending_choice and state.pending_choice["kind"] == "trigger_target"
    _assert_clean(session)
    assert "named rekindling phoenix" in session.view("p1")["pending_choice"]["prompt"]
    assert "<<rekindling phoenix>>" in state.pending_choice["prompt"]  # state itself is not rewritten


def test_marker_is_hidden_for_sengir_nosferatu_on_the_stack_and_in_a_choice():
    session, engine, state = _session()
    _, bat = _bat(session, engine, state)
    _assert_clean(session)
    _put(state, _card("Sengir Nosferatu", "Creature — Vampire", NOSFERATU, "{3}{B}{B}", 4, 4),
         owner="p2", zone=Zone.EXILE)
    bat.summoning_sick = False
    _mana(state, b=2)
    session.apply_action({"type": "activate_ability", "instance_id": bat.instance_id, "ability_index": 0}, "p1")
    _assert_clean(session)  # on the stack
    engine.resolve_until_stable()
    assert state.pending_choice and state.pending_choice["kind"] == "choose_objects"
    _assert_clean(session)  # option list open


def test_marker_is_hidden_for_sound_the_call_wolf_and_its_static_description():
    session, engine, state = _session()
    spell = _put(state, _card("Sound the Call", "Sorcery", SOUND, "{2}{G}"), zone=Zone.HAND)
    state.player_by_id("p1").hand.append(spell)
    state.player_by_id("p1").mana_pool.add_many({"G": 1, "C": 2})
    engine.cast_spell(state.player_by_id("p1"), spell)
    _assert_clean(session)  # spell on the stack
    engine.resolve_until_stable()
    _assert_clean(session)
    [wolf] = [o for o in session.view("p1")["state"]["battlefield"] if o["name"] == "Wolf"]
    assert "named sound the call" in wolf["oracle_text"]


def test_food_fight_parse_is_unchanged_and_its_view_is_clean():
    session, engine, state = _session()
    _put(state, _card("Food Fight", "Enchantment", FOOD_FIGHT))
    _put(state, _card("Treasure Idol", "Artifact", "", "{1}"))
    engine.recompute_continuous_effects()
    _mana(state, c=2)
    _assert_clean(session)
    result = parse_oracle(_card("Food Fight", "Enchantment", FOOD_FIGHT))
    [grant] = result.specs[0].effects
    selector = grant.params["grant_effects"][0]["params"]["amount"]["selector"]
    assert selector["terms"][0]["filter"] == {"name": "food fight"}
