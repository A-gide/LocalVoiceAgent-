import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TurnContext:
    """Represents a conversational turn lifecycle and stale-state tracking.
    
    Inspired by voice2/turn_context.py.
    Provides three lines of defense against overlapping conversational turns:
    1. Input entry cancellation (handle_conversation_trigger)
    2. Model stream checkpointing (single_conversation)
    3. Final WebSocket transmission gate (tts_manager)
    """
    turn_id: int
    client_uid: str
    created_at: float = field(default_factory=time.monotonic)
    cancelled: bool = False
    stale: bool = False

    def is_live(self) -> bool:
        """Returns True if the turn is neither cancelled nor marked stale."""
        return not self.cancelled and not self.stale

    def mark_cancelled(self) -> None:
        """Mark this turn as cancelled (e.g. by barge-in or new input arrival)."""
        self.cancelled = True

    def mark_stale(self) -> None:
        """Mark this turn as superseded by a newer turn."""
        self.stale = True
