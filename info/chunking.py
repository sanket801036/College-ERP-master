"""Splitting a document into the pieces a retriever can actually match.

Retrieval quality is decided here, before any model is involved. An embedding
is one vector for a whole chunk, so a chunk holding four unrelated paragraphs
averages into a vector that is close to nothing, and a chunk cut mid-sentence
embeds a fragment whose meaning is not the meaning of either half. Both fail
quietly: the search returns *something*, it is just the wrong something, and
nothing in the stack reports an error.

So the rules here are about boundaries and overlap rather than about size:
prefer to cut where the author already cut, and let consecutive chunks share a
little text so a fact that straddles a boundary is still findable.

Nothing in this module talks to a model or to the database. It is pure text in,
pure text out, which is what makes it the one part of the pipeline that can be
tested exhaustively.
"""
import re
from collections import namedtuple

# A chunk knows where it came from. The offsets are what a citation is built
# from later - "Unit 3, characters 4200-5400" survives the document being
# re-chunked with different settings, where a bare chunk index would not.
Chunk = namedtuple('Chunk', 'text start end index')

# Sizes are in characters, not tokens, and that is a deliberate trade.
# Counting tokens means shipping a tokenizer that matches whichever embedding
# model is configured, and being wrong about it silently when the model
# changes. Characters are stable, and the ratio is close enough: at roughly
# four characters per token, 1200 characters is ~300 tokens, comfortably inside
# every embedding model's input limit with room for the overlap.
TARGET_CHARS = 1200

# About fifteen percent. Enough that a definition split across a boundary
# appears whole in one of the two chunks; small enough that the bank is not
# mostly duplicates.
OVERLAP_CHARS = 180

# And never more than this share of either neighbour, whatever OVERLAP_CHARS
# says. The flat number is right for a full-size chunk and wrong for a short
# one, where it would make a passage mostly its predecessor - see `_emit`.
OVERLAP_MAX_FRACTION = 0.25

# Below this a chunk is a heading, a page number or a stray line. Embedding it
# gives a vector that matches far too much, so it is folded into its neighbour
# instead of being stored as a chunk of its own.
MIN_CHARS = 120

# Two or more newlines is a paragraph break in every format we ingest - a PDF
# text layer, a markdown file, or pasted notes.
_PARAGRAPH = re.compile(r'\n\s*\n')

# Sentence ends, approximately. Deliberately not a full sentence tokenizer:
# this only has to find a *decent* place to cut when a paragraph is too long to
# keep whole, and a wrong guess costs a slightly awkward boundary rather than a
# wrong answer.
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')

# A bullet, a dash, or a numbered clause. A line break before one of these is
# the author's, not the page width's.
_LIST_ITEM = re.compile(r'^\s*(?:[-*•‣◦]|\(?\d+[.)])\s')


def normalise(text):
    """Collapse the whitespace a PDF text layer leaves behind.

    Extracted PDF text arrives with hard-wrapped lines, stray carriage returns
    and runs of spaces where the layout engine positioned words. None of that
    is meaning, and all of it moves the embedding.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Any run of blank lines becomes exactly one blank line, so _PARAGRAPH has
    # a single shape to look for.
    text = re.sub(r'\n\s*\n[\s\n]*', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = '\n'.join(line.strip() for line in text.split('\n')).strip()
    return _unwrap(text)


def _unwrap(text):
    """Join lines a layout engine broke; keep lines an author broke.

    A PDF text layer wraps every line at whatever column the page ended, and
    pasted notes do the same. Those breaks are not meaning, and keeping them
    means the same paragraph out of a PDF and out of a text file chunks into
    different strings - so a re-ingest of identical content fails to recognise
    itself and stores the document twice.

    The exception is a line starting a list item or a numbered clause. That
    break the author put there, and joining it would run a syllabus's five
    units together into one sentence.
    """
    lines = []
    for line in text.split('\n'):
        joinable = (
            lines                                  # something to join onto
            and lines[-1]                          # not across a blank line
            and line                               # not a blank line itself
            and not _LIST_ITEM.match(line)         # not the author's break
            and lines[-1][-1] not in '.!?:;'       # previous line unfinished
        )
        if joinable:
            lines[-1] = '%s %s' % (lines[-1], line)
        else:
            lines.append(line)
    return '\n'.join(lines)


def chunk_text(text, *, target=TARGET_CHARS, overlap=OVERLAP_CHARS,
               minimum=MIN_CHARS):
    """Split text into overlapping chunks, cutting where the author cut.

    Returns a list of Chunk. Deterministic: the same text and settings always
    produce the same chunks, which is what lets a re-ingest recognise that
    nothing changed instead of duplicating the document.
    """
    if overlap >= target:
        raise ValueError('overlap must be smaller than target')

    text = normalise(text)
    if not text:
        return []

    pieces = _split_to_size(text, target)
    return _emit(text, _merge_runts(pieces, minimum), overlap, target)


def _split_to_size(text, target):
    """Paragraphs, further split when one is longer than a chunk."""
    pieces = []
    for para in _PARAGRAPH.split(text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= target:
            pieces.append(para)
        else:
            pieces.extend(_split_paragraph(para, target))
    return pieces


def _split_paragraph(para, target):
    """One over-long paragraph, cut at sentence ends where possible."""
    out, current = [], ''
    for sentence in _SENTENCE_END.split(para):
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= target:
            current = '%s %s' % (current, sentence)
        else:
            out.append(current)
            current = sentence

        # A single sentence longer than a whole chunk is a table, a formula
        # dump or a document with no punctuation. There is no good boundary in
        # it, so take the size hit rather than lose the text.
        while len(current) > target:
            out.append(current[:target])
            current = current[target:]

    if current:
        out.append(current)
    return out


def _merge_runts(pieces, minimum):
    """Fold anything too short into its neighbour.

    A heading is a runt, and a heading belongs with the paragraph it
    introduces, so it merges forward. A short trailing fragment has nothing
    after it and merges back instead.
    """
    merged = []
    for piece in pieces:
        if merged and len(merged[-1]) < minimum:
            merged[-1] = '%s\n\n%s' % (merged[-1], piece)
        else:
            merged.append(piece)

    if len(merged) > 1 and len(merged[-1]) < minimum:
        tail = merged.pop()
        merged[-1] = '%s\n\n%s' % (merged[-1], tail)
    return merged


def _emit(text, pieces, overlap, target):
    """Attach overlap and locate each chunk back in the original."""
    chunks, cursor = [], 0
    for index, piece in enumerate(pieces):
        # Locating rather than accumulating: the pieces have been stripped and
        # rejoined, so their lengths no longer add up to an offset in `text`.
        start = text.find(piece, cursor)
        if start == -1:
            # Only reachable for a piece that was merged or hard-split, whose
            # exact string is no longer contiguous in the source. The chunk is
            # still correct; only its offsets fall back to the cursor.
            start = cursor
        end = start + len(piece)
        cursor = end

        body = piece
        if index and overlap:
            # The tail of the previous chunk, cut at a space so the overlap
            # does not begin with half a word.
            #
            # Capped as a fraction of the neighbours rather than taken flat.
            # A flat 180 characters is the intended ~15% of a full-size chunk
            # and half of a short one, and a chunk that is half its neighbour
            # embeds to a vector pulled toward the neighbour's subject. That
            # showed up only against a real embedding model: a question about
            # re-evaluation matched the fees passage at 0.805 and the
            # re-evaluation passage at 0.767, because the latter opened with
            # 180 characters about fees.
            previous = pieces[index - 1]
            take = min(overlap,
                       int(len(previous) * OVERLAP_MAX_FRACTION),
                       int(len(piece) * OVERLAP_MAX_FRACTION))
            carried = previous[-take:] if take else ''
            space = carried.find(' ')
            if space != -1:
                carried = carried[space + 1:]
            if carried:
                body = '%s %s' % (carried, piece)
                start = max(0, start - len(carried) - 1)

        chunks.append(Chunk(text=body, start=start, end=end, index=index))

    return chunks
