"""Project commands with fake network and process runners only."""
import subprocess
import urllib.error
import pytest
from jarvis.app.context import build_controller
from jarvis.core import quick as Q
from jarvis.core import projects as P
from jarvis.adapters.project_tools import ProjectTools
from test_commands import FakeBackend

CFG = {'servers': [{'name': 'example', 'spoken': ['пример'], 'url': 'https://example.invalid/health'},
                   {'name': 'router', 'spoken': ['роутер'], 'host': '192.0.2.1', 'port': 80}],
       'projects': {'demo': {'path': '.', 'spoken': ['демо'], 'test_command': ['python', '-m', 'pytest', '-q']}}}


class Resp:
    def __init__(self, status): self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): return False


class Conn:
    def close(self): pass


def tools(tmp_path, opener=None, connect=None, runner=None):
    return ProjectTools(tmp_path, opener=opener or (lambda req, timeout: Resp(200)),
                          connect=connect or (lambda addr, timeout: Conn()), runner=runner or pytest.fail)


@pytest.mark.parametrize('text,cmd,key,value', [
    ('статус сервера пример', 'server_health', 'target', 'пример'),
    ('проверь серверы', 'server_health', 'target', ''),
    ('запусти тесты проекта демо', 'project_tests', 'project', 'демо'),
    ('прогони тесты', 'project_tests', 'project', '')])
def test_match(text, cmd, key, value):
    a = Q.match(text); assert a['cmd'] == cmd and a[key] == value


def test_status_of_tasks_is_not_a_server_check():
    a = Q.match('статус по задачам'); assert a is None or a['cmd'] != 'server_health'


def test_http_health_ok(tmp_path):
    assert ProjectTools.health_reply(tools(tmp_path), 'пример', CFG).startswith('Сервер example отвечает')


def test_http_health_error_code(tmp_path):
    def opener(req, timeout): raise urllib.error.HTTPError(req.full_url, 503, 'x', {}, None)
    assert 'код 503' in tools(tmp_path, opener=opener).health_reply('пример', CFG)


def test_tcp_health_and_all(tmp_path):
    def connect(addr, timeout): raise OSError('refused')
    reply = tools(tmp_path, connect=connect).health_reply('', CFG)
    assert reply.startswith('Не отвечают: router') and 'example' not in reply


def test_unknown_and_unconfigured(tmp_path):
    t = tools(tmp_path)
    assert t.health_reply('марс', CFG) == 'Не знаю такой сервер, сэр.'
    assert 'не настроены' in t.health_reply('', {})


def test_non_http_urls_are_ignored():
    assert P.servers({'servers': [{'name': 'x', 'url': 'file:///etc/passwd'}]}) == []


def test_projects_require_argument_list():
    assert P.projects({'projects': {'a': {'path': '.', 'test_command': 'pytest && rm -rf /'}}}) == []


def test_run_tests_without_shell_and_sanitized_env(tmp_path, monkeypatch):
    monkeypatch.setenv('JARVIS_HOME', 'secret-home'); monkeypatch.setenv('FATSECRET_ACCESS_TOKEN', 'x')
    seen = {}
    def runner(args, **kw):
        seen.update(args=args, **kw); return subprocess.CompletedProcess(args, 0, '..\n2 passed in 0.1s\n', '')
    run = tools(tmp_path, runner=runner).run_tests(P.projects(dict(CFG, projects={'demo': dict(CFG['projects']['demo'], path=str(tmp_path))}))[0])
    assert seen['args'] == ['python', '-m', 'pytest', '-q'] and 'shell' not in seen and seen['cwd'] == str(tmp_path)
    assert 'JARVIS_HOME' not in seen['env'] and 'FATSECRET_ACCESS_TOKEN' not in seen['env']
    assert run.ok and run.summary == '2 успешно' and P.tests_phrase(run) == 'Тесты проекта demo прошли: 2 успешно, сэр.'
    assert '2 passed' in open(run.report, encoding='utf-8').read()


def test_failed_and_timeout(tmp_path):
    p = P.Project('demo', str(tmp_path), ('x',), timeout_s=1)
    r = tools(tmp_path, runner=lambda a, **k: subprocess.CompletedProcess(a, 1, '= 1 failed, 3 passed in 1s =', '')).run_tests(p)
    assert not r.ok and P.tests_phrase(r).endswith('Подробности в отчёте.') and '1 с ошибкой' in r.summary
    def slow(a, **k): raise subprocess.TimeoutExpired(a, 1)
    assert 'не уложились' in tools(tmp_path, runner=slow).run_tests(p).summary


def test_start_tests_announces_when_done(tmp_path, cfg):
    cfg.update(CFG, projects={'demo': dict(CFG['projects']['demo'], path=str(tmp_path))})
    t = tools(tmp_path, runner=lambda a, **k: subprocess.CompletedProcess(a, 0, '5 passed', ''))
    c = build_controller(tmp_path, FakeBackend(), tools=t); said = []
    c.execute(Q.match('запусти тесты проекта демо', cfg), '', cfg, lambda x, s, **k: said.append(x) or True, None, test=True)
    assert said[-1].startswith('Запускаю тесты проекта demo')
    t._running['demo'].join(5)
    c.timers.clock = lambda: 10 ** 12  # the listener polls this same store
    assert c.timers.pop_fired() == [{'label': 'Тесты проекта demo прошли: 5 успешно, сэр.', 'kind': 'notice'}]


def test_missing_project_folder(tmp_path):
    cfg = dict(CFG, projects={'demo': dict(CFG['projects']['demo'], path=str(tmp_path / 'missing'))})
    assert 'не найдена' in tools(tmp_path).start_tests('демо', cfg, pytest.fail)
