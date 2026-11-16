"""RULE 707.10: a copied mana ability resolves without paying its activation cost."""
from __future__ import annotations

import copy
from dataclasses import replace

from .core import GameEffect
from ..mana_abilities import self_damage_amount, resolve_options, mana_source_kind_for, is_snow_source_for, option_label, mana_types_a_land_could_produce
from ..mana_spend_riders import arm_next_cast_rider, build_rider


class CopiedManaAbilityEffect(GameEffect):
    def __init__(self, source, ability, visit, x, exiled_mv, sacrificed_mv, untapped_cost_land=None):
        super().__init__(source)
        self.ability = copy.deepcopy(ability)
        self.visit = visit
        self.x = x
        self.exiled_mv = exiled_mv
        self.sacrificed_mv = sacrificed_mv
        self.untapped_cost_land = untapped_cost_land

    def apply(self, context, targets=None):
        rules = context.engine
        source = self.source
        live = source.zone_incarnation == self.visit
        if not live:
            source = context.state.zone_visit_sources.get((source.instance_id, self.visit), source)
        source = copy.copy(source)
        source.controller_id = context.resolving_controller_id or source.controller_id
        player = context.state.player_by_id(source.controller_id)
        ability = self.ability
        if live and ability.source_counters_before_mana:
            for kind, amount in ability.source_counters.items():
                rules.add_counters(self.source, amount, kind, source=self.source)
            source.counters = dict(self.source.counters)
        # RULE 602.5: activation restrictions and costs do not restrict a copy's resolution.
        template = replace(ability, cost=replace(ability.cost, activation_condition=None))
        options = resolve_options(template, source, context.state)
        if ability.color_selector == 'untapped_cost_land_types':
            land = None
            if self.untapped_cost_land is not None:
                iid, visit = self.untapped_cost_land
                land = context.state.find_object(iid)
                if land is None or land.zone_incarnation != visit:
                    land = context.state.zone_visit_sources.get((iid, visit))
            options = ([{color: 1} for color in sorted(mana_types_a_land_could_produce(land, context.state))]
                       if land is not None else [])
        if ability.x_scaled:
            options = [{color: amount * self.x for color, amount in option.items()} for option in options]
        if ability.cost.exile_creature:
            options = [{color: (self.exiled_mv or 0) + 1 for color in option} for option in options]
        if ability.amount_from_sacrificed_creature:
            options = [{color: self.sacrificed_mv or 0 for color in option} for option in options]
        frame = {'effect': self, 'source': source, 'player_id': player.id, 'live': live,
                 'options': options, 'produced': {}, 'remaining': None}
        if ability.any_combination and options:
            frame['remaining'] = sum(options[0].values())
            frame['options'] = [{color: 1} for option in options for color in option]
        context.state.pending_copied_mana_ability = frame
        continue_resolution(rules)


def continue_resolution(rules):
    frame = rules.state.pending_copied_mana_ability
    options = frame['options']
    if frame['remaining'] == 0 or not options:
        finish_resolution(rules)
        return
    if len(options) == 1:
        chosen = dict(options[0])
        if frame['remaining'] is not None:
            chosen = {color: amount * frame['remaining'] for color, amount in chosen.items()}
        frame['produced'] = chosen
        finish_resolution(rules)
        return
    rules.open_choice({
        'kind': 'copied_mana_option', 'player_id': frame['player_id'],
        'source_id': frame['source'].instance_id, 'prompt': 'Mana der Fähigkeitskopie wählen',
        'options': [{'id': str(index), 'label': option_label(option)} for index, option in enumerate(options)],
    })


def choose_option(rules, answer):
    frame = rules.state.pending_copied_mana_ability
    if frame is None:
        return
    options = frame['options']
    index = int(answer) if answer is not None and str(answer).isdigit() else 0
    index = index if 0 <= index < len(options) else 0
    for color, amount in options[index].items():
        frame['produced'][color] = frame['produced'].get(color, 0) + amount
    if frame['remaining'] is not None:
        frame['remaining'] -= 1
        continue_resolution(rules)
    else:
        finish_resolution(rules)


def finish_resolution(rules):
    frame = rules.state.pending_copied_mana_ability
    rules.state.pending_copied_mana_ability = None
    effect, source = frame['effect'], frame['source']
    ability = effect.ability
    player = rules.state.player_by_id(frame['player_id'])
    restriction = copy.deepcopy(ability.restriction)
    if restriction and restriction.get('your_commander'):
        restriction['owner_id'] = player.id
    if restriction and restriction.get('kind') == 'chosen_type_spell':
        restriction = {'kind': 'type_spell', 'types': [source.chosen_type] if source.chosen_type else [],
                       'allow_ability': restriction.get('allow_ability', False)}
    elif restriction and restriction.get('kind') == 'chosen_color_monocolored_spell':
        restriction = {'kind': 'monocolored_spell', 'color': source.chosen_color}
    # RULE 605.1 / 707.10: copying does not tap a permanent for mana; tap-only
    # replacements and TAPPED_FOR_MANA triggers do not apply to this production.
    player.mana_pool.add_many(frame['produced'], restriction=restriction,
                              source_kind=mana_source_kind_for(source), is_snow=is_snow_source_for(source),
                              rider=build_rider(ability.spend_rider, source) if ability.spend_rider else None)
    rules.state.record_stat(player.id, 'mana', amount=sum(frame['produced'].values()))
    if ability.next_cast_rider:
        arm_next_cast_rider(rules.state, source, ability.next_cast_rider)
    if ability.x_scaled and ability.gain_life_x and effect.x:
        rules.gain_life(player, effect.x)
    if ability.self_damage:
        rules.deal_damage(player, self_damage_amount(ability, rules.state, player.id), source=source)
    if ability.self_rad_counters:
        rules.add_player_counters(player, ability.self_rad_counters, 'rad', source=source)
    if frame['live'] and not ability.source_counters_before_mana:
        for kind, amount in ability.source_counters.items():
            rules.add_counters(effect.source, amount, kind, source=source)
    for kind, amount in ability.player_counters.items():
        rules.add_player_counters(player, amount, kind, source=source)
