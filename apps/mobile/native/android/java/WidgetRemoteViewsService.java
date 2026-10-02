package icu.savrc3.supercourse.widgets;

import android.appwidget.AppWidgetManager;
import android.content.Intent;
import android.widget.RemoteViewsService;

public class WidgetRemoteViewsService extends RemoteViewsService {
    @Override
    public RemoteViewsFactory onGetViewFactory(Intent intent) {
        return new WidgetRemoteViewsFactory(
            getApplicationContext(),
            intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID),
            intent.getStringExtra(WidgetRenderer.EXTRA_WIDGET_TYPE)
        );
    }
}
