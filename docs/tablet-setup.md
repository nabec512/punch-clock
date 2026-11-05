# Set up an Android tablet as a shared time clock

This guide turns an Android tablet into a shared time clock that employees can use to clock in and out, but can't leave. By the end:

- The **native Jibble app** records the punches. Its kiosk mode controls how employees clock in.
- **FreeKiosk** is the tablet's Home app and Android Device Owner. It keeps employees out of Android and other apps.

Punch Clock doesn't run on the tablet. It processes the weekly export from Jibble on a Windows PC, as described in the [main README](../README.md).

Choosing a Home app and assigning Device Owner are separate steps, and neither one alone stops employees from leaving Jibble. Only the tests in [step 6](#6-test-the-tablet) show that it's locked down.

**Tested configuration:** an Android tablet running **Android 16 in a Go/low-RAM configuration** (`ro.config.low_ram=true`), with **FreeKiosk 2.0.0, version code 52**, and the **native Jibble Android app**. Verification covered Device Owner, the administrator return button and PIN, navigation restrictions, automatic startup after reboot, and an awake screen after more than 90 seconds without input. Jibble's payroll, offline-sync and employee-verification settings were outside that test. Other tablet models, firmware and app versions still need their own checks.

### Configure additional tablets

Set up **one tablet at a time**, with only that tablet connected to ADB. Find its serial with `./adb devices -l`. `YOUR_TABLET_SERIAL` in this guide is a placeholder: substitute the serial of the tablet being configured. If you keep several connected, add `-s YOUR_TABLET_SERIAL` immediately after `./adb` in **every device command**, including reboot and configuration commands. Keep real serials and deployment records outside this public repository.

Follow steps 1–7 in order. The tested settings were:

1. FreeKiosk installed as **Device Owner**, with its own **Set FreeKiosk as default launcher** control enabled.
2. **Display over other apps** explicitly allowed through ADB. Device Owner alone did not grant this on the tested firmware.
3. Android set to **stay awake while powered**, with FreeKiosk's **screensaver and screen schedule off**.
4. Jibble selected as the **single external app**, with **Lock Mode**, **Launch on Boot** and **Auto-Relaunch App** on, and **Back Button Behavior → Immediate Return**.
5. A **visible bottom-right Fixed Button**, requiring **5 taps within 3000 ms**, followed by the administrator PIN. This is the FreeKiosk corner button, **not Android's Back button**.
6. Successful administrator-access, lockdown, idle-screen and reboot tests before deployment.

The commands and exact FreeKiosk settings are below. Keep the trusted PC connected until these checks pass on each tablet.

## What you need

- The tablet, its charger and a **USB data cable** known to work. Some cables only charge.
- A trusted Windows PC to manage the tablet from, with [Git Bash](https://git-scm.com/downloads) installed.
- Google's [Android SDK Platform-Tools for Windows](https://developer.android.com/tools/releases/platform-tools), extracted to `C:\platform-tools`. You don't need Android Studio.
- Your Jibble owner, admin or manager sign-in.
- Two new PINs, one for Jibble and one for FreeKiosk, kept in secure storage. Don't put credentials, PINs or employee records in this repository.

If a factory reset ever becomes necessary, it erases local apps, settings and any punches that haven't synced. See [Remove Device Owner or start again](#remove-device-owner-or-start-again) first.

## 1. Prepare the tablet

1. Enable Developer options by tapping **Build number** seven times under **About tablet**.
2. In Developer options, turn on **USB debugging**. Leave it on until you finish [step 7](#7-finish-up).
3. Install FreeKiosk and Jibble from their official sources. FreeKiosk's [installation guide](https://github.com/RushB-fr/freekiosk/blob/main/docs/installation.md) covers its options. If they're already installed, you don't need to remove them.

## 2. Connect the tablet to the PC

Run every command in this guide in Git Bash. Don't copy prompts or example output as commands.

```bash
cd /c/platform-tools
./adb devices -l
```

Unlock the tablet and accept **Allow USB debugging?**. Choose **Always allow from this computer** only on your trusted PC.

When it's working, the tablet is listed with the status `device`:

```text
List of devices attached
YOUR_TABLET_SERIAL    device product:MODEL model:MODEL device:MODEL transport_id:2
```

If several devices are listed, disconnect the others, or add `-s YOUR_TABLET_SERIAL` after `./adb` in each command.

### If it doesn't connect

| What you see | What to do |
|---|---|
| No device listed | Replace the cable first. Then try a USB port directly on the PC, check that USB debugging is on, and try File transfer/MTP rather than charging only |
| `unauthorized` | Unlock the screen and accept the debugging prompt |
| `offline` | Reconnect the cable and restart ADB, as shown below. If it continues, restart the tablet |
| Windows sees the USB device, but ADB's list stays empty | Look for an unknown device or driver error in Device Manager. Use the tablet manufacturer's ADB driver, not a driver from an unknown source |
| `more than one device/emulator` | Disconnect the others, or use `-s` as described above |
| An error mentioning `$ADB_VENDOR_KEYS` | You probably don't need to set that variable. Check the cable and the prompt on the tablet first |

To restart ADB on the PC:

```bash
./adb kill-server
./adb start-server
./adb devices -l
```

If the prompt doesn't appear, use **Developer options → Revoke USB debugging authorizations**, turn USB debugging off and on, reconnect and accept the new prompt. This also removes access for any PC already trusted, so never do it on a tablet that's locked down.

Google's [hardware connection guide](https://developer.android.com/studio/run/device) has more on cables and drivers.

## 3. Make FreeKiosk the Device Owner

First, check that the tablet supports device administration:

```bash
./adb shell pm list features | grep device_admin
```

You should see the line below. If you don't, check the full `./adb shell pm list features` output, and don't continue until you know the firmware supports it.

```text
feature:android.software.device_admin
```

Next, check whether the tablet already has an owner:

```bash
./adb shell dumpsys device_policy | grep -A 8 "Device Owner"
```

**If you see this block, FreeKiosk is already the owner. Skip the owner-assignment command and continue with [Permissions for the native Jibble setup](#permissions-for-the-native-jibble-setup):**

```text
Device Owner:
  admin=ComponentInfo{com.freekiosk/com.freekiosk.DeviceAdminReceiver}
  package=com.freekiosk
  isOrganizationOwnedDevice=true
  User ID: 0
```

A line such as `Device Owner Type: 0`, or FreeKiosk appearing only under Enabled Device Admins, doesn't count. If you're not sure, read the full output of `./adb shell dumpsys device_policy`.

### Assign the owner

1. Check that ADB shows `device` and that FreeKiosk is installed.
2. Open **Settings → Accounts**, which may be called Passwords & accounts. Existing Android accounts can block this step. Back up what you need and make sure you have the sign-in details before removing any account from the tablet. This only removes it from the tablet, and doesn't delete the account.
3. Check for another Device Owner, a work profile or additional Android users. Don't remove another management setup or delete users just to make the command succeed.
4. Keep both apps installed, then run:

   ```bash
   ./adb shell dpm set-device-owner com.freekiosk/.DeviceAdminReceiver
   ```

5. Run the owner check above again, and look for the same block. The wording of the command's own success message varies, so rely on this check instead.

Add back only the accounts the tablet needs, if its device policy allows it.

| If it fails with | What to check |
|---|---|
| Accounts already exist | Any Android accounts still on the tablet, including work accounts. Don't erase data as your first response |
| An owner already exists | The output of `dumpsys device_policy`. If it's FreeKiosk, continue. If it's another app, sort out that management setup first |
| Unknown admin or component | That the command was typed exactly, and that `./adb shell pm list packages com.freekiosk` shows `package:com.freekiosk` |
| Additional users, or a provisioning or firmware error | Keep the exact error and check `./adb shell pm list users` and the policy output before changing anything |

### Permissions for the native Jibble setup

These permissions don't assign Device Owner or enable lockdown by themselves.

**Required for the tested corner-button setup: allow FreeKiosk to display over other apps.** On the tested Android Go firmware, the return button was unreliable or unavailable even though FreeKiosk was Device Owner. Android showed the overlay permission as `default`, and the logs reported `permission denied for window type 2038`. This command fixed the missing overlay:

```bash
./adb shell appops set com.freekiosk SYSTEM_ALERT_WINDOW allow
./adb shell appops get com.freekiosk SYSTEM_ALERT_WINDOW
```

The check must report `SYSTEM_ALERT_WINDOW: allow`. A historical `rejectTime` can still appear after the fix; it doesn't undo the current `allow` state. After granting it, return to Jibble and test the corner button. Don't assume Device Owner granted this permission automatically, or that Android Go makes the feature impossible.

**Usage access:** this was enabled in the tested configuration. Allow it so FreeKiosk can monitor which app is in front:

```bash
./adb shell appops set com.freekiosk android:get_usage_stats allow
./adb shell appops get com.freekiosk android:get_usage_stats
```

Expect `GET_USAGE_STATS: allow` (the output may use the uppercase operation name).

**Optional, not established as necessary in the successful test:** FreeKiosk documents this permission for automatically configuring its accessibility service:

```bash
./adb shell pm grant com.freekiosk android.permission.WRITE_SECURE_SETTINGS
```

To check that optional permission, look for `granted=true`. A permission listed only as requested hasn't been granted.

```bash
./adb shell dumpsys package com.freekiosk | grep -A 3 WRITE_SECURE_SETTINGS
```

- **Accessibility service:** the second permission doesn't turn the service on. If you need it, use FreeKiosk's accessibility controls or Android's Accessibility settings, then confirm it's running.
- **Errors:** if a command reports an undeclared permission, a `SecurityException` or an unsupported operation, keep the error and check your FreeKiosk version.
- **Overlay still unavailable:** check the `SYSTEM_ALERT_WINDOW` result, the selected return-button settings in step 5, and the exact warning. Usage access and `WRITE_SECURE_SETTINGS` are separate permissions and do not replace the overlay grant.

FreeKiosk's [ADB instructions](https://github.com/RushB-fr/freekiosk/blob/main/docs/adb-configuration.md) cover these in more detail.

## 4. Set up the Jibble kiosk

Get clocking in working in Jibble before you lock down Android.

1. Open Jibble and sign in with your owner, admin or manager account.
2. Go to **Menu → Kiosk** and choose **Set up Kiosk Mode**, or **Switch to Kiosk** if it's already set up.
3. Select the employees or groups, name the kiosk after its location, and set the Jibble PIN.
4. Open the kiosk settings with the gear icon and your PIN, and choose the settings below.

| Setting | Suggestion |
|---|---|
| Clock-in method | Start with Basic Mode for a simple test. Add face recognition, QR or NFC only if you need them, and only after testing them on your tablet |
| Employee verification | Follow your site's policy. Choosing a name from a list doesn't verify who someone is |
| Camera and location permissions | Grant only what your chosen features need, before lockdown. Test at the tablet's final location |
| Time and connection | Check the tablet's date, time, time zone and Wi-Fi against your Jibble setup |
| Breaks | Turn off Jibble's break button if you can. Punch Clock refuses exports with break punches, because it [deducts a fixed lunch](../README.md#how-hours-are-calculated) |
| Offline tracking | Turn on only if your site wants it, then test an outage and check that punches sync afterward |

Then make a clearly labeled test clock-in and clock-out, and check that they appear in Jibble's timesheet. Have an administrator deal with those test entries so they don't end up in payroll.

Jibble's guides cover [kiosk setup](https://www.jibble.io/help/set-up-kiosk-mode-to-use-your-tablet-as-a-shared-time-clock) and [kiosk settings](https://www.jibble.io/help/managing-kiosk-settings). The Jibble PIN protects Jibble's settings, and the FreeKiosk PIN protects the tablet's. Keep them as two separate PINs.

## 5. Set up FreeKiosk

### Keep the screen awake while plugged in

Use Android's **Developer options → Stay awake** setting, or run the tested command:

```bash
./adb shell svc power stayon true
./adb shell input keyevent 224
./adb shell settings get global stay_on_while_plugged_in
./adb shell dumpsys power | grep -E 'mWakefulness=|mIsPowered=|mStayOn='
```

`input keyevent 224` wakes the display without toggling it off. The tested Android version returned `15` for `stay_on_while_plugged_in`, plus `mWakefulness=Awake`, `mIsPowered=true` and `mStayOn=true`. The value persisted after reboot. A different Android version may use a different power-source bitmask; confirm actual behavior as well as the setting.

In FreeKiosk's **Display** tab, set:

| Control | Tested setting |
|---|---|
| Enable Screensaver | **Off**, including Dim Only mode |
| Enable Screen Schedule | **Off** |
| Show Status Bar | **Off** (FreeKiosk's custom status bar) |

The tested External App configuration used Android's keep-awake control; a generic FreeKiosk Keep Screen On control was not visible in this screen. Don't rely on a WebView-only setting to keep the native Jibble app awake.

This prevents **idle sleep while the tablet is powered**. It doesn't promise the screen stays on when unplugged, and a short press of the physical power button can still switch it off. Keep the production tablet connected to its charger. After setup, don't turn off the master Developer options switch as part of disabling USB debugging; recheck Stay awake after any change to Developer options.

### Select Jibble and configure the administrator return

1. Open FreeKiosk's settings and set an administrator PIN that isn't the default. Enter it locally on the tablet; don't put it in a command, chat or this repository.
2. In **General**, choose **Display Mode → App**, **App Mode → Single App**, and select **Jibble 2** from the picker. On the tested tablet its package was `io.jibble.androidclient.jibble`. This uses the installed Android app, with no Jibble web address.
3. In **Security → Return to Settings**, configure the following:

   | Control | Tested setting |
   |---|---|
   | Return mode | **Fixed Button** |
   | Number of Taps | **5** |
   | Detection Timeout | **3000 ms** (three seconds for all five taps) |
   | Button position | **Bottom Right** |
   | Show Button | **On** |
   | Volume Button Alternative | **Off** |

4. Save, acknowledge the confirmation, and return to Jibble. If FreeKiosk shows **Waiting for application…**, tap **Return to Application**.
5. Tap the **visible bottom-right FreeKiosk button five times within three seconds**, then enter the PIN and tap **Validate**. If FreeKiosk first shows its return screen, tap **Settings** to reach the PIN prompt. Confirm Settings remains open without bouncing back to Jibble. Do this before enabling lockdown.

The original 1500 ms tap window and invisible button were less forgiving. Making the button visible and allowing 3000 ms made the gesture easier to perform. **Five presses of Android's Back button are not the administrator gesture.**

### Enable the final lockdown settings

In FreeKiosk's **Security** tab, use these settings. Save after editing; don't leave the tablet in its temporary testing configuration.

| Control | Tested setting |
|---|---|
| Enable Lock Mode | **On** |
| Launch on Boot | **On** |
| Set FreeKiosk as default launcher | **On**, using FreeKiosk's own control |
| Auto-Relaunch App | **On** |
| Back Button Behavior | **Immediate Return** |
| Block Power Menu | **On**; this does not block a short power-button press |
| Allow Notifications (NFC) | **Off**; NFC clocking was not tested with this configuration |
| Show System Info Bar | **Off** (Android's status information) |
| Allow the USB Debugging Prompt In Lock Mode | **Off**; authorize the maintenance PC before locking down |
| System screen-lock compatibility | **Off** for the tested configuration without a native Android PIN/password lock; reassess if you configure one |
| Enable Lock Screen Controls | **Off** |

The tested configuration left **Block Factory Reset**, **Allow Remote Screenshots** and **Allow Screenshots With Hardware Buttons** off. These were not needed to resolve the screen-sleep and return-button problems. Factory-reset resistance and screenshot restrictions were not acceptance-tested.

Tap **Save** at the bottom and acknowledge **Configuration saved / Lock mode enabled**. Return to Jibble if needed, then perform step 6 with restrictions active.

**Keep FreeKiosk as the default launcher for deployment.** Testing with the native Android Go launcher (`com.android.launcher3/.Launcher3QuickStepGo`) briefly exposed the ordinary Android home screen after reboot, before FreeKiosk started and locked Jibble. Restoring FreeKiosk's own default-launcher setting removed that observed home-screen gap in the repeat test. Choosing the native launcher is a maintenance step, not the final setup.

Check the selected Home app:

```bash
./adb shell cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME
```

The tested FreeKiosk version returned `com.freekiosk/.MainActivity`.

FreeKiosk's [feature guide](https://github.com/RushB-fr/freekiosk/blob/main/docs/features-and-modes.md) and [documentation](https://freekiosk.app/docs/) describe these controls. Android's [lock task documentation](https://developer.android.com/work/dpc/dedicated-devices/lock-task-mode) explains how this differs from ordinary screen pinning, which anyone can leave. Seeing a screen-pinning message doesn't mean the tablet is locked down.

## 6. Test the tablet

Run these with an administrator present and the USB connection still available.

### Results from the tested configuration

These results apply to the configuration described above. Repeat the checks on every tablet:

| Check | Observed result |
|---|---|
| Five taps and correct PIN | Physical taps on the corner button followed by the correct PIN opened Settings successfully |
| PIN screen stays protected | Home and Recent Apps did not bypass the PIN screen; it stayed open without the earlier flickering |
| Navigation while Jibble is running | Home, Recent Apps and Back did not escape the managed kiosk; Jibble remained or returned |
| Swipe down from the top | Did not open usable notification/system controls |
| Android kiosk state | `mLockTaskModeState=LOCKED`, with FreeKiosk and Jibble in the allowed package list |
| Restart | After restoring FreeKiosk as default launcher, startup went through FreeKiosk into Jibble's kiosk activity in locked mode, without the ordinary launcher appearing in the observed sequence |
| Return button after restart | Five taps opened a stable PIN screen; returning from that screen brought back locked Jibble |
| Idle display after restart | More than 90 seconds without input, beyond the configured 60-second timeout: display `ON`, power state `Awake`, `mStayOn=true`, Jibble still `LOCKED` |

For each tablet, repeat the physical tap/PIN test and the navigation checks. Then use these read-only checks:

```bash
./adb shell dumpsys activity activities | grep -E 'ResumedActivity|mLockTaskModeState'
./adb shell dumpsys power | grep -E 'mWakefulness=|mIsPowered=|mStayOn=|mScreenOffTimeoutSetting=|lastUserActivityTime='
./adb shell dumpsys display | grep -E 'mScreenState=|mScreenBrightness='
```

In the tested configuration, the foreground Jibble activity was `io.jibble.androidclient.kiosk.KioskNavigationActivity`, in package `io.jibble.androidclient.jibble`. Expect `LOCKED`, not `NONE` or ordinary screen pinning. For the idle test, leave the tablet untouched for longer than its configured timeout and verify the screen is visibly on as well as checking the output. A saved setting alone doesn't prove the result.

### Full deployment checklist

The broader checks below still apply. **Test punches, offline sync, export/payroll results, cold power-off/on, physical power-button behavior, external links and keyboard escape routes were outside the configuration test.** Don't mark them passed solely because the checks above passed.

| Test | It passes when |
|---|---|
| Admin access before lockdown | The gesture or button opens the PIN prompt, and the correct PIN opens the settings |
| Admin access with Jibble in front | The same route works, and nobody gets into the settings without the PIN |
| Home and Recent Apps | They don't lead to the normal launcher, other apps or Android settings |
| Back, pressed repeatedly | It doesn't lead out of the kiosk. Jibble stays usable or comes back by itself |
| Notification shade and Quick Settings | Employees can't open system controls or follow a notification out of the kiosk |
| Links, dialogs, keyboard settings and power controls | None lead to other apps or device settings. Note any your firmware can't block |
| Relaunch | After punches have synced, closing or restarting Jibble brings back a usable kiosk, with no login loop |
| Normal restart | FreeKiosk starts and Jibble opens, with no Home app prompt and nothing to do by hand. Note any unlock screen that gets in the way |
| Power off and on | The launch, restriction and admin access checks all still pass. Turning on by itself after a power cut depends on the hardware, so test it separately |
| Idle screen on charger | The display remains on beyond its normal timeout; repeat after reboot and on the final wall charger, not just the PC's USB port |
| Sleep and wake | If someone manually switches the screen off, waking it returns to the protected time clock and the administrator button still works |
| Network outage | It behaves as your offline policy says, and test punches sync afterward with no duplicates |
| Clock in and out, then export | Entries appear under the right employee and time zone, and a weekly export works in Punch Clock |

To restart the tablet from the PC, first make sure nobody is entering a punch:

```bash
./adb reboot
```

After it starts up, run the owner check from [step 3](#3-make-freekiosk-the-device-owner) again, and test Home and admin access again.

## 7. Finish up

Once every test passes:

1. Make sure an administrator knows how to turn USB debugging back on through the tested admin route.
2. Turn off USB debugging for everyday use, and protect physical access to the USB port.
3. Keep a maintenance record outside this repository for each tablet, with its serial, Android/FreeKiosk/Jibble versions, the return gesture, Jibble mode, test results and who holds the PINs. Record the PINs themselves only in secure credential storage.

Keep USB debugging available during setup and recovery checks. Disabling it is a separate deployment step and was outside the configuration test. Disable USB debugging separately from the master Developer options switch, then verify the screen still stays awake on its charger and the five-tap administrator route still works.

To get the versions, run these before turning off USB debugging. Jibble's version is on its Android **App info** page.

```bash
./adb shell getprop ro.build.version.release
./adb shell getprop ro.build.version.sdk
./adb shell dumpsys package com.freekiosk | grep -E 'versionName|versionCode'
```

Repeat the relevant tests after any Jibble, FreeKiosk or firmware update.

## Maintenance and recovery

### Everyday maintenance

Tap the visible **bottom-right button five times within three seconds**, enter the FreeKiosk PIN on the tablet, and tap **Validate**. If the FreeKiosk return screen appears first, choose **Settings**. Use Jibble's separate PIN for Jibble's own settings. Opening the FreeKiosk PIN screen does not itself remove lockdown: it remained `LOCKED` during testing.

After maintenance, save the intended settings, acknowledge the confirmation and return to Jibble. Verify it is usable and locked. Opening Settings or temporarily turning Lock Mode off doesn't remove Device Owner, and routine work doesn't require removing it.

### If the gesture or Jibble stops working

1. Connect the PC you already authorized, using the known-good cable, and run `./adb devices -l`.
2. If it shows `device`, first check the overlay permission, which caused the failed administrator return during testing, and wake the screen if necessary:

   ```bash
   ./adb shell input keyevent 224
   ./adb shell appops get com.freekiosk SYSTEM_ALERT_WINDOW
   ./adb shell appops set com.freekiosk SYSTEM_ALERT_WINDOW allow
   ./adb shell appops get com.freekiosk SYSTEM_ALERT_WINDOW
   ```

   Once it reports `allow`, try five taps on the actual corner button again. Check **Fixed Button**, **Bottom Right**, **Show Button on**, **5 taps**, **3000 ms** when you regain Settings. Don't repeatedly press Android Back expecting the PIN prompt.

3. If the button still doesn't work, save the policy output and your versions. You can try opening FreeKiosk's main screen, but this is **not a reliable direct route to its PIN screen**: auto-relaunch brought Jibble back during testing. It doesn't authenticate you or bypass the PIN.

   ```bash
   ./adb shell am start -n com.freekiosk/.MainActivity
   ```

4. If it shows `unauthorized`, the tablet needs to approve this PC, and lockdown may hide the prompt. Use the admin route to pause lockdown and approve it. Don't revoke the only working authorization, and don't assume another PC can recover the tablet.
5. If USB debugging is off or you can't approve the PC, ADB can't help. Contact your device administrator or vendor with your versions and what happened. Don't clear Jibble's data or uninstall apps as a first response.

### Temporarily use the native launcher for maintenance

This procedure was tested after administrator authentication. **It deliberately allows leaving Jibble**, so do it only while an administrator controls the tablet:

1. Open FreeKiosk Settings with the PIN.
2. Set **Enable Lock Mode off**, **Auto-Relaunch App off**, **Back Button Behavior → Test Mode**, and **Set FreeKiosk as default launcher off**. Save and acknowledge the confirmation.
3. Select the native Android Home app in Android settings. On the tested Android Go firmware, the following command also worked:

   ```bash
   ./adb shell cmd package set-home-activity --user 0 com.android.launcher3/.Launcher3QuickStepGo
   ./adb shell cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME
   ```

   Don't assume this component exists on another model. Turn off FreeKiosk's own launcher setting first: during testing, the shell command reported success while FreeKiosk's persistent Home policy still overrode the selection.

4. Confirm Home opens the native launcher. When maintenance is finished, restore **all final settings in step 5**, including FreeKiosk as default launcher, save, return to Jibble and repeat the lock, PIN and reboot tests. Do not hand over a tablet still in Test Mode.

The successful repair needed **no factory reset, app-data clearing, uninstall or removal of Device Owner**.

### Remove Device Owner or start again

To retire the tablet or change management software, use FreeKiosk's **Remove Device Owner** control if your version has it. Then check that the owner block is gone, and choose the Home app you want.

Don't count on `dpm remove-active-admin com.freekiosk/.DeviceAdminReceiver` as an emergency unlock. [Android's ADB reference](https://developer.android.com/tools/adb#dpm) limits it to admins declaring `android:testOnly`, so a normal release build may reject it, even though FreeKiosk's documentation lists it.

A factory reset is the last resort, and may be needed if the PIN is lost and nothing else works. Before you reset:

1. Check that Jibble's entries have synced.
2. Save the configuration details securely.
3. Confirm you have the account and recovery sign-ins.
4. Get approval from whoever owns the device.
