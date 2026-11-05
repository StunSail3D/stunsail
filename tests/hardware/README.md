# Hardware-in-the-loop tests

Tests in this directory require a real Klipper/Moonraker installation and are
not part of the default CI run. The Phase 1 plan targets an Ender 3 V2 and must
validate actual Moonraker versions, available status objects, job lifecycle,
reconnect/restart behavior, and persistent samples while Mainsail is closed.

Record device/software versions, test conditions, and observed data gaps with
each run. Never include API keys, private network credentials, or unredacted
printer configuration in committed results.
