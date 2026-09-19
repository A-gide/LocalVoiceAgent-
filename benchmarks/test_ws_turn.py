import asyncio
import json
import time
import websockets

async def test_turn():
    uri = "ws://127.0.0.1:12393/client-ws"
    print(f"Connecting to {uri}...")
    t0 = time.time()
    async with websockets.connect(uri) as ws:
        print(f"Connected in {time.time()-t0:.3f}s")
        msg = {
            "type": "text-input",
            "text": "你好，请用一句话告诉我什么是络合反应？"
        }
        await ws.send(json.dumps(msg, ensure_ascii=False))
        print(f"Sent prompt: {msg['text']}")

        first_text_time = None
        first_audio_time = None
        audio_chunks = 0

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=20.0)
                data = json.loads(raw)
                msg_type = data.get("type")

                if msg_type == "full-text":
                    text = data.get("text", "")
                    if text not in ["Thinking...", "Connection established"]:
                        if first_text_time is None:
                            first_text_time = time.time()
                            print(f"[TTFT: {first_text_time - t0:.3f}s] Full text: {text}")
                        else:
                            print(f"Text update: {text}")

                elif msg_type == "audio":
                    audio_chunks += 1
                    if first_audio_time is None:
                        first_audio_time = time.time()
                        print(f"[TTFA: {first_audio_time - t0:.3f}s] Received first audio chunk (len: {len(data.get('audio', ''))})")
                    await ws.send(json.dumps({"type": "frontend-playback-complete"}))

                elif msg_type == "control":
                    ctrl = data.get("text")
                    print(f"Control signal: {ctrl}")
                    if ctrl == "conversation-chain-end":
                        print(f"Turn complete! Total time: {time.time()-t0:.3f}s, Audio chunks: {audio_chunks}")
                        break
            except asyncio.TimeoutError:
                print("Timeout waiting for server!")
                break

if __name__ == "__main__":
    asyncio.run(test_turn())
