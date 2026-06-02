#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>

// Front door reed switch for ESP32-C6.
// Wiring: one reed switch wire to GPIO4, the other to GND.
// The internal pull-up keeps the pin HIGH when the switch is open.

constexpr int REED_PIN = 4;
constexpr unsigned long DEBOUNCE_MS = 50;
constexpr unsigned long MQTT_RETRY_MS = 5000;

const char *WIFI_SSID = "YOUR_WIFI_SSID";
const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char *MQTT_HOST = "192.168.8.1";
constexpr uint16_t MQTT_PORT = 1883;
const char *MQTT_USER = "";
const char *MQTT_PASSWORD = "";

const char *DEVICE_ID = "front_door_reed_switch";
const char *DEVICE_NAME = "Front Door Sensor";
const char *STATE_TOPIC = "home/front_door/state";
const char *AVAILABILITY_TOPIC = "home/front_door/availability";
const char *DISCOVERY_TOPIC = "homeassistant/binary_sensor/front_door_reed_switch/config";

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

bool stableDoorOpen = false;
bool lastRawDoorOpen = false;
unsigned long lastRawChangeAt = 0;
unsigned long lastMqttAttemptAt = 0;

bool readDoorOpen() {
  // HIGH means the reed switch is not connecting the pin to GND.
  return digitalRead(REED_PIN) == HIGH;
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print('.');
  }
  Serial.println();
  Serial.print("WiFi connected: ");
  Serial.println(WiFi.localIP());
}

void publishDiscovery() {
  String payload = "{";
  payload += "\"name\":\"Front Door\",";
  payload += "\"unique_id\":\"front_door_reed_switch\",";
  payload += "\"device_class\":\"door\",";
  payload += "\"state_topic\":\"" + String(STATE_TOPIC) + "\",";
  payload += "\"availability_topic\":\"" + String(AVAILABILITY_TOPIC) + "\",";
  payload += "\"payload_on\":\"OPEN\",";
  payload += "\"payload_off\":\"CLOSED\",";
  payload += "\"device\":{";
  payload += "\"identifiers\":[\"" + String(DEVICE_ID) + "\"],";
  payload += "\"name\":\"" + String(DEVICE_NAME) + "\",";
  payload += "\"manufacturer\":\"ESP32-C6\",";
  payload += "\"model\":\"Reed Switch\"";
  payload += "}";
  payload += "}";

  mqtt.publish(DISCOVERY_TOPIC, payload.c_str(), true);
}

void publishDoorState(bool doorOpen) {
  mqtt.publish(STATE_TOPIC, doorOpen ? "OPEN" : "CLOSED", true);
  Serial.print("Door state: ");
  Serial.println(doorOpen ? "OPEN" : "CLOSED");
}

void connectMqtt() {
  if (mqtt.connected()) {
    return;
  }

  unsigned long now = millis();
  if (now - lastMqttAttemptAt < MQTT_RETRY_MS) {
    return;
  }
  lastMqttAttemptAt = now;

  Serial.print("Connecting to MQTT...");
  bool connected = false;
  if (strlen(MQTT_USER) > 0) {
    connected = mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASSWORD, AVAILABILITY_TOPIC, 1, true, "offline");
  } else {
    connected = mqtt.connect(DEVICE_ID, AVAILABILITY_TOPIC, 1, true, "offline");
  }

  if (!connected) {
    Serial.print(" failed, rc=");
    Serial.println(mqtt.state());
    return;
  }

  Serial.println(" connected");
  mqtt.publish(AVAILABILITY_TOPIC, "online", true);
  publishDiscovery();
  publishDoorState(stableDoorOpen);
}

void setup() {
  Serial.begin(115200);
  pinMode(REED_PIN, INPUT_PULLUP);

  stableDoorOpen = readDoorOpen();
  lastRawDoorOpen = stableDoorOpen;
  lastRawChangeAt = millis();

  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  connectMqtt();
}

void loop() {
  connectWiFi();
  connectMqtt();
  mqtt.loop();

  bool rawDoorOpen = readDoorOpen();
  unsigned long now = millis();

  if (rawDoorOpen != lastRawDoorOpen) {
    lastRawDoorOpen = rawDoorOpen;
    lastRawChangeAt = now;
  }

  if ((now - lastRawChangeAt) >= DEBOUNCE_MS && rawDoorOpen != stableDoorOpen) {
    stableDoorOpen = rawDoorOpen;
    publishDoorState(stableDoorOpen);
  }
}
