# Hocanın Gereksinimleri ve Raporda Karşılıkları

> **Sahibi:** Nevin · Orijinal belgeler: [`references/`](references/)
> - `project-requirements-p6.jpeg`, `project-requirements-p7.jpeg` — puanlama kriterleri
> - `report-template.pdf` — rapor şablonu ve format kuralları
> - `project-proposal-form.pdf` — gönderdiğimiz proje önerisi (verdiğimiz sözler)
>
> **Bu dosya neden var?** Hoca iki ayrı belge verdi: biri *neyi cevaplayacağımızı ve puanları* (kriterler), diğeri *raporun hangi başlıklarla yazılacağını* (şablon) söylüyor. İkisi birbirine uymuyor. Biz raporu **şablonun iskeletiyle** yazıyoruz ve **her kriteri uygun başlığın içine yerleştiriyoruz**. Aşağıdaki tablolar bu eşlemeyi tek bakışta gösterir.

---

## 1. Puan özeti

| Bölüm | Puan | Nerede karşılanıyor |
|---|---|---|
| **Part #1** — Tasarım dokümantasyonu | **70** | Rapor (Phase 1 ağırlıklı) |
| · Feasibility Study | 20 | Chapter 1 |
| · Network Needs Analysis | 20 | 3.6.1 – 3.6.8 |
| · High-Level Network Design | 20 | 3.6.9 – 3.6.12 |
| · Detailed Design Documentation | 10 | 3.11 ve 4.2 |
| **Part #2** — GUI programı | **30** | Kod (bu repo) + 4.1 |
| **Toplam** | **100** | |

Part #1'in başında hoca şunu da şart koşuyor: *"You will be writing a specific design code pattern to complete this project"* → Tasarım desenlerimiz [`ARCHITECTURE.md` §2](ARCHITECTURE.md) ve raporda **3.6.13**.

---

## 2. Part #1 — kriter kriter eşleme

Kimlik kodu (ör. `FS-1`) issue, PR ve commit'lerde kullanılır: `docs(report): FS-1 project scope draft`.

### 2.1 Feasibility Study (20)

| Kod | Hocanın sorusu (orijinal) | Ne anlama geliyor | Puan | Rapor başlığı | Sahibi |
|---|---|---|---|---|---|
| FS-1 | Project Scope | Ne yapıyoruz / ne yapmıyoruz | 2 | 1.6 → *Scope* | Sude |
| FS-2 | Objectives of the project design network | Ölçülebilir hedefler | 3 | 1.5 | Sude |
| FS-3 | Intended Users | Hedef kullanıcılar | 2 | 1.2 → *Intended Users* | İlayda |
| FS-4 | Design Assumptions | Tasarım varsayımları | 3 | 1.6 → *Design Assumptions* | Yusuf |
| FS-5 | Explain things to consider before adopting a strategy and justify whether an approach would be useful for your design | Seçeneklerin (TCP/UDP, thread/asyncio, Tkinter/PyQt) değerlendirilmesi ve seçimimizin gerekçesi | 5 | 1.7 | Sude |
| FS-6 | Give an overview of the business or industry that you are in based on the assignment topic | Socket programlamanın sektördeki yeri | 3 | 1.3 | Yiğit |
| FS-7 | Include the business/technical problem, domain, rules, constraints, and issues | Problem, alan, kurallar, kısıtlar | 2 | 1.4 | Hamit |

### 2.2 Network Needs Analysis (20)

| Kod | Hocanın sorusu | Ne anlama geliyor | Puan | Rapor | Sahibi |
|---|---|---|---|---|---|
| NNA-1 | Data Types are used in the project design network | Metin, ikili dosya, kontrol paketleri; JSON vs ham byte | 2 | 3.6.1 | Tina |
| NNA-2 | Data Sources in the project design network | Verinin geldiği yerler (kullanıcı girdisi, dosya sistemi, sunucu) | 3 | 3.6.2 | Tina |
| NNA-3 | Number of Users and Priority Levels | Kaç kullanıcı (MAX_CLIENTS=50), mesaj öncelikleri | 2 | 3.6.3 | Yusuf |
| NNA-4 | Transmission Speed Requirements | Hedef gecikme ve hız değerleri | 3 | 3.6.4 | Yusuf |
| NNA-5 | Storage Requirements | Loglar, indirilen dosyalar, ayarlar; bellek | 2 | 3.6.5 | Tina |
| NNA-6 | Reliability Requirements | Checksum, ACK, yeniden gönderim, heartbeat, yeniden bağlanma | 3 | 3.6.6 | Hamit |
| NNA-7 | Security Requirements | Girdi doğrulama, dosya adı temizleme, boyut sınırları, (opsiyonel) TLS | 2 | 3.6.7 | Hamit |
| NNA-8 | Provide the architecture, components, interaction between components, and technical issues | Mimari ve teknik sorunlar | 3 | 3.6.8 | Sude |

### 2.3 High-Level Network Design (20)

| Kod | Hocanın sorusu | Ne çizilecek / yazılacak | Puan | Rapor | Sahibi |
|---|---|---|---|---|---|
| HLD-1 | Top-Level Network Diagram | Kuşbakışı: client'lar ↔ LAN/Internet ↔ router ↔ sunucu | 5 | 3.6.9 | Nevin |
| HLD-2 | Detailed Network Diagram | Sunucu ve client içi: thread'ler, kuyruklar, katmanlar | 5 | 3.6.10 | Nevin |
| HLD-3 | Detailed Network Sub-Diagram | Paket yapısı + güvenilir UDP sıra diyagramı | 5 | 3.6.11 | Nevin |
| HLD-4 | How will it be integrated into the project, and how will it function? | Parçaların birleşmesi: GUI ↔ EventBus/kuyruk ↔ çekirdek ↔ transport | 5 | 3.6.12 | İlayda |

### 2.4 Detailed Design Documentation (10)

| Kod | Hocanın sorusu | Puan | Rapor | Sahibi |
|---|---|---|---|---|
| DDD-1 | What are two specific advantages of using your solution design and two specific disadvantages within this context? | 5 | 3.11 | Sude + Yusuf |
| DDD-2 | How can the design pattern (code) be tested? What assessments are used? | 5 | 4.2 (+ 3.7, 3.8) | Meryem |

---

## 3. Part #2 — GUI programı (30)

Hocanın cümlesi: *"Write a complete GUI program to simulate the above proposal title."*

"Complete" ve "simulate" kelimelerini karşılamak için **asgari kabul kriterleri** (demo bunları göstermeli):

| # | Özellik | Sahibi |
|---|---|---|
| G-1 | Sunucu penceresi: IP/port/mod seçip başlat-durdur | Tina |
| G-2 | Client penceresi: IP/port/kullanıcı adı/mod seçip bağlan-ayrıl | İlayda |
| G-3 | Aynı anda en az 3 client'ın birbirine mesaj atması (herkese ve özel) | Hamit + Yusuf |
| G-4 | Bağlantı durumu canlı gösterim (renkli) | İlayda |
| G-5 | Çevrimiçi kullanıcı listesi | İlayda |
| G-6 | Dosya gönderme + ilerleme çubuğu | Tina |
| G-7 | Canlı paket log'u (gönderilen/alınan/düşen/yeniden gönderilen) | İlayda + Tina |
| G-8 | İstatistik paneli (paket, byte, retransmission, RTT) | İlayda + Tina |
| G-9 | UDP modunda kayıp % ve gecikme slider'ları → güvenilirliğin canlı simülasyonu | Yiğit + İlayda |
| G-10 | Hata senaryolarında çökmeme: sunucuyu kapat, yanlış port, aynı kullanıcı adı | Hamit |
| G-11 | Sunucu panelinde client tablosu + kick | Tina |

## 4. Önerimizde verdiğimiz sözler (hoca kontrol edebilir)

`project-proposal-form.pdf`'de yazdıklarımız ve koddaki karşılıkları:

| Söz | Karşılığı | Sahibi |
|---|---|---|
| Client-server mimarisi | `ChatServer` / `ChatClient` | Yusuf, Hamit |
| OOP ile modüler kod | Paket yapısı, sınıflar, desenler | Herkes |
| Verimli serialization ve packet parsing | `protocol.py` (struct header + JSON/ham payload) | Sude |
| Paket kaybına karşı doğru ve sıralı teslim | TCP + `reliable_udp.py` (Go-Back-N) | Sude, Yiğit |
| Multi-threading / asenkron, bloklamayan sunucu | Thread-per-client, timeout'lu döngüler | Yusuf |
| Bağlantı kopması, timeout, geçersiz istek yönetimi | Exception hiyerarşisi, heartbeat, yeniden bağlanma, ERROR kodları | Hamit |
| GUI'den IP/port ayarı, durum izleme, iki yönlü veri akışının gerçek zamanlı takibi | G-1…G-8 | İlayda, Tina |

---

## 5. Rapor şablonunun tam iskeleti ve sahipleri

Şablondaki başlıklar **aynen** korunur (İngilizce). Kriterler alt başlık olarak eklenir. Başlık numarası en fazla **üç basamak** olabilir (şablon kuralı).

| Başlık | Kriter | Sahibi | Faz |
|---|---|---|---|
| Kapak (form bilgileri) | — | Nevin | 1 |
| ABSTRACT | — | Nevin (en son) | 2 |
| LIST OF FIGURES / TABLES / ABBREVIATIONS | — | Nevin | 1–2 |
| Rubric Mapping Table (bu dosyanın §2 özeti) | — | Nevin | 1 |
| **CHAPTER 1 INTRODUCTION** | | | |
| 1.1 Background of Related Projects | — | Yiğit | 1 |
| 1.2 Project Description | — | Sude | 1 |
| 1.2.1 Intended Users | FS-3 | İlayda | 1 |
| 1.3 The Benefits of Research Related to the Industry | FS-6 | Yiğit | 1 |
| 1.4 Project Problem Statement | FS-7 | Hamit | 1 |
| 1.5 Project Goals and Objectives | FS-2 | Sude | 1 |
| 1.6.1 Scope | FS-1 | Sude | 1 |
| 1.6.2 Limitations | — | Sude | 1 |
| 1.6.3 Design Assumptions | FS-4 | Yusuf | 1 |
| 1.7 Project Proposed Solution | FS-5 | Sude | 1 |
| 1.8 Project Software Development Model | — | Tina | 1 |
| 1.9.1 Project's Hardware | — | İlayda | 1 |
| 1.9.2 Project's Software | — | İlayda | 1 |
| **CHAPTER 2 LITERATURE REVIEW** (≥ 20 makale, 2014+) | — | Herkes 3 makale, birleştiren Yiğit | 1 |
| **CHAPTER 3 RESEARCH METHODOLOGY** | | | |
| 3.1 Introduction | — | Yiğit | 1 |
| 3.2 Review of related work / research gap | — | Yiğit | 1 |
| 3.3 Current techniques (ARQ, TCP mekanizmaları) ve etkinlikleri | — | Yiğit | 1 |
| 3.4 Comparing approaches (thread / asyncio / select; TCP / UDP) | — | Yusuf | 1 |
| 3.5 Proposed algorithm (güvenilir UDP) | — | Yiğit | 1 |
| 3.6 Description of the proposed system design | | | |
| 3.6.1 – 3.6.8 | NNA-1…8 | bkz. §2.2 | 1 |
| 3.6.9 – 3.6.11 | HLD-1…3 | Nevin | 1 |
| 3.6.12 Integration and functioning | HLD-4 | İlayda | 1 |
| 3.6.13 Design patterns | "design code pattern" | Sude | 1 |
| 3.7 Description of experimental system design | — | Meryem | 1 |
| 3.8 Description of measurement and data analysis | — | Meryem | 1 |
| 3.9 Error compounding testing | — | Hamit | 1 |
| 3.10 Method of presentation of the output results | — | İlayda | 1 |
| 3.11 Discussion (2 avantaj, 2 dezavantaj) | DDD-1 | Sude + Yusuf | 1 |
| **CHAPTER 4 PROJECT SETUP, TESTING, RESULTS, AND DISCUSSION** | | | |
| 4.1 Prototype / simulator | Part #2 | İlayda + Tina | 2 |
| 4.2 Project design approach testing | DDD-2 | Meryem | 2 |
| 4.3 Project verification and validation | — | Meryem | 2 |
| 4.4 Discussion of results (size, processing time, quality) | — | Meryem (UDP verisi: Yiğit) | 2 |
| **CHAPTER 5 CONCLUSION, FUTURE RESEARCH WORKS, AND REMARKS** | — | Nevin | 2 |
| REFERENCES | — | Nevin | 1–2 |
| APPENDIX A: Contribution table · B: Installation guide | — | Nevin | 2 |

> Şablonda "Chapter 8" yazıyor; numaralandırma sırasına göre Chapter 5 kullanıyoruz. Yiğit hocaya teyit ettirecek.

## 6. Format kuralları (şablondan, eksiksiz)

| Kural | Değer |
|---|---|
| Yazı tipi | Times New Roman |
| Punto | Metin 12 · alt başlık 12 · ana başlık 14 |
| Ana başlık | BÜYÜK HARF, kalın, yeni sayfada başlar |
| Tüm başlıklar | Kalın; numara en fazla 3 basamak (ör. 3.6.12) |
| Başlık boşlukları | Ana başlık altında 2 boş satır; alt başlık üstünde 2, altında 1 boş satır |
| Satır aralığı | Metin 1.5 · kapak ve abstract 1.0 |
| Kenar boşlukları | Sol **4 cm** (ciltleme) · sağ 1.5 cm · üst/alt 2–2.5 cm (ekler dahil) |
| Paragraf | Girinti yok · iki yana yaslı · paragraflar arası 1 boş satır |
| Sayfa sonu | Bölünen paragrafın sayfa altında/üstünde en az 2 satırı kalmalı |
| Sayfa numarası | Sağ alt · kapaktan sonraki ilk sayfa "1" · kaynakçanın son sayfasına kadar · ekler numarasız |
| Baskı | Tek yüz |
| Dil | Resmi, tam cümleler, üçüncü şahıs; argo/klişe/konuşma kısaltması yok |
| Şekil ve tablo | Hepsi numaralı ve başlıklı; başka kaynaktan alındıysa kaynak gösterilir |
| Chapter 1 ve 4 | Şablon: "Explain and cite all the sections and subsections, including the Figures and Tables" → her alt başlıkta kaynak gösterilmeli |
