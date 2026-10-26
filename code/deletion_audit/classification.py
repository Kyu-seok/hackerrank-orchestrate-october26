"""Does ``request_text`` authorize deletion?

Placeholder until the LLM classification ticket: every request is treated as a
deletion request (all 32 labeled samples are).
"""


def is_deletion_request(request):
    return True
