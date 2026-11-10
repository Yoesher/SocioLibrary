import pytest

from sociolit.indexing import import_snapshot
from sociolit.literature import excerpts, recommend_metadata, recommend_semantic
from sociolit.semantic import build_vectors
from sociolit.store import Store
from sociolit.zotero import Snapshot


@pytest.fixture
def library(tmp_path):
    store = Store(tmp_path)
    items = [{"key": "A", "title": "家庭照料与女性就业", "abstract": "生育后的照料约束与就业退出", "tags": ["生育"], "doi": "10.1/a"},
             {"key": "B", "title": "女性就业与家庭照料", "abstract": "育儿照料和就业选择", "tags": ["生育"]},
             {"key": "C", "title": "清代赋役制度", "abstract": "历史档案与财政", "tags": ["历史"]},
             {"key": "D", "title": "同一篇文献的另一来源", "abstract": "家庭照料与女性就业", "doi": "10.1/a"}]
    import_snapshot(store, Snapshot("synthetic", items, [], True))
    return store


def test_keyword_recommendations_exclude_self_and_duplicate_work_and_explain(library):
    result = recommend_metadata(library, "synthetic:A")
    assert [row["id"] for row in result["results"]] == ["synthetic:B"]
    assert result["mode"] == "metadata" and "本机" in result["scope"]
    assert "共同" in " ".join(result["results"][0]["reasons"])
    assert library.stats()["vectors"] == 0


def test_sparse_metadata_does_not_produce_arbitrary_recommendations(library):
    result = recommend_metadata(library, "synthetic:C")
    assert result["results"] == []
    with pytest.raises(ValueError):
        recommend_metadata(library, "missing")


class Embedder:
    key = "synthetic-model"

    def encode(self, texts, query=False):
        return [[1., 0.] if (query or "照料" in text) else [0., 1.] for text in texts]


def test_semantic_recommendations_use_existing_scope_and_never_silently_fallback(library):
    embedder = Embedder()
    with pytest.raises(RuntimeError, match="尚未完成"):
        recommend_semantic(library, "synthetic:A", embedder)
    scope = ["synthetic:A", "synthetic:B", "synthetic:C"]
    build_vectors(library, embedder, item_ids=scope)
    result = recommend_semantic(library, "synthetic:A", embedder, item_ids=scope, scope="核心文献")
    assert [row["id"] for row in result["results"]] == ["synthetic:B"]
    assert result["scope"] == "核心文献" and result["mode"] == "semantic"
    assert "原文" not in result["results"][0]  # No PDF or file path is returned.


def test_seed_many_chunks_cannot_fill_semantic_candidates(library):
    with library.connect() as db:
        for ordinal in range(240):
            library.add_chunk(db, item_id="synthetic:A", kind="metadata", text="家庭照料", ordinal=ordinal+1)
    build_vectors(library, Embedder())
    result = recommend_semantic(library, "synthetic:A", Embedder())
    assert [row["id"] for row in result["results"]] == ["synthetic:B"]


def test_excerpts_have_current_fingerprints_and_restrict_search_to_one_paper(library):
    result = excerpts(library, "synthetic:B", "照料")
    assert result["chunks"] and all(row["item_id"] == "synthetic:B" for row in result["chunks"])
    assert all(len(row["source_digest"]) == 64 for row in result["chunks"])
    assert excerpts(library, "synthetic:B", "清代")["chunks"] == []


def test_tag_only_candidates_work_with_old_metadata_fts_and_single_character_tags(tmp_path):
    store = Store(tmp_path)
    import_snapshot(store, Snapshot("synthetic", [{"key": "A", "title": "Fertility preferences", "tags": ["史"]},
        {"key": "B", "title": "Tax archives", "tags": ["史"]}], [], True))
    result = recommend_metadata(store, "synthetic:A")
    assert [row["id"] for row in result["results"]] == ["synthetic:B"]
    assert "标签" in " ".join(result["results"][0]["reasons"])
