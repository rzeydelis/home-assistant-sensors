# Raspberry Pi Zero W + OV5647 doorbell camera

Configuration for a low-latency Frigate doorbell stream from this specific
camera host:

- Raspberry Pi Zero W Rev 1.1 (`armv6l`)
- Raspberry Pi Camera Module v1 / OV5647
- 1280x720 H.264 stream over TCP
- Frigate 0.17 with go2rtc
- Google Coral M.2/PCIe detector
- Intel UHD 605 VAAPI video decoding

These settings are deliberately hardware-labelled. Do not assume they are
optimal for a Pi 3, Pi 4, Pi 5, Zero 2 W, or a different camera sensor. In
particular, `--low-latency` is a Pi 5 software-encoder option and is not used
on this Pi Zero W.

## What changed

The camera originally streamed 720p at 15 FPS, 1.5 Mbps, and the default
60-frame H.264 keyframe interval. A new viewer could wait almost four seconds
for a clean keyframe. The Pi was healthy, with no thermal or power throttling,
so the stream was changed to:

- 30 FPS for smoother live video and recordings
- 3 Mbps to preserve roughly the same bits per frame
- a 30-frame keyframe interval, or one keyframe per second
- a one-second systemd restart delay after a disconnected TCP consumer
- seven-day retention for motion, alert, and detection recordings and snapshots

Frigate detection remains at 5 FPS. Raising detection to 30 FPS would waste
CPU and Coral capacity without improving the live view.

## Files

- [`systemd/doorbell-camera.service`](systemd/doorbell-camera.service) runs
  `rpicam-vid` on the Pi Zero W.
- [`frigate-pi-zero-w-ov5647.yml`](frigate-pi-zero-w-ov5647.yml) contains the
  matching Frigate/go2rtc configuration.
- [`docker-compose.devices.yml`](docker-compose.devices.yml) shows the Coral
  and Intel GPU device mappings required by the Frigate container.
- [`nftables/rpcam-guard.nft`](nftables/rpcam-guard.nft) restricts the raw
  camera feed to the Frigate host.

Replace the example Pi address `192.168.1.50` in the Frigate snippet with the
camera's reserved LAN address.

## Install the Pi service

Back up an existing unit before replacing it:

```bash
sudo cp /etc/systemd/system/doorbell-camera.service \
  /etc/systemd/system/doorbell-camera.service.backup
sudo install -m 0644 systemd/doorbell-camera.service \
  /etc/systemd/system/doorbell-camera.service
sudo systemctl daemon-reload
sudo systemctl enable --now doorbell-camera.service
```

The service accepts one TCP consumer on port 5000. In this setup, that consumer
is Frigate's bundled go2rtc process.

## Restrict access to the raw feed

`rpicam-vid` does not authenticate clients on its raw TCP output. Restrict port
5000 at the Pi so only Frigate can connect. First reserve addresses for both
hosts, then replace `192.168.1.10` in `nftables/rpcam-guard.nft` with the
Frigate host's address.

Install and validate the rule fragment:

```bash
sudo install -d -m 0755 /etc/nftables.d
sudo install -m 0644 nftables/rpcam-guard.nft \
  /etc/nftables.d/rpcam-guard.nft
sudo nft -c -f /etc/nftables.d/rpcam-guard.nft
sudo nft -f /etc/nftables.d/rpcam-guard.nft
sudo systemctl enable nftables
```

Add this line to `/etc/nftables.conf` after any `flush ruleset` directive so
the fragment is loaded after a reboot:

```nftables
include "/etc/nftables.d/*.nft"
```

The table has an accept policy and filters only TCP port 5000, so it does not
change SSH access or unrelated services. Verify that its allow counter rises
while Frigate is streaming and that a connection from another LAN device
times out:

```bash
sudo nft list table inet rpcam_guard
```

## Configure Frigate

Merge the contents of `frigate-pi-zero-w-ov5647.yml` into Frigate's existing
`config.yml`; do not replace unrelated cameras or MQTT settings. Merge the two
device mappings from `docker-compose.devices.yml` into the existing Frigate
service, then recreate the container.

The two accelerators have separate jobs:

- Coral Edge TPU runs object-detection inference.
- Intel VAAPI decodes H.264 for FFmpeg.

The Coral does not accelerate FFmpeg. Docker CPU percentages are measured per
core, so 75% on a four-core host is about 19% of total CPU capacity.

## Verify

On the Pi:

```bash
systemctl is-active doorbell-camera.service
ps -C rpicam-vid -o pid,etimes,%cpu,%mem,args
vcgencmd measure_temp
vcgencmd get_throttled
```

On the Frigate host:

```bash
curl -s http://127.0.0.1:5000/api/stats | python3 -m json.tool
docker exec frigate sh -c 'ls -l /dev/apex_0 /dev/dri/renderD128'
```

To sample the live restream for ten seconds with Frigate 0.17's bundled
FFmpeg:

```bash
docker exec frigate /usr/lib/ffmpeg/7.0/bin/ffmpeg \
  -hide_banner -loglevel info -rtsp_transport tcp \
  -i rtsp://127.0.0.1:8554/doorbell -t 10 -an -f null -
```

Confirm that the input reports 30 FPS. Frigate camera stats should settle near
5 FPS because `detect.fps` is intentionally limited to 5.

## Measured result

Measurements from the target installation:

| Metric | Before | After |
| --- | ---: | ---: |
| Live source rate | 15 FPS | 30 FPS |
| Frames decoded during a 10-second join test | 99 | 284 |
| Pi `rpicam-vid` CPU | 29.6% | 49.4% |
| Pi temperature | 55.1 C | 57.3 C |
| Pi throttling flags | `0x0` | `0x0` |
| Frigate skipped FPS | 0 | 0 |

The Coral was detected as `/dev/apex_0`, used the `apex` kernel driver, and
reported approximately 9.9 ms inference time. The running FFmpeg process used
`-hwaccel vaapi` with `/dev/dri/renderD128` and recorded with `-c copy`.

## Roll back

Restore the backed-up service and restart it:

```bash
sudo cp /etc/systemd/system/doorbell-camera.service.backup \
  /etc/systemd/system/doorbell-camera.service
sudo systemctl daemon-reload
sudo systemctl restart doorbell-camera.service
```

The earlier command used 15 FPS, 1.5 Mbps, and systemd's three-second restart
delay. Rolling back Frigate only requires restoring its prior `config.yml` and
Compose file, then recreating the container.

To roll back only the feed restriction, move the persistent fragment aside and
remove the live table:

```bash
sudo mv /etc/nftables.d/rpcam-guard.nft \
  /etc/nftables.d/rpcam-guard.nft.disabled
sudo nft delete table inet rpcam_guard
```
