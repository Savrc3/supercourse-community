package icu.savrc3.supercourse;

import android.content.Intent;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;
import icu.savrc3.supercourse.widgets.WidgetPlugin;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(WidgetPlugin.class);
        super.onCreate(savedInstanceState);
        WidgetPlugin.captureRoute(this, getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        WidgetPlugin.captureRoute(this, intent);
    }
}
