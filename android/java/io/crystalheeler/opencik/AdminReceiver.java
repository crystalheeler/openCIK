package io.crystalheeler.opencik;

import android.app.admin.DeviceAdminReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

/**
 * Device admin receiver for openCIK.
 *
 * Required by Android so we can call DevicePolicyManager.lockNow()
 * and (later, in M7) DevicePolicyManager.wipeData(). The user must
 * grant device-admin permission once via Settings → Security →
 * Device admin apps; until they do, lockNow()/wipeData() will throw
 * SecurityException.
 *
 * The XML policy file at res/xml/device_admin.xml declares which
 * policies this admin requests (force-lock, wipe-data). It is
 * registered via the manifest <receiver> entry that our build
 * pipeline injects into the p4a manifest template.
 *
 * onDisableRequested is intentionally NOT empty — in a duress
 * deployment, an attacker hitting Settings to revoke admin is a
 * tampering signal. M8 will wire up a "wipe on disable attempt"
 * toggle that fires the wipe trigger from this callback.
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

    @Override
    public CharSequence onDisableRequested(Context context, Intent intent) {
        Log.w(TAG, "device admin disable requested");
        return "Disabling openCIK admin will leave the device unprotected. "
             + "If openCIK is currently armed and 'wipe on admin disable' "
             + "is enabled, this action will trigger a factory reset.";
    }
}
