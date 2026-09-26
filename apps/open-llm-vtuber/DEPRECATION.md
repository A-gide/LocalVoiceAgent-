# Subsystem Deprecation Notice: Open-LLM-VTuber

> **Status: DEPRECATED & FROZEN (PR-033 / PR-036)**  
> **Superseded by: LVA Core (`src/lva`) & Desktop UI Live2D Embed (`apps/desktop-ui/src/features/character/live2d`)**

## Architecture Decision Records
- **ADR-001 / ADR-010**: Single Conversation Authority and Secure IPC.
  - LVA Core is the sole authority for Session, Turn, Floor, Interrupt, ASR/LLM/TTS scheduling, and Memory routing.
  - OLV conversation contexts, memory routers, and separate LLM/TTS schedulers are frozen and no longer execute turns or write to memory.
- **PR-034**: Direct Live2D WebGL renderer and assets are embedded directly into `apps/desktop-ui`, eliminating the requirement for an independent Python renderer process.
- **PR-036**: Removal of OLV background process and migration to direct desktop-ui client architecture.
