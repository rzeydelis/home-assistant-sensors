# SDC40 sensor

Raspberry Pi Pico W MicroPython code for an SCD40 CO2, temperature, and humidity sensor publishing JSON readings over MQTT for Home Assistant.

The folder name is `sdc40_sensor` to match the project naming request. The physical sensor addressed by the code is the Sensirion SCD40/SCD4x at I2C address `0x62`.

## Hardware

- Raspberry Pi Pico W or Pico WH
- SCD40/SCD4x sensor on I2C
- SDA on GP16
- SCL on GP17

## MQTT payload

The Pico publishes to:

```text
home/pico_scd40_living_room/state
```

Example payload:

```json
{"co2_ppm": 612, "temperature_c": 22.84, "humidity_rh": 45.8}
```

Availability is published to:

```text
home/pico_scd40_living_room/availability
```

## Setup

1. Copy `secrets.example.py` to `secrets.py`.
2. Fill in Wi-Fi and MQTT values in `secrets.py`.
3. Copy `main.py`, `secrets.py`, and the `lib/` folder to the Pico filesystem.
4. Reset the Pico.

`secrets.py`, crash logs, and sensor history are ignored so credentials and local runtime data do not get committed.
