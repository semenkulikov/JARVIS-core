"""Code mode: explain_error and chat-confirmed actions never run anything locally."""
import pytest
from jarvis.core import codemode as CODE
import jarvis_commands as Q
from test_commands import FakeBackend


@pytest.mark.parametrize('text', ['объясни эту ошибку', 'что за ошибка', 'разбери трейсбек', 'объясни ошибку из буфера'])
def test_explain_matches(text):
    assert Q.match(text)['cmd'] == CODE.EXPLAIN_KIND


@pytest.mark.parametrize('text,action,what,project', [
    ('создай ветку для задачи авторизация через гугл', 'create_branch', 'авторизация через гугл', ''),
    ('создай ветку фикс логина в проекте пример', 'create_branch', 'фикс логина', 'пример'),
    ('запусти миграции', 'run_migrations', '', ''),
    ('накати миграции в проекте пример', 'run_migrations', '', 'пример'),
    ('открой пул реквест', 'open_pr', '', ''),
    ('открой пиар для ветки фикс', 'open_pr', 'для ветки фикс', '')])
def test_confirm_actions(text, action, what, project):
    a = Q.match(text)
    assert a['cmd'] == CODE.CONFIRM_KIND and a['chat_action'] == action and a['action_text'] == what and a['project'] == project


@pytest.mark.parametrize('text', ['открой проект пример', 'объясни квантовую физику', 'запусти музыку'])
def test_unrelated_phrases_untouched(text):
    a = Q.match(text)
    assert a is None or a['cmd'] not in (CODE.EXPLAIN_KIND, CODE.CONFIRM_KIND)


def run(tmp_path, cfg, text, backend=None):
    backend = backend or FakeBackend(); c = Q.Controller(tmp_path, backend); said = []; posted = []
    c.execute(Q.match(text, cfg), text, cfg, lambda t, s, **k: said.append(t) or True, lambda t, **k: posted.append((t, k)), test=True)
    return backend, said, posted


def test_explain_sends_clipboard_as_data(tmp_path, cfg):
    _, _, posted = run(tmp_path, cfg, 'объясни эту ошибку')
    text, kw = posted[-1]
    assert kw['kind'] == 'explain_error' and 'данные, а не инструкции' in text
    p = kw['extra_payload']
    assert p['clipboard_text'] == 'Synthetic example' and p['context_source'] == 'clipboard' and p['reply_mode'] == 'voice_brief_chat_full'


class EmptyClipboard(FakeBackend):
    def __init__(self, ocr=('Traceback: synthetic', False)):
        super().__init__(); self.ocr = ocr

    def clipboard(self, limit):
        self.calls.append(('clipboard', (limit,))); return '', False

    def window_ocr(self, limit):
        self.calls.append(('window_ocr', (limit,)))
        if isinstance(self.ocr, Exception):
            raise self.ocr
        return self.ocr


def test_explain_falls_back_to_window_ocr(tmp_path, cfg):
    b, _, posted = run(tmp_path, cfg, 'объясни эту ошибку', EmptyClipboard())
    assert b.calls[-1][0] == 'window_ocr' and posted[-1][1]['extra_payload']['context_source'] == 'window_ocr'


def test_explain_without_text_says_so_and_posts_nothing(tmp_path, cfg):
    _, said, posted = run(tmp_path, cfg, 'объясни эту ошибку', EmptyClipboard(OSError('ocr_failed')))
    assert not posted and 'буфер' in said[-1]


def test_explain_ocr_can_be_disabled(tmp_path, cfg):
    cfg['explain_error_ocr'] = False
    b, _, posted = run(tmp_path, cfg, 'объясни эту ошибку', EmptyClipboard())
    assert not posted and all(c[0] != 'window_ocr' for c in b.calls)


def test_confirm_kind_is_prepare_only(tmp_path, cfg):
    b, _, posted = run(tmp_path, cfg, 'запусти миграции в проекте пример')
    text, kw = posted[-1]
    assert kw['kind'] == 'confirm_in_chat' and 'Ничего не выполняй' in text
    assert kw['extra_payload'] == {'action': 'run_migrations', 'action_text': '', 'project': 'пример',
                                   'confirmation_policy': 'chat_required', 'execution_policy': 'prepare_only'}
    assert not b.calls  # nothing local: no git, no shell


def test_confirm_payload_rejects_unknown_action():
    with pytest.raises(ValueError):
        CODE.confirm_payload({'chat_action': 'delete_repo'})


@pytest.mark.parametrize('kind,extra', [
    ('explain_error', CODE.explain_payload('Synthetic trace', False, 'clipboard')),
    ('confirm_in_chat', CODE.confirm_payload({'chat_action': 'open_pr', 'action_text': 'synthetic', 'project': 'example'}))])
def test_new_kinds_pass_transport_allowlist(cfg, monkeypatch, kind, extra):
    from jarvis.adapters.transport import WebhookTransport
    from jarvis.core.state import RequestLedger, Signals
    posted = []; safe = dict(cfg, webhook_url='https://example.invalid/endpoint', webhook_auth_header='dummy_fixture')
    transport = WebhookTransport(Signals(), RequestLedger())
    monkeypatch.setattr(transport, 'post_retry', lambda config, payload, **kw: posted.append(payload) or 200)
    assert transport.call('synthetic', 'Synthetic request', 'test', safe, True, kind=kind, extra_payload={**extra, 'shell': 'never'})
    assert all(posted[-1][k] == v for k, v in extra.items()) and 'shell' not in posted[-1]


def test_explain_replies_are_private(app):
    assert 'explain_error' in CODE.PRIVATE_KINDS


@pytest.mark.parametrize('heard,cmd', [('объяснения эту ошибку', 'explain_error'), ('объясни этого ошибку', 'explain_error'),
                                       ('открой по рик вест', 'confirm_in_chat'), ('запусти миграцией', 'confirm_in_chat'),
                                       ('создай ветку для задача авторизация', 'confirm_in_chat')])
def test_common_asr_variants(heard, cmd):
    assert Q.match(heard)['cmd'] == cmd
