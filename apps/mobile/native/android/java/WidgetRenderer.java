package icu.savrc3.supercourse.widgets;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.widget.RemoteViews;
import icu.savrc3.supercourse.MainActivity;
import icu.savrc3.supercourse.R;
import java.text.SimpleDateFormat;
import java.text.ParseException;
import java.util.Calendar;
import java.util.Date;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

final class WidgetRenderer {
    static final String GUIDE = "guide";
    static final String TODAY = "today";
    static final String OVERVIEW = "overview";
    static final String TODOS = "todos";
    static final String EXTRA_WIDGET_TYPE = "widgetType";
    private static final String[] TYPES = { GUIDE, TODAY, OVERVIEW, TODOS };

    private WidgetRenderer() { }

    static JSONObject readSnapshot(Context context) {
        String raw = context.getSharedPreferences(WidgetPlugin.PREFS, Context.MODE_PRIVATE)
            .getString(WidgetPlugin.SNAPSHOT, "{}");
        try {
            return new JSONObject(raw);
        } catch (JSONException ignored) {
            return new JSONObject();
        }
    }

    static void updateAll(Context context) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        for (String type : TYPES) {
            ComponentName component = providerFor(context, type);
            int[] ids = manager.getAppWidgetIds(component);
            for (int widgetId : ids) update(context, manager, widgetId, type);
        }
        scheduleNextRefresh(context);
    }

    static void update(Context context, AppWidgetManager manager, int widgetId, String type) {
        JSONObject snapshot = readSnapshot(context);
        RemoteViews views;
        if (TODAY.equals(type) || TODOS.equals(type)) {
            views = buildList(context, widgetId, type, snapshot);
        } else if (OVERVIEW.equals(type)) {
            views = buildOverview(context, widgetId, snapshot);
        } else {
            views = buildGuide(context, widgetId, snapshot);
        }
        applySize(manager.getAppWidgetOptions(widgetId), views, type);
        manager.updateAppWidget(widgetId, views);
        if (TODAY.equals(type) || TODOS.equals(type)) manager.notifyAppWidgetViewDataChanged(widgetId, R.id.widget_list);
    }

    static void clearInstance(Context context, String type, int widgetId) {
        SharedPreferences.Editor editor = context.getSharedPreferences(WidgetPlugin.PREFS, Context.MODE_PRIVATE).edit();
        for (String suffix : new String[] { "phrase", "phrase_day", "phrase_mood" }) {
            editor.remove(suffix + "_" + type + "_" + widgetId);
        }
        editor.apply();
    }

    private static RemoteViews buildGuide(Context context, int widgetId, JSONObject snapshot) {
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_guide);
        EventSelection selection = selectEvents(snapshot, new Date());
        JSONObject main = selection.main;
        boolean active = selection.active;
        String date = main == null ? today() : main.optString("date", today());
        String mood = mood(snapshot, GUIDE, new Date());
        views.setTextViewText(R.id.widget_date, dateLabel(date));
        if (main == null) {
            views.setTextViewText(R.id.widget_status, noScheduleLabel(snapshot));
            boolean hasTerm = snapshot.optBoolean("hasCurrentTerm", false);
            views.setTextViewText(R.id.widget_course_title, hasTerm ? "本学期暂无后续课程" : snapshot.optBoolean("initialized", false) ? "先设置当前学期" : "课程数据尚未准备好");
            views.setTextViewText(R.id.widget_course_time, hasTerm ? "打开课序查看学期安排" : "打开课序后同步最近安排");
            views.setTextViewText(R.id.widget_course_room, "");
            views.setTextViewText(R.id.widget_course_hint, "");
        } else {
            views.setTextViewText(R.id.widget_status, active ? "正在上课 · 下课 " + main.optString("end", "") : "下一节 · " + dateLabel(date));
            views.setTextViewText(R.id.widget_course_title, main.optString("title", "课程"));
            views.setTextViewText(R.id.widget_course_time, main.optString("start", "") + " – " + main.optString("end", ""));
            String room = main.optString("room", "");
            views.setTextViewText(R.id.widget_course_room, room.isEmpty() || "null".equals(room) ? "地点未填写" : "⌖ " + room);
            JSONObject next = active ? selection.next : null;
            views.setTextViewText(R.id.widget_course_hint, next == null ? "" : "下一节  " + next.optString("start", "") + " · " + next.optString("title", "课程"));
        }
        views.setTextViewText(R.id.widget_quote, phrase(context, snapshot, GUIDE, mood, widgetId));
        applyTextColors(context, views, new int[] { R.id.widget_date, R.id.widget_status, R.id.widget_course_title, R.id.widget_course_time, R.id.widget_course_room, R.id.widget_course_hint, R.id.widget_quote });
        setLaunchClick(context, views, R.id.widget_root, main == null ? "/" : courseRoute(main));
        return views;
    }

    private static RemoteViews buildOverview(Context context, int widgetId, JSONObject snapshot) {
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_overview);
        EventSelection selection = selectEvents(snapshot, new Date());
        JSONObject main = selection.main;
        boolean active = selection.active;
        JSONObject todo = firstTodo(snapshot);
        String mood = mood(snapshot, OVERVIEW, new Date());
        views.setTextViewText(R.id.widget_date, todayLabel());
        views.setTextViewText(R.id.widget_class_label, main == null ? "課表" : active ? "正在上课" : "下一节课程");
        views.setTextViewText(R.id.widget_class_title, main == null ? "暂无课程安排" : main.optString("title", "课程"));
        views.setTextViewText(R.id.widget_class_detail, main == null ? "打开课序查看最近同步" : main.optString("start", "") + " – " + main.optString("end", "") + "  ·  " + displayRoom(main));
        views.setTextViewText(R.id.widget_todo_label, "待办速览");
        views.setTextViewText(R.id.widget_todo_title, todo == null ? "暂无未完成待办" : todo.optString("title", "待办"));
        views.setTextViewText(R.id.widget_todo_detail, todo == null ? "" : formatDue(todo.optString("dueAt", ""), todo.optBoolean("allDay", false)));
        views.setTextViewText(R.id.widget_quote, phrase(context, snapshot, OVERVIEW, mood, widgetId));
        applyTextColors(context, views, new int[] { R.id.widget_date, R.id.widget_class_label, R.id.widget_class_title, R.id.widget_class_detail, R.id.widget_todo_label, R.id.widget_todo_title, R.id.widget_todo_detail, R.id.widget_quote });
        setLaunchClick(context, views, R.id.widget_class_root, main == null ? "/" : courseRoute(main));
        setLaunchClick(context, views, R.id.widget_todo_root, todo == null ? "/todo" : "/todo/" + todo.optString("id", ""));
        setLaunchClick(context, views, R.id.widget_root, main != null ? courseRoute(main) : todo != null ? "/todo/" + todo.optString("id", "") : "/");
        return views;
    }

    private static RemoteViews buildList(Context context, int widgetId, String type, JSONObject snapshot) {
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_list);
        boolean todayList = TODAY.equals(type);
        String mood = mood(snapshot, type, new Date());
        views.setTextViewText(R.id.widget_list_title, todayList ? "今日课表" : "待办清单");
        views.setTextViewText(R.id.widget_date, todayLabel());
        views.setTextViewText(R.id.widget_quote, phrase(context, snapshot, type, mood, widgetId));
        JSONArray items = visibleItems(snapshot, todayList);
        String empty = !snapshot.optBoolean("initialized", false)
            ? "打开课序同步后，这里就有内容啦"
            : todayList && !snapshot.optBoolean("hasCurrentTerm", false)
                ? "先在课序设置当前学期"
                : todayList ? "今天没有课，出去透口气？" : "清单空了，快乐可以上岗。";
        views.setTextViewText(R.id.widget_empty, empty);
        views.setViewVisibility(R.id.widget_empty, items.length() == 0 ? android.view.View.VISIBLE : android.view.View.GONE);
        views.setViewVisibility(R.id.widget_list, items.length() == 0 ? android.view.View.GONE : android.view.View.VISIBLE);

        Intent service = new Intent(context, WidgetRemoteViewsService.class);
        service.putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId);
        service.putExtra(EXTRA_WIDGET_TYPE, type);
        service.setData(android.net.Uri.parse(service.toUri(Intent.URI_INTENT_SCHEME)));
        views.setRemoteAdapter(R.id.widget_list, service);
        views.setPendingIntentTemplate(R.id.widget_list, activityPendingIntent(context, widgetId, "/"));
        setLaunchClick(context, views, R.id.widget_root, todayList ? "/" : "/todo");
        return views;
    }

    private static JSONArray visibleItems(JSONObject snapshot, boolean todayList) {
        JSONArray source = snapshot.optJSONArray(todayList ? "events" : "todos");
        JSONArray result = new JSONArray();
        if (source == null) return result;
        if (todayList) {
            String date = today();
            for (int index = 0; index < source.length(); index++) {
                JSONObject event = source.optJSONObject(index);
                if (event != null && date.equals(event.optString("date"))) result.put(event);
            }
        } else {
            for (int index = 0; index < Math.min(5, source.length()); index++) {
                JSONObject todo = source.optJSONObject(index);
                if (todo != null) result.put(todo);
            }
        }
        return result;
    }

    private static JSONObject firstTodo(JSONObject snapshot) {
        JSONArray todos = snapshot.optJSONArray("todos");
        return todos == null || todos.length() == 0 ? null : todos.optJSONObject(0);
    }

    static String mood(JSONObject snapshot, String type, Date now) {
        if (!snapshot.optBoolean("initialized", false)) return "unavailable";
        if (!snapshot.optBoolean("hasCurrentTerm", false) && !TODOS.equals(type)) return "unavailable";
        String date = new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(now);
        String time = new SimpleDateFormat("HH:mm", Locale.US).format(now);
        JSONArray todos = snapshot.optJSONArray("todos");
        if (TODOS.equals(type)) {
            if (todos == null || todos.length() == 0) return "free";
            for (int i = 0; i < todos.length(); i++) {
                JSONObject todo = todos.optJSONObject(i);
                if (todo == null) continue;
                String dueAt = todo.optString("dueAt", "");
                if (!dueAt.isEmpty() && dueAt.substring(0, Math.min(10, dueAt.length())).compareTo(date) <= 0) return "urgent";
            }
            return "class";
        }
        JSONArray events = snapshot.optJSONArray("events");
        int remaining = 0;
        int todayCount = 0;
        if (events != null) {
            for (int i = 0; i < events.length(); i++) {
                JSONObject item = events.optJSONObject(i);
                if (item == null || !date.equals(item.optString("date"))) continue;
                todayCount++;
                if (item.optString("end", "").compareTo(time) > 0) remaining++;
            }
        }
        if (remaining >= 4) return "busy";
        if (remaining > 0) return "class";
        if (todos != null) {
            for (int i = 0; i < todos.length(); i++) {
                JSONObject todo = todos.optJSONObject(i);
                if (todo == null) continue;
                String dueAt = todo.optString("dueAt", "");
                if (!dueAt.isEmpty() && dueAt.substring(0, Math.min(10, dueAt.length())).compareTo(date) <= 0) return "urgent";
            }
        }
        return todayCount > 0 ? "done" : "free";
    }

    private static String phrase(Context context, JSONObject snapshot, String type, String mood, int widgetId) {
        JSONObject copy = snapshot.optJSONObject("copy");
        JSONArray options = copy == null ? null : copy.optJSONObject(mood) == null ? null : copy.optJSONObject(mood).optJSONArray(type);
        if (options == null || options.length() == 0) return "";
        SharedPreferences prefs = context.getSharedPreferences(WidgetPlugin.PREFS, Context.MODE_PRIVATE);
        String key = "phrase_" + type + "_" + widgetId;
        String dayKey = "phrase_day_" + type + "_" + widgetId;
        String moodKey = "phrase_mood_" + type + "_" + widgetId;
        String today = today();
        String current = prefs.getString(key, "");
        if (today.equals(prefs.getString(dayKey, "")) && mood.equals(prefs.getString(moodKey, "")) && contains(options, current)) return current;
        String previous = current;
        int selected = (int) (Math.random() * options.length());
        if (options.length() > 1) {
            for (int attempt = 0; attempt < 4 && previous.equals(options.optString(selected)); attempt++) {
                selected = (selected + 1 + (int) (Math.random() * (options.length() - 1))) % options.length();
            }
        }
        String phrase = options.optString(selected, "");
        prefs.edit().putString(key, phrase).putString(dayKey, today).putString(moodKey, mood).apply();
        return phrase;
    }

    private static boolean contains(JSONArray array, String value) {
        for (int i = 0; i < array.length(); i++) if (value.equals(array.optString(i))) return true;
        return false;
    }

    private static EventSelection selectEvents(JSONObject snapshot, Date now) {
        JSONArray events = snapshot.optJSONArray("events");
        EventSelection result = new EventSelection();
        if (events == null) return result;
        String date = new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(now);
        String time = new SimpleDateFormat("HH:mm", Locale.US).format(now);
        for (int i = 0; i < events.length(); i++) {
            JSONObject item = events.optJSONObject(i);
            if (item == null) continue;
            String itemDate = item.optString("date", "");
            String start = item.optString("start", "");
            String end = item.optString("end", "");
            if (itemDate.equals(date) && start.compareTo(time) <= 0 && end.compareTo(time) > 0) {
                result.main = item;
                result.active = true;
                break;
            }
        }
        if (result.main == null) {
            String nowKey = date + "T" + time;
            for (int i = 0; i < events.length(); i++) {
                JSONObject item = events.optJSONObject(i);
                if (item == null) continue;
                if ((item.optString("date") + "T" + item.optString("start")).compareTo(nowKey) >= 0) {
                    result.main = item;
                    break;
                }
            }
        }
        if (result.active) {
            String nowKey = date + "T" + time;
            for (int i = 0; i < events.length(); i++) {
                JSONObject item = events.optJSONObject(i);
                if (item != null && (item.optString("date") + "T" + item.optString("start")).compareTo(nowKey) > 0) {
                    result.next = item;
                    break;
                }
            }
        }
        return result;
    }

    private static void setLaunchClick(Context context, RemoteViews views, int viewId, String route) {
        views.setOnClickPendingIntent(viewId, activityPendingIntent(context, route.hashCode(), route));
    }

    private static void applySize(android.os.Bundle options, RemoteViews views, String type) {
        int width = options == null ? 240 : options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 240);
        int height = options == null ? 180 : options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 180);
        if (height < 155) views.setViewVisibility(R.id.widget_quote, android.view.View.GONE);
        if (GUIDE.equals(type)) {
            if (height < 132) views.setViewVisibility(R.id.widget_course_hint, android.view.View.GONE);
            if (width < 145) views.setViewVisibility(R.id.widget_course_room, android.view.View.GONE);
        } else if (OVERVIEW.equals(type)) {
            if (height < 140) views.setViewVisibility(R.id.widget_class_detail, android.view.View.GONE);
            if (height < 130) views.setViewVisibility(R.id.widget_todo_detail, android.view.View.GONE);
        }
    }

    private static PendingIntent activityPendingIntent(Context context, int requestCode, String route) {
        Intent intent = new Intent(context, MainActivity.class)
            .setAction("icu.savrc3.supercourse.WIDGET_OPEN." + requestCode)
            .putExtra("widgetRoute", route)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) flags |= PendingIntent.FLAG_IMMUTABLE;
        return PendingIntent.getActivity(context, requestCode, intent, flags);
    }

    private static ComponentName providerFor(Context context, String type) {
        if (TODAY.equals(type)) return new ComponentName(context, TodayWidgetProvider.class);
        if (OVERVIEW.equals(type)) return new ComponentName(context, OverviewWidgetProvider.class);
        if (TODOS.equals(type)) return new ComponentName(context, TodoWidgetProvider.class);
        return new ComponentName(context, NextClassWidgetProvider.class);
    }

    static void scheduleNextRefresh(Context context) {
        AlarmManager alarms = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        if (alarms == null) return;
        boolean hasAny = false;
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        for (String type : TYPES) hasAny |= manager.getAppWidgetIds(providerFor(context, type)).length > 0;
        Intent intent = new Intent(context, WidgetRefreshReceiver.class).setAction("icu.savrc3.supercourse.WIDGET_REFRESH");
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) flags |= PendingIntent.FLAG_IMMUTABLE;
        PendingIntent operation = PendingIntent.getBroadcast(context, 7203, intent, flags);
        if (!hasAny) {
            alarms.cancel(operation);
            return;
        }
        long now = System.currentTimeMillis();
        long[] nextHolder = { now + 30L * 60L * 1000L };
        Calendar midnight = Calendar.getInstance();
        midnight.add(Calendar.DAY_OF_YEAR, 1);
        midnight.set(Calendar.HOUR_OF_DAY, 0);
        midnight.set(Calendar.MINUTE, 1);
        midnight.set(Calendar.SECOND, 0);
        midnight.set(Calendar.MILLISECOND, 0);
        nextHolder[0] = Math.min(nextHolder[0], midnight.getTimeInMillis());
        JSONObject snapshot = readSnapshot(context);
        JSONArray events = snapshot.optJSONArray("events");
        if (events != null) {
            for (int i = 0; i < events.length(); i++) {
                JSONObject item = events.optJSONObject(i);
                if (item == null) continue;
                considerLocalTime(item.optString("date") + "T" + item.optString("start"), now, nextHolder);
                considerLocalTime(item.optString("date") + "T" + item.optString("end"), now, nextHolder);
            }
        }
        JSONArray todos = snapshot.optJSONArray("todos");
        if (todos != null) {
            for (int i = 0; i < todos.length(); i++) {
                JSONObject todo = todos.optJSONObject(i);
                if (todo == null) continue;
                String dueAt = todo.optString("dueAt", "");
                if (dueAt.length() >= 16) considerLocalTime(dueAt.substring(0, 16), now, nextHolder);
                else if (dueAt.length() >= 10) considerLocalTime(dueAt.substring(0, 10) + "T23:59", now, nextHolder);
            }
        }
        if (nextHolder[0] <= now) nextHolder[0] = now + 60_000L;
        if (Build.VERSION.SDK_INT >= 23) alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, nextHolder[0], operation);
        else alarms.set(AlarmManager.RTC_WAKEUP, nextHolder[0], operation);
    }

    private static void considerLocalTime(String value, long now, long[] nextHolder) {
        if (value == null || value.length() < 16) return;
        try {
            Date date = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm", Locale.US).parse(value.substring(0, 16));
            if (date != null && date.getTime() > now && date.getTime() < nextHolder[0]) nextHolder[0] = date.getTime();
        } catch (ParseException ignored) {
            // Invalid local dates are ignored; the 30-minute system update remains the fallback.
        }
    }

    static String formatDue(String dueAt, boolean allDay) {
        if (dueAt == null || dueAt.isEmpty()) return "无截止时间";
        String date = dueAt.length() >= 10 ? dueAt.substring(0, 10) : dueAt;
        if (allDay) return dateLabel(date) + " · 全天";
        return dueAt.length() >= 16 ? dateLabel(date) + " " + dueAt.substring(11, 16) : dateLabel(date);
    }

    static boolean isOverdue(String dueAt, boolean allDay) {
        if (dueAt == null || dueAt.isEmpty()) return false;
        Date now = new Date();
        if (allDay && dueAt.length() >= 10) {
            String today = new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(now);
            return dueAt.substring(0, 10).compareTo(today) < 0;
        }
        if (dueAt.length() < 16) return false;
        String pattern = dueAt.length() >= 19 ? "yyyy-MM-dd'T'HH:mm:ss" : "yyyy-MM-dd'T'HH:mm";
        try {
            Date due = new SimpleDateFormat(pattern, Locale.US).parse(dueAt.substring(0, pattern.endsWith("ss") ? 19 : 16));
            return due != null && due.before(now);
        } catch (ParseException ignored) {
            return false;
        }
    }

    static String today() { return new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date()); }
    private static String todayLabel() { return dateLabel(today()); }
    private static String dateLabel(String value) {
        if (value == null || value.length() < 10) return value == null ? "" : value;
        return value.substring(5, 7) + "月" + value.substring(8, 10) + "日";
    }
    private static String noScheduleLabel(JSONObject snapshot) {
        if (!snapshot.optBoolean("initialized", false)) return "最近同步";
        return snapshot.optBoolean("hasCurrentTerm", false) ? "学期安排" : "还没设置学期";
    }
    static String displayRoom(JSONObject event) {
        String room = event.optString("room", "");
        return room.isEmpty() || "null".equals(room) ? "地点未填写" : room;
    }
    private static String courseRoute(JSONObject event) { return "/courses/" + event.optString("courseId", "") + "?date=" + event.optString("date", ""); }
    private static void applyTextColors(Context context, RemoteViews views, int[] ids) {
        for (int id : ids) views.setTextColor(id, context.getColor(id == R.id.widget_quote || id == R.id.widget_date || id == R.id.widget_status || id == R.id.widget_class_label || id == R.id.widget_todo_label ? R.color.widget_secondary : R.color.widget_ink));
    }

    private static final class EventSelection {
        JSONObject main;
        JSONObject next;
        boolean active;
    }
}
