# -*- coding: utf-8 -*-
"""에이스컴뱃2 본체 EXE 역어셈블. 본체는 ACE2.DAT+0x800 의 PS-X EXE (적재 0x80018000).

  python tools/mdis.py 0x80065200 0x100          # 주소 구간
  python tools/mdis.py --func 0x80065230         # 그 주소를 품은 함수 전체 + 호출자

## 배치 (실측)
```
ACE2.DAT+0x800   PS-X EXE 머리 (pc 0x8001CB50 · t_addr 0x80018000 · t_size 0xA1800)
ACE2.DAT+0x1000  = 0x80018000   (파일→주소: a = 0x80018000 + (f - 0x1000))
```
work/ACE2MAIN.EXE 가 없으면 DAT 에서 뽑아 만든다.
"""
import os, struct, sys
import capstone

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, '..', 'work')
EXE = os.path.join(WORK, 'ACE2MAIN.EXE')
BASE, HDR = 0x80018000, 0x800


def load():
    if not os.path.exists(EXE):
        d = open(os.path.join(WORK, 'ACE2.DAT'), 'rb').read()
        assert d[0x800:0x808] == b'PS-X EXE'
        t_addr, t_size = struct.unpack_from('<II', d, 0x818)
        assert t_addr == BASE
        open(EXE, 'wb').write(d[0x800:0x1000 + t_size])
    return open(EXE, 'rb').read()


D = load()
MD = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)


def word(a):
    return struct.unpack_from('<I', D, a - BASE + HDR)[0]


def dis(a, n):
    off = a - BASE + HDR
    for ins in MD.disasm(D[off:off + n], a):
        print('%08x  %08x  %-8s %s' % (ins.address, word(ins.address), ins.mnemonic, ins.op_str))


def func_bounds(a):
    s = a & ~3
    while s > BASE:
        w = word(s)
        if w >> 16 == 0x27BD and (w & 0x8000):      # addiu sp,sp,-N
            break
        s -= 4
    e = a & ~3
    end = BASE + len(D) - HDR
    while e < end:
        if word(e) == 0x03E00008:                   # jr ra
            e += 8
            break
        e += 4
    return s, e


def callers(t):
    out = []
    for p in range(HDR, len(D) - 3, 4):
        w = struct.unpack_from('<I', D, p)[0]
        if w >> 26 == 3 and (BASE & 0xF0000000) | ((w & 0x3FFFFFF) << 2) == t:
            out.append(BASE + p - HDR)
    return out


if __name__ == '__main__':
    if sys.argv[1] == '--func':
        a = int(sys.argv[2], 16)
        s, e = func_bounds(a)
        print('함수 %08X..%08X  호출자 %s' % (s, e, [hex(c) for c in callers(s)]))
        dis(s, e - s)
    else:
        dis(int(sys.argv[1], 16), int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x80)
