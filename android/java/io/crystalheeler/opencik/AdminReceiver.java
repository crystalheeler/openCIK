package io.crystalheeler.opencik;

import android.app.admin.DeviceAdminReceiver;
import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;

/**
 * Device admin receiver for openCIK.
 *
 * Required so the app can call DevicePolicyManager.lockNow() and
 * .wipeData(). The user grants device admin once via Settings; until
 * they do, both calls throw SecurityException.
 *
 * onDisableRequested is the tampering-defense hook (M8): when the user
 * (or an attacker) goes to Settings to disable openCIK's admin, this
 * callback fires WHILE admin is still active. If the user has both
 * armed the app AND enabled "wipe on admin disable" in Settings, we
 * fire wipeData() from here BEFORE admin gets revoked.
 *
 * Reads state from the same arm.json + settings.json that the Python
 * side writes. JSON files are tiny so we just re-parse on each call.
 */
public class AdminReceiver extends DeviceAdminReceiver {

    private static final String TAG = "opencik-admin";

    public static ComponentName componentName(Context ctx) {
        return new ComponentName(ctx, AdminReceiver.class);
    }

    @Override
    public void onEnabled(Context context, Intent intent) {
        super.onEnabled(context, intent);
        Log.i(TAG, "device admin enabled");
    }

    @Override
    public void onDisabled(Context context, Intent intent) {
        super.onDisabled(context, intent);
        Log.i(TAG, "device admin disabled");
    }

    /**
     * Called when the user has tapped "Disable" in the device admin
     * settings, BEFORE the actual disable goes through. The return
     * value is shown to the user as a confirmation message; returning
     * the empty string skips the confirmation.
     *
     * This is also our hook to detect an attacker (or an unwary user)
     * trying to defang openCIK. If the user has armed the app AND
     * enabled the "wipe on admin disable" setting, we fire
     * DevicePolicyManager.wipeData() FROM HERE — admin is still
     * active at this point, so the call succeeds.
     */
    @Override
    public CharSequence onDisableRequested(Context context, Intent intent) {
        Log.w(TAG, "device admin disable REQUESTED — evaluating M8 wipe");

        boolean armed = readArmed(context);
        boolean wipeOnDisable = readSetting(
            context, "wipe_on_admin_disable", false
        );

        Log.w(TAG, "armed=" + armed
              + " wipe_on_admin_disable=" + wipeOnDisable);

        if (armed && wipeOnDisable) {
            Log.w(TAG, "M8 trigger — firing wipeData() from "
                  + "onDisableRequested");
            try {
                DevicePolicyManager dpm = (DevicePolicyManager)
                    context.getSystemService(Context.DEVICE_POLICY_SERVICE);
                // 0 = no flags. WIPE_RESET_PROTECTION_DATA=2 would also
                // wipe FRP; we don't enable that here.
                dpm.wipeData(0);
            } catch (Throwable t) {
                Log.e(TAG, "wipeData() from onDisableRequested failed", t);
            }
            // Whatever we return here is moot — the device will be
            // wiping by the time the user sees a dialog.
            return "openCIK is armed — the device is wiping now.";
        }

        // Not armed, or wipe-on-disable is off — just warn the user
        return "Disabling openCIK admin will leave the device "
             + "unprotected. If openCIK is armed and 'wipe on admin "
             + "disable' is enabled, this action triggers a factory "
             + "reset.";
    }

    // ---- shared-state file readers (M8 + lifecycle hooks) ----

    /** Read arm.json's `armed` boolean. */
    private boolean readArmed(Context ctx) {
        JSONObject json = readJson(ctx, "arm.json");
        if (json == null) return false;
        return json.optBoolean("armed", false);
    }

    /** Read settings.json and return one boolean key. */
    private boolean readSetting(Context ctx, String key, boolean def) {
        JSONObject json = readJson(ctx, "settings.json");
        if (json == null) return def;
        return json.optBoolean(key, def);
    }

    /**
     * Slurp app-private files/<name> as JSON. Returns null on any
     * error (file missing, parse error, IO error). Caller falls back
     * to defaults — we never want a missing file to throw and
     * accidentally fire a wipe.
     */
    private JSONObject readJson(Context ctx, String name) {
        File f = new File(ctx.getFilesDir(), name);
        if (!f.isFile()) return null;
        try (BufferedReader r = new BufferedReader(new FileReader(f))) {
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) sb.append(line);
            return new JSONObject(sb.toString());
        } catch (IOException | JSONException | RuntimeException e) {
            Log.w(TAG, "could not read " + name, e);
            return null;
        }
    }
}
