"""Visible decision context; even diagnostic unredacted views are not trusted."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import re
from mtg_analyzer.services.bot_strategy import cost_requirements, normalize
from .profile import roles_for, rules_text

# Scores are utility units, not probabilities. Named terms keep tuning auditable.
@dataclass(frozen=True)
class Weights:
    card: float = 8.0
    body: float = 1.5
    mana: float = 6.0
    cost: float = 2.0
    draw: float = 7.0
    engine: float = 8.0
    synergy: float = 6.0
    combo_cap: float = 18.0
    land: float = 24.0
    removal: float = 1.5
    attack_trigger: float = 7.0
    combat_damage: float = 2.0
    lethal: float = 1000.0
    loss: float = 1.4
    reserve: float = 12.0
    protection: float = 15.0
    activation: float = 2.0
    unknown: float = 3.0

W = Weights()
# Limits are work budgets, not claims of exhaustive search.
MAX_CANDIDATES = 128
MAX_TARGET_OPTIONS = 24
MAX_COMBAT_PACKAGES = 32
MAX_ABILITY_USES = 64
MAX_TRACE_CANDIDATES = 8
# RULE 903.10a / 704.5c. Only ordinary Commander games, not team formats.
COMMANDER_LETHAL = 21
POISON_LETHAL = 10
# These policy thresholds describe resource saturation, not game rules.
DEVELOPMENT_SOURCES = 6
LOW_HAND = 3
LIFE_RESERVE = 5
TOKEN_RETENTION_FACTOR = .5  # replaceable token material versus a retained card


def number(value, default=0):
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def stable(value):
    return json.dumps(value, sort_keys=True, default=str, separators=(',', ':'))


class Context:
    def __init__(self, view, player_id, profile):
        self.view, self.player_id, self.profile = view, player_id, profile
        self.state = view.get('state', {})
        self.players = self.state.get('players', [])
        self.me = next((p for p in self.players if p['id'] == player_id), {})
        self.opponents = [p for p in self.players if p['id'] != player_id and not p.get('has_lost')]
        self.board = [o for o in self.state.get('battlefield', []) if not o.get('phased_out')]
        self.ours = [o for o in self.board if o.get('controller_id') == player_id]
        self.theirs = [o for o in self.board if o.get('controller_id') != player_id]
        self.hand = self.me.get('hand', [])
        self.objects = list(self.board)
        # RULE 400.2: public zones plus our hand/command only. Libraries and
        # opponents' hands never feed this evaluator, even in debug fixtures.
        for p in self.players:
            for zone in ('graveyard', 'exile', 'command'):
                self.objects.extend(o for o in p.get(zone, [])
                                    if not o.get('face_down_in_exile') or p['id'] == player_id)
        self.objects.extend(self.hand)
        self.objects.extend(s['object'] for s in self.state.get('stack', []) if s.get('object'))
        self.by_id = {o['instance_id']: o for o in self.objects if 'instance_id' in o}
        self.turn = (self.state.get('internal_turn') or {}).get('number', 0)
        self.step = self.state.get('current_step', '')
        self.active = self.state.get('active_player_id') == player_id
        self.stack = self.state.get('stack') or []
        self.sources = sum(bool(o.get('is_land')) or 'ramp' in self.roles(o) for o in self.ours)
        summary = view.get('mana_potential', {}).get(player_id, {})
        pool = {c: number(n) for c, n in (self.me.get('mana_pool') or {}).items() if isinstance(n, (int, float))}
        self.mana_branches = [{c: number(n) + pool.get(c, 0) for c, n in v.get('mana', {}).items()}
                              | {c: n for c, n in pool.items() if c not in v.get('mana', {})}
                              for v in summary.get('variations', [])]
        if not self.mana_branches:
            self.mana_branches = [pool]  # no guessed simultaneous dual-land maxima
        self.mana = max((sum(b.values()) for b in self.mana_branches), default=0)
        self.styles = getattr(profile, 'styles', {})
        own_power = sum(max(0, number(o.get('power'))) for o in self.ours if o.get('is_creature'))
        enemy_power = sum(max(0, number(o.get('power'))) for o in self.theirs if o.get('is_creature'))
        self.behind = enemy_power > own_power or number(self.me.get('life'), 40) <= enemy_power
        self.role = 'stabilize' if self.behind else ('pressure' if self.styles.get('initiative', 0) else 'develop')

    def obj(self, action):
        obj = self.by_id.get(action.get('instance_id'), action)
        if action.get('face') in ('back','fuse'):
            face = getattr(self.profile,'faces',{}).get(normalize(obj.get('name',''))+'|'+action['face'])
            if face:
                p = face['plan']
                return {**obj,'name':p.name,'oracle_text':p.text,'type_line':p.types,'mana_cost':p.cost,
                        'mana_value':p.mana_value,'power':face['power'],'toughness':face['toughness'],
                        'is_creature':face['is_creature'],'is_land':face['is_land']}
        return obj

    def plan(self, action):
        if action.get('face') in ('back','fuse'):
            obj = self.by_id.get(action.get('instance_id'), action)
            face = getattr(self.profile,'faces',{}).get(normalize(obj.get('name',''))+'|'+action['face'])
            if face:
                return face['plan']
        return self.profile.cards.get(normalize(self.obj(action).get('name') or action.get('name', '')))

    def text(self, action):
        obj = self.obj(action)
        plan = self.plan(action)
        return (obj.get('oracle_text') or (plan.text if plan else '')).casefold()

    def effect_text(self, action):
        text = action.get('mode_description') or action.get('description')
        if text:
            return str(text).casefold()
        text = self.text(action)
        if action.get('type') == 'activate_ability':
            lines = [line for line in text.splitlines() if ':' in line]
            index = int(action.get('ability_index', 0))
            if lines and index < len(lines):
                return lines[index].split(':', 1)[1].strip()
        return text

    def roles(self, obj):
        return roles_for(self.text(obj), self.obj(obj).get('type_line', ''))

    def value(self, obj):
        """Retention value, distinct from the utility of casting/activating it."""
        obj = self.obj(obj)
        p = self.plan(obj)
        mv = number(obj.get('mana_value'), p.mana_value if p else 0)
        v = W.card + mv + W.body * (max(0, number(obj.get('power'))) + max(0, number(obj.get('toughness'))))
        roles = self.roles(obj)
        if roles & {'draw', 'ramp', 'death-payoff', 'spellslinger', 'landfall'}:
            v += W.engine
        if obj.get('is_token'):
            v *= TOKEN_RETENTION_FACTOR  # disposable token bodies; power still contributes above
        return v

    def owner(self, option):
        if option.get('player_id'):
            return option['player_id']
        if option.get('stack_id'):
            return next((s.get('controller_id') or (s.get('source') or {}).get('controller_id')
                         for s in self.stack if s.get('stack_id') == option['stack_id']), None)
        obj = self.obj(option)
        return obj.get('controller_id') or obj.get('owner_id')

    def payable(self, cost, reserve=''):
        pips, generic = cost_requirements(((cost or '') + reserve).upper())
        return any(all(branch.get(c, 0) >= n for c, n in pips.items())
                   and sum(branch.values()) >= sum(pips.values()) + generic for branch in self.mana_branches)

    def position(self):
        # Fingerprint excludes logs and all hidden content. Include counters,
        # pending choices and stack so a genuine resource change permits reuse.
        visible = {'board': self.board, 'me': {k: self.me.get(k) for k in
                   ('hand', 'command', 'graveyard', 'exile', 'life', 'mana_pool', 'library_count', 'counters')},
                   'players': [{k: p.get(k) for k in ('id', 'life', 'poison', 'counters', 'library_count', 'commander_damage')}
                               for p in self.players],
                   'turn': self.turn, 'step': self.step, 'stack': self.stack,
                   'choice': self.view.get('pending_choice'), 'facts': self.view.get('turn_facts')}
        return hashlib.sha256(stable(visible).encode()).hexdigest()

    def cost(self, action):
        p = self.plan(action)
        # Cast alternatives have their own offered cost; never substitute MV
        # when an effective cost was actually supplied by the server.
        raw = action.get('effective_cost') or action.get('cost') or action.get('cost_label') or action.get('alt_cost_label') or action.get('evoke_cost_label') or action.get('mana_cost')
        if not raw and p and action.get('type') == 'cast_spell':
            raw = p.cost
        if action.get('free'):
            return 0
        pips, generic = cost_requirements(str(raw or '').upper())
        return sum(pips.values()) + generic + int(action.get('x', 0) or 0) * max(1, p.cost.upper().count('{X}') if p else str(raw).upper().count('{X}')) + int(action.get('kicked', 0) or 0) * sum(cost_requirements(action.get('kicker_cost', ''))[0].values()) + int(action.get('kicked', 0) or 0) * cost_requirements(action.get('kicker_cost', ''))[1]

    def public_text(self):
        return '\n'.join(self.text(o) for o in self.ours)
