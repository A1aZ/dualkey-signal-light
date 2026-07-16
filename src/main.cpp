#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <NimBLEDevice.h>
#include <USB.h>
#include <USBCDC.h>

#include <algorithm>
#include <cstring>
#include <string>

namespace {

// M5Stack Chain DualKey (C147) pin map.
constexpr uint8_t KEY_1_PIN = 0;
constexpr uint8_t KEY_2_PIN = 17;
constexpr uint8_t LED_DATA_PIN = 21;
constexpr uint8_t LED_POWER_PIN = 40;
constexpr uint8_t LED_COUNT = 2;

constexpr char DEVICE_NAME[] = "DualKey Signal Light";
constexpr char SERVICE_UUID[] = "7b7f3d10-7d20-4b8e-a2d7-4d55414c0001";
constexpr char RX_UUID[] = "7b7f3d10-7d20-4b8e-a2d7-4d55414c0002";
constexpr char TX_UUID[] = "7b7f3d10-7d20-4b8e-a2d7-4d55414c0003";

constexpr uint8_t DEFAULT_BRIGHTNESS = 64;
constexpr uint32_t BLE_WAITING_DELAY_MS = 15000;
constexpr uint32_t COMMAND_MAX_LENGTH = 95;

USBCDC CdcSerial;
Adafruit_NeoPixel pixels(LED_COUNT, LED_DATA_PIN, NEO_GRB + NEO_KHZ800);
NimBLECharacteristic* txCharacteristic = nullptr;
QueueHandle_t commandQueue = nullptr;

enum class SignalState : uint8_t {
    Idle,
    Working,
    Attention,
    Blocked,
    Complete,
    Off,
};

enum class CommandSource : uint8_t {
    Usb,
    Ble,
};

struct CommandItem {
    CommandSource source;
    char text[COMMAND_MAX_LENGTH + 1];
};

struct ButtonState {
    explicit ButtonState(uint8_t buttonPin) : pin(buttonPin) {}

    uint8_t pin;
    bool rawPressed = false;
    bool pressed = false;
    uint32_t rawChangedAt = 0;
    uint32_t pressedAt = 0;
};

SignalState currentState = SignalState::Idle;
uint8_t brightness = DEFAULT_BRIGHTNESS;
uint32_t stateChangedAt = 0;
uint32_t lastTransportActivityAt = 0;
uint32_t lastLedFrameAt = 0;
uint32_t lastRendered[LED_COUNT] = {0xFFFFFFFF, 0xFFFFFFFF};
volatile bool bleConnected = false;
bool chordHandled = false;
String usbInput;
ButtonState key1{KEY_1_PIN};
ButtonState key2{KEY_2_PIN};

const char* stateName(SignalState state) {
    switch (state) {
        case SignalState::Idle:
            return "idle";
        case SignalState::Working:
            return "working";
        case SignalState::Attention:
            return "attention";
        case SignalState::Blocked:
            return "blocked";
        case SignalState::Complete:
            return "complete";
        case SignalState::Off:
            return "off";
    }
    return "idle";
}

uint32_t rgb(uint8_t red, uint8_t green, uint8_t blue) {
    return (static_cast<uint32_t>(red) << 16) |
           (static_cast<uint32_t>(green) << 8) |
           static_cast<uint32_t>(blue);
}

uint8_t scaleChannel(uint8_t value, uint8_t level) {
    return static_cast<uint8_t>((static_cast<uint16_t>(value) * level) / 255);
}

uint32_t scaleColor(uint32_t color, uint8_t level) {
    return rgb(scaleChannel((color >> 16) & 0xFF, level),
               scaleChannel((color >> 8) & 0xFF, level),
               scaleChannel(color & 0xFF, level));
}

uint32_t blend(uint32_t from, uint32_t to, uint16_t amount, uint16_t range) {
    const auto mix = [amount, range](uint8_t a, uint8_t b) -> uint8_t {
        return static_cast<uint8_t>((static_cast<uint32_t>(a) * (range - amount) +
                                     static_cast<uint32_t>(b) * amount) /
                                    range);
    };
    return rgb(mix((from >> 16) & 0xFF, (to >> 16) & 0xFF),
               mix((from >> 8) & 0xFF, (to >> 8) & 0xFF),
               mix(from & 0xFF, to & 0xFF));
}

uint32_t workingColor(uint32_t phaseMs) {
    constexpr uint32_t segmentMs = 1500;
    constexpr uint32_t cycleMs = segmentMs * 3;
    constexpr uint32_t colors[] = {
        0x00FF20,  // green
        0xFFD000,  // yellow
        0xFF1800,  // red
    };
    phaseMs %= cycleMs;
    const uint8_t segment = phaseMs / segmentMs;
    const uint16_t within = phaseMs % segmentMs;
    return blend(colors[segment], colors[(segment + 1) % 3], within, segmentMs);
}

void renderPixels(uint32_t first, uint32_t second) {
    const uint32_t colors[] = {first, second};
    bool changed = false;
    for (uint8_t index = 0; index < LED_COUNT; ++index) {
        if (lastRendered[index] != colors[index]) {
            pixels.setPixelColor(index,
                                 (colors[index] >> 16) & 0xFF,
                                 (colors[index] >> 8) & 0xFF,
                                 colors[index] & 0xFF);
            lastRendered[index] = colors[index];
            changed = true;
        }
    }
    if (changed) {
        pixels.show();
    }
}

void renderWaitingForBle(uint32_t now) {
    const uint32_t phase = now % 1800;
    uint8_t level = 5;
    if (phase < 300) {
        level = static_cast<uint8_t>(5 + (phase * 35) / 300);
    } else if (phase < 600) {
        level = static_cast<uint8_t>(40 - ((phase - 300) * 35) / 300);
    }
    const uint32_t blue = scaleColor(0x0060FF, level);
    renderPixels(blue, phase >= 900 ? blue : 0);
}

void renderSignal(uint32_t now) {
    if (now - lastLedFrameAt < 20) {
        return;
    }
    lastLedFrameAt = now;

    if (!bleConnected &&
        (currentState == SignalState::Idle || currentState == SignalState::Off) &&
        now - lastTransportActivityAt >= BLE_WAITING_DELAY_MS) {
        renderWaitingForBle(now);
        return;
    }

    switch (currentState) {
        case SignalState::Idle: {
            const uint32_t green = scaleColor(0x00FF18, brightness);
            renderPixels(green, green);
            break;
        }
        case SignalState::Working: {
            const uint32_t elapsed = now - stateChangedAt;
            renderPixels(scaleColor(workingColor(elapsed), brightness),
                         scaleColor(workingColor(elapsed + 2250), brightness));
            break;
        }
        case SignalState::Attention: {
            const bool on = ((now - stateChangedAt) % 900) < 500;
            const uint32_t yellow = on ? scaleColor(0xFFD000, brightness) : 0;
            renderPixels(yellow, yellow);
            break;
        }
        case SignalState::Blocked: {
            const uint32_t phase = (now - stateChangedAt) % 1100;
            const bool on = phase < 140 || (phase >= 260 && phase < 400);
            const uint32_t red = on ? scaleColor(0xFF0000, brightness) : 0;
            renderPixels(red, red);
            break;
        }
        case SignalState::Complete: {
            const uint32_t phase = (now - stateChangedAt) % 500;
            const bool on = phase < 220;
            const uint32_t green = on ? scaleColor(0x00FF18, brightness) : 0;
            renderPixels(green, green);
            break;
        }
        case SignalState::Off:
            renderPixels(0, 0);
            break;
    }
}

void setState(SignalState state) {
    currentState = state;
    stateChangedAt = millis();
    lastLedFrameAt = 0;
    lastRendered[0] = 0xFFFFFFFF;
    lastRendered[1] = 0xFFFFFFFF;
}

bool parseState(String value, SignalState& result) {
    value.trim();
    value.toLowerCase();
    if (value == "idle" || value == "session_start") {
        result = SignalState::Idle;
    } else if (value == "working" || value == "thinking" || value == "tool_done") {
        result = SignalState::Working;
    } else if (value == "attention" || value == "done" || value == "notification") {
        result = SignalState::Attention;
    } else if (value == "blocked" || value == "permission" || value == "error" ||
               value == "failed") {
        result = SignalState::Blocked;
    } else if (value == "complete" || value == "session_done" || value == "session_end") {
        result = SignalState::Complete;
    } else if (value == "off" || value == "clear") {
        result = SignalState::Off;
    } else {
        return false;
    }
    return true;
}

void sendBleNotification(const String& message) {
    if (bleConnected && txCharacteristic != nullptr) {
        txCharacteristic->setValue(message.c_str());
        txCharacteristic->notify();
    }
}

void reply(CommandSource source, const String& message) {
    if (source == CommandSource::Usb) {
        CdcSerial.println(message);
    } else {
        sendBleNotification(message);
    }
}

void enqueueCommand(CommandSource source, const char* text, size_t length) {
    if (commandQueue == nullptr || text == nullptr || length == 0) {
        return;
    }
    CommandItem item{};
    item.source = source;
    const size_t safeLength = std::min(length, static_cast<size_t>(COMMAND_MAX_LENGTH));
    memcpy(item.text, text, safeLength);
    item.text[safeLength] = '\0';
    xQueueSend(commandQueue, &item, 0);
}

void handleCommand(const CommandItem& item) {
    String command(item.text);
    command.trim();
    if (command.isEmpty()) {
        return;
    }

    lastTransportActivityAt = millis();

    String upper = command;
    upper.toUpperCase();
    if (upper == "PING") {
        reply(item.source, "PONG dualkey-signal-light/0.1.0");
        return;
    }
    if (upper == "INFO" || upper == "STATUS") {
        reply(item.source,
              String("STATUS state=") + stateName(currentState) +
                  " brightness=" + brightness +
                  " ble=" + (bleConnected ? "connected" : "advertising"));
        return;
    }
    if (upper.startsWith("BRIGHTNESS ")) {
        const int value = command.substring(11).toInt();
        if (value < 1 || value > 255) {
            reply(item.source, "ERR brightness must be 1..255");
            return;
        }
        brightness = static_cast<uint8_t>(value);
        lastRendered[0] = 0xFFFFFFFF;
        lastRendered[1] = 0xFFFFFFFF;
        reply(item.source, String("OK BRIGHTNESS ") + brightness);
        return;
    }

    String stateText = command;
    if (upper.startsWith("STATE ")) {
        stateText = command.substring(6);
    } else if (upper.startsWith("SET ")) {
        stateText = command.substring(4);
    }

    SignalState parsed;
    if (!parseState(stateText, parsed)) {
        reply(item.source, "ERR expected STATE idle|working|attention|blocked|complete|off");
        return;
    }
    setState(parsed);
    reply(item.source, String("OK STATE ") + stateName(parsed));
}

class ServerCallbacks final : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer*, NimBLEConnInfo&) override {
        bleConnected = true;
        lastTransportActivityAt = millis();
    }

    void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int) override {
        bleConnected = false;
        lastTransportActivityAt = millis();
    }
};

class RxCallbacks final : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo&) override {
        const std::string value = characteristic->getValue();
        enqueueCommand(CommandSource::Ble, value.data(), value.size());
    }
};

ServerCallbacks serverCallbacks;
RxCallbacks rxCallbacks;

void setupBle() {
    NimBLEDevice::init(DEVICE_NAME);
    NimBLEDevice::setPower(3);

    NimBLEServer* server = NimBLEDevice::createServer();
    server->setCallbacks(&serverCallbacks, false);
    server->advertiseOnDisconnect(true);

    NimBLEService* service = server->createService(SERVICE_UUID);
    txCharacteristic = service->createCharacteristic(
        TX_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY, 128);
    txCharacteristic->setValue("READY dualkey-signal-light/0.1.0");

    NimBLECharacteristic* rxCharacteristic = service->createCharacteristic(
        RX_UUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR, 128);
    rxCharacteristic->setCallbacks(&rxCallbacks);

    server->start();
    NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
    advertising->setName(DEVICE_NAME);
    advertising->addServiceUUID(SERVICE_UUID);
    advertising->enableScanResponse(true);
    advertising->start();
}

void setupUsb() {
    USB.VID(0x303A);
    USB.PID(0x4010);
    USB.manufacturerName("M5Stack Community");
    USB.productName(DEVICE_NAME);
    USB.serialNumber("DUALKEY-SIGNAL");
    CdcSerial.begin(115200);
    USB.begin();
}

void pollUsb() {
    while (CdcSerial.available() > 0) {
        const char next = static_cast<char>(CdcSerial.read());
        if (next == '\n' || next == '\r') {
            if (!usbInput.isEmpty()) {
                enqueueCommand(CommandSource::Usb, usbInput.c_str(), usbInput.length());
                usbInput.clear();
            }
        } else if (usbInput.length() < COMMAND_MAX_LENGTH) {
            usbInput += next;
        } else {
            usbInput.clear();
            CdcSerial.println("ERR command too long");
        }
    }
}

void onShortPress(ButtonState& button) {
    if (button.pin == KEY_1_PIN) {
        setState(SignalState::Idle);
        lastTransportActivityAt = millis();
        sendBleNotification("EVENT ACK");
        CdcSerial.println("EVENT ACK");
        return;
    }

    static uint8_t demoIndex = 0;
    constexpr SignalState demoStates[] = {
        SignalState::Idle,
        SignalState::Working,
        SignalState::Attention,
        SignalState::Blocked,
        SignalState::Complete,
        SignalState::Off,
    };
    demoIndex = (demoIndex + 1) % (sizeof(demoStates) / sizeof(demoStates[0]));
    setState(demoStates[demoIndex]);
    lastTransportActivityAt = millis();
    const String event = String("EVENT DEMO ") + stateName(currentState);
    sendBleNotification(event);
    CdcSerial.println(event);
}

void updateButton(ButtonState& button, uint32_t now) {
    const bool rawPressed = digitalRead(button.pin) == LOW;
    if (rawPressed != button.rawPressed) {
        button.rawPressed = rawPressed;
        button.rawChangedAt = now;
    }

    if (rawPressed != button.pressed && now - button.rawChangedAt >= 25) {
        button.pressed = rawPressed;
        if (button.pressed) {
            button.pressedAt = now;
        } else if (!chordHandled && now - button.pressedAt < 1200) {
            onShortPress(button);
        }
    }
}

void pollButtons(uint32_t now) {
    updateButton(key1, now);
    updateButton(key2, now);

    if (key1.pressed && key2.pressed && !chordHandled) {
        const uint32_t chordStartedAt = std::max(key1.pressedAt, key2.pressedAt);
        if (now - chordStartedAt >= 1500) {
            chordHandled = true;
            setState(SignalState::Off);
            lastTransportActivityAt = now;
            sendBleNotification("EVENT CLEAR");
            CdcSerial.println("EVENT CLEAR");
        }
    }

    if (!key1.pressed && !key2.pressed && chordHandled) {
        chordHandled = false;
    }
}

}  // namespace

void setup() {
    // The official BSP drives GPIO40 as open-drain and LOW means WS2812 power on.
    pinMode(LED_POWER_PIN, OUTPUT_OPEN_DRAIN);
    digitalWrite(LED_POWER_PIN, LOW);
    pixels.begin();
    pixels.clear();
    pixels.show();

    pinMode(KEY_1_PIN, INPUT_PULLUP);
    pinMode(KEY_2_PIN, INPUT_PULLUP);

    commandQueue = xQueueCreate(8, sizeof(CommandItem));
    stateChangedAt = millis();
    lastTransportActivityAt = millis();

    setupUsb();
    setupBle();
    CdcSerial.println("READY dualkey-signal-light/0.1.0");
}

void loop() {
    const uint32_t now = millis();
    pollUsb();
    pollButtons(now);

    CommandItem item{};
    while (xQueueReceive(commandQueue, &item, 0) == pdTRUE) {
        handleCommand(item);
    }

    if (currentState == SignalState::Complete && now - stateChangedAt >= 1400) {
        setState(SignalState::Idle);
    }

    renderSignal(now);
    delay(2);
}
