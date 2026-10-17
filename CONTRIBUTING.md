# Katkı Rehberi (Git İş Akışı)

> Git'i hiç kullanmamış biri için adım adım. Komutlar terminalde (Windows'ta **Git Bash** veya PowerShell, macOS/Linux'ta Terminal) çalıştırılır.

## 0. Bir kerelik kurulum

1. **Git'i kur:** https://git-scm.com/downloads
2. **Kimliğini tanıt** (commit'lerde adın doğru görünsün diye; e-posta GitHub hesabındakiyle aynı olmalı):
   ```bash
   git config --global user.name "Ad Soyad"
   git config --global user.email "okul-veya-github-epostan@ornek.com"
   ```
3. **GitHub hesabı aç**, kullanıcı adını `#duyurular` kanalına yaz. Sude seni repoya *collaborator* olarak ekler; e-postadaki daveti kabul et.
4. **Repoyu bilgisayarına indir:**
   ```bash
   git clone https://github.com/<sude-kullanici-adi>/socketlink.git
   cd socketlink
   ```
5. **Ortamı kur** (README §5).

> Terminal istemiyorsan **GitHub Desktop** (https://desktop.github.com) aynı işleri butonlarla yapar. Aşağıdaki adımların her birinin karşılığı orada var; kavramlar aynı.

## 1. Her iş için döngü

```
main'i güncelle → yeni branch aç → kod yaz → commit → push → Pull Request → review → merge → main'i güncelle
```

### Adım 1 — main'i güncelle ve branch aç
```bash
git checkout main
git pull origin main
git checkout -b feature/yusuf-server-accept-loop
```

**Branch isimlendirme:** `<tür>/<isim>-<kısa-konu>` (küçük harf, Türkçe karakter yok, tire)

| Tür | Ne için | Örnek |
|---|---|---|
| `feature/` | Yeni özellik | `feature/hamit-heartbeat` |
| `fix/` | Hata düzeltme | `fix/ilayda-status-color` |
| `test/` | Yalnızca test | `test/meryem-protocol-roundtrip` |
| `docs/` | Doküman / diyagram | `docs/nevin-top-level-diagram` |
| `refactor/` | Davranışı değiştirmeyen düzenleme | `refactor/tina-file-chunks` |

### Adım 2 — çalış ve commit et
Küçük, anlamlı adımlarla commit at (günde birkaç kez normaldir):
```bash
git status                       # neler değişti?
git add socketlink/server/server.py
git commit -m "feat(server): accept loop with stop event"
```

**Commit mesajı formatı:** `<tür>(<kapsam>): <ne yaptın, İngilizce, küçük harfle başlar>`

| Tür | Kapsam örnekleri |
|---|---|
| `feat`, `fix`, `test`, `docs`, `refactor`, `chore` | `protocol`, `transport`, `server`, `client`, `udp`, `transfer`, `client-gui`, `server-gui`, `config`, `tests`, `diagrams`, `report` |

Örnekler:
```
feat(protocol): encode and decode with crc32 checksum
fix(client): reconnect loop no longer blocks on close
test(udp): retransmission under 20% loss
docs(diagrams): HLD-1 top-level network diagram
```

`git add .` kullanmadan önce `git status` ile neyin ekleneceğini kontrol et; log, `downloads/`, `.venv/` gibi şeyler `.gitignore` sayesinde zaten eklenmez.

### Adım 3 — göndermeden önce kontrol et
```bash
ruff check .            # stil ve bariz hatalar
python -m pytest        # testler
```
İkisi de temiz değilse PR açma.

### Adım 4 — main'deki son değişiklikleri al (çakışmayı erken yakala)
```bash
git fetch origin
git merge origin/main
```
Çakışma (conflict) çıkarsa → §3.

### Adım 5 — push ve Pull Request
```bash
git push -u origin feature/yusuf-server-accept-loop
```
Terminalde çıkan linke tıkla (veya GitHub'da **Compare & pull request**). PR şablonunu doldur, **reviewer olarak kod eşini** seç (README §9.2).

### Adım 6 — review
- **Reviewer** 24 saat içinde bakar. Ya **Approve**, ya da somut yorum (*"burada lock tutarken send yapılıyor, ARCHITECTURE §3 kural 3"*).
- Yazar yorumları düzeltir, aynı branch'e yeni commit push'lar (PR otomatik güncellenir).
- Onay + CI yeşil → yazar **Squash and merge** yapar → branch'i siler.

### Adım 7 — yeni işe geçmeden
```bash
git checkout main
git pull origin main
```

## 2. Kesin kurallar

1. `main`'e **doğrudan push yok.** Her şey PR ile.
   > Repo private ise GitHub'ın branch koruması yalnızca ücretli planlarda (veya GitHub Student Developer Pack ile gelen GitHub Pro'da) açılabiliyor. Sude'de varsa açar; yoksa kural **anlaşmayla** uygulanır.
2. Bir PR **bir konu.** "server + biraz GUI + README düzeltmesi" olmaz.
3. PR'lar küçük: ideali < 400 satır değişiklik. **En geç 2-3 günde bir** PR.
4. Başkasının klasörüne dokunma (sahipler: README §6, `.github/CODEOWNERS`). Gerekirse önce sahibine yaz.
5. **Ortak sözleşme dosyaları** (`constants.py`, `events.py`, `exceptions.py`, `protocol.py`, `transport.py`, `docs/PROTOCOL.md`) yalnızca Sude onayıyla değişir.
6. Başkasının dosyasında **otomatik biçimlendirme** çalıştırma (gereksiz satır değişikliği = gereksiz çakışma).
7. Kırık kod `main`'e girmez. CI kırmızıysa merge yok.
8. Şifre, token, kişisel bilgi asla commit'lenmez.

## 3. Çakışma (merge conflict) çıkarsa

Git, iki kişinin aynı satırları değiştirdiğini fark ederse dosyaya şöyle işaretler koyar:
```
<<<<<<< HEAD
senin satırın
=======
main'deki satır
>>>>>>> origin/main
```
1. Dosyayı aç, iki versiyondan doğru olanı bırak (gerekirse ikisini birleştir), işaret satırlarını sil.
2. ```bash
   git add <dosya>
   git commit -m "chore: resolve merge conflict with main"
   ```
3. Emin değilsen o satırların sahibine sor. **Başkasının kodunu "benimki kalsın" diye silme.**

## 4. Sık yapılan hatalar

| Durum | Çözüm |
|---|---|
| Yanlışlıkla `main`'de çalıştım | `git checkout -b feature/...` → değişiklikler yeni branch'e taşınır, sonra normal devam |
| Son commit mesajı yanlış (henüz push etmedim) | `git commit --amend -m "doğru mesaj"` |
| Push reddedildi ("fetch first") | `git pull origin <branch-adın>` sonra tekrar push |
| Bir dosyadaki değişiklikleri çöpe atmak istiyorum | `git restore <dosya>` (geri alınamaz!) |
| Takıldım | 2 saat kuralı: önce kod eşine, sonra `#yardım` kanalına; hata mesajının **tamamını** yapıştır |
