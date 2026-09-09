"""The corpus: what goes into it, and who is allowed to search which part.

`chunking.py` decides where a document is cut, `embeddings.py` turns those
pieces into vectors and `generation.py` writes an answer from them. This module
is the part that touches the database - it stores the pieces, and it decides
which of them a given person's question is even allowed to see.

**That second job is the security boundary.** `guardrails.py` explains at
length why the prompt-injection classifier is not: it was measured, it misses
things, and no threshold catches everything. What actually keeps one student
out of another's coursework is that `searchable_for()` never puts the other
student's material in the candidate set. An injection that gets past the
classifier still has nothing to reach for.

So the rule here is narrow and worth stating plainly: a student may search the
material of courses their class is actually assigned, plus college-wide
policy, and nothing else. Not "material they might reasonably want" - material
their timetable entitles them to.
"""
import hashlib
import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from pgvector.django import CosineDistance

from info.chunking import chunk_text, normalise
from info.embeddings import get_embedder
from info.models import (
    MATERIAL_COURSE,
    MATERIAL_POLICY,
    Assign,
    AuditLog,
    CourseMaterial,
    MaterialChunk,
)

logger = logging.getLogger(__name__)


class MaterialNotAllowed(Exception):
    """Refused, with a reason written to be shown to whoever tried."""


def content_hash(text):
    """A stable identity for a document's *words*, not its bytes or its layout.

    Hashing the file would store the same handbook twice when it arrives once
    as a PDF and once pasted into a box, and every answer would then cite
    whichever copy the search happened to hit.

    Every run of whitespace collapses to one space here - more aggressively
    than `normalise()`, which keeps paragraph structure because the chunker
    needs it. Identity must not depend on where a layout engine chose to wrap:
    a hard wrap that happens to land just after a full stop is preserved by
    `normalise` and absent from the flowed copy of the same sentence, so
    hashing that would call one document two.
    """
    words = ' '.join(normalise(text).split())
    return hashlib.sha256(words.encode('utf-8')).hexdigest()


def can_ingest(course, kind, text):
    """(allowed, reason). The reason is written to be shown."""
    if not (text or '').strip():
        return False, 'There is no text in that document.'

    if kind == MATERIAL_COURSE and course is None:
        return False, ('Course material has to belong to a course, or no '
                       'student can reach it.')
    if kind == MATERIAL_POLICY and course is not None:
        return False, 'College policy is not attached to a single course.'

    digest = content_hash(text)
    if CourseMaterial.objects.filter(course=course,
                                     content_hash=digest).exists():
        return False, 'That document is already here, word for word.'

    return True, ''


@transaction.atomic
def ingest(text, *, title, actor, course=None, kind=MATERIAL_COURSE,
           source='', publish=False):
    """Store a document and the passages it splits into.

    Deliberately does not embed. Embedding is a network call that costs money
    and fails, and doing it inside the transaction that stores the text would
    mean a provider outage loses the upload as well. The passages are stored
    first and given vectors afterwards, so a failed embedding leaves a
    document that is present, visible to staff, and simply not yet searchable.
    """
    allowed, reason = can_ingest(course, kind, text)
    if not allowed:
        raise MaterialNotAllowed(reason)

    chunks = chunk_text(text)
    if not chunks:
        raise MaterialNotAllowed('There is no text in that document.')

    material = CourseMaterial.objects.create(
        course=course, kind=kind, title=title, source=source,
        content_hash=content_hash(text), chunk_count=len(chunks),
        uploaded_by=actor if getattr(actor, 'pk', None) else None,
        is_published=publish,
        published_at=timezone.now() if publish else None)

    MaterialChunk.objects.bulk_create([
        MaterialChunk(material=material, index=chunk.index, text=chunk.text,
                      start=chunk.start, end=chunk.end)
        for chunk in chunks])

    AuditLog.record(
        actor, 'material.added', material,
        '%s: %d passages from %s' % (material.title, len(chunks),
                                     source or 'pasted text'))
    return material


@transaction.atomic
def remove(material, actor, reason=''):
    """Take a document out of the corpus, passages and all."""
    title = material.title
    material.chunks.all().delete()
    material.delete()
    AuditLog.record(actor, 'material.removed', None,
                    '%s removed%s' % (title, ': %s' % reason if reason else ''))


def courses_for(student):
    """The courses this student's class is actually assigned.

    Derived from `Assign` rather than `StudentCourse`, matching how the marks
    page and `decorators.assert_teaches` already answer this question -
    StudentCourse rows are created by a signal and can legitimately be
    missing, and a missing row must not silently widen or narrow what somebody
    can search.
    """
    return (Assign.objects
            .filter(class_id=student.class_id_id)
            .values_list('course_id', flat=True)
            .distinct())


def searchable_for(user):
    """The chunks a question from this user is allowed to be answered from.

    **The boundary.** Everything the assistant ever sees passes through here.

    - a student: their class's course material, plus college policy
    - a teacher or an administrator: everything published, because they can
      already open every course in the app
    - anybody else, including an anonymous request: nothing at all

    Unpublished material is invisible to everybody. Staff review it on its own
    page rather than by having the assistant answer out of it.
    """
    published = MaterialChunk.objects.filter(material__is_published=True)

    if user is None or not getattr(user, 'is_authenticated', False):
        return MaterialChunk.objects.none()

    if user.is_superuser or getattr(user, 'is_teacher', False):
        return published

    if getattr(user, 'is_student', False):
        return published.filter(_student_scope(user.student))

    return MaterialChunk.objects.none()


def _student_scope(student):
    """Course material for their own timetable, or college policy. No else."""
    return (Q(material__kind=MATERIAL_POLICY)
            | Q(material__kind=MATERIAL_COURSE,
                material__course_id__in=courses_for(student)))


# How many passages an answer is built from. Enough that a fact split across a
# boundary is present in one of them, few enough that the model is not handed
# four topics and asked to pick.
TOP_K = 4

# Below this, the best match is not about the question, and the honest answer
# is "I do not have that" - given without a generation call at all.
#
# Measured against a real embedding model rather than chosen round. On three
# questions the correct passage scored 0.809, 0.813 and 0.876; the other
# passages of the same handbook sat at 0.73-0.77; and "what is the weather in
# Mumbai", which the corpus says nothing about, still scored 0.638-0.678. A
# floor of 0.62 - the first guess here - let every one of those through, so an
# off-topic question was answered from the fees paragraph.
#
# 0.72 sits above the off-topic ceiling and well under the correct-answer
# floor. Note what it does *not* separate: a wrong passage from the same
# handbook still clears it, which is fine because the right one outranks it
# and the prompt tells the model to answer only from what it was given.
#
# Provisional: three passages is not a corpus. Re-measure once there is real
# course material, with the same shape of check - a question the documents
# genuinely do not answer must come back empty.
MIN_SIMILARITY = 0.72

EMBED_BATCH = 32


def embed_pending(material=None, embedder=None, limit=None):
    """Give vectors to the passages that do not have one yet.

    Separate from `ingest` on purpose - see its docstring. Re-runnable, and it
    only ever touches rows where `embedding` is null, so an interrupted run
    resumes instead of paying to redo the part that succeeded.

    Returns how many passages were embedded.
    """
    embedder = embedder or get_embedder()
    pending = MaterialChunk.objects.filter(embedding__isnull=True)
    if material is not None:
        pending = pending.filter(material=material)
    pending = pending.order_by('material_id', 'index')
    if limit:
        pending = pending[:limit]

    chunks = list(pending)
    done = 0
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start:start + EMBED_BATCH]
        vectors = embedder.embed([c.text for c in batch])

        now = timezone.now()
        for chunk, vector in zip(batch, vectors, strict=True):
            chunk.embedding = vector
            chunk.embedded_at = now
        MaterialChunk.objects.bulk_update(batch, ['embedding', 'embedded_at'])
        done += len(batch)

    if done:
        logger.info('embedded %d passages', done)
    return done


def search(question, user, *, top_k=TOP_K, embedder=None,
           minimum=MIN_SIMILARITY):
    """The passages that might answer this question, best first.

    Scoped through `searchable_for` before any distance is computed, so the
    boundary is applied by the database rather than by trimming results
    afterwards. A passage the asker may not read is never a candidate, never
    ranked, and never in the context handed to a model.

    Returns [(chunk, similarity)] and an empty list when nothing clears the
    floor - which the caller must treat as "say you do not know" rather than
    as "use the best of a bad set".
    """
    if not (question or '').strip():
        return []

    allowed = searchable_for(user).filter(embedding__isnull=False)
    # Cheap and worth it: scoping alone can leave nothing to search, and
    # embedding the question costs a network call.
    if not allowed.exists():
        return []

    embedder = embedder or get_embedder()
    vector = embedder.embed_one(question)

    rows = (allowed
            .annotate(distance=CosineDistance('embedding', vector))
            .order_by('distance')
            .select_related('material')[:top_k])

    # pgvector's cosine *distance* is 1 - similarity.
    scored = [(chunk, 1 - chunk.distance) for chunk in rows]
    return [(chunk, score) for chunk, score in scored if score >= minimum]


def context_for(results):
    """The retrieved passages, formatted for a prompt, with their citations.

    Each passage is numbered and labelled so the model can point at one, and
    so an answer that cites [2] can be checked against the same [2] on screen.
    An unlabelled blob invites the model to blend four passages into one
    confident paragraph with nothing to verify.
    """
    return '\n\n'.join(
        '[%d] (%s)\n%s' % (n, chunk.citation, chunk.text)
        for n, (chunk, _) in enumerate(results, start=1))


# What the model is told before every question. Short on purpose: a long
# instruction competes with the passages for the model's attention, and the
# only behaviours that matter here are "use what you were given" and "say so
# when it is not there".
SYSTEM_PROMPT = (
    'You are the assistant for a college ERP. Answer only from the numbered '
    'passages below. Cite the passage you used, like [1]. If the passages do '
    'not contain the answer, reply exactly: I do not have that in the college '
    'material. Keep answers short and plain. Never invent a rule, a date, a '
    'fee or a number that is not in the passages.'
)

# Shown when retrieval found nothing close enough. Deliberately the same
# sentence the model is told to use, so a refusal reads the same whether it
# came from the floor or from the model.
NO_ANSWER = 'I do not have that in the college material.'


class Reply:
    """An answer and everything needed to show why it should be believed."""

    def __init__(self, text, *, sources=(), refused=False, reason='',
                 truncated=False):
        self.text = text
        self.sources = list(sources)
        self.refused = refused
        self.reason = reason
        self.truncated = truncated

    def __str__(self):
        return self.text


def answer(question, user, *, embedder=None, generator=None, guard=None):
    """The whole question-to-answer path, in the order the checks must run.

    The order is the design. Budget before guard because a refused message
    should not cost two calls; guard before retrieval because a message that
    is not a question should not touch the corpus; retrieval before
    generation because an empty result is answered without a model at all.
    """
    from info import guardrails
    from info.generation import get_generator

    allowed, reason = guardrails.can_spend(user, 'generation')
    if not allowed:
        return Reply('', refused=True, reason=reason)

    guard = guard or guardrails.get_guard()
    verdict = guard.check(question)
    if not verdict.allowed:
        return Reply('', refused=True, reason=verdict.reason)

    results = search(question, user, embedder=embedder)
    if not results:
        # No model call. Cheaper, and a refusal nobody had to pay for.
        return Reply(NO_ANSWER, refused=False)

    generator = generator or get_generator()
    guardrails.record_spend(user, 'generation')
    written = generator.ask(
        SYSTEM_PROMPT,
        '%s\n\nQuestion: %s' % (context_for(results), question))

    return Reply(written.text,
                 sources=[chunk for chunk, _ in results],
                 truncated=written.truncated)


# ---------------------------------------------------------------------------
# When the assistant cannot help
# ---------------------------------------------------------------------------


class EscalationNotAllowed(Exception):
    """Refused, with a reason written to be shown to the student."""


def can_escalate(student, course=None):
    """(allowed, reason). The reason is written to be shown."""
    from info.models import MAX_OPEN_ESCALATIONS, AssistantEscalation

    open_now = AssistantEscalation.objects.filter(student=student).open().count()
    if open_now >= MAX_OPEN_ESCALATIONS:
        return False, ('You already have %d questions waiting for a teacher. '
                       'Wait for one to be answered, or withdraw it.'
                       % MAX_OPEN_ESCALATIONS)

    if course is not None and course.pk not in set(courses_for(student)):
        return False, 'That course is not on your timetable.'

    return True, ''


@transaction.atomic
def escalate(student, question, actor, *, assistant_said='', course=None):
    """Hand a question to a teacher, with what the assistant already said."""
    from info.models import AssistantEscalation

    allowed, reason = can_escalate(student, course)
    if not allowed:
        raise EscalationNotAllowed(reason)

    question = (question or '').strip()
    if len(question) < 5:
        raise EscalationNotAllowed('Say a little more about what you need.')

    escalation = AssistantEscalation.objects.create(
        student=student, course=course, question=question,
        assistant_said=(assistant_said or '')[:2000])

    AuditLog.record(actor, 'assistant.escalated', escalation,
                    'asked a teacher: %s' % question[:120], student=student)
    return escalation


@transaction.atomic
def answer_escalation(escalation, response, actor):
    """A teacher's written answer. There is no 'resolved without a reason'."""
    from info.models import ESCALATION_ANSWERED, ESCALATION_OPEN

    if escalation.status != ESCALATION_OPEN:
        raise EscalationNotAllowed('That question has already been dealt with.')

    response = (response or '').strip()
    if len(response) < 10:
        # The student is waiting because a machine gave them nothing useful.
        # A one-word reply repeats the experience with a person attached.
        raise EscalationNotAllowed('Write an answer the student can use.')

    escalation.status = ESCALATION_ANSWERED
    escalation.response = response
    escalation.answered_by = actor if getattr(actor, 'pk', None) else None
    escalation.answered_at = timezone.now()
    escalation.save(update_fields=['status', 'response', 'answered_by',
                                   'answered_at'])

    AuditLog.record(actor, 'assistant.answered', escalation,
                    'answered %s' % escalation.student.name,
                    student=escalation.student)
    return escalation


@transaction.atomic
def withdraw_escalation(escalation, actor):
    from info.models import ESCALATION_OPEN, ESCALATION_WITHDRAWN

    if escalation.status != ESCALATION_OPEN:
        raise EscalationNotAllowed('That question is no longer open.')

    escalation.status = ESCALATION_WITHDRAWN
    escalation.save(update_fields=['status'])
    AuditLog.record(actor, 'assistant.withdrawn', escalation,
                    'withdrew a question', student=escalation.student)
    return escalation
