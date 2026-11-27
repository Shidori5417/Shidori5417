# scripts

Profil README'sini ve portföy sitesinin okuduğu veriyi üreten betikler. `.github/workflows/update-profile.yml` her gün 03:17 UTC'de (ve `scripts/**` ya da `data/projects.yml` değişince, ya da elle) çalıştırır.

## build_cards.py

`assets/` altındaki istatistik kartlarını üretir. Token: `GH_STATS_TOKEN` (private repo toplamları için) ya da `GITHUB_TOKEN`.

## build_profile.py

README'nin **Featured**, **More** ve **Now** bölümlerini ve `data/profile.json` dosyasını üretir. Bölümler README'de şu işaretlerin arasına yazılır; işaretlerin dışına dokunulmaz:

```
<!-- FEATURED:START --> ... <!-- FEATURED:END -->
<!-- MORE:START -->     ... <!-- MORE:END -->
<!-- NOW:START -->      ... <!-- NOW:END -->
```

```sh
pip install pyyaml
GITHUB_TOKEN=$(gh auth token) python scripts/build_profile.py --dry-run   # yazmadan göster
GITHUB_TOKEN=$(gh auth token) python scripts/build_profile.py             # README + data/profile.json yaz
python -m unittest scripts/test_build_profile.py                          # testler (ağ yok)
```

Ortam: `PROFILE_OWNER` (varsayılan `Shidori5417`), `GITHUB_TOKEN` (rate limit için; sabitlenmiş repoları okumak için de gerekir, bkz. More). `--now-date YYYY-MM-DD` "şimdi"yi o günün sonuna sabitler (test için).

### data/projects.yml: Featured, blurbs, labels

Featured listesi elle düzenlenir (sıra korunur); More otomatiktir, buradaki `blurbs`/`labels` yalnızca geçersiz kılmadır.

```yaml
owner: Shidori5417
featured:            # 2'şerli satırlarla tablo
  - repo: vuln-stack
    image: https://raw.githubusercontent.com/...
    alt: görsel açıklaması
    blurb: tek cümlelik açıklama
    stack: Rust · ratatui
    focus: true      # isteğe bağlı: status.yml'deki focus (en) cümlesini italik satır olarak ekler
blurbs:              # More: repo → ":" sonrası metin (yoksa GitHub açıklaması kullanılır)
  micctl: "PipeWire mic DSP and soundboard CLI/TUI, the predecessor of micforge"
labels:              # More: repo → bağlantıdan sonra "(etiket)"
  DomainSniper: DomainGözcü
```

### Featured

Her hücre: görsel (repo'ya bağlı), repo adı, blurb ve canlı veriden bir künye satırı:

```
<sub>Rust · ratatui · SSH — v0.1.0 · maintenance · ★ 3</sub>
```

`stack — son release (release sayfasına bağlı) · status.yml durumu · ★ yıldız`. Yıldız yalnızca 0'dan büyükse, durum `released` ve release etiketi varsa (aynı şeyi söylerdi) gösterilmez; canlı veri yoksa yalnızca stack kalır. Öğe sayısı tekse son satır boş bir hücreyle tamamlanır (genişlikler hep %50). Tüm değerler `html.escape`'ten geçer; release bağlantısı yalnızca `https://github.com/` ile başlıyorsa bağlanır.

### More (otomatik)

Profil sayfasında README'nin hemen altında sabitlenmiş (pinned) repolar kart olarak görünür; More, bunların ve Featured'ın dışında kalan her şeyi listeler, böylece hiçbir proje iki kez gösterilmez ya da atlanmaz.

- **Pinned:** GraphQL `user.pinnedItems(first: 6, types: REPOSITORY)` (`POST https://api.github.com/graphql`, token gerekir; Actions'taki `GITHUB_TOKEN` public veri için yeterli). Private ve başka sahibe ait sabitlemeler yok sayılır. Çağrı başarısız olur ya da token yoksa önceki `profile.json`'daki `pinned` listesi kullanılır; o da yoksa sabitlenmiş repo yokmuş gibi devam edilir (uyarı loglanır, çalışma asla düşmez; bu durumda More'da sabitlenmiş repolar da görünür).
- **Küme:** toplanan public, fork olmayan, arşivlenmemiş (GitHub `archived` ya da `status: archived`) repolar, sabitlenmişler ve Featured çıkarılmış hâlde.
- **Sıra:** `lastWorkAt` azalan, sonra `pushedAt` azalan, sonra ad.
- **Metin:** `blurbs[repo]`, yoksa GitHub açıklaması (tek satır, sondaki nokta atılır, ilk harf küçültülür; `PipeWire`, `CVE`, `Discord` gibi kısaltma/özel isimlere dokunulmaz), o da yoksa yalnızca bağlantı. Tüm metin `md_inline()`'dan geçer.
- **Durum ipucu:** `status.yml` durumu `paused` ise ` · on hold`, `prototype` ise ` · prototype`, `maintenance` ise ` · maintenance` eklenir; `active`/`released`/durumsuz için hiçbir şey eklenmez. Bu yüzden blurb'a "(prototype)" gibi durum notu yazılmaz.

Örnek satır: `- [micctl](https://github.com/Shidori5417/micctl): PipeWire mic DSP and soundboard CLI/TUI, the predecessor of micforge · maintenance`

### .github/status.yml: repo başına durum

Her public repo kök dizininde `.github/status.yml` tutabilir. Yoksa ya da geçersizse (uyarı loglanır) status/focus/note `null` olur; tek repo yüzünden çalışma hiç durmaz.

```yaml
status: active        # active | prototype | released | maintenance | paused | archived
focus:                # Now bölümünde gösterilen cümle
  en: "..."
  tr: "..."
note:                 # isteğe bağlı
  en: "..."
  tr: "..."
```

### Now nasıl seçilir

- Son 14 günün commit'leri puanlanır: `puan = Σ ağırlık · exp(-yaş_gün / 7)`. Merge, bot, `docs/ci/chore/style/build/deps:` önekli ve badge/README commit'leri sayılmaz; `fix` yarım, diğerleri tam puan.
- `profile.json` içindeki `activityScore` zamanla azalmayan, tam sayıya yuvarlanmış ve `0..3` ile sınırlı bir kovadır (`3` = 3+); `lastWorkAt` gün hassasiyetindedir (`…T00:00:00Z`). Böylece dosya her gün değişip gereksiz commit/deploy olmaz; zamanla azalan ince puan yalnızca sıralamada kullanılır ve dosyaya yazılmaz.
- Puanı 0.3'ün üstündeki en iyi 3 repo "work" maddesi olur. Metin her zaman reponun `status.yml` içindeki iki dilli `focus` alanından gelir; `focus`'u olmayan repo (Türkçe sayfaya ham İngilizce GitHub açıklaması sızmasın diye) Now'a alınmaz ve log'a uyarı yazılır — çözüm o repoya `.github/status.yml` eklemektir.
- Son 14 günde yayınlanan release'ler (aynı repo zaten "work" ise eklenmez) "release" maddesi olur. En fazla 4 madde.
- Hiçbiri yoksa tek satır: "Quiet stretch; see the repos above."
- `archived` repolar (GitHub ya da `status: archived`) puanlanmaz. Yalnızca public, fork olmayan repolar işlenir; profil reposu ve private repolar çıktıda hiç geçmez.
- Bir repo için API çağrısı başarısız olursa o repo'nun önceki `profile.json` değerleri korunur.

### data/profile.json

Portföy sitesinin okuduğu sözleşme (`schemaVersion: 1`): `generatedAt`, `owner`, `now[]` (TR/EN metinli), `repos{}` (açıklama, status, focus, note, yıldız, `lastWorkAt`, `activityScore`, `latestRelease`), `pinned[]` (sabitleme sırasıyla public repo adları). Alanlar eklenir, mevcutlar kaldırılmaz/yeniden adlandırılmaz. `generatedAt` yalnızca dosyada başka bir şey değiştiyse yenilenir, böylece her gün boş commit atılmaz.

## Workflow

1. `build_cards.py` kartları üretir (genel bakış ve dil dağılımı).
2. `build_profile.py` README bölümlerini ve `data/profile.json`'ı üretir (`pip install pyyaml` gerekir; `GITHUB_TOKEN` pinned listesi için kullanılır).
3. Değişiklik varsa (kartlarda yalnızca tarih değişimi sayılmaz) `assets`, `README.md`, `data` commit'lenip push'lanır.
4. `data/profile.json` değiştiyse (yalnızca `generatedAt`/`activityScore`/`lastWorkAt` farkları sayılmaz) ve `VERCEL_DEPLOY_HOOK` secret'ı tanımlıysa portföy sitesi bu hook'a POST atılarak yeniden dağıtılır (hook adresi loglanmaz).
