from apps.trafalgar.web.events import EventBroadcaster

JOB_EVENTS = EventBroadcaster(max_buffer=64)


__all__ = [
    "JOB_EVENTS",
]
