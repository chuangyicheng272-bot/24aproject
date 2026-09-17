/*
For ESP32S3 UWB AT Demo


Use 2.0.0   Wire
Use 1.11.7   Adafruit_GFX_Library
Use 1.14.4   Adafruit_BusIO
Use 2.0.0   SPI
Use 2.5.7   Adafruit_SSD1306

*/

//去掉DTR脚串口， 否则一直拉低复位脚

// User config          ------------------------------------------

#define UWB_INDEX 4

#define ANCHOR

#define UWB_TAG_COUNT 64

static_assert(
    UWB_INDEX >= 1 && UWB_INDEX <= 4,
    "This project uses Anchor IDs A1 through A4.");

// User config end       ------------------------------------------

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <time.h>

// Copy include/local_config.example.h to include/local_config.h before building.
#include "local_config.h"

static const unsigned long WIFI_RETRY_INTERVAL_MS = 10000;
static const unsigned long HTTP_TIMEOUT_MS = 3000;

#define SERIAL_LOG Serial
#define SERIAL_AT mySerial2

HardwareSerial SERIAL_AT(2);

// ESP32S3
#define RESET 16

#define IO_RXD2 18
#define IO_TXD2 17

#define I2C_SDA 39
#define I2C_SCL 38

Adafruit_SSD1306 display(128, 64, &Wire, -1);

void logoshow(void);
String sendData(String command, const int timeout, boolean debug);
String config_cmd();
String cap_cmd();
void connectWiFi();
void ensureWiFi();
void handleUwbLine(const String &line);
bool parseRangeLine(
    const String &line,
    int &tagId,
    unsigned long &sequenceId,
    long rangesCm[8],
    unsigned long &anchorMask);
bool postRange(
    int tagId,
    unsigned long sequenceId,
    unsigned long timestamp,
    long distanceMm);

void setup()
{
    pinMode(RESET, OUTPUT);
    digitalWrite(RESET, HIGH);

    SERIAL_LOG.begin(115200);

    SERIAL_LOG.print(F("Hello! ESP32-S3 AT command V1.0 Test"));
    SERIAL_AT.begin(115200, SERIAL_8N1, IO_RXD2, IO_TXD2);

    SERIAL_AT.println("AT");
    Wire.begin(I2C_SDA, I2C_SCL);
    delay(1000);
    // SSD1306_SWITCHCAPVCC = generate display voltage from 3.3V internally
    if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C))
    { // Address 0x3C for 128x32
        SERIAL_LOG.println(F("SSD1306 allocation failed"));
        for (;;)
            ; // Don't proceed, loop forever
    }
    display.clearDisplay();

    logoshow();

    sendData("AT?", 2000, 1);
    sendData("AT+RESTORE", 5000, 1);

    sendData(config_cmd(), 2000, 1);
    sendData(cap_cmd(), 2000, 1);
//    sendData("AT+GETCAP?/r/n", 2000, 1);
    sendData("AT+SETRPT=1", 2000, 1);
    sendData("AT+SAVE", 2000, 1);
    sendData("AT+RESTART", 2000, 1);

    connectWiFi();
    configTime(8 * 3600, 0, "pool.ntp.org", "time.nist.gov");
}

long int runtime = 0;

String response = "";
unsigned long lastWiFiAttempt = 0;
bool wifiConnectedMessageShown = false;

void loop()
{
    while (SERIAL_LOG.available() > 0)
    {
        SERIAL_AT.write(SERIAL_LOG.read());
        yield();
    }
    while (SERIAL_AT.available() > 0)
    {
        char c = SERIAL_AT.read();

        if (c == '\r')
            continue;
        else if (c == '\n' || c == '\r')
        {
            if (!response.isEmpty())
            {
                SERIAL_LOG.println(response);
                handleUwbLine(response);
            }
            response = "";
        }
        else
            response += c;
    }

    ensureWiFi();
}

void connectWiFi()
{
    lastWiFiAttempt = millis();
    SERIAL_LOG.print("Connecting Wi-Fi: ");
    SERIAL_LOG.println(WIFI_SSID);

    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void ensureWiFi()
{
    if (WiFi.status() == WL_CONNECTED)
    {
        if (!wifiConnectedMessageShown)
        {
            SERIAL_LOG.print("Wi-Fi connected, ESP32 IP: ");
            SERIAL_LOG.println(WiFi.localIP());
            wifiConnectedMessageShown = true;
        }
        return;
    }

    if (millis() - lastWiFiAttempt >= WIFI_RETRY_INTERVAL_MS)
    {
        wifiConnectedMessageShown = false;
        SERIAL_LOG.print("Wi-Fi not connected, status=");
        SERIAL_LOG.println(static_cast<int>(WiFi.status()));
        WiFi.disconnect();
        connectWiFi();
    }
}

void handleUwbLine(const String &line)
{
    if (line.indexOf("AT+RANGE=") < 0)
        return;

    int tagId = -1;
    unsigned long sequenceId = 0;
    unsigned long anchorMask = 0;
    long rangesCm[8] = {};

    if (!parseRangeLine(
            line, tagId, sequenceId, rangesCm, anchorMask))
    {
        SERIAL_LOG.println("RANGE parse failed");
        return;
    }

    const unsigned long anchorBit = 1UL << UWB_INDEX;
    const long distanceCm = rangesCm[UWB_INDEX];
    if ((anchorMask & anchorBit) == 0 || distanceCm <= 0)
    {
        SERIAL_LOG.println("No valid range for this anchor");
        return;
    }

    // Makerfabs AT+RANGE reports distance in centimetres.
    const long distanceMm = distanceCm * 10L;
    time_t currentTime = time(nullptr);
    unsigned long timestamp =
        currentTime >= 1000000000 ? static_cast<unsigned long>(currentTime)
                                  : millis() / 1000UL;

    postRange(tagId, sequenceId, timestamp, distanceMm);
}

bool parseRangeLine(
    const String &line,
    int &tagId,
    unsigned long &sequenceId,
    long rangesCm[8],
    unsigned long &anchorMask)
{
    int tidStart = line.indexOf("tid:");
    int maskStart = line.indexOf(",mask:");
    int seqStart = line.indexOf(",seq:");
    int rangeStart = line.indexOf(",range:(");
    int rangeEnd = line.indexOf("),rssi:");
    if (rangeEnd < 0)
        rangeEnd = line.indexOf("),ancid:");

    if (tidStart < 0 || maskStart < 0 || seqStart < 0 ||
        rangeStart < 0 || rangeEnd < 0)
        return false;

    tagId = line.substring(tidStart + 4, maskStart).toInt();
    String maskText = line.substring(maskStart + 6, seqStart);
    anchorMask = strtoul(maskText.c_str(), nullptr, 16);
    sequenceId =
        strtoul(line.substring(seqStart + 5, rangeStart).c_str(), nullptr, 10);

    String rangeText =
        line.substring(rangeStart + 8, rangeEnd);
    int parsed = sscanf(
        rangeText.c_str(),
        "%ld,%ld,%ld,%ld,%ld,%ld,%ld,%ld",
        &rangesCm[0], &rangesCm[1], &rangesCm[2], &rangesCm[3],
        &rangesCm[4], &rangesCm[5], &rangesCm[6], &rangesCm[7]);

    return tagId >= 0 && parsed == 8;
}

bool postRange(
    int tagId,
    unsigned long sequenceId,
    unsigned long timestamp,
    long distanceMm)
{
    if (WiFi.status() != WL_CONNECTED)
    {
        SERIAL_LOG.println("Skip HTTP: Wi-Fi is not connected");
        return false;
    }

    // Makerfabs T0 maps to backend BELT-001, T1 to BELT-002, etc.
    char beltId[16];
    snprintf(beltId, sizeof(beltId), "BELT-%03d", tagId + 1);

    String payload = "{";
    payload += "\"sequence_id\":" + String(sequenceId) + ",";
    // Physical A1-A4 map directly to backend Anchor1-Anchor4.
    payload += "\"anchor_id\":\"Anchor" + String(UWB_INDEX) + "\",";
    payload += "\"timestamp\":" + String(timestamp) + ",";
    payload += "\"detected_belts\":{\"" + String(beltId) + "\":{";
    payload += "\"distance_mm\":" + String(distanceMm);
    payload += "}}}";

    SERIAL_LOG.println("POST payload:");
    SERIAL_LOG.println(payload);

    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.begin(FLASK_URL);
    http.addHeader("Content-Type", "application/json");
    int statusCode = http.POST(payload);
    String responseBody =
        statusCode > 0 ? http.getString() : http.errorToString(statusCode);
    http.end();

    SERIAL_LOG.print("HTTP response code: ");
    SERIAL_LOG.println(statusCode);
    SERIAL_LOG.println(responseBody);
    return statusCode >= 200 && statusCode < 300;
}

// SSD1306

void logoshow(void)
{
    display.clearDisplay();

    display.setTextSize(1);              // Normal 1:1 pixel scale
    display.setTextColor(SSD1306_WHITE); // Draw white text
    display.setCursor(0, 0);             // Start at top-left corner
    display.println(F("MaUWB DW3000"));

    display.setCursor(0, 20); // Start at top-left corner
    // display.println(F("with STM32 AT Command"));

    display.setTextSize(2);

    String temp = "";

    temp = temp + "A" + UWB_INDEX;

    temp = temp + "   6.8M";

    display.println(temp);

    display.setCursor(0, 40);

    temp = "Total: ";
    temp = temp + UWB_TAG_COUNT;
    display.println(temp);

    display.display();

    delay(2000);
}

String sendData(String command, const int timeout, boolean debug)
{
    String response = "";
    // command = command + "\r\n";

    SERIAL_LOG.println(command);
    SERIAL_AT.println(command); // send the read character to the SERIAL_LOG

    long int time = millis();

    while ((time + timeout) > millis())
    {
        while (SERIAL_AT.available())
        {

            // The esp has data so display its output to the serial window
            char c = SERIAL_AT.read(); // read the next character.
            response += c;
        }
    }

    if (debug)
    {
        SERIAL_LOG.println(response);
    }

    return response;
}

String config_cmd()
{
    String temp = "AT+SETCFG=";

    // Set device id
    temp = temp + UWB_INDEX;

    // Set device role
    //x2:Device Role(0:Tag / 1:Anchor)
    temp = temp + ",1";


    // Set frequence 850k or 6.8M

    temp = temp + ",1";

    // Set range filter
    temp = temp + ",1";

    return temp;
}

String cap_cmd()
{
    String temp = "AT+SETCAP=";

    // Set Tag capacity
    temp = temp + UWB_TAG_COUNT;

    //  Time of a single time slot  6.5M : 10MS  850K ： 15MS
    temp = temp + ",10";

    //X3:extMode, whether to increase the passthrough command when transmitting
    //(0: normal packet when communicating, 1: extended packet when communicating)
    temp = temp + ",1";

    return temp;
}
