import asyncio
import json
import time
import websockets

async def test_barge_in():
    uri = "ws://127.0.0.1:12393/client-ws"
    print(f"Connecting to {uri}...")
    async with websockets.connect(uri) as ws:
        print("Connected!")
        # Start a long query
        msg = {
            "type": "text-input",
            "text": "请详细为我讲解有机化学中的Baeyer-Villiger氧化反应机理，包括迁移基团的迁移能力差异和过氧酸作用步骤，至少说五句话。"
        }
        await ws.send(json.dumps(msg, ensure_ascii=False))
        print("Sent prompt for long speech...")

        audio_received = 0
        interrupted = False
        t_interrupt_sent = None
        barge_in_latency = None

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                data = json.loads(raw)
                msg_type = data.get("type")

                if msg_type == "audio":
                    audio_received += 1
                    print(f"Audio chunk {audio_received} received.")
                    
                    if audio_received == 1 and not interrupted:
                        print("AI started speaking! Now triggering user BARGE-IN...")
                        t_interrupt_sent = time.time()
                        interrupt_msg = {
                            "type": "interrupt-signal",
                            "heard_response": "等等，我不是这个意思。"
                        }
                        await ws.send(json.dumps(interrupt_msg, ensure_ascii=False))
                        interrupted = True
                    elif interrupted:
                        print("WARNING: Audio received AFTER interrupt!")

                elif msg_type == "interrupt-signal":
                    barge_in_latency = (time.time() - t_interrupt_sent) * 1000
                    print(f"Server acknowledged interruption! Barge-in latency: {barge_in_latency:.1f}ms")
                    break

                elif msg_type == "control" and data.get("text") == "conversation-chain-end":
                    if interrupted:
                        if barge_in_latency is None and t_interrupt_sent:
                            barge_in_latency = (time.time() - t_interrupt_sent) * 1000
                        print(f"Conversation chain terminated! Barge-in latency: {barge_in_latency:.1f}ms")
                    break

            except asyncio.TimeoutError:
                print("Timeout waiting for server event.")
                break

        print(f"Test complete. Total audio chunks played before cut: {audio_received}, Barge-in response: {barge_in_latency:.1f}ms")
        return barge_in_latency

if __name__ == "__main__":
    asyncio.run(test_barge_in())
