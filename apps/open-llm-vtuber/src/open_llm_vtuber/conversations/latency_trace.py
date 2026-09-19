import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class LatencyTrace:
    """Unified latency tracing across conversation, LLM, and TTS pipelines.
    
    Inspired by voice2 logging_util standard markings.
    Accurately populates llm_ttft_ms, tts_chunk_ms, and ttfa_ms for live WebSocket turns.
    """
    turn_id: int
    t_trigger: float = field(default_factory=time.time)
    t_asr_done: Optional[float] = None
    t_think_start: Optional[float] = None
    t_first_token: Optional[float] = None
    t_tts_first_sample: Optional[float] = None
    t_playback_start: Optional[float] = None
    t_turn_complete: Optional[float] = None

    def mark_asr_done(self) -> None:
        self.t_asr_done = time.time()

    def mark_think_start(self) -> None:
        self.t_think_start = time.time()

    def mark_first_token(self) -> None:
        if self.t_first_token is None:
            self.t_first_token = time.time()

    def mark_tts_first_sample(self) -> None:
        if self.t_tts_first_sample is None:
            self.t_tts_first_sample = time.time()

    def mark_playback_start(self) -> None:
        if self.t_playback_start is None:
            self.t_playback_start = time.time()

    def mark_turn_complete(self) -> None:
        self.t_turn_complete = time.time()

    @property
    def llm_ttft_ms(self) -> Optional[float]:
        if self.t_first_token is not None and self.t_think_start is not None:
            return round((self.t_first_token - self.t_think_start) * 1000.0, 1)
        return None

    @property
    def tts_chunk_ms(self) -> Optional[float]:
        if self.t_tts_first_sample is not None and self.t_first_token is not None:
            return round((self.t_tts_first_sample - self.t_first_token) * 1000.0, 1)
        elif self.t_tts_first_sample is not None and self.t_think_start is not None:
            return round((self.t_tts_first_sample - self.t_think_start) * 1000.0, 1)
        return None

    @property
    def ttfa_ms(self) -> Optional[float]:
        ref = self.t_asr_done or self.t_trigger
        if self.t_playback_start is not None and ref is not None:
            return round((self.t_playback_start - ref) * 1000.0, 1)
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "llm_ttft_ms": self.llm_ttft_ms,
            "tts_chunk_ms": self.tts_chunk_ms,
            "ttfa_ms": self.ttfa_ms,
        }
