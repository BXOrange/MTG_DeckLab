"""SmartBot policy; shared registry/driver is services.bots."""
from __future__ import annotations

from typing import Any, Optional

from .greedy import GreedyBot

#: Fewest mana sources (lands + cheap mana rocks/rituals) an opening hand needs.
MIN_OPENING_SOURCES = 2
#: More lands than this in the opening hand is a flood, not a keep.
MAX_OPENING_LANDS = 5
#: A mana rock/ritual costing at most this much counts as an opening mana
#: source (Sol Ring, Moxen, Lotus Petal, Elves); judgement call — a 3-drop
#: rock does not rescue a hand that cannot cast anything on turn 2.
CHEAP_MANA_MAX_VALUE = 2
#: Below this life total a shock land stays tapped instead of costing 2 life
#: (judgement call: roughly the point where a Commander table can punish it).
SHOCK_LIFE_FLOOR = 10
#: Lands on the battlefield from which Mox Diamond may cost the next land drop.
MOX_DIAMOND_BOARD_LANDS = 3
#: Types worth burning a one-shot mana source on (targets are not a concern).
PERMANENT_TYPES = frozenset({'creature', 'artifact', 'enchantment', 'planeswalker'})


class SmartBot(GreedyBot):
    """Bounded, deck-aware heuristic policy using only the client view.

    The supplied deck is unordered prior knowledge. Combo progress uses
    *visible* objects; a library match never means that a card is in hand.
    """

    kind = 'smart'
    label = 'Smart Bot'
    description = 'Erkennt Deckstrategie und Farben, entwickelt Commander und WinCons und sucht Combo-Teile.'

    def __init__(self, player_id: str, name: str = '') -> None:
        super().__init__(player_id, name)
        from mtg_analyzer.services.bot_strategy import DeckStrategy
        self.strategy = DeckStrategy()
        self._ability_uses = {}
        self._ability_positions = set()

    def prepare(self, session) -> None:
        super().prepare(session)
        from mtg_analyzer.services.bot_strategy import build_strategy
        profiles = getattr(session, '_bot_strategies', {})
        if self.player_id not in profiles:
            deck = getattr(session, '_bot_decklists', {}).get(self.player_id)
            if deck:
                profiles[self.player_id] = build_strategy(deck['cards'], deck['commanders'])
                session._bot_strategies = profiles
        if self.player_id in profiles:
            self.strategy = profiles[self.player_id]
        memory = getattr(session, '_smart_ability_uses', {})
        self._ability_uses = memory.setdefault(self.player_id, {})
        session._smart_ability_uses = memory
        positions = getattr(session, '_smart_ability_positions', {})
        self._ability_positions = positions.setdefault(self.player_id, set())
        session._smart_ability_positions = positions

    def _mine(self, view):
        return next((p for p in view['state'].get('players', []) if p['id'] == self.player_id), {})

    def _objects(self, view):
        objects = list(view['state'].get('battlefield', []))
        for player in view['state'].get('players', []):
            for zone in ('hand', 'command', 'graveyard', 'exile'):
                objects.extend(player.get(zone, []))
        objects.extend(s['object'] for s in view['state'].get('stack', []) if s.get('object'))
        return objects

    def _object(self, view, action):
        return next((o for o in self._objects(view) if o.get('instance_id') == action.get('instance_id')), {})

    def _target_owner(self, view, option):
        if 'player_id' in option:
            return option['player_id']
        if 'stack_id' in option:
            return next((s.get('controller_id') for s in view['state'].get('stack', [])
                         if s.get('stack_id') == option['stack_id']), None)
        obj = self._object(view, option)
        return obj.get('controller_id') or obj.get('owner_id') or option.get('controller_id')

    def _plan(self, view, action):
        from mtg_analyzer.services.bot_strategy import normalize
        obj = self._object(view, action)
        return self.strategy.cards.get(normalize(obj.get('name') or action.get('name') or ''))

    def _combo_value(self, view, name, existing=False):
        from collections import Counter
        from mtg_analyzer.services.bot_strategy import normalize
        name = normalize(name)
        board = Counter(normalize(o.get('name', '')) for o in view['state'].get('battlefield', [])
                        if o.get('controller_id') == self.player_id)
        accessible = board + Counter(normalize(o.get('name', ''))
                                     for zone in ('hand', 'command') for o in self._mine(view).get(zone, []))
        best = 0
        for combo in self.strategy.combos:
            needed = dict(combo.pieces)
            if name not in needed:
                continue
            total = sum(needed.values())
            progress = sum(min(board[n], q) for n, q in combo.pieces)
            assembled = all(accessible[n] >= q for n, q in combo.pieces)
            # Work on the closest visible plan, giving its missing part the
            # strongest tutor vote. Do not search for redundant copies.
            payoff = ' '.join(combo.outputs).casefold()
            winning = any(word in payoff for word in ('win the game', 'damage', 'life loss', 'mill'))
            value = 35 + 45 * progress / total + (35 if assembled else 0) + (15 if winning else 0)
            if not existing and board[name] >= needed[name]:
                value = 5
            best = max(best, value)
        return best

    def _combo_piece(self, name):
        from mtg_analyzer.services.bot_strategy import normalize
        return any(normalize(name) in dict(c.pieces) for c in self.strategy.combos)

    def _card_value(self, view, action):
        plan = self._plan(view, action)
        if not plan:
            return 12
        value = 16 - plan.mana_value * 1.5 + self._combo_value(
            view, plan.name, existing=action.get('type') == 'activate_ability')
        if 'wincon' in plan.roles:
            value += 24
        if ' '.join(plan.name.casefold().split()) in self.strategy.commanders:
            value += 28
        value += 12 * len(plan.roles & self.strategy.themes)
        lands = sum(o.get('is_land', False) for o in view['state'].get('battlefield', [])
                    if o.get('controller_id') == self.player_id)
        if 'ramp' in plan.roles:
            value += max(0, 28 - 4 * lands) + (8 if self.strategy.archetype == 'ramp' else 0)
        if 'draw' in plan.roles:
            value += 18 if len(self._mine(view).get('hand', [])) <= 3 else 8
        if 'tutor' in plan.roles and self.strategy.combos:
            value += 30
        if 'creature' in plan.types and self.strategy.archetype == 'aggro':
            value += 15
        return value

    def setup(self, view, actions):
        hand = self._mine(view).get('hand', [])
        lands = sum(o.get('is_land', False) for o in hand)
        # Cheap rocks/rituals are mana too: a land plus Sol Ring is a keep,
        # while a hand of only spells is not.
        sources = lands + sum(1 for o in hand if self._cheap_mana(o))
        if ((lands < 1 or sources < MIN_OPENING_SOURCES or lands > MAX_OPENING_LANDS)
                and view['setup'].get('mulligan_count', 0) < 2
                and any(a['type'] == 'mulligan' for a in actions)):
            return {'type': 'mulligan'}
        count = next(a for a in actions if a['type'] == 'keep_hand').get('bottom_count', 0)
        # Retain two lands, then preserve the cards advancing the plan.
        protected = {o['instance_id'] for o in [o for o in hand if o.get('is_land')][:2]}
        ranked = sorted(hand, key=lambda o: (o['instance_id'] in protected,
                         -10 if o.get('is_land') and lands > 3 else self._card_value(view, o)))
        return {'type': 'keep_hand', 'bottom_instance_ids': [o['instance_id'] for o in ranked[:count]]}

    def _cheap_mana(self, obj):
        from mtg_analyzer.services.bot_strategy import normalize
        plan = self.strategy.cards.get(normalize(obj.get('name') or ''))
        return bool(plan and 'land' not in plan.types and 'ramp' in plan.roles
                    and plan.mana_value <= CHEAP_MANA_MAX_VALUE)

    def _wants_untapped_land(self, view):
        # Paying life for an untapped entry only matters when something can
        # be cast with the mana this turn.
        me = self._mine(view)
        has_spell = any(not o.get('is_land') for o in me.get('hand', [])) or bool(me.get('command'))
        return has_spell and me.get('life', 40) > SHOCK_LIFE_FLOOR

    def answer_choice(self, view, answers):
        kind = (view.get('pending_choice') or {}).get('kind', '')
        choices = [a for a in answers if a['type'] == 'choose']
        # RULE 614.1 enters-tapped options: a shock land is paid for when the
        # mana is needed this turn, a "reveal a card" land always reveals
        # (free), and Mox Diamond discards the land it needs least (a Mox
        # that is declined is simply lost).
        if kind == 'land_tapped' and self._wants_untapped_land(view):
            pay = next((a for a in choices if a.get('option_id') == 'pay'), None)
            if pay:
                return pay
        if kind == 'land_tapped_reveal':
            reveal = next((a for a in choices if a.get('option_id') == 'reveal'), None)
            if reveal:
                return reveal
        if kind == 'enter_or_graveyard':
            lands = [a for a in choices if a.get('option_id') != 'decline']
            if lands:
                return min(lands, key=lambda a: (self._colour_need(view, self._plan(view, a))
                                                 if self._plan(view, a) else 0))
        if kind == 'name_card' and choices and self._oracle_trigger(view):
            from collections import Counter
            from mtg_analyzer.services.bot_strategy import normalize
            # A name with all deck copies publicly outside the library
            # empties the library. Only choose from the engine's offers.
            outside = Counter(normalize(o.get('name', '')) for o in self._objects(view)
                              if o.get('owner_id', o.get('controller_id')) == self.player_id and not o.get('is_token'))
            absent = [a for a in choices if self.strategy.quantities.get(normalize(a.get('name') or ''), 0)
                      and outside[normalize(a['name'])] >= self.strategy.quantities[normalize(a['name'])]]
            if absent:
                return absent[0]
            text_offer = next((a for a in choices if a.get('free_text')), None)
            if text_offer:
                for name, quantity in self.strategy.quantities.items():
                    if outside[name] >= quantity:
                        return {**text_offer, 'option_id': self.strategy.cards[name].name}
        if kind == 'search' and choices:
            def score(a):
                value = self._card_value(view, a)
                plan = self._plan(view, a)
                if plan and 'land' in plan.types:
                    value += self._colour_need(view, plan)
                return value
            return max(choices, key=score)
        pending = view.get('pending_choice') or {}
        sacrifice = kind == 'choose_objects' and pending.get('action') == 'sacrifice'
        pregame_exile = (kind == 'choose_objects' and pending.get('action') == 'exile'
                         and not view['state'].get('current_step'))
        if ('discard' in kind or kind == 'sacrifice' or sacrifice or pregame_exile) and choices:
            objects = [a for a in choices if a.get('instance_id') is not None]
            if objects:
                return min(objects, key=lambda a: self._card_value(view, a) +
                           (80 if self._combo_piece(self._object(view, a).get('name', '')) else 0))
        # Optional effects need context. Take free draw/token effects; keep
        # the base class's conservative answer for unknown payment prompts.
        pending = view.get('pending_choice') or {}
        source_plan = self._plan(view, {'name': pending.get('source_name')})
        if kind == 'composite_optional' and choices and source_plan:
            if source_plan.roles & {'draw', 'tokens'} and 'pay ' not in source_plan.text:
                return choices[0]
        if kind in ('scry', 'surveil') and choices:
            if pending.get('phase') == 'order':
                return max(choices, key=lambda a: self._card_value(view, a))
            lands = sum(o.get('is_land', False) for o in view['state'].get('battlefield', [])
                        if o.get('controller_id') == self.player_id)
            if lands >= 6:
                land = next((a for a in choices if self._plan(view, a) and
                             'land' in self._plan(view, a).types), None)
                if land:
                    return land
        return super().answer_choice(view, answers)

    def _colour_need(self, view, plan):
        from collections import Counter
        import re
        demand = Counter()
        for o in self._mine(view).get('hand', []) + self._mine(view).get('command', []):
            p = self._plan(view, o)
            if p and 'land' not in p.types:
                for colour in re.findall(r'\{([WUBRG])\}', p.cost):
                    demand[colour] += 1
        supplied = Counter()
        for o in view['state'].get('battlefield', []):
            if o.get('controller_id') == self.player_id and o.get('is_land'):
                p = self._plan(view, o)
                if p:
                    supplied.update(p.identity)
        return sum(8 * demand[c] / (1 + supplied[c]) for c in plan.identity)

    def rank_targets(self, view, options, polarity=None):
        ranked = super().rank_targets(view, options, polarity)
        def value(option):
            obj = self._object(view, option)
            owner = self._target_owner(view, option)
            preferred = (owner == self.player_id) if polarity == 'beneficial' else (owner != self.player_id)
            if option.get('player_id'):
                life = next((p.get('life', 40) for p in view['state'].get('players', [])
                             if p['id'] == option['player_id']), 40)
                threat = 40 - life
            else:
                threat = self._card_value(view, obj) + (obj.get('power') or 0) * 2
            return (preferred, threat)
        return sorted(ranked, key=value, reverse=True)

    def _oracle_trigger(self, view):
        return any(s.get('controller_id') == self.player_id and s.get('category') == 'triggered_ability'
                   and (s.get('source') or {}).get('name') == "Thassa's Oracle"
                   for s in view['state'].get('stack', []))

    def can_pass_turn(self, view, actions):
        # Off its own turn `play` below only ever acts against something on
        # the stack (a counter or removal aimed at an opponent's object), and
        # the server never passes over an opponent's stack item — so with an
        # empty stack every window is a pass. The one exception is its own
        # Thassa's Oracle trigger, which is the bot's own stack item and so
        # would be passed over too.
        return not self._oracle_trigger(view)

    def play(self, view, actions):
        offered_actions = actions
        actions = [a for a in actions if a['type'] not in self._IGNORED and not a.get('locked')]
        attacks = [a for a in actions if a['type'] == 'attack']
        if attacks:
            return self._attack(view, attacks)
        state = view['state']
        turn = state.get('internal_turn', {}).get('number', 0)
        self._ability_positions.intersection_update(p for p in list(self._ability_positions) if p[0] == turn)
        for key in list(self._ability_uses):
            if key[0] != turn:
                del self._ability_uses[key]
        stack = state.get('stack') or []
        main = self.is_active(view) and state.get('current_step') in ('main1', 'main2') and not stack
        if main:
            lands = [a for a in actions if a['type'] == 'play_land']
            if lands:
                return max(lands, key=lambda a: (self._colour_need(view, self._plan(view, a))
                           if self._plan(view, a) else 0) + (5 if a.get('enters_tapped') is False else 0))
        candidates = []
        for a in actions:
            if a['type'] not in ('cast_spell', 'activate_ability'):
                continue
            plan = self._plan(view, a)
            text = (a.get('mode_description') or a.get('description') or (plan.text if plan else '')).casefold()
            counter = 'counter target' in text and 'spell' in text
            consultation = bool(plan and plan.name == 'Demonic Consultation')
            oracle = bool(plan and plan.name == "Thassa's Oracle")
            oracle_line = self._oracle_trigger(view) and consultation
            if consultation and not oracle_line:
                continue  # exiling a library without a pending win is self-defeat
            if oracle and self._mine(view).get('library_count', 99) > 2:
                consultation_in_hand = any(o.get('name') == 'Demonic Consultation'
                                           for o in self._mine(view).get('hand', []))
                summary = view.get('mana_potential', {}).get(self.player_id, {})
                pool = self.my_pool(view)
                # Each branch is one coherent allocation of dual sources,
                # unlike summing the independent per-colour maxima.
                affordable = any(branch.get('mana', {}).get('U', 0) + pool.get('U', 0) >= 2
                                 and branch.get('mana', {}).get('B', 0) + pool.get('B', 0) >= 1
                                 for branch in summary.get('variations', []))
                if not consultation_in_hand or not affordable:
                    continue  # wait until the complete win line is affordable
            if plan and 'you may discard a land card instead' in plan.text:
                # Mox Diamond costs a land card: only worth it with a spare
                # one in hand, or once the board already has lands to spare.
                hand_lands = sum(o.get('is_land', False) for o in self._mine(view).get('hand', []))
                board_lands = sum(o.get('is_land', False) for o in state.get('battlefield', [])
                                  if o.get('controller_id') == self.player_id)
                if hand_lands < 1 or (hand_lands < 2 and board_lands < MOX_DIAMOND_BOARD_LANDS):
                    continue
            if counter:
                if not stack or self._stack_controller(stack[-1]) == self.player_id:
                    continue
            elif not main and not oracle_line:
                # Respond with removal to opponents; other development
                # waits for our main phase so alternatives can be compared.
                if not stack or self._stack_controller(stack[-1]) == self.player_id:
                    continue
                if not ('destroy target' in text or 'exile target' in text):
                    continue
            # Avoid spending removal on our own board when it is the only
            # legal target, including mandatory target requirements.
            if any(r.get('polarity') == 'harmful' and not r.get('optional') and
                   not any(self._target_owner(view, o) != self.player_id
                           for o in r.get('options', [])) for r in a.get('targets', [])):
                continue
            if 'destroy all' in text or 'exile all' in text:
                ours = sum(self._card_value(view, o) for o in state.get('battlefield', [])
                           if o.get('controller_id') == self.player_id and o.get('is_creature'))
                theirs = sum(self._card_value(view, o) for o in state.get('battlefield', [])
                             if o.get('controller_id') != self.player_id and o.get('is_creature'))
                if theirs <= ours + 15:
                    continue
            built = self._fill_in(view, a)
            if built is None:
                continue
            score = self._card_value(view, a)
            if counter or oracle_line:
                score += 80
            if oracle:
                score += 120
            if a['type'] == 'activate_ability':
                # Re-equipping an already attached equipment is legal but
                # gains nothing. Likewise, cap repeatable abilities per
                # turn; this memory lives on the session across bot rebuilds.
                obj = self._object(view, a)
                if a.get('attach_kind') and obj.get('attached_to'):
                    continue
                if (obj.get('is_land') and 'add ' in text and 'search your library' not in text
                        and 'becomes' not in text):
                    continue  # a land's mana ability: spells auto-tap it, tapping it now only wastes the mana
                turn = state.get('internal_turn', {}).get('number', 0)
                key = (turn, self._signature(a))
                if self._ability_uses.get(key, 0) >= 64 or self._activation_position(view, a) in self._ability_positions:
                    continue
                score -= 10
                if 'sacrifice' in str(a.get('cost_label', '')).casefold():
                    score -= 20
                    if self._combo_piece(obj.get('name', '')) and 'tutor' not in (plan.roles if plan else ()):
                        continue
                if not text and not a.get('attach_kind'):
                    continue
                # Don't run a combo outlet until another piece is visible.
                if plan and 'sacrifice' in plan.roles and self.strategy.archetype == 'combo':
                    from collections import Counter
                    from mtg_analyzer.services.bot_strategy import normalize
                    board_names = Counter(normalize(o.get('name', '')) for o in state.get('battlefield', [])
                                          if o.get('controller_id') == self.player_id)
                    complete = any(normalize(plan.name) in dict(c.pieces) and
                                   all(board_names[n] >= q for n, q in c.pieces)
                                   for c in self.strategy.combos)
                    if not complete:
                        continue
            candidates.append((score, built, a))
        if main:
            unlock = self._unlock_tap(view, offered_actions, max((c[0] for c in candidates), default=0))
            if unlock is not None:
                return unlock
        if not candidates:
            return None  # preserve mana instead of tapping it without a purpose
        _, built, offer = max(candidates, key=lambda item: item[0])
        if offer['type'] == 'activate_ability':
            turn = state.get('internal_turn', {}).get('number', 0)
            key = (turn, self._signature(offer))
            self._ability_uses[key] = self._ability_uses.get(key, 0) + 1
            self._ability_positions.add(self._activation_position(view, offer))
        return built

    def _unlock_tap(self, view, actions, best_score):
        """Tap a sacrifice / hand-exile mana source so a key permanent becomes castable.

        The engine only offers ``cast_spell`` when plain untapped sources can
        pay (never a Lotus Petal, Treasure or Spirit Guide), although the
        view's mana potential counts them. A combo piece or commander that is
        payable with them but not offered is therefore unlocked by putting
        that mana into the pool first; the next call then sees the cast offer.
        Once per card and turn, so an unexpected refusal cannot burn sources.
        """
        from mtg_analyzer.services.bot_strategy import cost_requirements, normalize
        sources = [a for a in actions if a['type'] == 'activate_hand_mana' or (
            a['type'] == 'tap_for_mana' and 'sacrifice' in str(a.get('cost_label', '')).casefold())]
        if not sources:
            return None
        me = self._mine(view)
        summary = view.get('mana_potential', {}).get(self.player_id, {})
        pool = self.my_pool(view)
        offered = {a.get('instance_id') for a in actions if a['type'] == 'cast_spell'}
        turn = view['state'].get('internal_turn', {}).get('number', 0)
        taxes = me.get('commander_casts') or {}
        command_ids = {o.get('instance_id') for o in me.get('command', [])}
        best = None
        for obj in me.get('hand', []) + me.get('command', []):
            plan = self.strategy.cards.get(normalize(obj.get('name') or ''))
            if (not plan or obj.get('instance_id') in offered or 'land' in plan.types
                    or not PERMANENT_TYPES & set(plan.types.split())
                    or not (self._combo_piece(plan.name) or normalize(plan.name) in self.strategy.commanders)
                    or self._ability_uses.get((turn, ('unlock', plan.name)), 0)):
                continue
            pips, generic = cost_requirements(plan.cost)
            if obj.get('instance_id') in command_ids:
                generic += 2 * taxes.get(str(obj['instance_id']), 0)
            need = sum(pips.values()) + generic
            payable = any(all(v['mana'].get(c, 0) + pool.get(c, 0) >= n for c, n in pips.items())
                          and sum(v['mana'].values()) + sum(pool.values()) >= need
                          for v in summary.get('variations', []))
            if not payable:
                continue
            value = self._card_value(view, {'instance_id': obj['instance_id'], 'name': obj['name']})
            if value > best_score and (best is None or value > best[0]):
                best = (value, plan, pips)
        if best is None:
            return None
        _, plan, pips = best
        self._ability_uses[(turn, ('unlock', plan.name))] = 1
        scarcity = summary.get('open', {})
        # Supply the scarcest colour the card needs and the pool lacks.
        wanted = sorted((c for c, n in pips.items() if pool.get(c, 0) < n), key=lambda c: scarcity.get(c, 0))
        for source in sources:
            options = source.get('options') or []
            for colour in wanted or ['']:
                option = next((o for o in options if colour in o['mana'] or not colour), None)
                if option is not None:
                    return {'type': source['type'], 'instance_id': source['instance_id'],
                            'ability_index': source.get('ability_index', 0), 'option_index': option['index']}
        return None

    def _activation_position(self, view, offer):
        import json
        # Ignore stack ids and logs, which change even when an ability has
        # no effect. Actual resource/board progress permits another use.
        state = view['state']
        players = [(p.get('id'), p.get('life'), p.get('mana_pool'), p.get('library_count'),
                    [o.get('instance_id') for o in p.get('hand', [])]) for p in state.get('players', [])]
        board = [(o.get('instance_id'), o.get('controller_id'), o.get('tapped'), o.get('power'),
                  o.get('toughness'), o.get('counters'), o.get('attached_to'))
                 for o in state.get('battlefield', [])]
        return (state.get('internal_turn', {}).get('number', 0),
                json.dumps([self._signature(offer), players, board], sort_keys=True))

    @staticmethod
    def _stack_controller(item):
        return item.get('controller_id') or (item.get('source') or {}).get('controller_id')

    def _attack(self, view, attacks):
        objects = {o['instance_id']: o for o in view['state'].get('battlefield', [])}
        best = None
        for defender in attacks[0].get('legal_defenders') or []:
            if defender.get('kind') != 'player':
                continue
            blockers = [o for o in objects.values() if o.get('controller_id') == defender['id']
                        and o.get('is_creature') and not o.get('tapped') and not o.get('phased_out')]
            chosen = []
            for offer in attacks:
                if defender not in offer.get('legal_defenders', []):
                    continue
                obj = objects.get(offer['instance_id'], {})
                keywords = set(obj.get('keywords') or ())
                relevant = [b for b in blockers if 'Flying' not in keywords or
                            {'Flying', 'Reach'} & set(b.get('keywords') or ())]
                if self._combo_piece(obj.get('name', '')):
                    continue
                safe = all((b.get('power') or 0) < (obj.get('toughness') or 0) and
                           'Deathtouch' not in (b.get('keywords') or []) for b in relevant)
                if not relevant or (safe and len(relevant) <= 1) or 'Indestructible' in keywords:
                    chosen.append(offer['instance_id'])
            damage = sum(objects.get(i, {}).get('power') or 0 for i in chosen)
            life = next((p.get('life', 40) for p in view['state'].get('players', [])
                         if p['id'] == defender['id']), 40)
            attack_value = (damage >= life, damage, -life)
            if chosen and (best is None or attack_value > best[0]):
                best = (attack_value, chosen, defender)
        if best:
            return {'type': 'attack', 'instance_ids': best[1], 'defender': best[2]}
        return None

    def blocks(self, view, offers):
        objects = {o['instance_id']: o for o in view['state'].get('battlefield', [])}
        assignments = []
        blocked = set()
        life = self._mine(view).get('life', 40)
        incoming = sum((o.get('power') or 0) for o in objects.values()
                       if o.get('attacking') and o.get('controller_id') != self.player_id
                       and (o.get('combat_defender') or {}).get('id') == self.player_id)
        for offer in sorted(offers, key=lambda a: self._card_value(view, a)):
            blocker = objects.get(offer['instance_id'], {})
            candidates = [a for a in offer.get('legal_attackers', []) if a['instance_id'] not in blocked]
            candidates.sort(key=lambda a: objects.get(a['instance_id'], {}).get('power') or 0, reverse=True)
            for candidate in candidates:
                attacker = objects.get(candidate['instance_id'], {})
                if 'Menace' in (attacker.get('keywords') or []):
                    continue  # conservative: never submit a lone menace block
                survives = ('Indestructible' in (blocker.get('keywords') or []) or
                            ((attacker.get('power') or 0) < (blocker.get('toughness') or 0)
                             and 'Deathtouch' not in (attacker.get('keywords') or [])))
                trades = ((blocker.get('power') or 0) >= (attacker.get('toughness') or 1) or
                          ('Deathtouch' in (blocker.get('keywords') or []) and (blocker.get('power') or 0) > 0))
                critical = self._combo_piece(blocker.get('name', ''))
                if incoming >= life or (not critical and (survives or trades)):
                    assignments.append({'blocker': offer['instance_id'], 'attacker': candidate['instance_id']})
                    blocked.add(candidate['instance_id'])
                    break
        return assignments
