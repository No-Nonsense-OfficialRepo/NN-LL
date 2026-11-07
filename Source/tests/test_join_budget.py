from lantool.netcore.errors import JoinBudget


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_budget_caps_each_phase_to_its_own_limit():
    clock = FakeClock()
    b = JoinBudget(total=90, floor=15, clock=clock)
    assert b.slice(60) == 60


def test_budget_shrinks_second_phase_after_slow_first():
    clock = FakeClock()
    b = JoinBudget(total=90, floor=15, clock=clock)
    clock.t += 55
    assert b.remaining() == 35
    assert b.slice(60) == 35


def test_budget_never_starves_a_phase_below_floor():
    clock = FakeClock()
    b = JoinBudget(total=90, floor=15, clock=clock)
    clock.t += 200
    assert b.remaining() == 0
    assert b.slice(60) == 15


def test_budget_worst_case_is_total_plus_floor():
    clock = FakeClock()
    b = JoinBudget(total=90, floor=15, clock=clock)
    first = b.slice(60)
    clock.t += first
    second = b.slice(60)
    assert first + second <= 90 + 15
