import asyncio
import json
from typing import Dict, Optional, Callable

import numpy as np
from fastapi import WebSocket
from loguru import logger

from ..chat_group import ChatGroupManager
from ..chat_history_manager import store_message
from ..service_context import ServiceContext
from .group_conversation import process_group_conversation
from .single_conversation import process_single_conversation
from .conversation_utils import EMOJI_LIST
from .types import GroupConversationState
from .turn_context import TurnContext
from .latency_trace import LatencyTrace
from prompts import prompt_loader

# Monotonic turn counters and active turn contexts per client
turn_counters: Dict[str, int] = {}
active_turn_contexts: Dict[str, TurnContext] = {}


async def handle_conversation_trigger(
    msg_type: str,
    data: dict,
    client_uid: str,
    context: ServiceContext,
    websocket: WebSocket,
    client_contexts: Dict[str, ServiceContext],
    client_connections: Dict[str, WebSocket],
    chat_group_manager: ChatGroupManager,
    received_data_buffers: Dict[str, np.ndarray],
    current_conversation_tasks: Dict[str, Optional[asyncio.Task]],
    broadcast_to_group: Callable,
) -> None:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}

    if msg_type == "ai-speak-signal":
        custom_text = data.get("text")
        tier = data.get("tier")
        if custom_text and custom_text.strip():
            user_input = custom_text.strip()
        elif tier == 1:
            user_input = "用户有一段时间没有说话了，请自然而简短地跟进询问一句（不要超过20字）。"
        elif tier == 2:
            user_input = "用户依然没有回应，请极其简短地表示你随时都在，然后保持安静（不要超过15字）。"
        else:
            try:
                # Get proactive speak prompt from config
                prompt_name = "proactive_speak_prompt"
                prompt_file = context.system_config.tool_prompts.get(prompt_name)
                if prompt_file:
                    user_input = prompt_loader.load_util(prompt_file)
                else:
                    logger.warning("Proactive speak prompt not configured, using default")
                    user_input = "Please say something."
            except Exception as e:
                logger.error(f"Error loading proactive speak prompt: {e}")
                user_input = "Please say something."

        # Add metadata to indicate this is a proactive speak request
        # that should be skipped in both memory and history
        metadata = {
            "proactive_speak": True,
            "skip_memory": True,  # Skip storing in AI's internal memory
            "skip_history": True,  # Skip storing in local conversation history
        }

        await websocket.send_text(
            json.dumps(
                {
                    "type": "full-text",
                    "text": "AI wants to speak something...",
                }
            )
        )
    elif msg_type == "text-input":
        user_input = data.get("text", "")
    else:  # mic-audio-end
        user_input = received_data_buffers[client_uid]
        received_data_buffers[client_uid] = np.array([])

    images = data.get("images")
    session_emoji = np.random.choice(EMOJI_LIST)

    group = chat_group_manager.get_client_group(client_uid)
    if group and len(group.members) > 1:
        # Use group_id as task key for group conversations
        task_key = group.group_id
        if (
            task_key not in current_conversation_tasks
            or current_conversation_tasks[task_key].done()
        ):
            logger.info(f"Starting new group conversation for {task_key}")

            current_conversation_tasks[task_key] = asyncio.create_task(
                process_group_conversation(
                    client_contexts=client_contexts,
                    client_connections=client_connections,
                    broadcast_func=broadcast_to_group,
                    group_members=group.members,
                    initiator_client_uid=client_uid,
                    user_input=user_input,
                    images=images,
                    session_emoji=session_emoji,
                    metadata=metadata,
                )
            )
    else:
        # Line of Defense 1: Cancel any existing active conversation task for client (Floor Owner / Stale turn suppression)
        old_task = current_conversation_tasks.get(client_uid)
        if old_task and not old_task.done():
            logger.info(f"🛑 Cancelling previous conversation task for client {client_uid} before starting new turn")
            old_task.cancel()  # Never await! (A4)
            if client_uid in active_turn_contexts:
                active_turn_contexts[client_uid].mark_cancelled()
            if hasattr(context, "tts_manager") and context.tts_manager:
                old_turn_id = active_turn_contexts[client_uid].turn_id if client_uid in active_turn_contexts else None
                context.tts_manager.drain(old_turn_id)

        # Monotonic turn_id assignment
        new_turn_id = turn_counters.get(client_uid, 0) + 1
        turn_counters[client_uid] = new_turn_id
        turn_ctx = TurnContext(turn_id=new_turn_id, client_uid=client_uid)
        active_turn_contexts[client_uid] = turn_ctx

        # Unified latency trace
        trace = LatencyTrace(turn_id=new_turn_id)

        # Use client_uid as task key for individual conversations
        current_conversation_tasks[client_uid] = asyncio.create_task(
            process_single_conversation(
                context=context,
                websocket_send=websocket.send_text,
                client_uid=client_uid,
                user_input=user_input,
                images=images,
                session_emoji=session_emoji,
                metadata=metadata,
                turn_context=turn_ctx,
                latency_trace=trace,
            )
        )


async def handle_individual_interrupt(
    client_uid: str,
    current_conversation_tasks: Dict[str, Optional[asyncio.Task]],
    context: ServiceContext,
    heard_response: str,
):
    if client_uid in active_turn_contexts:
        active_turn_contexts[client_uid].mark_cancelled()
        if hasattr(context, "tts_manager") and context.tts_manager:
            context.tts_manager.drain(active_turn_contexts[client_uid].turn_id)

    if client_uid in current_conversation_tasks:
        task = current_conversation_tasks[client_uid]
        if task and not task.done():
            task.cancel()
            logger.info("🛑 Conversation task was successfully interrupted")

        try:
            context.agent_engine.handle_interrupt(heard_response)
        except Exception as e:
            logger.error(f"Error handling interrupt: {e}")

        if context.history_uid:
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="ai",
                content=heard_response,
                name=context.character_config.character_name,
                avatar=context.character_config.avatar,
            )
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="system",
                content="[Interrupted by user]",
            )


async def handle_group_interrupt(
    group_id: str,
    heard_response: str,
    current_conversation_tasks: Dict[str, Optional[asyncio.Task]],
    chat_group_manager: ChatGroupManager,
    client_contexts: Dict[str, ServiceContext],
    broadcast_to_group: Callable,
) -> None:
    """Handles interruption for a group conversation"""
    task = current_conversation_tasks.get(group_id)
    if not task or task.done():
        return

    # Get state and speaker info before cancellation
    state = GroupConversationState.get_state(group_id)
    current_speaker_uid = state.current_speaker_uid if state else None

    # Get context from current speaker
    context = None
    group = chat_group_manager.get_group_by_id(group_id)
    if current_speaker_uid:
        context = client_contexts.get(current_speaker_uid)
        logger.info(f"Found current speaker context for {current_speaker_uid}")
    if not context and group and group.members:
        logger.warning(f"No context found for group {group_id}, using first member")
        context = client_contexts.get(next(iter(group.members)))

    # Now cancel the task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info(f"🛑 Group conversation {group_id} cancelled successfully.")

    current_conversation_tasks.pop(group_id, None)
    GroupConversationState.remove_state(group_id)  # Clean up state after we've used it

    # Store messages with speaker info
    if context and group:
        for member_uid in group.members:
            if member_uid in client_contexts:
                try:
                    member_ctx = client_contexts[member_uid]
                    member_ctx.agent_engine.handle_interrupt(heard_response)
                    store_message(
                        conf_uid=member_ctx.character_config.conf_uid,
                        history_uid=member_ctx.history_uid,
                        role="ai",
                        content=heard_response,
                        name=context.character_config.character_name,
                        avatar=context.character_config.avatar,
                    )
                    store_message(
                        conf_uid=member_ctx.character_config.conf_uid,
                        history_uid=member_ctx.history_uid,
                        role="system",
                        content="[Interrupted by user]",
                    )
                except Exception as e:
                    logger.error(f"Error handling interrupt for {member_uid}: {e}")

    await broadcast_to_group(
        list(group.members),
        {
            "type": "interrupt-signal",
            "text": "conversation-interrupted",
        },
    )
