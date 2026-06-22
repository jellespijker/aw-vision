"""Aggregate analytics: processing-time stats, per-project hours and binned timelines."""
import os
import time
from pathlib import Path
from typing import Optional

import lancedb
import pyarrow as pa
import requests

from aw_vision.config import config


class AnalyticsMixin:
    def get_processing_stats(self) -> dict:
        """Query all records and calculate mean, min, and max processing times for each phase."""
        try:
            tbl = self.table
            # Select only the duration fields to maximize query execution performance
            records = tbl.search().select(["duration_ocr", "duration_vision", "duration_embedding", "duration_total"]).limit(100000).to_list()
        except Exception as e:
            print(f"Error loading records for processing stats: {e}")
            return {}

        ocr_times = []
        vision_times = []
        emb_times = []
        total_times = []

        for r in records:
            ocr_val = r.get("duration_ocr")
            # Only count active model executions (greater than 0.0s) to keep stats mathematically accurate
            if ocr_val is not None and ocr_val > 0.0:
                ocr_times.append(ocr_val)

            vis_val = r.get("duration_vision")
            if vis_val is not None and vis_val > 0.0:
                vision_times.append(vis_val)

            emb_val = r.get("duration_embedding")
            if emb_val is not None and emb_val > 0.0:
                emb_times.append(emb_val)

            tot_val = r.get("duration_total")
            if tot_val is not None and tot_val > 0.0:
                total_times.append(tot_val)

        def calc_stats(times):
            if not times:
                return {"mean": 0.0, "min": 0.0, "max": 0.0, "count": 0}
            return {
                "mean": round(sum(times) / len(times), 2),
                "min": round(min(times), 2),
                "max": round(max(times), 2),
                "count": len(times)
            }

        return {
            "ocr": calc_stats(ocr_times),
            "vision": calc_stats(vision_times),
            "embedding": calc_stats(emb_times),
            "total": calc_stats(total_times),
        }

    def get_project_statistics(self) -> dict:
        """Aggregate total counted hours per project.

        Assumes each screenshot represents config.screenshot_interval seconds of active work.
        """
        try:
            records = self.get_all_records(limit=10000)
        except Exception:
            return {}

        stats = {}
        interval_hours = config.screenshot_interval / 3600.0

        for r in records:
            p_num = r.get("project_number")
            if not p_num:
                p_num = "None"

            # Count only if user wasn't AFK
            if r.get("is_afk"):
                continue

            stats[p_num] = stats.get(p_num, 0.0) + interval_hours

        return stats

    def get_binned_timeline(self, start_time: float, end_time: float, resolution_seconds: float) -> dict:
        """Query and aggregate active screenshot durations binned by resolution_seconds.

        Returns:
            dict mapping project_number to a list of dicts containing binned times.
        """
        try:
            where_clause = f"timestamp >= {start_time} AND timestamp <= {end_time}"
            records = self.query_metadata(where_clause, limit=100000)
        except Exception as e:
            print(f"Error querying binned timeline metadata: {e}")
            records = []

        # Align bins to multiples of resolution_seconds
        aligned_start = (start_time // resolution_seconds) * resolution_seconds

        # Determine number of bins, cap at 5000 for safety
        if resolution_seconds <= 0:
            resolution_seconds = 3600.0

        num_bins = int((end_time - aligned_start) // resolution_seconds) + 1
        if num_bins > 5000:
            num_bins = 5000

        # Get configured project numbers and Unclassified
        try:
            projects_list = config.load_projects()
            project_numbers = [p["project_number"] for p in projects_list] + ["Unclassified"]
        except Exception:
            project_numbers = ["Unclassified"]

        bins_by_project = {p_num: [0.0] * num_bins for p_num in project_numbers}
        interval_seconds = config.screenshot_interval

        for r in records:
            # Skip if user was AFK
            if r.get("is_afk"):
                continue

            p_num = r.get("project_number")
            if not p_num or p_num.strip() == "" or p_num.lower() == "none":
                p_num = "Unclassified"

            ts = r.get("timestamp")
            if ts < aligned_start:
                continue

            bin_idx = int((ts - aligned_start) // resolution_seconds)
            if 0 <= bin_idx < num_bins:
                if p_num not in bins_by_project:
                    bins_by_project[p_num] = [0.0] * num_bins
                bins_by_project[p_num][bin_idx] += interval_seconds

        # Format results for the frontend
        result = {}
        for p_num, durations in bins_by_project.items():
            project_bins = []
            for idx, dur in enumerate(durations):
                b_start = aligned_start + idx * resolution_seconds
                b_end = b_start + resolution_seconds
                dur_capped = min(dur, resolution_seconds)
                project_bins.append({
                    "start_time": b_start,
                    "end_time": b_end,
                    "duration_seconds": round(dur_capped, 1)
                })
            result[p_num] = project_bins

        return {
            "aligned_start": aligned_start,
            "resolution_seconds": resolution_seconds,
            "num_bins": num_bins,
            "projects": result
        }
