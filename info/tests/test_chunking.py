"""Splitting documents, which is where retrieval quality is decided.

Every failure in this module is silent downstream. A chunk cut mid-sentence
still embeds, still gets stored, still comes back from a search - it is simply
the wrong passage, and the only symptom is a chatbot that answers slightly
beside the question. There is no exception to catch and no log line to read.

So this file is mostly about boundaries and about the inputs that are not
prose: an empty file, a heading with nothing under it, a table with no
punctuation, a PDF text layer full of hard-wrapped lines.
"""
from django.test import SimpleTestCase

from info.chunking import (
    MIN_CHARS,
    Chunk,
    chunk_text,
    normalise,
)


def para(word, count):
    """A paragraph of a known length, made of one repeated word."""
    return ' '.join([word] * count)


class NormaliseTests(SimpleTestCase):
    def test_windows_line_endings_become_plain_ones(self):
        # The break is kept here only because the first line finished a
        # sentence; the point of the test is that no carriage return survives.
        self.assertEqual(normalise('one.\r\ntwo'), 'one.\ntwo')

    def test_runs_of_blank_lines_collapse_to_one(self):
        # A PDF text layer routinely leaves four or five. Left alone they are
        # just as good a paragraph break as two, but the splitter should only
        # have one shape to look for.
        self.assertEqual(normalise('one\n\n\n\n\ntwo'), 'one\n\ntwo')

    def test_runs_of_spaces_collapse(self):
        # The layout engine positioned words with spaces; that is not meaning,
        # and it moves the embedding.
        self.assertEqual(normalise('one     two'), 'one two')

    def test_a_hard_wrapped_line_is_joined_back_up(self):
        # The layout engine broke this, not the author. Keeping the break
        # would mean the same paragraph out of a PDF and out of a text file
        # chunk differently, and a re-ingest would not recognise itself.
        self.assertEqual(normalise('binary trees are\nhierarchical'),
                         'binary trees are hierarchical')

    def test_a_finished_sentence_keeps_its_break(self):
        self.assertEqual(normalise('One idea.\nAnother idea.'),
                         'One idea.\nAnother idea.')

    def test_a_list_keeps_the_breaks_the_author_put_in(self):
        # Joining these would run five syllabus units into one sentence.
        text = 'Units\n- Trees\n- Graphs\n2. Sorting\n(3) Hashing'

        self.assertEqual(normalise(text), text)

    def test_a_paragraph_break_is_never_joined_across(self):
        self.assertEqual(normalise('one\n\ntwo'), 'one\n\ntwo')

    def test_leading_and_trailing_whitespace_goes(self):
        self.assertEqual(normalise('   one   '), 'one')

    def test_an_empty_document_stays_empty(self):
        self.assertEqual(normalise('   \n\n  \r\n '), '')


class SplittingTests(SimpleTestCase):
    def test_an_empty_document_produces_no_chunks(self):
        # Not one empty chunk. An empty vector matches everything.
        self.assertEqual(chunk_text(''), [])

    def test_whitespace_only_produces_no_chunks(self):
        self.assertEqual(chunk_text('\n\n   \t  \n'), [])

    def test_a_short_document_is_one_chunk(self):
        chunks = chunk_text('Binary trees are hierarchical structures.')

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, 'Binary trees are hierarchical structures.')

    def test_paragraphs_are_kept_whole_when_they_fit(self):
        one, two = para('alpha', 40), para('beta', 40)

        chunks = chunk_text('%s\n\n%s' % (one, two), overlap=0)

        self.assertEqual([c.text for c in chunks], [one, two])

    def test_an_over_long_paragraph_is_cut_at_a_sentence_end(self):
        sentences = ['%s number %d.' % (para('word', 30), n) for n in range(6)]

        chunks = chunk_text(' '.join(sentences), target=400, overlap=0)

        # Every chunk ends where a sentence ended, not mid-clause.
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertTrue(chunk.text.rstrip().endswith('.'), chunk.text[-40:])

    def test_a_sentence_longer_than_a_chunk_is_still_kept(self):
        # A table, a formula dump, or a document with no punctuation at all.
        # There is no good boundary in it; losing the text would be worse than
        # an awkward one.
        monster = para('x', 900)

        chunks = chunk_text(monster, target=300, overlap=0)

        self.assertGreater(len(chunks), 1)
        self.assertIn('x', chunks[0].text)

    def test_chunks_stay_within_the_target(self):
        text = '\n\n'.join(para('word', 60) for _ in range(8))

        for chunk in chunk_text(text, target=500, overlap=0):
            self.assertLessEqual(len(chunk.text), 500)


class RuntTests(SimpleTestCase):
    def test_a_heading_is_folded_into_what_it_introduces(self):
        # On its own a heading embeds to a vector that is close to far too
        # much. Attached to its paragraph it sharpens that paragraph instead.
        body = para('content', 40)

        chunks = chunk_text('Unit 3: Trees\n\n%s' % body, overlap=0)

        self.assertEqual(len(chunks), 1)
        self.assertIn('Unit 3: Trees', chunks[0].text)
        self.assertIn('content', chunks[0].text)

    def test_a_short_tail_is_folded_backwards(self):
        # Nothing follows it to merge forward into.
        body = para('content', 60)

        chunks = chunk_text('%s\n\nPage 4' % body, overlap=0)

        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].text.endswith('Page 4'))

    def test_a_document_of_nothing_but_a_heading_is_still_kept(self):
        # Merging has nowhere to put it, and dropping it would silently lose
        # the only text in the file.
        chunks = chunk_text('Unit 3: Trees')

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, 'Unit 3: Trees')

    def test_nothing_below_the_minimum_survives_as_its_own_chunk(self):
        text = '\n\n'.join(['Heading', para('body', 40), 'x', para('more', 40)])

        chunks = chunk_text(text, overlap=0)

        for chunk in chunks[:-1]:
            self.assertGreaterEqual(len(chunk.text), MIN_CHARS)


class OverlapTests(SimpleTestCase):
    def test_consecutive_chunks_share_text(self):
        # A definition that straddles a boundary is otherwise unfindable: it is
        # in neither chunk in full, so it is close to neither vector.
        one, two = para('alpha', 50), para('beta', 50)

        chunks = chunk_text('%s\n\n%s' % (one, two), overlap=60)

        self.assertEqual(len(chunks), 2)
        self.assertIn('alpha', chunks[1].text)
        self.assertIn('beta', chunks[1].text)

    def test_the_first_chunk_carries_nothing(self):
        one, two = para('alpha', 50), para('beta', 50)

        chunks = chunk_text('%s\n\n%s' % (one, two), overlap=60)

        self.assertEqual(chunks[0].text, one)

    def test_the_carried_text_never_starts_mid_word(self):
        text = '\n\n'.join(para('supercalifragilistic', 20) for _ in range(3))

        for chunk in chunk_text(text, overlap=50)[1:]:
            first = chunk.text.split(' ', 1)[0]
            self.assertEqual(first, 'supercalifragilistic', chunk.text[:60])

    def test_overlap_at_least_as_large_as_the_target_is_refused(self):
        # It would make every chunk contain the previous one entire.
        with self.assertRaises(ValueError):
            chunk_text('anything', target=100, overlap=100)


class OffsetTests(SimpleTestCase):
    def test_offsets_locate_the_chunk_in_the_document(self):
        one, two = para('alpha', 40), para('beta', 40)
        text = '%s\n\n%s' % (one, two)

        chunks = chunk_text(text, overlap=0)

        for chunk in chunks:
            self.assertEqual(text[chunk.start:chunk.end], chunk.text)

    def test_indexes_run_in_document_order(self):
        text = '\n\n'.join(para('word', 40) for _ in range(5))

        chunks = chunk_text(text, overlap=0)

        self.assertEqual([c.index for c in chunks], list(range(len(chunks))))

    def test_a_chunk_is_a_named_tuple_so_templates_can_read_it(self):
        chunk = chunk_text('Binary trees are structures.')[0]

        self.assertIsInstance(chunk, Chunk)
        self.assertEqual(chunk.index, 0)


class DeterminismTests(SimpleTestCase):
    def test_the_same_document_always_chunks_the_same_way(self):
        # Re-ingesting an unchanged document has to recognise it as unchanged.
        # If chunking wandered, every re-ingest would duplicate the file and
        # quietly double the embedding bill.
        text = '\n\n'.join(para('word', 50) for _ in range(6))

        self.assertEqual(chunk_text(text), chunk_text(text))

    def test_hard_wrapped_text_chunks_the_same_as_flowed_text(self):
        # The same paragraph out of a PDF text layer and out of a text file
        # must land in the same chunk, or the two ingests disagree about a
        # document that is word-for-word identical.
        flowed = para('word', 50)
        wrapped = '\n'.join(flowed[i:i + 40] for i in range(0, len(flowed), 40))

        self.assertEqual([c.text for c in chunk_text(wrapped, overlap=0)],
                         [c.text for c in chunk_text(flowed, overlap=0)])
