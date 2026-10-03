import numpy as np

from backend.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, embed_query, embed_texts, get_model


def test_embed_texts_shape_and_norm():
    vectors = embed_texts(["Dravet syndrome", "SCN1A sodium channel", "banana bread"], batch_size=2)
    assert EMBEDDING_MODEL == "BAAI/bge-small-en-v1.5"
    assert vectors.shape == (3, EMBEDDING_DIM) and vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)
    assert embed_texts([]).shape == (0, EMBEDDING_DIM)


def test_query_is_closer_to_related_text():
    docs = embed_texts(["Dravet syndrome is caused by SCN1A variants", "Recipe for banana bread"])
    q = np.array(embed_query("epilepsy sodium channel gene"), dtype=np.float32)
    assert len(q) == EMBEDDING_DIM
    scores = docs @ q
    assert scores[0] > scores[1]


def test_model_is_singleton():
    assert get_model() is get_model()
