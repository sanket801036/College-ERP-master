"""Deployment checks for the settings that fail quietly.

`manage.py check` runs these on every start, including the one Render does
during a deploy, which is the only moment anybody is watching.

The case that prompted this file: the bucket, the region and the credentials
were set on the deployed service but the endpoint was not, so boto3 signed the
request for Backblaze and addressed it to Amazon. Uploads worked, the file
landed in the bucket, and every link pointed at a host that had never heard of
it - a failure with no error anywhere near it.
"""
import re

from django.conf import settings
from django.core.checks import Warning, register

# AWS regions are `us-east-1`, `eu-west-2`, `ap-south-1`: two letters, a word,
# one or two digits. Backblaze uses `us-east-005` and Cloudflare uses `auto`,
# so a region that does not fit AWS's shape is a region belonging to somebody
# who needs an endpoint.
AWS_REGION = re.compile(r'^[a-z]{2}(-gov)?-[a-z]+-\d{1,2}$')

W001 = 'info.W001'
W002 = 'info.W002'


@register('deploy')
def check_object_storage(app_configs, **kwargs):
    """Is the S3 configuration internally consistent?"""
    if not getattr(settings, 'USE_S3', False):
        return []

    problems = []
    region = getattr(settings, 'AWS_S3_REGION_NAME', '') or ''
    endpoint = getattr(settings, 'AWS_S3_ENDPOINT_URL', None)

    if not endpoint and region and not AWS_REGION.match(region):
        problems.append(Warning(
            'AWS_S3_REGION_NAME is %r, which is not an AWS region, but no '
            'AWS_S3_ENDPOINT_URL is set.' % region,
            hint='Uploads will be signed for that region and addressed to '
                 'Amazon, so they will be written to a bucket whose links '
                 'nobody can open. Backblaze wants '
                 'https://s3.<region>.backblazeb2.com; Cloudflare R2 wants '
                 'the account endpoint from its dashboard.',
            id=W001))

    missing = [name for name in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY')
               if not getattr(settings, name, '')]
    if missing:
        problems.append(Warning(
            'A bucket is configured but %s is empty.' % ' and '.join(missing),
            hint='Every upload will fail at the point of writing. Unset '
                 'AWS_STORAGE_BUCKET_NAME to fall back to local disk '
                 'deliberately rather than by accident.',
            id=W002))

    return problems


W003 = 'info.W003'
W004 = 'info.W004'
W005 = 'info.W005'


@register('deploy')
def check_ai_layer(app_configs, **kwargs):
    """Is the AI configuration whole, or half-configured?

    Two providers are needed and neither does the other's job: Groq writes
    answers and has no embeddings endpoint, Gemini embeds and is not used for
    generation. Configuring one and not the other leaves a chatbot that
    retrieves against meaningless vectors, or a retriever with nothing to
    answer with - both of which look like they work.
    """
    generation = bool(getattr(settings, 'GROQ_API_KEY', ''))
    embedding = bool(getattr(settings, 'GEMINI_API_KEY', ''))
    problems = []

    if generation and not embedding:
        problems.append(Warning(
            'GROQ_API_KEY is set but GEMINI_API_KEY is not.',
            hint='Retrieval will fall back to the deterministic fake '
                 'embedder, which knows nothing about meaning. The chatbot '
                 'will answer fluently from whichever passages it happened to '
                 'retrieve, and nothing will report that they were the wrong '
                 'ones. Set GEMINI_API_KEY, or unset GROQ_API_KEY to turn the '
                 'feature off deliberately.',
            id=W003))

    if embedding and not generation:
        problems.append(Warning(
            'GEMINI_API_KEY is set but GROQ_API_KEY is not.',
            hint='Documents will be embedded and stored, and there is nothing '
                 'configured to answer with. The prompt guard is off too, '
                 'since it runs on the same key.',
            id=W004))

    if generation or embedding:
        caps = [name for name in ('AI_DAILY_CALL_CAP', 'AI_USER_DAILY_CALL_CAP')
                if getattr(settings, name, 0) <= 0]
        if caps:
            problems.append(Warning(
                'The AI layer is configured but %s is zero.'
                % ' and '.join(caps),
                hint='Zero switches the feature off, which is a legitimate '
                     'setting and the fastest way to stop a runaway. If that '
                     'was not the intent, a public demo with an uncapped key '
                     'behind it is one bored visitor away from an exhausted '
                     'quota.',
                id=W005))

    return problems
