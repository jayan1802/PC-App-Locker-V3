PC APP LOCKER V4.1 — WINDOWS 10/11
=================================

V4.1 changes
- Protected apps launch without PIN/password while applicable limits remain.
- Closing and reopening an app does not reset its daily usage.
- One parent/admin alphanumeric password; minimum 6 characters and must include letters and numbers.
- No separate PIN.
- Password required only for parent override after restrictions are reached and for changing credentials.
- Recovery key can be generated in Settings and used to reset a forgotten admin password.
- Application Rules uses a scrollable panel with Save/Cancel fixed at the bottom.
- V3 profile migration: the existing V3 password hash is carried forward as the V4.1 admin password; the old PIN is discarded.
- Per-Windows-user profile remains under %LOCALAPPDATA%\PCAppLocker\profile.json.

Build without Python on the target PC
1. Upload the contents of this folder to a GitHub repository's main branch.
2. Ensure .github/workflows/build-windows.yml is included at that exact path.
3. Open Actions and run "Build PC App Locker V4.1 for Windows".
4. Download artifact PCAppLockerV4.1-Windows.
5. Extract PCAppLockerV4.1.exe and run it on Windows.

Local build (requires Python)
Run build_exe.bat.

IMPORTANT LIMITATIONS
- This is a user-session monitor, not tamper-proof Windows enforcement. A local administrator or user able to terminate the process can bypass it.
- Process runtime is counted, not foreground interaction time.
- Some apps use launchers/helper processes. Roblox may spawn a separate player process; verify the configured executable matches the actual process.
- This build has passed Python syntax validation only. It has NOT been run or tested on Windows in this environment.
- Test with a non-admin Windows account and a short test limit before relying on it.
- Do not rely on it as the only parental-control or security mechanism. Use Windows Family Safety and standard child accounts for stronger controls.
- The recovery key is shown once when generated. Store it safely; anyone with it can reset the admin password.


V4.1 FIX
- Modal dialogs now acquire focus/grab only after controls are created, to avoid a disappearing/frozen Application Rules window.
- Application Rules window height is reduced for more screen compatibility.
- Dialog-open exceptions are surfaced instead of silently leaving the main window stuck.
