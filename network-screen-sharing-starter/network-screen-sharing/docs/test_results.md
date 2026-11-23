# Test results (real outcomes only)

Fill a row only after running the test on the real laptops. Status: `pass`, `fail` or `not run`. Add date, laptops, network and notes. Never fill a row from memory or assumption.

| # | Check (ARCHITECTURE.md section 18.3) | Status | Notes (date, laptops, network, evidence file) |
|---:|---|---|---|
| 1 | Host starts and displays its LAN IPv4 address and TCP port 5000. | not run | |
| 2 | Host generates a new temporary session code for each sharing session. | not run | |
| 3 | Viewer 1 can connect from another laptop over the private LAN/hotspot. | not run | |
| 4 | Viewer 2 can connect at the same time. | not run | |
| 5 | A third Viewer is denied cleanly. | not run | |
| 6 | Both Viewers see the Host screen. | not run | |
| 7 | Screen display preserves the source aspect ratio. | not run | |
| 8 | A Viewer can request control. | not run | |
| 9 | Host can approve and deny a request. | not run | |
| 10 | A second control request is denied while a request is pending or another Viewer controls. | not run | |
| 11 | Only the active Viewer can move/click/type on the Host. | not run | |
| 12 | Host can revoke control immediately after the current input action completes. | not run | |
| 13 | Held keys/buttons are released after revoke or disconnect. | not run | |
| 14 | A Viewer disconnecting does not crash the other Viewer session. | not run | |
| 15 | Host Stop Sharing closes the listener and all sessions. | not run | |
| 16 | PyAutoGUI fail-safe remains enabled. | not run | |
| 17 | Host statistics panel shows each Viewer's `ip:port`, frames, bytes and skipped frames. | not run | |
| 18 | `demo/transport_demos.py boundaries` and `ports` run and print the expected result. | not run | |
| 19 | The flow-control demonstration was tried on the real laptops and its result recorded (worked or did not work) in `docs/test_results.md`. | not run | |
| 20 | A `.pcapng` capture and screenshots exist as a fallback for the demonstration. | not run | |
| 21 | Wireshark shows the real TCP handshake, application data and connection termination. | not run | |
| 22 | The team can explain that TCP is provided by the operating system and that the 5-byte header belongs to the application protocol. | not run | |
