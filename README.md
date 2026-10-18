# SocketLink

**COME413 Computer Networks — Course Project: Socket Programming in Python**
Üsküdar Üniversitesi · 8 kişilik grup projesi

SocketLink, Python ile yazılmış, client-server mimarisinde çalışan çok kullanıcılı bir **mesajlaşma ve dosya transferi uygulaması** ve aynı zamanda bir **ağ simülatörüdür**. Kendi uygulama katmanı protokolünü hem **TCP** hem de kendi yazdığımız **güvenilir UDP** (Go-Back-N) üzerinde çalıştırır. GUI'den yapay paket kaybı ve gecikme verilerek, kayıplara rağmen verinin doğru ve sıralı teslim edildiği canlı olarak izlenebilir.

> ### 👋 Repoya yeni geldiysen, bu sırayla oku
> 1. Bu README'nin tamamı (özellikle **§3 Ekip**, **§7 senin görev kartın**, **§9 kodlama kuralları**)
> 2. [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) — hocanın ne istediği ve puanların kime düştüğü
> 3. [`docs/PROTOCOL.md`](docs/PROTOCOL.md) — herkesin uyduğu paket formatı (sözleşme)
> 4. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — sınıflar, thread'ler, diyagramlar
> 5. [`CONTRIBUTING.md`](CONTRIBUTING.md) — Git ile nasıl çalışacağız
> 6. Rapor yazıyorsan: [`docs/REPORT_GUIDE.md`](docs/REPORT_GUIDE.md)

---

## İçindekiler

1. [Proje hakkında](#1-proje-hakkında)
2. [Hoca ne istiyor? (özet)](#2-hoca-ne-istiyor-özet)
3. [Ekip, roller ve yönetim](#3-ekip-roller-ve-yönetim)
4. [Mimari özet](#4-mimari-özet)
5. [Ortam kurulumu ve çalıştırma](#5-ortam-kurulumu-ve-çalıştırma)
6. [Repo yapısı ve klasör sahipleri](#6-repo-yapısı-ve-klasör-sahipleri)
7. [Kişi kişi görev kartları](#7-kişi-kişi-görev-kartları)
8. [Tasarım kararları (karar kaydı)](#8-tasarım-kararları-karar-kaydı)
9. [Kodlama kuralları ve isimlendirme](#9-kodlama-kuralları-ve-isimlendirme)
10. [Çakışmaları önleme önlemleri](#10-çakışmaları-önleme-önlemleri)
11. [İletişim ve senkronizasyon](#11-iletişim-ve-senkronizasyon)
12. [Rapor](#12-rapor)
13. [Test ve ölçüm stratejisi](#13-test-ve-ölçüm-stratejisi)
14. [Takvim](#14-takvim)
15. [Definition of Done (bitti ne demek?)](#15-definition-of-done-bitti-ne-demek)
16. [Takım anlaşması](#16-takım-anlaşması)
17. [İlk gün kurulum listesi](#17-ilk-gün-kurulum-listesi)
18. [Sık sorulan sorular](#18-sık-sorulan-sorular)
19. [Linkler](#19-linkler)

---

## 1. Proje hakkında

### 1.1 Ne yapıyoruz?
Önerimizdeki (`docs/references/project-proposal-form.pdf`) hedef: *"reliable, scalable, and interactive network communication application based on a client-server architecture"*. Bunu şu ürünle karşılıyoruz:

| Özellik | Açıklama |
|---|---|
| **Sunucu + dashboard** | Bir port açar, çok sayıda client'ı aynı anda kabul eder, mesajları yönlendirir, bağlı client'ları ve trafiği canlı gösterir |
| **Client penceresi** | IP/port/kullanıcı adı girip bağlanır; herkese veya kişiye mesaj, dosya gönderme |
| **İki taşıma modu** | TCP (işletim sistemi güvenilirlik sağlar) ve güvenilir UDP (güvenilirliği **biz** sağlıyoruz) |
| **Ağ simülasyonu** | UDP modunda % paket kaybı, ms gecikme ve pencere boyutu GUI'den ayarlanır |
| **Gözlemlenebilirlik** | Canlı paket log'u (gönderildi / alındı / düştü / yeniden gönderildi), istatistikler, RTT |
| **Hata toleransı** | Kopma, timeout, bozuk paket, aynı kullanıcı adı… program çökmez, kullanıcıya anlaşılır mesaj verir |

### 1.2 Demo senaryosu (final sunumunda gösterilecek)
1. Sunucu TCP modunda başlatılır; 3 client (`alice`, `bob`, `carol`) bağlanır.
2. Herkese ve özel mesajlaşma; kullanıcı listesi güncellenir.
3. `alice` → `bob` dosya gönderir; ilerleme çubuğu, CRC doğrulaması.
4. Bir client'ın penceresi zorla kapatılır → sunucu bunu fark eder, listeden çıkarır.
5. Sunucu UDP modunda yeniden başlatılır; kayıp %20 yapılır → paket log'unda kırmızı (düşen) ve turuncu (yeniden gönderilen) satırlar, mesajlar yine eksiksiz ve sıralı gelir.
6. Pencere boyutu 1 ↔ 4 değiştirilip Stop-and-Wait ile Go-Back-N farkı istatistiklerde gösterilir.
7. Sunucu kapatılır → client'lar "reconnecting" durumuna geçer, çökmez.

---

## 2. Hoca ne istiyor? (özet)

Ayrıntılı ve eksiksiz hali: **[`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md)**. Orijinal belgeler: [`docs/references/`](docs/references/).

| Bölüm | Puan | Ne |
|---|---|---|
| **Part #1** | **70** | Yazılı tasarım: Feasibility Study (20), Network Needs Analysis (20), High-Level Network Design (20), Detailed Design Documentation (10) |
| **Part #2** | **30** | *"Write a complete GUI program to simulate the above proposal title."* |

Hoca ayrıca iki şey istiyor:
- *"You will be writing a specific design code pattern"* → tasarım desenlerimiz §8 ve [`ARCHITECTURE.md` §2](docs/ARCHITECTURE.md).
- Rapor, şablondaki bölümlerle yazılacak (Chapter 1 Introduction, 2 Literature Review **≥ 20 makale, 2014+**, 3 Methodology, 4 Testing & Results, 5 Conclusion) ve katı format kurallarına uyacak (Times New Roman 12, 1.5 satır, sol kenar 4 cm…).

> **Önemli:** Puanın **%70'i rapordan** geliyor. Kod ne kadar iyi olursa olsun rapor zayıfsa not düşer. Bu yüzden **herkesin hem kod hem rapor görevi var** ve ikisi paralel ilerliyor.

---

## 3. Ekip, roller ve yönetim

| Kişi | Rol | Kod sahipliği | Rapor (kriter puanı) |
|---|---|---|---|
| **Sude Ünal** | 🟣 **Lider & Protokol** · Kod ekibi koordinatörü | `common/protocol.py`, `transport.py` (TCP), ortak sözleşme dosyaları | FS-1, FS-2, FS-5, NNA-8, DDD-1 (ortak) + 1.2, 1.6.2, 3.6.13 |
| **Yiğit Efe Kılıç** | 🔵 **Güvenilir UDP & Literatür** · Hocayla resmi iletişim | `reliability/` | FS-6 + 1.1, **Chapter 2**, 3.1–3.3, 3.5 |
| **Mehmet Yusuf İzci** | 🟢 **Sunucu** | `server/` | FS-4, NNA-3, NNA-4, DDD-1 (ortak) + 3.4 |
| **Hamit İşcioğlu** | 🟡 **Client & Hata Yönetimi** | `client/` | FS-7, NNA-6, NNA-7 + 3.9 |
| **İlayda Yalçınöz** | 🟠 **Client GUI** | `gui/client_gui.py`, `gui/theme.py` | FS-3, HLD-4 + 1.9, 3.10, 4.1 (ortak) |
| **Tina Türkay** | 🔴 **Sunucu Paneli & Dosya Transferi** | `gui/server_gui.py`, `transfer/` | NNA-1, NNA-2, NNA-5 + 1.8, 4.1 (ortak) |
| **Meryem Kaşıkçı** | ⚪ **Test & Ölçüm** | `tests/`, `benchmarks/`, `results/` | DDD-2 + 3.7, 3.8, 4.3, 4.4 |
| **Nevin Malkoç** | 🟤 **Dokümantasyon & Diyagramlar** · Rapor ekibi koordinatörü | `common/config.py`, `common/logger.py`, `docs/` | HLD-1, HLD-2, HLD-3 + Abstract, Chapter 5, format, kaynakça |

Kriter kodları (FS-1, NNA-8…) → [`docs/REQUIREMENTS.md` §2](docs/REQUIREMENTS.md#2-part-1--kriter-kriter-eşleme).
**Literatür:** herkes kendi konusunda **3 makale** (toplam 24, 4 yedek) — konular [`REPORT_GUIDE.md` §3](docs/REPORT_GUIDE.md#literatür-konu-dağılımı-kişi-başı-3-makale).

### 3.1 Karar ve yönetim yapısı
- **Sude:** Genel koordinasyon, haftalık toplantıyı yönetir, kod ekibinin takılmalarını çözer, `main`'e son merge, ortak sözleşme dosyalarının onayı.
- **Nevin:** Rapor ekibinin koordinasyonu; rapor iskeleti, format, son düzenleme.
- **Yiğit:** Proje formunda grup lideri olarak kayıtlı → **hocayla resmi iletişim** onda. Hocaya sorulacak sorular `#hoca-sorular` kanalında toplanır, Yiğit toplu iletir.
- **Anlaşmazlık:** Önce ilgili iki kişi → olmazsa ekip koordinatörü → olmazsa haftalık toplantıda oylama (eşitlikte Sude'nin oyu belirler).

### 3.2 Bağımlılık haritası (kim kimi bekliyor?)
```
                        Sude (protocol.py + TcpTransport + PROTOCOL.md)
                      /            |                 \
             Yusuf (server)   Hamit (client)   Yiğit (reliable UDP)
                  |                |
          Tina (server GUI)   İlayda (client GUI) ← Tina (file_transfer, client'a da gerekir)
                   \               /
                    Meryem (testler, ölçümler)
                              |
              Nevin (diyagramlar, rapor son hali)
```
- **Sude'nin 1. hafta çıktısı herkesin önünde.** `PROTOCOL.md` ve `protocol.py` 1. haftanın sonunda bitmezse herkes gecikir.
- Kimse boş beklemez: GUI'ler **sahte (mock) olaylarla**, Meryem **test senaryolarıyla**, Nevin **Mermaid'den diyagram taslaklarıyla** başlar.

---

## 4. Mimari özet

Tam hali, diyagramlarıyla: **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**

```
┌───────────────────────────── gui/ (Tkinter, yalnızca ana thread) ─────────────────────────────┐
│   ClientApp (İlayda)                                       ServerApp (Tina)                  │
└──────────▲────────────────────────────────────────────────────────▲──────────────────────────┘
           │ queue ← EventBus (Observer)                            │ queue ← EventBus
┌──────────┴──────────────┐   ┌──────────────────────┐   ┌──────────┴───────────────────────────┐
│ ChatClient (Hamit)      │──▶│ FileSender/Receiver  │   │ ChatServer + ClientHandler (Yusuf)   │
│ State: ConnectionState  │   │ (Tina)               │   │ thread-per-client                    │
└──────────┬──────────────┘   └──────────────────────┘   └──────────┬───────────────────────────┘
           │            Transport / TransportListener  (Strategy)   │
     ┌─────┴───────────────────────────┬────────────────────────────┴───┐
     │ TcpTransport, TcpListener (Sude)│ ReliableUdpTransport/Listener   │
     │                                 │ + LossSimulator (Yiğit)         │
     └─────────────────┬───────────────┴───────────────┬─────────────────┘
                       │  Packet + make_*() (Factory) — protocol.py (Sude)
                       ▼
           22 B header [magic|ver|type|flags|rsv|seq|ack|len|crc32] + payload (JSON / ham)
```

Üç cümlede:
1. **Çekirdek GUI'yi tanımaz.** `ChatClient`/`ChatServer` olayları `EventBus`'a yayınlar; GUI bir kuyruktan okur (`root.after` ile). Bu sayede çekirdek terminalden ve testlerden çalışır.
2. **Sunucu ve client hangi modda olduklarını bilmez.** Yalnızca `Transport` arayüzüyle konuşurlar; TCP ↔ UDP seçimi tek bir fabrika fonksiyonunda yapılır.
3. **Her paket aynı formattadır**, her yerde aynı `make_*()` fonksiyonlarıyla oluşturulur.

---

## 5. Ortam kurulumu ve çalıştırma

### 5.1 Gereksinimler

| Ne | Sürüm | Not |
|---|---|---|
| **Python** | **3.10 veya üstü** (önerilen 3.12) | `python --version` ile kontrol et. Kodda 3.10+ sözdizimi var (`str \| None`) |
| **Tkinter** | Python ile gelir | Kontrol: `python -m tkinter` → küçük bir pencere açılmalı |
| **Git** | herhangi güncel | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| **Editör** | VS Code önerilir | Eklentiler: *Python*, *Ruff*, *Draw.io Integration* (Nevin), *Markdown Preview Mermaid Support* |
| Wireshark | opsiyonel (Meryem zorunlu) | Paket yakalama kanıtı için |

**Uygulamanın çalışması için hiçbir pip paketi gerekmez** (yalnızca standart kütüphane, tasarım kararı D-01). Pip paketleri yalnızca geliştirme ve test içindir.

#### İşletim sistemine özel notlar
- **Windows:** python.org yükleyicisinde *"Add Python to PATH"* işaretle. Komutlarda `python` yerine `py` gerekebilir. İlk sunucu açılışında **Windows Güvenlik Duvarı** izin sorar → *Özel ağlar* için izin ver (başka bilgisayarlardan bağlanmak için şart).
- **macOS:** Homebrew Python kullanıyorsan Tkinter ayrıca kurulur: `brew install python-tk@3.12`. Port **5000 kullanılmaz** (AirPlay kullanıyor) → varsayılan portumuz **5050**.
- **Linux (Ubuntu/Debian):** `sudo apt install python3-tk python3-venv`
- **Wireshark + localhost:** Windows'ta kurulumda **Npcap**'i *"Support loopback traffic"* seçeneğiyle kur; arayüz olarak *"Adapter for loopback traffic capture"* seç. macOS/Linux'ta `lo0`/`lo`. Filtre: `tcp.port == 5050 || udp.port == 5050`.

### 5.2 Kurulum (her geliştirici, bir kez)
```bash
git clone https://github.com/<sude-kullanici-adi>/socketlink.git
cd socketlink

python -m venv .venv
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# Windows (Git Bash):    source .venv/Scripts/activate
# macOS / Linux:         source .venv/bin/activate

pip install -r requirements-dev.txt
python -m pytest          # 19 smoke testi geçmeli
ruff check .              # "All checks passed!"
```
`.venv` klasörü `.gitignore`'da; **asla commit'lenmez**.

### 5.3 Çalıştırma
Komutlar **repo kök klasöründen** çalıştırılır (yoksa `import socketlink` bulunamaz):
```bash
python run_server.py      # sunucu dashboard'u
python run_client.py      # bir client penceresi — birden fazla kullanıcı için birkaç kez aç
```
- Aynı bilgisayarda test: client'ta host `127.0.0.1`, port `5050`.
- Farklı bilgisayarlar (aynı Wi-Fi): sunucu bind host `0.0.0.0`; client'lar sunucunun yerel IP'sini girer (Windows `ipconfig`, macOS/Linux `ipconfig getifaddr en0` / `ip addr`).
- Okul/yurt ağları genelde cihazlar arası trafiği engeller; uzaktan ortak test için herkes **kendi bilgisayarında localhost** ile çalışır, entegrasyon demosu ekran paylaşımıyla yapılır.

### 5.4 Testler
```bash
python -m pytest                       # hepsi
python -m pytest -m "not slow"         # hızlılar (CI bunu çalıştırır)
python -m pytest tests/test_protocol.py -v
```
Her PR'da GitHub Actions (`.github/workflows/ci.yml`) Windows ve Ubuntu'da, Python 3.10 ve 3.12 ile `ruff` + `pytest` çalıştırır. **CI kırmızıysa merge yok.**

---

## 6. Repo yapısı ve klasör sahipleri

```
socketlink/
├── README.md                     ← bu dosya (Sude + Nevin)
├── CONTRIBUTING.md               ← Git iş akışı
├── pyproject.toml                ← ruff + pytest ayarları
├── requirements-dev.txt          ← yalnızca geliştirme araçları
├── run_server.py / run_client.py ← giriş noktaları (dokunma)
│
├── socketlink/                   ← UYGULAMA KODU (Python paketi)
│   ├── common/
│   │   ├── constants.py          🟣 Sude    ✅ hazır — bütün sabitler ve enum'lar
│   │   ├── exceptions.py         🟣 Sude    ✅ hazır — hata sınıfları
│   │   ├── events.py             🟣 Sude    ✅ hazır — EventBus + olay sözleşmesi
│   │   ├── stats.py              🟣 Sude    ✅ hazır — TransportStats
│   │   ├── protocol.py           🟣 Sude    🔲 iskelet — Packet, encode/decode, make_*()
│   │   ├── transport.py          🟣 Sude    🔲 iskelet — arayüzler ✅, TCP 🔲
│   │   ├── config.py             🟤 Nevin   🔲 iskelet — ServerConfig, ClientConfig
│   │   └── logger.py             🟤 Nevin   ⚙️ çalışan temel sürüm
│   ├── server/server.py          🟢 Yusuf   🔲 iskelet
│   ├── client/client.py          🟡 Hamit   🔲 iskelet
│   ├── reliability/
│   │   ├── reliable_udp.py       🔵 Yiğit   🔲 iskelet
│   │   └── loss_simulator.py     🔵 Yiğit   🔲 iskelet
│   ├── transfer/file_transfer.py 🔴 Tina    🔲 iskelet
│   └── gui/
│       ├── theme.py              🟠 İlayda (+Tina onayı) ✅ hazır — renk, font
│       ├── client_gui.py         🟠 İlayda  🔲 iskelet
│       └── server_gui.py         🔴 Tina    🔲 iskelet
│
├── tests/                        ⚪ Meryem (herkes kendi modülünün unit testini ekler)
├── benchmarks/                   ⚪ Meryem — ölçüm scriptleri
├── results/                      ⚪ Meryem — rapora giren CSV/PNG (ham veriler results/raw/, ignore)
│
├── docs/                         🟤 Nevin
│   ├── REQUIREMENTS.md           ← hocanın kriterleri + eşleme
│   ├── PROTOCOL.md               🟣 Sude — protokol sözleşmesi
│   ├── ARCHITECTURE.md           🟣 Sude — mimari, thread'ler, API
│   ├── REPORT_GUIDE.md           ← rapor yazım kuralları
│   ├── diagrams/                 ← draw.io kaynakları + PNG'ler (rapordaki şekiller)
│   └── references/               ← hocanın belgeleri (değiştirme)
│
└── .github/
    ├── workflows/ci.yml          ← otomatik test
    ├── PULL_REQUEST_TEMPLATE.md
    ├── ISSUE_TEMPLATE/task.md
    └── CODEOWNERS                ← klasör sahipleri (PR'da otomatik reviewer)
```

**İskelet ne demek?** Sınıf ve metod isimleri, parametreleri, dönüş tipleri ve ne yapmaları gerektiği (docstring) **zaten yazılı**; gövdeleri `raise NotImplementedError("TODO(isim)")`. Sen gövdeyi dolduruyorsun. **İsimleri ve imzaları değiştirmiyorsun** — başkaları onlara göre kod yazıyor.

---

## 7. Kişi kişi görev kartları

Her kartta: kod görevleri (checklist), rapor görevleri, kimden ne bekliyorsun, kime ne teslim ediyorsun, kod eşin ve rapor eşin. Haftalar §14'teki takvime göre. Görevler GitHub Projects'te issue olarak da açılır; burada kapalı kutu işaretlemek gerekmez.

### 🟣 Sude — Lider & Protokol

**Kod**
- [ ] **H1** `docs/PROTOCOL.md`'yi gözden geçir, grupla 1. hafta toplantısında **dondur** (v1)
- [ ] **H1** `protocol.py`: `Packet.encode()`, `Packet.decode()`, `Packet.parse_header()`, `json_payload()`, `summary()` ve bütün `make_*()` fabrikaları
- [ ] **H1** `tests/test_protocol.py`: her mesaj tipi için encode→decode gidiş-dönüş, bozuk checksum, yanlış magic, yanlış sürüm, fazla büyük payload
- [ ] **H2** `transport.py`: `TcpTransport` (`connect`, `_recv_exact(n)` ile framing, thread-safe `send` için `_send_lock`, `close` idempotent) ve `TcpListener` (`bound_address` dahil)
- [ ] **H2** `tests/test_tcp_transport.py`: port 0 ile gerçek localhost bağlantısı, parça parça gelen veri, karşı taraf kapanınca `ConnectionClosedError`
- [ ] **H1** Repo kurulumu: collaborator davetleri, `CODEOWNERS`'a gerçek kullanıcı adları, GitHub Projects panosu, (mümkünse) `main` koruması
- [ ] Sürekli: PR'ları son merge, ortak dosya değişiklik isteklerini değerlendir

**Rapor:** 1.2 Project Description · 1.5 Objectives (**FS-2**, 3) · 1.6.1 Scope (**FS-1**, 2) · 1.6.2 Limitations · 1.7 Proposed Solution (**FS-5**, 5) · 3.6.8 Architecture (**NNA-8**, 3) · 3.6.13 Design Patterns · 3.11 Discussion (**DDD-1**, Yusuf ile)
**Literatür:** application-layer protocol design, serialization
**Teslim ettiğin:** `protocol.py` + `TcpTransport` → Yusuf, Hamit, Yiğit · **Bekledığın:** —
**Kod eşi:** Yiğit · **Rapor eşi:** Meryem

### 🔵 Yiğit — Güvenilir UDP & Literatür

**Kod**
- [ ] **H2** `loss_simulator.py`: `should_drop()`, `delay_seconds()`; seed'li `random.Random` ile test edilebilir
- [ ] **H2–3** `ReliableUdpTransport`: Go-Back-N gönderici (pencere, `base`, zamanlayıcı, pencerenin tamamını yeniden gönderme, `MAX_RETRIES`), alıcı (`expected_seq`, kümülatif ACK, tekrar/sıra dışı atma), `set_network_conditions`, `set_window_size`
- [ ] **H3** `ReliableUdpListener`: tek soket + `udp-demux` thread'i, adrese göre yönlendirme, HELLO ile yeni oturum, `bound_address`
- [ ] **H3** İstatistikler: `retransmissions`, `packets_dropped_simulated`, `duplicates_received`; olaylar: `PACKET_DROPPED`, `PACKET_RETRANSMITTED`
- [ ] **H3** `tests/test_reliable_udp.py`: %0/%10/%30 kayıpla 200 paket → hepsi, sırayla, bir kez; pencere 1 ve 4; `MAX_RETRIES` aşımı
- [ ] **H6** Meryem'e UDP ölçüm verisi (kayıp oranı × retransmission × süre)

**Rapor:** 1.1 Background · 1.3 Industry (**FS-6**, 3) · **Chapter 2 Literature Review** (24 özeti birleştirip konulara göre akıcı metin) · 3.1 · 3.2 Research Gap · 3.3 Current Techniques · 3.5 Proposed Algorithm
**Literatür:** reliable data transfer over UDP, ARQ
**Teslim ettiğin:** `ReliableUdpTransport` → Yusuf/Hamit (aynı arayüz, kod değiştirmeden çalışmalı) · **Bekledığın:** Sude (`protocol.py`)
**Kod eşi:** Sude · **Rapor eşi:** Nevin · **Ek:** hocayla resmi iletişim

### 🟢 Yusuf — Sunucu

**Kod**
- [ ] **H2** `ChatServer.start/stop/is_running`; `srv-accept` thread'i (`listener.accept(timeout=SOCKET_TIMEOUT)` döngüsü)
- [ ] **H2** `ClientHandler.run/handle_packet/send`: ilk paket HELLO kontrolü, CHAT yönlendirme (herkese / özel / `UNKNOWN_USER`), PING→PONG, BYE
- [ ] **H2** `register/unregister`: kullanıcı adı doğrulama (regex, büyük/küçük harf duyarsız benzersizlik, `MAX_CLIENTS`), WELCOME, `USER_LIST` yayını, `CLIENT_JOINED/LEFT` olayları
- [ ] **H3** `srv-watchdog`: `CONNECTION_TIMEOUT` boyunca sessiz client'ları at (`reason=timeout`)
- [ ] **H3** FILE_* paketlerini `to` kullanıcısına aktarma (saklamadan, `from` ekleyerek)
- [ ] **H3** `get_clients`, `kick`, `get_stats`, `set_network_conditions`; saniyede bir `STATS_UPDATED`
- [ ] **H3** `tests/test_server.py`: 3 client'lı yayın, özel mesaj, aynı ad reddi, HELLO'suz paket reddi, `stop()` sırasında bağlı client'lar

**Rapor:** 1.6.3 Design Assumptions (**FS-4**, 3) · 3.4 Comparing Approaches · 3.6.3 Users & Priority (**NNA-3**, 2) · 3.6.4 Transmission Speed (**NNA-4**, 3) · 3.11 Discussion (**DDD-1**, Sude ile)
**Literatür:** concurrent server architectures
**Teslim ettiğin:** `ChatServer` API → Tina · **Bekledığın:** Sude (`TcpTransport`, `TcpListener`)
**Kod eşi:** Hamit · **Rapor eşi:** İlayda

### 🟡 Hamit — Client & Hata Yönetimi

**Kod**
- [ ] **H1 sonu** İlayda'ya `ChatClient` API'sinin hazır olduğunu teyit et (iskelette zaten tanımlı; değişiklik gerekiyorsa şimdi konuş)
- [ ] **H2** `_set_state` (State pattern, `STATE_TRANSITIONS` kontrolü), `connect` (arka plan thread'i, HELLO→WELCOME/ERROR, `CONNECT_TIMEOUT`), `disconnect`
- [ ] **H2** `send_chat` (doğrulama), `_receive_loop` (tipe göre dağıtım, olay yayını)
- [ ] **H3** `_heartbeat_loop` (PING, RTT ölçümü), `_handle_connection_lost` (`RECONNECT_DELAYS` ile yeniden bağlanma)
- [ ] **H3** Hata yakalama: `ConnectionRefusedError`, `ConnectionResetError`, `TimeoutError`, `ProtocolError` alt sınıfları, `ERROR` paketleri → hepsi olay olarak, çökme yok
- [ ] **H5** `send_file` (Tina'nın `FileSender`'ını kullanarak) ve gelen FILE_* paketlerini `FileReceiver`'a aktarma
- [ ] **H3** `tests/test_client.py`: kapalı sunucuya bağlanma, sunucu düşünce RECONNECTING, geçersiz durumda `send_chat` → `InvalidStateError`

**Rapor:** 1.4 Problem Statement (**FS-7**, 2) · 3.6.6 Reliability (**NNA-6**, 3) · 3.6.7 Security (**NNA-7**, 2) · 3.9 Error Compounding Testing
**Literatür:** fault tolerance, failure detection
**Teslim ettiğin:** `ChatClient` API → İlayda · **Bekledığın:** Sude (`TcpTransport`), Tina (`file_transfer`, H5)
**Kod eşi:** Yusuf · **Rapor eşi:** Tina

### 🟠 İlayda — Client GUI

**Kod**
- [ ] **H2** Arayüz iskeleti ve yerleşim (`build_ui`), yalnızca `theme.py` değerleriyle
- [ ] **H2** **Mock modu:** gerçek client olmadan test için sahte olay üreten küçük bir fonksiyon (`EventBus`'a `MESSAGE_RECEIVED`, `PACKET_DROPPED`… basar). Gerçek kod gelince kaldırılmaz, `--demo` bayrağıyla kalabilir
- [ ] **H2** `_poll_events` (`get_nowait` döngüsü + `root.after(GUI_POLL_INTERVAL_MS)`) ve `_handle_event`
- [ ] **H2–3** Bağlantı paneli (host, port, username, TCP/UDP, Connect/Disconnect, renkli durum), sohbet paneli, alıcı seçimi, kullanıcı listesi
- [ ] **H3** Ağ simülasyonu paneli (yalnızca UDP'de aktif): kayıp % (0–50), gecikme ms (0–1000), pencere (1–32) → `set_network_conditions`
- [ ] **H3** İstatistik paneli ve renkli **paket log'u** (son 500 satır tutulur)
- [ ] **H5** Gerçek `ChatClient`'a bağlama; dosya seçme diyaloğu + ilerleme çubuğu
- [ ] **H5** Hata mesajları kullanıcı dostu (`messagebox`), girdi doğrulama hatası alan yanında gösterilir; `on_close` temiz kapanış

**Rapor:** 1.2.1 Intended Users (**FS-3**, 2) · 1.9.1 Hardware · 1.9.2 Software · 3.6.12 Integration & Functioning (**HLD-4**, 5) · 3.10 Presentation of Output · 4.1 Prototype (Tina ile, ekran görüntüleri)
**Literatür:** network simulation / visualization tools for education
**Teslim ettiğin:** ekran görüntüleri → Nevin, Meryem · **Bekledığın:** Hamit (`ChatClient`)
**Kod eşi:** Tina · **Rapor eşi:** Yusuf
<!-- okudum: İlayda Yalçınöz, 18.10.2026 -->
### 🔴 Tina — Sunucu Paneli & Dosya Transferi

**Kod**
- [ ] **H2** `server_gui.py` iskeleti; İlayda ile **aynı tema ve aynı mock yaklaşımı**
- [ ] **H2–3** Kontrol paneli (bind host, port, mod, Start/Stop), `ttk.Treeview` client tablosu, sağ tık → Kick, canlı log, toplam istatistikler, ağ simülasyonu paneli
- [ ] **H3** `file_transfer.py`: `FileSender` (boyut kontrolü, CRC32, parçalama, ilerleme olayları en fazla ~10/s, `cancel`) ve `FileReceiver` (parça toplama, sayı + CRC doğrulama, güvenli dosya adı, çakışan adlara `" (1)"`)
- [ ] **H3** `tests/test_file_transfer.py`: 0 byte, 1 parça, 1 MB, eksik parça, bozuk CRC, `../../evil.txt` adı
- [ ] **H5** Gerçek `ChatServer`'a bağlama; Hamit ile client tarafı dosya akışının entegrasyonu

**Rapor:** 1.8 Software Development Model · 3.6.1 Data Types (**NNA-1**, 2) · 3.6.2 Data Sources (**NNA-2**, 3) · 3.6.5 Storage (**NNA-5**, 2) · 4.1 Prototype (İlayda ile)
**Literatür:** file transfer over networks, network monitoring
**Teslim ettiğin:** `FileSender/FileReceiver` → Hamit · **Bekledığın:** Yusuf (`ChatServer`), Sude (`make_file_*`)
**Kod eşi:** İlayda · **Rapor eşi:** Hamit

### ⚪ Meryem — Test & Ölçüm

**Kod**
- [ ] **H1** `tests/conftest.py`: ortak fixture'lar → port 0 ile sunucu başlatan `running_server`, `event_bus`, olay bekleyen `wait_for_event(q, EventType, timeout)` yardımcı fonksiyonu
- [ ] **H2** Test senaryo listesini (§13.2) issue'lara dönüştür, sahiplerle paylaş
- [ ] **H4** `tests/test_integration.py`: uçtan uca (sunucu + 3 client) TCP ve UDP modunda
- [ ] **H5** `benchmarks/`: gecikme (mesaj gönderim→alım), throughput (1/10 MB dosya), kayıp oranı taraması (0–30%, pencere 1/4/8), yük testi (10/25/50 client), CPU/bellek (psutil). Her script `results/<ad>.csv` yazar, her ölçüm **5 tekrar**, ortalama ± standart sapma
- [ ] **H6** Grafikler (`results/*.png`, matplotlib — yalnızca benchmark ortamında) ve Wireshark ekran görüntüleri (handshake, paket başlığı, retransmission)
- [ ] Sürekli: CI kırmızıya döndüğünde ilk müdahale eden kişi

**Rapor:** 3.7 Experimental Design · 3.8 Measurement & Data Analysis · 4.2 Design Approach Testing (**DDD-2**, 5) · 4.3 Verification & Validation · 4.4 Discussion of Results
**Literatür:** network performance measurement, testing networked software
**Teslim ettiğin:** grafikler ve tablolar → Nevin, rapor · **Bekledığın:** herkesin modülü (başta senaryolar ve fixture'larla başla)
**Kod eşi:** Nevin · **Rapor eşi:** Sude

### 🟤 Nevin — Dokümantasyon, Diyagramlar & Rapor Editörü

**Kod**
- [ ] **H2** `config.py`: `validate()` (IP `ipaddress` ile, port 1024–65535, kullanıcı adı regex, kayıp/pencere aralıkları → `ValidationError`), opsiyonel `from_args()`
- [ ] **H2** `logger.py`: `RotatingFileHandler`, `EventBusLogHandler` (sunucu panelindeki canlı log için)
- [ ] **H6** README'ye son kullanıcı için kısa *"How to run"* bölümü (İngilizce) ve ekran görüntüleri

**Rapor**
- [ ] **H1** Google Docs rapor şablonu: format kuralları stillere işlenmiş, bütün başlıklar sahibinin adıyla, kapak, içindekiler; Google Sheets durum tablosu ve kaynak tablosu
- [ ] **H3–4** 3.6.9 Top-Level (**HLD-1**, 5) · 3.6.10 Detailed (**HLD-2**, 5) · 3.6.11 Sub-Diagram (**HLD-3**, 5) — `docs/diagrams/`, [`REPORT_GUIDE.md` §5](docs/REPORT_GUIDE.md) kurallarıyla
- [ ] **H4** Phase 1 son düzenleme: tek üslup, terim sözlüğü, şekil/tablo numaraları, kaynakça numaralandırma, Rubric Mapping tablosu
- [ ] **H7** Abstract · Chapter 5 · listeler · Ek A katkı tablosu · Ek B kurulum · final format kontrolü

**Literatür:** client-server architecture modelling
**Teslim ettiğin:** rapor şablonu → herkes (H1) · **Bekledığın:** Sude (mimari), Meryem (sonuçlar)
**Kod eşi:** Meryem · **Rapor eşi:** Yiğit

---

## 8. Tasarım kararları (karar kaydı)

Bu kararlar **dondurulmuştur**; değiştirmek için toplantıda konuşulup bu tablo güncellenir. Raporda doğrudan kullanılır: "neden?" sütunu **FS-5** (strateji gerekçesi) ve **3.4** için, "bedeli" sütunu **DDD-1** (dezavantajlar) için hammaddedir.

| # | Karar | Neden? | Alternatif (neden değil) | Bedeli |
|---|---|---|---|---|
| D-01 | Python ≥ 3.10, **yalnızca standart kütüphane** | Hocanın bilgisayarında kurulum gerektirmeden çalışır; 8 kişide sürüm/paket çakışması olmaz | PyQt, asyncio kütüphaneleri (kurulum, lisans, öğrenme yükü) | Bazı kolaylıklardan vazgeçiyoruz |
| D-02 | GUI: **Tkinter** | Python ile gelir, yeterli widget seti, öğrenmesi kolay | PyQt/PySide (ağır, kurulum), web arayüzü (projenin odağı değil) | Görünüm daha sade; thread-safe değil (D-09 ile çözüldü) |
| D-03 | **İki taşıma modu**: TCP + güvenilir UDP, **Strategy** deseniyle | Önerideki "paket kaybı ve doğru sıra" sözünü gerçekten **bizim kodumuz** karşılar; "simulate" şartı için ideal | Yalnızca TCP (güvenilirliği göstermek imkânsız) | UDP katmanı ek iş ve test yükü |
| D-04 | **Sabit 22 B binary header** (`struct`) + **JSON** veya ham payload | Header hızlı ve sabit boyutlu (framing kolay); JSON okunabilir ve genişletilebilir; dosyalar için ham byte (verimli) | Satır sonlu düz metin (dosya taşıyamaz, sınır sorunu); `pickle` (**güvensiz**: ağdan gelen pickle kod çalıştırabilir) | JSON birkaç byte fazla |
| D-05 | **CRC32** checksum (`zlib`) her pakette | UDP modunda bozulma tespiti; TCP modunda da protokol hatası/yanlış istemci tespiti; hızlı | MD5/SHA (gereksiz yavaş, güvenlik amacı yok) | 4 B/paket |
| D-06 | **Thread-per-client** sunucu, `MAX_CLIENTS = 50` | Basit, okunur, hata ayıklaması kolay; ders kapsamında yeterli | `asyncio` (daha ölçeklenebilir ama öğrenme eğrisi), `select` (karmaşık) | GIL ve thread maliyeti → binlerce client'a ölçeklenmez |
| D-07 | Güvenilir UDP: **Go-Back-N**, kümülatif ACK, pencere varsayılan 4 (1 = Stop-and-Wait) | Ders kitabı algoritması, doğrulanabilir; pencere ayarıyla iki algoritma karşılaştırılabilir | Selective Repeat (daha verimli, alıcı tamponu ve karmaşıklık artar) | Kayıpta tüm pencere yeniden gönderilir → yüksek kayıpta verim düşer |
| D-08 | Sunucu **relay**: mesaj ve dosya **saklamaz** | Depolama ihtiyacı minimum (NNA-5), gizlilik, basitlik | Mesaj geçmişi veritabanı (kapsam dışı) | Çevrimdışı kullanıcıya mesaj iletilemez |
| D-09 | GUI entegrasyonu: **EventBus (Observer) + Queue + `root.after`** | Tkinter yalnızca ana thread'den güncellenebilir; çekirdek GUI'den bağımsız ve test edilebilir | Network thread'inden doğrudan widget güncelleme (rastgele çökme) | 50 ms'ye kadar görüntüleme gecikmesi |
| D-10 | Heartbeat 5 s / ölü kabul 15 s; yeniden bağlanma 1-2-4-8 s | Sessiz kopmalar (kablo, uyku modu) tespit edilir; ağ yükü ihmal edilebilir | TCP keepalive (varsayılanı saatler, ayarı işletim sistemine bağlı) | Kopma en geç 15 s'de fark edilir |
| D-11 | Varsayılan port **5050** | macOS'ta 5000 AirPlay'e ait; 1024 altı yönetici izni ister | 5000, 8080 (sık kullanılır) | — |
| D-12 | Kimlik doğrulama yok (yalnızca benzersiz kullanıcı adı), şifreleme yok; **girdi doğrulama, boyut sınırları, dosya adı temizleme var**. TLS → *future work* | Kapsamı yönetilebilir tutar; güvenlik gereksinimi (NNA-7) temel düzeyde karşılanır | `ssl` ile TLS (sertifika yönetimi, UDP'de DTLS standart kütüphanede yok) | Yerel ağ dışında güvenli değil — raporda **Limitations**'a yazılır |
| D-13 | Kod, yorumlar, commit mesajları ve rapor **İngilizce**; README ve iç dokümanlar Türkçe | Rapor ve kod uluslararası standart; ekip içi iletişim kolaylığı | — | — |
| D-14 | Tasarım desenleri: **Strategy, Observer, State, Factory Method, Thread-per-client, Producer–Consumer** | Hocanın "design code pattern" şartı; her biri gerçek bir problemi çözüyor ([`ARCHITECTURE.md` §2](docs/ARCHITECTURE.md)) | — | — |
| D-15 | Testlerde **port 0** (işletim sistemi boş port seçer) | Paralel testler ve CI'da "port in use" çakışması olmaz | Sabit test portu | — |
| D-16 | Rapor **Google Docs**, kaynak stili **IEEE**, diyagramlar **draw.io** | Eşzamanlı düzenleme, öneri modu, Word/PDF dışa aktarım | Word dosyası e-postayla (sürüm karmaşası), LaTeX (öğrenme yükü) | — |

**DDD-1 için başlangıç fikirleri** (Sude + Yusuf geliştirir):
- *Avantaj 1:* Strategy deseni sayesinde aynı uygulama hem TCP hem güvenilir UDP üzerinde değişiklik olmadan çalışır → iki taşıma yaklaşımı aynı koşullarda karşılaştırılabilir.
- *Avantaj 2:* Olay tabanlı (Observer) ayrım → ağ çekirdeği GUI olmadan test edilebilir; GUI donmaz.
- *Dezavantaj 1:* Thread-per-client modeli GIL ve thread maliyeti nedeniyle yüzlerce/binlerce eşzamanlı client'a ölçeklenmez (ölçüm: §13 yük testi).
- *Dezavantaj 2:* Go-Back-N yüksek kayıp oranlarında pencerenin tamamını yeniden gönderdiği için verimsizdir (ölçüm: kayıp taraması); ayrıca şifreleme olmaması yerel ağ dışında kullanımı kısıtlar.

---

## 9. Kodlama kuralları ve isimlendirme

### 9.1 İsimlendirme

| Ne | Kural | Örnek |
|---|---|---|
| Dosya / modül | `snake_case.py` | `file_transfer.py` |
| Sınıf | `PascalCase` | `ReliableUdpTransport`, `ChatClient` |
| Fonksiyon / metod / değişken | `snake_case`, fiille başlar | `send_chat()`, `handle_packet()`, `retry_count` |
| Özel (iç) metod/alan | `_` ile başlar | `_receive_loop()`, `_clients_lock` |
| Sabit | `UPPER_SNAKE_CASE`, **yalnızca** `constants.py`'de | `HEARTBEAT_INTERVAL` |
| Enum üyesi | `UPPER_SNAKE_CASE` | `MessageType.FILE_CHUNK` |
| Boolean | `is_`, `has_`, `should_`, `can_` | `is_open`, `should_drop()` |
| Thread adı | `<katman>-<görev>[-<kimlik>]` | `srv-accept`, `srv-client-alice`, `cli-heartbeat`, `udp-demux` |
| Test dosyası / fonksiyonu | `test_<modül>.py`, `test_<ne>_<koşul>_<beklenen>` | `test_decode_with_bad_checksum_raises()` |
| Olay `data` anahtarları | `snake_case`, `events.py`'deki sözleşmeyle **aynen** | `"done_bytes"`, `"total_bytes"` |
| JSON payload alanları | `snake_case`, `PROTOCOL.md` §4 ile **aynen** | `"transfer_id"`, `"client_id"` |
| Kısaltmalar sınıf adında | Yalnızca ilk harf büyük | `TcpTransport` ✅ `TCPTransport` ❌ |
| Dil | İngilizce, Türkçe karakter yok | `kullanici` ❌ `username` ✅ |

**Sabit kelime seti** (eş anlamlı kullanılmaz): `send` (≠ transmit/write), `receive` (≠ recv/get/read; düşük seviye soket çağrısı hariç), `packet` (≠ message/frame), `username` (≠ user/name/nick), `host` + `port` (≠ ip/address; birleşik hali `address: tuple[str, int]`), `transfer_id`, `client_id`.

### 9.2 Kod biçimi
- `ruff check .` temiz olmadan PR açılmaz. Satır uzunluğu 100.
- **Her** fonksiyonda tip ipuçları: `def send_to(self, username: str, packet: Packet) -> bool:`
- Her public sınıf ve metodda **docstring** (ne yapar, ne döner, hangi hatayı fırlatır).
- Her dosyanın başında: ne yaptığı, `OWNER:`, kimi kullandığı/kim tarafından kullanıldığı (iskeletlerdeki gibi).
- Dosya başına `from __future__ import annotations`.

### 9.3 Yasaklar ❌ → doğrusu ✅
| ❌ | ✅ |
|---|---|
| `print("connected")` | `log.info("Connected to %s:%d", host, port)` |
| `sock.connect(("127.0.0.1", 5050))` | `DEFAULT_HOST`, `DEFAULT_PORT`, config'ten |
| `time.sleep(0.5)` içinde sihirli sayı | `RETRANSMIT_TIMEOUT` |
| `except:` / `except Exception: pass` | En spesifik hata + log + `ERROR` olayı |
| `json.dumps({"txt": ...})` başka modülde | `make_chat(text=...)` |
| `if mode == "tcp":` (server/client içinde) | `create_transport(mode, ...)` |
| Network thread'inden `label.config(...)` | `bus.publish(Event(...))` → GUI kuyruktan okur |
| Kilit tutarken `transport.send()` | Listeyi kopyala, kilidi bırak, sonra gönder |
| `pickle.loads(data)` ağdan gelen veriyle | `Packet.decode()` |
| `open(filename_from_network, "wb")` | `Path(filename).name` ile temizle, `download_dir` altına |
| `import tkinter` `gui/` dışında | Yalnızca `gui/` |
| Yeni sabit/olay/mesaj tipini kendi dosyana eklemek | `constants.py` / `events.py` / `PROTOCOL.md`'ye PR (Sude onayı) |

### 9.4 Thread ve hata kuralları (özet; ayrıntı [`ARCHITECTURE.md` §3](docs/ARCHITECTURE.md))
1. Thread'ler `daemon=True`, isimli, `self._stop_event` ile durur; bloklayan çağrılar `SOCKET_TIMEOUT` ile.
2. Paylaşılan veri `threading.Lock` altında.
3. Bir network thread'inden **hiçbir istisna kaçmaz**: yakala → logla → `EventType.ERROR` yayınla → bağlantıyı düzgün kapat.
4. `close()` metodları **idempotent** (iki kez çağrılınca hata vermez).

### 9.5 Olay yayınlama örneği
```python
from socketlink.common.events import Event, EventType

self.event_bus.publish(Event(
    EventType.MESSAGE_RECEIVED,
    {"from": "alice", "to": None, "text": "hi", "timestamp": ts},
    source="client",
))
```
Zorunlu anahtarlar `EVENT_DATA_KEYS`'te; testlerde `event.validate()` ile kontrol edilir.

---

## 10. Çakışmaları önleme önlemleri

8 kişinin aynı kod tabanında birbirini ezmemesi için alınan önlemlerin tamamı:

| Risk | Önlem | Nerede |
|---|---|---|
| Aynı şeye farklı isim | Dondurulmuş iskelet imzaları + §9.1 isim tablosu + sabit kelime seti | §6, §9 |
| Paket formatı uyuşmazlığı | Tek spec (`PROTOCOL.md`) + tek kod (`make_*()`) + gidiş-dönüş testleri | `docs/PROTOCOL.md` |
| Sabitlerin dağılması | Bütün sayılar `constants.py`'de; sihirli sayı yasak | `constants.py` |
| Core ↔ GUI veri uyuşmazlığı | `EVENT_DATA_KEYS` sözleşmesi + `Event.validate()` | `events.py` |
| TCP/UDP'ye özel kodun yayılması | Strategy: mod kontrolü yalnızca `create_transport/create_listener`'da | `transport.py` |
| Döngüsel import | Katman import kuralları | `ARCHITECTURE.md` §1.1 |
| Aynı dosyada iki kişi | Klasör sahipliği + `CODEOWNERS` otomatik reviewer | §6, `.github/CODEOWNERS` |
| Ortak dosyada gelişigüzel değişiklik | Ortak sözleşme dosyaları yalnızca Sude onayıyla | `CONTRIBUTING.md` §2 |
| Birbirini bekleme | Bağımlılık haritası + mock modları + teslim mesajları | §3.2, §11 |
| Büyük, çakışmalı birleştirmeler | Küçük PR, 2-3 günde bir; PR öncesi `git merge origin/main` | `CONTRIBUTING.md` |
| Kırık kodun `main`'e girmesi | CI (ruff + pytest, 2 OS × 2 Python) + eş onayı | `.github/workflows/ci.yml` |
| "Bende çalışıyordu" | Stdlib-only, Python ≥ 3.10, `.venv`, CI matrisi | §5 |
| Test port çakışması | Testlerde port 0 + `bound_address` | D-15 |
| Rapor 8 farklı ses | Terim sözlüğü, üslup kuralları, tek editör (Nevin) | `REPORT_GUIDE.md` |
| Raporla kodun çelişmesi | Sayılar `constants.py`'den, diyagramlarda kod isimleri; değiştiren raporu da günceller | `REPORT_GUIDE.md` §2 |
| Bir kriterin unutulması | Kriter kodları (FS-1…DDD-2) + durum tablosu + Rubric Mapping | `REQUIREMENTS.md` |
| Aynı makaleyi iki kişinin eklemesi | Kaynak tablosunda DOI ile kontrol | `REPORT_GUIDE.md` §3 |
| Gözden kaçan iş yükü dengesizliği | Haftalık yük kontrolü + katkı tablosu | §16 |

---

## 11. İletişim ve senkronizasyon

### 11.1 Araçlar — her işin **tek** yeri var

| Ne | Nerede |
|---|---|
| Kod | Bu repo |
| Görevler | GitHub Projects panosu (sütunlar: *Backlog · This week · In progress · In review · Done*) |
| Durum tablosu (kriterler + modüller) | Google Sheets (§19) |
| Rapor | Google Docs (tek doküman, §19) |
| Kaynaklar | Google Sheets kaynak tablosu (§19) |
| Diyagramlar | `docs/diagrams/` (draw.io + PNG) |
| Konuşma | Discord sunucusu |

**Discord kanalları:** `#duyurular` (yalnızca Sude ve Yiğit yazar; kararlar ve tarihler) · `#günlük-güncelleme` · `#kod` · `#rapor` · `#yardım` · `#hoca-sorular` · `#github` (repo bildirimleri, webhook) · `#genel`

### 11.2 Ritim

**Her gün — yazılı güncelleme** (`#günlük-güncelleme`, 1 dakika):
```
Yusuf
Dün: accept loop + HELLO/WELCOME çalışıyor (PR #14)
Bugün: broadcast ve özel mesaj
Engel: yok
```

**Her hafta — toplantı** (sabit gün/saat, 30–40 dk, Sude yönetir):
1. Herkes 2 dakika: biten / bitmeyen / neden
2. Takılmalar
3. Entegrasyon kontrolü: `main` birlikte çalıştırılır (ekran paylaşımı)
4. Gelecek haftanın kartları; yük kontrolü
5. Kararlar → `#duyurular` (sözlü kalan karar unutulur)

Katılamayan güncellemesini **önceden** yazılı bırakır.

**Haftalık entegrasyon günü:** toplantıdan **bir gün önce** herkes o haftanın işini `main`'e merge etmiş olur.

**Anlık — teslim mesajı:** başkasının beklediği bir şey bitince ilgili kişi etiketlenir:
```
@İlayda ChatClient.connect / send_chat / disconnect main'de (PR #21). CONNECTED ve MESSAGE_RECEIVED olayları geliyor.
```

### 11.3 Eşleşmeler

| Kod eşleri (PR review + ilk yardım) | Rapor eşleri (çapraz okuma) |
|---|---|
| Sude ↔ Yiğit (protokol ↔ güvenilirlik) | Yiğit ↔ Nevin |
| Yusuf ↔ Hamit (server ↔ client) | Sude ↔ Meryem |
| İlayda ↔ Tina (iki GUI aynı görünmeli) | Yusuf ↔ İlayda |
| Meryem ↔ Nevin (test sonuçları ↔ rapor/diyagram) | Hamit ↔ Tina |

### 11.4 Takılma kuralı
**2 saatten fazla** takıldıysan: önce kod/rapor eşine, sonra `#yardım`'a. Mesajda: ne yapmaya çalıştın, ne oldu (hata mesajının **tamamı**), ne denedin.

---

## 12. Rapor

- **Nerede:** tek Google Docs dokümanı (link §19). Herkes yalnızca kendi başlığına yazar; başkasınınkine **öneri modu**.
- **Kurallar:** [`docs/REPORT_GUIDE.md`](docs/REPORT_GUIDE.md) (dil, terim sözlüğü, IEEE kaynak, şekil adları, diyagram stili, kalite listesi).
- **Kim neyi yazıyor:** [`docs/REQUIREMENTS.md` §5](docs/REQUIREMENTS.md#5-rapor-şablonunun-tam-iskeleti-ve-sahipleri) (başlık başlık).
- **Format (özet):** Times New Roman · metin 12, ana başlık 14 BÜYÜK kalın · satır 1.5 (kapak/abstract 1.0) · sol 4 cm, sağ 1.5 cm, üst/alt 2–2.5 cm · girintisiz, iki yana yaslı · her chapter yeni sayfa · sayfa no sağ alt · üçüncü şahıs.
- **Phase 1** = Chapter 1–3 (+ kapak, listeler, kaynakça) · **Phase 2** = Chapter 4–5 + Abstract + GUI programı.
- **Kod ↔ rapor bağı:** raporda geçen her sınıf adı, sabit değeri ve mesaj tipi bu repodakiyle **aynı** olmalı.

---

## 13. Test ve ölçüm stratejisi

### 13.1 Seviyeler
| Seviye | Kim yazar | Örnek | Rapor |
|---|---|---|---|
| Unit | Her modülün sahibi | `test_protocol.py`, `test_loss_simulator.py` | 4.2 |
| Integration | Meryem (+ sahipler) | Sunucu + 3 client, TCP ve UDP | 4.2, 4.3 |
| Fault injection | Hamit + Meryem | Kopma, timeout, bozuk paket, kayıp + gecikme birlikte | 3.9, 4.2 |
| Performance | Meryem | Gecikme, throughput, yük, kayıp taraması | 3.8, 4.4 |
| Manuel / demo | Herkes | §1.2 demo senaryosu, Wireshark | 4.1, 4.3 |

### 13.2 Test senaryoları (Meryem issue'lara dönüştürür)
| ID | Senaryo | Beklenen | Sahibi |
|---|---|---|---|
| T-01 | Her mesaj tipi encode → decode | Aynı paket | Sude |
| T-02 | Bir byte'ı değiştirilmiş paket | `BadChecksumError`, bağlantı açık | Sude |
| T-03 | TCP'de paketin 1'er byte gelmesi | Tek ve doğru paket | Sude |
| T-04 | 3 client, herkese mesaj | Hepsi aynı sırada alır | Yusuf |
| T-05 | Özel mesaj / olmayan kullanıcıya | Yalnızca hedef alır / `UNKNOWN_USER` | Yusuf |
| T-06 | Aynı kullanıcı adı (`Alice` vs `alice`) | `USERNAME_TAKEN` | Yusuf |
| T-07 | HELLO'suz CHAT | `NOT_AUTHENTICATED` + kapatma | Yusuf |
| T-08 | Kapalı sunucuya bağlanma | `ERROR` olayı, çökme yok | Hamit |
| T-09 | Bağlıyken sunucu kapatılır | RECONNECTING → denemeler | Hamit |
| T-10 | Client sessizce kaybolur (kill) | Sunucu ≤ 15 s'de çıkarır | Hamit |
| T-11 | UDP %0/10/20/30 kayıp, 500 mesaj | Hepsi, sırayla, bir kez | Yiğit |
| T-12 | Pencere 1 vs 4 vs 8, %10 kayıp | Süre ve retransmission karşılaştırması | Yiğit + Meryem |
| T-13 | `MAX_RETRIES` aşımı (%100 kayıp) | `TransportTimeoutError`, temiz kapanış | Yiğit |
| T-14 | 1 MB dosya, TCP ve UDP %10 kayıp | CRC eşleşir | Tina |
| T-15 | `../../evil.txt` dosya adı | `downloads/<user>/evil.txt` | Tina |
| T-16 | **Hata bileşimi:** %20 kayıp + 200 ms gecikme + transfer ortasında kopma | Çökme yok, `FILE_FAILED`, yeniden bağlanma | Hamit + Meryem |
| T-17 | 10 / 25 / 50 client yük | Ortalama gecikme, CPU, bellek | Meryem |
| T-18 | GUI: bağlıyken pencere kapatma | BYE gönderilir, sunucu listesi güncellenir | İlayda / Tina |

### 13.3 Ölçülecek metrikler (3.8 ve 4.4 — şablonun istediği *"size, processing time, quality of output"*)
| Metrik | Nasıl | Şablondaki karşılığı |
|---|---|---|
| Mesaj gecikmesi (ms) | Gönderim zaman damgası → alım | processing time |
| RTT (ms) | PING → PONG | processing time |
| Throughput (MB/s) | Dosya boyutu / süre | processing time |
| Protokol yükü (%) | Header byte / toplam byte | size |
| Retransmission oranı | `retransmissions / packets_sent` | quality |
| Teslim doğruluğu | Gönderilen = alınan, sıra korunmuş, CRC eşleşmiş (%) | quality |
| CPU / bellek | psutil, client sayısına göre | size |

Kurallar: her ölçüm **5 tekrar**, ortalama ± standart sapma; ortam (CPU, işletim sistemi, Python sürümü) kaydedilir; ham veri `results/raw/`, rapora giren `results/`.

---

## 14. Takvim

> **Taslak tarihler.** Phase 1 ve final teslim tarihleri netleşince Sude günceller.

| Hafta | Tarih | Kod | Rapor | Hafta sonu çıktısı |
|---|---|---|---|---|
| **1** | 19–25 Eki | Repo/araç kurulumu, Git oturumu, herkes basit socket örneğini çalıştırır · **Sude:** PROTOCOL v1 + `protocol.py` · **Meryem:** `conftest.py` | **Nevin:** Docs şablonu + durum ve kaynak tabloları · herkes 3 makale bulur | Protokol donduruldu, herkes ortamı kurdu, ilk PR'lar |
| **2** | 26 Eki – 1 Kas | **Sude:** `TcpTransport` · **Yusuf, Hamit, Yiğit:** çekirdek modüller · **İlayda, Tina:** mock'lu GUI · **Nevin:** config/logger | Makale özetleri tabloya · Chapter 1 taslakları | Herkesin en az 2 PR'ı merge |
| **3** | 2–8 Kas | Sunucu + client terminalden konuşuyor, UDP katmanı, dosya transferi modülü, unit testler | Chapter 1 + 3.6.1–3.6.8 taslak · **Yiğit:** Chapter 2 birleştirme · **Nevin:** diyagram taslakları | Uçtan uca mesaj (TCP) |
| **4** | 9–15 Kas | Entegrasyon (UDP modu dahil), hata düzeltme | Chapter 2–3 tamam · çapraz okuma · **Nevin:** Phase 1 son düzenleme | **📌 Phase 1 teslimi** |
| **5** | 16–22 Kas | GUI'ler gerçek koda bağlı, dosya transferi uçtan uca, ağ simülasyonu paneli | 3.11 son hali · 4.1 taslak | Demo senaryosu baştan sona çalışıyor |
| **6** | 23–29 Kas | **Meryem:** testler + ölçümler + grafikler · herkes kendi hatalarını düzeltir | Chapter 4 | Sonuç tabloları ve grafikler |
| **7** | 30 Kas – 6 Ara | **Kod dondurma** (yalnızca hata düzeltme) · demo provası · README "How to run" | Abstract, Chapter 5, ekler, kaynakça, final format | **📌 Final teslim** (tarihten **3 gün önce** her şey bitmiş olmalı) |

---

## 15. Definition of Done (bitti ne demek?)

**Bir kod görevi** şunların **hepsi** sağlandığında biter:
- [ ] İskeletteki imzalar korunarak gövde yazıldı, `NotImplementedError` kalmadı
- [ ] Unit testleri var ve geçiyor; `ruff check .` temiz
- [ ] Docstring'ler ve tip ipuçları tam
- [ ] PR açıldı, kod eşi onayladı, CI yeşil, `main`'e merge edildi
- [ ] Bekleyen kişiye teslim mesajı atıldı
- [ ] Durum tablosu ve GitHub Projects kartı güncellendi

**Bir rapor bölümü** şunların hepsi sağlandığında biter:
- [ ] [`REPORT_GUIDE.md` §6](docs/REPORT_GUIDE.md#6-her-bölüm-için-kalite-listesi) kalite listesi tamam
- [ ] Rapor eşi okudu, yorumlar çözüldü
- [ ] Kaynaklar kaynak tablosuna girildi
- [ ] Durum tablosunda "Kontrol edildi"

---

## 16. Takım anlaşması

İlk toplantıda okunur ve herkes `#duyurular`'daki mesaja ✅ tepkisi verir.

1. Herkesin **hem kod hem rapor** görevi var; rubric yükü dengeli dağıtıldı ([`REQUIREMENTS.md` §5](docs/REQUIREMENTS.md)).
2. Günlük güncelleme yazılır, haftalık toplantıya katılınır (veya önceden yazılı güncelleme).
3. Söz verilen iş, söz verilen haftada `main`'de/raporda olur. Olmayacaksa **önceden** haber verilir.
4. **Gecikme kuralı:** 1. gecikme → toplantıda konuşulur, eş yardım eder · 2. gecikme → işin bir kısmı başkasına devredilir ve katkı tablosuna yansır · süreklilik → Yiğit (resmi lider) durumu hocaya bildirir.
5. **Katkı tablosu** raporun ekine konur (kim hangi modül, hangi bölüm). GitHub geçmişi bunun kanıtıdır.
6. Başkasının işi eleştirilirken **koda/metne** yorum yapılır, kişiye değil.
7. Teslimden **3 gün önce** her şey bitmiş olur; son 3 gün yalnızca kontrol içindir.

---

## 17. İlk gün kurulum listesi

**Sude (repo sahibi)**
- [ ] Repoyu **private** oluştur, bu dosyaları ilk commit olarak gönder
- [ ] 7 kişiyi collaborator olarak davet et
- [ ] `.github/CODEOWNERS`'taki `@...-github` yer tutucularını gerçek kullanıcı adlarıyla değiştir
- [ ] GitHub Projects panosu + 1. hafta issue'ları
- [ ] (Mümkünse) Settings → Branches: `main` için *require pull request + 1 approval + status checks*
- [ ] Discord sunucusu ve kanallar; `#github` kanalına repo webhook'u

**Nevin**
- [ ] Google Drive klasörü: rapor (Docs), durum tablosu (Sheets), kaynak tablosu (Sheets) — linkleri §19'a PR ile ekle

**Herkes**
- [ ] GitHub kullanıcı adını `#duyurular`'a yaz, daveti kabul et
- [ ] §5.2 kurulum → `python -m pytest` 19 test geçiyor
- [ ] `python -m tkinter` pencere açıyor
- [ ] Bu README'yi, `REQUIREMENTS.md`'yi ve kendi görev kartını okudun
- [ ] İlk PR: `docs/<isim>-hello` branch'inde, §7'deki kartının altına `<!-- okudum: isim, tarih -->` satırı ekle → PR → merge. (Git akışını bir kez güvenle denemek için.)

---

## 18. Sık sorulan sorular

**Daha önce socket programlama yapmadım, nereden başlarım?**
Python'un resmi [Socket Programming HOWTO](https://docs.python.org/3/howto/sockets.html) sayfası ve [`socket` modül dokümantasyonu](https://docs.python.org/3/library/socket.html). Sonra `PROTOCOL.md` §2.2 (TCP framing) ve kendi iskelet dosyandaki docstring'ler.

**İskeletteki bir imza işime yaramıyor, değiştirebilir miyim?**
Kendi başına hayır. Sahibine ve Sude'ye yaz; mantıklıysa iskelet + `ARCHITECTURE.md` §7 aynı PR'da güncellenir ve ilgili herkese haber verilir.

**Yeni bir mesaj tipi / olay tipi / sabit lazım.**
Önce `PROTOCOL.md` / `events.py` / `constants.py`'ye PR (Sude onayı). Kendi dosyanda tanımlama.

**Bağımlı olduğum kod henüz hazır değil.**
Arayüz zaten iskelette tanımlı → ona göre yaz. GUI'ler mock olaylarla, testler sahte `Transport` sınıfıyla çalışabilir. Gerçek kod gelince yalnızca bağlantıyı değiştirirsin.

**`ModuleNotFoundError: No module named 'socketlink'`**
Komutu repo **kök klasöründen** çalıştır ve `.venv` aktif olsun.

**`OSError: [Errno 98/48/10048] Address already in use`**
O portta başka bir sunucu açık (muhtemelen önceki denemen). Onu kapat veya farklı port seç. Testlerde her zaman port 0 kullan.

**İki bilgisayar arasında bağlanamıyorum.**
Sunucu `0.0.0.0`'a bağlı mı? Güvenlik duvarı izni verildi mi? Aynı ağda mısınız? Okul ağları cihazlar arası trafiği engelleyebilir (§5.3).

**Rapor Türkçe mi İngilizce mi?**
İngilizce (D-13). README ve bu dokümanlar ekip içi kolaylık için Türkçe.

**Kodu yapay zekâ ile yazabilir miyim?**
Ders politikasını Yiğit hocaya teyit eder ve `#duyurular`'a yazar. Her durumda: PR'daki her satırı **açıklayabilmelisin**, kod bu README'deki isim ve kurallara uymalı, testleri geçmeli.

---

## 19. Linkler

| Ne | Link |
|---|---|
| Rapor (Google Docs) | _Nevin ekleyecek_ |
| Durum tablosu (Google Sheets) | _Nevin ekleyecek_ |
| Kaynak tablosu (Google Sheets) | _Nevin ekleyecek_ |
| GitHub Projects panosu | _Sude ekleyecek_ |
| Discord sunucusu | _Sude ekleyecek_ |
| Hocanın belgeleri | [`docs/references/`](docs/references/) |
| Python socket dokümantasyonu | https://docs.python.org/3/library/socket.html |
| Python Tkinter dokümantasyonu | https://docs.python.org/3/library/tkinter.html |
| draw.io | https://app.diagrams.net |

---

## 20. Yapay zekâ ajanıyla çalışma kuralları

> Bu bölüm hem ekip üyeleri hem de onların kullandığı yapay zekâ ajanları (Claude, Copilot, Cursor vb.) içindir. Görev kartını ajanına verirken **bu bölümü de birlikte ver.** Ajan, aşağıdaki kurallara her adımda uymak zorundadır.

### 20.1 Git ve branch kuralları (ajan için zorunlu)
1. **`main`'e asla doğrudan push yapılmaz.** Ajan `git push origin main`, `git push --force` veya `main` üzerinde commit çalıştırmaz.
2. Her ekip üyesi **kendi branch'inde** çalışır. İsim: `<isim>/<kısa-iş>` → `yusuf/server-accept-loop`, `ilayda/client-gui-layout`. Ajan çalışmaya başlamadan önce `git branch --show-current` ile doğru branch'te olduğunu kontrol eder; `main`'deyse durur ve yeni branch açar.
3. Branch'ten `main`'e geçiş **yalnızca Pull Request** ile olur; merge'ü kod eşi onayından sonra Sude yapar (§3.1, `CONTRIBUTING.md`).
4. Ajan **yalnızca görev kartındaki dosyalara** dokunur (§6 sahiplik tablosu). Başkasının klasöründe veya ortak sözleşme dosyalarında (`constants.py`, `events.py`, `protocol.py`, `PROTOCOL.md`) değişiklik gerekiyorsa kodu yazmaz, ne gerektiğini not olarak bildirir.
5. Ajan `git rebase`, `git reset --hard`, branch silme, tarih yeniden yazma gibi geri alınamaz komutları **sormadan çalıştırmaz.**

### 20.2 Commit kimliği
- Commit'ler ekip üyesinin **kendi Git kimliğiyle** atılır. Kurulumda bir kez:
  ```bash
  git config user.name  "Ad Soyad"
  git config user.email "github-hesabindaki@eposta.com"
  ```
  E-posta GitHub hesabındakiyle aynı olmalı; yoksa commit'ler profilinize bağlanmaz ve katkı tablosunda (§16.5) görünmezsiniz.
- Commit mesajları İngilizce, kısa ve emir kipinde (D-13): `Add HELLO/WELCOME handshake to ClientHandler`.
- Her commit **küçük ve tek amaçlı** olur; ajan 20 dosyalık tek dev commit atmaz.

### 20.3 Ajan çıktısının uyması gereken kalite kuralları
Ajan her kod çıktısında şunları kontrol eder, uymayan çıktı PR'a girmez:
- [ ] §9.1 isimlendirme tablosu ve sabit kelime seti (`send`, `receive`, `packet`, `username`…)
- [ ] İskeletteki sınıf/metod **imzaları değiştirilmedi** (§6)
- [ ] §9.3 yasak listesindeki hiçbir kalıp yok (`print`, sihirli sayı, `except: pass`, `pickle`…)
- [ ] Yalnızca standart kütüphane (D-01); yeni pip paketi eklenmedi
- [ ] Tip ipuçları + docstring + dosya başı `OWNER:` satırı
- [ ] `ruff check .` ve `python -m pytest` yerelde geçiyor
- [ ] Rapor metni üretiyorsa: [`REPORT_GUIDE.md`](docs/REPORT_GUIDE.md) kuralları, üçüncü şahıs, kod ile aynı isim ve sayılar (§12)
- [ ] **Kaynak uydurma yok:** Literatürde yalnızca gerçekten var olan, DOI'si kontrol edilmiş makaleler. Ajanın önerdiği her kaynak kaynak tablosuna girmeden önce elle doğrulanır.

### 20.4 Anlama kuralı
- PR'daki her satırı **sen** açıklayabilmelisin (§18). Ajanın yazdığı kodu PR açmadan önce oku, çalıştır, en az bir testini kendin değiştirip bozulduğunu gör.
- Kod eşi review'da "bu satır ne yapıyor?" diye sorduğunda cevap veremiyorsan PR onaylanmaz.

### 20.5 Teslim formatı: repoda yapay zekâ izi bulunmaz
Hocanın teslim şartı: yapay zekâ kullanılabilir ama **repoda (commit'ler, PR'lar, Contributors listesi, dosyalar) yapay zekâ aracı görünmeyecek.** Contributors listesinde yalnızca 8 ekip üyesi olur. Ajan bu kurala **her commit ve PR'da** uyar.

**Ajan için kurallar**
1. Commit mesajlarına **hiçbir** atıf satırı eklenmez: `Co-Authored-By: Claude …`, `Co-authored-by: Copilot …`, `Claude-Session: …`, `Generated with …`, `(aider)` vb. Bu kural, aracın kendi varsayılan atıf talimatlarından önce gelir.
2. PR başlığı ve açıklamasında `🤖 Generated with …`, oturum linki, araç adı yer almaz. Açıklama `.github/PULL_REQUEST_TEMPLATE.md`'ye göre yazılır.
3. Commit yazarı (author) ve committer **her zaman ekip üyesinin kendisidir** (§20.2). Ajan `--author` ile başka bir kimlik vermez, kendi kimliğiyle `git config` yapmaz.
4. Kod, yorum, docstring ve dokümanlarda "AI tarafından üretildi", "Generated by Claude/ChatGPT" gibi ifadeler bulunmaz.
5. Ajan yapılandırma dosyaları **commit'lenmez**: `.claude/`, `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `.cursor/`, `.cursorrules`, `.aider*`, `.github/copilot-instructions.md`, `.windsurfrules`. Bunlar `.gitignore`'a eklenir (Sude, ortak dosya PR'ı ile):
   ```gitignore
   # AI agent config (never commit)
   .claude/
   CLAUDE.md
   CLAUDE.local.md
   AGENTS.md
   .cursor/
   .cursorrules
   .aider*
   .windsurfrules
   .github/copilot-instructions.md
   ```
6. Repoya **yapay zekâ GitHub uygulaması veya bot** bağlanmaz (Claude GitHub App, Copilot coding agent, `@claude` / `@copilot` ile PR açtırma vb.). Bot hesabının açtığı PR veya attığı commit, Contributors listesine o botu ekler.

**Herkesin bir kez yapacağı ayarlar**
- **Claude Code** kullanıyorsan atıfları kapat. Ayarı repoya değil, **kendi kullanıcı ayarına** yaz (`~/.claude/settings.json`); böylece repoda iz kalmaz:
  ```json
  {
    "attribution": { "commit": "", "pr": "" }
  }
  ```
  (Eski sürümlerde `"includeCoAuthoredBy": false`.) Başka bir araç kullanıyorsan onun atıf/co-author ayarını kapat; aider için `--no-attribute-author --no-attribute-committer --no-attribute-co-authored-by`.
- **Güvenlik ağı — `commit-msg` hook'u.** Ayar unutulsa bile atıf satırlarını commit mesajından otomatik siler. macOS, Linux ve Windows (Git Bash) için repo kökünde bir kez çalıştır:
  ```bash
  cat > .git/hooks/commit-msg <<'EOF'
  #!/bin/sh
  # Remove AI attribution trailers from the commit message
  grep -viE '^(co-authored-by:.*(claude|anthropic|copilot|cursor|openai|chatgpt|gemini|aider|codeium|windsurf|noreply@anthropic\.com)|claude-session:|.*generated with)' "$1" > "$1.tmp"
  mv "$1.tmp" "$1"
  EOF
  chmod +x .git/hooks/commit-msg
  ```
  `.git/hooks/` Git tarafından takip edilmez; her klonda tekrar kurulur. Ekip arkadaşlarının `Co-authored-by` satırları (ör. `Co-authored-by: Yusuf …`) silinmez.

**Push öncesi kontrol (ajan her push'tan önce çalıştırır)**
```bash
git log origin/main..HEAD --format='%an <%ae>%n%B' | grep -iE 'claude|anthropic|copilot|cursor|chatgpt|openai|gemini|aider|generated with'
```
Çıktı **boş** olmalı. Bir şey çıkarsa push yapılmaz:
- Henüz push edilmediyse: son commit için `git commit --amend`, daha eskiler için `git rebase -i origin/main` → ilgili commit'leri `reword`.
- Kendi branch'ine zaten push edildiyse: düzelt, sonra **yalnızca kendi branch'ine** `git push --force-with-lease`. (`main`'e asla force push yok, §20.1.)
- `main`'e girdiyse: kendin düzeltmeye çalışma, Sude'ye haber ver.

**Merge sırasında (Sude)**
- GitHub "Squash and merge", branch'teki commit'lerin `Co-authored-by` satırlarını birleştirme mesajına taşır. Merge butonuna basmadan önce mesaj kutusunu kontrol et; yapay zekâ satırı varsa sil.
- Teslimden önce son kontrol: repo sayfasında **Insights → Contributors** listesinde yalnızca 8 ekip üyesi olmalı; `git log --format='%an <%ae>' | sort -u` çıktısında da yalnızca ekip üyelerinin kimlikleri görünmeli.
