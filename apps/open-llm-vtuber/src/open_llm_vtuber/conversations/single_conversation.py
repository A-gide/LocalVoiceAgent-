from typing import Union, List, Dict, Any, Optional
import asyncio
import json
from loguru import logger
import numpy as np

from .conversation_utils import (
    create_batch_input,
    process_agent_output,
    send_conversation_start_signals,
    process_user_input,
    finalize_conversation_turn,
    cleanup_conversation,
    EMOJI_LIST,
)
from .types import WebSocketSend
from .tts_manager import TTSTaskManager
from .turn_context import TurnContext
from .latency_trace import LatencyTrace
from ..chat_history_manager import store_message
from ..service_context import ServiceContext
from ..agent.output_types import SentenceOutput, AudioOutput


async def process_single_conversation(
    context: ServiceContext,
    websocket_send: WebSocketSend,
    client_uid: str,
    user_input: Union[str, np.ndarray],
    images: Optional[List[Dict[str, Any]]] = None,
    session_emoji: str = np.random.choice(EMOJI_LIST),
    metadata: Optional[Dict[str, Any]] = None,
    turn_context: Optional[TurnContext] = None,
    latency_trace: Optional[LatencyTrace] = None,
) -> str:
    """Process a single-user conversation turn with 3-line turn isolation and non-blocking I/O.

    Args:
        context: Service context containing all configurations and engines
        websocket_send: WebSocket send function
        client_uid: Client unique identifier
        user_input: Text or audio input from user
        images: Optional list of image data
        session_emoji: Emoji identifier for the conversation
        metadata: Optional metadata for special processing flags
        turn_context: Optional TurnContext for stale turn suppression
        latency_trace: Optional LatencyTrace for unified micro-benchmarking

    Returns:
        str: Complete response text
    """
    tts_manager = TTSTaskManager()
    turn_id = turn_context.turn_id if turn_context else 0
    if turn_context:
        tts_manager.set_current_turn(turn_context.turn_id)
    context.tts_manager = tts_manager
    full_response = ""

    try:
        # Send initial signals
        await send_conversation_start_signals(websocket_send)
        logger.info(f"New Conversation Chain {session_emoji} (turn={turn_id}) started!")

        # Process user input with A5 early transcription reuse if available
        early_task = metadata.get("early_asr_task") if metadata else None
        early_samples = metadata.get("early_asr_samples", 0) if metadata else 0
        input_text = await process_user_input(
            user_input, context.asr_engine, websocket_send, early_task, early_samples
        )
        if latency_trace:
            latency_trace.mark_asr_done()

        from ..memory_router import (
            correct_scientific_terminology,
            is_temporal_query,
            query_screenpipe_history,
            archive_to_screenpipe,
            load_user_profile,
        )

        # Scientific terminology post-processing (Section 6)
        corrected_text, fixes = correct_scientific_terminology(input_text)
        if fixes:
            logger.info(f"Corrected input text: '{input_text}' -> '{corrected_text}'")

        # P1-1: Non-blocking fire-and-forget archive to Screenpipe
        asyncio.create_task(
            asyncio.to_thread(archive_to_screenpipe, corrected_text, "live", True)
        )

        # Deterministic Memory Router (Section 18, 19, 20) with P1-1 to_thread
        final_prompt_text = corrected_text
        if is_temporal_query(corrected_text):
            mem_res = await asyncio.to_thread(query_screenpipe_history, corrected_text)
            final_prompt_text = f"{mem_res['context_prompt']}\n\n用户当前提问：{corrected_text}"
            logger.info("Injected Screenpipe memory context into conversation prompt.")

        # User profile injection (Vocalis inspiration)
        user_prof = load_user_profile()
        if user_prof and not (metadata and metadata.get("proactive_speak")):
            prof_str = "【已知用户信息】\n" + "\n".join(f"- {k}: {v}" for k, v in user_prof.items())
            final_prompt_text = f"{prof_str}\n\n{final_prompt_text}"

        # Line of Defense 2: Check if turn was cancelled before calling LLM
        if turn_context and not turn_context.is_live():
            logger.info(f"🛑 Turn {turn_id} was cancelled before LLM generation. Suppressed.")
            return ""

        # Create batch input
        batch_input = create_batch_input(
            input_text=final_prompt_text,
            images=images,
            from_name=context.character_config.human_name,
            metadata=metadata,
        )

        # Store user message
        skip_history = metadata and metadata.get("skip_history", False)
        if context.history_uid and not skip_history:
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="human",
                content=corrected_text,
                name=context.character_config.human_name,
            )

        logger.info(f"User input (turn={turn_id}): {input_text}")
        if images:
            logger.info(f"With {len(images)} images")

        if latency_trace:
            latency_trace.mark_think_start()

        try:
            agent_output_stream = context.agent_engine.chat(batch_input)

            async for output_item in agent_output_stream:
                # Line of Defense 2: Check during stream generation
                if turn_context and not turn_context.is_live():
                    logger.info(f"🛑 Turn {turn_id} cancelled mid-stream. Breaking stream loop.")
                    break

                if latency_trace and latency_trace.t_first_token is None:
                    latency_trace.mark_first_token()

                if (
                    isinstance(output_item, dict)
                    and output_item.get("type") == "tool_call_status"
                ):
                    output_item["name"] = context.character_config.character_name
                    logger.debug(f"Sending tool status update: {output_item}")
                    await websocket_send(json.dumps(output_item))

                elif isinstance(output_item, (SentenceOutput, AudioOutput)):
                    response_part = await process_agent_output(
                        output=output_item,
                        character_config=context.character_config,
                        live2d_model=context.live2d_model,
                        tts_engine=context.tts_engine,
                        websocket_send=websocket_send,
                        tts_manager=tts_manager,
                        translate_engine=context.translate_engine,
                        turn_id=turn_id,
                        latency_trace=latency_trace,
                    )
                    response_part_str = (
                        str(response_part) if response_part is not None else ""
                    )
                    full_response += response_part_str
                else:
                    logger.warning(
                        f"Received unexpected item type from agent chat stream: {type(output_item)}"
                    )

        except Exception as e:
            logger.exception(f"Error processing agent response stream: {e}")
            await websocket_send(
                json.dumps(
                    {
                        "type": "error",
                        "message": f"Error processing agent response: {str(e)}",
                    }
                )
            )

        # Wait for any pending TTS tasks
        if tts_manager.task_list:
            await asyncio.gather(*[t for t in tts_manager.task_list if not t.done()])
            await websocket_send(json.dumps({"type": "backend-synth-complete"}))

        await finalize_conversation_turn(
            tts_manager=tts_manager,
            websocket_send=websocket_send,
            client_uid=client_uid,
        )

        if full_response:
            # P1-1: Non-blocking fire-and-forget archive
            asyncio.create_task(
                asyncio.to_thread(archive_to_screenpipe, full_response, "live", False)
            )

        if context.history_uid and full_response:
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="ai",
                content=full_response,
                name=context.character_config.character_name,
                avatar=context.character_config.avatar,
            )
            logger.info(f"AI response (turn={turn_id}): {full_response}")

        if latency_trace:
            latency_trace.mark_turn_complete()

        return full_response

    except asyncio.CancelledError:
        logger.info(f"🤡👍 Conversation {session_emoji} (turn={turn_id}) cancelled because interrupted.")
        raise
    except Exception as e:
        logger.error(f"Error in conversation chain: {e}")
        await websocket_send(
            json.dumps({"type": "error", "message": f"Conversation error: {str(e)}"})
        )
        raise
    finally:
        cleanup_conversation(tts_manager, session_emoji)
