# TheEnd cloud Android agent bridge

The agent can now use the protected HTTP screen/input endpoint exposed by the cloud Android session instead of requiring a local ADB device.

## Configuration

Set these values on the machine where `theend_agent.py` runs:

- `THEEND_REMOTE_ANDROID_URL`: the private cloud-session base URL including its `?k=...` access key.
- `THEEND_AGENT_TOKEN`: the existing TheEnd agent token.
- `THEEND_URL`: optional API base URL; defaults to the production TheEnd API.

Keep the full cloud-session URL private. Do not paste it into chat, commit it, or send it to friends. It grants control of the temporary Android session.

## Supported operations

In cloud HTTP mode the agent supports:
- PNG screenshot retrieval;
- tap and swipe input;
- Android Back/Home/Menu/Enter/Delete key events allowed by the remote endpoint.

ADB shell, UIAutomator hierarchy dumps, package inspection, and device-side file operations are not available through this HTTP bridge. Semantic modules that require UIAutomator therefore remain unavailable in cloud mode. The visual resource scanner can inspect frames and issue guarded taps, but must be validated against a live game session before being trusted.

## Important runtime limitation

This bridge does not make the agent continuously hosted by itself. The Python agent still needs to be running somewhere with its dependencies installed and network access to the protected cloud session and TheEnd API. The current GitHub cloud Android workflow is temporary and runs for up to 60 minutes. A persistent, unattended worker and session lifecycle still need separate implementation and testing.

Never put game passwords, email passwords, verification codes, or session cookies into TheEnd configuration.
