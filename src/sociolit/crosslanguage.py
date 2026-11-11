"""Offline terminology expansion plus explicitly bounded multilingual retrieval."""
import itertools
import re

from .retrieval import reciprocal_rank_fusion

# Original, small sociology glossary; it is query expansion, not an LLM translation.
CONCEPTS = [
    (['生育支持政策', '生育支持'], ['fertility support', 'family policy', 'parental leave']),
    (['生育意愿', '生育计划'], ['fertility intentions', 'childbearing intentions']),
    (['母职惩罚', '母职工资惩罚'], ['motherhood penalty', 'motherhood wage penalty']),
    (['父职溢价'], ['fatherhood premium']),
    (['生育', '生殖'], ['fertility', 'childbearing', 'reproduction']),
    (['女性就业', '女性劳动参与'], ['female employment', 'women employment']),
    (['性别平等'], ['gender equality']), (['性别不平等'], ['gender inequality']),
    (['辅助生殖'], ['assisted reproduction']), (['不孕'], ['infertility']),
    (['托育', '儿童照料'], ['childcare', 'child care']),
    (['育儿假', '产假'], ['parental leave', 'maternity leave']),
    (['家庭支持'], ['family support']), (['家庭分工'], ['division of household labor']),
    (['工作家庭冲突', '工作与家庭冲突', '工作—家庭冲突'], ['work family conflict']),
    (['社会再生产'], ['social reproduction']), (['生命历程'], ['life course']),
    (['社会资本'], ['social capital']), (['社会网络'], ['social networks']),
    (['社会分层'], ['social stratification']), (['社会流动'], ['social mobility']),
    (['阶级'], ['social class']), (['身份认同'], ['identity', 'identification']),
    (['劳动力市场'], ['labor market', 'labour market']),
    (['不稳定就业'], ['precarious employment', 'precarious work']),
    (['劳动过程'], ['labor process', 'labour process']),
    (['平台劳动'], ['platform labor', 'gig work']),
    (['情感劳动'], ['emotional labor', 'emotional labour']),
    (['照料劳动'], ['care work', 'care labor']), (['社会政策'], ['social policy']),
    (['人口转变'], ['demographic transition']), (['人口老龄化'], ['population aging']),
    (['婚姻'], ['marriage']), (['离婚'], ['divorce']), (['家庭'], ['family']),
    (['教育'], ['education']), (['就业'], ['employment']),
    (['女性'], ['women', 'female']), (['男性'], ['men', 'male']),
    (['迁移', '移民'], ['migration']), (['城乡'], ['rural urban']),
]


def expand(query):
    lowered = query.casefold()
    matches = []
    for chinese, english in CONCEPTS:
        for term in [*chinese, *english]:
            pattern = re.escape(term) if re.search(r'[\u3400-\u9fff]', term) else r'\b' + re.escape(term) + r'\b'
            for match in re.finditer(pattern, lowered):
                target = english if term in chinese else chinese
                matches.append((match.start(), match.end(), target))
    selected, covered = [], set()
    for start, end, target in sorted(matches, key=lambda m: (-(m[1]-m[0]), m[0])):
        positions = set(range(start, end))
        if positions & covered:
            continue
        selected.append((start, target[:3]))
        covered |= positions
        if len(selected) == 4:
            break
    groups = [target for _, target in sorted(selected)]
    variants = []
    for values in itertools.islice(itertools.product(*groups), 8) if groups else []:
        text = ' '.join(values)[:200]
        if text.casefold() != lowered and text not in variants:
            variants.append(text)
    return variants


def search(store, query, selected, semantic):
    variants = expand(query)
    rankings = [store.search(query, limit=100, item_ids=selected)]
    rankings.extend(store.search(value, limit=100, item_ids=selected) for value in variants)
    info = {'expanded_queries': variants, 'semantic': False, 'semantic_scope': '',
            'message': '全库字词检索与离线中英术语扩展；术语表不能翻译任意句子。'}
    try:
        rows, scope = semantic()
        rankings.append(rows)
        info.update(semantic=True, semantic_scope=scope,
                    message='已结合本机多语言语义检索。语义仅覆盖显示的索引范围；字词与术语检索覆盖全部已导入资料。')
    except (RuntimeError, ValueError) as exc:
        info['message'] += ' 本次语义未参与：' + str(exc)[:240]
    fused = reciprocal_rank_fusion(*rankings)
    if re.search(r'[\u3400-\u9fff]', query) and (variants or info['semantic']):
        translated_ids = {row['id'] for ranking in rankings[1:1+len(variants)] for row in ranking}
        if info['semantic']:
            translated_ids.update(row['id'] for row in rankings[-1])
        foreign = [row for row in fused if row['id'] in translated_ids
                   and len(re.findall(r'[a-zA-Z]', row.get('title', ''))) >= 10
                   and not re.search(r'[\u3400-\u9fff]', row.get('title', ''))]
        # Make cross-language candidates visible without comparing incompatible scores.
        pending, mixed, seen = list(fused), [], set()
        while pending or foreign:
            for pool, amount in ((pending, 2), (foreign, 1)):
                count = 0
                while pool and count < amount:
                    row = pool.pop(0)
                    if row['id'] not in seen:
                        seen.add(row['id'])
                        mixed.append(row)
                        count += 1
        fused = mixed
        info['message'] += ' 英文题名候选与其他候选交错展示，排序不代表论文质量。'
    return fused, info
