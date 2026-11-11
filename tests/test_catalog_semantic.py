import json

import pytest

from sociolit import catalog_semantic, graph
from sociolit.indexing import import_snapshot
from sociolit.store import Store
from sociolit.zotero import Snapshot


class Model:
    key = 'synthetic-model'

    def __init__(self):
        self.calls = []

    def encode(self, texts, query=False):
        self.calls.append((texts, query))
        return [[1., .2] if 'fertility' in text.lower() or '生育' in text else [.2, 1.] for text in texts]


@pytest.fixture
def catalog(tmp_path):
    store = Store(tmp_path)
    items = [{'key':'A','title':'Fertility intentions and employment uncertainty','abstract':'Fertility plans','tags':[]},
             {'key':'B','title':'Social networks and employment uncertainty','abstract':'Network evidence','tags':[]}]
    import_snapshot(store,Snapshot('synthetic',items,[],True))
    catalog_semantic.initialize(store)
    return store


def test_catalog_one_vector_per_item_incremental_and_independent_from_pdf_scope(catalog):
    model=Model()
    result=catalog_semantic.build(catalog,model)
    assert result['indexed']==2 and result['items']==2
    assert catalog.stats()['vectors']==0
    assert catalog_semantic.status(catalog,model.key)=={'done':2,'total':2,'ready':True}
    assert catalog_semantic.build(catalog,model)['indexed']==0
    assert len(model.calls)==1
    rows=catalog_semantic.search(catalog,model,'生育问题')
    assert rows[0]['item_id']=='synthetic:A' and rows[0]['kind']=='metadata'
    assert rows[0]['retrieval_kind']=='catalog_semantic' and rows[0]['page'] is None
    assert catalog_semantic.search(catalog,model,'生育问题',item_ids=['synthetic:B'])[0]['item_id']=='synthetic:B'


def test_catalog_content_changes_invalidate_but_raw_timestamp_does_not(catalog):
    model=Model()
    catalog_semantic.build(catalog,model)
    with catalog.connect() as db:
        metadata=json.loads(db.execute("SELECT metadata FROM items WHERE id='synthetic:A'").fetchone()[0])
        metadata['raw']={'dateModified':'later'}
        db.execute("UPDATE items SET metadata=? WHERE id='synthetic:A'",(json.dumps(metadata),))
    assert catalog_semantic.status(catalog,model.key)['ready']
    with catalog.connect() as db:
        metadata['abstract']='Changed evidence'
        db.execute("UPDATE items SET metadata=? WHERE id='synthetic:A'",(json.dumps(metadata),))
    assert catalog_semantic.status(catalog,model.key)['done']==1
    with pytest.raises(RuntimeError,match='尚未齐备'):
        catalog_semantic.search(catalog,model,'fertility')
    assert catalog_semantic.build(catalog,model)['indexed']==1


def test_catalog_deletion_and_incomplete_import(catalog):
    model=Model()
    catalog_semantic.build(catalog,model)
    with catalog.connect() as db:
        db.execute("DELETE FROM items WHERE id='synthetic:B'")
        assert db.execute('SELECT count(*) FROM catalog_vectors').fetchone()[0]==1
    catalog.set_state('import_incomplete',True)
    with pytest.raises(RuntimeError):
        catalog_semantic.build(catalog,model)
    with pytest.raises(RuntimeError):
        catalog_semantic.search(catalog,model,'fertility')


@pytest.mark.parametrize('vector', [[float('nan')], [], [float('inf')], [0., 0.]])
def test_catalog_refuses_invalid_embeddings(catalog,vector):
    model=Model()
    model.encode=lambda texts,**_: [vector for _ in texts]
    with pytest.raises(ValueError):
        catalog_semantic.build(catalog,model)
    assert not catalog_semantic.status(catalog,model.key)['ready']


def test_catalog_refuses_wrong_dimension(catalog):
    model=Model()
    catalog_semantic.build(catalog,model)
    with catalog.connect() as db:
        db.execute("UPDATE catalog_vectors SET embedding='[1]' WHERE item_id='synthetic:A'")
    with pytest.raises(RuntimeError,match='维度'):
        catalog_semantic.search(catalog,model,'fertility')


def test_title_clues_make_untagged_papers_explainable_not_citations(catalog):
    graph.initialize(catalog)
    with catalog.connect() as db:
        db.execute('CREATE TABLE literature_comparisons(id TEXT,title TEXT,body_json TEXT,archived INTEGER,updated TEXT)')
    value=graph.build(catalog)
    assert any(edge['origin']=='title' and 'employment' in edge['label'] for edge in value['edges'])
    assert not any(edge.get('kind')=='cites' for edge in value['edges'])


def test_graph_reuses_catalog_vectors_without_loading_or_requesting_model(catalog):
    with catalog.connect() as db:
        meta={'authors':[],'abstract':'fertility evidence','tags':[]}
        db.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',('synthetic:C','synthetic','C','Household choices over time','article',json.dumps(meta),'test'))
        catalog.add_chunk(db,item_id='synthetic:C',kind='metadata',text='Household choices over time')
    model=Model()
    catalog_semantic.build(catalog,model)
    calls=len(model.calls)
    neighbors=catalog_semantic.graph_candidates(catalog,seed='synthetic:A')
    assert any(right=='synthetic:C' for left,right,score in neighbors)
    assert len(model.calls)==calls
    graph.initialize(catalog)
    with catalog.connect() as db:
        db.execute('CREATE TABLE literature_comparisons(id TEXT,title TEXT,body_json TEXT,archived INTEGER,updated TEXT)')
    network=graph.build(catalog,seed='synthetic:A')
    assert any(node['id']=='synthetic:C' for node in network['nodes'])
    assert any(edge['origin']=='semantic' for edge in network['edges'])
    assert len(model.calls)==calls
    assert len(graph.build(catalog,seed='synthetic:A',include_auto=False)['nodes'])==1
