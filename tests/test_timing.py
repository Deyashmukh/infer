from spike.timing import Timer


def test_timer_records_duration_with_fake_clock():
    ticks = iter([100.0, 103.5])  # start, stop
    timer = Timer(clock=lambda: next(ticks))
    timer.start("mfa_to_pdf")
    assert timer.stop("mfa_to_pdf") == 3.5
    assert timer.durations["mfa_to_pdf"] == 3.5


def test_timer_to_dict_is_serializable():
    ticks = iter([0.0, 2.0])
    timer = Timer(clock=lambda: next(ticks))
    timer.start("login")
    timer.stop("login")
    assert timer.to_dict() == {"login": 2.0}
