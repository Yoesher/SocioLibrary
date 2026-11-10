"""Local semantic integration tested with deterministic encoders, no model download."""

import json
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sociolit.indexing import import_snapshot
from sociolit.semantic import MODEL_ID, LocalEmbedder, build_vectors, search_vectors
from sociolit.store import Store
from sociolit.zotero import Snapshot


class FakeEncoder:
    def __init__(self, key="fake-v1"):
        self.key = key
        self.calls = []

    def encode(self, texts, *, query=False):
        self.calls.append((list(texts), query))
        return [[1.0, 0.0] if "care" in text.lower() else [0.0, 1.0] for text in texts]


def documents():
    return [{"key": "CARE1234", "title": "Care responsibilities", "authors": [], "tags": [], "abstract": ""},
            {"key": "LABO1234", "title": "Labor institutions", "authors": [], "tags": [], "abstract": ""}]


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.store = Store(self.directory / "library")
        import_snapshot(self.store, Snapshot("zotero:test", documents(), [], True))
        self.encoder = FakeEncoder()

    def tearDown(self):
        self.temp.cleanup()

    def test_semantic_ranking_and_query_mode(self):
        self.assertEqual(build_vectors(self.store, self.encoder, batch_size=1), 2)
        results = search_vectors(self.store, self.encoder, "care obligations")
        self.assertEqual(results[0]["item_key"], "CARE1234")
        self.assertEqual(results[0]["score"], 1.0)
        self.assertEqual(results[1]["score"], 0.0)
        self.assertTrue(self.encoder.calls[-1][1])
        self.assertTrue(all(not call[1] for call in self.encoder.calls[:-1]))
        self.assertNotIn("embedding", results[0])

    def test_rebuild_is_incremental(self):
        self.assertEqual(build_vectors(self.store, self.encoder), 2)
        calls = len(self.encoder.calls)
        self.assertEqual(build_vectors(self.store, self.encoder), 0)
        self.assertEqual(len(self.encoder.calls), calls)

    def test_unbuilt_or_different_model_is_not_silently_lexical(self):
        with self.assertRaisesRegex(RuntimeError, "尚未完成"):
            search_vectors(self.store, self.encoder, "care")
        build_vectors(self.store, self.encoder)
        with self.assertRaisesRegex(RuntimeError, "尚未完成"):
            search_vectors(self.store, FakeEncoder("fake-v2"), "care")
        self.assertEqual(build_vectors(self.store, FakeEncoder("fake-v2")), 2)
        self.assertEqual(self.store.stats()["vectors"], 4)

    def test_item_change_invalidates_only_affected_vectors(self):
        build_vectors(self.store, self.encoder)
        records = documents()
        records[0]["title"] = "Care and family employment"
        import_snapshot(self.store, Snapshot("zotero:test", records, [], True))
        self.assertEqual(self.store.stats()["vectors"], 1)
        with self.assertRaisesRegex(RuntimeError, "尚未完成"):
            search_vectors(self.store, self.encoder, "care")
        self.assertEqual(build_vectors(self.store, self.encoder), 1)

    def test_deleted_item_cascades_vector(self):
        build_vectors(self.store, self.encoder)
        import_snapshot(self.store, Snapshot("zotero:test", documents()[:1], [], True))
        self.assertEqual(self.store.stats()["vectors"], 1)
        self.assertEqual(len(search_vectors(self.store, self.encoder, "care")), 1)

    def test_dimension_mismatch_fails_clearly(self):
        build_vectors(self.store, self.encoder)
        self.encoder.encode = lambda texts, query=False: [[1.0, 0.0, 0.0] for _ in texts]
        with self.assertRaisesRegex(RuntimeError, "dimension changed"):
            search_vectors(self.store, self.encoder, "care")

    def test_invalid_vectors_rollback_whole_build(self):
        self.encoder.encode = lambda texts, query=False: [[1.0, 0.0], [float("nan"), 0.0]]
        with self.assertRaisesRegex(ValueError, "Invalid embedding"):
            build_vectors(self.store, self.encoder)
        self.assertEqual(self.store.stats()["vectors"], 0)
        self.encoder.encode = lambda texts, query=False: []
        with self.assertRaisesRegex(ValueError, "batch size mismatch"):
            build_vectors(self.store, self.encoder)
        self.assertEqual(self.store.stats()["vectors"], 0)

    def test_interrupted_embedding_keeps_completed_batches_for_resume(self):
        self.encoder.encode = lambda texts, query=False: [[1.0, 0.0]] if "care" in texts[0].lower() else [[float("nan"), 0.0]]
        with self.assertRaisesRegex(ValueError, "Invalid embedding"):
            build_vectors(self.store, self.encoder, batch_size=1)
        self.assertEqual(self.store.stats()["vectors"], 1)
        with self.assertRaisesRegex(RuntimeError, "尚未完成"):
            search_vectors(self.store, self.encoder, "care")
        self.encoder = FakeEncoder()
        self.assertEqual(build_vectors(self.store, self.encoder, batch_size=1), 1)
        self.assertEqual(self.store.stats()["vectors"], 2)

    def test_missing_local_model_fails_before_network(self):
        with self.assertRaisesRegex(RuntimeError, "Local model missing"):
            LocalEmbedder(self.directory / "not-downloaded")

    def test_unversioned_or_wrong_model_rejected_before_loading(self):
        model_dir = self.directory / "unversioned-model"
        model_dir.mkdir()
        def unexpected_load(*args, **kwargs):
            self.fail("Invalid model directory must not reach the model loader")
        with patch.dict(sys.modules, {"sentence_transformers": SimpleNamespace(SentenceTransformer=unexpected_load)}):
            with self.assertRaisesRegex(RuntimeError, "versioned"):
                LocalEmbedder(model_dir)
            (model_dir / "sociolit-model.json").write_text(json.dumps({"model": "unknown-model"}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "E5 model"):
                LocalEmbedder(model_dir)

    def test_local_encoder_loads_only_local_files_and_e5_prefixes(self):
        model_dir = self.directory / "model"
        model_dir.mkdir()
        manifest = model_dir / "sociolit-model.json"
        manifest.write_text(json.dumps({"model": MODEL_ID, "revision": "revision-one"}), encoding="utf-8")
        constructor = []
        calls = []

        class FakeModel:
            def __init__(self, location, **kwargs):
                constructor.append((location, kwargs))

            def encode(self, texts, **kwargs):
                calls.append((texts, kwargs))
                return SimpleNamespace(tolist=lambda: [[1.0, 0.0] for _ in texts])

        with patch.dict(sys.modules, {"sentence_transformers": SimpleNamespace(SentenceTransformer=FakeModel)}):
            embedder = LocalEmbedder(model_dir)
            self.assertEqual(embedder.key, sha256(manifest.read_bytes()).hexdigest())
            self.assertEqual(embedder.encode(["劳动研究"]), [[1.0, 0.0]])
            embedder.encode(["care"], query=True)
            first_key = embedder.key
            manifest.write_text(json.dumps({"model": MODEL_ID, "revision": "revision-two"}), encoding="utf-8")
            self.assertNotEqual(LocalEmbedder(model_dir).key, first_key)
        self.assertEqual(constructor[0][1], {"local_files_only": True, "trust_remote_code": False})
        self.assertEqual(calls[0][0], ["passage: 劳动研究"])
        self.assertEqual(calls[1][0], ["query: care"])
        self.assertTrue(calls[0][1]["normalize_embeddings"])


if __name__ == "__main__":
    unittest.main()
