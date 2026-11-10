def test_followup_grammar_rescues_read_only_question(app, cfg):
    assert app.c.router.followup_rescue("ярость когда тренировках", "когда тренировка", cfg) == "когда тренировка"
    assert app.c.router.followup_rescue("ярость сегодня", "когда тренировка", cfg) == ""
    assert app.c.router.followup_rescue("выруби экран", "выруби экран", cfg) == ""  # actions are never rescued


def test_followup_rescue_needs_grammar_text(app, cfg):
    assert app.c.router.followup_rescue("когда тренировка", "", cfg) == ""
