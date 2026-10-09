# EnigmaPlay Store

متجر إضافات لأجهزة إنيجما2 — هذا المستودع يحتوي **بيانات المتجر فقط** (القائمة الموقّعة والملفات والصور).
كود EnigmaPlay خاص ومحمي (انظر [LICENSE](LICENSE)).

## التثبيت على الرسيفر
```sh
wget -qO- https://raw.githubusercontent.com/Ahmadarjan1/EnigmaPlay-Repo/main/install.sh | sh
```

## المحتوى
- `index.json` — قائمة المتجر، موقّعة بـ Ed25519 (يرفض البلجن أي قائمة غير موقّعة).
- `packages/<category>/<id>.json` — بيانات كل بلجن · `categories.json` — الأقسام.
- `files/`, `icons/`, `screenshots/` — ملفات التثبيت والصور.
- `tools/` و `.github/workflows/` — بناء القائمة وتوقيعها، استيراد طلبات المطوّرين، ومزامنة البلجنات من مستودعات مطوّريها.

للمطوّرين: ارفع بلجنك من بوابة المطوّرين في المتجر.

© 2026 Ahmad Alarjan — جميع الحقوق محفوظة.
