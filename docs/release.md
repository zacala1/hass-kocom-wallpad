# 배포 준비와 제한

기준일: 2026-10-03 (Asia/Seoul). 현재 통합 버전은 미출시 베타 `2.1.0b1`입니다.
**패키징 준비와 공개 배포 승인은 다릅니다. 현재 공개 배포는 차단되어 있습니다.**

## HA/Python 기준

공식 [최신 안정판 릴리스 노트](https://www.home-assistant.io/blog/2026/09/02/release-20269/)와
[해당 버전 메타데이터](https://github.com/home-assistant/core/blob/2026.9.4/pyproject.toml)를 확인했습니다.
최신 안정판 `2026.9.4`는 Python `3.14.2+`를 요구합니다.
`2026.10` 시험판은 안정판 지원 기준에 섞지 않습니다.

| 검증 대상 | Python 계열 | 의미 |
| --- | --- | --- |
| `2025.2.2` | `3.13` | 기존 HACS 최소 버전, 실제 인증은 아직 아님 |
| `2025.2.5` | `3.13` | 기존 최소 계열의 마지막 패치 |
| `2026.9.4` | `3.14` 최신 패치 | 조사 시점 최신 안정판 |

매트릭스는 `release/policy.json`에서 관리하고 CI가 읽습니다.
[2025.2 계열의 Python 요구사항](https://github.com/home-assistant/core/blob/2025.2.5/pyproject.toml)은 `3.13.0+`입니다.
최신 HA의 import 검증을 추가했다고 실제 설치·기기 제어 호환성이 입증되는 것은 아닙니다.
지원 하한은 임의로 올리지 않았습니다. 하한을 올릴 경우 기존 설치 배제와 버전 정책을 별도 검토해야 합니다.

현재 `pyserial==3.5`, `pyserial-asyncio==0.6`을 정확히 고정했습니다.
HA의 [serialx 전환 안내](https://developers.home-assistant.io/blog/2026/04/27/pyserial-to-serialx/)와
[기기 레지스트리 변경](https://developers.home-assistant.io/blog/2026/08/24/device-registry-follow-up-changes/)은 후속 호환성 검토 대상입니다.
이번 배포 준비에서 통신 라이브러리나 엔티티 식별자를 교체하지 않았습니다.

## ZIP 계약

- 파일명: `kocom_wallpad.zip`, 해시: `kocom_wallpad.zip.sha256`.
- ZIP 루트에 `manifest.json`, Python 모듈, `translations/`를 넣습니다. `custom_components/`를 ZIP 안에 중복 중첩하지 않습니다.
- Git에 커밋된 `release/files.json`의 명시적 파일만 포함합니다. 런타임 추적 파일과 목록이 다르면 실패합니다.
- 미커밋 변경과 미추적 파일, symlink, 태그/버전 불일치, 허용되지 않은 경로를 거부합니다. 무시된 로컬 비밀 파일은 포함하지 않습니다.
- Git blob의 원본 바이트를 사용하므로 Windows checkout의 CRLF 변환을 패키지에 반영하지 않습니다.
- 이름 정렬, 고정 ZIP timestamp와 두 독립 빌드의 SHA256 비교를 사용합니다. 서로 다른 압축기/.NET 버전 간 동일 해시까지 보장한 것은 아닙니다.
- 기존 ZIP은 덮어쓰지 않습니다. 재검증은 새 dist 하위 디렉터리를 사용합니다.

PowerShell 7에서 저장소 루트의 깨끗한 커밋을 빌드합니다.

```powershell
pwsh -NoProfile -File tests/test-release.ps1
pwsh -NoProfile -File scripts/build-release.ps1 -OutputDirectory dist/check-a
pwsh -NoProfile -File scripts/build-release.ps1 -OutputDirectory dist/check-b
Get-FileHash dist/check-a/kocom_wallpad.zip, dist/check-b/kocom_wallpad.zip
```

HACS는 [공식 ZIP 릴리스 설정](https://www.hacs.xyz/docs/publish/start/)에 따라
`zip_release`, `filename`, `hide_default_branch`를 사용합니다.
이 메타데이터가 원격에 적용되면 릴리스 파일이 필요합니다. 태그만 만들거나 자산 없이 main만 푸시하면 설치 경로가 완성되지 않습니다.
첫 릴리스가 승인되기 전에는 [수동 미리보기 설치](../README.md)를 사용하세요.

## 현재 공개 배포 차단 이유

`release/policy.json`의 `publication_enabled`는 `false`입니다. 실패 검사를 우회하기 위해 켜지 마세요.

1. 현재 LICENSE가 없고 원본 README는 권리 유보 표기입니다. 재배포 권한과 적용할 라이선스를 확인하고 근거를 기록해야 합니다. 다른 포크의 라이선스를 복사하지 않습니다.
2. 원격 HACS/Hassfest 및 전체 CI 결과가 없습니다. 로컬 YAML 검사와 회귀 테스트만으로 원격 통과를 주장하지 않습니다.
3. 실제 HA의 깨끗한 설치, 통합 설정 생성, 플랫폼 로드, 옵션 reload, unload, 연결 실패 재시도, 업그레이드/복구 검증이 필요합니다. CI의 실제 HA import 테스트는 그 일부만 확인합니다.
4. 모델과 연결 방식이 명시된 실물 동작 기록이 필요합니다. 현재 18개 테스트는 HA shim과 로컬 TCP를 사용합니다.
5. 통합 개발 품질 계약의 locked 환경, strict 타입/전체 lint·format, branch coverage 95% 및 모듈 규모 요구사항은 아직 충족하지 않았습니다. 현재 CI의 fatal lint는 이를 대신하지 않습니다.

기존 `hass.data` 소유 구조, 레지스트리 API와 넓은 예외 처리 등의 전체 현대화는 이번 변경 범위 밖입니다.
필요한 후속 검증/개선을 수행하고 품질 계약의 충족 근거를 남기기 전에는 배포 승인을 기록하지 않습니다.

## 승인 기록과 발행 제한

베타/RC는 `X.Y.ZbN`, `X.Y.ZrcN`; 태그는 `v<manifest의 정확한 버전>`입니다.
발행된 버전/태그/자산은 재사용하거나 이동하지 않습니다. 이번 `2.1.0b1`은 아직 발행하지 않아 그대로 유지했습니다.
manifest와 policy 버전, README/CHANGELOG, CI 및 태그를 함께 갱신합니다.

공개 배포를 별도로 승인받은 뒤에만 아래 절차를 수행합니다.

1. 검증 대상 런타임 tree ID를 `git rev-parse HEAD:custom_components/kocom_wallpad`로 구합니다.
2. 라이선스, clean install, 실물, 품질 계약 각각의 결과를 `release/evidence/<이름>.md`에 커밋합니다. 버전과 runtime tree ID, 환경/모델, 실행 명령·결과·로그 위치를 기록합니다.
3. policy의 evidence 경로와 tree ID, `license_reviewed`를 실제 근거에 맞게 갱신합니다. 증거의 존재 검사만으로 기록 내용의 진실성이 증명되지는 않으므로 소유자 검토가 필요합니다.
4. GitHub `preview-release` environment에 required reviewers와 자체 승인 방지, 허용 preview 태그 정책을 설정합니다. **YAML의 environment 이름만으로 승인 보호가 생기지는 않습니다.** 요금제/저장소 유형상 reviewer 보호를 설정할 수 없다면 publication을 계속 차단합니다.
5. 기본 브랜치와 배포 워크플로/정책 변경에 리뷰 보호를 설정합니다. 공개 HACS 목록 제출은 Issues·설명·topics·브랜드·라이선스·실제 release 등의 요구사항도 따로 확인합니다.
6. 별도 승인 후 policy를 활성화하고 정확한 preview 태그에서 수동 release 워크플로를 실행합니다. 정책 검사 → 같은 commit 전체 CI → environment 승인 → ZIP 재빌드 → prerelease 발행 순서입니다.

워크플로는 기존 release 덮어쓰기, 안정판 발행, Latest 지정, 브랜치에서 발행을 허용하지 않습니다.
기본 권한은 읽기 전용이고 최종 발행 job만 `contents: write`를 사용합니다.
태그가 검사 중 이동하면 발행 직전에 commit 일치 확인으로 실패합니다.
태그 자동 푸시나 자동 안정판 승격은 없습니다. 안정판은 별도 승인과 정책 변경이 필요합니다.
HACS 사용자에게 preview 버전 표시/다운로드를 켜는 절차도 릴리스 안내에 명시하세요.

## 업그레이드와 안전한 현장 QA

HA 전체 백업과 기존 통합 파일을 보관한 뒤 같은 도메인에 포크 하나만 설치합니다.
현재 설정 항목과 엔티티 ID를 유지하는 것이 목표이며 이번 변경에는 데이터 스키마 migration이 없습니다.
복구는 기존 통합 파일을 되돌리고 HA를 재시작하는 방식으로 먼저 시험합니다.
통합 설정 항목 삭제를 일반 업그레이드 절차로 요구하지 않습니다.

실물 확인은 조명 등 안전한 장치의 상태 수신/제어, 난방 표시, 재시작/연결 복구부터 진행합니다.
가스 해제 명령을 시험하지 않고 엘리베이터 호출 취소로 off를 쓰지 않습니다.
일괄소등은 사용 중인 설비에 영향을 줄 수 있어 설치 소유자의 승인과 안전한 조건에서만 확인합니다.
로그 공유 전 주소·세대 정보 등 개인정보를 제거합니다.
