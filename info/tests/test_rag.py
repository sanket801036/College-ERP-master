"""The corpus, and the scoping that is the actual security boundary.

`guardrails.py` is measured and honest about missing things: no threshold on a
prompt-injection classifier catches every attempt, and one of the messages
tested there scores lower than an ordinary question about fees. So the
classifier is not what keeps one student out of another's coursework.

`searchable_for()` is. An injection that gets past the classifier reaches a
candidate set that never contained the other student's material, and there is
nothing in it to leak. That makes the ScopeTests below the most important in
this file - every one of them is a leak if it fails, and none of them would
show up as an error anywhere. The answer would simply be about the wrong
course.
"""
from django.test import TestCase

from info import rag
from info.embeddings import Embedder, FakeEmbedder
from info.models import (
    EMBEDDING_DIMENSIONS,
    MATERIAL_COURSE,
    MATERIAL_POLICY,
    AuditLog,
    CourseMaterial,
    MaterialChunk,
)
from info.tests import factories as f

HANDBOOK = """
Attendance

A student must attend at least seventy five percent of the classes held in
each course to be eligible for the semester end examination. Approved medical
leave is excluded from the total rather than counted as present.

Fees

Semester fees are due on the first working day of the semester. A late payment
carries a fine of two hundred rupees per week, capped at two thousand rupees.
"""


class IngestBase(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.course = f.make_course(self.dept)
        self.teacher = f.make_teacher(self.dept, username='staff')
        self.student = f.make_student(self.klass, username='asha')
        self.admin = f.make_admin()

    def policy(self, text=HANDBOOK, title='Handbook', publish=True):
        return rag.ingest(text, title=title, actor=self.admin,
                          kind=MATERIAL_POLICY, publish=publish)

    def material(self, course=None, text=HANDBOOK, title='Notes',
                 publish=True):
        return rag.ingest(text, title=title, actor=self.teacher.user,
                          course=course or self.course,
                          kind=MATERIAL_COURSE, publish=publish)


class IngestTests(IngestBase):
    def test_a_document_becomes_passages(self):
        material = self.policy()

        self.assertGreater(material.chunk_count, 1)
        self.assertEqual(material.chunks.count(), material.chunk_count)

    def test_the_passages_keep_their_order(self):
        material = self.policy()

        indexes = list(material.chunks.values_list('index', flat=True))
        self.assertEqual(indexes, sorted(indexes))
        self.assertEqual(indexes[0], 0)

    def test_an_empty_document_is_refused_with_a_reason(self):
        with self.assertRaises(rag.MaterialNotAllowed) as caught:
            rag.ingest('   \n\n  ', title='Nothing', actor=self.admin,
                       kind=MATERIAL_POLICY)

        self.assertIn('no text', str(caught.exception))

    def test_the_same_document_twice_is_refused(self):
        # Otherwise every answer cites whichever copy the search happened to
        # hit, and the embedding bill doubles for no new information.
        self.policy()

        with self.assertRaises(rag.MaterialNotAllowed) as caught:
            self.policy(title='Handbook again')

        self.assertIn('already here', str(caught.exception))

    def test_the_same_text_reflowed_is_still_the_same_document(self):
        # The hash is over the normalised text, not the bytes. A handbook out
        # of a PDF and out of a pasted email is one document.
        self.policy()
        hard_wrapped = HANDBOOK.replace(' ', '\n', 40)

        with self.assertRaises(rag.MaterialNotAllowed):
            rag.ingest(hard_wrapped, title='Same thing', actor=self.admin,
                       kind=MATERIAL_POLICY)

    def test_the_same_text_for_two_different_courses_is_allowed(self):
        # A shared reading really can belong to two courses.
        other = f.make_course(self.dept, id='CS102', name='Algorithms')
        self.material()

        self.assertIsNotNone(self.material(course=other))

    def test_course_material_without_a_course_is_refused(self):
        # No student could ever reach it.
        with self.assertRaises(rag.MaterialNotAllowed) as caught:
            rag.ingest(HANDBOOK, title='Orphan', actor=self.teacher.user,
                       kind=MATERIAL_COURSE)

        self.assertIn('belong to a course', str(caught.exception))

    def test_policy_pinned_to_one_course_is_refused(self):
        with self.assertRaises(rag.MaterialNotAllowed):
            rag.ingest(HANDBOOK, title='Not policy', actor=self.admin,
                       course=self.course, kind=MATERIAL_POLICY)

    def test_ingesting_is_recorded(self):
        self.policy()

        self.assertTrue(AuditLog.objects.filter(action='material.added')
                        .exists())

    def test_removing_takes_the_passages_with_it(self):
        material = self.policy()

        rag.remove(material, self.admin)

        self.assertEqual(CourseMaterial.objects.count(), 0)
        self.assertEqual(MaterialChunk.objects.count(), 0)


class PublicationTests(IngestBase):
    def test_an_unpublished_document_is_searchable_by_nobody(self):
        # A teacher uploading last year's paper by mistake has to be able to
        # notice before students are answered out of it.
        self.material(publish=False)

        self.assertFalse(rag.searchable_for(self.student.user).exists())
        self.assertFalse(rag.searchable_for(self.teacher.user).exists())
        self.assertFalse(rag.searchable_for(self.admin).exists())

    def test_publishing_makes_it_searchable(self):
        material = self.material(publish=False)

        material.publish()

        self.assertTrue(rag.searchable_for(self.teacher.user).exists())

    def test_unpublishing_takes_it_back_out(self):
        material = self.material()

        material.unpublish()

        self.assertFalse(rag.searchable_for(self.student.user).exists())


class ScopeTests(IngestBase):
    """The boundary. Every failure here is a leak, and none of them raise."""

    def setUp(self):
        super().setUp()
        f.make_assign(self.klass, self.course, self.teacher)

    def test_a_student_can_search_their_own_course_material(self):
        self.material()

        self.assertTrue(rag.searchable_for(self.student.user).exists())

    def test_a_student_cannot_search_a_course_they_do_not_take(self):
        # The leak that matters. Nothing errors - the assistant would simply
        # answer out of somebody else's coursework.
        other_dept = f.make_dept(id='ME', name='Mechanical')
        other_course = f.make_course(other_dept, id='ME101', name='Thermo')
        self.material(course=other_course)

        self.assertFalse(rag.searchable_for(self.student.user).exists())

    def test_a_student_can_always_search_college_policy(self):
        self.policy()

        self.assertTrue(rag.searchable_for(self.student.user).exists())

    def test_the_scope_follows_the_timetable_not_the_enrolment_rows(self):
        # Assign is the authority record. StudentCourse rows are created by a
        # signal and can legitimately be missing; a missing one must not
        # silently change what somebody may search.
        self.material()
        self.student.user.student.studentcourse_set.all().delete()

        self.assertTrue(rag.searchable_for(self.student.user).exists())

    def test_a_teacher_sees_everything_published(self):
        # They can already open every course in the app; withholding it here
        # would be theatre.
        other_dept = f.make_dept(id='ME', name='Mechanical')
        other_course = f.make_course(other_dept, id='ME101', name='Thermo')
        self.material(course=other_course)

        self.assertTrue(rag.searchable_for(self.teacher.user).exists())

    def test_an_administrator_sees_everything_published(self):
        self.material()

        self.assertTrue(rag.searchable_for(self.admin).exists())

    def test_an_anonymous_request_sees_nothing(self):
        from django.contrib.auth.models import AnonymousUser

        self.policy()

        self.assertFalse(rag.searchable_for(AnonymousUser()).exists())

    def test_no_user_at_all_sees_nothing(self):
        self.policy()

        self.assertFalse(rag.searchable_for(None).exists())

    def test_a_signed_in_account_that_is_neither_sees_nothing(self):
        # An account with no student and no teacher record - an issued login
        # whose person was deleted, say.
        from info.models import User

        self.policy()
        stranger = User.objects.create_user('stranger', password='pass12345')

        self.assertFalse(rag.searchable_for(stranger).exists())


class CitationTests(IngestBase):
    def test_a_passage_names_where_it_came_from(self):
        material = rag.ingest(HANDBOOK, title='Handbook', actor=self.admin,
                              kind=MATERIAL_POLICY, source='Student Handbook',
                              publish=True)

        first = material.chunks.first()
        self.assertIn('Student Handbook', first.citation)

    def test_it_falls_back_to_the_title_when_there_is_no_source(self):
        material = self.policy(title='Rules')

        self.assertIn('Rules', material.chunks.first().citation)


class Steered(Embedder):
    """An embedder whose vectors are chosen by the test.

    FakeEmbedder is deterministic but meaningless - every pair of its vectors
    is roughly as similar as every other, so it cannot express "this passage
    is about the question and that one is not". These tests need to, so they
    say so directly.
    """

    name, dimensions = 'steered', EMBEDDING_DIMENSIONS

    def __init__(self, by_text, default=(0.0, 0.0, 1.0)):
        self.by_text = by_text
        self.default = default

    def embed(self, texts):
        out = []
        for text in texts:
            direction = self.default
            for needle, value in self.by_text.items():
                if needle in text:
                    direction = value
                    break
            out.append(self._pad(direction))
        return out

    def _pad(self, direction):
        """A three-dimensional idea in the column's real width.

        The stored column is 768 wide and the database refuses anything else.
        Trailing zeros do not move a cosine, so the test can keep reasoning in
        three axes while the row stays the shape production uses.
        """
        vector = list(direction) + [0.0] * (self.dimensions - len(direction))
        return vector[:self.dimensions]


class EmbedPendingTests(IngestBase):
    def test_it_gives_every_passage_a_vector(self):
        material = self.policy()

        done = rag.embed_pending(material=material, embedder=FakeEmbedder())

        self.assertEqual(done, material.chunk_count)
        self.assertFalse(material.chunks.filter(embedding__isnull=True).exists())

    def test_running_it_again_costs_nothing(self):
        # An interrupted run has to resume rather than pay to redo the part
        # that already succeeded.
        material = self.policy()
        rag.embed_pending(material=material, embedder=FakeEmbedder())

        self.assertEqual(
            rag.embed_pending(material=material, embedder=FakeEmbedder()), 0)

    def test_it_only_touches_passages_without_one(self):
        first = self.policy()
        rag.embed_pending(material=first, embedder=FakeEmbedder())
        second = self.material()

        done = rag.embed_pending(embedder=FakeEmbedder())

        self.assertEqual(done, second.chunk_count)

    def test_a_passage_records_when_it_was_embedded(self):
        material = self.policy()

        rag.embed_pending(material=material, embedder=FakeEmbedder())

        self.assertIsNotNone(material.chunks.first().embedded_at)


class SearchTests(IngestBase):
    def setUp(self):
        super().setUp()
        f.make_assign(self.klass, self.course, self.teacher)

    def prepared(self, embedder):
        material = self.policy()
        rag.embed_pending(material=material, embedder=embedder)
        return material

    def test_the_closest_passage_comes_first(self):
        embedder = Steered({'Attendance': (1, 0, 0), 'Fees': (0, 1, 0)})
        self.prepared(embedder)

        results = rag.search('anything', self.admin, embedder=Steered(
            {'anything': (0, 1, 0)}), minimum=0)

        self.assertIn('Fees', results[0][0].text)

    def test_nothing_below_the_floor_is_returned(self):
        # An off-topic question has to come back empty so the caller can say
        # "I do not know" instead of answering from the least bad paragraph.
        embedder = Steered({'Attendance': (1, 0, 0)}, default=(1, 0, 0))
        self.prepared(embedder)

        results = rag.search('unrelated', self.admin,
                             embedder=Steered({'unrelated': (0, 0, 1)}))

        self.assertEqual(results, [])

    def test_an_empty_question_searches_nothing(self):
        self.prepared(FakeEmbedder())

        self.assertEqual(rag.search('   ', self.admin), [])

    def test_a_student_never_retrieves_another_course_s_material(self):
        # The leak that matters, at the layer that actually prevents it. The
        # other course's passage is the *best* match here and must still not
        # appear.
        other_dept = f.make_dept(id='ME', name='Mechanical')
        other_course = f.make_course(other_dept, id='ME101', name='Thermo')
        embedder = Steered({}, default=(1, 0, 0))
        other = self.material(course=other_course)
        rag.embed_pending(material=other, embedder=embedder)

        results = rag.search('anything', self.student.user,
                             embedder=Steered({'anything': (1, 0, 0)}),
                             minimum=0)

        self.assertEqual(results, [])

    def test_an_anonymous_question_retrieves_nothing(self):
        from django.contrib.auth.models import AnonymousUser

        self.prepared(FakeEmbedder())

        self.assertEqual(rag.search('anything', AnonymousUser()), [])

    def test_nothing_searchable_means_the_question_is_never_embedded(self):
        # Embedding costs a network call. Scoping alone can leave nothing to
        # search, and paying to embed a question with no corpus behind it is
        # money for an empty list.
        embedder = FakeEmbedder()
        calls = []
        original = embedder.embed
        embedder.embed = lambda texts: calls.append(texts) or original(texts)

        self.assertEqual(rag.search('anything', self.student.user,
                                    embedder=embedder), [])
        self.assertEqual(calls, [])

    def test_an_unembedded_passage_is_not_a_candidate(self):
        # Stored but not yet embedded. It must be invisible to search rather
        # than matching nothing-in-particular.
        self.policy()

        self.assertEqual(rag.search('anything', self.admin,
                                    embedder=FakeEmbedder()), [])


class ContextTests(IngestBase):
    def test_each_passage_is_numbered_and_cited(self):
        # An answer citing [2] has to be checkable against the same [2] on
        # screen; an unlabelled blob invites the model to blend passages.
        material = rag.ingest(HANDBOOK, title='Handbook', actor=self.admin,
                              kind=MATERIAL_POLICY, source='Student Handbook',
                              publish=True)
        results = [(chunk, 0.9) for chunk in material.chunks.all()[:2]]

        context = rag.context_for(results)

        self.assertIn('[1]', context)
        self.assertIn('[2]', context)
        self.assertIn('Student Handbook', context)

    def test_no_passages_is_an_empty_context(self):
        self.assertEqual(rag.context_for([]), '')
