# -*- coding: utf-8 -*-
"""배포 패키지 — 빌드 xdelta 를 배포 이름으로 복사하고 CP949 readme 를 쓴다.

  python tools/mkdist.py alpha 0.1      # dist/AceCombat2(J-K)(alpha).xdelta ← dist/AC2_KR_v0.1.xdelta

readme 머리 형식은 전프로젝트 규칙(memory feedback_readme_patch_header_format): 단일 트랙 → «…bin 에 패치하시면 됩니다»,
md5 두 줄 들여쓰기 없음, CP949.
"""
import hashlib, os, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, '..', 'dist')
OUTBIN = os.path.join(HERE, '..', 'work', 'out', 'AC2_KR.bin')
ORIG_MD5 = 'ece1e7b3f995b67483b94f98401bb925'


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    tag, ver = sys.argv[1], sys.argv[2]
    src = os.path.join(D, 'AC2_KR_v%s.xdelta' % ver)
    name = 'AceCombat2(J-K)(%s).xdelta' % tag
    dst = os.path.join(D, name)
    shutil.copyfile(src, dst)
    assert md5(src) == md5(dst)
    pm = md5(OUTBIN)
    txt = '''Ace Combat 2 (Japan) (Rev 1).bin 에 패치하시면 됩니다.

원본md5 : %s
패치md5 : %s

입니다.


에이스컴뱃 2 (Ace Combat 2, SLPS-00830) PS1 일본판 Rev 1 한글 패치 %s
====================================================================

적용 방법
  xdelta3 -d -s "Ace Combat 2 (Japan) (Rev 1).bin" "%s" "Ace Combat 2 (Japan) (Rev 1) [KR].bin"
  (또는 xdelta UI 로 원본 .bin 에 패치를 적용)
  단일 트랙 이미지입니다. .cue 는 원본 것을 쓰고 파일 이름만 맞춰 주세요.

바뀌는 것
  - 게임 속 일본어 전부 한글
      메뉴, 옵션, 조작 설정 도움말, 메모리 카드 문구, 기체 설명, 미션 목록
      오프닝 브리핑, 엔딩 기록
      미션 브리핑 30편 전부
      비행 중 무선 메시지 125종 (원판처럼 화면 오른쪽 세로쓰기)
  - 한글 글꼴은 네오둥근모를 바탕으로 만든 조합형 16x15 글꼴이라
    어떤 PS1 BIOS(일본판/미국판/한글 BIOS)로 돌려도 한글이 나옵니다.

그대로 남는 것
  - 영문 UI (타이틀 메뉴, Play Level, HUD, 브리핑 위쪽 영문 내레이션) - 원판부터 영어입니다.
  - 동영상과 그림 속 글자

알파 버전 주의
  - 아직 모든 장면을 확인하지 않은 테스트 버전입니다.
  - 원판에서 만든 에뮬레이터 세이브스테이트를 불러오면 원판 상태로 돌아갑니다.
    새로 부팅해서 플레이해 주세요. (메모리 카드 세이브는 그대로 쓸 수 있습니다)
  - 글자가 비거나 잘리는 화면을 발견하시면 스크린샷과 함께 알려 주세요.

글꼴
  네오둥근모 (SIL Open Font License 1.1) 에서 자모를 떼어 조합형으로 재구성했습니다.
''' % (ORIG_MD5, pm, tag, name)
    rp = os.path.join(D, '읽어보세요_%s.txt' % tag)
    with open(rp, 'w', encoding='cp949', newline='\r\n') as f:
        f.write(txt)
    print('xdelta %s  %d B  md5 %s' % (name, os.path.getsize(dst), md5(dst).upper()))
    print('readme %s  %d B (CP949) · 패치md5 %s' % (os.path.basename(rp), os.path.getsize(rp), pm))


if __name__ == '__main__':
    main()
