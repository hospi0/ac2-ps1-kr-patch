# -*- coding: utf-8 -*-
r"""한글 글리프 훅 — BIOS Krom2RawAdd 호출을 가로채 조합형 한글 16×15 를 돌려준다.

  python tools/krhook.py            # 시뮬레이터 전수 대조만 (쓰기 없음)

## 구조 (docs/01_초기조사.md §8)
```
디스크 LBA 246,564~ (STP 뒤 빈 섹터)  ──CdRead──▶  0x80013000 «낮은 영역 이미지»
  +0      u32 MAGIC
  +4      루틴 (코드 → 이진탐색 → 부품 합성 → 30 B 버퍼 주소 반환 / 없으면 j 썽크)
  …       30 B 버퍼
  …       블롭 (테마 호스피탈 thkr.py 형식: codes[n] · desc[n][3] · pidx[210] · 부품)
본체 EXE (죽은 조각 0x80048874, 468 B)
  TRAMP   0x80013000 에 MAGIC 이 있으면 j 루틴, 없으면 j 썽크   ← 읽기 실패해도 안 죽는다
  STUB    CdIntToPos → CdControl(Setloc) → CdRead(n, 0x80013000, 0x80) → CdReadSync (재시도 8회) → j 0x80063D6C
본체 EXE 수정 3워드
  0x80065230 · 0x80065450   jal 0x8009F248(썽크) → jal TRAMP
  0x80063B54                jal 0x80063D6C → jal STUB      (시작 시 1회: 0x800619C0 → 0x80063B34)
```
글리프 30 B = 15행 × u16, 행의 byte0 = 왼쪽 8픽셀(MSB 가 왼쪽) — 변환 함수 0x80065220 이 `lhu` 후
하위 바이트 0x80 부터 읽는 것과 일치(BIOS 형식과 같다).
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import johab
import mipsasm as M

LOW = 0x80013000
LOW_LIMIT = 0x80016800            # 위는 부트 로더 파일 정보(0x80016800~)
LOW_FLOOR = 0x80012E30            # 아래는 세이브 이미지(0x80010E30 + 8 KB)
MAGIC = 0x4B524654
THUNK = 0x8009F248
HOOKS = (0x80065230, 0x80065450)
INIT_SITE, INIT_TARGET = 0x80063B54, 0x80063D6C
DEAD, DEAD_END = 0x80048874, 0x80048A48
CD_INTTOPOS, CD_CONTROL, CD_READ, CD_READSYNC = 0x800A6D64, 0x800A6B9C, 0x800A94A4, 0x800A9584
BLOB_LBA = 246564
NPART = 210
HORZ = set('ㅗㅛㅜㅠㅡ')


def jal(t):
    return 0x0C000000 | ((t >> 2) & 0x3FFFFFF)


def hilo(addr):
    lo = addr & 0xFFFF
    return (addr >> 16) + (1 if lo >= 0x8000 else 0), (lo - 0x10000 if lo >= 0x8000 else lo)


# ── 부품·블롭 (thkr.py 와 같은 형식)
def part_index(key):
    if key[0] == 'C':
        _, c, grp, f = key
        return c * 6 + grp * 2 + f
    if key[0] == 'V':
        _, v, f = key
        return 114 + v * 2 + f
    _, j, k = key
    return 156 + (j - 1) * 2 + k


def pack_parts(P):
    blobs, off, uniq = bytearray(), [0] * NPART, {}
    for key, g in P.items():
        ink = [y for y in range(johab.H) if any(g[y])]
        if not ink:
            rec = bytes([0, 0])
        else:
            t, n = ink[0], ink[-1] - ink[0] + 1
            b = bytearray([t, n])
            for y in range(t, t + n):
                v = 0
                for x in range(johab.W):
                    if g[y][x]:
                        v |= 1 << (15 - x)
                b += bytes([v >> 8, v & 0xFF])
            rec = bytes(b)
        if rec not in uniq:
            uniq[rec] = len(blobs)
            blobs += rec
        off[part_index(key)] = uniq[rec]
    return bytes(blobs), off


def desc_of(ch):
    u = ord(ch) - 0xAC00
    c, v, f = u // 588, (u % 588) // 28, u % 28
    cs = 0 if johab.JUNG[v] in johab.VERT else (1 if johab.JUNG[v] in HORZ else 2)
    jf = 1 if f else 0
    return (part_index(('C', c, cs, jf)), part_index(('V', v, jf)),
            part_index(('J', f, 0 if cs == 0 else 1)) if f else 0xFF)


def build_blob(rows, P):
    """rows = [(코드, 음절)] (코드 오름차순)"""
    parts, poff = pack_parts(P)
    n = len(rows)
    off_codes = 12
    off_desc = off_codes + 2 * n
    off_pidx = (off_desc + 3 * n + 1) & ~1
    off_parts = off_pidx + 2 * NPART
    b = bytearray(off_parts)
    struct.pack_into('<IHHHH', b, 0, MAGIC, n, off_codes, off_desc, off_pidx)
    for i, (c, ch) in enumerate(rows):
        struct.pack_into('<H', b, off_codes + 2 * i, c)
        b[off_desc + 3 * i:off_desc + 3 * i + 3] = bytes(desc_of(ch))
    for i in range(NPART):
        struct.pack_into('<H', b, off_pidx + 2 * i, off_parts + poff[i])
    return bytes(b + parts)


# ── 루틴 (낮은 영역) — thkr.routine 에서 «블롭 = 고정 주소»로 바꾼 것
def routine(blob, buf):
    bh, bl = hilo(blob)
    xh, xl = hilo(buf)
    L = []
    A = L.append
    A(('lui', 't0', bh)); A(('addiu', 't0', 't0', bl))    # t0 = blob
    A(('lhu', 't1', 4, 't0'))                             # n
    A(('lhu', 't2', 6, 't0'))                             # off_codes
    A(('lhu', 't9', 10, 't0'))                            # off_pidx
    A(('addu', 't2', 't2', 't0'))
    A(('addu', 't9', 't9', 't0'))
    A(('addu', 't3', 'zero', 'zero'))                     # lo
    A(('addu', 't4', 't1', 'zero'))                       # hi
    A('BS')
    A(('beq', 't3', 't4', 'MISS')); A(('nop',))
    A(('addu', 't5', 't3', 't4'))
    A(('srl', 't5', 't5', 1))
    A(('sll', 't6', 't5', 1))
    A(('addu', 't6', 't6', 't2'))
    A(('lhu', 't6', 0, 't6')); A(('nop',))
    A(('beq', 't6', 'a0', 'FOUND')); A(('nop',))
    A(('sltu', 't7', 't6', 'a0'))
    A(('beq', 't7', 'zero', 'LOW')); A(('nop',))
    A(('addiu', 't3', 't5', 1))
    A(('j', 'BS')); A(('nop',))
    A('LOW')
    A(('addu', 't4', 't5', 'zero'))
    A(('j', 'BS')); A(('nop',))
    A('FOUND')
    A(('lhu', 'a2', 8, 't0'))                             # off_desc
    A(('sll', 't7', 't5', 1))
    A(('addu', 't7', 't7', 't5'))                         # mid*3
    A(('addu', 'a2', 'a2', 't0'))
    A(('addu', 'a2', 'a2', 't7'))
    A(('lui', 't8', xh)); A(('addiu', 't8', 't8', xl))
    for k in range(0, 28, 4):
        A(('sw', 'zero', k, 't8'))
    A(('sh', 'zero', 28, 't8'))
    A(('addu', 'a1', 'zero', 'zero'))
    A('DL')
    A(('addu', 'v1', 'a1', 'a2'))
    A(('lbu', 'v1', 0, 'v1'))
    A(('addiu', 'a3', 'zero', 0xFF))
    A(('beq', 'v1', 'a3', 'DSKIP')); A(('nop',))
    A(('sll', 'v1', 'v1', 1))
    A(('addu', 'v1', 'v1', 't9'))
    A(('lhu', 'v1', 0, 'v1')); A(('nop',))
    A(('addu', 'v1', 'v1', 't0'))
    A(('lbu', 't6', 0, 'v1'))                             # top
    A(('lbu', 't7', 1, 'v1'))                             # nrows
    A(('sll', 't6', 't6', 1))
    A(('addu', 't6', 't6', 't8'))
    A(('addiu', 'v1', 'v1', 2))
    A('RL')
    A(('beq', 't7', 'zero', 'DSKIP')); A(('nop',))
    A(('lbu', 'a3', 0, 'v1'))
    A(('lbu', 'v0', 0, 't6')); A(('nop',))
    A(('or', 'v0', 'v0', 'a3'))
    A(('sb', 'v0', 0, 't6'))
    A(('lbu', 'a3', 1, 'v1'))
    A(('lbu', 'v0', 1, 't6')); A(('nop',))
    A(('or', 'v0', 'v0', 'a3'))
    A(('sb', 'v0', 1, 't6'))
    A(('addiu', 'v1', 'v1', 2))
    A(('addiu', 't6', 't6', 2))
    A(('addiu', 't7', 't7', -1))
    A(('j', 'RL')); A(('nop',))
    A('DSKIP')
    A(('addiu', 'a1', 'a1', 1))
    A(('addiu', 'a3', 'zero', 3))
    A(('bne', 'a1', 'a3', 'DL')); A(('nop',))
    A(('addu', 'v0', 't8', 'zero'))
    A(('jr', 'ra')); A(('nop',))
    A('MISS')
    A(('j', 'THUNK')); A(('nop',))
    return L


# ── EXE 쪽 (죽은 조각)
def exe_code(routine_addr, nsec):
    lh, ll = hilo(LOW)
    L = []
    A = L.append
    A('TRAMP')
    A(('lui', 't0', lh))
    A(('lw', 't1', ll, 't0'))
    A(('lui', 't2', MAGIC >> 16))
    A(('ori', 't2', 't2', MAGIC & 0xFFFF))
    A(('bne', 't1', 't2', 'TMISS')); A(('nop',))
    A(('j', 'ROUTINE')); A(('nop',))
    A('TMISS')
    A(('j', 'THUNK')); A(('nop',))
    A('STUB')
    A(('addiu', 'sp', 'sp', -32))
    A(('sw', 'ra', 24, 'sp'))
    A(('sw', 's0', 20, 'sp'))
    A(('addiu', 's0', 'zero', 8))                         # 재시도 횟수
    A('RETRY')
    A(('beq', 's0', 'zero', 'DONE'))
    A(('addiu', 's0', 's0', -1))
    A(('lui', 'a0', BLOB_LBA >> 16))
    A(('ori', 'a0', 'a0', BLOB_LBA & 0xFFFF))
    A(('jal', 'CD_INTTOPOS'))
    A(('addiu', 'a1', 'sp', 16))
    A(('addiu', 'a0', 'zero', 2))                         # CdlSetloc
    A(('addiu', 'a1', 'sp', 16))
    A(('jal', 'CD_CONTROL'))
    A(('addiu', 'a2', 'zero', 0))
    A(('beq', 'v0', 'zero', 'RETRY')); A(('nop',))
    A(('addiu', 'a0', 'zero', nsec))
    A(('lui', 'a1', lh))
    A(('addiu', 'a1', 'a1', ll))
    A(('jal', 'CD_READ'))
    A(('addiu', 'a2', 'zero', 0x80))
    A(('beq', 'v0', 'zero', 'RETRY')); A(('nop',))
    A(('addiu', 'a0', 'zero', 0))
    A(('jal', 'CD_READSYNC'))
    A(('addiu', 'a1', 'zero', 0))
    A(('bne', 'v0', 'zero', 'RETRY')); A(('nop',))
    A('DONE')
    A(('lw', 'ra', 24, 'sp'))
    A(('lw', 's0', 20, 'sp'))
    A(('addiu', 'sp', 'sp', 32))
    A(('j', 'INIT_TARGET')); A(('nop',))
    extra = {'ROUTINE': routine_addr, 'THUNK': THUNK, 'INIT_TARGET': INIT_TARGET,
             'CD_INTTOPOS': CD_INTTOPOS, 'CD_CONTROL': CD_CONTROL,
             'CD_READ': CD_READ, 'CD_READSYNC': CD_READSYNC}
    return M.assemble(L, DEAD, extra=extra)


def glyph_bytes(P, ch):
    g = johab.compose(P, ch)
    out = bytearray()
    for y in range(15):
        v = 0
        for x in range(16):
            if g[y][x]:
                v |= 1 << (15 - x)
        out += bytes([v >> 8, v & 0xFF])
    return bytes(out)


def build(rows):
    """rows=[(코드, 음절)] → (낮은 영역 이미지, EXE 조각 코드, 라벨, 섹터 수, P)"""
    rows = sorted(rows)
    P = johab.build()
    blob_tmp = build_blob(rows, P)
    ncode = sum(1 for x in routine(0, 0) if not isinstance(x, str)) * 4
    r_addr = LOW + 4
    buf = (r_addr + ncode + 3) & ~3
    blob_addr = (buf + 32 + 3) & ~3
    code, _ = M.assemble(routine(blob_addr, buf), r_addr, extra={'THUNK': THUNK})
    assert len(code) == ncode
    img = bytearray(blob_addr - LOW)
    struct.pack_into('<I', img, 0, MAGIC)
    img[4:4 + len(code)] = code
    img += blob_tmp
    nsec = (len(img) + 2047) // 2048
    if LOW + nsec * 2048 > LOW_LIMIT or LOW < LOW_FLOOR:
        raise SystemExit('⛔ 낮은 영역 이미지 %d B (섹터 %d) 가 0x%08X 를 넘는다' % (len(img), nsec, LOW_LIMIT))
    ecode, elab = exe_code(r_addr, nsec)
    if DEAD + len(ecode) > DEAD_END:
        raise SystemExit('⛔ EXE 조각 코드 %d B 가 죽은 조각(%d B)을 넘는다' % (len(ecode), DEAD_END - DEAD))
    return bytes(img), ecode, elab, nsec, P, r_addr, buf


def pool_base(img):
    """낮은 영역 이미지 뒤에 붙일 «문자열 풀»의 시작 주소 (4 정렬)."""
    return LOW + ((len(img) + 3) & ~3)


def finalize(img, r_addr, tail=b''):
    """이미지 + 꼬리(문자열 풀) → 최종 이미지·섹터 수·EXE 조각(스텁의 섹터 수 반영)."""
    full = bytearray(img)
    full += bytes(pool_base(img) - LOW - len(img))
    full += tail
    nsec = (len(full) + 2047) // 2048
    if LOW + nsec * 2048 > LOW_LIMIT:
        raise SystemExit('⛔ 낮은 영역 %d B (섹터 %d) 가 0x%08X 를 넘는다 — 풀 %d B 를 줄여야 한다'
                         % (len(full), nsec, LOW_LIMIT, len(tail)))
    ecode, elab = exe_code(r_addr, nsec)
    if DEAD + len(ecode) > DEAD_END:
        raise SystemExit('⛔ EXE 조각 코드가 죽은 조각을 넘는다')
    return bytes(full), nsec, ecode, elab


def verify(rows, img, ecode, elab, P, r_addr):
    """시뮬레이터 전수 대조 — 한글 전부 · 비한글은 썽크로 · 트램펄린 매직 유/무."""
    RAM = bytearray(2 * 1024 * 1024)
    RAM[LOW - 0x80000000:LOW - 0x80000000 + len(img)] = img
    code = img[4:]
    sim = M.Sim(RAM, 0x80000000)
    bad = 0
    for c, ch in rows:
        sim.r = [0] * 32; sim.r[4] = c; sim.r[31] = 0x7FFFFFF0
        st, r = sim.run(r_addr, code, r_addr)
        if st != 'RET' or sim.exit_pc != 0x7FFFFFF0:
            bad += 1; print('  ⛔ %s(%04X) 가 썽크로 샜다' % (ch, c)); continue
        got = bytes(sim.m[r[2] - 0x80000000:r[2] - 0x80000000 + 30])
        if got != glyph_bytes(P, ch):
            bad += 1; print('  ⛔ %s(%04X) 글리프 불일치' % (ch, c))
    have = {c for c, _ in rows}
    for c in (0x8140, 0x824F, 0x82A0, 0x8341, 0x889E, 0x9FFC, 0x88A0 if 0x88A0 not in have else 0x9872):
        if c in have:
            continue
        sim.r = [0] * 32; sim.r[4] = c; sim.r[31] = 0x7FFFFFF0
        sim.run(r_addr, code, r_addr)
        if sim.exit_pc != THUNK:
            bad += 1; print('  ⛔ 비한글 %04X 가 썽크로 안 갔다' % c)
    # 트램펄린
    t0 = elab['TRAMP']
    for have_magic, want in ((True, r_addr), (False, THUNK)):
        R2 = bytearray(RAM) if have_magic else bytearray(2 * 1024 * 1024)
        s2 = M.Sim(R2, 0x80000000); s2.r = [0] * 32; s2.r[4] = 0x889F
        s2.run(t0, ecode, DEAD)
        if s2.exit_pc != want or s2.r[4] != 0x889F:
            bad += 1; print('  ⛔ 트램펄린(매직 %s) → %08X (기대 %08X)' % (have_magic, s2.exit_pc, want))
    return bad


if __name__ == '__main__':
    demo = [(0x889F + i, ch) for i, ch in enumerate('가나다라마바사아자차카타파하힣')]
    img, ecode, elab, nsec, P, r_addr, buf = build(demo)
    print('낮은 영역 이미지 %d B (%d 섹터) · 루틴 %08X · 버퍼 %08X · EXE 조각 %d B' % (len(img), nsec, r_addr, buf, len(ecode)))
    bad = verify(sorted(demo), img, ecode, elab, P, r_addr)
    print('시뮬 대조 실패 %d' % bad)
