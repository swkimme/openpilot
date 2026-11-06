# [sangw 수정] 정지선 오프셋 (SANGW_MODS §13)
# 실험 모드(e2e)는 모델이 낸 감속을 그대로 써서 정지선을 약 3m 넘어서 섬(2026-11-06 상우).
# 모델 계획이 '정지'로 바뀌면 그 정지 지점 - OFFSET을 주행거리 기준으로 고정하고,
# 그 지점에 맞는 등감속(-v²/2d)이 모델보다 세면 등감속을 씀 → 더 밟아서 덜 가서 섬.
# 덜 밟는 쪽으로는 절대 바꾸지 않음(항상 min). 선 뒤에 선 뒤엔 신호가 바뀔 때까지 붙잡아 둠.
import numpy as np

STOP_LINE_OFFSET = 3.0   # m. 모델 정지 지점보다 이만큼 덜 가서 섬
MIN_LATCH_SPEED = 2.0    # m/s. 이보다 느릴 때는 새로 잡지 않음(정차·서행 중)
MAX_LATCH_SPEED = 22.0   # m/s(약 80km/h). 이보다 빠를 때는 새로 잡지 않음
PLAN_STOP_V = 0.5        # m/s. 모델 계획 속도가 이 아래로 떨어지면 '정지 계획'
PLAN_GO_V = 3.0          # m/s. 계획 끝 속도가 이보다 크면 해제(신호가 바뀜 등)
FREEZE_REM = 3.0         # m. 목표까지 이보다 가까우면 목표를 더 고치지 않음
LEAD_MARGIN = 15.0       # m. 레이더 앞차가 목표 지점 + 이 거리 안이면 모델대로(앞차 뒤 정지는 그대로)
FILTER_K = 0.2           # 목표 지점 갱신 비율(20Hz 기준 약 0.25초)
MAX_EXTRA_DECEL = -2.5   # m/s². 오프셋 때문에 이보다 세게는 안 밟음(모델이 원래 세게 밟는 건 그대로)
HOLD_SPEED = 0.3         # m/s. 목표 근처에서 이보다 느리면 정지 유지


class StopLineOffset:
  def __init__(self, dt: float, offset: float = STOP_LINE_OFFSET):
    self.dt = dt
    self.offset = offset
    self.s = 0.0           # 주행거리(m)
    self.target = None     # 고정한 정지 목표(주행거리 기준)

  def update(self, enabled: bool, v_ego: float, plan_x, plan_v, lead_status: bool, lead_d: float,
             a_model: float) -> tuple[float, bool]:
    """(가속 목표, 정지 유지 여부)를 돌려줌. 오프셋을 안 쓸 땐 (a_model, False)."""
    self.s += max(v_ego, 0.0) * self.dt

    if not enabled or self.offset <= 0 or len(plan_v) == 0 or len(plan_x) != len(plan_v):
      self.target = None
      return a_model, False

    plan_x = np.asarray(plan_x, dtype=float)
    plan_v = np.asarray(plan_v, dtype=float)

    # 모델이 다시 가려 함(신호 바뀜) → 해제
    if plan_v[-1] > PLAN_GO_V:
      self.target = None
      return a_model, False

    d_model = None
    if plan_v[-1] < PLAN_STOP_V:
      d_model = max(float(plan_x[int(np.argmax(plan_v < PLAN_STOP_V))]), 0.0)

    if self.target is None:
      if d_model is None or not (MIN_LATCH_SPEED < v_ego < MAX_LATCH_SPEED):
        return a_model, False
      self.target = self.s + d_model - self.offset
    elif d_model is not None and self.target - self.s > FREEZE_REM:
      self.target += FILTER_K * (self.s + d_model - self.offset - self.target)

    rem = self.target - self.s
    if lead_status and lead_d < max(rem, 0.0) + LEAD_MARGIN:
      self.target = None
      return a_model, False

    # 목표 근처(또는 지남)에서 거의 섰으면 정지 유지 — 모델이 3m 더 가려고 다시 출발하는 것 막음
    if v_ego < HOLD_SPEED and rem < FREEZE_REM:
      return min(a_model, 0.0), True

    if rem <= 0.1:
      a_needed = MAX_EXTRA_DECEL
    else:
      a_needed = max(-(v_ego ** 2) / (2.0 * rem), MAX_EXTRA_DECEL)
    return min(a_model, a_needed), False
