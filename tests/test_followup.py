def test_followup_grammar_rescues_read_only_question(listener, cfg):
    assert listener.followup_rescue("ярость когда тренировках", "когда тренировка", cfg) == "когда тренировка"
    assert listener.followup_rescue("ярость сегодня", "когда тренировка", cfg) == ""
    assert listener.followup_rescue("выруби экран", "выруби экран", cfg) == ""  # actions are never rescued


def test_followup_rescue_needs_grammar_text(listener, cfg):
    assert listener.followup_rescue("когда тренировка", "", cfg) == ""
