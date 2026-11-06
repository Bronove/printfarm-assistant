# Release Checklist

## Before pushing

1. Confirm the public repository is `Bronove/printfarm-assistant`.
2. Run the public-source checks from `app/ui_v2`:

   ```powershell
   npm ci
   npm run build
   $env:PRINTFARM_PYTHON = "D:\python\python.exe"
   npm run test:backend
   npm run test:ui
   .\protected_core.exe version
   Get-FileHash .\protected_core.exe -Algorithm SHA256
   ```

3. Manually test multicolor planning from a real multi-color 3MF on the target
   host, including editable 3MF and printable output paths. Automated Codex
   runs must not be treated as a substitute for this host check.
4. Confirm that a missing, modified or old `protected_core.exe` is rejected.
5. Confirm no model, log, user configuration, API key, token, or password is
   present in the Git diff.
6. Review `NOTICE.md`, `THIRD_PARTY_NOTICES.md`, and the GPL text.

## Tag and release

```powershell
git add .
git commit -m "Release PrintFarm Assistant 1.6.0-beta.1"
git tag -a v1.6.0-beta.1 -m "PrintFarm Assistant 1.6.0-beta.1"
git push origin main
git push origin v1.6.0-beta.1
```

Create a GitHub Draft Release for tag `v1.6.0-beta.1` and attach:

- `PrintFarmAssistant-v1.6.0-beta.1-win64-setup.exe`
- `SHA256SUMS.txt`
- `COMPONENT-SHA256SUMS.txt`
- `PrintFarmAssistant-1.6.0-beta.1.spdx.json`
- `RELEASE_NOTES_1.6.0-beta.1.md`
- `MIT-LICENSE.txt`
- `GPL-2.0.txt`
- `THIRD_PARTY_NOTICES.md`

The local release bundle is:

```text
C:\Users\bronove\Documents\ChatGPT\打印农场\ui_v2\release\1.6.0-beta.1
```

## After publication

1. Download the release asset again and verify its SHA-256.
2. Test a clean install from the downloaded file, not the build folder.
3. Mark the release as a pre-release while `1.6.0-beta.1` remains the app version.
4. Keep the GitHub token and any API keys out of issue reports and logs.
