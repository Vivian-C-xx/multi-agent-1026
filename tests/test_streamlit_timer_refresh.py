import inspect
import unittest

import streamlit_app


class StreamlitTimerRefreshTest(unittest.TestCase):
    def test_running_timer_does_not_force_secondly_page_reruns(self):
        source = inspect.getsource(streamlit_app.maybe_refresh_running_timer)
        self.assertNotIn("time.sleep", source)
        self.assertNotIn("remaining > 0", source)

    def test_countdown_updates_in_browser_without_streamlit_rerun(self):
        source = inspect.getsource(streamlit_app.render_browser_countdown)
        self.assertIn("setInterval", source)
        self.assertIn("target.textContent", source)
        self.assertNotIn("st.rerun", source)


if __name__ == "__main__":
    unittest.main()
