# -*- coding: utf-8 -*-
r"""본 빌드 — 번역표(work/text/*.tsv) → 한글 디스크 이미지.

  python tools/build.py                 # 드라이런 (검사 · 배치 · 변경 census · 시뮬 대조) — 쓰기 없음
  python tools/build.py --write 0.1     # work/out/AC2_KR.bin(+cue) · F: 설치본 교체 · dist/AC2_KR_v0.1.xdelta

순서
  ① krcheck (오류면 중단)  ② 한글 음절 → 0x889F~ 코드 배정 · 블롭(krhook)
  ③ BRF·RAD: 모든 사본 칸에 제자리 (번역 + NUL, 칸 나머지는 원본 그대로)
  ④ EXE: 원문 자리에 들어가면 제자리(남는 바이트 0), 넘치면 «문자열 풀»(낮은 영역 이미지 뒤)로 옮기고 u32 포인터 전부 교체
     (lui/addiu 쌍 참조 문장은 이주 금지 — 3개뿐)
  ⑤ 훅 2곳 · 초기화 스텁 · 트램펄린 (build_poc 와 같음) · 디스크 끝 빈 섹터에 낮은 영역 이미지
  ⑥ census: 바뀐 바이트가 모두 계획 범위 안 · 되읽기 · EDC · 블롭 대조
"""
import hashlib, os, shutil, struct, subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, HERE)
import krhook as K
import krcheck as C
import ac2text as T
from cdsector import fix_sector, edc

ORIG = r'C:\claude\roms\ps\Ace Combat 2 (Japan) (Rev 1)\Ace Combat 2 (Japan) (Rev 1).bin'
ORIG_MD5 = 'ECE1E7B3F995B67483B94F98401BB925'
FDST = r'F:\hospi\roms\ps roms\Ace Combat 2 (Japan) (Rev 1)\Ace Combat 2 (Japan) (Rev 1).bin'   # 사용자 실행본
OUTDIR = os.path.join(ROOT, 'work', 'out')
OUT = os.path.join(OUTDIR, 'AC2_KR.bin')
XD = r'C:\claude\utils\xdelta.exe'
RAW, UOFF, DAT_LBA = 2352, 24, 73


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest().upper()


class Disc:
    def __init__(self, path):
        self.f = open(path, 'rb'); self.mod = {}

    def sector(self, lba):
        if lba in self.mod:
            return self.mod[lba]
        self.f.seek(lba * RAW)
        return bytearray(self.f.read(RAW))

    def read(self, off, n):                     # DAT 오프셋
        out = bytearray()
        while n:
            lba, o = DAT_LBA + off // 2048, off % 2048
            k = min(n, 2048 - o)
            out += self.sector(lba)[UOFF + o:UOFF + o + k]
            off += k; n -= k
        return bytes(out)

    def write(self, off, data):
        i = 0
        while i < len(data):
            lba, o = DAT_LBA + off // 2048, off % 2048
            k = min(len(data) - i, 2048 - o)
            sec = self.sector(lba)
            assert sec[15] == 2 and not (sec[18] & 0x20), 'DAT 섹터 %d 가 Form1 이 아니다' % lba
            sec[UOFF + o:UOFF + o + k] = data[i:i + k]
            self.mod[lba] = sec
            off += k; i += k


def plan():
    ne, nw, tr, cmap, base, strides = C.check()
    if ne:
        raise SystemExit('⛔ 검사 오류 %d — 빌드하지 않는다' % ne)
    rows = sorted((c, ch) for ch, c in cmap.items())
    if not rows:                                        # 번역 0 이면 PoC 음절로 루틴만
        rows = [(0x889F, '가')]
    img0, _, _, _, P, r_addr, buf = K.build(rows)
    patches = []                                        # (DAT 오프셋, 새 바이트) — census 용
    # ③ BRF · RAD
    for kind in ('BRF', 'RAD'):
        for e in base[kind]:
            ko = tr.get(e['id'])
            if not ko:
                continue
            enc = T.encode(ko, cmap) + b'\0'
            for o in e['locs']:
                patches.append((o, enc))
    # ④ EXE
    pool = bytearray()
    pb = K.pool_base(img0)
    moved = inplace = 0
    for e in base['EXE']:
        ko = tr.get(e['id'])
        if not ko:
            continue
        enc = T.encode(ko, cmap)
        cap = C.exe_cap(e, strides)          # 같은 간격 표 칸은 뒤쪽 0 여백까지 (검사기와 같은 함수)
        if len(enc) <= cap:
            n = max(len(e['raw']), len(enc))
            patches.append((T.exe_off(e['addr']), enc + bytes(n - len(enc))))
            inplace += 1
            continue
        if any(r[0] != 'u32' for r in e['refs']):
            raise SystemExit('⛔ %s 는 lui/addiu 참조라 이주 금지 — %d B 이하로 줄일 것' % (e['id'], len(e['raw'])))
        if e['id'] in strides:
            raise SystemExit('⛔ %s 같은 간격 표 — 이주 금지' % e['id'])
        while len(pool) % 4:
            pool.append(0)
        na = pb + len(pool)
        pool += enc + b'\0'
        for r in e['refs']:
            patches.append((T.exe_off(int(r[1]) if isinstance(r[1], int) else r[1]), struct.pack('<I', na)))
        moved += 1
    img, nsec, ecode, elab = K.finalize(img0, r_addr, bytes(pool))
    bad = K.verify(rows, img, ecode, elab, P, r_addr)
    if bad:
        raise SystemExit('⛔ 훅 시뮬 대조 실패 %d' % bad)
    # ⑤ 훅 · 스텁 · 트램펄린
    orig = Disc(ORIG)
    def exe_word(a):
        return struct.unpack('<I', orig.read(T.exe_off(a), 4))[0]
    for h in K.HOOKS:
        assert exe_word(h) == K.jal(K.THUNK), '⛔ 훅 자리 %08X' % h
        patches.append((T.exe_off(h), struct.pack('<I', K.jal(elab['TRAMP']))))
    assert exe_word(K.INIT_SITE) == K.jal(K.INIT_TARGET), '⛔ 초기화 자리'
    patches.append((T.exe_off(K.INIT_SITE), struct.pack('<I', K.jal(elab['STUB']))))
    import deadcode
    p = K.DEAD
    for s, e2 in sorted(deadcode.dead):
        if s <= p < e2:
            p = e2
    assert p >= K.DEAD + len(ecode), '⛔ 죽은 조각이 덮이지 않는다'
    patches.append((T.exe_off(K.DEAD), ecode))
    # 겹침 검사 — 두 패치가 같은 바이트를 쓰면 실패 (feedback_two_tables_writing_same_bytes)
    owner = {}
    for i, (o, b) in enumerate(patches):
        for x in range(o, o + len(b)):
            if x in owner and owner[x][1] != b[x - o]:
                raise SystemExit('⛔ 패치 겹침 DAT+%X' % x)
            owner[x] = (i, b[x - o])
    print('배치: BRF·RAD 칸 %d · EXE 제자리 %d · 이주 %d (풀 %d B) · 낮은 영역 %d B (%d 섹터)' % (
        sum(1 for o, b in patches if b.endswith(b'\0')), inplace, moved, len(pool), len(img), nsec))
    return patches, img, nsec, cmap


def build(patches, img, nsec):
    disc = Disc(ORIG)
    for o, b in patches:
        disc.write(o, b)
    for i in range(nsec):
        lba = K.BLOB_LBA + i
        sec = disc.sector(lba)
        assert sec[15] == 2 and not any(sec[UOFF:UOFF + 2048]) and lba < 246714, '⛔ LBA %d 가 빈 섹터가 아니다' % lba
        sec[16:24] = bytes([0, 0, 0x08, 0, 0, 0, 0x08, 0])
        chunk = img[i * 2048:(i + 1) * 2048]
        sec[UOFF:UOFF + 2048] = chunk + bytes(2048 - len(chunk))
        disc.mod[lba] = sec
    for lba, sec in disc.mod.items():
        fix_sector(sec)
    return disc


def census(disc, patches):
    allowed = set()
    orig = Disc(ORIG)
    for o, b in patches:
        old = orig.read(o, len(b))
        allowed.update(o + i for i in range(len(b)) if old[i] != b[i])
    diff = set()
    for lba, sec in disc.mod.items():
        if lba >= K.BLOB_LBA:
            continue
        o = orig.sector(lba)
        base = (lba - DAT_LBA) * 2048
        diff.update(base + i for i in range(2048) if o[UOFF + i] != sec[UOFF + i])
    extra, miss = diff - allowed, allowed - diff
    print('census: DAT 변경 %d B · 계획 밖 %d · 누락 %d · 바뀐 섹터 %d' % (len(diff), len(extra), len(miss), len(disc.mod)))
    if extra or miss:
        raise SystemExit('⛔ census 불일치 %s %s' % ([hex(x) for x in sorted(extra)[:5]], [hex(x) for x in sorted(miss)[:5]]))


def main():
    write = '--write' in sys.argv
    ver = sys.argv[sys.argv.index('--write') + 1] if write and len(sys.argv) > sys.argv.index('--write') + 1 else 'dev'
    patches, img, nsec, cmap = plan()
    disc = build(patches, img, nsec)
    census(disc, patches)
    if not write:
        print('드라이런 — 쓰지 않았다. 쓰려면 --write <버전>')
        return
    if md5(ORIG) != ORIG_MD5:
        raise SystemExit('⛔ 원본 md5 가 다르다')
    os.makedirs(OUTDIR, exist_ok=True); os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
    shutil.copyfile(ORIG, OUT)
    with open(OUT, 'r+b') as g:
        for lba, sec in sorted(disc.mod.items()):
            g.seek(lba * RAW); g.write(sec)
    with open(OUT[:-4] + '.cue', 'w', encoding='ascii') as c:
        c.write('FILE "%s" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n' % os.path.basename(OUT))
    chk = Disc(OUT)
    for lba in disc.mod:
        s = chk.sector(lba)
        assert s == disc.mod[lba], '⛔ 되읽기 %d' % lba
        assert struct.unpack_from('<I', s, 2072)[0] == edc(bytes(s[16:2072])), '⛔ EDC %d' % lba
    assert os.path.getsize(OUT) == os.path.getsize(ORIG)
    m = md5(OUT)
    print('✅ %s  %d B  md5 %s' % (OUT, os.path.getsize(OUT), m))
    with open(os.path.join(OUTDIR, 'charmap.tsv'), 'w', encoding='utf-8') as t:
        t.write('코드\t음절\n')
        for ch, c in sorted(cmap.items(), key=lambda x: x[1]):
            t.write('%04X\t%s\n' % (c, ch))
    x = os.path.join(ROOT, 'dist', 'AC2_KR_v%s.xdelta' % ver)
    rt = os.path.join(os.environ.get('TEMP', '.'), 'ac2_rt.bin')
    subprocess.run([XD, '-e', '-9', '-S', 'lzma', '-A', '-B', '268435456', '-f', '-s', ORIG, OUT, x], check=True)
    subprocess.run([XD, '-d', '-f', '-s', ORIG, x, rt], check=True)
    r = md5(rt); os.remove(rt)
    print('xdelta %s %d B md5 %s · 왕복 %s' % (x, os.path.getsize(x), md5(x), 'OK' if r == m else '⛔불일치'))
    shutil.copyfile(OUT, FDST)
    print('F: 설치본 md5 %s %s' % (md5(FDST), 'OK' if md5(FDST) == m else '⛔불일치'))


if __name__ == '__main__':
    main()
