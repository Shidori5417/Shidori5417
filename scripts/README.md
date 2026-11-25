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

Ortam: `PROFILE_OWNER` (varsayılan `Shidori5417`), `GITHUB_TOKEN` (isteğe bağlı, rate limit için). `--now-date YYYY-MM-DD` "şimdi"yi o günün sonuna sabitler (test için).

### data/projects.yml: Featured ve More

README'deki içeriğin tek kaynağı. Elle düzenlenir, sıra korunur.

```yaml
owner: Shidori5417
featured:            # 2'şerli satırlarla tablo
  - repo: vuln-stack
    image: https://raw.githubusercontent.com/...
    alt: görsel açıklaması
    blurb: tek cümlelik açıklama
    stack: Rust · ratatui
more:                # madde listesi
  - repo: DomainSniper
    label: DomainGözcü   # isteğe bağlı: bağlantıdan sonra "(DomainGözcü)" yazar
    blurb: ":" sonrası gelen metin
```

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
- Puanı 0.3'ün üstündeki en iyi 3 repo "work" maddesi olur (metin: `focus`, yoksa repo açıklaması).
- Son 21 günde yayınlanan release'ler (aynı repo zaten "work" ise eklenmez) "release" maddesi olur. En fazla 4 madde.
- Hiçbiri yoksa tek satır: "Quiet stretch; see the repos above."
- `archived` repolar (GitHub ya da `status: archived`) puanlanmaz. Yalnızca public, fork olmayan repolar işlenir; profil reposu ve private repolar çıktıda hiç geçmez.
- Bir repo için API çağrısı başarısız olursa o repo'nun önceki `profile.json` değerleri korunur.

### data/profile.json

Portföy sitesinin okuduğu sözleşme (`schemaVersion: 1`): `generatedAt`, `owner`, `now[]` (TR/EN metinli), `repos{}` (açıklama, status, focus, note, yıldız, `lastWorkAt`, `activityScore`, `latestRelease`). `generatedAt` yalnızca dosyada başka bir şey değiştiyse yenilenir, böylece her gün boş commit atılmaz.

## Workflow

1. `build_cards.py` kartları üretir.
2. `build_profile.py` README bölümlerini ve `data/profile.json`'ı üretir (`pip install pyyaml` gerekir).
3. Değişiklik varsa (kartlarda yalnızca tarih değişimi sayılmaz) `assets`, `README.md`, `data` commit'lenip push'lanır.
4. `data/profile.json` değiştiyse ve `VERCEL_DEPLOY_HOOK` secret'ı tanımlıysa portföy sitesi bu hook'a POST atılarak yeniden dağıtılır (hook adresi loglanmaz).
