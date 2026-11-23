"""PAR-322: Delirium / Fateful hour / Spell mastery paragraphs on an instant or
sorcery continue the spell's previous instruction (RULE 207.2c: an ability word
has no rules meaning, so the paragraph is one more instruction of the same spell
ability, RULE 608.2c).  Every card below is cast and resolved on a real engine
with the ability word's condition true and false.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.gate import _SPELL_RIDER_PARAGRAPH_RE

#: Fateful hour threshold (the printed "5 or less life").
FATEFUL_LIFE = 5
#: Plenty of mana of every colour so payment is never what a test measures.
POOL = 30
LIBRARY = 10

# Oracle text as printed (reminder text stripped by the parser).
CARDS = {
    "Calculated Dismissal": ("{2}{U}", "Instant",
        "Counter target spell unless its controller pays {3}.\nSpell mastery — If there are two or more instant and/or sorcery cards in your graveyard, scry 2."),
    "Clinging Mists": ("{2}{G}", "Instant",
        "Prevent all combat damage that would be dealt this turn.\nFateful hour — If you have 5 or less life, tap all attacking creatures. Those creatures don't untap during their controller's next untap step."),
    "Dark Petition": ("{3}{B}{B}", "Sorcery",
        "Search your library for a card, put that card into your hand, then shuffle.\nSpell mastery — If there are two or more instant and/or sorcery cards in your graveyard, add {B}{B}{B}."),
    "Exquisite Firecraft": ("{1}{R}{R}", "Sorcery",
        "Exquisite Firecraft deals 4 damage to any target.\nSpell mastery — If there are two or more instant and/or sorcery cards in your graveyard, this spell can't be countered."),
    "Gideon's Phalanx": ("{5}{W}{W}", "Instant",
        "Create four 2/2 white Knight creature tokens with vigilance.\nSpell mastery — If there are two or more instant and/or sorcery cards in your graveyard, creatures you control gain indestructible until end of turn."),
    "Impossible Inferno": ("{4}{R}", "Instant",
        "Impossible Inferno deals 6 damage to target creature.\nDelirium — If there are four or more card types among cards in your graveyard, exile the top card of your library. You may play it until the end of your next turn."),
    "Spell Snuff": ("{1}{U}{U}", "Instant",
        "Counter target spell.\nFateful hour — If you have 5 or less life, draw a card."),
    "Unholy Hunger": ("{3}{B}{B}", "Instant",
        "Destroy target creature.\nSpell mastery — If there are two or more instant and/or sorcery cards in your graveyard, you gain 2 life."),
    "Violent Urge": ("{R}", "Instant",
        "Target creature gets +1/+0 and gains first strike until end of turn.\nDelirium — If there are four or more card types among cards in your graveyard, that creature gains double strike until end of turn."),
    "Break of Day": ("{1}{W}", "Instant",
        "Creatures you control get +1/+1 until end of turn.\nFateful hour — If you have 5 or less life, those creatures gain indestructible until end of turn."),
    "Send to Sleep": ("{1}{U}", "Instant",
        "Tap up to two target creatures.\nSpell mastery — If there are two or more instant and/or sorcery cards in your graveyard, those creatures don't untap during their controllers' next untap steps."),
    "Ravaging Blaze": ("{X}{R}{R}", "Instant",
        "Ravaging Blaze deals X damage to target creature.\nSpell mastery — If there are two or more instant and/or sorcery cards in your graveyard, Ravaging Blaze also deals X damage to that creature's controller."),
}


def _card(name: str) -> Card:
    cost, kind, text = CARDS[name]
    return Card(id=name, name=name, type_line=kind, mana_cost_string=cost,
                is_instant=kind == "Instant", is_sorcery=kind == "Sorcery",
                oracle_text=text)


def _filler(n):
    return Card(id=f"f{n}", name=f"Filler {n}", type_line="Creature — Bear", is_creature=True,
                power=2, toughness=2)


def _setup(name, *, mastery=False, delirium=False, low_life=False):
    engine = GameEngine.new_game(
        [("p1", "A", [_filler(i) for i in range(LIBRARY)]),
         ("p2", "B", [_filler(i) for i in range(LIBRARY)])],
        starting_life=20, starting_hand=0)
    state = engine.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    obj = GameObject(_card(name), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    def grave(card):
        g = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
        p1.graveyard.append(g)
    if mastery:
        for i in range(2):
            grave(Card(id=f"gi{i}", name=f"GI{i}", type_line="Instant", is_instant=True))
    if delirium:
        for i, (tl, kw) in enumerate([("Instant", "is_instant"), ("Sorcery", "is_sorcery"),
                                      ("Land", "is_land"), ("Artifact", "is_artifact_unused")]):
            grave(Card(id=f"gd{i}", name=f"GD{i}", type_line=tl, **({kw: True} if kw.startswith("is_") and kw != "is_artifact_unused" else {})))
    if low_life:
        p1.life = FATEFUL_LIFE
    engine.start()
    while state.current_phase != "precombat_main":
        engine.advance_step()
    for colour in "WUBRGC":
        p1.mana_pool.add(colour, POOL)
    return engine, state, p1, p2, obj


def _creature(state, owner, name, power=2, toughness=2):
    o = GameObject(Card(id=f"{owner}-{name}", name=name, type_line="Creature — Bear",
                        is_creature=True, power=power, toughness=toughness),
                   owner_id=owner, zone=Zone.BATTLEFIELD)
    o.controller_id = owner
    o.summoning_sick = False
    state.add_to_battlefield(o)
    return o


def _cast(engine, p1, obj, targets=None, x=0):
    engine.cast_spell(p1, obj, targets=targets, x=x)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def _victim_spell(engine, p2, state):
    """An opposing spell sitting on the stack for a counterspell to hit."""
    card = Card(id="victim", name="Victim", type_line="Sorcery", is_sorcery=True,
                oracle_text="You gain 1 life.")
    v = GameObject(card, owner_id="p2", zone=Zone.STACK)
    v.controller_id = "p2"
    return v


def test_every_card_is_modeled_as_one_spell_effect():
    for name in CARDS:
        parsed = parse_oracle(_card(name))
        assert parsed.modeled, (name, parsed.unclaimed)


@pytest.mark.parametrize("word", ["Delirium", "Fateful hour", "Spell mastery", "Infusion", "Addendum"])
def test_rider_regex_accepts_each_ability_word_only_after_a_sentence(word):
    assert _SPELL_RIDER_PARAGRAPH_RE.search(f"Draw a card.\n{word} — If you X, draw.")
    assert not _SPELL_RIDER_PARAGRAPH_RE.search(f"Draw a card\n{word} — If you X, draw.")
    assert not _SPELL_RIDER_PARAGRAPH_RE.search(f"Draw a card.\n{word} — Draw.")


def _enemy_spell(state):
    """A bare opposing spell on the stack, a legal counter target."""
    from mtg_analyzer.models.game.game_state import StackItem
    obj = GameObject(Card(id="victim", name="Victim", type_line="Sorcery", is_sorcery=True),
                     owner_id="p2", zone=Zone.STACK)
    state.stack.append(StackItem(kind="spell", controller_id="p2", obj=obj,
                                 description=obj.name, effects=[]))
    return obj


def _kw(obj, keyword):
    """Whether the recomputed object (RULE 613) has the keyword."""
    return keyword in obj.granted_keywords


def _drain_choices(engine, state, pick=None):
    """Answer every interactive prompt (search / scry) the resolving spell opens."""
    while state.pending_choice:
        options = [o for o in state.pending_choice["options"] if o["id"] != "decline"]
        engine.resolve_pending_choice(pick or (options[0]["id"] if options else "decline"))
        engine.resolve_until_stable()


def _black(player):
    return player.mana_pool.pool.get("B", 0)


@pytest.mark.parametrize("flag", [False, True])
def test_dark_petition_adds_bbb_only_with_spell_mastery(flag):
    engine, state, p1, p2, obj = _setup("Dark Petition", mastery=flag)
    _cast(engine, p1, obj)
    _drain_choices(engine, state)
    left = POOL - 2  # {B}{B} of the printed cost
    assert _black(p1) == left + (3 if flag else 0)
    assert len(p1.hand) == 1  # the searched card, both ways


@pytest.mark.parametrize("flag", [False, True])
def test_unholy_hunger_gains_life_only_with_spell_mastery(flag):
    engine, state, p1, p2, obj = _setup("Unholy Hunger", mastery=flag)
    victim = _creature(state, "p2", "Victim")
    _cast(engine, p1, obj, [victim])
    assert victim.zone == Zone.GRAVEYARD  # the base effect always happens
    assert p1.life == 20 + (2 if flag else 0)


@pytest.mark.parametrize("flag", [False, True])
def test_spell_snuff_draws_only_at_fateful_hour(flag):
    engine, state, p1, p2, obj = _setup("Spell Snuff", low_life=flag)
    target = _enemy_spell(state)
    _cast(engine, p1, obj, [target])
    assert target.zone == Zone.GRAVEYARD  # countered
    assert len(p1.hand) == (1 if flag else 0)


@pytest.mark.parametrize("flag", [False, True])
def test_calculated_dismissal_scries_only_with_spell_mastery(flag):
    engine, state, p1, p2, obj = _setup("Calculated Dismissal", mastery=flag)
    target = _enemy_spell(state)
    _cast(engine, p1, obj, [target])
    assert (state.pending_choice or {}).get("kind") == ("scry" if flag else None)


@pytest.mark.parametrize("flag", [False, True])
def test_violent_urge_double_strike_only_with_delirium(flag):
    engine, state, p1, p2, obj = _setup("Violent Urge", delirium=flag)
    bear = _creature(state, "p1", "Bear")
    _cast(engine, p1, obj, [bear])
    assert _kw(bear, "first_strike") and bear.power == 3
    assert _kw(bear, "double_strike") is flag


@pytest.mark.parametrize("flag", [False, True])
def test_break_of_day_indestructible_only_at_fateful_hour(flag):
    engine, state, p1, p2, obj = _setup("Break of Day", low_life=flag)
    bear = _creature(state, "p1", "Bear")
    other = _creature(state, "p2", "Other")
    _cast(engine, p1, obj)
    assert bear.power == 3
    assert _kw(bear, "indestructible") is flag
    assert not _kw(other, "indestructible") and other.power == 2


@pytest.mark.parametrize("flag", [False, True])
def test_gideons_phalanx_indestructible_only_with_spell_mastery(flag):
    engine, state, p1, p2, obj = _setup("Gideon's Phalanx", mastery=flag)
    bear = _creature(state, "p1", "Bear")
    _cast(engine, p1, obj)
    knights = [o for o in state.battlefield if o.card.name == "Knight"]
    assert len(knights) == 4
    assert _kw(bear, "indestructible") is flag
    assert all(_kw(k, "indestructible") is flag for k in knights)


@pytest.mark.parametrize("flag", [False, True])
def test_send_to_sleep_skips_untap_only_with_spell_mastery(flag):
    engine, state, p1, p2, obj = _setup("Send to Sleep", mastery=flag)
    a, b = _creature(state, "p2", "A"), _creature(state, "p2", "B")
    _cast(engine, p1, obj, [a, b])
    assert a.tapped and b.tapped
    assert a.skip_next_untap is flag and b.skip_next_untap is flag


@pytest.mark.parametrize("flag", [False, True])
def test_ravaging_blaze_hits_the_controller_only_with_spell_mastery(flag):
    engine, state, p1, p2, obj = _setup("Ravaging Blaze", mastery=flag)
    victim = _creature(state, "p2", "Big", toughness=9)
    _cast(engine, p1, obj, [victim], x=3)
    assert victim.damage_marked == 3
    assert p2.life == 20 - (3 if flag else 0)


@pytest.mark.parametrize("flag", [False, True])
def test_exquisite_firecraft_cant_be_countered_only_with_spell_mastery(flag):
    engine, state, p1, p2, obj = _setup("Exquisite Firecraft", mastery=flag)
    engine.cast_spell(p1, obj, targets=[p2], x=0)
    # RULE 101.2: read while the spell is still on the stack, where the marker matters.
    assert engine.rules._is_cant_be_countered(obj) is flag
    engine.resolve_until_stable()
    assert p2.life == 16  # the base 4 damage either way


@pytest.mark.parametrize("flag", [False, True])
def test_impossible_inferno_exiles_the_top_card_only_with_delirium(flag):
    engine, state, p1, p2, obj = _setup("Impossible Inferno", delirium=flag)
    victim = _creature(state, "p2", "Big", toughness=9)
    top = p1.library[-1]
    _cast(engine, p1, obj, [victim])
    assert victim.damage_marked == 6
    assert (top in p1.exile) is flag
    assert (top in p1.library) is not flag


@pytest.mark.parametrize("flag", [False, True])
def test_clinging_mists_taps_attackers_only_at_fateful_hour(flag):
    engine, state, p1, p2, obj = _setup("Clinging Mists", low_life=flag)
    attacker = _creature(state, "p2", "Attacker")
    attacker.attacking = True
    idle = _creature(state, "p2", "Idle")
    _cast(engine, p1, obj)
    assert attacker.tapped is flag
    assert attacker.skip_next_untap is flag
    assert not idle.tapped and not idle.skip_next_untap
