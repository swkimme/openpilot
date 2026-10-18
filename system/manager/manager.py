#!/usr/bin/env python3
import datetime
import os
import signal
import sys
import time
import traceback

from cereal import log
import cereal.messaging as messaging
import openpilot.system.sentry as sentry
from openpilot.common.utils import atomic_write
from openpilot.common.params import Params, ParamKeyFlag
from openpilot.common.text_window import TextWindow
from openpilot.system.hardware import HARDWARE
from openpilot.system.manager.helpers import unblock_stdout, write_onroad_params, save_bootlog
from openpilot.system.manager.process import ensure_running
from openpilot.system.manager.process_config import managed_processes
from openpilot.system.athena.registration import register, UNREGISTERED_DONGLE_ID
from openpilot.common.swaglog import cloudlog, add_file_handler
from openpilot.system.version import get_build_metadata
from openpilot.system.hardware.hw import Paths
from openpilot.system.hardware import PC

from openpilot.sunnypilot.system.params_migration import run_migration

# [sangw 수정, docs/SANGW_MODS.md §7] 기본값 바꾸기. params_keys.h 기본값은 미리 빌드된 라이브러리(prebuilt)에선 안 먹고
# 아래 루프가 옛 기본값을 먼저 써 버리므로, 파이썬에서 한 번 덮어쓴다. 값을 바꾸거나 키를 늘리면 VERSION을 올릴 것.
SANGW_DEFAULTS_VERSION = "7"  # 4는 되돌린 버전이라 건너뜀
SANGW_DEFAULTS: dict[str, bool | int] = {
  "AlphaLongitudinalEnabled": True,
  "ExperimentalMode": True,
  "ExperimentalModeConfirmed": True,
  "AutoLaneChangeTimer": 2,  # 0.5초 (nudge 0 · nudgeless 1 · 0.5초 2 · 1초 3)
  "AutoLaneChangeBsmDelay": True,
  "NeuralNetworkLateralControl": False,  # 2026-10-18 저속에서 핸들을 좌우로 흔들어 끔
  "QuietMode": True,
  "MaxTimeOffroad": 180,
  "SmartCruiseControlVision": True,
  "HyundaiLongitudinalTuning": 1,
  "DynamicExperimentalControl": True,
  "LaneTurnDesire": True,
  "IsMetric": True,  # Toggles에서 숨김 — km/h 고정
  # 속도 버튼: 짧게 5, 길게 1 (기존 Custom ACC 설정 사용)
  "CustomAccIncrementsEnabled": True,
  "CustomAccShortPressIncrement": 5,
  "CustomAccLongPressIncrement": 1,
  "LongitudinalPersonality": 2,  # relaxed (aggressive 0 · standard 1 · relaxed 2)
  # 화면에서 숨긴 토글(toggles.py) — 꺼짐 고정
  "AlwaysOnDM": False,
  "DisengageOnAccelerator": False,
  "RecordFront": False,
  "RecordAudio": False,
  # Visuals에서 숨김 — 꺼짐 고정 (속도계는 보임)
  "RainbowMode": False,
  "ShowTurnSignals": False,
  "RocketFuel": False,
  "HideVEgoUI": False,
}


def apply_sangw_defaults(params: Params) -> None:
  # 버전마다 한 번만 씀 → 그 뒤 설정 화면에서 바꾼 값은 유지.
  # 차를 한 번 인식한 뒤(CarParamsPersistent)에만 씀: 차 정보가 없으면 UI가 종방향·실험 모드·NNLC 등을 지워 버림
  if params.get("CarParamsPersistent") is None:
    return
  marker = os.path.join(Paths.comma_home() if PC else "/data", "sangw_defaults_version")
  try:
    with open(marker) as f:
      if f.read().strip() == SANGW_DEFAULTS_VERSION:
        return
  except FileNotFoundError:
    pass
  for k, v in SANGW_DEFAULTS.items():
    try:
      params.put(k, v, block=True)
    except Exception:
      cloudlog.exception(f"sangw default failed: {k}")
  with open(marker, "w") as f:
    f.write(SANGW_DEFAULTS_VERSION)


def manager_init() -> None:
  save_bootlog()

  build_metadata = get_build_metadata()

  params = Params()
  params.clear_all(ParamKeyFlag.CLEAR_ON_MANAGER_START)
  params.clear_all(ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION)
  params.clear_all(ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION)
  params.clear_all(ParamKeyFlag.CLEAR_ON_IGNITION_ON)
  # if build_metadata.release_channel:
  #   params.clear_all(ParamKeyFlag.DEVELOPMENT_ONLY)

  # device boot mode
  if params.get("DeviceBootMode") == 1:  # start in Always Offroad mode
    params.put_bool("OffroadMode", True, block=True)

  # quick boot
  if params.get_bool("QuickBootToggle") and not PC:
    prebuilt_path = "/data/openpilot/prebuilt"
    if not os.path.exists(prebuilt_path):
      open(prebuilt_path, 'x').close()

  if params.get_bool("RecordFrontLock"):
    params.put_bool("RecordFront", True, block=True)

  if not PC:
    run_migration(params)

  try:
    apply_sangw_defaults(params)  # [sangw 수정, docs/SANGW_MODS.md §7]
  except Exception:
    cloudlog.exception("sangw defaults failed")

  # set unset params to their default value
  for k in params.all_keys():
    default_value = params.get_default_value(k)
    if default_value is not None and params.get(k) is None:
      params.put(k, default_value, block=True)

  # Create folders needed for msgq
  try:
    os.mkdir(Paths.shm_path())
  except FileExistsError:
    pass
  except PermissionError:
    print(f"WARNING: failed to make {Paths.shm_path()}")

  # set params
  serial = HARDWARE.get_serial()
  params.put("Version", build_metadata.openpilot.version, block=True)
  params.put("GitCommit", build_metadata.openpilot.git_commit, block=True)
  params.put("GitCommitDate", build_metadata.openpilot.git_commit_date, block=True)
  params.put("GitBranch", build_metadata.channel, block=True)
  params.put("GitRemote", build_metadata.openpilot.git_origin, block=True)
  params.put_bool("IsDevelopmentBranch", build_metadata.development_channel, block=True)
  params.put_bool("IsTestedBranch", build_metadata.tested_channel, block=True)
  params.put_bool("IsReleaseBranch", build_metadata.release_channel, block=True)
  params.put_bool("IsReleaseSpBranch", build_metadata.release_sp_channel, block=True)
  params.put("HardwareSerial", serial, block=True)

  # set dongle id
  reg_res = register(show_spinner=True)
  if reg_res:
    dongle_id = reg_res
  else:
    raise Exception(f"Registration failed for device {serial}")
  os.environ['DONGLE_ID'] = dongle_id  # Needed for swaglog
  os.environ['GIT_ORIGIN'] = build_metadata.openpilot.git_normalized_origin # Needed for swaglog
  os.environ['GIT_BRANCH'] = build_metadata.channel # Needed for swaglog
  os.environ['GIT_COMMIT'] = build_metadata.openpilot.git_commit # Needed for swaglog

  if not build_metadata.openpilot.is_dirty:
    os.environ['CLEAN'] = '1'

  # init logging
  sentry.init(sentry.SentryProject.SELFDRIVE)
  cloudlog.bind_global(dongle_id=dongle_id,
                       version=build_metadata.openpilot.version,
                       origin=build_metadata.openpilot.git_normalized_origin,
                       branch=build_metadata.channel,
                       commit=build_metadata.openpilot.git_commit,
                       dirty=build_metadata.openpilot.is_dirty,
                       device=HARDWARE.get_device_type())

  # preimport all processes
  for p in managed_processes.values():
    p.prepare()


def manager_cleanup() -> None:
  # send signals to kill all procs
  for p in managed_processes.values():
    p.stop(block=False)

  # ensure all are killed
  for p in managed_processes.values():
    p.stop(block=True)

  cloudlog.info("everything is dead")


def manager_thread() -> None:
  cloudlog.bind(daemon="manager")
  cloudlog.info("manager start")
  cloudlog.info({"environ": os.environ})

  params = Params()

  ignore: list[str] = []
  if params.get("DongleId") in (None, UNREGISTERED_DONGLE_ID):
    ignore += ["manage_athenad", "uploader"]
  if os.getenv("NOBOARD") is not None:
    ignore.append("pandad")
  ignore += [x for x in os.getenv("BLOCK", "").split(",") if len(x) > 0]

  sm = messaging.SubMaster(['deviceState', 'carParams', 'pandaStates'], poll='deviceState')
  pm = messaging.PubMaster(['managerState'])

  write_onroad_params(False, params)
  ensure_running(managed_processes.values(), False, params=params, CP=sm['carParams'], not_run=ignore)

  started_prev = False
  ignition_prev = False

  while True:
    sm.update(1000)

    started = sm['deviceState'].started

    if started and not started_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION)
    elif not started and started_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION)

    ignition = any(ps.ignitionLine or ps.ignitionCan for ps in sm['pandaStates'] if ps.pandaType != log.PandaState.PandaType.unknown)
    if ignition and not ignition_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_IGNITION_ON)

    # update onroad params, which drives pandad's safety setter thread
    if started != started_prev:
      write_onroad_params(started, params)

    started_prev = started
    ignition_prev = ignition

    ensure_running(managed_processes.values(), started, params=params, CP=sm['carParams'], not_run=ignore)

    running = ' '.join("{}{}\u001b[0m".format("\u001b[32m" if p.proc.is_alive() else "\u001b[31m", p.name)
                       for p in managed_processes.values() if p.proc)
    print(running)
    cloudlog.debug(running)

    # send managerState
    msg = messaging.new_message('managerState', valid=True)
    msg.managerState.processes = [p.get_process_state_msg() for p in managed_processes.values()]
    pm.send('managerState', msg)

    # kick AGNOS power monitoring watchdog
    try:
      if sm.all_checks(['deviceState']):
        with atomic_write("/var/tmp/power_watchdog", "w", overwrite=True) as f:
          f.write(str(time.monotonic()))
    except Exception:
      pass

    # Exit main loop when uninstall/shutdown/reboot is needed
    shutdown = False
    for param in ("DoUninstall", "DoShutdown", "DoReboot"):
      if params.get_bool(param):
        shutdown = True
        params.put("LastManagerExitReason", f"{param} {datetime.datetime.now()}", block=True)
        cloudlog.warning(f"Shutting down manager - {param} set")

    if shutdown:
      break


def main() -> None:
  manager_init()
  if os.getenv("PREPAREONLY") is not None:
    return

  # SystemExit on sigterm
  signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(1))

  try:
    manager_thread()
  except Exception:
    traceback.print_exc()
    sentry.capture_exception()
  finally:
    manager_cleanup()

  params = Params()
  if params.get_bool("DoUninstall"):
    cloudlog.warning("uninstalling")
    HARDWARE.uninstall()
  elif params.get_bool("DoReboot"):
    cloudlog.warning("reboot")
    HARDWARE.reboot()
  elif params.get_bool("DoShutdown"):
    cloudlog.warning("shutdown")
    HARDWARE.shutdown()


if __name__ == "__main__":
  unblock_stdout()

  try:
    main()
  except KeyboardInterrupt:
    print("got CTRL-C, exiting")
  except Exception:
    add_file_handler(cloudlog)
    cloudlog.exception("Manager failed to start")

    try:
      managed_processes['ui'].stop()
    except Exception:
      pass

    # Show last 3 lines of traceback
    error = traceback.format_exc(-3)
    error = "Manager failed to start\n\n" + error
    with TextWindow(error) as t:
      t.wait_for_exit()

    raise

  # manual exit because we are forked
  sys.exit(0)
