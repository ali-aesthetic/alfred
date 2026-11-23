# Apple signing & notarization — what the user does himself

**Why:** without it, other people's Macs show "can't be opened, developer not verified". Building from source (install.sh) does not need it.

| Cost | |
|---|---|
| **$99 / year** | Apple Developer Program (individual). Free tier cannot make Developer ID certificates |
| $0 | notarization itself (included) |

## Checklist (all need the maintainer's Apple ID)
- [ ] 1. Enroll at developer.apple.com/programs (ID check, can take 1–2 days)
- [ ] 2. Xcode → Settings → Accounts → Manage Certificates → **+ Developer ID Application**
- [ ] 3. Make an app-specific password at account.apple.com (for notarytool)
- [ ] 4. Store it once in Keychain:
```bash
xcrun notarytool store-credentials "alfred-notary" --apple-id "YOU@EMAIL" --team-id "TEAMID"
```
- [ ] 5. Sign with hardened runtime (`mac-app/build.sh` already takes `SIGN_ID`; with `-` it signs ad-hoc):
```bash
codesign --force --options runtime --timestamp --sign "Developer ID Application: NAME (TEAMID)" Alfred.app
```
- [ ] 6. Zip, notarize, staple:
```bash
ditto -c -k --keepParent Alfred.app Alfred.zip
xcrun notarytool submit Alfred.zip --keychain-profile "alfred-notary" --wait
xcrun stapler staple Alfred.app
```
- [ ] 7. Pack a `.dmg`, notarize it too, attach to a GitHub Release.

## Things the code must handle first (dev work, not the user)
- Hardened runtime needs entitlements: microphone, camera, Apple Events (automation), disable-library-validation if the app launches the Python brain.
- The app launches a separate Python brain: ship it inside the app or download on first run (signed binaries only).
- Permissions users will see: Microphone, Accessibility, Screen Recording, Automation, Camera (optional).
