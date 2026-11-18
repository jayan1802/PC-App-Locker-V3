PC APP LOCKER V3 — WINDOWS 10/11
=================================

WHAT'S NEW
----------
* Modern dashboard using CustomTkinter.
* Per-Windows-user profile stored in that user's %LOCALAPPDATA%\PCAppLocker.
* Selected application protection with PIN + password.
* Per-app daily allowance and per-session limit.
* Allowed time schedule, including overnight windows.
* Separate weekday and weekend daily allowances.
* Warnings before time expires (configured threshold and 1-minute warning).
* Override sessions are included in usage reports.
* Optional continuous-use break.
* Usage dashboard, last-7-days history and CSV export.
* Failed-authentication lockout after 5 incorrect attempts (5-minute lockout).
* Optional current-user Windows startup registration.
* Optional system tray icon.

MULTIPLE WINDOWS USERS
----------------------
Each Windows account has an independent profile. Sign into each Windows account,
run PCAppLockerV3.exe, set that account's parent/admin PIN and password, and
configure its protected apps and limits. The settings and usage are separate.

This release does NOT include a central parent console to administer every
Windows account from one account. It also does not install a Windows service.
For a child account, use a standard (non-administrator) Windows account. Keep
the parent account as administrator and do not share its password.

BUILD A STANDALONE EXE WITHOUT PYTHON ON THE TARGET PC
------------------------------------------------------
GitHub Actions builds the executable on a hosted Windows runner.

1. Create a GitHub repository.
2. Upload the contents of this project folder, preserving the .github/workflows
   folder and keeping app_locker_v3.py and requirements.txt at the repository root.
3. Open Actions.
4. Run "Build PC App Locker V3 for Windows".
5. Download the PCAppLockerV3-Windows artifact from the completed run.
6. Extract PCAppLockerV3.exe and copy it to each Windows user account's PC.
7. Run it while signed into each account and configure that profile.

The target Windows PC does not need Python, pip or a command prompt.

SECURITY AND ACCURACY LIMITATIONS
---------------------------------
This is a user-session convenience monitor, not tamper-proof OS enforcement.
An administrator can terminate the process or modify its files. The app monitors
the selected executable process after launch, so a short launch flash may occur.
Some apps spawn helper processes or use launchers; they may require adding the
actual executable as well. Time is process-running time, not foreground-only
keyboard/mouse activity. The current break workflow closes the app and prompts
again; it is a basic pause rather than a secure system-wide lock.

For stronger parental controls, use a standard Windows child account and combine
this app with Windows Family Safety / supported Windows application control
policies. Do not rely on this prototype as the only protection for sensitive data.

CREDENTIALS
-----------
PIN and password are stored as salted PBKDF2-HMAC-SHA256 hashes in the current
Windows user's profile file. This protects against casual plaintext disclosure,
but does not protect against a local administrator or malware running as that user.

EXIT BEHAVIOUR
--------------
Closing the main window minimizes to the system tray when pystray is available.
Use Exit in the tray menu to stop monitoring. A user can still terminate the
process through Task Manager; this is not tamper-proof.

TEST BEFORE DEPLOYMENT
----------------------
Test on a non-admin Windows account with a harmless application first. Verify
launch authentication, daily/session expiry, schedule boundaries, overnight
schedules, midnight reset, break behavior, startup, and tray restore/exit.
