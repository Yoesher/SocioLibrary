"""Offline inference regression using a tiny random BERT, never a real corpus."""
import json
import math
import os
from pathlib import Path


def verify(directory):
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
    os.environ['TQDM_DISABLE'] = '1'
    import torch
    from sentence_transformers import SentenceTransformer, models
    from transformers import BertConfig, BertModel, BertTokenizer
    from transformers.utils import logging as transformer_logging

    from .semantic import MODEL_ID, LocalEmbedder, search_vectors
    from .store import Store

    torch.set_num_threads(2)
    transformer_logging.disable_progress_bar()
    torch.manual_seed(7)
    root = Path(directory) / 'synthetic-inference'
    root.mkdir()
    raw = root / 'raw'
    words = ['[PAD]', '[UNK]', '[CLS]', '[SEP]', '[MASK]', 'query', 'passage', ':',
             'synthetic', 'family', 'work', 'reading', 'study', 'paper']
    tokenizer = BertTokenizer(vocab={word: i for i, word in enumerate(words)})
    tokenizer.save_pretrained(raw)
    model = BertModel(BertConfig(vocab_size=len(words), hidden_size=16, num_hidden_layers=1,
                                num_attention_heads=2, intermediate_size=32, max_position_embeddings=64))
    model.save_pretrained(raw)
    transformer = models.Transformer(str(raw), max_seq_length=32,
                                     model_args={'local_files_only': True}, tokenizer_args={'local_files_only': True})
    sentence = SentenceTransformer(modules=[transformer, models.Pooling(16), models.Normalize()], device='cpu')
    saved = root / 'model'
    sentence.save_pretrained(saved, create_model_card=False)
    (saved / 'sociolit-model.json').write_text(json.dumps({'model': MODEL_ID, 'synthetic': True}), encoding='utf-8')
    embedder = LocalEmbedder(saved)
    texts = ['synthetic family study', 'synthetic work paper']
    vectors = embedder.encode(texts)
    assert len(vectors) == 2 and all(len(vector) == 16 for vector in vectors)
    assert all(all(math.isfinite(x) for x in vector) and abs(sum(x*x for x in vector) - 1) < 1e-5 for vector in vectors)
    store = Store(root / 'search')
    with store.connect() as db:
        for i, (text, vector) in enumerate(zip(texts, vectors, strict=True)):
            item = 'synthetic:' + str(i)
            db.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)', (item, 'synthetic', str(i), text, 'journalArticle', '{}', text))
            chunk = store.add_chunk(db, item_id=item, text=text, kind='metadata')
            db.execute('INSERT INTO vectors VALUES(?,?,?)', (chunk, embedder.key, json.dumps(vector)))
    results = search_vectors(store, embedder, 'family work', limit=2)
    assert len(results) == 2 and all(math.isfinite(row['score']) for row in results)
    assert results[0]['score'] >= results[1]['score']
    return {'semantic_roundtrip': True, 'embedding_dimensions': 16}
