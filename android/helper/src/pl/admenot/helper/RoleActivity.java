package pl.admenot.helper;

import android.app.Activity;
import android.app.role.RoleManager;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.provider.Telephony;

/** `am start -n pl.admenot.helper/.RoleActivity`: shows the system "default SMS app" dialog, then closes. */
public final class RoleActivity extends Activity {
    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (state != null) return; // dialog already requested before a configuration change
        try {
            startActivityForResult(request(), 1);
        } catch (RuntimeException e) {
            finish();
        }
    }

    private Intent request() {
        if (Build.VERSION.SDK_INT >= 29) {
            RoleManager rm = getSystemService(RoleManager.class);
            return rm.createRequestRoleIntent(RoleManager.ROLE_SMS);
        }
        return new Intent(Telephony.Sms.Intents.ACTION_CHANGE_DEFAULT)
                .putExtra(Telephony.Sms.Intents.EXTRA_PACKAGE_NAME, getPackageName());
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        finish();
    }
}
