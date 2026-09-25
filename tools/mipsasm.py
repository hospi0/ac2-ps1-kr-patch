# -*- coding: utf-8 -*-
"""아주 작은 MIPS R3000 어셈블러 + 인터프리터

코드 주입은 **시뮬레이터로 먼저 증명한 뒤** 디스크에 쓴다.
→ [[feedback_code_injection_simulate_first]]

  python tools/mipsasm.py test     # 자체 시험
"""
import struct, sys

R = {n: i for i, n in enumerate(
    ['zero', 'at', 'v0', 'v1', 'a0', 'a1', 'a2', 'a3', 't0', 't1', 't2', 't3',
     't4', 't5', 't6', 't7', 's0', 's1', 's2', 's3', 's4', 's5', 's6', 's7',
     't8', 't9', 'k0', 'k1', 'gp', 'sp', 'fp', 'ra'])}


def _i(op, rs, rt, imm):
    return (op << 26) | (R[rs] << 21) | (R[rt] << 16) | (imm & 0xFFFF)


def _r(rs, rt, rd, sa, fn):
    return (R[rs] << 21) | (R[rt] << 16) | (R[rd] << 11) | (sa << 6) | fn


LOADS = {'lhu', 'lw', 'lb', 'lbu', 'lh'}
# ⚠️`divu` 뒤 `mflo`/`mfhi` 는 R3000 이 자동 인터록한다(지연슬롯 아님)
# ★`lw` 두 줄이 연달아 있으면 앞의 것은 뒤 명령에서 안 쓰이므로 위반이 아니다


def check_load_delay(lines):
    """★★R3000 **로드 지연 슬롯** 위반을 잡는다.

    적재한 레지스터는 **바로 다음 명령에서 쓸 수 없다**(옛 값이 보인다).
    ⛔이걸 어겨 검은 화면 4연속이었다(Tobal 2, 2026-08-24).
      시뮬레이터가 이 위험을 모델링하지 않아 「증명 통과」가 거짓말을 했다.
    """
    ins = [x for x in lines if not isinstance(x, str)]
    bad = []
    for a, b in zip(ins, ins[1:]):
        if a[0] not in LOADS:
            continue
        dst = a[1]
        if dst in b[1:]:
            bad.append('%s %s -> 바로 다음 %s 가 %s 를 읽는다' % (a[0], dst, b[0], dst))
    return bad


def assemble(lines, base, extra=None):
    """[(라벨|None, 니모닉, 인수…)] -> (바이트열, 라벨주소)"""
    bad = check_load_delay(lines)
    if bad:
        raise ValueError('로드 지연 슬롯 위반: ' + ' / '.join(bad))
    lab, pc = dict(extra or {}), base
    for x in lines:
        if isinstance(x, str):
            lab[x] = pc
        else:
            pc += 4
    out, pc = bytearray(), base
    for x in lines:
        if isinstance(x, str):
            continue
        m, a = x[0], x[1:]
        if m == 'lui':
            w = _i(0x0F, 'zero', a[0], a[1])
        elif m == 'addiu':
            w = _i(0x09, a[1], a[0], a[2])
        elif m == 'lhu':
            w = _i(0x25, a[2], a[0], a[1])
        elif m == 'addu':
            w = _r(a[1], a[2], a[0], 0, 0x21)
        elif m == 'subu':
            w = _r(a[1], a[2], a[0], 0, 0x23)
        elif m == 'sltu':
            w = _r(a[1], a[2], a[0], 0, 0x2B)
        elif m == 'lw':
            w = _i(0x23, a[2], a[0], a[1])
        elif m == 'lbu':
            w = _i(0x24, a[2], a[0], a[1])
        elif m == 'sb':
            w = _i(0x28, a[2], a[0], a[1])
        elif m == 'ori':
            w = _i(0x0D, a[1], a[0], a[2])
        elif m == 'sh':
            w = _i(0x29, a[2], a[0], a[1])
        elif m == 'sw':
            w = _i(0x2B, a[2], a[0], a[1])
        elif m == 'or':
            w = _r(a[1], a[2], a[0], 0, 0x25)
        elif m == 'divu':
            w = _r(a[0], a[1], 'zero', 0, 0x1B)
        elif m == 'mflo':
            w = _r('zero', 'zero', a[0], 0, 0x12)
        elif m == 'mfhi':
            w = _r('zero', 'zero', a[0], 0, 0x10)
        elif m == 'andi':
            w = _i(0x0C, a[1], a[0], a[2])
        elif m == 'srl':
            w = _r('zero', a[1], a[0], a[2], 0x02)
        elif m == 'sltiu':
            w = _i(0x0B, a[1], a[0], a[2])
        elif m == 'sll':
            w = _r('zero', a[1], a[0], a[2], 0x00)
        elif m == 'beq':
            w = _i(0x04, a[0], a[1], (lab[a[2]] - (pc + 4)) >> 2)
        elif m == 'bne':
            w = _i(0x05, a[0], a[1], (lab[a[2]] - (pc + 4)) >> 2)
        elif m == 'j':
            w = (0x02 << 26) | ((lab[a[0]] >> 2) & 0x3FFFFFF)
        elif m == 'jal':                       # ac2: 스텁이 본체 libcd 를 부른다
            w = (0x03 << 26) | ((lab[a[0]] >> 2) & 0x3FFFFFF)
        elif m == 'jr':
            w = _r(a[0], 'zero', 'zero', 0, 0x08)
        elif m == 'nop':
            w = 0
        else:
            raise ValueError(m)
        out += struct.pack('<I', w)
        pc += 4
    return bytes(out), lab


class Sim:
    """분기 지연슬롯까지 흉내내는 최소 인터프리터"""

    def __init__(self, mem, base):
        self.m = bytearray(mem)      # base 부터의 바이트열
        self.base = base
        self.r = [0] * 32
        self.lo = self.hi = 0
        self.exit_pc = None

    def _ld(self, a, n):
        o = a - self.base
        if o < 0 or o + n > len(self.m):
            raise ValueError('범위 밖 읽기 0x%08X' % a)
        return int.from_bytes(self.m[o:o + n], 'little')

    def _st(self, a, v, n):
        o = a - self.base
        if o < 0 or o + n > len(self.m):
            raise ValueError('범위 밖 쓰기 0x%08X' % a)
        self.m[o:o + n] = (v & ((1 << (n * 8)) - 1)).to_bytes(n, 'little')

    def run(self, pc, code, cbase, maxstep=100000):
        def fetch(p):
            return struct.unpack_from('<I', code, p - cbase)[0]
        step = 0
        while step < maxstep:
            step += 1
            w = fetch(pc)
            op, rs, rt, rd = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
            sa, imm = (w >> 6) & 31, w & 0xFFFF
            s = imm - 0x10000 if imm & 0x8000 else imm
            nxt = pc + 4
            br = None
            if w == 0:
                pass
            elif op == 0 and (w & 63) == 0x21:
                self.r[rd] = (self.r[rs] + self.r[rt]) & 0xFFFFFFFF
            elif op == 0 and (w & 63) == 0x23:
                self.r[rd] = (self.r[rs] - self.r[rt]) & 0xFFFFFFFF
            elif op == 0 and (w & 63) == 0x2B:
                self.r[rd] = 1 if self.r[rs] < self.r[rt] else 0
            elif op == 0x23:
                self.r[rt] = self._ld(self.r[rs] + s, 4)
            elif op == 0 and (w & 63) == 0x00:
                self.r[rd] = (self.r[rt] << sa) & 0xFFFFFFFF
            elif op == 0 and (w & 63) == 0x08:
                br = self.r[rs]
            elif op == 0x0F:
                self.r[rt] = (imm << 16) & 0xFFFFFFFF
            elif op == 0x09:
                self.r[rt] = (self.r[rs] + s) & 0xFFFFFFFF
            elif op == 0x25:
                self.r[rt] = self._ld(self.r[rs] + s, 2)
            elif op == 0x24:
                self.r[rt] = self._ld(self.r[rs] + s, 1)
            elif op == 0x28:
                self._st(self.r[rs] + s, self.r[rt], 1)
            elif op == 0x0D:
                self.r[rt] = self.r[rs] | imm
            elif op == 0x29:
                self._st(self.r[rs] + s, self.r[rt], 2)
            elif op == 0x2B:
                self._st(self.r[rs] + s, self.r[rt], 4)
            elif op == 0 and (w & 63) == 0x25:
                self.r[rd] = self.r[rs] | self.r[rt]
            elif op == 0x0B:
                self.r[rt] = 1 if self.r[rs] < (s & 0xFFFFFFFF) else 0
            elif op == 0x0C:
                self.r[rt] = self.r[rs] & imm
            elif op == 0 and (w & 63) == 0x02:
                self.r[rd] = (self.r[rt] >> sa) & 0xFFFFFFFF
            elif op == 0 and (w & 63) == 0x1B:
                d = self.r[rt]
                self.lo, self.hi = (self.r[rs] // d, self.r[rs] % d) if d else (0, 0)
            elif op == 0 and (w & 63) == 0x12:
                self.r[rd] = self.lo
            elif op == 0 and (w & 63) == 0x10:
                self.r[rd] = self.hi
            elif op == 0x04:
                br = pc + 4 + s * 4 if self.r[rs] == self.r[rt] else None
            elif op == 0x05:
                br = pc + 4 + s * 4 if self.r[rs] != self.r[rt] else None
            elif op == 0x02:
                br = (pc & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
            else:
                raise ValueError('미구현 0x%08X @0x%08X' % (w, pc))
            self.r[0] = 0
            if br is not None:                       # 지연슬롯 한 개 실행
                d = fetch(nxt)
                if d:
                    self.run_one(d)
                if br == 0xB0:
                    return 'BIOS', self.r
                pc = br
                if pc < cbase or pc >= cbase + len(code):
                    self.exit_pc = pc
                    return 'RET', self.r
                continue
            pc = nxt
        raise RuntimeError('무한 루프')

    def run_one(self, w):
        op, rs, rt, rd = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
        sa, imm = (w >> 6) & 31, w & 0xFFFF
        s = imm - 0x10000 if imm & 0x8000 else imm
        if op == 0 and (w & 63) == 0x21:
            self.r[rd] = (self.r[rs] + self.r[rt]) & 0xFFFFFFFF
        elif op == 0 and (w & 63) == 0x00:
            self.r[rd] = (self.r[rt] << sa) & 0xFFFFFFFF
        elif op == 0x09:
            self.r[rt] = (self.r[rs] + s) & 0xFFFFFFFF
        elif op == 0x0F:
            self.r[rt] = (imm << 16) & 0xFFFFFFFF
        elif op == 0x25:
            self.r[rt] = self._ld(self.r[rs] + s, 2)
        else:
            raise ValueError('지연슬롯 미구현 0x%08X' % w)
        self.r[0] = 0


if __name__ == '__main__':
    print('모듈 — tools/patch_kr.py 에서 쓴다')
