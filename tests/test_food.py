"""Local food logging against a fake FatSecret diary; no real entries are ever created."""
import datetime
import json
import pytest
import jarvis_commands as Q
from pathlib import Path

from jarvis.adapters.food_diary import AliasCache, FoodLogger
from jarvis.core import food as F
from test_commands import FakeBackend

NOW = datetime.datetime(2030, 1, 2, 13, 0)
DAY = F.epoch_day(NOW.date())
ALIASES = [{'names': ['творог', 'творога', 'творогу'], 'food_id': '1', 'serving_id': '10', 'label': 'Творог',
            'kcal_per_unit': 1.03, 'protein_per_unit': 0.125},
           {'names': ['яйцо', 'яйца', 'яиц'], 'food_id': '2', 'serving_id': '20', 'label': 'Яйца', 'piece_g': 50},
           {'names': ['кефир', 'кефира'], 'food_id': '3', 'serving_id': '30', 'label': 'Кефир', 'unit': 'ml'}]


class FakeDiary:
    def __init__(self, entries=None, fail_create=False, fail_read=False, day=DAY):
        self.day = day; self.entries = list(entries or []); self.calls = []; self.fail_create = fail_create; self.fail_read = fail_read

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method == 'food_entries.get':
            if self.fail_read: raise OSError('net')
            assert self.day is None or params['date'] == str(self.day)
            return {'food_entries': {'food_entry': list(self.entries)}} if self.entries else {'food_entries': None}
        if method == 'food_entry.create':
            n = float(params['number_of_units'])
            entry = {'food_entry_id': str(100 + len(self.entries)), 'food_id': params['food_id'], 'number_of_units': '%.3f' % n,
                     'calories': str(round(n * 1.03)), 'protein': str(round(n * 0.125, 2)), 'meal': params['meal']}
            self.entries.append(entry)
            if self.fail_create: raise OSError('lost response')
            return {'food_entry_id': {'value': entry['food_entry_id']}}
        raise AssertionError(method)

    def creates(self):
        return [p for m, p in self.calls if m == 'food_entry.create']


@pytest.fixture
def home(tmp_path):
    (tmp_path / 'cache').mkdir()
    (tmp_path / 'cache' / 'food_aliases.json').write_text(json.dumps({'version': 1, 'foods': ALIASES}, ensure_ascii=False), encoding='utf-8')
    return tmp_path


def logger(home, diary, clock=lambda: 1000.0, **cfg):
    c = dict(F.DEFAULTS, food_local_enabled=True, nutrition_targets={'calories': 3500, 'protein_g': 150}, **cfg)
    return FoodLogger(home, diary, c, now=lambda: NOW, clock=clock)


@pytest.mark.parametrize('text,amount,unit,food,meal', [
    ('добавь 200 грамм творога', 200, 'g', 'творога', None),
    ('добавь двести пятьдесят грамм творога на ужин', 250, 'g', 'творога', 'dinner'),
    ('добавь два яйца', 2, 'pc', 'яйца', None),
    ('добавь творог 200 грамм', 200, 'g', 'творог', None),
    ('добавь 1,5 кг творога', 1500, 'g', 'творога', None),
    ('запиши в дневник 300 мл кефира', 300, 'ml', 'кефира', None)])
def test_parse(text, amount, unit, food, meal):
    assert F.parse(text) == F.FoodRequest(amount, unit, food, meal)


@pytest.mark.parametrize('text', ['добавь творог', 'добавь 200 грамм творога и банан', 'добавь творог, банан', 'добавь задачу купить хлеб'])
def test_parse_needs_server(text):
    assert F.parse(text) is None


def test_logs_once_and_reports_remaining(home):
    d = FakeDiary([{'food_entry_id': '1', 'food_id': '9', 'number_of_units': '1', 'calories': '500', 'protein': '40'}])
    r = logger(home, d).log_text('добавь 200 грамм творога')
    assert r.status == 'logged' and r.entry_id == '101'
    assert d.creates() == [{'food_id': '1', 'serving_id': '10', 'number_of_units': '200', 'meal': 'lunch',
                            'food_entry_name': 'Творог', 'date': str(DAY)}]
    assert r.spoken == ('Записал: творог, 200 грамм. 206 килокалорий, 25 грамм белка. '
                        'До нормы белка 85 грамм, до нормы калорий 2794 килокалорий, сэр.')


def test_repeated_command_is_not_logged_twice(home):
    d = FakeDiary(); t = [1000.0]
    assert logger(home, d, clock=lambda: t[0]).log_text('добавь 200 грамм творога').status == 'logged'
    t[0] += 30
    r = logger(home, d, clock=lambda: t[0]).log_text('добавь двести грамм творога')
    assert r.status == 'duplicate' and len(d.creates()) == 1
    t[0] += 600
    assert logger(home, d, clock=lambda: t[0]).log_text('добавь 200 грамм творога').status == 'logged'


def test_lost_create_response_is_read_back_not_retried(home):
    d = FakeDiary(fail_create=True)
    r = logger(home, d).log_text('добавь 200 грамм творога')
    assert r.status == 'logged' and len(d.creates()) == 1


def test_diary_down_before_write_falls_back_without_writing(home):
    d = FakeDiary(fail_read=True)
    assert logger(home, d).log_text('добавь 200 грамм творога').status == 'unavailable' and not d.creates()


@pytest.mark.parametrize('text,reason', [('добавь 200 грамм банана', 'unknown_food'), ('добавь 200 мл творога', 'amount'),
                                         ('добавь 5 кг творога', 'amount'), ('добавь творог', 'unparsed')])
def test_ambiguous_goes_to_server(home, text, reason):
    d = FakeDiary(); r = logger(home, d).log_text(text)
    assert (r.status, r.reason) == ('ambiguous', reason) and not d.calls


def test_pieces_convert_with_piece_weight(home):
    d = FakeDiary(); logger(home, d).log_text('добавь три яйца на завтрак')
    assert d.creates()[0]['number_of_units'] == '150' and d.creates()[0]['meal'] == 'breakfast'


def test_remaining_reply(home):
    d = FakeDiary([{'food_entry_id': '1', 'food_id': '9', 'number_of_units': '1', 'calories': '3600', 'protein': '120.5'}])
    assert logger(home, d).remaining() == ('Сегодня 120 грамм белка и 3600 килокалорий. '
                                           'До нормы белка 30 грамм, норма калорий выполнена, сэр.')


def test_alias_cache_rejects_close_ties(tmp_path):
    c = AliasCache(tmp_path / 'a.json')
    c.save([F.alias_from_dict({'names': ['сыр'], 'food_id': '1', 'serving_id': '1'}),
            F.alias_from_dict({'names': ['сырок'], 'food_id': '2', 'serving_id': '2'})])
    assert c.find('сыр').food_id == '1' and c.find('колбаса') is None


def harness(home, cfg, diary):
    c = Q.Controller(home, FakeBackend(), food_call=diary); said = []; posted = []
    def run(text):
        c.execute(Q.match(text, cfg), text, cfg, lambda t, s, **k: said.append(t) or True, lambda t, **k: posted.append(k), test=True)
    return run, said, posted


def test_controller_local_first_then_server(home, cfg):
    cfg.update(food_local_enabled=True, nutrition_targets={'protein_g': 150})
    d = FakeDiary(day=None); run, said, posted = harness(home, cfg, d)
    run('добавь 200 грамм творога')
    assert said[-1].startswith('Записал: творог') and not posted
    run('добавь 200 грамм банана')
    assert posted[-1]['kind'] == 'food_log' and len(d.creates()) == 1
    run('сколько осталось до нормы белка')
    assert said[-1] == 'Сегодня 25 грамм белка и 206 килокалорий. До нормы белка 125 грамм, сэр.'


def test_disabled_by_default_goes_to_server(home, cfg):
    run, said, posted = harness(home, cfg, pytest.fail)
    run('добавь двести грамм творога')
    assert posted[-1]['kind'] == 'food_log'
    a = Q.match('сколько осталось до нормы белка', cfg)
    assert a is None or a['cmd'] != 'nutrition_left'


def test_food_alias_script_uses_metric_serving(tmp_path):
    import argparse, importlib.util
    spec = importlib.util.spec_from_file_location('food_alias', str(Path(__file__).resolve().parent.parent / 'scripts' / 'food_alias.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    food = {'food': {'food_name': 'Synthetic', 'servings': {'serving': [
        {'serving_id': '5', 'measurement_description': 'cup', 'number_of_units': '1', 'calories': '200', 'protein': '20'},
        {'serving_id': '6', 'measurement_description': 'g', 'number_of_units': '100', 'calories': '103', 'protein': '12.5'}]}}}
    calls = []
    alias = m.add(tmp_path, argparse.Namespace(food_id='7', names='творог, творога', label='', unit='g', piece_g=0),
                  lambda method, p: calls.append(method) or food)
    assert calls == ['food.get'] and alias.serving_id == '6' and alias.protein_per_unit == 0.125 and alias.label == 'Творог'
    assert AliasCache(tmp_path / 'cache' / 'food_aliases.json').find('творога').food_id == '7'
