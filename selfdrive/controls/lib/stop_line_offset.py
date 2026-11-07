# [sangw 수정] 정지선 오프셋 (SANGW_MODS §13)
# 실험 모드(e2e)는 모델이 낸 감속을 그대로 써서 정지선을 약 3m 넘어서 섬(2026-11-06 상우).
# 모델 계획이 '정지'로 바뀌면 그 정지 지점 - OFFSET을 주행거리 기준으로 고정하고,
# 그 지점까지 -K·v²/d로 밟음 → 덜 가서 섬. K>0.5라 끝으로 갈수록 감속이 0으로 줄어 부드럽게 멈춤.
# 멀리서부터 미리 밟지는 않음.
# 덜 밟는 쪽으로는 절대 바꾸지 않음(항상 min). 선 뒤에 선 뒤엔 신호가 바뀔 때까지 붙잡아 둠.
import numpy as np

STOP_LINE_OFFSET = 2.0   # m. 모델 정지 지점보다 이만큼 덜 가서 섬
MIN_LATCH_SPEED = 2.0    # m/s. 이보다 느릴 때는 새로 잡지 않음(정차·서행 중)
MAX_LATCH_SPEED = 22.0   # m/s(약 80km/h). 이보다 빠를 때는 새로 잡지 않음
PLAN_STOP_V = 0.5        # m/s. 모델 계획 끝 속도가 이 아래면 '정지 계획'
PLAN_KEEP_V = 1.0        # m/s. 계획 끝 속도가 이보다 크면 바로 해제(모델이 계속 가려 함·신호 바뀜)
STOP_PLAN_FRAMES = 10    # 정지 계획이 이만큼 연속(20Hz 10번 = 0.5초)일 때만 잡음 — 한순간 튄 계획으로 서지 않게
MIN_LATCH_REM = 2.0      # m. 목표까지 이보다 가까우면 안 잡음(이미 늦음 → 모델대로)
FREEZE_REM = 3.0         # m. 목표까지 이보다 가까우면 목표를 더 고치지 않음
LEAD_MARGIN = 15.0       # m. 앞차(이 차는 카메라로 잡음)가 목표 지점 + 이 거리 안이면 모델대로(앞차 뒤 정지는 그대로)
FILTER_K = 0.2           # 목표 지점 갱신 비율(20Hz 기준 약 0.25초)
MAX_EXTRA_DECEL = -2.5   # m/s². 오프셋 때문에 이보다 세게는 안 밟음(모델이 원래 세게 밟는 건 그대로)
BLEND_DECEL = (0.8, 1.4)  # m/s². 필요한 감속이 앞 값을 넘으면 섞기 시작, 뒤 값부터 전부 적용 — 멀리서부터 미리 밟지 않게
PAST_TARGET_DECEL = -0.4  # m/s². 목표를 지났는데 아직 굴러가면 최소 이만큼 밟음
SOFT_STOP_K = 0.6        # 감속 = -K·v²/남은거리. 0.5면 끝까지 같은 세기(정지 단계가 그 값을 물고 툭 섬), 클수록 끝에서 빨리 줄고 처음이 셈
MIN_REM = 0.3            # m. 남은 거리를 이보다 작게 안 봄 — 끝에서 감속이 튀지 않게
HOLD_SPEED = 0.3         # m/s. 이보다 느리고
STOPPED_SPEED = 0.05     # m/s. 이보다 느리면 선 것으로 봄
HOLD_REM = 0.2           # m. 목표까지 이보다 가까우면(지난 경우 포함) 정지 유지


class StopLineOffset:
  def __init__(self, dt: float, offset: float = STOP_LINE_OFFSET):
    self.dt = dt
    self.offset = offset
    self.s = 0.0           # 주행거리(m)
    self.target = None     # 고정한 정지 목표(주행거리 기준)
    self.stop_cnt = 0      # 정지 계획이 연속으로 나온 횟수
    self.w = 0.0           # 오프셋 감속을 섞는 비율. 한 번 올라가면 이번 정지 끝까지 안 내림 — v²에 묶이면 저속에서 도로 0이 돼 목표를 지나감

  def _release(self) -> None:
    self.target = None
    self.stop_cnt = 0
    self.w = 0.0

  def update(self, enabled: bool, v_ego: float, plan_x, plan_v, lead_status: bool, lead_d: float,
             a_model: float) -> tuple[float, bool]:
    """(가속 목표, 정지 유지 여부)를 돌려줌. 오프셋을 안 쓸 땐 (a_model, False)."""
    self.s += max(v_ego, 0.0) * self.dt

    if not enabled or self.offset <= 0 or len(plan_v) == 0 or len(plan_x) != len(plan_v):
      self._release()
      return a_model, False

    plan_x = np.asarray(plan_x, dtype=float)
    plan_v = np.asarray(plan_v, dtype=float)

    # 모델이 계속 가려 함(신호 바뀜·서행) → 해제
    if plan_v[-1] > PLAN_KEEP_V:
      self._release()
      return a_model, False

    d_model = None
    if plan_v[-1] < PLAN_STOP_V:
      d_model = max(float(plan_x[int(np.argmax(plan_v < PLAN_STOP_V))]), 0.0)
      self.stop_cnt += 1
    else:
      self.stop_cnt = 0

    if self.target is None:
      if d_model is None or self.stop_cnt < STOP_PLAN_FRAMES or not (MIN_LATCH_SPEED < v_ego < MAX_LATCH_SPEED):
        return a_model, False
      rem_new = d_model - self.offset
      # 이미 늦었으면(목표가 너무 가깝거나 세게 밟아야 함) 이번 정지는 모델대로
      if rem_new < MIN_LATCH_REM or -SOFT_STOP_K * v_ego ** 2 / rem_new < MAX_EXTRA_DECEL:
        return a_model, False
      self.target = self.s + rem_new
    elif d_model is not None and self.target - self.s > FREEZE_REM:
      self.target += FILTER_K * (self.s + d_model - self.offset - self.target)

    rem = self.target - self.s
    if lead_status and lead_d < max(rem, 0.0) + LEAD_MARGIN:
      self._release()
      return a_model, False

    # 목표에서 거의 섰으면 정지 유지 — 모델이 남은 거리를 기어가려고 다시 출발하는 것 막음
    if (v_ego < HOLD_SPEED and rem < HOLD_REM) or (v_ego < STOPPED_SPEED and self.w > 0.0 and rem < FREEZE_REM):
      return min(a_model, 0.0), True

    # HOLD_SPEED로 목표에 닿게 밟음 — 0으로 잡으면 목표 전에 느려져 일찍 정지 유지가 걸림
    a_needed = max(-SOFT_STOP_K * max(v_ego ** 2 - HOLD_SPEED ** 2, 0.0) / max(rem, MIN_REM), MAX_EXTRA_DECEL)
    if rem <= 0.1:
      a_needed = min(a_needed, PAST_TARGET_DECEL)
    w = (-a_needed - BLEND_DECEL[0]) / (BLEND_DECEL[1] - BLEND_DECEL[0])
    self.w = max(self.w, float(np.clip(w, 0.0, 1.0)))
    return a_model + self.w * (min(a_model, a_needed) - a_model), False
