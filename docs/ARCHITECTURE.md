# SocketLink Mimari Dokümanı

> **Sahibi:** Sude · Bu dosyadaki diyagramlar GitHub'da otomatik çizilir (Mermaid). Rapordaki resmi diyagramları Nevin draw.io ile bunlardan türetir (`docs/diagrams/`).

---

## 1. Katmanlar

```mermaid
flowchart TB
    subgraph L4["Sunum katmanı — gui/"]
        CG["client_gui.py<br/>ClientApp (İlayda)"]
        SG["server_gui.py<br/>ServerApp (Tina)"]
        TH["theme.py"]
    end
    subgraph L3["Uygulama katmanı"]
        CC["client/client.py<br/>ChatClient (Hamit)"]
        CS["server/server.py<br/>ChatServer + ClientHandler (Yusuf)"]
        FT["transfer/file_transfer.py<br/>FileSender / FileReceiver (Tina)"]
    end
    subgraph L2["Taşıma katmanı (Strategy)"]
        TI["common/transport.py<br/>Transport · TransportListener<br/>TcpTransport · TcpListener (Sude)"]
        RU["reliability/reliable_udp.py<br/>ReliableUdpTransport · Listener (Yiğit)"]
        LS["reliability/loss_simulator.py (Yiğit)"]
    end
    subgraph L1["Ortak çekirdek — common/"]
        PR["protocol.py — Packet + make_* (Sude)"]
        EV["events.py — EventBus (Sude)"]
        CO["constants.py · exceptions.py · stats.py (Sude)"]
        CF["config.py · logger.py (Nevin)"]
    end
    CG --> CC
    SG --> CS
    CC --> FT
    CC --> TI
    CS --> TI
    TI -.UDP modu.-> RU
    RU --> LS
    TI --> PR
    RU --> PR
    CC -.publish.-> EV
    CS -.publish.-> EV
    EV -.queue.-> CG
    EV -.queue.-> SG
```

### 1.1 Import kuralları (döngüsel import ve çakışmayı önler)

| Modül | Import EDEBİLİR | Import EDEMEZ |
|---|---|---|
| `common/*` | yalnızca `common/*` ve standart kütüphane | `server`, `client`, `gui`, `transfer` (tek istisna: `transport.py` içindeki fabrika fonksiyonlarının **fonksiyon içinden** `reliability`'yi import etmesi) |
| `reliability/*` | `common/*` | `server`, `client`, `gui`, `transfer` |
| `transfer/*` | `common/*` | `server`, `client`, `gui` |
| `server/*`, `client/*` | `common/*`, `transfer/*` | `gui/*`, birbirleri |
| `gui/*` | hepsi | — |

**Altın kural:** `gui` dışındaki hiçbir dosya `tkinter` import etmez. Çekirdek kod GUI'den tamamen bağımsızdır ve terminalden/testlerden çalışabilir.

---

## 2. Tasarım desenleri (hocanın "design code pattern" şartı)

| Desen | Nerede | Neden | Raporda |
|---|---|---|---|
| **Strategy** | `Transport` arayüzü; `TcpTransport` ve `ReliableUdpTransport` | Sunucu/client kodu değişmeden TCP ↔ UDP geçişi | 3.6.13 |
| **Observer** | `EventBus` (`events.py`) | Ağ çekirdeği GUI'yi tanımadan olay yayınlar; GUI abone olur | 3.6.12, 3.6.13 |
| **State** | `ConnectionState` + `STATE_TRANSITIONS`, `ChatClient._set_state()` | Geçersiz durum geçişlerini engeller (ör. bağlı değilken mesaj göndermek) | 3.6.13 |
| **Factory Method** | `protocol.make_*()`, `create_transport()`, `create_listener()` | Paketler ve transport'lar tek yerden, tutarlı oluşturulur | 3.6.13 |
| **Thread-per-client** (eşzamanlılık deseni) | `ClientHandler(threading.Thread)` | Her client bağımsız; bir client yavaşsa diğerleri etkilenmez | 3.4, 3.11 |
| **Producer–Consumer** | `EventBus.subscribe_queue()` + `root.after()` | Network thread'leri üretir, GUI ana thread'i tüketir (Tkinter thread-safe değil) | 3.6.12 |

---

## 3. Thread modeli

```mermaid
flowchart LR
    subgraph Server process
        A["srv-accept<br/>listener.accept()"] -->|yeni Transport| H1["srv-client-sude<br/>ClientHandler"]
        A --> H2["srv-client-yusuf<br/>ClientHandler"]
        W["srv-watchdog<br/>sessiz client'ları at"]
        D["udp-demux<br/>(yalnızca UDP)"] -.datagram.-> H1
        D -.datagram.-> H2
        GUI1["Tk main thread<br/>ServerApp"]
    end
    subgraph Client process
        C1["cli-connect"] --> R["cli-receiver<br/>transport.receive()"]
        HB["cli-heartbeat<br/>PING / 5 s"]
        RT["udp-retransmit<br/>(yalnızca UDP)"]
        GUI2["Tk main thread<br/>ClientApp"]
    end
    H1 <-->|packets| R
```

Kurallar:
1. Bütün thread'ler `daemon=True` ve **isimli** (`name="srv-accept"` vb.). Log'larda `%(threadName)s` görünür.
2. Her döngü `while not self._stop_event.is_set():` ile döner; bloklayan çağrılar `SOCKET_TIMEOUT` (1 s) ile çağrılır ki durdurma isteği en geç 1 saniyede fark edilsin.
3. Paylaşılan her `dict`/`list` bir `threading.Lock` ile korunur. **Kilit tutulurken ağ üzerinden gönderim yapılmaz** (kopyala → bırak → gönder).
4. Aynı sokete birden fazla thread yazabiliyorsa `send()` içinde bir `_send_lock` kullanılır.
5. Network thread'i **asla** Tkinter widget'ına dokunmaz.

---

## 4. Client durum makinesi (State pattern)

```mermaid
stateDiagram-v2
    [*] --> DISCONNECTED
    DISCONNECTED --> CONNECTING: connect()
    CONNECTING --> CONNECTED: WELCOME alındı
    CONNECTING --> DISCONNECTED: ERROR / timeout / reddedildi
    CONNECTED --> DISCONNECTING: disconnect()
    CONNECTED --> RECONNECTING: bağlantı koptu (auto_reconnect)
    RECONNECTING --> CONNECTED: yeniden bağlandı
    RECONNECTING --> DISCONNECTED: denemeler bitti
    DISCONNECTING --> DISCONNECTED: BYE gönderildi, soket kapandı
```

GUI butonları duruma göre aktif/pasif olur: ör. `send_chat` yalnızca `CONNECTED` durumunda; Connect butonu yalnızca `DISCONNECTED` durumunda.

---

## 5. Bir mesajın yolculuğu (uçtan uca)

```mermaid
sequenceDiagram
    participant UI as ClientApp (Tk)
    participant C as ChatClient
    participant T as Transport
    participant H as ClientHandler (server)
    participant S as ChatServer
    participant C2 as Diğer client
    UI->>C: send_chat("Merhaba", to=None)
    C->>T: send(make_chat(...))
    T->>H: [header|payload] (TCP veya güvenilir UDP)
    H->>S: broadcast(make_chat(..., sender, ts))
    S->>C2: CHAT
    S->>T: CHAT (gönderene de geri)
    T->>C: receive() → Packet
    C-->>UI: EventBus → queue → MESSAGE_RECEIVED
    Note over UI: root.after(50 ms) kuyruğu okur, ekrana yazar
```

---

## 6. Güvenilir UDP — kayıp ve yeniden gönderim (rapor için alt diyagram adayı)

```mermaid
sequenceDiagram
    participant S as Gönderici (window=4)
    participant R as Alıcı
    S->>R: seq=1
    S->>R: seq=2
    S-xR: seq=3 (LossSimulator attı)
    S->>R: seq=4
    R->>S: ACK 1
    R->>S: ACK 2
    R->>S: ACK 2 (seq=4 sıra dışı → atıldı)
    Note over S: 0.5 s timeout (base=3)
    S->>R: seq=3 (RETRANSMISSION)
    S->>R: seq=4 (RETRANSMISSION)
    R->>S: ACK 3
    R->>S: ACK 4
```

---

## 7. Genel API özeti (imzalar dondurulmuştur)

Bu imzalar iskelet dosyalarda tanımlıdır. **İsim, parametre sırası ve dönüş tipi değiştirilmez**; gerekirse önce sahibine ve Sude'ye danışılır, ardından bu tablo güncellenir.

### `ChatClient` (Hamit → İlayda kullanır)
| Metod | Döner | Sonuç olayı |
|---|---|---|
| `connect(config=None)` | `None` (hemen) | `CONNECTED` veya `ERROR` |
| `disconnect()` | `None` | `DISCONNECTED` |
| `send_chat(text, to=None)` | `None` | `MESSAGE_SENT`, sonra sunucudan `MESSAGE_RECEIVED` |
| `send_file(path, to)` | `int` transfer_id | `FILE_PROGRESS`… `FILE_COMPLETED`/`FILE_FAILED` |
| `get_stats()` | `dict` | — |
| `set_network_conditions(loss_rate, delay_ms)` | `None` | — |
| `state` (property) | `ConnectionState` | `STATE_CHANGED` |

### `ChatServer` (Yusuf → Tina kullanır)
| Metod | Döner | Sonuç olayı |
|---|---|---|
| `start()` | `None` | `SERVER_STARTED` |
| `stop()` | `None` | `SERVER_STOPPED` |
| `is_running` (property) | `bool` | — |
| `get_clients()` | `list[ClientInfo]` | — |
| `kick(username, reason)` | `None` | `CLIENT_LEFT` |
| `get_stats()` | `dict` | — |
| `set_network_conditions(loss_rate, delay_ms)` | `None` | — |

### `Transport` (Sude/Yiğit → Yusuf, Hamit, Tina kullanır)
`send(packet)`, `receive(timeout)`, `close()`, `peer_address`, `is_open`, `stats`, `set_network_conditions(loss_rate, delay_ms)`

### Olay veri sözleşmesi
Her olay tipinin `data` sözlüğünde bulunması zorunlu anahtarlar `common/events.py` içindeki `EVENT_DATA_KEYS` tablosundadır. Testler (`Event.validate()`) bunu kontrol eder.
