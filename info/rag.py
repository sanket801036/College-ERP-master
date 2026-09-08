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

from info.chunking import chunk_text, normalise
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
