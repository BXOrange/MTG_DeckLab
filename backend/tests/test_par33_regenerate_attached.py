"""PAR-33 — "regenerate enchanted creature" as an Aura's own activated
ability (RULE 701.16 / 303 — Regeneration / Gaea's Embrace / Blessing of
Leeches / Dark Privilege / Serpent Skin).

New `handlers._REGENERATE_ATTACHED_RE` → `EffectSpec("regenerate",
{"target_kind": "attached_permanent"})`, routing to `RegenerateEffect`'s
pre-existing `attached_permanent` mode (reads `source.attached_to` live).
No engine change.
"""

from __future__ import annotations

from mtg_analyzer.game.effects.core import GameContext, RegenerateEffect
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game import continuous
from mtg_analyzer.game import combat
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _rules():
    p1, p2 = Player(id="p1", life=20), Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    return RulesEngine(state), state, p1


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


# --- parse -----------------------------------------------------------------


def test_regenerate_enchanted_creature_parses():
    assert parse_effect_body("regenerate enchanted creature") == [
        EffectSpec("regenerate", {"target_kind": "attached_permanent"})
    ]
    assert parse_effect_body("regenerate equipped creature") == [
        EffectSpec("regenerate", {"target_kind": "attached_permanent"})
    ]


def test_plain_regenerate_target_creature_unaffected():
    assert parse_effect_body("regenerate target creature") == [
        EffectSpec("regenerate", {"target_kind": "creature"})
    ]


def test_quoted_grant_with_tap_or_untap_target_permanent_parses():
    """PAR-33: recursive quoted-grant parsing retains the real choice.

    The choice itself is exercised by the Derevi engine regression; this
    asserts that the Aura form reaches that existing primitive rather than
    merely accepting the outer quote.
    """
    card = Card(
        id="ghostly-touch", name="Ghostly Touch", type_line="Enchantment — Aura",
        oracle_text=(
            'Enchant creature\nEnchanted creature has "Whenever ~ attacks, '
            'you may tap or untap target permanent."'
        ),
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    specs = static_effect_specs(
        'enchanted creature has "whenever ~ attacks, you may tap or untap target permanent."'
    )
    assert specs is not None
    grant = specs[0]
    assert grant.type == "grant_triggered_ability"
    assert grant.params["grant_effects"] == [{
        "type": "tap",
        "params": {"target_kind": "permanent", "choose_tap_or_untap": True},
    }]


def test_dual_casting_quoted_spell_copy_keeps_its_controller_restriction():
    card = Card(
        id="dual-casting", name="Dual Casting", type_line="Enchantment — Aura",
        oracle_text=(
            'Enchant creature\nEnchanted creature has "{R}, {T}: Copy target instant '
            'or sorcery spell you control. You may choose new targets for the copy."'
        ),
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    specs = static_effect_specs(
        'enchanted creature has "{r}, {t}: copy target instant or sorcery spell you control. '
        'you may choose new targets for the copy."'
    )
    assert specs is not None
    grant = specs[0]
    assert grant.type == "grant_activated_ability"
    assert grant.params["grant_effects"] == [{
        "type": "copy_spell",
        "params": {"card_types": ["instant", "sorcery"], "target_kind": "spell_you_control"},
    }]


def test_spell_you_control_target_kind_excludes_an_opponents_spell():
    _, state, _ = _rules()
    mine = GameObject(
        Card(id="mine", name="Mine", type_line="Instant", is_instant=True),
        owner_id="p1", zone=Zone.STACK,
    )
    theirs = GameObject(
        Card(id="theirs", name="Theirs", type_line="Instant", is_instant=True),
        owner_id="p2", zone=Zone.STACK,
    )
    state.stack.extend([
        StackItem(kind="spell", controller_id="p1", obj=mine, description="Mine"),
        StackItem(kind="spell", controller_id="p2", obj=theirs, description="Theirs"),
    ])
    options = legal_targets(
        state, "p1", TargetSpec(kind="spell_you_control", spell_filter={"card_types": ["instant", "sorcery"]})
    )
    assert [option["instance_id"] for option in options] == [mine.instance_id]


def test_inevitable_end_quoted_upkeep_sacrifice_is_modeled_and_uses_its_controller():
    card = Card(
        id="inevitable-end", name="Inevitable End", type_line="Enchantment — Aura",
        oracle_text='Enchant creature\nEnchanted creature has "At the beginning of your upkeep, sacrifice a creature."',
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    specs = static_effect_specs(
        'enchanted creature has "at the beginning of your upkeep, sacrifice a creature."'
    )
    assert specs is not None
    assert specs[0].params["grant_effects"] == [{
        "type": "sacrifice", "params": {"selector": "controller", "what": "creature", "count": 1},
    }]

    engine, state, p1 = _rules()
    victim = _bf(state, Card(id="victim", name="Victim", type_line="Creature", is_creature=True))
    grant = specs[0]
    from mtg_analyzer.game.effects.registry import EffectRegistry
    effect = EffectRegistry.create(grant.params["grant_effects"][0]["type"], grant.params["grant_effects"][0]["params"])
    effect.source = _bf(state, Card(id="source", name="Source", type_line="Creature", is_creature=True))
    effect.apply(GameContext(state, engine))
    assert state.pending_choice is not None
    engine.resolve_choice(str(victim.instance_id))
    assert victim in p1.graveyard


def test_pendrell_flux_quoted_upkeep_uses_the_grantees_mana_cost():
    card = Card(
        id="pendrell-flux", name="Pendrell Flux", type_line="Enchantment — Aura",
        oracle_text=(
            'Enchant creature\nEnchanted creature has "At the beginning of your upkeep, '
            'sacrifice this creature unless you pay its mana cost."'
        ),
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    specs = static_effect_specs(
        'enchanted creature has "at the beginning of your upkeep, sacrifice this creature unless you pay its mana cost."'
    )
    assert specs is not None
    assert specs[0].params["grant_effects"] == [{
        "type": "sacrifice_unless_pay", "params": {"cost": "source_mana_cost"},
    }]

    engine, state, p1 = _rules()
    host = _bf(state, Card(
        id="host", name="Host", type_line="Creature", is_creature=True,
        mana_cost_string="{2}{G}", converted_mana_cost=3,
    ))
    from mtg_analyzer.game.effects.registry import EffectRegistry
    effect = EffectRegistry.create("sacrifice_unless_pay", {"cost": "source_mana_cost"})
    effect.source = host
    p1.mana_pool.add_many({"C": 2, "G": 1})
    effect.apply(GameContext(state, engine))
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "sacrifice_unless_pay"
    assert "{2}{G}" in choice["prompt"]


def test_instill_furor_quoted_end_step_sacrifice_checks_the_grantee_attack_flag():
    card = Card(
        id="instill-furor", name="Instill Furor", type_line="Enchantment — Aura",
        oracle_text=(
            'Enchant creature\nEnchanted creature has "At the beginning of your end step, '
            'sacrifice this creature unless it attacked this turn."'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'enchanted creature has "at the beginning of your end step, sacrifice this creature unless it attacked this turn."'
    )
    assert specs is not None
    assert specs[0].params["grant_effects"] == [{
        "type": "sacrifice_unless_attacked", "params": {},
    }]

    engine, state, p1 = _rules()
    host = _bf(state, Card(id="host", name="Host", type_line="Creature", is_creature=True))
    from mtg_analyzer.game.effects.registry import EffectRegistry
    effect = EffectRegistry.create("sacrifice_unless_attacked", {})
    effect.source = host
    effect.apply(GameContext(state, engine))
    assert host in p1.graveyard

    survivor = _bf(state, Card(id="survivor", name="Survivor", type_line="Creature", is_creature=True))
    survivor.attacked_this_turn = True
    effect.source = survivor
    effect.apply(GameContext(state, engine))
    assert survivor in state.battlefield


def test_predatory_urge_quoted_pre_keyword_fight_is_one_atomic_fight():
    card = Card(
        id="predatory-urge", name="Predatory Urge", type_line="Enchantment — Aura",
        oracle_text=(
            'Enchant creature\nEnchanted creature has "{T}: This creature deals damage equal '
            'to its power to target creature. That creature deals damage equal to its power to this creature."'
        ),
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    specs = static_effect_specs(
        'enchanted creature has "{t}: this creature deals damage equal to its power to target creature. '
        'that creature deals damage equal to its power to this creature."'
    )
    assert specs is not None
    assert specs[0].params["grant_effects"] == [{"type": "fight", "params": {"other_kind": "creature"}}]

    engine, state, _ = _rules()
    host = _bf(state, Card(id="host", name="Host", type_line="Creature", is_creature=True, power=3, toughness=3))
    foe = _bf(state, Card(id="foe", name="Foe", type_line="Creature", is_creature=True, power=2, toughness=4), controller="p2")
    from mtg_analyzer.game.effects.registry import EffectRegistry
    effect = EffectRegistry.create("fight", {"other_kind": "creature"})
    effect.source = host
    effect.apply(GameContext(state, engine), [foe])
    assert host.damage_marked == 2 and foe.damage_marked == 3


def test_manriki_gusari_quoted_destroy_equipment_uses_the_existing_subtype_target():
    card = Card(
        id="manriki-gusari", name="Manriki-Gusari", type_line="Artifact — Equipment",
        oracle_text=(
            'Equipped creature gets +1/+2 and has "{T}: Destroy target Equipment."\nEquip {1}'
        ),
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    specs = static_effect_specs(
        'equipped creature gets +1/+2 and has "{t}: destroy target equipment."'
    )
    assert specs is not None
    assert specs[1].params["grant_effects"] == [{
        "type": "destroy", "params": {"target_kind": "equipment"},
    }]

    engine, state, p1 = _rules()
    source = _bf(state, Card(id="source", name="Source", type_line="Creature", is_creature=True))
    equipment = _bf(state, Card(id="equipment", name="Equipment", type_line="Artifact — Equipment"))
    from mtg_analyzer.game.effects.registry import EffectRegistry
    effect = EffectRegistry.create("destroy", {"target_kind": "equipment"})
    effect.source = source
    effect.apply(GameContext(state, engine), [equipment])
    assert equipment in p1.graveyard


def test_arc_spitter_quoted_damage_targets_only_its_blocker():
    card = Card(
        id="arc-spitter", name="Arc Spitter", type_line="Artifact — Equipment",
        oracle_text=(
            'Equipped creature has "{1}: This creature deals 1 damage to target creature that\'s blocking it."'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'equipped creature has "{1}: this creature deals 1 damage to target creature that\'s blocking it."'
    )
    assert specs is not None
    assert specs[0].params["grant_effects"] == [{
        "type": "damage", "params": {"amount": 1, "target_kind": "creature_blocking_source"},
    }]

    _, state, _ = _rules()
    attacker = _bf(state, Card(id="attacker", name="Attacker", type_line="Creature", is_creature=True))
    blocker = _bf(state, Card(id="blocker", name="Blocker", type_line="Creature", is_creature=True), controller="p2")
    bystander = _bf(state, Card(id="bystander", name="Bystander", type_line="Creature", is_creature=True), controller="p2")
    blocker.blocking = attacker.instance_id
    options = legal_targets(state, "p1", TargetSpec(kind="creature_blocking_source"), source=attacker)
    assert [option["instance_id"] for option in options] == [blocker.instance_id]
    assert bystander.instance_id not in [option["instance_id"] for option in options]


def test_blinding_powder_unattaches_the_granting_equipment_as_its_cost():
    card = Card(
        id="blinding-powder", name="Blinding Powder", type_line="Artifact — Equipment",
        oracle_text=(
            'Equipped creature has "Unattach Blinding Powder: Prevent all combat damage '
            'that would be dealt to this creature this turn."\nEquip {2}'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'equipped creature has "unattach blinding powder: prevent all combat damage '
        'that would be dealt to this creature this turn."'
    )
    assert specs is not None
    assert specs[0].params["cost"]["unattach_grant_source"] is True
    assert specs[0].params["grant_effects"] == [{
        "type": "prevent_damage_shield",
        "params": {"amount": "all", "self_only": True, "combat_only": True},
    }]

    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = engine.state
    host = _bf(state, Card(id="host", name="Host", type_line="Creature", is_creature=True))
    powder = _bf(state, card)
    bind_from_catalogue(powder)
    powder.attached_to = host.instance_id
    continuous.recompute(state)
    assert len(host._granted_activated_abilities) == 1
    assert engine.can_activate(state.active_player, host, host._granted_activated_abilities[0])
    engine.activate_ability(state.active_player, host, 0)
    assert powder.attached_to is None
    assert host.attached_to is None


def test_voltaic_whip_quoted_attacks_alone_trigger_is_regranted():
    card = Card(
        id="voltaic-whip", name="Voltaic Whip", type_line="Artifact — Equipment",
        oracle_text=(
            'Equipped creature gets +2/+0 and has "Whenever this creature attacks alone, '
            'you draw a card and lose 1 life."\nEquip {2}'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'equipped creature gets +2/+0 and has "whenever ~ attacks alone, '
        'you draw a card and lose 1 life."'
    )
    assert specs is not None
    assert specs[1].params["trigger_event"] == "ATTACKS_ALONE"
    assert specs[1].params["grant_effects"] == [
        {"type": "draw", "params": {"count": 1}},
        {"type": "lose_life", "params": {"amount": 1}},
    ]


def test_giants_amulet_quoted_self_static_is_regranted_to_its_host():
    card = Card(
        id="giants-amulet", name="Giant's Amulet", type_line="Artifact — Equipment",
        oracle_text=(
            'Equipped creature gets +0/+1 and has "This creature has hexproof as long as it\'s untapped."\nEquip {2}'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'equipped creature gets +0/+1 and has "~ has hexproof as long as it\'s untapped."'
    )
    assert specs is not None
    assert specs[1].params["static_specs"] == [{
        "type": "grant_keyword",
        "params": {"affects": "self", "keywords": ["hexproof"], "active_if": {"kind": "source_untapped"}},
    }]

    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = engine.state
    host = _bf(state, Card(id="host", name="Host", type_line="Creature", is_creature=True))
    amulet = _bf(state, card)
    bind_from_catalogue(amulet)
    amulet.attached_to = host.instance_id
    continuous.recompute(state)
    assert combat.has_hexproof(host) is True
    host.tapped = True
    continuous.recompute(state)
    assert combat.has_hexproof(host) is False


def test_livewire_lash_quoted_becomes_target_trigger_is_regranted():
    card = Card(
        id="livewire-lash", name="Livewire Lash", type_line="Artifact — Equipment",
        oracle_text=(
            'Equipped creature gets +2/+0 and has "Whenever this creature becomes the target '
            'of a spell, this creature deals 2 damage to any target."\nEquip {2}'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'equipped creature gets +2/+0 and has "whenever ~ becomes the target of a spell, '
        '~ deals 2 damage to any target."'
    )
    assert specs is not None
    assert specs[1].params["trigger_event"] == "BECOMES_TARGET"
    assert specs[1].params["grant_effects"] == [{
        "type": "damage", "params": {"amount": 2, "target_kind": "any"},
    }]


def test_iconic_shield_quoted_trigger_targets_another_attacking_creature():
    card = Card(
        id="iconic-shield", name="Iconic Shield", type_line="Artifact — Equipment",
        oracle_text=(
            'Equipped creature gets +1/+2 and has "Whenever this creature attacks, another target '
            'attacking creature gains indestructible until end of turn."\nEquip {3}'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'equipped creature gets +1/+2 and has "whenever ~ attacks, another target attacking '
        'creature gains indestructible until end of turn."'
    )
    assert specs is not None
    assert specs[1].params["grant_effects"] == [{
        "type": "pump", "params": {"target_kind": "creature", "creature_filter": {"attacking": True}, "keywords": ["indestructible"]},
    }]

    _, state, _ = _rules()
    source = _bf(state, Card(id="source", name="Source", type_line="Creature", is_creature=True))
    fellow = _bf(state, Card(id="fellow", name="Fellow", type_line="Creature", is_creature=True))
    bystander = _bf(state, Card(id="bystander", name="Bystander", type_line="Creature", is_creature=True))
    source.attacking = fellow.attacking = True
    options = legal_targets(state, "p1", TargetSpec(kind="creature", creature_filter={"attacking": True}), source=source)
    assert [option["instance_id"] for option in options] == [fellow.instance_id]
    assert bystander.instance_id not in [option["instance_id"] for option in options]


def test_urban_burgeoning_quoted_other_players_untap_step_trigger_is_regranted():
    card = Card(
        id="urban-burgeoning", name="Urban Burgeoning", type_line="Enchantment — Aura",
        oracle_text='Enchant land\nEnchanted land has "Untap this land during each other player\'s untap step."',
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'enchanted land has "untap this land during each other player\'s untap step."'
    )
    assert specs is not None
    assert specs[0].params == {
        "trigger_event": "STEP_BEGIN", "phase_relation": "not_you",
        "grant_effects": [{"type": "tap", "params": {"target_kind": None, "untap": True}}],
        "optional": False, "affects": "attached_permanent",
    }


def test_security_blockade_quoted_damage_shield_ability_is_regranted():
    card = Card(
        id="security-blockade", name="Security Blockade", type_line="Enchantment — Aura",
        oracle_text='Enchant land\nEnchanted land has "{T}: Prevent the next 1 damage that would be dealt to you this turn."',
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'enchanted land has "{t}: prevent the next 1 damage that would be dealt to you this turn."'
    )
    assert specs is not None
    assert specs[0].params["grant_effects"] == [{
        "type": "prevent_damage_shield", "params": {"amount": 1},
    }]


def test_friendly_neighborhood_quoted_dynamic_target_pump_is_regranted():
    card = Card(
        id="friendly-neighborhood", name="Friendly Neighborhood", type_line="Enchantment — Aura",
        oracle_text=(
            'Enchant land\nEnchanted land has "{1}, {T}: Target creature gets +1/+1 until end of turn '
            'for each creature you control. Activate only as a sorcery."'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'enchanted land has "{1}, {t}: target creature gets +1/+1 until end of turn '
        'for each creature you control. activate only as a sorcery."'
    )
    assert specs is not None
    assert specs[0].params["grant_effects"] == [{
        "type": "pump", "params": {"target_kind": "creature", "amount_from_count_selector": "creatures_you_control"},
    }]
    assert specs[0].params["sorcery_speed_only"] is True


def test_ceremonial_knife_quoted_combat_damage_trigger_creates_a_blood_token():
    card = Card(
        id="ceremonial-knife", name="Ceremonial Knife", type_line="Artifact — Equipment",
        oracle_text=(
            'Equipped creature gets +1/+0 and has "Whenever this creature deals combat damage, '
            'create a Blood token."\nEquip {2}'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'equipped creature gets +1/+0 and has "whenever ~ deals combat damage, create a blood token."'
    )
    assert specs is not None
    assert specs[1].params["trigger_event"] == "DAMAGE"
    assert specs[1].params["filter"] == {"combat": True}
    assert specs[1].params["grant_effects"] == [{
        "type": "create_token", "params": {"count": 1, "token_name": "Blood"},
    }]


def test_sorcerers_wand_quoted_damage_uses_the_hosts_live_wizard_type():
    card = Card(
        id="sorcerers-wand", name="Sorcerer's Wand", type_line="Artifact — Equipment",
        oracle_text=(
            'Equipped creature has "{T}: This creature deals 1 damage to target player or planeswalker. '
            'If this creature is a Wizard, it deals 2 damage instead."\nEquip {3}'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'equipped creature has "{t}: ~ deals 1 damage to target player or planeswalker. '
        'if ~ is a wizard, it deals 2 damage instead."'
    )
    assert specs is not None
    assert specs[0].params["grant_effects"] == [{
        "type": "damage",
        "params": {"amount": 1, "target_kind": "player", "amount_if_source_subtype": {"subtype": "wizard", "amount": 2}},
    }]

    engine, state, p1 = _rules()
    target = state.player_by_id("p2")
    from mtg_analyzer.game.effects.registry import EffectRegistry
    effect = EffectRegistry.create("damage", {
        "amount": 1, "target_kind": "player",
        "amount_if_source_subtype": {"subtype": "wizard", "amount": 2},
    })
    effect.source = _bf(state, Card(id="wizard", name="Wizard", type_line="Creature — Wizard", is_creature=True))
    effect.apply(GameContext(state, engine), [target])
    assert target.life == 18
    effect.source.card.type_line = "Creature"
    effect.apply(GameContext(state, engine), [target])
    assert target.life == 17


def test_pathway_arrows_quoted_damage_taps_only_a_colorless_creature():
    card = Card(
        id="pathway-arrows", name="Pathway Arrows", type_line="Artifact — Equipment",
        oracle_text=(
            'Equipped creature has "{2}, {T}: This creature deals 1 damage to target creature. '
            'If a colorless creature is dealt damage this way, tap it."\nEquip {2}'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'equipped creature has "{2}, {t}: ~ deals 1 damage to target creature. '
        'if a colorless creature is dealt damage this way, tap it."'
    )
    assert specs is not None
    assert specs[0].params["grant_effects"] == [{
        "type": "damage", "params": {"amount": 1, "target_kind": "creature", "tap_target_if_colorless": True},
    }]

    engine, state, _ = _rules()
    source = _bf(state, Card(id="source", name="Source", type_line="Creature", is_creature=True))
    colorless = _bf(state, Card(id="colorless", name="Colorless", type_line="Artifact Creature", is_creature=True), controller="p2")
    colored = _bf(state, Card(id="colored", name="Colored", type_line="Creature", is_creature=True, color_identity=["R"]), controller="p2")
    from mtg_analyzer.game.effects.registry import EffectRegistry
    effect = EffectRegistry.create("damage", {"amount": 1, "target_kind": "creature", "tap_target_if_colorless": True})
    effect.source = source
    effect.apply(GameContext(state, engine), [colorless])
    assert colorless.tapped is True and colorless.damage_marked == 1
    effect.apply(GameContext(state, engine), [colored])
    assert colored.tapped is False and colored.damage_marked == 1


def test_splinter_twin_quoted_self_copy_grant_is_parsed_with_its_delayed_exile():
    card = Card(
        id="splinter-twin", name="Splinter Twin", type_line="Enchantment — Aura",
        oracle_text=(
            'Enchant creature\nEnchanted creature has "{T}: Create a token that\'s a copy '
            'of this creature, except it has haste. Exile that token at the beginning of the next end step."'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'enchanted creature has "{t}: create a token that\'s a copy of ~, except it has haste. '
        'exile that token at the beginning of the next end step."'
    )
    assert specs is not None
    assert specs[0].params["grant_effects"] == [
        {"type": "copy_permanent", "params": {"target_kind": None, "referent": "source", "haste": True}},
        {"type": "create_delayed_trigger", "params": {
            "step": "end", "scope": "any", "capture": "created_objects",
            "effects": [{"type": "exile_specific", "params": {}}],
        }},
    ]


def test_diviners_wand_two_quoted_grants_are_regranted_independently():
    card = Card(
        id="diviners-wand", name="Diviner's Wand", type_line="Artifact — Equipment",
        oracle_text=(
            'Equipped creature has "Whenever you draw a card, this creature gets +1/+1 and gains flying until end of turn" '
            'and "{4}: Draw a card."\nEquip {3}'
        ),
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'equipped creature has "whenever you draw a card, ~ gets +1/+1 and gains flying until end of turn" '
        'and "{4}: draw a card."'
    )
    assert specs is not None
    assert [spec.type for spec in specs] == ["grant_triggered_ability", "grant_activated_ability"]
    assert specs[0].params["trigger_event"] == "DRAW"
    assert specs[1].params["grant_effects"] == [{"type": "draw", "params": {"count": 1}}]


def test_grasp_of_the_hieromancer_quoted_attack_tap_uses_defending_player_scope():
    card = Card(
        id="grasp", name="Grasp of the Hieromancer", type_line="Enchantment — Aura",
        oracle_text='Enchant creature\nEnchanted creature gets +1/+1 and has "Whenever this creature attacks, tap target creature defending player controls."',
    )
    assert parse_oracle(card).coverage != UNMODELED
    specs = static_effect_specs(
        'enchanted creature gets +1/+1 and has "whenever ~ attacks, tap target creature defending player controls."'
    )
    assert specs is not None
    assert specs[1].params["grant_effects"] == [{
        "type": "tap", "params": {"target_kind": "creature_defending_player_controls", "untap": False},
    }]


def test_well_rested_quoted_untapped_trigger_is_regranted_once_per_turn():
    card = Card(
        id="well-rested", name="Well Rested", type_line="Enchantment — Aura",
        oracle_text=(
            'Enchant creature\nEnchanted creature has "Whenever this creature becomes untapped, '
            'put 2 +1/+1 counters on it, then you gain 2 life and draw a card. '
            'This ability triggers only once each turn."'
        ),
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    specs = static_effect_specs(
        'enchanted creature has "whenever this creature becomes untapped, put 2 +1/+1 counters on it, '
        'then you gain 2 life and draw a card. this ability triggers only once each turn."'
    )
    assert specs is not None
    assert specs[0].params["trigger_event"] == "UNTAPPED"
    assert specs[0].params["once_per_turn"] is True


def test_real_cards_modeled():
    for name, text in [
        ("Regeneration", "Enchant creature\n{G}: Regenerate enchanted creature."),
        ("Blessing of Leeches",
         "Enchant creature\nEnchanted creature has \"{0}: Regenerate this creature. "
         "Activate only once each turn.\"\n{0}: Regenerate enchanted creature."),
        ("Dark Privilege",
         "Enchant creature\nEnchanted creature gets +1/+1.\n"
         "Sacrifice a creature: Regenerate enchanted creature."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Enchantment — Aura", oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_attached_regenerate_shields_the_host_from_destruction():
    eng, state, p1 = _rules()
    host = _bf(state, Card(id="h", name="Grizzly Bear", type_line="Creature — Bear",
                           is_creature=True, power=2, toughness=2))
    aura = _bf(state, Card(id="a", name="Regeneration", type_line="Enchantment — Aura"))
    aura.attached_to = host.instance_id

    RegenerateEffect(target_kind="attached_permanent", source=aura).apply(
        GameContext(state, eng)
    )
    eng.destroy(host, can_be_regenerated=True)

    assert host in state.battlefield          # the shield absorbed the destroy
    assert host not in p1.graveyard


def test_attached_regenerate_is_a_noop_when_unattached():
    eng, state, p1 = _rules()
    aura = _bf(state, Card(id="a", name="Regeneration", type_line="Enchantment — Aura"))
    aura.attached_to = None
    # must not raise
    RegenerateEffect(target_kind="attached_permanent", source=aura).apply(
        GameContext(state, eng)
    )
