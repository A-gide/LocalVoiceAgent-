//! Persisted pet-window geometry (PR-031).
//!
//! Frozen plan §8.3 / risk L1704: after a crash or restart the window must come
//! back where the user left it, and a position saved on a monitor that no longer
//! exists must be clamped onto one that does, with Reset Position available.
//!
//! This is a separate file from `settings.json` on purpose.  Window geometry is
//! not a user preference the settings UI edits, and putting it in `AppSettings`
//! would make every window move a settings write -- bumping `settings_revision`
//! and invalidating a settings edit the user was in the middle of.
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// A saved window position and size, in logical coordinates.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct WindowGeometry {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

impl WindowGeometry {
    /// A record is usable only when every field is finite and the size is positive.
    ///
    /// The file is user data that a hand edit, an older version or a truncated
    /// write can leave malformed; a bad record must degrade to "no saved
    /// position" rather than place the window somewhere unusable.
    pub fn is_usable(&self) -> bool {
        [self.x, self.y, self.width, self.height]
            .iter()
            .all(|v| v.is_finite())
            && self.width > 0.0
            && self.height > 0.0
    }
}

pub fn geometry_path() -> PathBuf {
    // The per-user runtime root PR-003 established, next to settings.json.
    crate::paths::get_app_dir().join("window_geometry.json")
}

/// Read the saved geometry, or `None` when there is nothing usable to restore.
///
/// Never propagates an error: a missing, unreadable or malformed file simply means
/// the caller falls back to its default placement.  Failing startup because a
/// convenience file was corrupt would leave the user with no window at all.
pub fn load_geometry() -> Option<WindowGeometry> {
    let path = geometry_path();
    let raw = std::fs::read_to_string(&path).ok()?;
    let parsed: WindowGeometry = serde_json::from_str(&raw).ok()?;
    if parsed.is_usable() {
        Some(parsed)
    } else {
        log::warn!("[Geometry] saved window geometry is not usable; ignoring it");
        None
    }
}

/// Persist the window geometry, refusing to store a record that cannot be used.
pub fn save_geometry(geometry: WindowGeometry) -> Result<(), String> {
    if !geometry.is_usable() {
        return Err("refusing to persist unusable window geometry".to_string());
    }
    let path = geometry_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let json = serde_json::to_string_pretty(&geometry).map_err(|e| e.to_string())?;
    std::fs::write(&path, json).map_err(|e| e.to_string())
}

/// Forget the saved geometry, so the next start uses the default placement.
pub fn clear_geometry() -> Result<(), String> {
    let path = geometry_path();
    if path.exists() {
        std::fs::remove_file(&path).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_normal_record_is_usable() {
        let g = WindowGeometry { x: 100.0, y: 200.0, width: 360.0, height: 520.0 };
        assert!(g.is_usable());
    }

    #[test]
    fn a_non_finite_or_degenerate_record_is_not_usable() {
        let cases = [
            WindowGeometry { x: f64::NAN, y: 0.0, width: 10.0, height: 10.0 },
            WindowGeometry { x: 0.0, y: f64::INFINITY, width: 10.0, height: 10.0 },
            WindowGeometry { x: 0.0, y: 0.0, width: 0.0, height: 10.0 },
            WindowGeometry { x: 0.0, y: 0.0, width: 10.0, height: -5.0 },
        ];
        for case in cases {
            assert!(!case.is_usable(), "{:?} must not be usable", case);
        }
    }

    #[test]
    fn a_negative_position_is_still_a_valid_record() {
        // A monitor to the left of the primary has negative coordinates; the
        // record is legitimate, and clamping happens against the live monitor
        // list rather than by rejecting negative numbers here.
        let g = WindowGeometry { x: -1800.0, y: 100.0, width: 360.0, height: 520.0 };
        assert!(g.is_usable());
    }

    #[test]
    fn unusable_geometry_is_never_written() {
        let bad = WindowGeometry { x: 0.0, y: 0.0, width: 0.0, height: 0.0 };
        assert!(save_geometry(bad).is_err(), "a degenerate record must be refused");
    }
}
