; NSIS Custom Hooks for LocalVoiceAgent Pet (lva-pet)
; Requirement 2 & 3: Clean registry autostart on uninstall, never touch external Adopted services.

!macro NSIS_HOOK_PREINSTALL
  ; Pre-installation hook: Verification of environment
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Post-installation hook: Ensure user AppData directory template if needed
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; Clean up autostart registry entry if user had enabled it
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "LocalVoiceAgentPet"
  ; Boundary defense: We explicitly NEVER kill or touch external processes (llama-server.exe, screenpipe.exe)
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; Post-uninstallation cleanup complete
!macroend
