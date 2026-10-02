package icu.savrc3.supercourse.widgets;

import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.Context;
import android.os.Bundle;

abstract class WidgetProvider extends AppWidgetProvider {
    abstract String widgetType();

    @Override
    public void onUpdate(Context context, AppWidgetManager manager, int[] widgetIds) {
        for (int widgetId : widgetIds) WidgetRenderer.update(context, manager, widgetId, widgetType());
        WidgetRenderer.scheduleNextRefresh(context);
    }

    @Override
    public void onAppWidgetOptionsChanged(Context context, AppWidgetManager manager, int widgetId, Bundle options) {
        WidgetRenderer.update(context, manager, widgetId, widgetType());
        WidgetRenderer.scheduleNextRefresh(context);
    }

    @Override
    public void onDeleted(Context context, int[] widgetIds) {
        for (int widgetId : widgetIds) {
            WidgetRenderer.clearInstance(context, widgetType(), widgetId);
        }
        WidgetRenderer.scheduleNextRefresh(context);
    }
}
