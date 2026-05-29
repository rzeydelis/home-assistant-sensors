# main.py - Pico W/H + SCD40 -> MQTT
import json
import time

import network
from machine import I2C, Pin, reset
from umqtt.simple import MQTTClient

try:
    import secrets
except ImportError:
    raise RuntimeError("Create secrets.py from secrets.example.py before running")


WIFI_SSID = secrets.WIFI_SSID
WIFI_PASS = secrets.WIFI_PASS
MQTT_HOST = secrets.MQTT_HOST
MQTT_PORT = getattr(secrets, "MQTT_PORT", 1883)
MQTT_USER = getattr(secrets, "MQTT_USER", "")
MQTT_PASS = getattr(secrets, "MQTT_PASS", "")
DEVICE_ID = getattr(secrets, "DEVICE_ID", "ENTER_NAME_FOR_DEVICE")

# I2C: GP16=SDA (physical pin 21), GP17=SCL (physical pin 22).
I2C_ID = 0
SDA_GP = 16
SCL_GP = 17
I2C_FREQ = 50_000

PUBLISH_EVERY_SEC = 600

LED = Pin("LED", Pin.OUT)

SCD4X_ADDR = 0x62

STATE_TOPIC = ("home/%s/state" % DEVICE_ID).encode()
AVAIL_TOPIC = ("home/%s/availability" % DEVICE_ID).encode()
CLIENT_ID = DEVICE_ID.encode()


def blink(n, dt=0.15):
    for _ in range(n):
        LED.on()
        time.sleep(dt)
        LED.off()
        time.sleep(dt)


def wifi_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan

    print("Wi-Fi connecting...")
    wlan.connect(WIFI_SSID, WIFI_PASS)

    t0 = time.ticks_ms()
    while not wlan.isconnected():
        time.sleep(0.25)
        if time.ticks_diff(time.ticks_ms(), t0) > 20_000:
            print("Wi-Fi failed; rebooting")
            time.sleep(1)
            reset()

    print("Wi-Fi OK:", wlan.ifconfig())
    return wlan


def cmd16(cmd):
    return bytes([(cmd >> 8) & 0xFF, cmd & 0xFF])


def crc8(data):
    crc = 0xFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x31) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def scd_write(i2c, cmd, tries=6):
    b = cmd16(cmd)
    for _ in range(tries):
        try:
            i2c.writeto(SCD4X_ADDR, b)
            return True
        except OSError:
            time.sleep_ms(200)
    return False


def scd_read_words(i2c, cmd, n_words):
    i2c.writeto(SCD4X_ADDR, cmd16(cmd))
    time.sleep_ms(5)
    raw = i2c.readfrom(SCD4X_ADDR, n_words * 3)

    out = []
    for i in range(n_words):
        msb = raw[i * 3]
        lsb = raw[i * 3 + 1]
        c = raw[i * 3 + 2]
        if crc8(bytes([msb, lsb])) != c:
            raise ValueError("CRC mismatch")
        out.append((msb << 8) | lsb)
    return out


def scd_start(i2c):
    # Stop periodic measurement first so the start command has a known state.
    scd_write(i2c, 0x3F86)
    time.sleep(1)
    ok = scd_write(i2c, 0x21B1)
    time.sleep(5)
    return ok


def scd_read_measurement(i2c):
    status = scd_read_words(i2c, 0xE4B8, 1)[0]
    if status == 0:
        return None

    co2, t_raw, rh_raw = scd_read_words(i2c, 0xEC05, 3)
    temp_c = -45 + 175 * (t_raw / 65535)
    rh = 100 * (rh_raw / 65535)
    return co2, temp_c, rh


def mqtt_connect():
    m = MQTTClient(
        client_id=CLIENT_ID,
        server=MQTT_HOST,
        port=MQTT_PORT,
        user=(MQTT_USER if MQTT_USER else None),
        password=(MQTT_PASS if MQTT_USER else None),
        keepalive=60,
    )
    m.set_last_will(AVAIL_TOPIC, b"offline", retain=True, qos=0)
    m.connect()
    m.publish(AVAIL_TOPIC, b"online", retain=True)
    return m


def main():
    blink(2)
    wifi_connect()

    i2c = I2C(I2C_ID, sda=Pin(SDA_GP), scl=Pin(SCL_GP), freq=I2C_FREQ)
    found = i2c.scan()
    print("I2C scan:", [hex(x) for x in found])

    if SCD4X_ADDR not in found:
        print("SCD40 not found at 0x62. Check wiring.")
        while True:
            blink(1, 0.5)
            time.sleep(1)

    if not scd_start(i2c):
        print("SCD40 start failed. Power-cycle sensor.")
        while True:
            blink(3, 0.2)
            time.sleep(2)

    mqtt = mqtt_connect()
    last_pub = 0

    while True:
        try:
            now = time.time()
            if now - last_pub >= PUBLISH_EVERY_SEC:
                meas = scd_read_measurement(i2c)
                if meas:
                    co2, temp_c, rh = meas
                    payload = {
                        "co2_ppm": int(co2),
                        "temperature_c": round(temp_c, 2),
                        "humidity_rh": round(rh, 1),
                    }
                    mqtt.publish(
                        STATE_TOPIC,
                        json.dumps(payload).encode("utf-8"),
                        retain=False,
                    )
                    mqtt.publish(AVAIL_TOPIC, b"online", retain=True)
                    LED.toggle()
                    last_pub = now
                else:
                    print("Not ready yet...")
            time.sleep(1)

        except Exception as e:
            print("Loop error:", e)
            try:
                mqtt = mqtt_connect()
            except Exception:
                print("Hard reboot")
                time.sleep(2)
                reset()


main()
