# Rapor Yazım Rehberi

> **Sahibi:** Nevin · Rapor **tek bir Google Docs** dokümanında yazılır (link README §10'da). Bu repo yalnızca rapor için referans, diyagram kaynakları ve sonuç verilerini tutar.

8 kişi yazınca rapor 8 farklı sesle konuşur. Bu rehber herkesin aynı dil, aynı terimler ve aynı biçimle yazmasını sağlar. **Bölümünü yazmaya başlamadan önce bu dosyanın tamamını oku.**

---

## 1. Dil ve üslup

- Rapor **İngilizce** yazılır.
- **Üçüncü şahıs / edilgen**: ❌ *"We used TCP"* → ✅ *"TCP was selected because..."* / *"The system uses..."*
- Zaman: tasarım ve sistem anlatımı **present simple** (*"The server accepts..."*), yapılan deney ve testler **past simple** (*"Each test was repeated five times."*).
- Konuşma dili kısaltması yok: *don't, can't, it's, etc.* yerine *do not, cannot, it is, and so on*.
- Her kısaltma ilk geçtiği yerde açılır: *"Transmission Control Protocol (TCP)"*, sonra *TCP*. Nevin bunları **LIST OF ABBREVIATIONS**'a ekler; yeni kısaltma kullanan kişi `#rapor` kanalına yazar.
- Doldurma cümle yok. Her paragraf bir şey iddia eder ve ya gerekçe, ya kaynak, ya da ölçüm verir.

## 2. Ortak terim sözlüğü (aynen bu şekilde kullan)

| Kullan | Kullanma |
|---|---|
| SocketLink (uygulamanın adı) | the app, our program, chat app |
| server, client | host, user program, customer |
| packet | message frame, datagram (UDP bağlamı dışında) |
| header, payload | head, body, data part |
| reliable UDP transport | custom UDP, safe UDP |
| Go-Back-N (GBN) | sliding window protocol (tek başına) |
| retransmission | resending, re-sending |
| acknowledgement (ACK) | acknowledgment, confirmation |
| sequence number | sequence id, packet number |
| round-trip time (RTT) | ping time, latency (RTT kastediliyorsa) |
| thread-per-client model | multi-thread server (tek başına) |
| event bus | event system, message bus |
| graphical user interface (GUI) | UI, interface (tek başına) |
| simulated packet loss | fake loss, packet drop rate |

Sayılar ve parametreler **kodla aynı** olmalı: `DEFAULT_PORT = 5050`, `MAX_CLIENTS = 50`, `HEARTBEAT_INTERVAL = 5 s`, `RETRANSMIT_TIMEOUT = 0.5 s`, `DEFAULT_WINDOW_SIZE = 4`, `FILE_CHUNK_SIZE = 1024 B`. Bir değer `constants.py`'de değişirse raporu güncellemek **değiştiren kişinin** sorumluluğudur.

## 3. Kaynak gösterme (IEEE stili)

- Metin içinde köşeli parantezli numara: *"Go-Back-N reduces idle time compared with Stop-and-Wait [7]."*
- Numara, kaynağın metinde **ilk geçtiği sıraya** göre verilir. Nevin sonda numaraları düzenler; o yüzden yazarken kaynak tablosundaki **kısa anahtarı** kullanın: `[Kurose2021]`, `[Smith2019]`. Nevin bunları sonra [1], [2]... ile değiştirir.
- Kaynak tablosu (Google Sheets) sütunları:
  `anahtar | yazarlar | yıl | başlık | dergi/konferans | DOI/URL | ekleyen | hangi bölümde kullanıldı | özet (3-4 cümle) | projeyle ilişkisi`
- **Chapter 2 için**: 2014 ve sonrası, hakemli dergi veya konferans makalesi (Google Scholar, IEEE Xplore, ACM DL, ScienceDirect). Blog, Wikipedia, Medium Chapter 2'de **kullanılmaz**.
- Ders kitabı (ör. Kurose & Ross) ve Python dokümantasyonu diğer bölümlerde kaynak olarak kullanılabilir.
- Başka kaynaktan kelimesi kelimesine cümle almayın; kendi cümlelerinizle yazıp kaynak gösterin.

### Literatür konu dağılımı (kişi başı 3 makale)

| Kişi | Konu |
|---|---|
| Sude | Application-layer protocol design, message serialization |
| Yiğit | Reliable data transfer over UDP, ARQ (Stop-and-Wait, GBN, Selective Repeat) |
| Yusuf | Multi-threaded / concurrent server architectures, scalability |
| Hamit | Fault tolerance, failure detection (heartbeat), connection recovery |
| İlayda | Network simulation / visualization tools for education |
| Tina | File transfer over networks, network monitoring |
| Meryem | Network performance measurement, testing of networked software |
| Nevin | Client-server architecture modelling, socket API overviews |

Aynı makaleyi iki kişi eklemesin: eklemeden önce tabloda DOI ile arayın.

## 4. Şekiller ve tablolar

- Numara: **bölüm.sıra** → *Figure 3.4*, *Table 3.2*.
- Şekil başlığı şeklin **altında**, tablo başlığı tablonun **üstünde**.
- Her şekil/tablo metinde **adıyla anılır** ve **önce** anılır: *"The top-level topology is shown in Figure 3.1."*
- Başka kaynaktan alınan şekil: başlığın sonunda kaynak → *"Figure 1.2: TCP three-way handshake [3]."*
- Ekran görüntüleri: pencere tam görünür, kişisel bilgi yok, kullanıcı adları `alice`, `bob`, `carol` gibi nötr.

## 5. Diyagram kuralları (Nevin + katkı verenler)

- Araç: **draw.io** (diagrams.net). Kaynak dosya ve PNG **birlikte** repoya konur:
  `docs/diagrams/fig-3-6-9-top-level.drawio` + `docs/diagrams/fig-3-6-9-top-level.png`
- Dosya adı: `fig-<başlık-numarası>-<kısa-ad>` (küçük harf, tire).
- Tek görsel dil:
  - Font: Times New Roman 12 (rapora uyum)
  - Sunucu bileşenleri **mavi** `#dbeafe`, client bileşenleri **yeşil** `#dcfce7`, ağ/transport **gri** `#f3f4f6`, hata/kayıp **kırmızı** `#fee2e2`
  - Oklar: düz çizgi = veri akışı, kesikli = kontrol/olay
- Başlangıç noktası olarak [`ARCHITECTURE.md`](ARCHITECTURE.md)'deki Mermaid diyagramlarını kullanın; rapordaki diyagram **kodla birebir aynı** isimleri (sınıf, thread, mesaj tipi) taşımalı.
- PNG dışa aktarımı: 200% ölçek, beyaz arka plan.

## 6. Her bölüm için kalite listesi

Bölümünü "Taslak bitti" yapmadan önce:

- [ ] Hocanın kriter sorusu (REQUIREMENTS.md'deki kod, ör. NNA-6) **açıkça** cevaplanıyor; mümkünse ilk cümlede
- [ ] Gerekçe var (*neden* böyle?)
- [ ] En az bir kaynak gösterildi (Chapter 1 ve 4'te zorunlu)
- [ ] Sayılar `constants.py` ile aynı
- [ ] Terimler §2'deki sözlükle aynı
- [ ] Şekil/tablo varsa numaralı, başlıklı ve metinde anılmış
- [ ] Üçüncü şahıs, resmi dil
- [ ] Rapor eşin okudu ve yorumları çözüldü

## 7. Google Docs çalışma kuralları

1. Herkes **yalnızca kendi başlığının altına** yazar. Başlıkların yanında sahibinin adı yazılıdır: `3.6.6 Reliability Requirements [Hamit]` (köşeli parantez son düzenlemede silinir).
2. Başkasının bölümüne müdahale: **Suggesting (Öneri) modu** veya yorum. Doğrudan silme/değiştirme yok.
3. Biçimlendirme şablonu Nevin'in kurduğu **stillerle** yapılır (Heading 1/2/3, Normal text). Elle punto/renk değiştirmeyin; yoksa içindekiler tablosu bozulur.
4. Tablolar ve şekiller için Nevin'in hazırladığı **örnek tablo** kopyalanır.
5. Yazarken referansları kısa anahtarla yazın (`[Kurose2021]`).
6. Bölüm durumu Google Sheets'teki durum tablosunda güncellenir.

## 8. Yazım örneği (üslup referansı)

> **3.6.6 Reliability Requirements**
>
> SocketLink is required to deliver every chat message and file chunk exactly once and in the order in which it was sent, even when the underlying network loses packets. In TCP mode this guarantee is provided by the transport protocol itself [Kurose2021]. In UDP mode, the reliable UDP transport implements Go-Back-N with cumulative acknowledgements, a retransmission timeout of 0.5 s and a window of four packets (Section 3.5). Corrupted packets are detected with a CRC32 checksum and discarded (Table 3.3). Liveness is monitored with a heartbeat every 5 s; a connection that remains silent for 15 s is considered failed and the client attempts to reconnect with exponential back-off.
