import pytest
from jarvis.core import routing as ROUTING
from jarvis.core import proactive as PROACTIVE
@pytest.mark.parametrize('text,action',[('статус по задачам','cache_field'),('что у меня на сегодня','cache_field'),('чё по планам','cache_field'),('сколько белка','cache_field'),('как дела','smalltalk'),('доброе утро','smalltalk'),('спасибо','smalltalk'),('который час','time'),('не беспокоить','proactive_dnd'),('можно беспокоить','proactive_dnd'),('повтори','quick2'),('помедленнее','quick2'),('громкость на тридцать','quick2'),('сделай скриншот','quick2'),('закрой активное окно','quick2'),('прочитай буфер','quick2'),('переведи буфер','quick2'),('таймер на пять минут','quick2'),('каждые сорок пять минут напоминай встать','quick2'),('запиши идею помощник','quick2'),('добавь задачу купить хлеб','quick2'),('отмени выключение','quick2'),('режим сна','quick2')])
def test_routes(app,cfg,text,action):
 al=ROUTING.match_alias(text,cfg);assert al and al['action']==action
@pytest.mark.parametrize('text',['какая завтра погода','объясни теорию относительности','добавь встречу завтра в календарь','почему надо закрыть окно','расскажи про статус HTTP'])
def test_free_not_local_action(app,cfg,text):
 al=ROUTING.match_alias(text,cfg)
 assert al is None or al.get('action') not in ('quick2','key','shutdown','proactive_dnd')
@pytest.mark.parametrize('text',['закрой окно','выключи через пять минут','не беспокоить','сделай скриншот','чё по планам','статус по задачам','сколько белка'])
def test_low_confidence_cannot_act(app,cfg,text):assert app.c.router.choose(text,.1,'',cfg)[1] is False
@pytest.mark.parametrize('text,confidence,echo,wanted',[('джарвис время',.99,'Сэр, слушаю.',True),('он сказал джарвис',.99,'Сэр.',False),('джарвис',.2,'Сэр.',False),('джарвис',1,'Я Джарвис.',False)])
def test_priority(app,cfg,text,confidence,echo,wanted):assert PROACTIVE.priority_candidate(text,confidence,echo,cfg)==wanted
