# sangw 수정 사항 (아이오닉5용)

> 기준: `release-tizi` (sunnypilot v2026.002.002, 커밋 `6a17f75`) 위의 `ioniq5-mod` 브랜치.
> 코드에서 `[sangw 수정]` 주석이 달린 곳이 전부 이 문서의 항목이야. 기기에 이미 저장된 설정값이 있으면 기본값보다 그 값이 우선이야.
> 2026-10-17 기기 설치·부팅 성공(`9751725`). 주행 동작은 아직 미확인 — 타 보고 확인할 것.

## 1. 속도 버튼 짧게/길게 동작 교체 (신규 옵션)
- 짧게 누르면 5씩(5의 배수로 맞춤), 길게 누르면 1씩. 켜짐/꺼짐은 MADS 설정의 "Swap Short/Long Press Set Speed".
- 파일: `sunnypilot/selfdrive/car/cruise_ext.py` (`swap_press_increments`), `selfdrive/ui/sunnypilot/layouts/settings/steering_sub_layouts/mads_settings.py`, `common/params_keys.h` (`SwapCruiseButtonIncrements`, 기본 꺼짐), 테스트 `sunnypilot/selfdrive/car/tests/test_custom_cruise.py`.
- 적용 조건: openpilot이 설정 속도를 직접 관리할 때(종방향 제어 켬)만 작동. 순정 크루즈 모드에서는 효과 없음.
- Custom ACC 증가폭과 같이 켜면 정해 둔 짧게/길게 값이 서로 바뀜.
- **새 설정 키라 미리 빌드된 params 라이브러리(`params_pyx.so`)엔 없음.** 없는 키를 읽으면 예외 → UI가 죽어 부팅 화면에서 멈춤(2026-10-17 실제 발생). 그래서 키가 없으면 UI는 토글을 숨기고 크루즈 코드는 꺼짐으로 처리. 다시 빌드해야 토글이 보임.

## 2. 운전자 모니터링 완화 (`selfdrive/monitoring/policy.py`)
| 항목 | 원래 | 지금 |
|---|---|---|
| 앞을 보라는 경고 1/2/3단계 시간 (`_VISION_POLICY_ALERT_*_TIMEOUT`) | 3 / 5 / 11초 | 10 / 20 / 30초 |
| 폰 감지 기준 (`_PHONE_THRESH`) | 0.5 | 0.8 |
| 고개 위아래 (`_POSE_PITCH_THRESHOLD` / `_SLACK`) | 0.3133 / 0.3237 | 0.36 / 0.372 |
| 고개 좌우 (`_POSE_YAW_THRESHOLD` / `_SLACK`) | 0.4020 / 0.5042 | 0.462 / 0.58 |

- **위험:** 3단계(해제)가 30초라 고속에서 약 800m 이상 앞을 안 봐도 해제되지 않음. 폰 감지와 고개 각도를 완화한 만큼 실제 주의 분산도 늦게 잡힘. 필요하면 3단계를 11초 근처로 되돌릴 것.

## 3. 경고음 볼륨 (`selfdrive/ui/soundd.py`)
- "앞을 보세요" (`promptDistracted`): 0.5배.
- 운전자 모니터링 3단계 `DISENGAGE IMMEDIATELY` (부제가 `Driver Distracted`/`Driver Unresponsive`일 때만): 0.7배. 충돌 경고 등 다른 `warningImmediate`는 그대로.
- 영어 알림 문구 비교에 의존하므로 문구가 바뀌면 이 조건이 안 맞음.

## 4. 앞차 끼어들기 (`selfdrive/controls/radard.py`)
- 앞차 인식 확률 기준 `LEAD_PROB_MIN`: 0.5 → 0.4. 끼어드는 차를 더 일찍 앞차로 잡음. 대신 오인식 감속이 늘 수 있음.

## 5. 감속 거동 (`selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py`)
- Relax 차간 시간(`get_T_FOLLOW` relaxed): 1.75 → 2.0초(2026-10-18). 1.2초 접근의 실제 원인은 아래 `COMFORT_BRAKE`였고, 이건 여유를 더 두려고 같이 늘림. 정속 거리는 약 14% 늘어남(100km/h에서 약 49m → 56m + 6m). Standard 1.45·Aggressive 1.25는 그대로.
- `COMFORT_BRAKE`: 2.2로 바꿨다가 **2.5로 되돌림**(2026-10-18). 이 값은 MPC 솔버(`c_generated_code`, 미리 빌드된 C)에도 들어가는데 기기는 다시 빌드하지 않음 → 파이썬 쪽(앞차 정지거리)만 2.2가 돼서 목표 거리가 v²×(1/4.4−1/5)만큼 줄었음. 100km/h에서 약 21m(0.75초) 더 붙음 → Relax인데 1.2초까지 접근한 원인. 바꾸려면 솔버를 다시 생성·빌드해야 함.

## 6. 온보딩 건너뛰기
- 튜토리얼(트레이닝 가이드): 완료로 처리.
- 약관 동의 (`HasAcceptedTerms`, `HasAcceptedTermsSP`): 자동 저장.
- sunnylink: 사용 안 함으로 고정 (`SunnylinkEnabled=False`, 거절 기록). 설정 메뉴에서도 숨김(`selfdrive/ui/sunnypilot/layouts/settings/settings.py`).
- 첫 시작 sunnylink 동의 팝업: 거절 기록을 비동기로 써서 바로 다음 줄이 못 읽고 팝업이 떴던 것 → `block=True`로 씀(2026-10-18).
- 단위 km/h(`IsMetric`): 아직 정한 적 없을 때만 켬. 설정에서 바꾼 값은 유지. 미리 빌드된 라이브러리에선 `params_keys.h` 기본값이 안 먹어서 온보딩 코드(파이썬)에서 씀.
- 파일: `selfdrive/ui/layouts/onboarding.py`(comma 3X), `selfdrive/ui/mici/layouts/onboarding.py`(mici).

## 7. 기본값 변경 (`system/manager/manager.py` `SANGW_DEFAULTS`, `common/params_keys.h`)
- 실제로 적용하는 곳은 `manager.py`의 `SANGW_DEFAULTS`. 미리 빌드된 라이브러리에선 `params_keys.h` 기본값이 안 먹고(2026-10-17 QuietMode·실험 모드가 꺼진 채 설치됨), 부팅 때 옛 기본값이 먼저 써지기 때문.
- 부팅 때 `SANGW_DEFAULTS_VERSION`이 `/data/sangw_defaults_version`과 다르면 표 값을 한 번 덮어씀 → 그 뒤 설정 화면에서 바꾼 값은 유지. 값을 고치면 두 파일을 같이 고치고 VERSION을 올릴 것.
- **차를 한 번 인식한 뒤에만 씀.** 차 정보(`CarParamsPersistent`)가 없으면 UI가 차 따라 다른 설정(종방향·실험 모드·DEC·NNLC·SCC-V·Custom ACC)을 지움. 그래서 새로 설치하면 첫 시동 → 재부팅(다음 시동)부터 적용, 종방향은 그다음 차 연결 때 켜짐.
| 설정 | 원래 | 지금 |
|---|---|---|
| `ExperimentalMode` / `ExperimentalModeConfirmed` | 꺼짐 | 켜짐 (확인 팝업 생략) |
| `AlphaLongitudinalEnabled` (openpilot 종방향 제어) | 꺼짐 | 켜짐 |
| `AutoLaneChangeTimer` | 0 (Nudge) | 3 (1초 타이머) |
| `AutoLaneChangeBsmDelay` | 꺼짐 | 켜짐 |
| `NeuralNetworkLateralControl` (NNLC) | 꺼짐 | 켜짐 |
| `QuietMode` | 꺼짐 | 켜짐 |
| `MaxTimeOffroad` | 1800분 (30h) | 180분 (3h) |
| `SmartCruiseControlVision` | 꺼짐 | 켜짐 (`SmartCruiseControlMap`은 꺼짐 그대로) |
| `HyundaiLongitudinalTuning` | 0 (Off) | 1 (Dynamic) |
| `DynamicExperimentalControl` (DEC) | 꺼짐 | 켜짐 |
| `LaneTurnDesire` | 꺼짐 | 켜짐 (속도 기준 `LaneTurnValue` 19 mph 그대로) |
| `CustomAccIncrementsEnabled` / 짧게 / 길게 | 꺼짐 / 1 / 5 | 켜짐 / 5 / 1 (속도 버튼 짧게 5씩, 길게 1씩 — §1 대신 기존 설정 사용) |
| `LongitudinalPersonality` | Standard | Relaxed (핸들 거리 버튼으로 바꾸면 그 값 유지) |
| `AlwaysOnDM` / `DisengageOnAccelerator` | 꺼짐 / 꺼짐 | 꺼짐 고정 + 토글 화면에서 숨김(`selfdrive/ui/layouts/settings/toggles.py`, comma 3X 화면만) |

메모:
- **종방향 제어를 켜면 차의 전방 충돌 방지(FCA/AEB)가 꺼짐.** openpilot이 차 ADAS ECU(0x7d0)를 진단 명령으로 끄고 계기판에 AEB 꺼짐 아이콘을 띄움(opendbc `hyundai/interface.py`·`hyundaicanfd.py`). 대신 openpilot 감속은 최대 −3.5m/s²(차 AEB는 약 −9~10), 못 멈출 것 같으면 "BRAKE!" 경고만(더 세게 밟지 않음). openpilot을 안 켜고 직접 운전할 땐 자동 감속 없음. 알고 켜 둠(2026-10-18). 끄려면 Developer에서 longitudinal alpha 끄고 ICBM 켜기.
- Custom ACC 토글은 주행 중에도 바꿀 수 있게 풂(`selfdrive/ui/sunnypilot/layouts/settings/cruise.py`, 원래 시동 꺼짐에서만). 크루즈 쪽이 0.1초마다 다시 읽어 바로 반영 — 운전 중에 바꾸면 버튼 한 번에 오르는 폭이 즉시 달라짐.
- 종방향 제어(`AlphaLongitudinalEnabled`)는 설정 → Developer → "sunnypilot Longitudinal Control (Alpha)". 이게 꺼져 있으면 실험 모드(`ExperimentalMode`)가 켜지지 않고 부팅 때 지워짐.
- NNLC는 차를 한 번 인식해야 화면 토글이 눌림. 코드는 차량 시작 시 기본값을 읽음.
- 사각지대 지연은 차에 사각지대 경고 장치(BCW)가 있을 때만 효과.
- DEC가 켜져 있으면 실험 모드 초기 크루즈 속도가 105가 아니라 일반 모드 값(40)으로 시작.
- ICBM은 종방향 제어가 켜져 있으면 코드가 설정을 지워서 쓸 수 없음.

## 8. 되돌리는 법
- 항목별: 위 표의 "원래" 값으로 `params_keys.h`를 되돌리거나, 해당 `[sangw 수정]` 주석 구간만 지움.
- 전부: `git diff 6a17f75` 로 변경을 확인하고 `git checkout release-tizi`.

## 9. 저장소
- 작업 브랜치: `ioniq5-mod` (포크 `swkimme/sunnypilot`, 원격 이름 `fork`). `origin`은 sunnypilot 공식 저장소라 푸시 불가.
- 설치용 사본: 같은 브랜치를 `swkimme/openpilot`에도 둠. `installer.comma.ai/<사용자>/<브랜치>`는 `<사용자>/openpilot` 저장소만 찾기 때문.
- 고친 뒤엔 두 곳 다 푸시:
  ```
  git push fork ioniq5-mod
  git push https://github.com/swkimme/openpilot.git ioniq5-mod
  ```

## 10. 기기에 설치
1. 기기 설정 → 소프트웨어 → 제거(Uninstall).
2. 재부팅 후 "Custom Software" → `installer.comma.ai/swkimme/ioniq5-mod` 입력 → 설치 끝날 때까지 대기.
3. 첫 시동 후 확인: 온보딩 생략, 속도 버튼 교체, 경고 민감도, 아래 「주의」의 기본값.

SSH로 바꾸는 법(설치 화면 없이): 설정 → 개발자 → SSH 켜고 GitHub 사용자 `swkimme` 등록 →
```
ssh comma@<기기IP>
cd /data/openpilot
git remote add fork https://github.com/swkimme/sunnypilot.git
git fetch fork ioniq5-mod && git checkout -B ioniq5-mod fork/ioniq5-mod
sudo reboot
```

**주의 — 미리 빌드된 라이브러리.** release 브랜치라 `.so`와 `prebuilt` 파일이 들어 있어 기기가 다시 빌드하지 않음. 그래서 C++ 수정(`params_keys.h`)은 안 먹음 → 기본값은 `manager.py`(§7), 새 설정 키는 만들지 않거나 없을 때를 대비(§1). 파이썬 수정은 그대로 적용됨.

## 11. 확인 체크리스트
업데이트·재설치 뒤 이 순서로 확인. 안 맞는 게 있으면 해당 절을 볼 것. 1~3 확인(2026-10-18).

1. [x] **버전** — Software에 브랜치 `ioniq5-mod`, 최신 커밋인지.
2. [x] **첫 화면** — 온보딩·약관·sunnylink 팝업 없음, 설정 사이드바에 sunnylink 메뉴 없음 (§6).
3. [x] **Toggles** — Experimental Mode 켜짐, Driving Personality = Relaxed, Use Metric System 켜짐, Always-On Driver Monitoring·Disengage on Accelerator Pedal 안 보임 (§7).
4. [ ] **Developer** — sunnypilot Longitudinal Control (Alpha) 켜짐. 계기판 AEB 꺼짐 아이콘이 뜨는 게 정상 → 직접 운전할 때도 차 긴급제동 없음 (§7 메모).
5. [ ] **Steering** — NNLC 켜짐, 차선 변경 타이머 1초, 사각지대 지연 켜짐 (§7).
6. [ ] **Cruise** — Custom ACC 켜짐(짧게 5 · 길게 1), DEC 켜짐, SCC-V 켜짐 (§7).
7. [ ] **Vehicle · Models · Device** — HyundaiLongitudinalTuning = Dynamic, LaneTurnDesire 켜짐, QuietMode 켜짐, Max Time Offroad 3시간 (§7).
8. [ ] **주행: 속도 버튼** — 짧게 누르면 5씩, 길게 누르면 1씩 (§7).
9. [ ] **주행: 차간 거리** — Relax 정속에서 앞차와 약 2초(100km/h 약 62m), 따라잡을 때도 1.2초까지 안 붙음 (§5).
10. [ ] **주행: 운전자 모니터링** — 앞을 보라는 경고가 늦게(10·20·30초), 경고음이 작게 (§2·§3).
11. [ ] **주행: 차선 변경** — 깜빡이 켜고 1초 뒤 자동 변경, 옆 차 있으면 기다림 (§7).
