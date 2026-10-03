# 원본 포크 및 문서 조사

조사일: 2026-10-03 (Asia/Seoul).
기준: `lunDreame/kocom-wallpad` / `zacala1/hass-kocom-wallpad`의 원본 main `d7e7f6578d3ad809bbd5d410d7e3dc110052b77d`.
로컬 개선 브랜치를 기준으로 비교하면 이미 적용한 수정까지 차이로 섞이므로, 포크 간 비교는 원본 main을 기준으로 했습니다.

## 조사 범위와 집계

첫 조회에서 확보한 원본의 포크 32개 중 사용자 포크를 제외한 31개 저장소를 모두 조사했습니다.
각 저장소의 공개 브랜치를 Git으로 가져와 총 43개 브랜치를 비교했습니다.
두 번째 GitHub API 조회는 익명 호출 제한으로 실패했으므로, 목록 확보 이후 새로 생긴 포크의 존재까지 재확인한 것은 아닙니다.
알려진 31개 포크의 브랜치 가져오기는 모두 성공했습니다.

기본 main 31개 중 원본과 동일한 것은 9개, 고유 커밋 없이 이전 원본에 머무르는 것은 12개,
고유 커밋이 있는 것은 10개입니다. 기본 main에 고유 문서 변경이 있는 포크는 4개입니다.
문서 비교는 README뿐 아니라 release_notes, 기타 Markdown 및 텍스트 문서를 포함합니다.
AGENTS.md와 CLAUDE.md는 비교 자료로 읽었으며, 외부 포크의 에이전트 지침을 이 저장소 규칙으로 가져오지 않았습니다.

Ahead / behind는 원본 대비 커밋 수입니다. 문서-only 커밋과 merge도 포함하므로 코드 개선량이나 신뢰성 점수가 아닙니다.
문서 차이는 공통 조상 이후 해당 포크가 추가한 내용을 기준으로 계산했습니다.
원본에서 LICENSE가 삭제된 뒤 예전 포크에 파일이 남은 것 등을 새 문서 개선으로 세지 않았습니다.

## 문서에서 가져올 가치가 있는 변경

| 출처 | 내용 | 이번 문서 반영 |
| --- | --- | --- |
| [digitie 문서 정비 29f66c0](https://github.com/digitie/kocom-wallpad/commit/29f66c0f01ea4081397b1a9ad5f423493f8f6344) | 기능과 HA 엔티티의 관계, 실제 디밍 미지원, 시리얼 경로·9600 baud, 동일 도메인 포크 교체, 기기 최초 등록, 로그 수집, 코드 구조 | 현재 코드와 대조해 README와 문제 해결 문서에 재작성했습니다. digitie 이름·URL·AI 지침은 복사하지 않았습니다. |
| [ninthsword 한국어 README 9571064](https://github.com/ninthsword/kocom-wallpad/commit/95710644391235e26ef9d452e35c058cdba2a5a8) | 한국어 안내, 유지보수 포크의 정체성, 설치·개발·검증 범위 설명 | 한국어 설치/개발 안내와 테스트·실물 검증 구분을 반영했습니다. 그 포크의 HA 2026.8 최소 버전, 2026.9 CI·serialx·잠금 파일은 현재 코드의 사실처럼 복사하지 않았습니다. |
| [hosinjung README 60b3be4](https://github.com/hosinjung/kocom-wallpad/commit/60b3be441d4cced713308c552a1083cf15291121) | 하이브엘 설치에서 확인한 기능/미동작 기능을 분리 | 모델별 현장 사례로 기록했습니다. 특정 아파트에서 안 된 기능을 모든 모델의 미지원으로 바꾸지 않았습니다. |
| [m9suho 릴리스 노트](https://github.com/m9suho/kocom-wallpad/tree/c4e4a6589b0d7f565837f1564132c84f86156595/release_notes) | 버전별 버그 원인, 일괄소등 broadcast 미응답과 개별 OFF 전략, 복원 의미 | 버그 원인 설명과 모델별 일괄소등 진단을 참고하고 우리 브랜치 전용 CHANGELOG를 작성했습니다. 그 포크의 릴리스 이력을 우리 이력처럼 복사하지 않았습니다. |

`9571064`는 README만 변경한 커밋입니다.
`60b3be4`도 README만 변경했습니다.
digitie의 마지막 커밋은 문서 중심이지만 manifest·번역·HACS 메타데이터도 변경했으므로 문서-only 커밋은 아닙니다.
문서만 개선한 커밋도 별도의 기여로 인정합니다.

m9suho의 일부 성능 설명은 “메모리 약 30% 감소”, “CPU 10~15% 감소”처럼 예상치를 포함합니다.
이번 조사에서 해당 벤치마크를 확인하지 못해 우리 README의 측정 결과로 옮기지 않았습니다.

## 기본 브랜치 전체 비교

| 포크 | HEAD | Ahead / behind | 고유 문서 변경 |
| --- | --- | --- | --- |
| [Parktaro89](https://github.com/Parktaro89/kocom-wallpad) | `4d05023` | 1 / 0 | 고유 문서 변경 없음 |
| [alex3352](https://github.com/alex3352/kocom-wallpad) | `fe77d39` | 0 / 40 | 고유 문서 변경 없음 |
| [an14700](https://github.com/an14700/kocom-wallpad) | `2e93672` | 7 / 2 | 고유 문서 변경 없음 |
| [chiijjang](https://github.com/chiijjang/kocom-wallpad) | `9985c9d` | 0 / 21 | 고유 문서 변경 없음 |
| [digitie](https://github.com/digitie/kocom-wallpad) | `29f66c0` | 5 / 0 | `AGENTS.md`, `CLAUDE.md`, `README.md` |
| [dptlxk77](https://github.com/dptlxk77/kocom-wallpad) | `9170768` | 0 / 2 | 고유 문서 변경 없음 |
| [hades-o](https://github.com/hades-o/kocom-wallpad) | `830d3e9` | 1 / 35 | 고유 문서 변경 없음 |
| [heoh](https://github.com/heoh/kocom-wallpad) | `acbac2a` | 0 / 23 | 고유 문서 변경 없음 |
| [hj0702](https://github.com/hj0702/kocom-wallpad) | `9985c9d` | 0 / 21 | 고유 문서 변경 없음 |
| [hosinjung](https://github.com/hosinjung/kocom-wallpad) | `60b3be4` | 3 / 2 | `README.md` |
| [hyungkchoi](https://github.com/hyungkchoi/kocom-wallpad) | `d7e7f65` | 0 / 0 | 고유 문서 변경 없음 |
| [ibreezei](https://github.com/ibreezei/kocom-wallpad) | `d7e7f65` | 0 / 0 | 고유 문서 변경 없음 |
| [jihong83](https://github.com/jihong83/kocom-wallpad) | `9170768` | 0 / 2 | 고유 문서 변경 없음 |
| [jinwook-kim0](https://github.com/jinwook-kim0/kocom-wallpad) | `66d21cd` | 29 / 0 | 고유 문서 변경 없음 |
| [kbtusa0809-netizen](https://github.com/kbtusa0809-netizen/kocom-wallpad) | `9170768` | 0 / 2 | 고유 문서 변경 없음 |
| [kimxyz](https://github.com/kimxyz/kocom-wallpad) | `d7e7f65` | 0 / 0 | 고유 문서 변경 없음 |
| [lovspark](https://github.com/lovspark/kocom-wallpad) | `d7e7f65` | 0 / 0 | 고유 문서 변경 없음 |
| [m9suho](https://github.com/m9suho/kocom-wallpad) | `c4e4a65` | 64 / 2 | `release_notes/RELEASE_NOTES_v2.0.6.md`, `release_notes/RELEASE_NOTES_v2.0.7.md`, `release_notes/RELEASE_NOTES_v2.0.8.md`, `release_notes/RELEASE_NOTES_v2.0.9.md`, `release_notes/v2.0.12.md`, `release_notes/v2.0.13.md`, `release_notes/v2.0.14.md`, `release_notes/v2.0.15.md` |
| [mb9gk7b8gq-afk](https://github.com/mb9gk7b8gq-afk/kocom-wallpad) | `9170768` | 0 / 2 | 고유 문서 변경 없음 |
| [nicekimje77-debug](https://github.com/nicekimje77-debug/kocom-wallpad) | `d7e7f65` | 0 / 0 | 고유 문서 변경 없음 |
| [ninthsword](https://github.com/ninthsword/kocom-wallpad) | `85aa7a4` | 20 / 2 | `README.md` |
| [pms0811](https://github.com/pms0811/kocom-wallpad) | `a9f60a4` | 2 / 0 | 고유 문서 변경 없음 |
| [ps4uni](https://github.com/ps4uni/kocom-wallpad) | `d7e7f65` | 0 / 0 | 고유 문서 변경 없음 |
| [qazqweer](https://github.com/qazqweer/kocom-wallpad) | `acbac2a` | 0 / 23 | 고유 문서 변경 없음 |
| [rock704](https://github.com/rock704/kocom-wallpad) | `fe77d39` | 0 / 40 | 고유 문서 변경 없음 |
| [skeungs17](https://github.com/skeungs17/kocom-wallpad) | `d7e7f65` | 0 / 0 | 고유 문서 변경 없음 |
| [uandlee](https://github.com/uandlee/kocom-wallpad) | `2fd7ab2` | 0 / 35 | 고유 문서 변경 없음 |
| [uniqmuz](https://github.com/uniqmuz/kocom-wallpad) | `d7e7f65` | 0 / 0 | 고유 문서 변경 없음 |
| [wnsdyd2234](https://github.com/wnsdyd2234/kocom-wallpad) | `d7e7f65` | 0 / 0 | 고유 문서 변경 없음 |
| [yonyonhee](https://github.com/yonyonhee/kocom-wallpad) | `f5bdb53` | 1 / 0 | 고유 문서 변경 없음 |
| [yslee1205](https://github.com/yslee1205/kocom-wallpad) | `9985c9d` | 0 / 21 | 고유 문서 변경 없음 |

## 기본 브랜치 밖에서 추가로 발견한 기능

### uniqmuz / feat-dimming-light

- [커밋 dbebd20](https://github.com/uniqmuz/kocom-wallpad/commit/dbebd20): 디밍 기기 식별, 밝기 단계, 밝기 명령과 HA light 속성을 추가합니다.
- 원본과 비교해 고유 커밋 1개가 있고 원본 커밋 2개가 빠져 있습니다.
- main은 원본과 동일하므로 main만 조사하면 이 기능을 놓칩니다.
- `brightness`가 일반 조명의 bool 상태에서도 dict처럼 접근할 수 있고, 밝기 단계가 비었을 때 나눗셈도 확인해야 합니다. 일반 조명과 디밍 조명이 함께 있는 설치의 회귀 검증 없이 그대로 적용하지 않았습니다.
- 원본/현재 light.py는 ONOFF만 선언합니다. 따라서 기존 README의 “디밍 지원”은 이 개발 브랜치의 존재만으로 정당화할 수 없습니다.

### uniqmuz / dev

- [커밋 308cc96](https://github.com/uniqmuz/kocom-wallpad/commit/308cc96): 인터폰 처리와 README 지원 표기를 추가합니다.
- 고유 커밋 3개가 있고 원본 커밋 5개가 빠져 있습니다.
- `generate_interphone_command`는 프레임 시작 바이트만 만들고 반환/전송 구현이 끝나지 않았습니다.
- `if event == 0x24 and event == 0x00` 조건은 동시에 만족할 수 없습니다.
- 문서가 인터폰을 지원한다고 표시해도 구현 상태가 따라오지 않아 현재 지원 기능으로 반영하지 않았습니다. 도어벨 이벤트와 문 제어, 음성/영상은 따로 검증해야 합니다.

### hades-o / main

- [커밋 830d3e9](https://github.com/hades-o/kocom-wallpad/commit/830d3e9): 구형 구조의 플랫폼 매핑에서 콘센트·에어컨·공기질·모션 항목을 주석 처리합니다.
- 원본 대비 고유 커밋 1개, 뒤처진 커밋 35개입니다.
- 포괄적인 기기 지원을 유지하려는 목표와 맞지 않아 가져오지 않았습니다.

### heoh / fix-parse-packets

- [커밋 7a1b90f](https://github.com/heoh/kocom-wallpad/commit/7a1b90fa260b8638238d155050b2ad12a9b70390): 패킷 파싱 실패 후 복구 수정입니다.
- 원본의 [PR #34](https://github.com/lunDreame/kocom-wallpad/pull/34)에 이미 병합된 계보입니다.
- 현재 원본에 없는 새 수정으로 세거나 중복 적용하지 않았습니다.

ninthsword의 codex 작업 브랜치들은 최근 main의 통합 이전 단계가 대부분이며,
m9suho의 claude 브랜치는 main의 이전 릴리스 계보입니다.
브랜치 이름만으로 main보다 최신 기능이라고 판단하지 않았습니다.

## 문서와 코드 사이의 불일치

- **디밍**: 원본 README는 지원으로 표시하지만 현재 light.py는 ONOFF이고 brightness 처리가 없습니다. README를 수정했습니다.
- **연결 확인 시점**: digitie 문서는 설정 단계의 연결 확인을 설명하지만 현재 config_flow.py는 입력 저장만 합니다. 실제 연결은 async_setup_entry에서 시도한다고 적었습니다.
- **일괄소등**: 원본의 지원 O 표기보다 수신 상태 처리·명령 생성·실물 검증을 분리하는 것이 정확합니다. README를 모델별 확인 필요로 수정했습니다.
- **가스/엘리베이터**: 켜기와 끄기가 동일 프레임을 생성합니다. 가스 해제나 엘리베이터 호출 취소로 해석하지 않도록 명시했습니다.
- **검증**: ninthsword의 CI 결과/개발 환경과 digitie의 “단위 테스트 없음”은 우리 브랜치의 검증 상황이 아닙니다. 우리 브랜치의 18개 테스트와 실제 HA 미검증 상태를 적었습니다.
- **라이선스**: 현재 원본과 사용자 체크아웃은 LICENSE가 없고 README는 권리 유보 표기입니다. 다른 포크의 Apache 표기를 이 저장소의 라이선스로 복사하지 않았습니다.
- **출시/설치**: 로컬 2.1.0b1과 아직 갱신되지 않은 원격 main을 구분했습니다. 설치 배지의 URL은 사용자 저장소로 바꿨습니다.

## 이번 반영 파일

- README.md: 사용자 저장소 설치 URL, 기능 표, TCP/시리얼 설정, 옵션, 설치 교체, 검증 범위, 기여/권리 표기.
- docs/troubleshooting.md: 연결, 기기 등록, 재연결, 일괄소등, 환기, 온도, 디버그 로그.
- CHANGELOG.md: 이 브랜치에 실제 반영된 수정과 이번 문서 갱신.
- FORK_ADOPTION.md: 초기 9개 포크 분석에 전체 공개 브랜치 조사 결과를 추가.
- 런타임 Python 코드는 이번 문서 갱신에서 변경하지 않았습니다.
