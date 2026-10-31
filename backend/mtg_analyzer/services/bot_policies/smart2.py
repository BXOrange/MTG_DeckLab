"""Independent, view-only SmartBot 2 decisions with mechanic/style evidence.

SmartBot supplies wire helpers (land choices and one-shot mana unlocking),
never its play/attack/sacrifice prohibitions. SmartBot 1 remains unchanged.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import random
import re

from .base import Bot
from .smart import SmartBot
from ..smart_bot2.profile import build_profile, roles_for, Profile, PROFILE_VERSION
from ..smart_bot2.context import (Context, W, MAX_CANDIDATES, MAX_TARGET_OPTIONS,
    MAX_ABILITY_USES, MAX_TRACE_CANDIDATES, DEVELOPMENT_SOURCES, number, stable)
from ..smart_bot2.choices import choice, target_value, fill_costs
from ..smart_bot2.combat import attack, blocks
from ..smart_bot2.evaluation import score, reserve
from ..smart_bot2.recipes import naming_choice, library_trigger


class SmartBot2(SmartBot):
    kind = 'smart2'
    label = 'Smart Bot 2'
    description = ('Plant nach Archetyp, Spielstil und sichtbarer Lage: bewertet '
                   'Kosten, Ziele, Combat, Timing und erreichbare Gewinnpläne.')

    def __init__(self, player_id: str, name: str = '') -> None:
        super().__init__(player_id, name)
        self.strategy = Profile()
        self.memory = {'uses': {}, 'positions': set(), 'trace': {}, 'reservation': {}}
        self._target_action = {}
        self._vote_rng = random.Random(int.from_bytes(hashlib.sha256(player_id.encode()).digest(), 'big'))

    def prepare(self, session):
        # Base dispatch failure bookkeeping is shared; Smart1 strategy and
        # ability memory must not be created/modified by this policy.
        Bot.prepare(self, session)
        deck = getattr(session, '_bot_decklists', {}).get(self.player_id)
        profiles = getattr(session, '_smart2_profiles', {})
        if deck:
            from mtg_analyzer.config import COMMANDER_SPELLBOOK_DB_PATH
            snapshot = COMMANDER_SPELLBOOK_DB_PATH.stat() if COMMANDER_SPELLBOOK_DB_PATH.exists() else None
            snapshot_key = (snapshot.st_mtime_ns, snapshot.st_size) if snapshot else None
            key = hashlib.sha256(stable([PROFILE_VERSION, snapshot_key, deck.get('archetypes'),
                [(c.name, c.oracle_text, c.mana_cost_string, c.type_line, c.back_name, c.back_oracle_text, c.back_mana_cost_string)
                 for c in deck['cards'] + deck['commanders']]]).encode()).hexdigest()
            cached = profiles.get(self.player_id)
            if not cached or cached[0] != key:
                profiles[self.player_id] = (key, build_profile(deck['cards'], deck['commanders'],
                                                            archetypes=deck.get('archetypes')))
            self.strategy = profiles[self.player_id][1]
            session._smart2_profiles = profiles
        memories = getattr(session, '_smart2_memory', {})
        self.memory = memories.setdefault(self.player_id,
            {'uses': {}, 'positions': set(), 'trace': {}, 'reservation': {}})
        session._smart2_memory = memories
        # Retain compatibility with SmartBot's narrowly reused unlock helper.
        self._ability_uses = self.memory['uses']
        self._ability_positions = self.memory['positions']

    def _context(self, view):
        return Context(view, self.player_id, self.strategy)

    def _objects(self, view):
        return self._context(view).objects

    def _object(self, view, action):
        return self._context(view).obj(action)

    def _plan(self, view, action):
        return self._context(view).plan(action)

    def _target_owner(self, view, option):
        return self._context(view).owner(option)

    def _card_value(self, view, action):
        # Retention/search uses an intrinsic value; decisions use score(), not
        # this helper. No Commander-name bonus or unbounded role accumulation.
        return self._context(view).value(action)

    def rank_targets(self, view, options, polarity=None):
        ctx = self._context(view)
        text = ctx.effect_text(self._target_action)
        ranked = sorted(options, key=lambda o: (-target_value(ctx, o, text, polarity), stable(o)))
        return ranked

    def pick_target_groups(self, view, action):
        self._target_action = action
        try:
            groups = Bot.pick_target_groups(self, view, action)
            if groups is None:
                return None
            # Optional harmful targets can be declined rather than destroying
            # our only permanent. Preserve the server's group partition.
            ctx = self._context(view)
            for i, requirement in enumerate(action.get('targets') or []):
                divided = any(d['requirement_index'] == i for d in action.get('damage_divisions') or [])
                if requirement.get('optional') and not divided:
                    groups[i] = [o for o in groups[i] if target_value(ctx, o,
                                    ctx.effect_text(action), requirement.get('polarity')) > 0]
            return groups
        finally:
            self._target_action = {}

    def _fill_in(self, view, action):
        action = self.announcement_offer(action)
        ctx = self._context(view)
        built = fill_costs(ctx, action)
        if built is None:
            return None
        built.pop('targets', None)
        built.pop('target_groups', None)
        built.pop('legal_defenders', None)
        if action.get('requires_target'):
            selected = self.pick_targets_and_groups(view, action)
            if selected is None:
                return None
            targets, groups = selected
            built['targets'] = targets
            if groups is not None:
                built['target_groups'] = groups
        # X is intentionally selected by candidate generation, including 0.
        if action.get('has_x'):
            built['x'] = int(action.get('x', action.get('min_x', 0)) or 0)
        return built if self.fill_damage_divisions(action, built) else None

    def setup(self, view, actions):
        # Existing bounded source-aware London handling now uses Smart2's
        # retention value and mechanic roles, rather than combo-name bonuses.
        return SmartBot.setup(self, view, actions)

    def answer_choice(self, view, answers):
        ctx = self._context(view)
        result = naming_choice(ctx, answers) or choice(ctx, answers)
        if result is not None:
            return result
        # Known entry/reveal/Mox wire choices are shared. Avoid the old
        # name-based library recipe and sacrifice heuristics here.
        kind = (view.get('pending_choice') or {}).get('kind', '')
        if kind in ('land_tapped', 'land_tapped_reveal') or (view.get('pending_choice') or {}).get('entry_effect'):
            return SmartBot.answer_choice(self, view, answers)
        return Bot.answer_choice(self, view, sorted(answers, key=stable))

    def _attack(self, view, offers):
        return attack(self._context(view), offers)

    def blocks(self, view, offers):
        return blocks(self._context(view), offers)

    def can_pass_turn(self, view, actions):
        ctx = self._context(view)
        if library_trigger(ctx):
            return False
        # Future windows matter only while the bot can still pay for them: an
        # instant it can afford (`castable` is the view's mana-potential
        # check) or a non-mana ability the server currently offers. Mana
        # abilities are never offered as `activate_ability`, so lands and
        # rocks do not count. Own visible information only.
        if any(a['type'] == 'activate_ability' and not a.get('locked') for a in actions):
            return False
        for obj in ctx.hand:
            p = ctx.plan(obj)
            instant = (p and 'instant' in p.types) or 'instant' in str(obj.get('type_line', '')).casefold()
            # A view without the flag (unannotated hand) counts as payable.
            if obj.get('castable', True) and (instant or 'flash' in ctx.text(obj)):
                return False
        for obj in ctx.ours:
            text = ctx.text(obj)
            if 'each end step' in text or "each of their turns" in text:
                return False
        return True

    def _variants(self, ctx, action, actions):
        variants = [dict(action)]
        if action.get('has_x'):
            low = int(action.get('min_x', 0) or 0)
            high = int(action.get('max_x', 0) or 0)
            _, held, _ = reserve(ctx, actions)
            # Thresholds bound the search: min, one, reserve-preserving, max,
            # and visible target toughness. Never range(large X).
            values = {low, min(high, max(low, 1)), high, max(low, high - int(held))}
            values |= {int(number(ctx.obj(o).get('toughness'))) for r in action.get('targets', [])
                       for o in r.get('options', [])[:MAX_TARGET_OPTIONS]}
            variants = [{**action, 'x': x} for x in sorted(values) if low <= x <= high]
        if action.get('has_kicker') and not action.get('kicker_has_x') and not action.get('kicked'):
            # Offered max_kicker is authoritative. Single kicker has no max
            # in some offers; its affordability is not assumed in that case.
            maximum = int(action.get('max_kicker', 0) or 0)
            if maximum:
                variants += [self.announcement_offer({**v, 'kicked': 1}) for v in variants
                             if not (v.get('kicker_variant') or {}).get('locked')]
        return variants

    def _record(self, ctx, candidates, selected):
        top = sorted(candidates, key=lambda c: (-c[0], stable(c[1])))[:MAX_TRACE_CANDIDATES]
        self.memory['trace'] = {'version': PROFILE_VERSION, 'position': ctx.position(),
            'role': ctx.role, 'styles': dict(ctx.styles), 'archetypes': list(ctx.profile.archetypes),
            'reservation': dict(self.memory.get('reservation', {})),
            'selected': selected,
            'candidates': [{'score': v, 'action': a, 'terms': terms, 'plan_status': status}
                           for v, a, terms, status in top]}

    def play(self, view, actions):
        # A kicked branch can have legal targets even when the base is locked.
        actions = [*actions, *(a['kicker_variant'] for a in actions
                              if isinstance(a.get('kicker_variant'), dict)
                              and not a['kicker_variant'].get('locked'))]
        ctx = self._context(view)
        attacks = [a for a in actions if a['type'] == 'attack' and not a.get('locked')]
        if attacks:
            result = attack(ctx, attacks)
            self._record(ctx, [], result)
            return result
        turn = ctx.turn
        self.memory['uses'] = {k: v for k, v in self.memory['uses'].items() if k[0] == turn}
        self.memory['positions'] = {p for p in self.memory['positions'] if p[0] == turn}
        self._ability_uses, self._ability_positions = self.memory['uses'], self.memory['positions']
        rvalue, rcost, purpose = reserve(ctx, actions)
        self.memory['reservation'] = {'purpose': purpose, 'mana': rcost, 'value': rvalue,
                                      'turn': turn, 'expires': 'next-position'}
        candidates = [(0.0, None, {'pass': 0.0}, 'none')]
        main = ctx.active and ctx.step in ('main1', 'main2') and not ctx.stack
        for offer in sorted(actions, key=stable):
            if offer.get('locked') or offer['type'] not in ('cast_spell', 'activate_ability', 'play_land', 'turn_face_up'):
                continue
            if offer['type'] == 'play_land' and not main:
                continue
            text = ctx.effect_text(offer)
            roles = roles_for(text)
            if ctx.stack:
                controller = ctx.stack[-1].get('controller_id') or (ctx.stack[-1].get('source') or {}).get('controller_id')
                # Do not develop into our own pending stack. Exception: an
                # explicitly recognized library-win response window.
                if controller == self.player_id and not library_trigger(ctx):
                    continue
                if not roles & {'counter', 'removal', 'bounce'} and not library_trigger(ctx):
                    if not any(r.get('polarity') == 'beneficial' for r in offer.get('targets', [])):
                        continue
            elif not main:
                if ctx.step not in ('end', 'end_combat', 'begin_combat', 'declare_blockers'):
                    continue
                if 'counter' in roles:
                    continue
            # Don't silently remove our own only target with a mandatory
            # harmful spell. Effect-aware sacrifice/transform is exempt.
            if any(r.get('polarity') == 'harmful' and not r.get('optional') and
                   not any(ctx.owner(o) != self.player_id for o in r.get('options', []))
                   for r in offer.get('targets', [])) and 'sacrifice' not in text:
                continue
            if offer['type'] == 'activate_ability':
                key = (turn, self._signature(offer))
                position = (turn, ctx.position(), self._signature(offer))
                if self._ability_uses.get(key, 0) >= MAX_ABILITY_USES or position in self._ability_positions:
                    continue
            # Don't cast entry-discard mana when it destroys our only land
            # drop. This is cost text, not a card name exception.
            if 'you may discard a land card instead' in ctx.text(offer):
                lands = sum(o.get('is_land', False) for o in ctx.hand)
                if lands < 1 or lands < 2 and ctx.sources < 3:
                    continue
            for variant in self._variants(ctx, offer, actions):
                built = self._fill_in(view, variant)
                if built is None:
                    continue
                value, terms, status = score(ctx, built, actions)
                if offer['type'] == 'play_land':
                    p = ctx.plan(offer)
                    if p:
                        terms['colour_need'] = self._colour_need(view, p)
                        value += terms['colour_need']
                if built.get('kicked'):
                    terms['kicker'] = W.engine
                    value += W.engine
                candidates.append((value, built, terms, status))
                if len(candidates) >= MAX_CANDIDATES:
                    break
            if len(candidates) >= MAX_CANDIDATES:
                break
        value, built, terms, status = max(candidates, key=lambda c: (c[0], stable(c[1])))
        if main:
            unlock = self._unlock_tap(view, actions, value)
            if unlock is not None:
                self._record(ctx, candidates, unlock)
                return unlock
        if built and built['type'] == 'activate_ability':
            key = (turn, self._signature(built))
            self._ability_uses[key] = self._ability_uses.get(key, 0) + 1
            self._ability_positions.add((turn, ctx.position(), self._signature(built)))
        self._record(ctx, candidates, built)
        return built
