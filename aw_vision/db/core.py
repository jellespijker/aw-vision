"""VisionDB: composes the focused database mixins into a single facade object."""
from aw_vision.config import config
from aw_vision.db.schema import SchemaMixin
from aw_vision.db.screenshots import ScreenshotsMixin
from aw_vision.db.analytics import AnalyticsMixin
from aw_vision.db.projects import ProjectsMixin
from aw_vision.db.reembedding import ReembeddingMixin


class VisionDB(SchemaMixin, ScreenshotsMixin, AnalyticsMixin, ProjectsMixin, ReembeddingMixin):
    def __init__(self):
        self.db_dir = config.db_dir
        self._db = None
        self._table = None
        self.table_name = "screenshots"
        self.projects_table_name = "projects"
        self._projects_table = None
        # Memoize embedding dimension per provider/model to avoid probing Ollama on every embed call.
        self._dim_cache = {}
        # Short-lived cache of unique tags to avoid full-table scans during batch processing.
        self._tags_cache = None
        self._tags_cache_time = 0.0
        self._tags_cache_ttl = 120.0
        self._reembedding_status = {
            "is_running": False,
            "total_records": 0,
            "processed_records": 0,
            "error": None,
            "current_model": ""
        }
