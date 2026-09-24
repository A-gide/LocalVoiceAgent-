// Minimal RFC 6455 WebSocket client for the Rust bridge (v1.2.1 PR-007).
//
// Deliberately narrow scope:
//   - client role only; no extensions, no compression, no subprotocols
//   - RSV1..RSV3 must be zero on every incoming frame
//   - one frame may not exceed MAX_FRAME_BYTES (16 MiB)
//   - server frames must be unmasked; client frames are always masked
//   - no reconnect policy here, the bridge owns that
// It is not a general purpose WebSocket implementation. It exists so the Rust
// bridge can own the single authenticated socket to LVA Core without adding a
// crate: the offline registry has no WebSocket crate, and the only crypto
// provider available (ring) cannot build on this machine. SHA-1 and base64 are
// therefore implemented here, with known-answer tests in the module below.

use std::io::{ErrorKind, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::{Duration, Instant};

pub const MAX_FRAME_BYTES: usize = 16 * 1024 * 1024;
pub const MAX_HANDSHAKE_BYTES: usize = 16 * 1024;

const READ_POLL_MS: u64 = 20;
const WRITE_TIMEOUT_S: u64 = 5;

const OP_CONTINUATION: u8 = 0x0;
const OP_TEXT: u8 = 0x1;
const OP_BINARY: u8 = 0x2;
const OP_CLOSE: u8 = 0x8;
const OP_PING: u8 = 0x9;
const OP_PONG: u8 = 0xA;

const WS_GUID: &str = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

// ------------------------------------------------------------------ SHA-1

pub fn sha1(data: &[u8]) -> [u8; 20] {
    let mut h: [u32; 5] = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0];
    let mut msg: Vec<u8> = Vec::with_capacity(data.len() + 72);
    msg.extend_from_slice(data);
    let bit_len = (data.len() as u64).wrapping_mul(8);
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0x00);
    }
    msg.extend_from_slice(&bit_len.to_be_bytes());

    for chunk in msg.chunks(64) {
        let mut w = [0u32; 80];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[i * 4],
                chunk[i * 4 + 1],
                chunk[i * 4 + 2],
                chunk[i * 4 + 3],
            ]);
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }

        let mut a = h[0];
        let mut b = h[1];
        let mut c = h[2];
        let mut d = h[3];
        let mut e = h[4];
        for i in 0..80 {
            let (f, k) = if i < 20 {
                ((b & c) | ((!b) & d), 0x5A827999u32)
            } else if i < 40 {
                (b ^ c ^ d, 0x6ED9EBA1u32)
            } else if i < 60 {
                ((b & c) | (b & d) | (c & d), 0x8F1BBCDCu32)
            } else {
                (b ^ c ^ d, 0xCA62C1D6u32)
            };
            let tmp = a
                .rotate_left(5)
                .wrapping_add(f)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(w[i]);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = tmp;
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
    }

    let mut out = [0u8; 20];
    for (i, v) in h.iter().enumerate() {
        out[i * 4..i * 4 + 4].copy_from_slice(&v.to_be_bytes());
    }
    out
}

// ----------------------------------------------------------------- base64

const B64_ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

pub fn base64_encode(data: &[u8]) -> String {
    let mut out = String::with_capacity((data.len() + 2) / 3 * 4);
    for chunk in data.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = *chunk.get(1).unwrap_or(&0) as u32;
        let b2 = *chunk.get(2).unwrap_or(&0) as u32;
        let n = (b0 << 16) | (b1 << 8) | b2;
        out.push(B64_ALPHABET[(n >> 18) as usize & 0x3F] as char);
        out.push(B64_ALPHABET[(n >> 12) as usize & 0x3F] as char);
        if chunk.len() > 1 {
            out.push(B64_ALPHABET[(n >> 6) as usize & 0x3F] as char);
        } else {
            out.push('=');
        }
        if chunk.len() > 2 {
            out.push(B64_ALPHABET[n as usize & 0x3F] as char);
        } else {
            out.push('=');
        }
    }
    out
}

/// RFC 6455 section 4.2.2: the server proves it read the client key.
pub fn accept_for_key(key: &str) -> String {
    let mut joined = String::with_capacity(key.len() + WS_GUID.len());
    joined.push_str(key);
    joined.push_str(WS_GUID);
    base64_encode(&sha1(joined.as_bytes()))
}

// ------------------------------------------------------------------ frames

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FrameHeader {
    pub fin: bool,
    pub rsv: u8,
    pub opcode: u8,
    pub masked: bool,
    pub mask: [u8; 4],
    pub len: usize,
}

/// Parse one frame header at the start of buf.
///
/// Returns Ok(None) when buf does not yet hold a complete header. Returns an
/// error for a declared length above MAX_FRAME_BYTES, before any allocation.
pub fn parse_frame_header(buf: &[u8]) -> Result<Option<(FrameHeader, usize)>, String> {
    if buf.len() < 2 {
        return Ok(None);
    }
    let fin = buf[0] & 0x80 != 0;
    let rsv = (buf[0] >> 4) & 0x07;
    let opcode = buf[0] & 0x0F;
    let masked = buf[1] & 0x80 != 0;
    let short_len = (buf[1] & 0x7F) as usize;

    let (len, mut offset) = match short_len {
        126 => {
            if buf.len() < 4 {
                return Ok(None);
            }
            (u16::from_be_bytes([buf[2], buf[3]]) as usize, 4usize)
        }
        127 => {
            if buf.len() < 10 {
                return Ok(None);
            }
            let mut raw = [0u8; 8];
            raw.copy_from_slice(&buf[2..10]);
            let wide = u64::from_be_bytes(raw);
            if wide > MAX_FRAME_BYTES as u64 {
                return Err(format!("WebSocket frame declares {} bytes, above the {} byte cap", wide, MAX_FRAME_BYTES));
            }
            (wide as usize, 10usize)
        }
        n => (n, 2usize),
    };

    if len > MAX_FRAME_BYTES {
        return Err(format!("WebSocket frame declares {} bytes, above the {} byte cap", len, MAX_FRAME_BYTES));
    }

    let mut mask = [0u8; 4];
    if masked {
        if buf.len() < offset + 4 {
            return Ok(None);
        }
        mask.copy_from_slice(&buf[offset..offset + 4]);
        offset += 4;
    }

    Ok(Some((
        FrameHeader {
            fin,
            rsv,
            opcode,
            masked,
            mask,
            len,
        },
        offset + len,
    )))
}

pub fn apply_mask(payload: &mut [u8], mask: [u8; 4]) {
    for (i, byte) in payload.iter_mut().enumerate() {
        *byte ^= mask[i % 4];
    }
}

fn write_frame(stream: &mut TcpStream, opcode: u8, payload: &[u8], mask: [u8; 4]) -> Result<(), String> {
    if payload.len() > MAX_FRAME_BYTES {
        return Err(format!("refusing to send a {} byte frame", payload.len()));
    }
    let mut header: Vec<u8> = Vec::with_capacity(14);
    header.push(0x80 | opcode);
    let len = payload.len();
    if len < 126 {
        header.push(0x80 | len as u8);
    } else if len <= u16::MAX as usize {
        header.push(0x80 | 126);
        header.extend_from_slice(&(len as u16).to_be_bytes());
    } else {
        header.push(0x80 | 127);
        header.extend_from_slice(&(len as u64).to_be_bytes());
    }
    header.extend_from_slice(&mask);

    let mut body = payload.to_vec();
    apply_mask(&mut body, mask);

    stream
        .write_all(&header)
        .map_err(|e| format!("WebSocket write error: {}", e))?;
    stream
        .write_all(&body)
        .map_err(|e| format!("WebSocket write error: {}", e))?;
    stream
        .flush()
        .map_err(|e| format!("WebSocket flush error: {}", e))?;
    Ok(())
}

fn fresh_mask() -> [u8; 4] {
    // uuid v4 draws from the OS CSPRNG, which is already a dependency.
    let bytes = *uuid::Uuid::new_v4().as_bytes();
    [bytes[0], bytes[1], bytes[2], bytes[3]]
}

// ------------------------------------------------------------------ client

#[derive(Debug, Clone)]
pub enum WsMessage {
    Text(String),
    Close { code: Option<u16>, reason: String },
}

pub struct WsClient {
    stream: TcpStream,
    buf: Vec<u8>,
    frag: Vec<u8>,
    frag_opcode: Option<u8>,
    closed: bool,
}

impl WsClient {
    /// Perform the HTTP upgrade handshake and return a connected client.
    ///
    /// `extra_headers` carries the bearer token, which therefore never reaches
    /// argv, env, disk or the WebView.
    pub fn connect(
        addr: SocketAddr,
        host_header: &str,
        path: &str,
        extra_headers: &[(String, String)],
        timeout: Duration,
    ) -> Result<Self, String> {
        let stream = TcpStream::connect_timeout(&addr, timeout)
            .map_err(|e| format!("Cannot reach Core at {}: {}", addr, e))?;
        stream.set_nodelay(true).ok();
        stream
            .set_read_timeout(Some(Duration::from_millis(READ_POLL_MS)))
            .map_err(|e| format!("Cannot set read timeout: {}", e))?;
        stream
            .set_write_timeout(Some(Duration::from_secs(WRITE_TIMEOUT_S)))
            .map_err(|e| format!("Cannot set write timeout: {}", e))?;

        let key_bytes = *uuid::Uuid::new_v4().as_bytes();
        let key = base64_encode(&key_bytes);

        let mut req = String::with_capacity(320);
        req.push_str("GET ");
        req.push_str(path);
        req.push_str(" HTTP/1.1\r\n");
        req.push_str("Host: ");
        req.push_str(host_header);
        req.push_str("\r\n");
        req.push_str("Upgrade: websocket\r\n");
        req.push_str("Connection: Upgrade\r\n");
        req.push_str("Sec-WebSocket-Key: ");
        req.push_str(&key);
        req.push_str("\r\n");
        req.push_str("Sec-WebSocket-Version: 13\r\n");
        for (name, value) in extra_headers {
            req.push_str(name);
            req.push_str(": ");
            req.push_str(value);
            req.push_str("\r\n");
        }
        req.push_str("\r\n");

        let mut stream = stream;
        stream
            .write_all(req.as_bytes())
            .map_err(|e| format!("WebSocket handshake write error: {}", e))?;
        stream
            .flush()
            .map_err(|e| format!("WebSocket handshake flush error: {}", e))?;

        let (status, headers, leftover) = read_http_response(&mut stream, Instant::now() + timeout)?;
        if status != 101 {
            return Err(format!(
                "Core refused the WebSocket upgrade with HTTP {} (expected 101)",
                status
            ));
        }
        let accept = headers
            .iter()
            .find(|(name, _)| name.eq_ignore_ascii_case("sec-websocket-accept"))
            .map(|(_, value)| value.trim().to_string())
            .ok_or("Core upgrade response has no Sec-WebSocket-Accept")?;
        let expected = accept_for_key(&key);
        if accept != expected {
            return Err("Core WebSocket accept hash mismatch: refusing a spoofed server".to_string());
        }
        if headers
            .iter()
            .any(|(name, _)| name.eq_ignore_ascii_case("sec-websocket-extensions"))
        {
            return Err("Core negotiated a WebSocket extension that was never offered".to_string());
        }

        Ok(Self {
            stream,
            buf: leftover,
            frag: Vec::new(),
            frag_opcode: None,
            closed: false,
        })
    }

    pub fn send_text(&mut self, text: &str) -> Result<(), String> {
        if self.closed {
            return Err("WebSocket is closed".to_string());
        }
        write_frame(&mut self.stream, OP_TEXT, text.as_bytes(), fresh_mask())
    }

    pub fn send_close(&mut self, code: u16) -> Result<(), String> {
        if self.closed {
            return Ok(());
        }
        self.closed = true;
        let payload = code.to_be_bytes();
        write_frame(&mut self.stream, OP_CLOSE, &payload, fresh_mask())
    }

    /// Return the next application message, or Ok(None) when the deadline
    /// passes first. Control frames are handled internally.
    pub fn try_next_message(&mut self, deadline: Instant) -> Result<Option<WsMessage>, String> {
        loop {
            let mut consumed = 0usize;
            let mut completed: Option<WsMessage> = None;

            loop {
                let Some((header, total)) = parse_frame_header(&self.buf[consumed..])? else {
                    break;
                };
                if self.buf.len() - consumed < total {
                    break;
                }
                let body = self.buf[consumed + (total - header.len)..consumed + total].to_vec();
                consumed += total;

                if header.rsv != 0 {
                    return Err("WebSocket frame set RSV bits; extensions are not supported".to_string());
                }
                if header.masked {
                    return Err("Core sent a masked frame; RFC 6455 forbids server masking".to_string());
                }

                match header.opcode {
                    OP_PING => {
                        let mask = fresh_mask();
                        write_frame(&mut self.stream, OP_PONG, &body, mask)?;
                    }
                    OP_PONG => {}
                    OP_CLOSE => {
                        let code = if body.len() >= 2 {
                            Some(u16::from_be_bytes([body[0], body[1]]))
                        } else {
                            None
                        };
                        let reason = if body.len() > 2 {
                            String::from_utf8_lossy(&body[2..]).to_string()
                        } else {
                            String::new()
                        };
                        self.closed = true;
                        let _ = write_frame(&mut self.stream, OP_CLOSE, &body[..body.len().min(2)], fresh_mask());
                        completed = Some(WsMessage::Close { code, reason });
                    }
                    OP_BINARY => {
                        return Err("Core sent a binary frame; the bridge speaks JSON text only".to_string());
                    }
                    OP_CONTINUATION => {
                        if self.frag_opcode.is_none() {
                            return Err("WebSocket continuation frame without a start frame".to_string());
                        }
                        self.frag.extend_from_slice(&body);
                        if header.fin {
                            let opcode = self.frag_opcode.take().unwrap_or(OP_TEXT);
                            let payload = std::mem::take(&mut self.frag);
                            completed = Some(finish_message(opcode, payload)?);
                        }
                    }
                    OP_TEXT => {
                        if header.fin {
                            completed = Some(finish_message(OP_TEXT, body)?);
                        } else {
                            self.frag_opcode = Some(OP_TEXT);
                            self.frag.extend_from_slice(&body);
                        }
                    }
                    other => {
                        return Err(format!("WebSocket frame with unknown opcode {}", other));
                    }
                }

                if completed.is_some() {
                    break;
                }
            }

            if consumed > 0 {
                self.buf.drain(..consumed);
            }
            if let Some(msg) = completed {
                return Ok(Some(msg));
            }
            if Instant::now() >= deadline {
                return Ok(None);
            }
            self.fill()?;
        }
    }

    fn fill(&mut self) -> Result<(), String> {
        let mut chunk = [0u8; 8192];
        match self.stream.read(&mut chunk) {
            Ok(0) => Err("Core closed the WebSocket connection".to_string()),
            Ok(n) => {
                self.buf.extend_from_slice(&chunk[..n]);
                Ok(())
            }
            Err(e)
                if e.kind() == ErrorKind::WouldBlock
                    || e.kind() == ErrorKind::TimedOut
                    || e.kind() == ErrorKind::Interrupted =>
            {
                Ok(())
            }
            Err(e) => Err(format!("WebSocket read error: {}", e)),
        }
    }
}

fn finish_message(opcode: u8, payload: Vec<u8>) -> Result<WsMessage, String> {
    match opcode {
        OP_TEXT => String::from_utf8(payload)
            .map(WsMessage::Text)
            .map_err(|_| "Core sent invalid UTF-8 in a text frame".to_string()),
        other => Err(format!("unsupported message opcode {}", other)),
    }
}

/// Read the HTTP upgrade response. Bytes after the header block stay with the
fn read_http_response(
    stream: &mut TcpStream,
    deadline: Instant,
) -> Result<(u16, Vec<(String, String)>, Vec<u8>), String> {
    let mut raw: Vec<u8> = Vec::with_capacity(1024);
    let mut chunk = [0u8; 1024];
    loop {
        if let Some(end) = find_header_end(&raw) {
            let head = String::from_utf8_lossy(&raw[..end]).to_string();
            let leftover = raw[end + 4..].to_vec();
            return Ok((parse_status(&head)?, parse_headers(&head), leftover));
        }
        if Instant::now() >= deadline {
            return Err("Timed out waiting for the Core WebSocket upgrade response".to_string());
        }
        if raw.len() > MAX_HANDSHAKE_BYTES {
            return Err("Core WebSocket upgrade response header is oversized".to_string());
        }
        match stream.read(&mut chunk) {
            Ok(0) => return Err("Core closed the connection during the WebSocket handshake".to_string()),
            Ok(n) => raw.extend_from_slice(&chunk[..n]),
            Err(e)
                if e.kind() == ErrorKind::WouldBlock
                    || e.kind() == ErrorKind::TimedOut
                    || e.kind() == ErrorKind::Interrupted => {}
            Err(e) => return Err(format!("WebSocket handshake read error: {}", e)),
        }
    }
}

fn find_header_end(raw: &[u8]) -> Option<usize> {
    raw.windows(4).position(|w| w == b"\r\n\r\n")
}

fn parse_status(head: &str) -> Result<u16, String> {
    let line = head.lines().next().unwrap_or("");
    let mut parts = line.split_whitespace();
    let version = parts.next().unwrap_or("");
    if !version.starts_with("HTTP/1.") {
        return Err(format!("Core upgrade response is not HTTP/1.x: {}", line));
    }
    parts
        .next()
        .and_then(|code| code.parse::<u16>().ok())
        .ok_or_else(|| format!("Core upgrade response has no status code: {}", line))
}

fn parse_headers(head: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for line in head.lines().skip(1) {
        if let Some((name, value)) = line.split_once(':') {
            out.push((name.trim().to_string(), value.trim().to_string()));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(bytes: &[u8]) -> String {
        let mut out = String::with_capacity(bytes.len() * 2);
        for byte in bytes {
            out.push_str(&format!("{:02x}", byte));
        }
        out
    }

    #[test]
    fn sha1_matches_published_vectors() {
        assert_eq!(hex(&sha1(b"")), "da39a3ee5e6b4b0d3255bfef95601890afd80709");
        assert_eq!(hex(&sha1(b"abc")), "a9993e364706816aba3e25717850c26c9cd0d89d");
        assert_eq!(
            hex(&sha1(b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")),
            "84983e441c3bd26ebaae4aa1f95129e5e54670f1"
        );
        assert_eq!(
            hex(&sha1(&vec![b'a'; 1_000_000])),
            "34aa973cd4c4daa4f61eeb2bdbad27316534016f"
        );
    }

    #[test]
    fn base64_matches_rfc4648_vectors() {
        assert_eq!(base64_encode(b""), "");
        assert_eq!(base64_encode(b"f"), "Zg==");
        assert_eq!(base64_encode(b"fo"), "Zm8=");
        assert_eq!(base64_encode(b"foo"), "Zm9v");
        assert_eq!(base64_encode(b"foob"), "Zm9vYg==");
        assert_eq!(base64_encode(b"fooba"), "Zm9vYmE=");
        assert_eq!(base64_encode(b"foobar"), "Zm9vYmFy");
    }

    #[test]
    fn accept_key_matches_rfc6455_sample() {
        assert_eq!(
            accept_for_key("dGhlIHNhbXBsZSBub25jZQ=="),
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        );
    }

    #[test]
    fn short_unmasked_text_frame_parses() {
        let buf = [0x81u8, 0x03, b'a', b'b', b'c'];
        let (header, total) = parse_frame_header(&buf).unwrap().unwrap();
        assert!(header.fin);
        assert_eq!(header.rsv, 0);
        assert_eq!(header.opcode, OP_TEXT);
        assert!(!header.masked);
        assert_eq!(header.len, 3);
        assert_eq!(total, 5);
    }

    #[test]
    fn extended_lengths_parse() {
        let mut buf = vec![0x81u8, 126, 0x01, 0x00];
        buf.extend(vec![0u8; 256]);
        let (header, total) = parse_frame_header(&buf).unwrap().unwrap();
        assert_eq!(header.len, 256);
        assert_eq!(total, 4 + 256);

        let mut buf = vec![0x82u8, 127];
        buf.extend_from_slice(&70000u64.to_be_bytes());
        buf.extend(vec![0u8; 70000]);
        let (header, total) = parse_frame_header(&buf).unwrap().unwrap();
        assert_eq!(header.opcode, OP_BINARY);
        assert_eq!(header.len, 70000);
        assert_eq!(total, 10 + 70000);
    }

    #[test]
    fn masked_frame_exposes_mask_and_payload_offset() {
        let buf = [0x81u8, 0x80 | 0x02, 0x11, 0x22, 0x33, 0x44, 0xAA, 0xBB];
        let (header, total) = parse_frame_header(&buf).unwrap().unwrap();
        assert!(header.masked);
        assert_eq!(header.mask, [0x11, 0x22, 0x33, 0x44]);
        assert_eq!(header.len, 2);
        assert_eq!(total, 8);
    }

    #[test]
    fn oversized_frame_is_rejected_before_allocation() {
        let mut buf = vec![0x81u8, 127];
        buf.extend_from_slice(&((MAX_FRAME_BYTES as u64) + 1).to_be_bytes());
        let err = parse_frame_header(&buf).unwrap_err();
        assert!(err.contains("above the"), "unexpected error: {}", err);
    }

    #[test]
    fn incomplete_headers_are_not_errors() {
        assert!(parse_frame_header(&[]).unwrap().is_none());
        assert!(parse_frame_header(&[0x81]).unwrap().is_none());
        assert!(parse_frame_header(&[0x81, 126, 0x00]).unwrap().is_none());
        assert!(parse_frame_header(&[0x81, 127, 0, 0, 0]).unwrap().is_none());
        assert!(parse_frame_header(&[0x81, 0x80 | 0x02, 0x11]).unwrap().is_none());
    }

    #[test]
    fn masking_round_trips() {
        let mask = [0x37u8, 0xFA, 0x21, 0x3D];
        let original = b"Hello".to_vec();
        let mut buf = original.clone();
        apply_mask(&mut buf, mask);
        assert_ne!(buf, original);
        apply_mask(&mut buf, mask);
        assert_eq!(buf, original);
    }
}
