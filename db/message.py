import threading

_message_queue = []
_event_queue = []
_event_cond = threading.Condition()


def push_message(text, kind="success"):
    _message_queue.append({"text": text, "kind": kind})


def pop_messages():
    msgs = list(_message_queue)
    _message_queue.clear()
    return msgs


def push_event(event_type, data):
    with _event_cond:
        _event_queue.append({"type": event_type, "data": data})
        _event_cond.notify_all()
