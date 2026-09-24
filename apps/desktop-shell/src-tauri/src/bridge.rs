// Single authenticated Rust <-> LVA Core bridge (v1.2.1 PR-007).
//
// Before R07 the shell reached Core over two HTTP endpoints: a POST to
// /api/command per command and a 250 ms poll of /api/events as the event
// channel. Both are gone. This module owns the one WebSocket to Core:
//
//   - the port and the bearer token stay inside Rust; the WebView only sees
//     Tauri commands and the lva://event stream
//   - every command is correlated by command_id and never replayed
//   - an event sequence gap or a runtime_instance_id change forces a fresh
//     snapshot, which is published to the WebView as a runtime.snapshot event
//   - a dropped connection is re-established with bounded backoff
//
// Threading: send_command blocks until Core answers, so it must never run on the
// WebView IPC thread. lib.rs awaits it through tauri::async_runtime::spawn_blocking
// and the worker thread below owns the socket.

use std::collections::HashMap;
use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender, TryRecvError};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};
use uuid::Uuid;

use crate::core_supervisor::CoreInstance;
use crate::ws::{WsClient, WsMessage};

/// Tauri event the WebView listens on; the payload is an EventEnvelope.
pub const EVENT_NAME: &str = "lva://event";

const CONNECT_TIMEOUT: Duration = Duration::from_secs(5);
const COMMAND_TIMEOUT: Duration = Duration::from_secs(10);
const READ_TICK: Duration = Duration::from_millis(20);
const IDLE_WAIT: Duration = Duration::from_millis(200);
const RECONNECT_MIN: Duration = Duration::from_millis(500);
const RECONNECT_MAX: Duration = Duration::from_secs(10);

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BridgeState {
    pub is_connected: bool,
    pub runtime_instance_id: Option<String>,
}

/// A command awaiting its command_result.
enum Pending {
    Caller(Sender<Value>),
    /// Internal resync: the result is turned into a runtime.snapshot event.
    Snapshot,
}

struct BridgeInner {
    instance: Option<CoreInstance>,
    connected: bool,
    runtime_instance_id: Option<String>,
    last_sequence: i64,
    pending: HashMap<String, Pending>,
    shutdown: bool,
}

#[derive(Clone)]
pub struct CoreBridge {
    inner: Arc<Mutex<BridgeInner>>,
    app: Arc<Mutex<Option<AppHandle>>>,
    outbound: Arc<Mutex<Sender<String>>>,
    outbound_rx: Arc<Mutex<Receiver<String>>>,
    wake: Arc<Mutex<Sender<()>>>,
    wake_rx: Arc<Mutex<Receiver<()>>>,
    started: Arc<Mutex<bool>>,
    // Test-only sink: emit() is otherwise unobservable without a live AppHandle.
    #[cfg(test)]
    emitted: Arc<Mutex<Vec<Value>>>,
}

impl CoreBridge {
    pub fn new() -> Self {
        let (outbound, outbound_rx) = mpsc::channel();
        let (wake, wake_rx) = mpsc::channel();
        Self {
            inner: Arc::new(Mutex::new(BridgeInner {
                instance: None,
                connected: false,
                runtime_instance_id: None,
                last_sequence: 0,
                pending: HashMap::new(),
                shutdown: false,
            })),
            app: Arc::new(Mutex::new(None)),
            outbound: Arc::new(Mutex::new(outbound)),
            outbound_rx: Arc::new(Mutex::new(outbound_rx)),
            wake: Arc::new(Mutex::new(wake)),
            wake_rx: Arc::new(Mutex::new(wake_rx)),
            started: Arc::new(Mutex::new(false)),
            #[cfg(test)]
            emitted: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Hand the bridge an AppHandle so it can publish lva://event.
    pub fn attach_app(&self, app: AppHandle) {
        *self.app.lock().unwrap() = Some(app);
    }

    /// Adopt a freshly spawned Core. Commands bound to a previous instance are
    /// dropped here: a restarted Core must never see a replayed command.
    pub fn set_instance(&self, instance: CoreInstance) {
        {
            let mut inner = self.inner.lock().unwrap();
            inner.connected = false;
            inner.runtime_instance_id = Some(instance.runtime_instance_id.clone());
            inner.last_sequence = 0;
            inner.pending.clear();
            inner.instance = Some(instance);
        }
        if let Ok(wake) = self.wake.lock() {
            let _ = wake.send(());
        }
    }

    /// Forget the current Core (stop talking to it, keep the worker alive).
    pub fn clear_instance(&self) {
        let mut inner = self.inner.lock().unwrap();
        inner.instance = None;
        inner.connected = false;
        inner.last_sequence = 0;
        inner.pending.clear();
    }

    /// Stop the worker. Used on application exit and by the bridge tests.
    pub fn shutdown(&self) {
        {
            let mut inner = self.inner.lock().unwrap();
            inner.shutdown = true;
            inner.connected = false;
            inner.pending.clear();
        }
        if let Ok(wake) = self.wake.lock() {
            let _ = wake.send(());
        }
    }
    pub fn get_state(&self) -> BridgeState {
        let inner = self.inner.lock().unwrap();
        BridgeState {
            is_connected: inner.connected,
            runtime_instance_id: inner.runtime_instance_id.clone(),
        }
    }

    /// Spawn the single worker thread that owns the Core socket.
    pub fn start(&self) {
        {
            let mut started = self.started.lock().unwrap();
            if *started {
                return;
            }
            *started = true;
        }
        let bridge = self.clone();
        if let Err(e) = std::thread::Builder::new()
            .name("lva-core-bridge".to_string())
            .spawn(move || bridge.run())
        {
            log::error!("[Bridge] Failed to spawn the Core bridge thread: {}", e);
        }
    }

    /// Send one command and wait for its correlated result.
    ///
    /// Blocking: call it from a blocking worker (see lib.rs), never from the
    /// WebView IPC thread.
    pub fn send_command(&self, mut cmd: Value) -> Result<Value, String> {
        let key = command_key(&mut cmd)?;
        let (tx, rx) = mpsc::channel();
        {
            let mut inner = self.inner.lock().unwrap();
            if inner.instance.is_none() {
                return Err("LVA Core is not running".to_string());
            }
            if !inner.connected {
                return Err("LVA Core bridge is not connected".to_string());
            }
            inner.pending.insert(key.clone(), Pending::Caller(tx));
        }
        let text = match serde_json::to_string(&cmd) {
            Ok(text) => text,
            Err(e) => {
                self.inner.lock().unwrap().pending.remove(&key);
                return Err(format!("Core command is not serialisable: {}", e));
            }
        };
        if self.outbound.lock().unwrap().send(text).is_err() {
            self.inner.lock().unwrap().pending.remove(&key);
            return Err("LVA Core bridge is not running".to_string());
        }
        match rx.recv_timeout(COMMAND_TIMEOUT) {
            Ok(value) => Ok(value),
            Err(RecvTimeoutError::Timeout) => {
                self.inner.lock().unwrap().pending.remove(&key);
                Err("Timed out waiting for the Core command result".to_string())
            }
            Err(RecvTimeoutError::Disconnected) => {
                Err("LVA Core connection dropped before the command completed".to_string())
            }
        }
    }

    // ------------------------------------------------------------ worker side

    fn run(&self) {
        let mut backoff = RECONNECT_MIN;
        loop {
            if self.is_shutdown() {
                return;
            }
            let Some(instance) = self.current_instance() else {
                self.wait_for_wake(IDLE_WAIT);
                continue;
            };
            let (port, token) = instance;
            match self.connect(port, &token) {
                Ok(mut client) => {
                    backoff = RECONNECT_MIN;
                    self.mark_connected(true);
                    log::info!(
                        "[Bridge] Connected to LVA Core on 127.0.0.1:{} over the authenticated WebSocket",
                        port
                    );
                    self.request_snapshot();
                    let reason = self.pump(&mut client, port, &token);
                    self.mark_disconnected();
                    self.drain_outbound();
                    log::warn!("[Bridge] Core WebSocket ended: {}", reason);
                }
                Err(e) => {
                    self.mark_disconnected();
                    self.drain_outbound();
                    log::warn!("[Bridge] Core WebSocket connect failed: {}", e);
                }
            }
            if self.instance_changed(port, &token) {
                backoff = RECONNECT_MIN;
            } else {
                // Interruptible: shutdown() and set_instance() wake the worker so
                // a replaced Core is picked up without waiting out the backoff.
                self.wait_for_wake(backoff);
                backoff = (backoff * 2).min(RECONNECT_MAX);
            }
        }
    }

    fn connect(&self, port: u16, token: &str) -> Result<WsClient, String> {
        let addr = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), port);
        let headers = vec![("Authorization".to_string(), format!("Bearer {}", token))];
        WsClient::connect(
            addr,
            &format!("127.0.0.1:{}", port),
            "/ws",
            &headers,
            CONNECT_TIMEOUT,
        )
    }

    /// Read frames until the connection ends; returns why it ended.
    fn pump(&self, client: &mut WsClient, port: u16, token: &str) -> String {
        loop {
            if self.is_shutdown() {
                let _ = client.send_close(1000);
                return "bridge shutdown".to_string();
            }
            if self.instance_changed(port, token) {
                let _ = client.send_close(1000);
                return "Core instance was replaced; reconnecting".to_string();
            }
            match client.try_next_message(Instant::now() + READ_TICK) {
                Ok(Some(WsMessage::Text(text))) => self.handle_text(&text),
                Ok(Some(WsMessage::Close { code, reason })) => {
                    return format!(
                        "closed by Core (code {:?}{})",
                        code,
                        if reason.is_empty() {
                            String::new()
                        } else {
                            format!(", {}", reason)
                        }
                    );
                }
                Ok(None) => {}
                Err(e) => return e,
            }
            if let Err(e) = self.flush_outbound(client) {
                return e;
            }
        }
    }

    fn flush_outbound(&self, client: &mut WsClient) -> Result<(), String> {
        loop {
            let next = self.outbound_rx.lock().unwrap().try_recv();
            match next {
                Ok(text) => client.send_text(&text)?,
                Err(TryRecvError::Empty) => return Ok(()),
                Err(TryRecvError::Disconnected) => return Ok(()),
            }
        }
    }

    fn handle_text(&self, text: &str) {
        let value: Value = match serde_json::from_str(text) {
            Ok(value) => value,
            Err(e) => {
                log::warn!("[Bridge] Core sent a non-JSON text frame: {}", e);
                return;
            }
        };

        match value.get("kind").and_then(|k| k.as_str()) {
            Some("command_result") => {
                self.resolve_command(&value);
                return;
            }
            Some("hello") => {
                log::info!(
                    "[Bridge] Core hello received (mode={})",
                    value
                        .pointer("/state/mode")
                        .and_then(|m| m.as_str())
                        .unwrap_or("?")
                );
                return;
            }
            Some("pong") | Some("ask_result") => return,
            _ => {}
        }

        let sequence = value.get("sequence").and_then(|s| s.as_i64());
        let payload_type = value.pointer("/payload/type").and_then(|t| t.as_str());
        if sequence.is_none() || payload_type.is_none() {
            // The untyped PL.Event channel (kind + ts + flat data) has no shape in
            // the generated EventEnvelope contract, so it is logged and not forwarded.
            log::debug!(
                "[Bridge] Un-typed Core event dropped (kind={:?})",
                value.get("kind")
            );
            return;
        }

        let mut resync = false;
        let mut instance_changed = false;
        {
            let mut inner = self.inner.lock().unwrap();
            if let Some(seq) = sequence {
                if inner.last_sequence > 0 && seq > inner.last_sequence + 1 {
                    log::warn!(
                        "[Bridge] Event gap detected: expected {}, received {}",
                        inner.last_sequence + 1,
                        seq
                    );
                    resync = true;
                }
                inner.last_sequence = seq;
            }
            if let Some(incoming) = value.get("runtime_instance_id").and_then(|v| v.as_str()) {
                if inner.runtime_instance_id.as_deref() != Some(incoming) {
                    log::warn!(
                        "[Bridge] Core runtime_instance_id changed to {}; dropping stale commands",
                        incoming
                    );
                    inner.runtime_instance_id = Some(incoming.to_string());
                    inner.pending.clear();
                    inner.last_sequence = sequence.unwrap_or(0);
                    instance_changed = true;
                }
            }
        }
        if resync || instance_changed {
            self.request_snapshot();
        }
        self.emit(value);
    }

    fn resolve_command(&self, value: &Value) {
        let key = match value.get("command_id").and_then(|v| v.as_str()) {
            Some(key) => key.to_string(),
            None => {
                log::warn!("[Bridge] command_result without a string command_id was dropped");
                return;
            }
        };
        let entry = self.inner.lock().unwrap().pending.remove(&key);
        match entry {
            Some(Pending::Caller(tx)) => {
                let _ = tx.send(value.clone());
            }
            Some(Pending::Snapshot) => self.publish_snapshot(value),
            None => log::debug!("[Bridge] command_result for an unknown or expired command was dropped"),
        }
    }

    /// Ask Core for a full snapshot; the result is published as a
    /// runtime.snapshot event so the store adopts authoritative state.
    fn request_snapshot(&self) {
        let id = Uuid::new_v4().to_string();
        {
            let mut inner = self.inner.lock().unwrap();
            if inner.instance.is_none() || !inner.connected {
                return;
            }
            inner.pending.insert(id.clone(), Pending::Snapshot);
        }
        let cmd = json!({
            "schema_version": "1.0",
            "command_id": id,
            "type": "runtime.get_snapshot",
            "payload": { "type": "runtime.get_snapshot" },
        });
        if self.outbound.lock().unwrap().send(cmd.to_string()).is_err() {
            self.inner.lock().unwrap().pending.remove(&id);
        }
    }

    fn publish_snapshot(&self, result: &Value) {
        let status = result.get("status").and_then(|s| s.as_str()).unwrap_or("");
        if status != "applied" && status != "duplicate" {
            log::warn!("[Bridge] Snapshot resync was not applied (status={})", status);
            return;
        }
        let Some(state) = result.get("data") else {
            log::warn!("[Bridge] Snapshot resync carried no data");
            return;
        };
        let runtime_instance_id = self
            .inner
            .lock()
            .unwrap()
            .runtime_instance_id
            .clone()
            .unwrap_or_default();
        // Same shape Core uses for a runtime.snapshot event. sequence 0 marks it
        // as a bridge-side resync rather than a sequenced Core event.
        let envelope = json!({
            "schema_version": "1.0",
            "type": "runtime.snapshot",
            "source": "core.bridge",
            "sequence": 0,
            "runtime_instance_id": runtime_instance_id,
            "payload": { "type": "runtime.snapshot", "state": state },
        });
        self.emit(envelope);
    }

    fn emit(&self, envelope: Value) {
        #[cfg(test)]
        self.emitted.lock().unwrap().push(envelope.clone());
        let app = self.app.lock().unwrap();
        if let Some(handle) = app.as_ref() {
            if let Err(e) = handle.emit(EVENT_NAME, envelope) {
                log::warn!("[Bridge] Failed to emit {}: {}", EVENT_NAME, e);
            }
        }
    }

    /// The connection parameters of the current Core. CoreInstance is not Clone
    /// (it owns the bootstrap stdin handle), so only what the worker needs is
    /// copied out.
    fn current_instance(&self) -> Option<(u16, String)> {
        let inner = self.inner.lock().unwrap();
        inner
            .instance
            .as_ref()
            .map(|instance| (instance.port, instance.token.clone()))
    }

    fn instance_changed(&self, port: u16, token: &str) -> bool {
        let inner = self.inner.lock().unwrap();
        match inner.instance.as_ref() {
            Some(current) => current.port != port || current.token != token,
            None => true,
        }
    }

    fn is_shutdown(&self) -> bool {
        self.inner.lock().unwrap().shutdown
    }

    fn mark_connected(&self, connected: bool) {
        self.inner.lock().unwrap().connected = connected;
    }

    /// A connection ended: waiting callers fail instead of being replayed later.
    fn mark_disconnected(&self) {
        let mut inner = self.inner.lock().unwrap();
        inner.connected = false;
        inner.pending.clear();
    }

    fn drain_outbound(&self) {
        let rx = self.outbound_rx.lock().unwrap();
        while rx.try_recv().is_ok() {}
    }

    fn wait_for_wake(&self, timeout: Duration) {
        let rx = self.wake_rx.lock().unwrap();
        let _ = rx.recv_timeout(timeout);
    }
}

impl Default for CoreBridge {
    fn default() -> Self {
        Self::new()
    }
}

/// Read the command_id, injecting one when the caller left it out, so the result
/// can be correlated even though Core defaults a missing id to a fresh UUID.
fn command_key(cmd: &mut Value) -> Result<String, String> {
    let obj = cmd
        .as_object_mut()
        .ok_or_else(|| "Core command must be a JSON object".to_string())?;
    if let Some(existing) = obj.get("command_id").and_then(|v| v.as_str()) {
        if !existing.is_empty() {
            return Ok(existing.to_string());
        }
    }
    let id = Uuid::new_v4().to_string();
    obj.insert("command_id".to_string(), Value::String(id.clone()));
    Ok(id)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::io::ErrorKind;
    use std::net::{TcpListener, TcpStream};
    use std::sync::atomic::{AtomicBool, Ordering};

    const RUNTIME_ID: &str = "aaaaaaaa-0000-4000-8000-000000000001";
    const OTHER_RUNTIME_ID: &str = "bbbbbbbb-0000-4000-8000-000000000002";

    /// Server side of RFC 6455, narrowed to what these tests need: one unmasked
    /// text frame per message, control frames ignored on read.
    struct StubConn {
        stream: TcpStream,
        buf: Vec<u8>,
    }

    impl StubConn {
        fn read_text(&mut self, timeout: Duration) -> Result<Option<String>, String> {
            let deadline = Instant::now() + timeout;
            loop {
                if let Some((header, total)) = crate::ws::parse_frame_header(&self.buf)? {
                    if self.buf.len() >= total {
                        let mut body = self.buf[total - header.len..total].to_vec();
                        self.buf.drain(..total);
                        if header.masked {
                            crate::ws::apply_mask(&mut body, header.mask);
                        }
                        if header.opcode == 0x1 {
                            return String::from_utf8(body).map(Some).map_err(|e| e.to_string());
                        }
                        continue;
                    }
                }
                if Instant::now() >= deadline {
                    return Ok(None);
                }
                let mut chunk = [0u8; 8192];
                match self.stream.read(&mut chunk) {
                    Ok(0) => return Err("client closed the socket".to_string()),
                    Ok(n) => self.buf.extend_from_slice(&chunk[..n]),
                    Err(e) if e.kind() == ErrorKind::WouldBlock || e.kind() == ErrorKind::TimedOut => {}
                    Err(e) => return Err(e.to_string()),
                }
            }
        }

        fn send_text(&mut self, text: &str) -> Result<(), String> {
            let payload = text.as_bytes();
            let mut frame = vec![0x81u8];
            if payload.len() < 126 {
                frame.push(payload.len() as u8);
            } else {
                frame.push(126);
                frame.extend_from_slice(&(payload.len() as u16).to_be_bytes());
            }
            frame.extend_from_slice(payload);
            self.stream.write_all(&frame).map_err(|e| e.to_string())
        }

        fn send_close(&mut self, code: u16) -> Result<(), String> {
            let mut frame = vec![0x88u8, 0x02];
            frame.extend_from_slice(&code.to_be_bytes());
            self.stream.write_all(&frame).map_err(|e| e.to_string())
        }
    }

    /// Accept `connections` sockets on a real loopback port and run `script` per
    /// connection after the WebSocket upgrade.
    fn stub_core<F>(connections: usize, script: F) -> (u16, std::thread::JoinHandle<()>)
    where
        F: Fn(usize, &mut StubConn) + Send + Sync + 'static,
    {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind the stub core");
        let port = listener.local_addr().unwrap().port();
        let handle = std::thread::spawn(move || {
            for index in 0..connections {
                let Ok((mut stream, _)) = listener.accept() else {
                    return;
                };
                stream
                    .set_read_timeout(Some(Duration::from_millis(20)))
                    .ok();
                if upgrade(&mut stream).is_err() {
                    return;
                }
                let mut conn = StubConn {
                    stream,
                    buf: Vec::new(),
                };
                script(index, &mut conn);
            }
        });
        (port, handle)
    }

    fn upgrade(stream: &mut TcpStream) -> Result<(), String> {
        let mut raw: Vec<u8> = Vec::new();
        let mut chunk = [0u8; 1024];
        let deadline = Instant::now() + Duration::from_secs(5);
        while raw.windows(4).position(|w| w == b"\r\n\r\n").is_none() {
            if Instant::now() >= deadline {
                return Err("timed out reading the client handshake".to_string());
            }
            match stream.read(&mut chunk) {
                Ok(0) => return Err("client closed during the handshake".to_string()),
                Ok(n) => raw.extend_from_slice(&chunk[..n]),
                Err(e) if e.kind() == ErrorKind::WouldBlock || e.kind() == ErrorKind::TimedOut => {}
                Err(e) => return Err(e.to_string()),
            }
        }
        let head = String::from_utf8_lossy(&raw).to_string();
        let key = head
            .lines()
            .find_map(|line| {
                let (name, value) = line.split_once(':')?;
                if name.trim().eq_ignore_ascii_case("sec-websocket-key") {
                    Some(value.trim().to_string())
                } else {
                    None
                }
            })
            .ok_or_else(|| "client handshake carried no Sec-WebSocket-Key".to_string())?;
        let response = format!(
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n\r\n",
            crate::ws::accept_for_key(&key)
        );
        stream
            .write_all(response.as_bytes())
            .map_err(|e| e.to_string())
    }

    fn instance(port: u16) -> CoreInstance {
        CoreInstance {
            port,
            token: "test-token".to_string(),
            nonce: "test-nonce".to_string(),
            runtime_instance_id: RUNTIME_ID.to_string(),
            bootstrap_stdin: None,
        }
    }

    fn hello() -> String {
        json!({
            "kind": "hello",
            "state": { "mode": "standby", "runtime_instance_id": RUNTIME_ID },
        })
        .to_string()
    }

    fn typed_event(sequence: i64, runtime_id: &str) -> String {
        json!({
            "schema_version": "1.0",
            "type": "mode.changed",
            "source": "core.runtime",
            "sequence": sequence,
            "runtime_instance_id": runtime_id,
            "payload": { "type": "mode.changed", "new_mode": "active", "resume_mode": null },
        })
        .to_string()
    }

    fn command_result(id: &str, status: &str, data: Value) -> String {
        json!({
            "kind": "command_result",
            "command_id": id,
            "status": status,
            "snapshot_version": 3,
            "revisions": { "runtime_control": 2, "hub_binding": 0 },
            "data": data,
        })
        .to_string()
    }

    fn wait_until(timeout: Duration, predicate: impl Fn() -> bool) -> bool {
        let deadline = Instant::now() + timeout;
        while Instant::now() < deadline {
            if predicate() {
                return true;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        predicate()
    }

    fn emitted(bridge: &CoreBridge) -> Vec<Value> {
        bridge.emitted.lock().unwrap().clone()
    }

    /// Reply to the snapshot request the bridge sends on every connect.
    fn answer_snapshot(conn: &mut StubConn, mode: &str) -> Result<(), String> {
        let request = conn
            .read_text(Duration::from_secs(5))?
            .ok_or_else(|| "no snapshot request arrived".to_string())?;
        let value: Value = serde_json::from_str(&request).map_err(|e| e.to_string())?;
        assert_eq!(value["type"], "runtime.get_snapshot");
        let id = value["command_id"].as_str().unwrap_or_default().to_string();
        conn.send_text(&command_result(&id, "applied", json!({ "mode": mode })))?;
        Ok(())
    }

    #[test]
    fn connect_requests_a_snapshot_and_publishes_it() {
        let (port, server) = stub_core(1, |_index, conn| {
            conn.send_text(&hello()).unwrap();
            answer_snapshot(conn, "standby").unwrap();
            std::thread::sleep(Duration::from_millis(200));
        });

        let bridge = CoreBridge::new();
        bridge.set_instance(instance(port));
        bridge.start();

        assert!(wait_until(Duration::from_secs(5), || !emitted(&bridge).is_empty()));
        let events = emitted(&bridge);
        let snapshot = events
            .iter()
            .find(|event| event["type"] == "runtime.snapshot")
            .expect("a runtime.snapshot event");
        assert_eq!(snapshot["payload"]["state"]["mode"], "standby");
        assert_eq!(snapshot["sequence"], 0);
        assert_eq!(snapshot["source"], "core.bridge");
        bridge.shutdown();
        server.join().unwrap();
    }

    #[test]
    fn commands_are_correlated_by_command_id() {
        let (port, server) = stub_core(1, |_index, conn| {
            conn.send_text(&hello()).unwrap();
            answer_snapshot(conn, "standby").unwrap();
            let command = conn
                .read_text(Duration::from_secs(5))
                .unwrap()
                .expect("the caller command");
            let value: Value = serde_json::from_str(&command).unwrap();
            assert_eq!(value["type"], "runtime.set_mode");
            let id = value["command_id"].as_str().unwrap().to_string();
            conn.send_text(&command_result(&id, "applied", json!({ "mode": "active" })))
                .unwrap();
            std::thread::sleep(Duration::from_millis(200));
        });

        let bridge = CoreBridge::new();
        bridge.set_instance(instance(port));
        bridge.start();
        assert!(wait_until(Duration::from_secs(5), || bridge
            .get_state()
            .is_connected));

        let result = bridge
            .send_command(json!({
                "schema_version": "1.0",
                "command_id": "11111111-1111-4111-8111-111111111111",
                "type": "runtime.set_mode",
                "payload": { "type": "runtime.set_mode", "mode": "active" },
            }))
            .expect("the correlated command result");
        assert_eq!(result["status"], "applied");
        assert_eq!(result["data"]["mode"], "active");
        assert_eq!(result["snapshot_version"], 3);
        assert_eq!(result["revisions"]["runtime_control"], 2);
        bridge.shutdown();
        server.join().unwrap();
    }

    #[test]
    fn an_event_gap_triggers_a_snapshot_resync() {
        let (port, server) = stub_core(1, |_index, conn| {
            conn.send_text(&hello()).unwrap();
            answer_snapshot(conn, "standby").unwrap();
            conn.send_text(&typed_event(1, RUNTIME_ID)).unwrap();
            conn.send_text(&typed_event(5, RUNTIME_ID)).unwrap();
            answer_snapshot(conn, "active").unwrap();
            std::thread::sleep(Duration::from_millis(200));
        });

        let bridge = CoreBridge::new();
        bridge.set_instance(instance(port));
        bridge.start();

        assert!(wait_until(Duration::from_secs(5), || emitted(&bridge).len() >= 3));
        let events = emitted(&bridge);
        let sequences: Vec<i64> = events
            .iter()
            .filter_map(|event| event["sequence"].as_i64())
            .collect();
        assert_eq!(sequences, vec![0, 1, 5, 0], "sequences: {:?}", sequences);
        let resync = events.last().unwrap();
        assert_eq!(resync["type"], "runtime.snapshot");
        assert_eq!(resync["payload"]["state"]["mode"], "active");
        bridge.shutdown();
        server.join().unwrap();
    }

    #[test]
    fn a_runtime_instance_change_drops_pending_and_resyncs() {
        let (port, server) = stub_core(1, |_index, conn| {
            conn.send_text(&hello()).unwrap();
            answer_snapshot(conn, "standby").unwrap();
            conn.send_text(&typed_event(1, OTHER_RUNTIME_ID)).unwrap();
            answer_snapshot(conn, "standby").unwrap();
            std::thread::sleep(Duration::from_millis(200));
        });

        let bridge = CoreBridge::new();
        bridge.set_instance(instance(port));
        bridge.start();

        assert!(wait_until(Duration::from_secs(5), || emitted(&bridge).len() >= 3));
        let events = emitted(&bridge);
        let changed = events
            .iter()
            .find(|event| event["runtime_instance_id"] == OTHER_RUNTIME_ID)
            .expect("the event carrying the new runtime instance");
        assert_eq!(changed["payload"]["type"], "mode.changed");
        assert_eq!(
            bridge.get_state().runtime_instance_id.as_deref(),
            Some(OTHER_RUNTIME_ID)
        );
        assert_eq!(events.last().unwrap()["type"], "runtime.snapshot");
        bridge.shutdown();
        server.join().unwrap();
    }

    #[test]
    fn untyped_core_events_are_not_forwarded() {
        let (port, server) = stub_core(1, |_index, conn| {
            conn.send_text(&hello()).unwrap();
            answer_snapshot(conn, "standby").unwrap();
            conn.send_text(&json!({ "kind": "transcript", "ts": 1.0, "text": "hi" }).to_string())
                .unwrap();
            std::thread::sleep(Duration::from_millis(400));
        });

        let bridge = CoreBridge::new();
        bridge.set_instance(instance(port));
        bridge.start();
        assert!(wait_until(Duration::from_secs(5), || emitted(&bridge).len() >= 1));
        std::thread::sleep(Duration::from_millis(300));
        let events = emitted(&bridge);
        assert_eq!(events.len(), 1, "events: {:?}", events);
        assert_eq!(events[0]["type"], "runtime.snapshot");
        bridge.shutdown();
        server.join().unwrap();
    }

    #[test]
    fn a_dropped_connection_is_re_established() {
        // Connection 0 hangs up after its snapshot; connection 1 stays open until
        // the test releases it, so "is_connected" here means the second socket.
        let release = Arc::new(AtomicBool::new(false));
        let release_for_stub = Arc::clone(&release);
        let (port, server) = stub_core(2, move |index, conn| {
            conn.send_text(&hello()).unwrap();
            answer_snapshot(conn, "standby").unwrap();
            if index == 0 {
                conn.send_close(1001).unwrap();
                return;
            }
            let deadline = Instant::now() + Duration::from_secs(10);
            while !release_for_stub.load(Ordering::SeqCst) && Instant::now() < deadline {
                std::thread::sleep(Duration::from_millis(20));
            }
        });

        let bridge = CoreBridge::new();
        bridge.set_instance(instance(port));
        bridge.start();
        assert!(wait_until(Duration::from_secs(5), || bridge
            .get_state()
            .is_connected));
        // The worker retried on its own: the second snapshot arrived over a new
        // socket, without any new set_instance call.
        assert!(wait_until(Duration::from_secs(5), || emitted(&bridge).len() >= 2));
        assert!(wait_until(Duration::from_secs(5), || bridge
            .get_state()
            .is_connected));
        assert_eq!(emitted(&bridge).len(), 2, "one snapshot per connection");
        release.store(true, Ordering::SeqCst);
        bridge.shutdown();
        server.join().unwrap();
    }

    #[test]
    fn a_command_without_a_running_core_is_rejected() {
        let bridge = CoreBridge::new();
        let err = bridge
            .send_command(json!({ "type": "runtime.get_snapshot" }))
            .expect_err("no Core is running");
        assert_eq!(err, "LVA Core is not running");
        bridge.shutdown();
    }

    #[test]
    fn a_spoofed_accept_hash_is_refused() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = std::thread::spawn(move || {
            let Ok((mut stream, _)) = listener.accept() else {
                return;
            };
            stream
                .set_read_timeout(Some(Duration::from_millis(20)))
                .ok();
            let mut raw: Vec<u8> = Vec::new();
            let mut chunk = [0u8; 1024];
            let deadline = Instant::now() + Duration::from_secs(5);
            while raw.windows(4).position(|w| w == b"\r\n\r\n").is_none() {
                if Instant::now() >= deadline {
                    return;
                }
                match stream.read(&mut chunk) {
                    Ok(0) => return,
                    Ok(n) => raw.extend_from_slice(&chunk[..n]),
                    Err(_) => {}
                }
            }
            let spoofed = "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: AAAAfakeacceptAAAAAAAAAAAAAAAAAAA=\r\n\r\n";
            let _ = stream.write_all(spoofed.as_bytes());
            std::thread::sleep(Duration::from_millis(300));
        });

        let bridge = CoreBridge::new();
        bridge.set_instance(instance(port));
        bridge.start();
        std::thread::sleep(Duration::from_millis(700));
        assert!(
            !bridge.get_state().is_connected,
            "a server that cannot prove the accept hash must never be trusted"
        );
        assert!(emitted(&bridge).is_empty());
        bridge.shutdown();
        server.join().unwrap();
    }
    /// Interop probe against a real uvicorn server running the real lva.server
    /// /ws route. Run manually:
    ///   cargo test --lib -- --ignored --nocapture live_core_interop_probe
    /// The server is started by scratch/probe_r07_ws_server.py, which stubs only
    /// VoiceCore (this machine has no audio devices and no MeloTTS model).
    #[test]
    #[ignore = "needs scratch/probe_r07_ws_server.py running"]
    fn live_core_interop_probe() {
        let port: u16 = std::env::var("LVA_PROBE_PORT")
            .expect("LVA_PROBE_PORT")
            .parse()
            .expect("numeric LVA_PROBE_PORT");
        let token = std::env::var("LVA_PROBE_TOKEN").expect("LVA_PROBE_TOKEN");

        let bridge = CoreBridge::new();
        bridge.set_instance(instance_with_token(port, &token));
        bridge.start();
        assert!(wait_until(Duration::from_secs(10), || bridge
            .get_state()
            .is_connected));
        eprintln!("[probe] connected to the live /ws route on port {}", port);

        let snapshot = bridge
            .send_command(json!({
                "schema_version": "1.0",
                "type": "runtime.get_snapshot",
                "payload": { "type": "runtime.get_snapshot" },
            }))
            .expect("the live snapshot result");
        eprintln!(
            "[probe] snapshot status={} version={} mode={}",
            snapshot["status"], snapshot["snapshot_version"], snapshot["data"]["mode"]
        );
        assert_eq!(snapshot["status"], "applied");
        let live_runtime_id = snapshot["data"]["runtime_instance_id"]
            .as_str()
            .expect("runtime_instance_id in the live snapshot")
            .to_string();
        eprintln!("[probe] live runtime_instance_id={}", live_runtime_id);

        // A stale CAS precondition must come back as a Core-side rejection.
        let stale = bridge
            .send_command(json!({
                "schema_version": "1.0",
                "type": "runtime.set_mode",
                "payload": { "type": "runtime.set_mode", "mode": "live" },
                "precondition": { "aggregate": "runtime_control", "revision": 999 },
            }))
            .expect("a rejected result is still a correlated result");
        eprintln!(
            "[probe] stale set_mode status={} code={}",
            stale["status"], stale["error"]["code"]
        );
        assert_eq!(stale["status"], "rejected");

        let applied = bridge
            .send_command(json!({
                "schema_version": "1.0",
                "type": "runtime.set_mode",
                "payload": { "type": "runtime.set_mode", "mode": "live" },
                "precondition": { "aggregate": "runtime_control", "revision": 0 },
            }))
            .expect("the applied result");
        eprintln!(
            "[probe] set_mode status={} snapshot_version={}",
            applied["status"], applied["snapshot_version"]
        );

        // The real /ws route enforces token and Origin; a wrong token must be
        // refused by production code, not by the probe server.
        let bad = CoreBridge::new();
        bad.set_instance(instance_with_token(port, "wrong-token"));
        bad.start();
        std::thread::sleep(Duration::from_millis(1500));
        eprintln!("[probe] wrong-token connected={}", bad.get_state().is_connected);
        assert!(
            !bad.get_state().is_connected,
            "the real /ws route must refuse a wrong token"
        );
        bad.shutdown();

        // Restart rotate: a replaced Core (new port, new token, new runtime
        // instance) must be adopted by the same bridge and its snapshot
        // republished, with no replay of anything the old Core never answered.
        let port2: u16 = std::env::var("LVA_PROBE_PORT2")
            .expect("LVA_PROBE_PORT2")
            .parse()
            .expect("numeric LVA_PROBE_PORT2");
        let token2 = std::env::var("LVA_PROBE_TOKEN2").expect("LVA_PROBE_TOKEN2");
        bridge.set_instance(instance_with_token(port2, &token2));
        let rotated = wait_until(Duration::from_secs(15), || {
            emitted(&bridge).iter().any(|event| {
                event["payload"]["type"] == "runtime.snapshot"
                    && event["payload"]["state"]["runtime_instance_id"]
                        .as_str()
                        .map(|id| id != live_runtime_id.as_str())
                        .unwrap_or(false)
            })
        });
        assert!(rotated, "the bridge must adopt the restarted Core");
        let rotated_snapshot = emitted(&bridge)
            .into_iter()
            .filter(|event| event["payload"]["type"] == "runtime.snapshot")
            .last()
            .expect("a snapshot from the restarted Core");
        eprintln!(
            "[probe] rotated snapshot instance={} mode={}",
            rotated_snapshot["payload"]["state"]["runtime_instance_id"],
            rotated_snapshot["payload"]["state"]["mode"]
        );
        assert!(bridge.get_state().is_connected);

        let events = emitted(&bridge);
        eprintln!("[probe] events seen = {}", events.len());
        for event in events.iter().take(4) {
            eprintln!("[probe]   event type={} sequence={}", event["type"], event["sequence"]);
        }
        bridge.shutdown();
    }

    fn instance_with_token(port: u16, token: &str) -> CoreInstance {
        CoreInstance {
            port,
            token: token.to_string(),
            nonce: "probe-nonce".to_string(),
            runtime_instance_id: RUNTIME_ID.to_string(),
            bootstrap_stdin: None,
        }
    }
}
