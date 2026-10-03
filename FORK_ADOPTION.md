# Fork adoption, 2026-10-03

Goal: reuse valid community fixes while preserving the integration's device coverage.
Baseline: zacala1/hass-kocom-wallpad main, d7e7f6578d3ad809bbd5d410d7e3dc110052b77d.
Original: lunDreame/kocom-wallpad, archived. Both repositories have the same main HEAD.
The latest original runtime release in this tree is 2.0.5; the 2026-02-07 commits change documentation and remove LICENSE.

## Comparison scope

The initial GitHub listing returned 32 forks. The first pass below compared nine active or changed default branches locally.
The follow-up surveyed all 31 other known forks and all 43 of their public branches, including documentation-only commits.
See [the complete fork and documentation survey](docs/fork-survey.md) for scope, pinned sources and API-listing limitations.
Dates below are commit dates in Asia/Seoul, not repository creation or star-update dates.
Ahead/behind counts include merge and documentation commits; they are not a quality score.

| Fork | HEAD | Date | Ahead / behind | Relevant differences |
| --- | --- | --- | --- | --- |
| [ninthsword](https://github.com/ninthsword/kocom-wallpad) | 85aa7a4 | 2026-09-18 | 20 / 2 | HA 2026.9 registry/serial changes, control-path safety, thermostat recovery, protocol tests |
| [digitie](https://github.com/digitie/kocom-wallpad) | 29f66c0 | 2026-09-13 | 5 / 0 | Reconnect locking, startup/unload cleanup, queue management, parser fixes |
| [m9suho](https://github.com/m9suho/kocom-wallpad) | c4e4a65 | 2026-08-30 | 64 / 2 | 2.0.15, individual-light all-off strategy; removes AIRCONDITIONER support |
| [Parktaro89](https://github.com/Parktaro89/kocom-wallpad) | 4d05023 | 2026-08-29 | 1 / 0 | Ventilation mode changes and 60-second polling |
| [jinwook-kim0](https://github.com/jinwook-kim0/kocom-wallpad) | 66d21cd | 2026-07-01 | 29 / 0 | Recovery, diagnostics/options and device-specific work |
| [yonyonhee](https://github.com/yonyonhee/kocom-wallpad) | f5bdb53 | 2026-05-29 | 1 / 0 | Per-room light counts, channel preservation, gas status fixes, electricity/water/hot-water meters |
| [an14700](https://github.com/an14700/kocom-wallpad) | 2e93672 | 2026-03-16 | 7 / 2 | Echo/elevator handling and reconnect experiments |
| [pms0811](https://github.com/pms0811/kocom-wallpad) | a9f60a4 | 2026-02-19 | 2 / 0 | Air-purification preset byte 0x08 to 0x09 |
| [hosinjung](https://github.com/hosinjung/kocom-wallpad) | 60b3be4 | 2025-09-08 | 3 / 2 | Hive L all-off scene handling |

## Adopted in 2.1.0b1 (local preview)

- digitie: one-shot initial connection, serialized iterative reconnects, bounded writer close, send errors propagated, startup rollback and platform-forwarding cleanup.
- digitie and ninthsword: retain a partial AA55 header between reads; use a callable gas-valve confirmation predicate.
- ninthsword: initialize command futures in the active loop, register confirmation before writing, resolve active/queued commands on stop, detect TCP EOF, publish current thermostat reports rather than stale cached temperatures.
- m9suho/ninthsword: return None for optional climate fan/preset properties instead of raising KeyError.
- Local adaptation: queued-command accounting is balanced on shutdown and reconnect is triggered after EOF; no fork was merged wholesale.
- Local adaptation: thermostat options default to auto, preserving the existing device step. An explicit 1-degree UI override applies only to thermostats and reloads the entry. It does not change packet encoding.

Sources:
- [digitie reconnect cleanup](https://github.com/digitie/kocom-wallpad/commit/490b9e5d92de9dd1aff39169cb445e734aaa781b)
- [digitie review fixes](https://github.com/digitie/kocom-wallpad/commit/20b78b9eda99499ceee48366a35f2f24bb6040a6)
- [ninthsword control safety](https://github.com/ninthsword/kocom-wallpad/commit/c0e0fe2f999e5468db03cc699f72cf5e03d24da6)
- [ninthsword protocol fixes](https://github.com/ninthsword/kocom-wallpad/commit/042801ca9045a1522229f07e2f9e4872334baf3a)

The narrow HA test shim was adapted from ninthsword's test_control_path_safety.py at 85aa7a42d4cf97f8645d1052c97a2322e98aebf9.

## Device coverage and model-specific changes

AIRCONDITIONER, ventilation, lighting, outlets, thermostat, gas valve, elevator, motion and air-quality support remain in the baseline code.
Do not infer a physical model's capabilities from one household's fork. A proven model/protocol profile should own its fixed capabilities; a manual override is for unknown profiles or installation-specific choices.

The baseline reads thermostat temperatures from individual integer bytes and writes int(temperature). Its half-degree auto-detection cannot trigger from that decode path. Neither this preview nor a UI step override establishes half-degree wire support. Preserve that distinction until captured packets establish a model-specific encoding.

Candidates requiring additional evidence before adoption:

- yonyonhee light-channel preservation and per-room counts: promising generic behavior; meter offsets/scaling require protocol fixtures/model evidence.
- m9suho all-off: use as an optional individual-light strategy for models without broadcast control; never remove air-conditioner support globally.
- Parktaro89 ventilation/polling: expose model-specific presets and optional polling; do not force every installation into ventilation mode or add bus traffic by default.
- pms0811 preset 0x09 and hosinjung Hive L scene frames: model/profile mappings, not universal replacements.
- ninthsword HA 2026.9 compatibility: serialx and via_device_id are useful, but its minimum HA increase from 2025.2.2 to 2026.8.0 is a separate compatibility decision.

Official references:
- [Serial migration](https://developers.home-assistant.io/blog/2026/04/27/pyserial-to-serialx/)
- [Device registry migration](https://developers.home-assistant.io/blog/2026/08/24/device-registry-follow-up-changes/)
  The latter documents custom-integration deprecation warnings before removal in 2027.8; a warning alone is not proof that the original integration cannot run.

## Validation and limits

- The original baseline failed eight targeted regression cases (including stale temperatures, split headers, unresolved commands, startup failure, and lost immediate confirmations).
- The adapted preview passes 18 tests, including a real local TCP round trip and actual voluptuous option-schema validation; HA interfaces are narrow test shims.
- Python syntax, runtime JSON and fatal Ruff checks pass. Broad linting also found inherited style/type-modernization findings; a repository-wide lint pass is not claimed.
- No real wallpad or running Home Assistant instance was used. Docker was not running; actual HA/Hassfest/HACS CI and a clean-install smoke test remain unverified.
- The original declared HA minimum (2025.2.2) is preserved as metadata, not newly certified by these tests.
- The local preview is not a published release, stable tag, deployment or remote push.

Run offline tests from the repository root:

```powershell
uv run --no-project --with-requirements requirements-dev.txt python -B -m unittest discover -s tests -v
```
