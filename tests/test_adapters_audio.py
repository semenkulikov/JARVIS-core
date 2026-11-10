import numpy as np

from jarvis.adapters import audio as A


def test_mic_callback_drops_frames_when_the_queue_is_full():
    mic = A.MicInput(maxsize=1)
    block = np.ones((4, 1), dtype=np.float32)
    mic.callback(block, 4, None, None); mic.callback(block * 2, 4, None, None)
    assert mic.queue.qsize() == 1 and mic.queue.get().tolist() == [1.0] * 4


def test_levels_report_resets(caplog):
    lv = A.MicLevels()
    lv.add(np.array([0.5, -0.25], dtype=np.float32))
    with caplog.at_level("INFO", logger="jarvis"):
        lv.report()
    assert "peak=0.500" in caplog.text and (lv.max, lv.n) == (0.0, 0)


def test_capture_starts_with_the_prebuffer():
    cap = A.Capture([np.zeros(A.SR // 2, np.float32), np.zeros(A.SR // 2, np.float32)])
    assert cap.q.qsize() == 2


def test_agc_lifts_quiet_speech_and_can_be_off():
    x = np.full(10, 0.05, np.float32)
    assert A.AGC({})(x).max() > 0.5 and A.AGC({"vosk_agc": False})(x) is x


def test_double_clap_is_detected():
    cfg = dict(clap_min_peak=0.2, clap_ratio=10.0, clap_attack=4.0, clap_max_len_s=0.15, clap_decay=0.25, clap_gap_min_s=0.12,
               clap_gap_max_s=0.9, clap_quiet_s=0.5, clap_peak_similarity=4.0, clap_log_min_peak=0.08, clap_tail_s=0.25,
               clap_noise_rel=0.35, clap_noise_attack=2.0)
    sig = np.full(A.SR * 2, 0.001, np.float32)
    for start in (int(0.2 * A.SR), int(0.6 * A.SR)):
        sig[start:start + 480] = 0.8
    det = A.ClapDetector(); hits = []
    for pos in range(0, len(sig), A.CHUNK):
        hits.append(det.feed(sig[pos:pos + A.CHUNK], pos, cfg))
    assert any(hits)
