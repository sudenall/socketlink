# SocketLink Protokol Spesifikasyonu (v1)

> **Sahibi:** Sude · **Durum:** Taslak → 1. haftanın sonunda grup onayıyla "Dondurulmuş"
>
> Bu doküman bütün ekibin uyduğu **sözleşmedir**. Server, client, UDP katmanı, dosya transferi ve testler bu dosyaya göre yazılır. Kodda bu dokümanla çelişen bir şey varsa **doküman doğrudur**, kod düzeltilir. Protokolde bir değişiklik gerekiyorsa önce bu dosya PR ile değiştirilir, sonra kod.

---

## 1. Genel bakış

- Uygulama katmanı protokolü; hem **TCP** hem **UDP** üzerinde aynı paket formatıyla çalışır.
- Her mesaj bir **paket**tir: sabit 22 byte'lık **başlık (header)** + değişken uzunlukta **içerik (payload)**.
- Bütün sayılar **network byte order** (big-endian, `struct` formatında `!`).
- Metin her zaman **UTF-8**.
- Kontrol ve sohbet mesajlarının payload'ı **JSON**; dosya parçalarının payload'ı **ham byte**.

## 2. Paket formatı

```
 0       2       3       4       5       6              10             14             18             22
 +-------+-------+-------+-------+-------+--------------+--------------+--------------+--------------+------------
 | magic |version| type  | flags |reservd|     seq      |     ack      |    length    |   checksum   | payload...
 | "SL"  |  1B   |  1B   |  1B   |  1B   |   uint32     |   uint32     |   uint32     |   uint32     | length B
 +-------+-------+-------+-------+-------+--------------+--------------+--------------+--------------+------------
```

`struct` formatı: `HEADER_FORMAT = "!2sBBBBIIII"` → `HEADER_SIZE = 22`

| Alan | Boyut | Açıklama |
|---|---|---|
| `magic` | 2 B | Her zaman `b"SL"`. Farklıysa → `MalformedPacketError` |
| `version` | 1 B | `PROTOCOL_VERSION = 1`. Farklıysa → `VersionMismatchError` |
| `type` | 1 B | `MessageType` değeri (bölüm 3) |
| `flags` | 1 B | `PacketFlag` bitleri: `ACK_REQUIRED=1`, `RETRANSMISSION=2` |
| `reserved` | 1 B | Her zaman 0 (ileride kullanım için) |
| `seq` | 4 B | Sıra numarası. TCP'de bilgi amaçlı, UDP'de zorunlu (bölüm 6). ACK paketlerinde 0 |
| `ack` | 4 B | Yalnızca `ACK` paketinde anlamlı: alınan son sıralı paketin `seq` değeri |
| `length` | 4 B | Payload uzunluğu (byte). En fazla `MAX_PAYLOAD_SIZE = 60000` |
| `checksum` | 4 B | `zlib.crc32(header_checksum_alanı_0_iken + payload) & 0xFFFFFFFF` |

### 2.1 Checksum hesaplama
1. Header'ı `checksum = 0` ile paketle.
2. `crc = zlib.crc32(header + payload) & 0xFFFFFFFF`
3. Header'ı `checksum = crc` ile tekrar paketle.

Alıcı aynı işlemi yapar; sonuç farklıysa `BadChecksumError` → paket **atılır**, `checksum_errors` sayacı artar, `PACKET_CORRUPTED` olayı yayınlanır. Bağlantı **kapatılmaz**.

### 2.2 TCP'de çerçeveleme (framing)
TCP bir byte akışıdır, mesaj sınırlarını korumaz. Bu yüzden alıcı **her zaman**:
1. Tam olarak `HEADER_SIZE` byte okur (`recv` daha az döndürebilir → döngüyle tamamla: `_recv_exact(n)`),
2. `Packet.parse_header()` ile `length` değerini alır,
3. Tam olarak `length` byte daha okur,
4. `Packet.decode(header + payload)` çağırır.

`recv()` boş `b""` döndürürse karşı taraf bağlantıyı kapatmıştır → `ConnectionClosedError`.

### 2.3 UDP'de çerçeveleme
Bir UDP datagramı = bir paket. Ek çerçeveleme yok. Datagram boyutu `HEADER_SIZE + length` ile tutmuyorsa → `MalformedPacketError`.

## 3. Mesaj tipleri

| Değer | İsim | Yön | Payload | Kısa açıklama |
|---|---|---|---|---|
| 1 | `HELLO` | C→S | JSON | Bağlantıdan sonraki **ilk** paket; kullanıcı adı bildirir |
| 2 | `WELCOME` | S→C | JSON | HELLO kabul edildi |
| 3 | `CHAT` | C↔S | JSON | Sohbet mesajı (herkese veya tek kişiye) |
| 4 | `ACK` | ↔ | boş | Alındı bildirimi (yalnızca UDP modunda) |
| 5 | `PING` | C→S | boş | Heartbeat |
| 6 | `PONG` | S→C | boş | Heartbeat cevabı |
| 7 | `USER_LIST` | S→C | JSON | Çevrimiçi kullanıcılar (her giriş/çıkışta herkese) |
| 8 | `FILE_START` | C→S→C | JSON | Dosya transferi başlıyor |
| 9 | `FILE_CHUNK` | C→S→C | ham | Dosya parçası |
| 10 | `FILE_END` | C→S→C | JSON | Dosya transferi bitti |
| 11 | `ERROR` | S→C | JSON | Hata bildirimi |
| 12 | `BYE` | ↔ | JSON | Düzgün bağlantı kapatma |

> Değerler **asla** yeniden numaralandırılmaz. Yeni tip gerekirse 13'ten devam edilir.

## 4. Payload şemaları (JSON)

Alan isimleri **snake_case** ve tam olarak aşağıdaki gibidir. `timestamp` her zaman Unix zamanı (saniye, `float`, `time.time()`).

```jsonc
// HELLO (C→S)
{ "username": "sude" }

// WELCOME (S→C)
{ "client_id": 7, "server_name": "SocketLink Server", "users": ["sude", "yusuf"] }

// CHAT  (C→S)  -- to = null => herkese
{ "text": "Merhaba!", "to": null }

// CHAT  (S→C)  -- sunucu "from" ve "timestamp" ekler
{ "text": "Merhaba!", "to": null, "from": "sude", "timestamp": 1760688000.123 }

// USER_LIST (S→C)
{ "users": ["hamit", "sude", "yusuf"] }        // alfabetik sıralı

// FILE_START (C→S→C)
{ "transfer_id": 3, "filename": "notes.pdf", "size": 48213,
  "total_chunks": 48, "checksum": 2882382797, "to": "yusuf", "from": "sude" }
// "from" alanını sunucu ekler; "checksum" = bütün dosyanın CRC32'si

// FILE_END (C→S→C)
{ "transfer_id": 3 }

// ERROR (S→C)
{ "code": "USERNAME_TAKEN", "message": "Username 'sude' is already in use." }

// BYE (↔)
{ "reason": "client_quit" }    // client_quit | server_shutdown | kicked_by_admin | timeout
```

**FILE_CHUNK payload (ham):**
```
struct.pack("!II", transfer_id, chunk_index) + data      # data <= FILE_CHUNK_SIZE (1024) byte
```
`chunk_index` 0'dan başlar.

### 4.1 Kurallar
- Kullanıcı adı: `^[A-Za-z0-9_]{3,16}$`, büyük/küçük harf duyarsız benzersiz (`Sude` ve `sude` aynı kişi).
- `text`: boş olamaz, en fazla `MAX_CHAT_LENGTH = 2000` karakter.
- `transfer_id`: gönderen client tarafından üretilir, o client için benzersiz (1'den başlayan sayaç). Sunucu tarafında `(from, transfer_id)` çifti benzersizdir.
- Bilinmeyen JSON alanları **yok sayılır** (ileriye uyumluluk). Eksik zorunlu alan → `MALFORMED_PACKET`.

## 5. Akışlar (sequence)

### 5.1 Bağlanma
```
Client                         Server
  |--- (TCP connect / ilk UDP datagramı) --->|
  |--- HELLO {username} -------------------->|  doğrula
  |<-- WELCOME {client_id, users} -----------|  başarılıysa
  |<-- USER_LIST (herkese) ------------------|
        veya
  |<-- ERROR {USERNAME_TAKEN} ---------------|  ardından sunucu bağlantıyı kapatır
```
- HELLO'dan önce gelen başka herhangi bir paket → `ERROR NOT_AUTHENTICATED` + bağlantı kapatılır.
- Sunucu doluysa (`MAX_CLIENTS`) → `ERROR SERVER_FULL` + kapat.
- Client, `CONNECT_TIMEOUT` içinde WELCOME/ERROR almazsa bağlantıyı kapatır ve `ERROR` olayı yayınlar.

### 5.2 Sohbet
```
A --- CHAT {text, to:null} ---> S --- CHAT {text, to:null, from:A, ts} ---> herkes (A dahil)
A --- CHAT {text, to:"B"} ----> S --- CHAT {..., from:A}               ---> B ve A
                                  (B yoksa)  ERROR {UNKNOWN_USER}       ---> A
```
Sunucu mesajı gönderene de geri yollar: böylece herkesin ekranında aynı zaman damgası ve sıra görünür.

### 5.3 Heartbeat
- Client her `HEARTBEAT_INTERVAL = 5 s`'de `PING` gönderir, sunucu `PONG` döner. PING→PONG süresi RTT ölçümüdür (`avg_rtt_ms`).
- Herhangi bir paket gelmesi "canlılık" sayılır. `CONNECTION_TIMEOUT = 15 s` boyunca hiçbir paket gelmezse taraf bağlantıyı ölü kabul eder.
- Sunucu ölü client'ı listeden çıkarır (`CLIENT_LEFT reason=timeout`) ve `USER_LIST` yayınlar.

### 5.4 Dosya transferi
```
A --- FILE_START {to:B, size, total_chunks, checksum} ---> S ---> B   (S "from" ekler)
A --- FILE_CHUNK (0) ------------------------------------> S ---> B
A --- FILE_CHUNK (1..n-1) -------------------------------> S ---> B
A --- FILE_END ------------------------------------------> S ---> B   B: parça sayısı + CRC32 kontrolü → kaydet
```
- Sunucu dosyayı **saklamaz**, yalnızca iletir (relay). `to` boş olamaz (dosya herkese gönderilmez).
- `size > MAX_FILE_SIZE` ise gönderen hiç başlamaz (`ValidationError`).
- Alıcı dosya adını `Path(filename).name` ile temizler (dizin saldırısı önlemi).
- CRC uyuşmazlığı veya eksik parça → dosya yazılmaz, `FILE_FAILED`.

### 5.5 Kapatma
- Düzgün kapatma: `BYE {reason}` gönder → soketi kapat.
- Sunucu kapanırken herkese `BYE {server_shutdown}` gönderir.
- Beklenmedik kopma (`ConnectionResetError`, `recv == b""`, timeout): istisna yakalanır, olay yayınlanır, program **çökmez**. Client `auto_reconnect=True` ise `RECONNECT_DELAYS` ile yeniden dener.

## 6. Güvenilir UDP (Go-Back-N)

TCP modunda TCP zaten güvenilirlik sağlar; uygulama seviyesinde **ACK kullanılmaz**. UDP modunda güvenilirliği `ReliableUdpTransport` sağlar:

**Gönderici**
- `next_seq` 1'den başlar. Her veri paketi (`ACK` hariç her tip) `seq = next_seq`, `flags |= ACK_REQUIRED` alır, `next_seq += 1`.
- En fazla `window_size` (varsayılan 4; 1 = Stop-and-Wait) adet ACK'lenmemiş paket olabilir. Pencere doluysa `send()` bekler.
- `base` = ACK'lenmemiş en eski paket. Zamanlayıcı `base` için çalışır.
- `ACK(ack=n)` gelince `n`'e kadar (dahil) bütün paketler onaylanmış sayılır (cumulative). `base = n + 1`.
- `RETRANSMIT_TIMEOUT = 0.5 s` dolarsa pencerenin **tamamı** yeniden gönderilir (`flags |= RETRANSMISSION`), `retransmissions` artar, `PACKET_RETRANSMITTED` yayınlanır.
- Aynı paket için `MAX_RETRIES = 8` aşılırsa → bağlantı kapatılır, `TransportTimeoutError`.

**Alıcı**
- `expected_seq` 1'den başlar.
- `seq == expected_seq` → paket kabul edilir, üst katmana verilir, `expected_seq += 1`.
- Diğer her durumda (sıra dışı veya tekrar) paket **atılır**; tekrar ise `duplicates_received` artar.
- Her veri paketinden sonra `ACK(ack = expected_seq - 1)` gönderilir.

**Kayıp simülasyonu**
- `LossSimulator`, `sendto()` çağrısından hemen önce uygulanır (hem veri hem ACK paketlerine).
- Atılan paket `packets_dropped_simulated` sayacını artırır ve `PACKET_DROPPED` olayı yayınlanır.

**Sunucu tarafı (demultiplexing)**
- Tek UDP soketi, bir `udp-demux` thread'i. Her datagram kaynak adresine `(ip, port)` göre ilgili client'ın transport'una yönlendirilir.
- Tanınmayan adresten gelen ilk paket `HELLO` ise yeni bir `ReliableUdpTransport` oluşturulur ve `accept()` onu döndürür; değilse atılır.

## 7. Hata kodları

"Python hatası" sütunu, `transport.receive()` / `Packet.decode()` çağıran kodun **hangi exception'ı yakalayacağını** gösterir. `—` olan satırlar paket ayrıştırma hatası değil, sunucunun kendi kuralıdır (exception yok; sunucu doğrudan `ERROR` paketi üretir).

| Kod | Ne zaman | Python hatası | Sunucu ne yapar |
|---|---|---|---|
| `BAD_CHECKSUM` | Checksum tutmadı | `BadChecksumError` — **TCP transport'u içinde yakalanır**, `receive()` fırlatmaz: paket atılır, `checksum_errors` artar, `PACKET_CORRUPTED` yayınlanır | Paketi atar, bağlantı açık kalır |
| `MALFORMED_PACKET` | Magic/uzunluk/tip/JSON hatalı | `MalformedPacketError` (`receive()`, `Packet.decode()` veya `json_payload()`) | Hata bildirir; aynı client'tan 5 kez üst üste → kapatır. TCP'de başlık bozuksa akış hizalanamaz, bu yüzden pratikte kapatmak en güvenlisi |
| `VERSION_MISMATCH` | Farklı protokol sürümü | `VersionMismatchError` (`receive()`) | Hata bildirir, kapatır |
| `NOT_AUTHENTICATED` | HELLO'dan önce başka paket | — | Hata bildirir, kapatır |
| `INVALID_USERNAME` | Kural dışı kullanıcı adı | — (`ValidationError` yalnızca client tarafındaki girdi kontrolünde) | Hata bildirir, kapatır |
| `USERNAME_TAKEN` | Ad kullanımda | — | Hata bildirir, kapatır |
| `UNKNOWN_USER` | `to` kullanıcısı yok | — | Yalnızca hata bildirir |
| `PAYLOAD_TOO_LARGE` | `length > MAX_PAYLOAD_SIZE` | `PayloadTooLargeError` (`receive()` başlıkta yakalar, payload'u okumaz; `send()` ve `encode()` da fırlatır) | Hata bildirir, kapatır (TCP akışı artık güvenilmez) |
| `SERVER_FULL` | `MAX_CLIENTS` doldu | — | Hata bildirir, kapatır |
| `FILE_REJECTED` | Dosya kurallara uymuyor | — | Yalnızca hata bildirir |
| `INTERNAL_ERROR` | Beklenmeyen sunucu hatası | herhangi biri | Loglar, hata bildirir |

### 7.1 Bağlantı durumu hataları (`receive()` / `send()`)
Bunlar protokol hatası değil, **bağlantı durumudur**; `ERROR` paketine karşılık gelmezler.

| Python hatası | Anlamı | Ne yapılır |
|---|---|---|
| `TransportTimeoutError` | `receive(timeout)` süresinde tam paket gelmedi | Hata değil; döngüye devam et, `CONNECTION_TIMEOUT` kontrolünü yap. Yarım gelen byte'lar kaybolmaz |
| `ConnectionClosedError` | Karşı taraf kapattı, bağlantı koptu veya `close()` çağrıldı | Client'ı listeden çıkar (`CLIENT_LEFT`) / yeniden bağlan |

## 8. Değişiklik geçmişi

| Sürüm | Tarih | Kim | Değişiklik |
|---|---|---|---|
| v1-draft | 2026-10-17 | Sude | İlk taslak |
| v1-draft | 2026-10-19 | Sude | §7: her hata kodu için "Python hatası" sütunu, §7.1 bağlantı durumu hataları eklendi (davranış değişmedi) |
