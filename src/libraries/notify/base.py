"""Base interfaces for notification backends."""

from abc import ABC, abstractmethod
from typing import Sequence


class Notifier(ABC):
    """Abstract notifier interface."""

    @abstractmethod
    def send(self, subject: str, message: str, recipients: Sequence[str]) -> bool:
        """Send a notification.

        Args:
            subject: Notification subject/title.
            message: Notification message body.
            recipients: Target recipients, if applicable for the notifier.

        Returns:
            ``True`` if the notification was sent successfully, otherwise ``False``.
        """

        raise NotImplementedError
