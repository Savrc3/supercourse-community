package icu.savrc3.supercourse.widgets;

import android.content.Context;
import android.widget.FrameLayout;
import android.widget.RemoteViews;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Runs the same RemoteViews inflation/filter used by the launcher, on a real Android runtime. */
@RunWith(AndroidJUnit4.class)
public class WidgetRemoteViewsTest {
    @Test public void guideInflates() { assertInflates("widget_guide"); }
    @Test public void listInflates() { assertInflates("widget_list"); }
    @Test public void overviewInflates() { assertInflates("widget_overview"); }
    @Test public void listRowInflates() { assertInflates("widget_list_row"); }
    @Test public void todayPreviewInflates() { assertInflates("widget_today_preview"); }
    @Test public void todosPreviewInflates() { assertInflates("widget_todos_preview"); }

    private void assertInflates(String layoutName) {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        int layoutId = context.getResources().getIdentifier(layoutName, "layout", context.getPackageName());
        if (layoutId == 0) throw new AssertionError("Missing widget layout: " + layoutName);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(() -> {
            try {
                new RemoteViews(context.getPackageName(), layoutId).apply(context, new FrameLayout(context));
            } catch (Throwable error) {
                failure.set(error);
            }
        });
        if (failure.get() != null) throw new AssertionError(layoutName + " cannot render as RemoteViews", failure.get());
    }
}
