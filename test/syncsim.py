"""In-memory model of the lean-com synchronization, for the tests and for protocol work.

Both state machines are generators that yield ('tx', byte) or ('rx', None) and receive the byte read through
send(); the channels are FIFOs. Bytes sent to a side that has not started yet are lost, as on a real link.
The constants are duplicated from leancom.Device on purpose (the test suite checks they are equal), so that
this file runs without the package: python3 test/syncsim.py [cases] [seed]
"""

import random
import sys
from collections import deque

HELLO = bytes.fromhex('DA 42 65 83 2B A0 E6 AA')
MAGIC = bytes.fromhex('BC 02 9D 8A A7 3F')
ACK = bytes.fromhex('2B D7 94 6C E1 38')
GO = bytes.fromhex('93 4A E8 27 5C B1 F6 0E')


def device():
    """leancom_synchronize() of include/leancom.h."""
    for b in HELLO:
        yield ('tx', b)
    window = bytearray()
    while True:  # wait for MAGIC and the session id
        window.append((yield ('rx', None)))
        del window[:-8]
        if len(window) == 8 and window[:6] == MAGIC:
            break
    sid = bytes(window[6:])
    for b in ACK + sid:
        yield ('tx', b)
    window = bytearray()
    while True:  # wait for GO; a MAGIC with another id is a restarted host
        window.append((yield ('rx', None)))
        del window[:-8]
        if window == GO:
            return
        if len(window) == 8 and window[:6] == MAGIC and bytes(window[6:]) != sid:
            sid = bytes(window[6:])
            for b in ACK + sid:
                yield ('tx', b)


def host(sid):
    """Device.synchronize() of leancom/__init__.py, with the session id sid."""
    for b in MAGIC + sid:
        yield ('tx', b)
    window = bytearray()
    while True:
        r = yield ('rx', None)
        window.append(r)
        del window[:-8]
        if len(window) == 8 and window[:6] == ACK:
            if bytes(window[6:]) == sid:
                break
            for b in MAGIC + sid:  # foreign id: the device acknowledged something else
                yield ('tx', b)
        elif r == HELLO[-1]:
            for b in MAGIC + sid:
                yield ('tx', b)
    for b in GO:
        yield ('tx', b)


def run(
    rnd,
    *,
    stale_h2d=b'',
    stale_d2h=b'',
    host_start=0,
    dev_start=0,
    dev_reset_at=None,
    dev_reset_keeps=True,
    host_restart_at=None,
    host_restart_keeps=True,
    max_steps=6000,
):
    """Run one scenario; returns (outcome, leftover host->device, leftover device->host, ids drawn, device done at).

    stale_*: bytes already in a channel at the start. *_start: step at which a side starts; what the peer sends
    before is lost. dev_reset_at / host_restart_at: step at which a side restarts from scratch, keeping or
    dropping what is in its input (*_keeps). The outcome is 'ok', 'deadlock' or 'livelock'.
    """
    queues = {'h2d': deque(stale_h2d), 'd2h': deque(stale_d2h)}
    ids = [rnd.randbytes(2)]
    gen = {'dev': device(), 'host': host(ids[0])}
    start = {'dev': dev_start, 'host': host_start}
    out = {'dev': 'd2h', 'host': 'h2d'}
    inn = {'dev': 'h2d', 'host': 'd2h'}
    peer = {'dev': 'host', 'host': 'dev'}
    op, done, t, dev_done_at = {}, set(), 0, None
    while len(done) < 2 and t < max_steps:
        t += 1
        if dev_reset_at == t and 'dev' not in done:
            gen['dev'] = device()
            op.pop('dev', None)
            if not dev_reset_keeps:
                queues['h2d'].clear()
        if host_restart_at == t and 'host' not in done:
            ids.append(rnd.randbytes(2))
            gen['host'] = host(ids[-1])
            op.pop('host', None)
            if not host_restart_keeps:
                queues['d2h'].clear()
        progressed = False
        for side in ['dev', 'host'] if rnd.random() < 0.5 else ['host', 'dev']:
            if side in done or t < start[side]:
                continue
            try:
                if side not in op:
                    op[side] = next(gen[side])
                    progressed = True
                    continue
                kind, b = op[side]
                if kind == 'tx':
                    if t >= start[peer[side]]:
                        queues[out[side]].append(b)
                    op[side] = gen[side].send(None)
                    progressed = True
                elif queues[inn[side]]:
                    op[side] = gen[side].send(queues[inn[side]].popleft())
                    progressed = True
            except StopIteration:
                done.add(side)
                progressed = True
                if side == 'dev':
                    dev_done_at = t
        pending = (dev_reset_at and t < dev_reset_at) or (host_restart_at and t < host_restart_at)
        if not progressed and all(t >= s for s in start.values()) and not pending:
            return 'deadlock', bytes(queues['h2d']), bytes(queues['d2h']), ids, dev_done_at
    outcome = 'ok' if len(done) == 2 else 'livelock'
    return outcome, bytes(queues['h2d']), bytes(queues['d2h']), ids, dev_done_at


def random_scenario(rnd):
    """Stale bytes and frames in both directions, a start delay, a device reset or a host restart, at random."""
    pool = [*HELLO, *MAGIC, *ACK, *GO, 0, 1, 0x55, 0xFF]

    def stale(n):
        return bytes(rnd.choice(pool) for _ in range(n))

    def part(p):
        k = rnd.randint(1, len(p) - 1)
        return p[:k] if rnd.random() < 0.5 else p[-k:]

    kw = {}
    r = rnd.random()
    if r < 0.3:
        kw['host_start'] = rnd.randint(1, 40)
    elif r < 0.6:
        kw['dev_start'] = rnd.randint(1, 40)
    h2d, d2h = stale(rnd.randint(0, 10)), stale(rnd.randint(0, 10))
    if rnd.random() < 0.3:
        h2d += part(MAGIC) + stale(rnd.randint(0, 3))
    if rnd.random() < 0.3:
        h2d = MAGIC + rnd.randbytes(2) + h2d  # a stale frame retained in the device
    if rnd.random() < 0.3:
        d2h += part(HELLO) + part(ACK)
    if rnd.random() < 0.3:
        d2h = HELLO + ACK + rnd.randbytes(2) + d2h  # a previous session's frames in the host buffer
    if rnd.random() < 0.2:
        d2h = ACK + d2h  # a truncated stale ACK
    kw['stale_h2d'], kw['stale_d2h'] = h2d, d2h
    if rnd.random() < 0.25:
        kw['dev_reset_at'], kw['dev_reset_keeps'] = rnd.randint(2, 70), rnd.random() < 0.5
    if rnd.random() < 0.35:
        kw['host_restart_at'], kw['host_restart_keeps'] = rnd.randint(2, 70), rnd.random() < 0.5
    return kw


def classify(kw, outcome, h2d, d2h, ids):
    """'ok', or why a failure is expected: 'device reset' (the host may have finished first), 'id collision'."""
    if outcome == 'ok' and not h2d and not d2h:
        return 'ok'
    if 'dev_reset_at' in kw:
        return 'device reset'
    if 'host_restart_at' in kw and len(set(ids)) < len(ids):
        return 'id collision'
    return 'unexpected'


def campaign(seed=1, cases=10000):
    """Run random scenarios, return the count of each class."""
    rnd = random.Random(seed)  # noqa: S311
    stats = {}
    for _ in range(cases):
        kw = random_scenario(rnd)
        outcome, h2d, d2h, ids, _ = run(rnd, **kw)
        key = classify(kw, outcome, h2d, d2h, ids)
        stats[key] = stats.get(key, 0) + 1
    return stats


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    for key, count in sorted(campaign(seed, n).items()):
        print(f'{count:7d}  {key}')
