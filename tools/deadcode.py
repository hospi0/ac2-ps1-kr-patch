# -*- coding: utf-8 -*-
"""본체 EXE 죽은 함수 census — 폰트·훅 루틴을 둘 자리 후보.

  python tools/deadcode.py            # 참조 0 함수 목록과 합계

함수 = `addiu sp,sp,-N` 머리부터 다음 머리 직전까지(잎 함수는 jr ra 경계로 보조).
참조 = jal / j 목표 · 32비트 절대주소 값(데이터 표·함수 포인터) · lui+addiu/ori 쌍.
⛔ «참조 0» 은 후보일 뿐이다 — 레지스터 산술로 만든 주소·다른 모듈(오버레이)의 참조는 못 본다.
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdis
D, BASE, HDR = mdis.D, mdis.BASE, mdis.HDR
T = D[HDR:]
END = BASE + len(T)
W = [struct.unpack_from('<I', T, p)[0] for p in range(0, len(T) - 3, 4)]

# 함수 머리
heads = [BASE + 4 * i for i, w in enumerate(W) if w >> 16 == 0x27BD and w & 0x8000]
# 잎 함수 보조: jr ra + 지연 슬롯 다음 주소도 머리 후보
for i, w in enumerate(W[:-2]):
    if w == 0x03E00008:
        heads.append(BASE + 4 * (i + 2))
heads = sorted(set(h for h in heads if h < END))

refs = {}
def add(t, src):
    refs.setdefault(t, []).append(src)
for i, w in enumerate(W):
    a = BASE + 4 * i
    op = w >> 26
    if op in (2, 3):
        add((a & 0xF0000000) | ((w & 0x3FFFFFF) << 2), a)
    if BASE <= w < END:
        add(w, a)
    if op == 0x0F:
        rt = (w >> 16) & 31; hi = (w & 0xFFFF) << 16
        for k in range(1, 12):
            if i + k >= len(W): break
            y = W[i + k]
            if (y >> 26) in (0x09, 0x0D) and (y >> 21) & 31 == rt:
                lo = y & 0xFFFF
                v = (hi + (lo - 0x10000 if (y >> 26) == 0x09 and lo & 0x8000 else lo)) & 0xFFFFFFFF
                add(v, a)
                break

# ⛔ prologue 를 머리로 믿으면 안 된다 — 컴파일러가 `lw` 를 prologue 앞으로 당겨 둔다
#    (0x8002888C lw → 0x80028894 addiu sp: «머리» 0x80028894 는 참조 0 이지만 진짜 시작은 참조됨).
#    그래서 블록 = «앞 jr ra 의 지연 슬롯 다음» ~ «이 jr ra 의 지연 슬롯» 으로 자르고,
#    블록 안 «어느 주소»든 참조되면 살아 있는 것으로 본다. 앞 블록이 jr ra 없이 끝나면(= fall-through) 합친다.
ends = [BASE + 4 * (i + 2) for i, w in enumerate(W[:-2]) if w == 0x03E00008]
blocks = []
s = BASE
for e in ends:
    if e > s:
        blocks.append((s, e))
        s = e
dead = []
for s, e in blocks:
    if e - s < 16:
        continue
    if any(t in refs for t in range(s, e, 4)):
        continue
    # 블록 머리의 nop 패딩만 있는 경우 제외
    body = [W[(a - BASE) // 4] for a in range(s, e, 4)]
    if all(x == 0 for x in body):
        continue
    dead.append((s, e))
tot = sum(e - h for h, e in dead)
if __name__ == '__main__':
    print('함수 머리 %d개 · 참조 0 함수 %d개 · 합계 %d B' % (len(heads), len(dead), tot))
    # 연속 구간으로 묶기
    runs = []
    for h, e in dead:
        if runs and runs[-1][1] >= h - 8:
            runs[-1][1] = e
        else:
            runs.append([h, e])
    runs.sort(key=lambda r: -(r[1] - r[0]))
    print('연속 구간 상위:')
    for s, e in runs[:25]:
        print('  %08X..%08X  %6d B' % (s, e, e - s))
