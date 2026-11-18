PC APP LOCKER V4.2 TEST — WINDOWS 10/11
======================================

PURPOSE
This is a TEST BUILD intended to verify the Application Rules window fix. It is not a production release.

V4.2 TEST changes
- Application Rules is now a non-modal window. It does not call grab_set() or wait_window().
- The main dashboard should remain interactive while Application Rules is open.
- Save is callback-based and updates the existing profile.
- Reopening an already-open rules window brings it to the front instead of creating duplicates.
- Tk callback and rules-window errors are logged to %LOCALAPPDATA%\PCAppLocker\app_locker.log.
- Uses a separate test profile folder (%LOCALAPPDATA%\PCAppLockerV42Test) so the existing V4/V4.1 profile is not read or modified.

TEST SAFETY
- Close all existing PC App Locker versions before testing this build.
- This test build uses its own profile folder and does not modify your live V4/V4.1 settings.
- Your existing profile remains at %LOCALAPPDATA%\PCAppLocker\profile.json. Do not delete it.
- Do not enable startup for this test build.
- The test build starts with a fresh test profile. Add Notepad first and use a short allowance; do not rely on it to enforce Roblox limits.
- If anything fails, close the test app and share app_locker.log.

BUILD
GitHub Actions workflow: .github/workflows/build-windows.yml
Artifact: PCAppLockerV4_2_TEST-Windows
Executable: PCAppLockerV4_2_TEST.exe

LIMITATIONS
This environment can validate source syntax and static behaviour but cannot certify Windows 10 GUI behaviour. The test must be run on the target Windows PC before this becomes a release. This is a user-session process monitor, not tamper-proof enforcement.
