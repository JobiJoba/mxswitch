# Mac KVM HTTP controller

Orchestrates **BetterDisplay** (monitor input) and **mxswitch** (Logitech Easy-Switch) from one local HTTP server on the Mac.

Windows only needs `curl`. No Logitech software on Windows.

## Mapping

| Endpoint       | Monitor (BetterDisplay `:55777`) | Logitech |
| -------------- | -------------------------------- | -------- |
| `GET /mac`     | HDMI — `ddcAlt=144`              | channel 2 |
| `GET /windows` | USB-C — `ddcAlt=465`             | channel 1 |
| `GET /health`  | —                                | —         |

Edit [`config.json`](config.json) to change ports, `ddcAlt` codes, or channels.

## Prerequisites

1. Build mxswitch: `make` from the repo root (produces `./mxswitch`).
2. Grant **Input Monitoring** to the `mxswitch` binary (and to whatever launches it, e.g. Terminal or the LaunchAgent’s `python3`).
3. BetterDisplay running with **HTTP integration** enabled on port `55777`.

## Run (foreground)

```bash
make
python3 server/kvm_server.py
```

Then:

```bash
curl http://localhost:55778/mac
curl http://localhost:55778/windows

# from Windows / another machine on the LAN:
curl http://192.168.x.x:55778/mac
curl http://192.168.x.x:55778/windows
```

Optional: `KVM_CONFIG=/path/to/config.json python3 server/kvm_server.py`

## Always-on (LaunchAgent)

1. Edit absolute paths in [`com.mxswitch.kvm.plist`](com.mxswitch.kvm.plist).
2. Install and load:

```bash
cp server/com.mxswitch.kvm.plist ~/Library/LaunchAgents/
# edit ProgramArguments / WorkingDirectory / KVM_CONFIG paths
launchctl load ~/Library/LaunchAgents/com.mxswitch.kvm.plist
```

Logs: `/tmp/mxswitch-kvm.log` and `/tmp/mxswitch-kvm.err`.

## Logitech constraint

`mxswitch` can only ChangeHost while the keyboard/mouse are connected to the Mac.

- `/windows` works when devices are on the Mac (display → USB-C, then leave to channel 1).
- `/mac` always switches the monitor to HDMI; Logitech returns to channel 2 only if the devices are still visible to the Mac. If they are already on Windows, use the Easy-Switch button once (or switch before leaving).
