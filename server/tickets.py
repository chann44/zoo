"""Single-use, short-lived tickets for websocket URLs, so a viewer URL never carries a session token or API key.

Tickets live in this process's memory: they are lost on restart (the viewer asks for a new one) and are not shared
between API workers."""
import secrets
import time

TICKET_TTL = 30

# ticket -> (user id, what it opens, expiry on the monotonic clock)
_tickets: dict[str, tuple[str, str, float]] = {}


def issue(user_id: str, target: str) -> str:
    now = time.monotonic()
    for ticket, (_, _, expires) in list(_tickets.items()):
        if expires <= now:
            del _tickets[ticket]
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (user_id, target, now + TICKET_TTL)
    return ticket


def redeem(ticket: str, target: str) -> str | None:
    """The user the ticket was issued to, if it is live and for this target. Any ticket is spent on first use."""
    entry = _tickets.pop(ticket, None)
    if entry is None or entry[1] != target or entry[2] <= time.monotonic():
        return None
    return entry[0]
