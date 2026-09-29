"""PAR-131: the legacy trigger rows retired onto the composed heads.

The migration is spec-level (flat keys → ``spell_filter`` / ``spell_cast_from``
/ ``condition.filter``), so each test here *executes* a path whose behaviour
could have drifted while the spec shape changed:

- a re-granted cast trigger keeps its composed spell filter (Black Mage's Rod
  shape — the old flat ``spell_exclude_card_types`` was dropped by the
  registry, so the granted trigger fired on creature spells too);
- the once-per-turn sentence on a composed cast trigger becomes ``limit``
  (Basim Ibn Ishaq shape) instead of a stray marker effect;
- a self/attached DAMAGE subject's recipient scope ("to an opponent", "to
  you", "to a creature") is a trigger-level gate, printed and re-granted;
- a RULE 603.4 gate around a selector effect still feeds "they" (Karlach —
  `test_mec28_intervening_if_residual.py` executes that one).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle


def _engine():
    filler = [
        Card(id=f"F{i}", name=f"Filler {i}", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2)
        for i in range(10)
    ]
    eng = GameEngine.new_game(
        [("p1", "Alice", list(filler)), ("p2", "Bob", list(filler))],
        starting_life=20, starting_hand=0,
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _creature(name, power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=power, toughness=toughness)


def _cast(eng, card, controller="p1"):
    """Free-cast ``card`` from hand; returns how many triggers it put on the stack."""
    player = eng.state.player_by_id(controller)
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    player.hand.append(obj)
    eng.rules.cast_without_paying(player, obj)
    return eng.rules.put_triggers_on_stack()


_INSTANT = Card(id="Test Shock", name="Test Shock", type_line="Instant", is_instant=True)


def _bear_spell(name="Test Bear Spell"):
    return _creature(name)


def test_regranted_noncreature_cast_trigger_keeps_its_filter():
    eng = _engine()
    rod = Card(
        id="Test Rod", name="Test Rod", type_line="Artifact — Equipment",
        oracle_text='Equipped creature has "Whenever you cast a noncreature spell, '
                    'you gain 1 life."\nEquip {1}',
    )
    assert parse_oracle(rod).coverage == MODELED
    host = _put(eng, _creature("Host"))
    equipment = _put(eng, rod)
    equipment.attached_to = host.instance_id
    eng.recompute_continuous_effects()

    assert _cast(eng, _bear_spell()) == 0  # a creature spell: filtered out
    assert _cast(eng, _INSTANT) == 1


def test_composed_cast_trigger_once_each_turn_is_a_limit():
    eng = _engine()
    card = Card(
        id="Test Historian", name="Test Historian", type_line="Creature — Human",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever you cast a historic spell, draw a card. "
                    "This ability triggers only once each turn.",
    )
    (spec,) = [s for s in parse_oracle(card).specs if s.ability_kind == "triggered"]
    assert spec.trigger.get("limit") is True
    assert [e.type for e in spec.effects] == ["draw"]

    _put(eng, card)
    relic = Card(id="Test Relic", name="Test Relic", type_line="Artifact")
    assert _cast(eng, relic) == 1
    assert _cast(eng, Card(id="Test Relic 2", name="Test Relic 2", type_line="Artifact")) == 0


def test_attached_damage_to_an_opponent_ignores_damage_to_you():
    eng = _engine()
    aura = Card(
        id="Test Curiosity", name="Test Curiosity", type_line="Enchantment — Aura",
        oracle_text="Enchant creature\n"
                    "Whenever enchanted creature deals damage to an opponent, you gain 1 life.",
    )
    host = _put(eng, _creature("Host"))
    enchantment = _put(eng, aura)
    enchantment.attached_to = host.instance_id
    p1, p2 = eng.state.players

    eng.rules.deal_damage(p1, 1, source=host)  # to the aura's controller: not an opponent
    assert eng.rules.put_triggers_on_stack() == 0
    eng.rules.deal_damage(p2, 1, source=host)
    assert eng.rules.put_triggers_on_stack() == 1


def test_self_damage_to_a_creature_ignores_a_planeswalker_recipient():
    eng = _engine()
    card = Card(
        id="Test Duelist", name="Test Duelist", type_line="Creature — Human",
        is_creature=True, power=2, toughness=2,
        oracle_text="Whenever Test Duelist deals damage to a creature, you gain 1 life.",
    )
    duelist = _put(eng, card)
    walker = _put(eng, Card(id="Test Walker", name="Test Walker",
                            type_line="Legendary Planeswalker — Test", loyalty=5), "p2")
    victim = _put(eng, _creature("Victim", 5, 5), "p2")

    eng.rules.deal_damage(walker, 1, source=duelist)
    assert eng.rules.put_triggers_on_stack() == 0
    eng.rules.deal_damage(victim, 1, source=duelist)
    assert eng.rules.put_triggers_on_stack() == 1


def test_becomes_target_that_player_is_the_targeting_spells_controller():
    # BECOMES_TARGET carries its acting player as ``player_id`` so "that
    # player" (`event_player`) resolves (Thunderbreak Regent shape).
    eng = _engine()
    regent = Card(
        id="Test Regent", name="Test Regent", type_line="Creature — Dragon",
        is_creature=True, power=4, toughness=4,
        oracle_text="Whenever a Dragon you control becomes the target of a spell or ability "
                    "an opponent controls, Test Regent deals 3 damage to that player.",
    )
    assert parse_oracle(regent).coverage == MODELED
    dragon = _put(eng, regent)
    shock = Card(id="Test Bolt", name="Test Bolt", type_line="Instant", is_instant=True,
                 oracle_text="Test Bolt deals 2 damage to any target.")
    p2 = eng.state.player_by_id("p2")
    obj = GameObject(shock, owner_id="p2", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p2.hand.append(obj)
    eng.rules.cast_without_paying(p2, obj, targets=[dragon])
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert p2.life == 17


# ---------------------------------------------------------------------------
# The hand-authored aggregate flags (``contributor_power_at_least`` /
# ``contributor_subtype`` / …) became the composed batch head's shape:
# ``contributors`` + a per-contributor ``condition.filter``.
# ---------------------------------------------------------------------------

from mtg_analyzer.game.card_registry import _REGISTRY  # noqa: E402
from mtg_analyzer.game.binding.core import bind_ability  # noqa: E402
from mtg_analyzer.models.game.events import EventType, GameEvent  # noqa: E402


def _bind_registered(eng, name, card):
    """Put ``card`` on the battlefield with the catalogue entry registered as ``name``."""
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    for spec in _REGISTRY[name.lower()]():
        bound = bind_ability(spec, obj)
        for ability in bound if isinstance(bound, list) else [bound]:
            obj.triggered_abilities.append(ability)
    return obj


def _combat_hit(eng, contributor, target="p2", amount=2):
    eng.state.fire_event(GameEvent(
        EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
        player_id=contributor.controller_id, target_id=target, is_player=True, amount=amount,
        contributor_ids=[contributor.instance_id], contributor_amounts=[amount],
    ))
    return eng.rules.put_triggers_on_stack()


def test_tifa_counts_only_a_power_seven_contributor():
    eng = _engine()
    _bind_registered(eng, "Tifa, Martial Artist", _creature("Tifa", 4, 4))
    assert _combat_hit(eng, _put(eng, _creature("Small", 6, 6))) == 0
    assert _combat_hit(eng, _put(eng, _creature("Big", 7, 7))) == 1


def test_malcolm_counts_a_pirate_hitting_an_opponent():
    eng = _engine()
    _bind_registered(eng, "Malcolm, Keen-Eyed Navigator", _creature("Malcolm", 2, 2))
    pirate = _put(eng, Card(id="Pirate", name="Pirate", type_line="Creature — Human Pirate",
                            is_creature=True, power=2, toughness=2))
    assert _combat_hit(eng, _put(eng, _creature("Bear", 2, 2))) == 0
    assert _combat_hit(eng, pirate, target="p1") == 0  # "your opponents" only
    assert _combat_hit(eng, pirate) == 1


def test_kediss_is_parser_modeled_per_commander_hit():
    # The catalogue entry is gone: the composed head reads Kediss per damage
    # event, so "that much damage" is that commander's own damage.
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_life=20, starting_hand=0,
    )
    kediss = Card(
        id="Test Kediss", name="Test Kediss", type_line="Legendary Creature — Elemental Lizard",
        is_creature=True, power=1, toughness=3,
        oracle_text="Whenever a commander you control deals combat damage to an opponent, "
                    "it deals that much damage to each other opponent.",
    )
    assert parse_oracle(kediss).coverage == MODELED
    _put(eng, kediss)
    commander = _put(eng, _creature("Commander", 3, 3))
    commander.is_commander = True
    bear = _put(eng, _creature("Bear", 5, 5))
    p1, p2, p3 = eng.state.players

    eng.rules.deal_damage(p2, 5, source=bear, combat=True)
    assert eng.rules.put_triggers_on_stack() == 0
    eng.rules.deal_damage(p2, 3, source=commander, combat=True)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert (p1.life, p2.life, p3.life) == (20, 12, 17)
