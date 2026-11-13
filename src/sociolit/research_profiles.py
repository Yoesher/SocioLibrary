"""Small, local research lenses. A lens never filters or migrates the library."""
import json

from filelock import FileLock

from .upgrades import _write

METHOD_GUIDANCE = (
    '先辨明材料属于定量、质性、混合、历史、规范或理论研究，再采用适合的证据标准。'
    '区分相关关系与因果识别，不能把回归系数直接解释为因果效应。'
    '质性研究关注选案、材料生成与解释过程；历史研究区分史料形成时间、事件时间和作者解释。'
    '规范与理论研究关注概念、前提和论证，不强行要求样本、假设检验或统计结果。'
    '材料没有说明的内容写“材料未提供”；研究缺口仅是所选材料的待核查线索，不能宣称整个领域无人研究。'
)

# Original navigation examples, not a disciplinary ontology or validated findings.
PROFILES = [
    dict(id='general', name='社会科学通用', focus='跨学科比较概念、问题、材料、论证和适用范围，保留不同研究传统。',
         examples=['教育不平等与社会流动', '数字平台与公共治理', '政策评估与因果推断'], journal=None),
    dict(id='education', name='教育研究', focus='关注学习过程、教育公平、教育政策与制度条件，区分教学效果与研究设计。',
         examples=['教育公平与学习机会', '教师专业发展', '形成性评价与学习成效'],
         journal=dict(name='Review of Educational Research', issn='0034-6543')),
    dict(id='economics', name='经济与劳动研究', focus='关注激励、资源配置、劳动市场与识别策略，区分理论假设、估计结果和福利判断。',
         examples=['收入不平等与劳动市场', '人力资本与就业', '双重差分与政策评估'],
         journal=dict(name='American Economic Review', issn='0002-8282')),
    dict(id='policy', name='政治与公共管理', focus='关注制度、政策过程、执行条件和公共价值，区分政策文本、实施过程与实际效果。',
         examples=['公共治理与政策执行', '政策扩散', '官僚组织与行政负担'],
         journal=dict(name='Journal of Public Administration Research and Theory', issn='1053-1858')),
    dict(id='psychology', name='心理与行为研究', focus='关注构念、测量、研究设计与效应解释，不依据片段作个体诊断或治疗建议。',
         examples=['自我效能与学习动机', '认知偏差与决策', '社会认同与群际关系'],
         journal=dict(name='Psychological Science', issn='0956-7976')),
    dict(id='sociology', name='社会学与人口研究', focus='关注社会关系、分层、家庭、人口过程与历史制度条件，区分机制解释与经验发现。',
         examples=['生育意愿与托育支持', '社会分层与社会流动', '平台劳动与劳动过程'],
         journal=dict(name='American Sociological Review', issn='0003-1224')),
    dict(id='communication', name='新闻与传播研究', focus='关注媒介、传播过程、受众与公共讨论，区分文本表征、使用行为和传播效果。',
         examples=['媒介素养与错误信息', '议程设置与框架分析', '算法推荐与选择性接触'],
         journal=dict(name='Journal of Communication', issn='0021-9916')),
    dict(id='geography', name='人文地理与区域研究', focus='关注空间尺度、地方情境、迁移与区域发展，区分空间相关和因果机制。',
         examples=['空间不平等与公共服务', '地方依恋与人口迁移', '城市更新与空间正义'],
         journal=dict(name='Progress in Human Geography', issn='0309-1325')),
    dict(id='history', name='历史与历史社会科学', focus='关注史料来源、时间顺序、历史情境与解释链条，不把后见之明当作行动者动机。',
         examples=['历史制度主义与路径依赖', '档案研究与过程追踪', '集体记忆与口述史'],
         journal=dict(name='History and Theory', issn='0018-2656')),
    dict(id='anthropology', name='人类学与文化研究', focus='关注田野关系、地方性知识、文化实践与研究者位置，区分当事人表述和研究者解释。',
         examples=['民族志与地方性知识', '亲属关系与文化实践', '参与观察与反身性'],
         journal=dict(name='American Anthropologist', issn='0002-7294')),
    dict(id='law', name='法学与社会法研究', focus='关注法规范、法解释、制度实践与社会经验，区分现行规范、实证发现和价值主张。',
         examples=['法律意识与司法可及性', '程序正义与制度信任', '法律多元主义'],
         journal=dict(name='Law & Society Review', issn='0023-9216')),
]
BY_ID = {row['id']: row for row in PROFILES}


def _settings(directory):
    path = directory / 'preferences.json'
    if not path.exists():
        return {}
    if path.stat().st_size > 1_000_000:
        raise ValueError('本机设置文件过大，未覆盖。')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('本机设置无法读取，原文件已保留。') from exc
    if not isinstance(value, dict):
        raise ValueError('本机设置格式无效，原文件已保留。')
    return value


def current(directory):
    identity = _settings(directory).get('research_profile', 'general')
    return BY_ID.get(identity, BY_ID['general']) if isinstance(identity, str) else BY_ID['general']


def catalog(directory):
    return {'current': current(directory)['id'], 'profiles': PROFILES,
            'message': '研究领域用于示例与阅读视角；全部文献仍可检索，原有语义试点和期刊订阅保持原设置。'}


def save(directory, identity):
    if identity not in BY_ID:
        raise ValueError('请选择列表中的研究领域。')
    with FileLock(str(directory / 'preferences.lock'), timeout=0.5):
        settings = _settings(directory)
        settings['research_profile'] = identity
        _write(directory / 'preferences.json', settings)
    return catalog(directory)


def system_prompt(base, profile):
    return base + '\n研究视角：' + profile['name'] + '。' + profile['focus'] + METHOD_GUIDANCE
