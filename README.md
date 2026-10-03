[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://my.home-assistant.io/redirect/hacs_repository/?owner=zacala1&repository=hass-kocom-wallpad&category=Integration)

# Kocom Wallpad for Home Assistant

코콤 월패드의 RS-485 통신을 Home Assistant에 연결하는 커스텀 통합입니다.
EW11 같은 TCP 변환기 또는 HA에서 접근 가능한 시리얼 장치로 월패드 패킷을 받아
조명·콘센트·난방·에어컨·환기·센서 엔티티로 제공합니다.

[lunDreame/kocom-wallpad](https://github.com/lunDreame/kocom-wallpad)(보관됨)에서 갈라져 나온 유지보수 포크입니다.
다른 포크의 안정성 개선 중 검증 가능한 것만 골라 반영합니다.

## 지원 기능

모델·배선·수신 패킷에 따라 실제로 제공되는 기능은 다릅니다.

| 기능 | HA 엔티티 | 비고 |
| --- | --- | --- |
| 조명 | `light` | 켜기/끄기만 지원합니다. 밝기 조절은 없습니다. |
| 일괄소등 | `light` | 신호 수신 상태만 표시하고 제어는 지원하지 않습니다. [알려진 제한](docs/troubleshooting.md#알려진-제한) 참고 |
| 콘센트 | `switch` | 켜기/끄기 |
| 난방 | `climate` | 난방/꺼짐, 목표·현재 온도, 외출 프리셋 |
| 에어컨 | `climate` | 냉방·송풍·제습·자동·꺼짐, 온도, 팬 모드 |
| 환기 | `fan` | 켜기/끄기, 3단 속도, 수신 패킷에 따라 프리셋 |
| 공기질 | `sensor` | PM10, PM2.5, CO₂, VOC, 온도, 습도 |
| 보일러·환기 상태 | `sensor`, `binary_sensor` | 온수·난방수 온도, CO₂, 오류 상태 |
| 가스밸브 | `switch` | 켜기/끄기가 같은 프레임을 보냅니다. 잠금 해제 기능으로 쓰지 마세요. |
| 엘리베이터 | `switch`, `sensor` | 호출, 방향, 수신되는 경우 층수. 끄기는 호출 취소가 아닙니다. |
| 현관 움직임 | `binary_sensor` | 움직임 상태 |
| 인터폰, 에너지미터 | — | 지원하지 않습니다. |

## 연결 방식

| 연결 | 호스트 입력 | 포트 | 속도 |
| --- | --- | --- | --- |
| EW11 등 TCP | HA에서 접근 가능한 IP 또는 호스트명 | 기본 `8899` | 어댑터 설정에 따름 |
| 직접 시리얼 | `/dev/ttyUSB0` 또는 `/dev/serial/by-id/...` | 무시됨 | `9600` baud |

호스트가 `/`로 시작하면 시리얼 경로로 처리합니다. 장치 파일은 HA가 실행되는 환경에서 보여야 합니다.
설정 화면은 입력값을 저장만 하고, 실제 연결은 통합을 불러올 때 시도합니다.
처음 연결에 실패하면 HA가 재시도하고, 사용 중 연결이 끊기면 자동으로 재연결합니다.

## 설치

현재 이 포크는 릴리스를 발행하지 않았습니다. HACS 설치는 릴리스가 생긴 뒤에 사용할 수 있고,
그 전에는 수동으로 설치합니다.

### 수동 설치

1. HA 설정을 백업합니다.
2. 이 저장소의 `custom_components/kocom_wallpad` 폴더를 HA 설정 디렉터리의 `custom_components/kocom_wallpad`에 복사합니다.
3. HA를 재시작합니다.
4. **설정 → 기기 및 서비스 → 통합구성요소 추가**에서 **Kocom Wallpad**를 검색하고 호스트와 포트를 입력합니다.

### HACS (릴리스 발행 후)

HACS의 **Custom repositories**에 `https://github.com/zacala1/hass-kocom-wallpad`를 **Integration**으로 추가하고 설치한 뒤 HA를 재시작합니다.
베타 버전은 HACS에서 베타 표시를 켜야 보입니다.
자세한 절차는 [HACS 공식 안내](https://www.hacs.xyz/docs/faq/custom_repositories/)를 참고하세요.

### 다른 포크에서 옮길 때

원본과 모든 포크는 같은 도메인 `kocom_wallpad`를 사용하므로 한 HA에 둘 이상 설치할 수 없습니다.
코드를 받아오는 저장소만 하나로 정하고, 기존 설정 항목은 지우지 않아도 됩니다.
교체 전에는 HA 전체 백업과 기존 통합 파일 보관을 권장합니다.

## 옵션

통합의 **구성**에서 난방 `thermostat_step`을 고를 수 있습니다.

| 값 | 동작 |
| --- | --- |
| `auto` (기본) | 기기가 보고한 온도 간격을 유지합니다. 현재 프로토콜의 기본은 1°C입니다. |
| `1` | 난방 조작 간격을 1°C로 고정합니다. 에어컨에는 적용되지 않습니다. |

이 옵션은 화면 조작 간격만 바꿉니다. 0.5°C 단위 제어를 추가하지 않습니다.
옵션을 저장하면 통합이 다시 로드됩니다.

## 문제가 있을 때

기기가 보이지 않거나, 상태는 보이는데 제어가 안 되거나, 연결이 끊기는 경우의 확인 방법과
문제 보고에 필요한 로그 수집은 [문제 해결 안내](docs/troubleshooting.md)에 있습니다.

## 개발

저장소 루트에서 실행합니다.

```sh
# HA 없이 패킷·게이트웨이 회귀 테스트
uv run --frozen python -B -m unittest discover -s tests -v

# 실제 HA 클래스와 로컬 TCP 월패드 에뮬레이터를 쓰는 테스트
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --frozen --group ha python -m pytest -p pytest_asyncio.plugin
```

테스트는 에뮬레이터 기반이며 실물 월패드 검증을 대신하지 않습니다.
최소 지원 HA는 `2025.2.2`입니다.

## 기여와 출처

제안과 버그 보고는 [Pull requests](https://github.com/zacala1/hass-kocom-wallpad/pulls)나 저장소 Issues로 보내주세요.
HA 버전, 월패드 모델, 어댑터·연결 방식, 기대/실제 동작과 로그를 함께 적어주시면 큰 도움이 됩니다.

원작자는 lunDreame이며 기존 코드의 권리 표기는 유지합니다.
원본 저장소는 초기에 MIT License(Copyright (c) 2024 lunDreame)로 공개되었다가 이후 LICENSE 파일이 삭제되었고,
이 저장소에는 현재 별도의 LICENSE 파일이 없습니다.
