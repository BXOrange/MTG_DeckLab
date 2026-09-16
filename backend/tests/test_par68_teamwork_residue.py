"""PAR-68 — Teamwork (RULE 702.194)-adjacent one-offs beyond the rider
condition PAR-56 already closed. Four cards, hand-authored/wired:

- Agent Maria Hill — "whenever ~ becomes tapped to pay a teamwork cost" —
  new `GameEngine.set_tapped(reason=...)` tag + `requires_tap_reason`
  trigger predicate.
- Virtual Assistant — "whenever you cast a spell using teamwork" — new
  `requires_spell_cast_via_teamwork` trigger predicate. This needed a real
  ordering fix: Teamwork's own tap-cost payment (and `GameObject.
  teamwork_paid`) moved earlier in `_cast_current_face`, ahead of
  `self.rules.cast_spell`/`cast_without_paying` — previously every
  additional-cost flag was set *after* `SPELL_CAST` already fired, which
  is invisible to a resolve-time reader (kicker_count et al.) but broke a
  trigger conditioned on the *same* SPELL_CAST event reading the flag off
  its own spell.
- Helicarrier Strike — a magnitude-only "instead" override (new
  `DealDamageEffect.amount_if_teamwork`, mirroring `amount_if_kicked`).
- Beast Mode — a trailing `condition={"teamwork_paid": True}` gate on a
  second effect reading "that creature" via `AddCountersEffect.
  previous_subject`.

Cruel Alliance / Too Evil to Stay Dead / Earth's Mightiest Heroes — whose own
"instead" clauses change *target legality*/*selection count* rather than a
flat magnitude — were closed separately under MEC-85 (`targeting.TargetSpec.
unless_flag` + `InspectTopChooseEffect.max_picks_if_teamwork`); see
`test_mec85_teamwork_targeting.py`.
"""

from __future__ import annotations

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


AGENT_MARIA_HILL = Card(
    id="AMH", name="Agent Maria Hill", type_line="Legendary Creature — Human Spy Hero",
    is_creature=True, mana_cost_string="{W}", converted_mana_cost=1, power=2, toughness=1,
    oracle_text=(
        "Whenever Agent Maria Hill becomes tapped to pay a teamwork cost, "
        "put a +1/+1 counter on her and draw a card."
    ),
)

VIRTUAL_ASSISTANT = Card(
    id="VA", name="Virtual Assistant", type_line="Artifact Creature — Illusion Advisor",
    is_creature=True, mana_cost_string="{2}", converted_mana_cost=2, power=3, toughness=3,
    keywords=["Defender"],
    oracle_text=(
        "Defender\n"
        "Whenever you cast a spell using teamwork, create a 1/1 colorless "
        "Robot Hero artifact creature token with flying."
    ),
)

HELICARRIER_STRIKE = Card(
    id="HS", name="Helicarrier Strike", type_line="Instant", is_instant=True,
    mana_cost_string="{W}", converted_mana_cost=1, keywords=["Teamwork"],
    oracle_text=(
        "Teamwork 2 (As an additional cost to cast this spell, you may tap "
        "any number of creatures you control with total power 2 or more.)\n"
        "Helicarrier Strike deals 2 damage to target attacking or blocking "
        "creature. If this spell was cast using teamwork, it deals 4 damage "
        "to that creature instead."
    ),
)

BEAST_MODE = Card(
    id="BM", name="Beast Mode", type_line="Instant", is_instant=True,
    mana_cost_string="{1}{G}", converted_mana_cost=2, keywords=["Teamwork"],
    oracle_text=(
        "Teamwork 1 (As an additional cost to cast this spell, you may tap "
        "any number of creatures you control with total power 1 or more.)\n"
        "Target creature gets +2/+2 and gains trample until end of turn. "
        "Also put a +1/+1 counter on that creature if this spell was cast "
        "using teamwork."
    ),
)


def _helper(eng, ctrl="p1", power=2, name="Helper"):
    o = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=power),
        owner_id=ctrl, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = ctrl
    o.summoning_sick = False
    eng.state.add_to_battlefield(o)
    return o


def _hand_spell(eng, card, ctrl="p1"):
    o = GameObject(card, owner_id=ctrl, zone=Zone.HAND)
    o.controller_id = ctrl
    bind_from_catalogue(o)
    eng.state.player_by_id(ctrl).hand.append(o)
    return o


# --- Agent Maria Hill --------------------------------------------------


def test_agent_maria_hill_specs():
    specs = specs_for(AGENT_MARIA_HILL)
    assert len(specs) == 1
    assert specs[0].trigger["requires_tap_reason"] == "teamwork"


def test_agent_maria_hill_triggers_off_her_own_teamwork_tap():
    eng = _engine()
    maria = GameObject(AGENT_MARIA_HILL, owner_id="p1", zone=Zone.BATTLEFIELD)
    maria.controller_id = "p1"
    maria.summoning_sick = False
    eng.state.add_to_battlefield(maria)
    bind_from_catalogue(maria)

    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 2})
    for i in range(5):
        p1.library.append(GameObject(
            Card(id=f"L{i}", name=f"L{i}", type_line="Island", is_land=True),
            owner_id="p1", zone=Zone.LIBRARY,
        ))
    tw_card = Card(
        id="TWS", name="Test Teamwork Spell", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{1}{G}", oracle_text="Teamwork 1 (test)\nDraw a card.",
        keywords=["Teamwork"],
    )
    tspell = _hand_spell(eng, tw_card)

    hand_before = len(p1.hand)
    eng.cast_spell(p1, tspell, teamwork=True, teamwork_choices=[maria.instance_id])
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert maria.tapped is True
    assert maria.counters.get("+1/+1") == 1
    # +1 from the teamwork spell's own draw, +1 from Maria's trigger.
    assert len(p1.hand) == hand_before - 1 + 2


def test_agent_maria_hill_ordinary_tap_does_not_trigger():
    eng = _engine()
    maria = GameObject(AGENT_MARIA_HILL, owner_id="p1", zone=Zone.BATTLEFIELD)
    maria.controller_id = "p1"
    maria.summoning_sick = False
    eng.state.add_to_battlefield(maria)
    bind_from_catalogue(maria)

    eng.rules.set_tapped(maria, True)  # no reason — an ordinary tap
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert not maria.counters.get("+1/+1")


# --- Virtual Assistant ---------------------------------------------------


def test_virtual_assistant_specs():
    specs = specs_for(VIRTUAL_ASSISTANT)
    triggered = [s for s in specs if s.ability_kind == "triggered"]
    assert len(triggered) == 1
    assert triggered[0].trigger["requires_spell_cast_via_teamwork"] is True


def test_virtual_assistant_creates_a_token_on_a_teamwork_cast():
    eng = _engine()
    va = GameObject(VIRTUAL_ASSISTANT, owner_id="p1", zone=Zone.BATTLEFIELD)
    va.controller_id = "p1"
    eng.state.add_to_battlefield(va)
    bind_from_catalogue(va)

    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 2})
    tw_card = Card(
        id="TWS2", name="Test Teamwork Spell 2", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{1}{G}", oracle_text="Teamwork 1 (test)\nDraw a card.",
        keywords=["Teamwork"],
    )
    tspell = _hand_spell(eng, tw_card)
    helper = _helper(eng, power=1)

    eng.cast_spell(p1, tspell, teamwork=True, teamwork_choices=[helper.instance_id])
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    tokens = [o for o in eng.state.battlefield if o.name == "Robot Hero"]
    assert len(tokens) == 1
    assert (tokens[0].power, tokens[0].toughness) == (1, 1)
    assert tokens[0].is_token


def test_virtual_assistant_no_token_without_teamwork():
    eng = _engine()
    va = GameObject(VIRTUAL_ASSISTANT, owner_id="p1", zone=Zone.BATTLEFIELD)
    va.controller_id = "p1"
    eng.state.add_to_battlefield(va)
    bind_from_catalogue(va)

    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 2})
    tw_card = Card(
        id="TWS3", name="Test Teamwork Spell 3", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{1}{G}", oracle_text="Teamwork 1 (test)\nDraw a card.",
        keywords=["Teamwork"],
    )
    tspell = _hand_spell(eng, tw_card)

    eng.cast_spell(p1, tspell)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert not [o for o in eng.state.battlefield if o.name == "Robot Hero"]


# --- Helicarrier Strike ---------------------------------------------------


def test_helicarrier_strike_specs():
    specs = specs_for(HELICARRIER_STRIKE)
    spell_effects = [s for s in specs if s.ability_kind == "spell_effect"]
    assert len(spell_effects) == 1
    params = spell_effects[0].effects[0].params
    assert params["amount"] == 2
    assert params["amount_if_teamwork"] == 4


def test_helicarrier_strike_deals_base_damage_without_teamwork():
    eng = _engine()
    target = GameObject(
        Card(id="T1", name="Target", type_line="Creature — Bear", is_creature=True,
             power=3, toughness=3),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    target.controller_id = "p2"
    target.attacking = True
    eng.state.add_to_battlefield(target)
    spell = _hand_spell(eng, HELICARRIER_STRIKE)
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1})

    eng.cast_spell(p1, spell, targets=[target])
    eng.resolve_until_stable()

    assert target.damage_marked == 2


def test_helicarrier_strike_deals_override_damage_with_teamwork():
    eng = _engine()
    target = GameObject(
        Card(id="T1", name="Target", type_line="Creature — Bear", is_creature=True,
             power=5, toughness=5),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    target.controller_id = "p2"
    target.attacking = True
    eng.state.add_to_battlefield(target)
    spell = _hand_spell(eng, HELICARRIER_STRIKE)
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1})
    helper = _helper(eng, power=2)

    eng.cast_spell(p1, spell, targets=[target], teamwork=True, teamwork_choices=[helper.instance_id])
    eng.resolve_until_stable()

    assert target.damage_marked == 4
    assert helper.tapped is True


# --- Beast Mode ------------------------------------------------------------


def test_beast_mode_specs():
    specs = specs_for(BEAST_MODE)
    spell_effects = [s for s in specs if s.ability_kind == "spell_effect"]
    assert len(spell_effects) == 1
    effects = spell_effects[0].effects
    assert effects[0].type == "pump"
    assert effects[1].type == "add_counters"
    assert effects[1].params["previous_subject"] is True
    assert effects[1].condition == {"teamwork_paid": True}


def test_beast_mode_pumps_only_without_teamwork():
    eng = _engine()
    target = GameObject(
        Card(id="T1", name="Target", type_line="Creature — Bear", is_creature=True,
             power=3, toughness=3),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    target.controller_id = "p1"
    eng.state.add_to_battlefield(target)
    spell = _hand_spell(eng, BEAST_MODE)
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 2})

    eng.cast_spell(p1, spell, targets=[target])
    eng.resolve_until_stable()

    assert (target.power, target.toughness) == (5, 5)
    assert not target.counters.get("+1/+1")


def test_beast_mode_also_counters_with_teamwork():
    eng = _engine()
    target = GameObject(
        Card(id="T1", name="Target", type_line="Creature — Bear", is_creature=True,
             power=3, toughness=3),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    target.controller_id = "p1"
    eng.state.add_to_battlefield(target)
    spell = _hand_spell(eng, BEAST_MODE)
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 2})
    helper = _helper(eng, power=1)

    eng.cast_spell(p1, spell, targets=[target], teamwork=True, teamwork_choices=[helper.instance_id])
    eng.resolve_until_stable()

    assert (target.power, target.toughness) == (6, 6)
    assert target.counters.get("+1/+1") == 1
