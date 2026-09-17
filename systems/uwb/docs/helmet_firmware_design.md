# 安全帽系統韌體設計文件

> **已棄用：** 本文件描述不再使用的舊硬體方案，只保留作歷史參考。現行系統以工人的安全腰帶狀態為判斷依據；正式 HTTP JSON 欄位為 `safety_belt`。下列舊韌體名稱與內部封包不可作為現行 HTTP API 規格。

本文件設計安全帽端 firmware 架構。安全帽是 UWB Tag，未來會透過 DW3000 與基站通訊。第一版先把模組邊界與資料格式定好，不綁定特定 DW3000 library，方便之後替換成真實 UWB driver。

## 1. 安全帽 firmware 專案目錄

```text
helmet-firmware/
├─ platformio.ini 或 CMakeLists.txt
├─ README.md
├─ src/
│  ├─ main.cpp
│  ├─ app/
│  │  ├─ helmet_app.cpp
│  │  ├─ helmet_app.h
│  │  ├─ helmet_state_machine.cpp
│  │  └─ helmet_state_machine.h
│  │
│  ├─ modules/
│  │  ├─ battery/
│  │  │  ├─ battery_monitor.cpp
│  │  │  └─ battery_monitor.h
│  │  ├─ wear/
│  │  │  ├─ wear_detector.cpp
│  │  │  └─ wear_detector.h
│  │  ├─ alert/
│  │  │  ├─ alert_controller.cpp
│  │  │  └─ alert_controller.h
│  │  ├─ identity/
│  │  │  ├─ device_identity.cpp
│  │  │  └─ device_identity.h
│  │  └─ uwb/
│  │     ├─ uwb_interface.h
│  │     ├─ uwb_mock.cpp
│  │     ├─ uwb_mock.h
│  │     ├─ uwb_packet.cpp
│  │     └─ uwb_packet.h
│  │
│  ├─ drivers/
│  │  ├─ gpio_driver.cpp
│  │  ├─ gpio_driver.h
│  │  ├─ adc_driver.cpp
│  │  ├─ adc_driver.h
│  │  ├─ buzzer_driver.cpp
│  │  ├─ buzzer_driver.h
│  │  ├─ led_driver.cpp
│  │  ├─ led_driver.h
│  │  ├─ vibration_driver.cpp
│  │  └─ vibration_driver.h
│  │
│  ├─ platform/
│  │  ├─ board_config.h
│  │  ├─ pin_map.h
│  │  └─ system_time.h
│  │
│  └─ protocol/
│     ├─ uwb_protocol.h
│     └─ command_protocol.h
│
└─ test/
   ├─ test_uwb_packet.cpp
   ├─ test_command_parser.cpp
   └─ test_state_machine.cpp
```

設計重點：

- `app/` 負責主流程與狀態機。
- `modules/` 負責功能邏輯，例如電量、配戴、警示、UWB。
- `drivers/` 負責硬體 GPIO / ADC / LED / 馬達 / 蜂鳴器。
- `modules/uwb/uwb_interface.h` 是抽象介面，之後接 DW3000 library 時主要替換這一層。
- `protocol/` 定義 payload 與 command 格式，避免散落在主程式裡。

## 2. 主流程 main loop

安全帽第一版主流程：

```text
setup()
  ↓
初始化 Serial / log
  ↓
讀取 board_config / pin_map
  ↓
初始化 battery_monitor
  ↓
初始化 wear_detector
  ↓
初始化 alert_controller
  ↓
初始化 uwb module
  ↓
讀取 helmet_id
  ↓
進入 loop()
```

主迴圈：

```text
loop()
  ↓
更新狀態機
  ↓
讀取 battery_level
  ↓
讀取 wearing_status
  ↓
組成 UWB payload
  ↓
透過 UWB 傳送給基站
  ↓
檢查是否收到基站 command
  ↓
如果 command = ALARM_ON
    啟動蜂鳴器、LED、震動馬達
  ↓
如果 command = ALARM_OFF
    關閉警示
  ↓
等待下一次週期
```

建議週期：

```text
已配戴：每 500 ms ~ 1000 ms 回報一次
未配戴：每 3000 ms ~ 10000 ms 回報一次
低電量：降低回報頻率，保留警示能力
```

概念 pseudo flow：

```cpp
void loop() {
  helmetApp.update();
}
```

`helmetApp.update()` 裡面負責：

```text
1. update sensors
2. update state machine
3. send UWB status payload when interval reached
4. receive UWB command
5. update alert output
```

## 3. 狀態機

安全帽狀態：

```text
BOOT
  ↓
INIT_HW
  ↓
SELF_TEST
  ↓
IDLE_NOT_WORN
  ↓
ACTIVE_WORN
  ↓
UWB_TX
  ↓
WAIT_COMMAND
  ↓
ALARM
```

完整狀態說明：

| 狀態 | 說明 |
|---|---|
| `BOOT` | MCU 剛開機 |
| `INIT_HW` | 初始化 GPIO、ADC、UWB、蜂鳴器、LED、震動馬達 |
| `SELF_TEST` | 檢查電池、配戴偵測、UWB 是否可用 |
| `IDLE_NOT_WORN` | 未配戴，降低回報頻率 |
| `ACTIVE_WORN` | 已配戴，正常回報狀態 |
| `UWB_TX` | 組成 payload 並送給基站 |
| `WAIT_COMMAND` | 等待基站回傳 command 或 ACK |
| `ALARM` | 收到 ALARM_ON，啟動蜂鳴器、LED、震動馬達 |
| `LOW_BATTERY` | 電量偏低，回報狀態並可發出低電量提醒 |
| `FAULT` | UWB、ADC 或感測器異常 |

事件：

```text
EV_BOOT_DONE
EV_HW_READY
EV_SELF_TEST_OK
EV_SELF_TEST_FAIL
EV_WEAR_ON
EV_WEAR_OFF
EV_SEND_INTERVAL
EV_UWB_SEND_OK
EV_UWB_SEND_FAIL
EV_COMMAND_ALARM_ON
EV_COMMAND_ALARM_OFF
EV_BATTERY_LOW
EV_FAULT
```

狀態轉移範例：

```text
INIT_HW + EV_HW_READY → SELF_TEST
SELF_TEST + EV_SELF_TEST_OK → IDLE_NOT_WORN
IDLE_NOT_WORN + EV_WEAR_ON → ACTIVE_WORN
ACTIVE_WORN + EV_SEND_INTERVAL → UWB_TX
UWB_TX + EV_UWB_SEND_OK → WAIT_COMMAND
WAIT_COMMAND + EV_COMMAND_ALARM_ON → ALARM
ALARM + EV_COMMAND_ALARM_OFF → ACTIVE_WORN
任意狀態 + EV_FAULT → FAULT
```

## 4. UWB payload 格式

安全帽傳給基站的 payload，第一版建議使用固定長度 binary。這比 JSON 更適合 UWB，封包較短、解析較快。

### UWB Packet Header

| 欄位 | 長度 | 說明 |
|---|---:|---|
| `magic` | 2 bytes | 固定值，例如 `0xA55A` |
| `version` | 1 byte | 協定版本，第一版為 `1` |
| `packet_type` | 1 byte | 封包類型 |
| `sequence` | 2 bytes | 封包序號 |
| `src_id` | 4 bytes | 來源 ID，例如 H001 |
| `dst_id` | 4 bytes | 目標 ID，例如 A001 或 broadcast |
| `payload_len` | 1 byte | payload 長度 |
| `payload` | N bytes | 實際資料 |
| `crc16` | 2 bytes | CRC 檢查 |

### packet_type

```text
0x01 HELMET_STATUS
0x02 HELMET_ACK
0x10 BASE_COMMAND
0x11 BASE_ACK
```

### HELMET_STATUS payload

| 欄位 | 長度 | 範例 | 說明 |
|---|---:|---|---|
| `helmet_id` | 4 bytes | `H001` | 安全帽 ID |
| `battery_level` | 1 byte | `85` | 0~100 |
| `wearing_status` | 1 byte | `1` | 1=已配戴，0=未配戴 |
| `fall_detected` | 1 byte | `0` | 第一版可固定 0 |
| `alert_state` | 1 byte | `0` | 0=無警示，1=警示中 |
| `uptime_s` | 4 bytes | `1234` | 開機秒數 |

語意等同：

```json
{
  "helmet_id": "H001",
  "battery_level": 85,
  "wearing_status": true,
  "fall_detected": false,
  "alert_state": 0,
  "uptime_s": 1234
}
```

以上欄位是安全帽韌體與 UWB 通訊使用的內部格式，不是基站送往後端的 HTTP JSON 格式：

- 舊設備識別欄位僅屬已棄用韌體／UWB 內部格式，現行 HTTP JSON 不接受該欄位。
- `wearing_status` 是舊內部欄位；現行 HTTP JSON 對應欄位為 `safety_belt`。
- `battery_level` 對應 HTTP JSON 的 `battery`。
- 基站負責將 UWB 內部格式轉換成 `/api/locations` 使用的新 HTTP JSON 格式。

## 5. command 格式

基站傳給安全帽的 command 用於控制警示。

### BASE_COMMAND payload

| 欄位 | 長度 | 範例 | 說明 |
|---|---:|---|---|
| `command_id` | 2 bytes | `1001` | 指令序號，避免重複執行 |
| `command_type` | 1 byte | `1` | 指令類型 |
| `duration_ms` | 2 bytes | `5000` | 警示持續時間 |
| `alarm_pattern` | 1 byte | `2` | 警示模式 |
| `alarm_level` | 1 byte | `3` | 強度等級 |

### command_type

```text
0x01 ALARM_ON
0x02 ALARM_OFF
0x03 STATUS_REQUEST
0x04 CONFIG_UPDATE
```

### alarm_pattern

```text
0x00 OFF
0x01 CONTINUOUS
0x02 SLOW_PULSE
0x03 FAST_PULSE
0x04 EMERGENCY
```

安全帽收到 command 後應回 ACK：

```text
HELMET_ACK payload
command_id    2 bytes
result        1 byte    0=OK, 1=unknown command, 2=busy, 3=error
```

## 6. 每個模組的責任

### `helmet_app`

負責安全帽主流程。

```text
初始化所有模組
定期呼叫 sensor update
定期送 UWB status
處理 command
驅動狀態機
```

### `helmet_state_machine`

負責狀態轉移。

```text
根據 wearing_status 決定 IDLE / ACTIVE
根據 battery_level 決定 LOW_BATTERY
根據 command 決定 ALARM
根據 UWB 錯誤進入 FAULT
```

### `battery_monitor`

負責電量。

```text
讀 ADC
轉換電壓
換算 battery_level 0~100
判斷低電量
```

### `wear_detector`

負責配戴狀態。

```text
讀 GPIO 或感測器
做 debounce
輸出 wearing_status true / false
```

### `alert_controller`

負責警示輸出。

```text
控制蜂鳴器
控制 LED
控制震動馬達
執行不同 alarm_pattern
處理 duration_ms
```

### `device_identity`

負責 ID。

```text
讀取 helmet_id
可先寫死 H001
未來可從 NVS / EEPROM / Flash 讀取
```

### `uwb_packet`

負責封包編碼與解碼。

```text
組 HELMET_STATUS payload
解析 BASE_COMMAND payload
產生 crc16
檢查 magic / version / payload_len
```

### `uwb_interface`

負責抽象 UWB 通訊。

```text
init()
send(packet)
receive(packet)
available()
setReceiveMode()
```

第一版可用 mock，之後再接真實 DW3000 library。

### `drivers`

負責硬體操作。

```text
gpio_driver：GPIO 讀寫
adc_driver：ADC 讀取
buzzer_driver：蜂鳴器
led_driver：LED
vibration_driver：震動馬達
```

## 7. 之後接 DW3000 library 時要替換哪些地方

之後接真實 DW3000 時，主要替換以下模組：

```text
modules/uwb/uwb_mock.cpp
modules/uwb/uwb_mock.h
```

新增：

```text
modules/uwb/dw3000_uwb.cpp
modules/uwb/dw3000_uwb.h
```

但保留共同介面：

```cpp
class IUwbRadio {
public:
  virtual bool init() = 0;
  virtual bool send(const uint8_t* data, uint16_t length) = 0;
  virtual bool receive(uint8_t* buffer, uint16_t maxLength, uint16_t* outLength) = 0;
  virtual bool available() = 0;
};
```

需要替換的內容：

| 模組 | 第一版 | 接 DW3000 後 |
|---|---|---|
| `uwb_mock` | 假傳送、假接收 | 移除或只留測試用 |
| `dw3000_uwb` | 無 | 呼叫真實 DW3000 library |
| `board_config` | 可先只設定 GPIO | 增加 SPI pin、IRQ pin、RST pin |
| `helmet_app` | 不需大改 | 透過 `IUwbRadio` 使用新 driver |
| `uwb_packet` | 保留 | 保留 |
| `command_protocol` | 保留 | 保留 |

DW3000 driver 需要處理：

```text
SPI 初始化
DW3000 reset
DW3000 config
TX frame
RX frame
RX timeout
IRQ interrupt
timestamp 讀取
錯誤狀態 recovery
```

主程式不應直接呼叫 DW3000 library。正確方式是：

```text
helmet_app
  ↓
IUwbRadio interface
  ↓
dw3000_uwb implementation
  ↓
DW3000 library
```

這樣未來如果 DW3000 library 更換，或 MCU 從 ESP32-S3 換成 STM32，只需要改 `dw3000_uwb` 和 `platform/`，不用重寫整個安全帽流程。
