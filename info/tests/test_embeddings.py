"""Turning text into vectors, and the two ways that goes wrong quietly.

The first is dimension drift. A vector is only comparable to vectors from the
same model, so a provider that returns a different width - because the model
changed, or because a response was malformed - makes every row already stored
meaningless. Nothing raises: the search still returns rows, they are just the
wrong rows. So the width is checked on every response and a mismatch is an
exception, not a stored value.

The second is a half-written batch. Embedding runs over every chunk of every
document, on somebody's free tier, so rate limits and timeouts are the normal
case rather than the exception. A caller has to get every vector it asked for
or none, because a partial result would be indistinguishable from a complete
one at the point where the rows are written.
"""
from unittest import mock

from django.test import SimpleTestCase, override_settings

from info.embeddings import (
    GEMINI_DIMENSIONS,
    Embedder,
    EmbeddingError,
    FakeEmbedder,
    GeminiEmbedder,
    cosine,
    get_embedder,
)


class FakeEmbedderTests(SimpleTestCase):
    def setUp(self):
        self.embedder = FakeEmbedder()

    def test_the_same_text_always_gives_the_same_vector(self):
        # Without this, re-ingesting an unchanged document would store a
        # different vector for identical text and the two would not match.
        self.assertEqual(self.embedder.embed_one('binary trees'),
                         self.embedder.embed_one('binary trees'))

    def test_different_text_gives_a_different_vector(self):
        self.assertNotEqual(self.embedder.embed_one('binary trees'),
                            self.embedder.embed_one('linked lists'))

    def test_it_returns_one_vector_per_text_in_order(self):
        vectors = self.embedder.embed(['one', 'two', 'three'])

        self.assertEqual(len(vectors), 3)
        self.assertEqual(vectors[0], self.embedder.embed_one('one'))
        self.assertEqual(vectors[2], self.embedder.embed_one('three'))

    def test_the_vectors_are_the_declared_width(self):
        self.assertEqual(len(self.embedder.embed_one('anything')),
                         GEMINI_DIMENSIONS)

    def test_the_vectors_are_unit_length(self):
        vector = self.embedder.embed_one('anything')

        self.assertAlmostEqual(sum(v * v for v in vector), 1.0, places=6)

    def test_the_components_are_not_all_positive(self):
        # A raw hash is entirely positive, which makes every pair of vectors
        # look similar and hides ordering bugs in the retriever.
        vector = self.embedder.embed_one('anything')

        self.assertTrue(any(v < 0 for v in vector))
        self.assertTrue(any(v > 0 for v in vector))

    def test_embedding_nothing_returns_nothing(self):
        self.assertEqual(self.embedder.embed([]), [])

    def test_an_empty_string_still_gets_a_vector(self):
        # A chunk should never be empty, but if one is, failing here would
        # take down an ingest for a blank line.
        self.assertEqual(len(self.embedder.embed_one('')), GEMINI_DIMENSIONS)


class DimensionGuardTests(SimpleTestCase):
    """The check that stops a wrong-width vector reaching the database."""

    def test_a_wrong_width_vector_is_refused(self):
        class Wrong(Embedder):
            name, dimensions = 'wrong', 4

            def embed(self, texts):
                return self._check([[0.1, 0.2]], len(texts))

        with self.assertRaises(EmbeddingError) as caught:
            Wrong().embed(['one'])

        self.assertIn('not comparable', str(caught.exception))

    def test_a_short_response_is_refused(self):
        class Short(Embedder):
            name, dimensions = 'short', 2

            def embed(self, texts):
                return self._check([[0.1, 0.2]], len(texts))

        with self.assertRaises(EmbeddingError) as caught:
            Short().embed(['one', 'two'])

        self.assertIn('1 vectors for 2 texts', str(caught.exception))


class GeminiTests(SimpleTestCase):
    def setUp(self):
        self.embedder = GeminiEmbedder('test-key')

    def reply(self, count, width=GEMINI_DIMENSIONS):
        return {'embeddings': [{'values': [0.01] * width} for _ in range(count)]}

    def test_a_key_is_required(self):
        with self.assertRaises(EmbeddingError):
            GeminiEmbedder('')

    def test_it_asks_for_document_embeddings_not_query_ones(self):
        # Gemini embeds a stored passage and a search differently. Using the
        # wrong task type costs real accuracy and reports nothing.
        with mock.patch.object(GeminiEmbedder, '_post',
                               return_value=self.reply(1)) as post:
            self.embedder.embed(['binary trees'])

        payload = post.call_args[0][0]
        self.assertEqual(payload['requests'][0]['taskType'], 'RETRIEVAL_DOCUMENT')

    def test_long_input_is_split_into_several_batches(self):
        with mock.patch.object(GeminiEmbedder, '_post') as post:
            post.side_effect = lambda payload: self.reply(
                len(payload['requests']))
            vectors = self.embedder.embed(['text'] * 150)

        self.assertEqual(len(vectors), 150)
        self.assertGreater(post.call_count, 1)

    def test_a_provider_returning_the_wrong_width_is_refused(self):
        # The failure this whole module exists to prevent.
        with mock.patch.object(GeminiEmbedder, '_post',
                               return_value=self.reply(1, width=1536)):
            with self.assertRaises(EmbeddingError) as caught:
                self.embedder.embed(['one'])

        self.assertIn('not comparable', str(caught.exception))

    def test_an_unexpected_response_shape_is_an_error_not_a_crash(self):
        with mock.patch.object(GeminiEmbedder, '_post', return_value={'oops': 1}):
            with self.assertRaises(EmbeddingError):
                self.embedder.embed(['one'])

    def test_embedding_nothing_makes_no_call(self):
        with mock.patch.object(GeminiEmbedder, '_post') as post:
            self.assertEqual(self.embedder.embed([]), [])

        post.assert_not_called()


class ConfigurationTests(SimpleTestCase):
    @override_settings(GEMINI_API_KEY='')
    def test_no_key_falls_back_to_the_fake(self):
        # A checkout with no keys still runs, the same rule storage and email
        # already follow here.
        self.assertIsInstance(get_embedder(), FakeEmbedder)

    @override_settings(GEMINI_API_KEY='a-key')
    def test_a_key_selects_gemini(self):
        self.assertIsInstance(get_embedder(), GeminiEmbedder)

    @override_settings(GEMINI_API_KEY='a-key')
    def test_both_providers_agree_on_the_width(self):
        # They have to: a store filled by one and queried through the other
        # would compare vectors that are not comparable.
        self.assertEqual(get_embedder().dimensions, FakeEmbedder().dimensions)


class CosineTests(SimpleTestCase):
    def test_a_vector_is_identical_to_itself(self):
        self.assertAlmostEqual(cosine([1, 0, 0], [1, 0, 0]), 1.0)

    def test_opposite_vectors_are_minus_one(self):
        self.assertAlmostEqual(cosine([1, 0], [-1, 0]), -1.0)

    def test_perpendicular_vectors_are_zero(self):
        self.assertAlmostEqual(cosine([1, 0], [0, 1]), 0.0)

    def test_a_zero_vector_is_zero_rather_than_a_division_error(self):
        self.assertEqual(cosine([0, 0], [1, 0]), 0.0)

    def test_vectors_of_different_widths_are_refused(self):
        with self.assertRaises(ValueError):
            cosine([1, 0], [1, 0, 0])
