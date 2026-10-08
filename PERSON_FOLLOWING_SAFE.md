# Safe official Pupper V3 person-following demo

This demo launches the official Pupper V3 packages for the camera, Hailo
detector, neural walking controller, velocity multiplexer, and person follower.
It does not replace or edit any file under `~/pupperv3-monorepo`.

Safety overrides applied at launch time:

- Maximum forward velocity after filtering: `0.28 m/s`
- Maximum angular velocity after filtering: `0.30 rad/s`
- Reverse motion is blocked
- The robot turns before moving forward
- Raw command timeout: `0.35 s`
- Official detection timeout: `0.4 s`
- Person following starts inactive and requires a separate activation command
- Activation is refused unless Hailo currently sees a person
- The complete stack automatically shuts down after a bounded runtime

After deployment, use a clear floor and keep the robot away from stairs.

Main terminal:

```bash
~/pupper-tests/run_official_person_follow_safe.sh 180
```

Second terminal, after the main terminal reports `READY`:

```bash
~/pupper-tests/start_person_following_safe.sh
```

Stop following while keeping the robot standing:

```bash
~/pupper-tests/stop_person_following_safe.sh
```

Press Ctrl+C in the main terminal to stop the complete stack.
