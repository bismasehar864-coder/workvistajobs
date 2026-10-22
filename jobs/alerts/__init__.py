"""Telling a job seeker when a new job suits them.

Three modules, split by how they fail rather than by layer:

- matching.py       pure scoring, total, no database
- notifications.py  writes rows; runs right after a scrape
- digest.py         reaches an SMTP server that can hang

That last one is why the bell and the email are separate passes: the
bell must never wait on a mail server, and a mail server being down
must never fail a scrape.
"""
