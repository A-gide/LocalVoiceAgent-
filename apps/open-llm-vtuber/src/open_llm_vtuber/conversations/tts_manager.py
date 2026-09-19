import asyncio
import json
import re
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Tuple, Set
from loguru import logger

from ..agent.output_types import DisplayText, Actions
from ..live2d_model import Live2dModel
from ..tts.tts_interface import TTSInterface
from ..utils.stream_audio import prepare_audio_payload
from .types import WebSocketSend
from .latency_trace import LatencyTrace


class TTSTaskManager:
    """Manages TTS tasks and ensures ordered delivery to frontend while allowing parallel TTS generation.
    
    Includes Turn-based stale turn suppression (Defense Line 3) and drain(turn_id).
    """

    def __init__(self) -> None:
        self.task_list: List[asyncio.Task] = []
        self._lock = asyncio.Lock()
        # Queue to store ordered payloads: (payload, sequence_number, turn_id, latency_trace)
        self._payload_queue: asyncio.Queue[Tuple[Dict, int, int, Optional[LatencyTrace]]] = asyncio.Queue()
        # Task to handle sending payloads in order
        self._sender_task: Optional[asyncio.Task] = None
        # Counter for maintaining order
        self._sequence_counter = 0
        self._next_sequence_to_send = 0
        self._current_turn_id = 0
        self._cancelled_turns: Set[int] = set()

    def set_current_turn(self, turn_id: int) -> None:
        """Sets the active turn ID for this manager."""
        self._current_turn_id = turn_id

    def mark_turn_cancelled(self, turn_id: int) -> None:
        """Marks a turn as cancelled and drains its pending tasks."""
        self._cancelled_turns.add(turn_id)
        self.drain(turn_id)

    async def speak(
        self,
        tts_text: str,
        display_text: DisplayText,
        actions: Optional[Actions],
        live2d_model: Live2dModel,
        tts_engine: TTSInterface,
        websocket_send: WebSocketSend,
        turn_id: int = 0,
        latency_trace: Optional[LatencyTrace] = None,
    ) -> None:
        """Queue a TTS task while maintaining order of delivery and turn isolation."""
        if turn_id in self._cancelled_turns:
            logger.info(f"Refusing speak for cancelled turn {turn_id}")
            return

        if len(re.sub(r'[\s.,!?，。！？\'"』」）】\s]+', "", tts_text)) == 0:
            logger.debug("Empty TTS text, sending silent display payload")
            current_sequence = self._sequence_counter
            self._sequence_counter += 1

            if not self._sender_task or self._sender_task.done():
                self._sender_task = asyncio.create_task(
                    self._process_payload_queue(websocket_send)
                )

            await self._send_silent_payload(display_text, actions, current_sequence, turn_id, latency_trace)
            return

        logger.debug(
            f"🏃Queuing TTS task (turn={turn_id}, seq={self._sequence_counter}) for: '''{tts_text}''' (by {display_text.name})"
        )

        current_sequence = self._sequence_counter
        self._sequence_counter += 1

        if not self._sender_task or self._sender_task.done():
            self._sender_task = asyncio.create_task(
                self._process_payload_queue(websocket_send)
            )

        task = asyncio.create_task(
            self._process_tts(
                tts_text=tts_text,
                display_text=display_text,
                actions=actions,
                live2d_model=live2d_model,
                tts_engine=tts_engine,
                sequence_number=current_sequence,
                turn_id=turn_id,
                latency_trace=latency_trace,
            )
        )
        task._turn_id = turn_id
        self.task_list.append(task)

    async def _process_payload_queue(self, websocket_send: WebSocketSend) -> None:
        """Process and send payloads in correct order with stale-turn suppression (Line of Defense 3)."""
        buffered_payloads: Dict[int, Tuple[Dict, int, Optional[LatencyTrace]]] = {}

        while True:
            try:
                payload, sequence_number, item_turn_id, trace = await self._payload_queue.get()
                buffered_payloads[sequence_number] = (payload, item_turn_id, trace)

                while self._next_sequence_to_send in buffered_payloads:
                    next_payload, item_turn_id, trace = buffered_payloads.pop(self._next_sequence_to_send)

                    # Line of Defense 3: Stale turn suppression
                    if item_turn_id in self._cancelled_turns or (self._current_turn_id > 0 and item_turn_id < self._current_turn_id):
                        logger.info(f"🛑 Stale audio payload for turn {item_turn_id} suppressed at WebSocket gate (current={self._current_turn_id})")
                        self._next_sequence_to_send += 1
                        continue

                    # Populate latency trace on first playback chunk
                    if trace is not None and not getattr(trace, "_playback_started", False):
                        trace.mark_playback_start()
                        trace._playback_started = True
                        next_payload["trace"] = trace.to_dict()

                    await websocket_send(json.dumps(next_payload))
                    self._next_sequence_to_send += 1

                self._payload_queue.task_done()

            except asyncio.CancelledError:
                break

    async def _send_silent_payload(
        self,
        display_text: DisplayText,
        actions: Optional[Actions],
        sequence_number: int,
        turn_id: int,
        latency_trace: Optional[LatencyTrace] = None,
    ) -> None:
        """Queue a silent audio payload"""
        audio_payload = prepare_audio_payload(
            audio_path=None,
            display_text=display_text,
            actions=actions,
        )
        await self._payload_queue.put((audio_payload, sequence_number, turn_id, latency_trace))

    async def _process_tts(
        self,
        tts_text: str,
        display_text: DisplayText,
        actions: Optional[Actions],
        live2d_model: Live2dModel,
        tts_engine: TTSInterface,
        sequence_number: int,
        turn_id: int,
        latency_trace: Optional[LatencyTrace] = None,
    ) -> None:
        """Process TTS generation and queue the result for ordered delivery"""
        audio_file_path = None
        try:
            # If turn was cancelled before synthesis begins, abort early
            if turn_id in self._cancelled_turns:
                logger.info(f"Turn {turn_id} cancelled before TTS generation, skipping '''{tts_text}'''")
                return

            audio_file_path = await self._generate_audio(tts_engine, tts_text)

            # Record TTS First Sample time if this is the first chunk (sequence 0)
            if sequence_number == 0 and latency_trace is not None:
                latency_trace.mark_tts_first_sample()

            payload = prepare_audio_payload(
                audio_path=audio_file_path,
                display_text=display_text,
                actions=actions,
            )
            await self._payload_queue.put((payload, sequence_number, turn_id, latency_trace))

        except asyncio.CancelledError:
            logger.debug(f"TTS synthesis cancelled for turn {turn_id}, seq {sequence_number}")
            raise
        except Exception as e:
            logger.error(f"Error preparing audio payload: {e}")
            payload = prepare_audio_payload(
                audio_path=None,
                display_text=display_text,
                actions=actions,
            )
            await self._payload_queue.put((payload, sequence_number, turn_id, latency_trace))

        finally:
            if audio_file_path:
                tts_engine.remove_file(audio_file_path)
                logger.debug("Audio cache file cleaned.")

    async def _generate_audio(self, tts_engine: TTSInterface, text: str) -> str:
        """Generate audio file from text"""
        logger.debug(f"🏃Generating audio for '''{text}'''...")
        return await tts_engine.async_generate_audio(
            text=text,
            file_name_no_ext=f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}",
        )

    def drain(self, turn_id: Optional[int] = None) -> None:
        """Cancel tasks and purge queued items for a specific turn, protecting other members/turns."""
        if turn_id is not None:
            self._cancelled_turns.add(turn_id)
            remaining_tasks = []
            for task in self.task_list:
                if getattr(task, "_turn_id", None) == turn_id:
                    if not task.done():
                        task.cancel()
                else:
                    remaining_tasks.append(task)
            self.task_list = remaining_tasks
            logger.info(f"Drained TTS tasks for turn {turn_id}")
        else:
            self.clear()

    def clear(self) -> None:
        """Clear all pending tasks and reset state, cancelling all in-flight tasks."""
        for task in self.task_list:
            if not task.done():
                task.cancel()
        self.task_list.clear()
        if self._sender_task and not self._sender_task.done():
            self._sender_task.cancel()
        self._sequence_counter = 0
        self._next_sequence_to_send = 0
        self._payload_queue = asyncio.Queue()
