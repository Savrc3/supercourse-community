package icu.savrc3.supercourse.widgets;

import android.content.Intent;
import android.content.SharedPreferences;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "AndroidWidgets")
public class WidgetPlugin extends Plugin {
    static WidgetPlugin instance;
    static final String PREFS = "supercourse_android_widgets";
    static final String SNAPSHOT = "snapshot";
    static final String ROUTE = "pending_route";

    @Override
    public void load() {
        instance = this;
    }

    @PluginMethod
    public void saveSnapshot(PluginCall call) {
        String snapshot = call.getString("snapshot");
        if (snapshot == null || snapshot.length() > 1_000_000) {
            call.reject("Invalid widget snapshot");
            return;
        }
        getContext().getSharedPreferences(PREFS, 0).edit().putString(SNAPSHOT, snapshot).apply();
        WidgetRenderer.updateAll(getContext());
        call.resolve();
    }

    @PluginMethod
    public void getPendingRoute(PluginCall call) {
        SharedPreferences prefs = getContext().getSharedPreferences(PREFS, 0);
        String route = prefs.getString(ROUTE, "");
        prefs.edit().remove(ROUTE).apply();
        JSObject result = new JSObject();
        result.put("route", route);
        call.resolve(result);
    }

    public static void captureRoute(android.content.Context context, Intent intent) {
        if (intent == null) return;
        String route = intent.getStringExtra("widgetRoute");
        if (route == null || !(route.equals("/") || route.startsWith("/courses/") || route.startsWith("/todo/"))) return;
        context.getSharedPreferences(PREFS, 0).edit().putString(ROUTE, route).apply();
        WidgetPlugin plugin = instance;
        if (plugin != null) {
            JSObject data = new JSObject();
            data.put("route", route);
            plugin.notifyListeners("widgetNavigate", data, true);
        }
    }
}
