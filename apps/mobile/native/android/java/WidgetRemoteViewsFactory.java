package icu.savrc3.supercourse.widgets;

import android.content.Context;
import android.content.Intent;
import android.widget.RemoteViews;
import android.widget.RemoteViewsService;
import icu.savrc3.supercourse.R;
import org.json.JSONArray;
import org.json.JSONObject;

final class WidgetRemoteViewsFactory implements RemoteViewsService.RemoteViewsFactory {
    private final Context context;
    private final int widgetId;
    private final String type;
    private JSONArray items = new JSONArray();

    WidgetRemoteViewsFactory(Context context, int widgetId, String type) {
        this.context = context;
        this.widgetId = widgetId;
        this.type = type;
    }

    @Override public void onCreate() { }

    @Override
    public void onDataSetChanged() {
        JSONObject snapshot = WidgetRenderer.readSnapshot(context);
        if (WidgetRenderer.TODAY.equals(type)) {
            String today = WidgetRenderer.today();
            JSONArray events = snapshot.optJSONArray("events");
            JSONArray result = new JSONArray();
            if (events != null) {
                for (int index = 0; index < events.length(); index++) {
                    JSONObject event = events.optJSONObject(index);
                    if (event != null && today.equals(event.optString("date"))) result.put(event);
                }
            }
            items = result;
        } else if (WidgetRenderer.TODOS.equals(type)) {
            JSONArray source = snapshot.optJSONArray("todos");
            JSONArray result = new JSONArray();
            if (source != null) {
                for (int index = 0; index < Math.min(5, source.length()); index++) result.put(source.optJSONObject(index));
            }
            items = result;
        } else {
            items = new JSONArray();
        }
    }

    @Override public void onDestroy() { items = new JSONArray(); }
    @Override public int getCount() { return items.length(); }

    @Override
    public RemoteViews getViewAt(int position) {
        JSONObject item = items.optJSONObject(position);
        if (item == null) return null;
        RemoteViews row = new RemoteViews(context.getPackageName(), R.layout.widget_list_row);
        if (WidgetRenderer.TODAY.equals(type)) {
            String start = item.optString("start", "") + "–" + item.optString("end", "");
            row.setTextViewText(R.id.widget_item_time, start);
            row.setTextViewText(R.id.widget_item_title, item.optString("title", "课程"));
            row.setTextViewText(R.id.widget_item_detail, WidgetRenderer.displayRoom(item));
            row.setTextColor(R.id.widget_item_time, context.getColor(R.color.widget_secondary));
            row.setTextColor(R.id.widget_item_title, context.getColor(R.color.widget_ink));
            row.setTextColor(R.id.widget_item_detail, context.getColor(R.color.widget_secondary));
        } else {
            String due = WidgetRenderer.formatDue(item.optString("dueAt", ""), item.optBoolean("allDay", false));
            String course = item.optString("courseName", "");
            row.setTextViewText(R.id.widget_item_time, due);
            row.setTextViewText(R.id.widget_item_title, item.optString("title", "待办"));
            row.setTextViewText(R.id.widget_item_detail, course.isEmpty() ? "" : course);
            boolean overdue = WidgetRenderer.isOverdue(item.optString("dueAt", ""), item.optBoolean("allDay", false));
            row.setTextColor(R.id.widget_item_time, context.getColor(overdue ? R.color.widget_accent : R.color.widget_secondary));
            row.setTextColor(R.id.widget_item_title, context.getColor(R.color.widget_ink));
            row.setTextColor(R.id.widget_item_detail, context.getColor(R.color.widget_secondary));
        }
        row.setOnClickFillInIntent(R.id.widget_item_root, new Intent().putExtra("widgetRoute", routeFor(item)));
        return row;
    }

    private String routeFor(JSONObject item) {
        if (WidgetRenderer.TODAY.equals(type)) {
            return "/courses/" + item.optString("courseId", "") + "?date=" + item.optString("date", "");
        }
        return "/todo/" + item.optString("id", "");
    }

    @Override public RemoteViews getLoadingView() { return null; }
    @Override public int getViewTypeCount() { return 1; }
    @Override public long getItemId(int position) {
        JSONObject item = items.optJSONObject(position);
        return item == null ? position : item.optString("id", String.valueOf(position)).hashCode();
    }
    @Override public boolean hasStableIds() { return true; }
}
