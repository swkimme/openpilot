# [sangw 수정] 정지선 오프셋 (SANGW_MODS §13)
# 실험 모드(e2e)는 모델이 낸 감속을 그대로 써서 정지선보다 약 3m 앞에서 섬(2026-11-06 상우).
# 모델 계획이 '정지'로 바뀌면 그 정지 지점 + OFFSET을 주행거리 기준으로 고정하고,
# 그 지점에 맞는 등감속(-v²/2d)보다 모델이 더 세게 밟으면 등감속을 씀 → 덜 밟아서 더 가서 섬.
# 더 세게 밟는 쪽으로는 절대 바꾸지 않음(항상 max).
import numpy as np

STOP_LINE_OFFSET = 2.0   # m. 모델 정지 지점보다 이만큼 더 가서 섬
MIN_LATCH_SPEED = 2.0    # m/s. 이보다 느릴 때는 새로 잡지 않음(정차·서행 중)
MAX_LATCH_SPEED = 22.0   # m/s(약 80km/h). 이보다 빠를 때는 새로 잡지 않음
PLAN_STOP_V = 0.5        # m/s. 모델 계획 속도가 이 아래로 떨어지면 '정지 계획'
PLAN_GO_V = 3.0          # m/s. 계획 끝 속도가 이보다 크면 해제(신호가 바뀜 등)
FREEZE_DIST = 3.0        # m. 모델 정지 지점이 이보다 가까우면 목표를 더 고치지 않음
EARLY_STOP_MARGIN = 2.0  # m. 모델이 이만큼(멀 땐 남은 거리의 10%) 더 일찍 서려 하면(새 장애물) 해제하고 모델대로
LEAD_MARGIN = 15.0       # m. 레이더 앞차가 목표 지점 + 이 거리 안이면 모델대로
EARLY_STOP_FRAMES = 3    # 위 조건이 이만큼 연속(20Hz 3번 = 0.15초)일 때만 해제 — 모델 값이 한 번 튀는 걸로는 안 끔
FILTER_K = 0.2           # 목표 지점 갱신 비율(20Hz 기준 약 0.25초)
MIN_REMAINING = 0.2      # m. 목표까지 이보다 가까우면 모델대로


class StopLineOffset:
  def __init__(self, dt: float, offset: float = STOP_LINE_OFFSET):
    self.dt = dt
    self.offset = offset
    self.s = 0.0           # 주행거리(m)
    self.target = None     # 고정한 정지 목표(주행거리 기준)
    self.blocked = False   # 새 장애물로 해제한 뒤엔 출발·정차 전까지 다시 안 잡음
    self.active = False    # 이번 주기에 모델 감속을 바꿨는지(로그용)
    self.early_cnt = 0

  def _release(self, blocked: bool = False) -> None:
    self.target = None
    self.blocked = blocked
    self.early_cnt = 0

  def update(self, enabled: bool, v_ego: float, plan_x, plan_v, lead_status: bool, lead_d: float, a_model: float) -> float:
    self.s += max(v_ego, 0.0) * self.dt
    self.active = False

    if not enabled or len(plan_v) == 0 or len(plan_x) != len(plan_v):
      self._release()
      return a_model

    plan_x = np.asarray(plan_x, dtype=float)
    plan_v = np.asarray(plan_v, dtype=float)

    # 모델이 계속 가려 하거나, 차가 섰으면 초기화
    if plan_v[-1] > PLAN_GO_V or v_ego < 0.1:
      self._release()
      return a_model

    d_model = None
    if plan_v[-1] < PLAN_STOP_V:
      d_model = max(float(plan_x[int(np.argmax(plan_v < PLAN_STOP_V))]), 0.0)

    if self.target is None:
      if d_model is None or self.blocked or not (MIN_LATCH_SPEED < v_ego < MAX_LATCH_SPEED):
        return a_model
      self.target = self.s + d_model + self.offset
    elif d_model is not None:
      rem_model = self.target - self.offset - self.s  # 고정해 둔 모델 정지 지점까지 남은 거리
      if d_model < rem_model - max(EARLY_STOP_MARGIN, 0.1 * rem_model):
        # 모델이 훨씬 일찍 서려 함 = 새 장애물·보행자 → 오프셋 끄고 모델대로
        self.early_cnt += 1
        if self.early_cnt >= EARLY_STOP_FRAMES:
          self._release(blocked=True)
          return a_model
      else:
        self.early_cnt = 0
      if d_model > FREEZE_DIST and self.early_cnt == 0:
        self.target += FILTER_K * (self.s + d_model + self.offset - self.target)

    rem = self.target - self.s
    if rem < MIN_REMAINING:
      return a_model
    if lead_status and lead_d < rem + LEAD_MARGIN:
      return a_model

    a_needed = -(v_ego ** 2) / (2.0 * rem)
    if a_needed > a_model:
      self.active = True
      return a_needed
    return a_model
