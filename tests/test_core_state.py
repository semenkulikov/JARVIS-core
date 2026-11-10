import time

from jarvis.core.state import ListenerFSM, ListenerState, Mode, RequestLedger


def test_conversation_flow_is_valid():
    fsm = ListenerFSM()
    for mode in (Mode.LISTENING, Mode.PROCESSING, Mode.SPEAKING, Mode.PROCESSING, Mode.FOLLOWUP, Mode.PROCESSING, Mode.IDLE, Mode.SLEEP, Mode.PROCESSING):
        assert fsm.to(mode)
    assert fsm.invalid == 0


def test_invalid_transition_is_counted_not_raised():
    fsm = ListenerFSM()
    assert fsm.to(Mode.FOLLOWUP) is False and fsm.mode is Mode.FOLLOWUP and fsm.invalid == 1
    assert fsm.to(Mode.IDLE)  # always allowed: the error boundary


def test_speaking_returns_to_the_previous_mode():
    fsm = ListenerFSM(Mode.PROCESSING)
    with fsm.speaking():
        assert fsm.mode is Mode.SPEAKING
    assert fsm.mode is Mode.PROCESSING and fsm.invalid == 0


def test_state_perf_marks_the_trace():
    marks = []
    st = ListenerState()
    st.perf("ignored")
    st.trace = type("T", (), {"mark": lambda self, e, **m: marks.append((e, m))})()
    st.perf("route", route="time")
    assert marks == [("route", {"route": "time"})] and st.reply_parts == [] and ListenerState().reply_parts is not st.reply_parts


def test_ledger_cancels_and_expires_down_flag():
    led = RequestLedger()
    led.cancel("r1"); led.cancel(None)
    assert led.is_cancelled("r1") and list(led.cancelled) == ["r1"]
    led.down_since = time.time() - 120
    assert led.recently_down({"server_down_ttl_s": 600}) and not led.recently_down({"server_down_ttl_s": 60})
