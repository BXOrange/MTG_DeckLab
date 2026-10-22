"""Deterministic paired policy campaigns; policy never receives the engine.

This developer harness intentionally separates fixture setup/measurement from
bot inputs. No production DB is opened here; a caller supplies resolved cards.
"""
from __future__ import annotations
from collections import Counter
from contextlib import contextmanager
import hashlib
import itertools
import random
import time

from mtg_analyzer.services.bots import _one_bot_action, GoldfishBot
from mtg_analyzer.services.game_session import GameSessionManager
from .context import stable

# A campaign limit is recorded as censoring, never silently a loss.
DEFAULT_ACTION_BUDGET = 400
DEFAULT_TURN_BUDGET = 12


@contextmanager
def seeded_random(seed):
    """Session setup currently uses global shuffles; restore caller RNG after."""
    saved = random.getstate()
    random.seed(seed)
    try:
        yield
    finally:
        random.setstate(saved)


def _run_match(cards, commanders, policy, *, seed=0, seat=0, opponent_cards=None,
              opponent_policy=GoldfishBot, action_budget=DEFAULT_ACTION_BUDGET,
              turn_budget=DEFAULT_TURN_BUDGET, archetypes=None):
    # Allocation IDs also affect deterministic tie-breaking. This is a
    # standalone test harness, never called by the server driver. Restore
    # them after the match rather than altering a live application's IDs.
    from mtg_analyzer.models.game import game_object
    opponent_cards = list(opponent_cards or cards)
    seats = [dict(player_id='candidate',name='Candidate',library=list(cards),commanders=list(commanders),archetypes=archetypes),
             dict(player_id='opponent',name='Opponent',library=opponent_cards,commanders=[])]
    if seat:
        seats.reverse()
    rng = random.Random(seed)
    # The session builder consumes a pre-shuffled list (the live API does
    # the shuffle). Keep each player's starting order independent of seat.
    for entry in sorted(seats,key=lambda entry:entry['player_id']):
        rng.shuffle(entry['library'])
    session = GameSessionManager().create_multiplayer(seats,mulligan_style='london')
    # Pin rules randomness separately from shuffling; stable object allocation
    # IDs are not used as random seeds by the policy.
    session.engine.state.rng_seed = seed
    measured_times, failures = [], []
    class Measured(policy):
        def decide(self, view, actions):
            start = time.perf_counter()
            result = super().decide(view, actions)
            measured_times.append((time.perf_counter()-start)*1000)
            return result
        def note_failure(self, action, error):
            failures.append({'action_type':action.get('type'),'error':str(error)})
            return super().note_failure(action,error)
    bots = {'candidate': Measured('candidate'), 'opponent': opponent_policy('opponent')}
    for pid,b in bots.items():
        b._vote_rng.seed(seed)
    latencies, fingerprints, errors, counts = [], [], [], Counter()
    original_apply = session.apply_action
    def measured_apply(action, actor_id=None):
        # Empty-stack priority passes are pure forward progress. Avoid the
        # undo history copy just for these frames (as dynamic_analysis does
        # for all frames), retaining full rollback for chosen spells/choices.
        old_history = session._keep_history
        if action.get('type') == 'pass_priority' and not session.engine.state.stack and not session.engine.state.pending_choice:
            session._keep_history = False
        try:
            result = original_apply(action, actor_id=actor_id)
        finally:
            session._keep_history = old_history
        if actor_id == 'candidate':
            counts[action.get('type','unknown')] += 1
            # Allocation counters from other rules subsystems need not be
            # process-global identical: hash the semantic chosen action.
            canonical = {k:v for k,v in action.items() if k in
                ('type','instance_id','instance_ids','ability_index','mode','x','kicked',
                 'option_id','sacrifice_choice','sacrifice_choices','tap_choices','discard_choices')}
            if action.get('targets'):
                canonical['targets'] = [{k:v for k,v in t.items() if k!='stack_id'} for t in action['targets']]
            fingerprints.append(canonical)
        return result
    session.apply_action = measured_apply
    status = 'action_budget'
    for _ in range(action_budget):
        state = session.engine.state
        if state.game_over:
            status = 'won' if state.winner_id == 'candidate' else 'lost' if state.winner_id else 'draw'
            break
        if state.internal_turn.number > turn_budget:
            status = 'turn_budget'
            break
        progressed = False
        for pid,b in bots.items():
            start = time.perf_counter()
            try:
                moved = _one_bot_action(session,{pid:b})
            except Exception as exc:  # campaigns must account for every attempted match
                errors.append(f'{type(exc).__name__}: {exc}')
                status='error'
                break
            elapsed = (time.perf_counter()-start)*1000
            if pid == 'candidate':
                latencies.append(elapsed)
            if moved:
                progressed=True
                break
        if errors:
            break
        if not progressed:
            status='stalled'
            break
    else:
        if session.engine.state.game_over:
            status = 'won' if session.engine.state.winner_id == 'candidate' else 'lost'
    ordered=sorted(measured_times)
    percentile=lambda f: ordered[min(len(ordered)-1,int((len(ordered)-1)*f))] if ordered else 0
    return {'seed':seed,'seat':seat,'status':status,'turn':session.engine.state.internal_turn.number,
            'actions':dict(counts),'errors':errors,'rejections':failures,
            'decision_ms':{'p50':percentile(.5),'p95':percentile(.95),'p99':percentile(.99)},
            'decision_count':len(measured_times),'trace_digest':hashlib.sha256(stable(fingerprints).encode()).hexdigest()}


def run_match(*args, **kwargs):
    """Run in a single benchmark worker; restore global allocation state."""
    from mtg_analyzer.models.game import game_object
    saved_counter = game_object._instance_counter
    game_object._instance_counter = itertools.count(1)
    try:
        with seeded_random(kwargs.get('seed', 0)):
            return _run_match(*args, **kwargs)
    finally:
        game_object._instance_counter = saved_counter
