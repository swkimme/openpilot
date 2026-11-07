# [sangw 수정] 앞차에 빠르게 다가갈 때만 차간 시간을 잠깐 늘림 (SANGW_MODS §5)
# 고속도로에서 느린 앞차에 "갑자기 확 가까워지는" 느낌(2026-11-07 상우) → 더 일찍 감속 시작.
# 같은 속도로 따라갈 땐 0이라 평소 거리는 그대로. 시내(50km/h 이하)도 그대로.
import numpy as np

CLOSING_BP = [1.5, 8.3]    # m/s. 다가가는 속도 약 5 → 30km/h
BOOST_V = [0.0, 0.6]       # 초. 차간 시간에 더하는 값(20km/h로 다가가면 약 0.37초)
SPEED_BP = [50. / 3.6, 70. / 3.6]  # m/s. 내 속도 50km/h 이하 끔, 70km/h부터 전부 적용
RISE_TAU = 1.0             # 초. 카메라 앞차 속도가 튀어도 바로 안 뛰게
FALL_TAU = 3.0             # 초. 속도가 맞은 뒤 천천히 풀어 다시 가속으로 꿀렁이지 않게


class ClosingFollowBoost:
  def __init__(self, dt: float):
    self.dt = dt
    self.x = 0.0

  def update(self, v_ego: float, lead_status: bool, v_lead: float) -> float:
    target = 0.0
    if lead_status:
      target = float(np.interp(v_ego - v_lead, CLOSING_BP, BOOST_V) * np.interp(v_ego, SPEED_BP, [0.0, 1.0]))
    tau = RISE_TAU if target > self.x else FALL_TAU
    self.x += (target - self.x) * self.dt / (tau + self.dt)
    return self.x
