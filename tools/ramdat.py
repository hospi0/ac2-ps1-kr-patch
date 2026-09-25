# -*- coding: utf-8 -*-
"""세이브스테이트 RAM 에 DAT 의 어느 조각이 어디 올라와 있는지 (적재 지도).

  python tools/ramdat.py 1 2 3 4 5          # work/state/<n>/ram.bin 사용

조각 = 목차 226항목 + 꼬리 표(본체 EXE 0x800AD8EC, 2048 B 단위 오름차순)의 각 시작점.
각 조각의 «앞 64 B»와 «중간 표본 몇 개»를 RAM 에서 찾아 적재 주소를 뽑는다.
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
W = os.path.join(HERE, '..', 'work')
d = open(os.path.join(W, 'ACE2.DAT'), 'rb').read()
X = open(os.path.join(W, 'ACE2MAIN.EXE'), 'rb').read()
n = struct.unpack_from('<I', d, 4)[0]
pieces = []
for i in range(n):
    s, o = struct.unpack_from('<II', d, 8 + 8 * i)
    pieces.append(('E%03d' % i, o * 512, s & 0x0FFFFFFF))
# 꼬리 표
T = 0x800AD8EC - 0x80018000 + 0x800
secs = []
p = T
while True:
    v = struct.unpack_from('<I', X, p)[0]
    if secs and v <= secs[-1] or v * 2048 >= len(d):
        break
    secs.append(v); p += 4
for k, v in enumerate(secs):
    a = v * 2048
    e = secs[k + 1] * 2048 if k + 1 < len(secs) else a + 0x10000
    pieces.append(('T%03d' % k, a, e - a))


def locate(ram, off, size):
    """조각 안 여러 표본(64 B)의 RAM 위치 → 같은 적재 기준이면 채택."""
    votes = {}
    for f in (0, 0x40, 0x800, 0x1000, size // 2, size - 0x80):
        if f < 0 or f + 64 > size:
            continue
        blob = d[off + f:off + f + 64]
        if not any(blob) or len(set(blob)) < 6:
            continue
        i = ram.find(blob)
        while i >= 0:
            base = 0x80000000 + i - f
            votes[base] = votes.get(base, 0) + 1
            i = ram.find(blob, i + 1)
    good = [(b, c) for b, c in votes.items() if c >= 2]
    return sorted(good, key=lambda x: -x[1])


for k in sys.argv[1:]:
    ram = open(os.path.join(W, 'state', k, 'ram.bin'), 'rb').read()
    print('== 상태', k)
    rows = []
    for nm, off, size in pieces:
        for base, c in locate(ram, off, size)[:2]:
            rows.append((base, base + size, nm, off, size, c))
    for base, end, nm, off, size, c in sorted(rows):
        print('  %08X..%08X  %-5s DAT+%08X  %7d B  표본일치 %d' % (base, end, nm, off, size, c))
