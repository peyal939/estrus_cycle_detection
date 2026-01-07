import os
from datetime import datetime
import pytz
from pymongo import MongoClient
from django.conf import settings

# Warning threshold for large dataset downloads
LARGE_DATASET_THRESHOLD = int(os.getenv("LARGE_DATASET_THRESHOLD", 100000))


def get_db_handle():
    client = MongoClient(os.getenv("MONGO_URI"))
    db = client["harnesstag"]
    return db, client


def get_distinct_tag_ids():
    """Get all distinct tagIDs from the iotdata collection."""
    db, client = get_db_handle()
    collection = db["iotdata"]
    try:
        tag_ids = collection.distinct("tagID")
        # Sort numerically if possible, otherwise alphabetically
        try:
            tag_ids = sorted(tag_ids, key=lambda x: int(x) if str(x).isdigit() else x)
        except (ValueError, TypeError):
            tag_ids = sorted(tag_ids, key=str)
        return tag_ids
    finally:
        client.close()


def generate_export_filename(tag_ids, start_datetime, end_datetime):
    """
    Generate filename for export based on tag IDs and datetime range.

    Format: tag_id<ID>_YYYY_MM_DD_HHMMSS_HHMMSS.csv
    Examples:
        - Single tag: tag_id1001_2025_12_01_090500_121000.csv
        - Multiple tags: tag_id1001-1002-1003_2025_12_01_090500_121000.csv
        - All tags: tag_idALL_2025_12_01_090500_121000.csv
    """
    # Format date and time parts
    date_str = start_datetime.strftime("%Y_%m_%d")
    start_time_str = start_datetime.strftime("%H%M%S")
    end_time_str = end_datetime.strftime("%H%M%S")

    # Format tag ID part
    if not tag_ids or len(tag_ids) == 0:
        tag_part = "ALL"
    elif len(tag_ids) == 1:
        tag_part = str(tag_ids[0])
    else:
        # Join multiple tags with hyphen
        tag_part = "-".join(
            str(t)
            for t in sorted(tag_ids, key=lambda x: int(x) if str(x).isdigit() else x)
        )

    return f"tag_id{tag_part}_{date_str}_{start_time_str}_{end_time_str}.csv"


def estimate_query_size(collection, query, max_count=None):
    """Estimate the number of documents matching the query.

    If max_count is provided, the count is capped by issuing a limited
    count query, which is much faster for large matches.
    """
    if max_count is not None:
        try:
            max_count_int = int(max_count)
            if max_count_int > 0:
                return collection.count_documents(query, limit=max_count_int)
        except Exception:
            pass

    return collection.count_documents(query)


def calculate_temperature_stats(start_utc, end_utc, tag_ids=None):
    """
    Calculate temperature statistics (variance, mean, std dev) for obj field.
    Filters out garbage data outside 30-50°C range.
    
    Args:
        start_utc: Start datetime in UTC
        end_utc: End datetime in UTC
        tag_ids: List of tag IDs to filter, None for all tags
    
    Returns:
        dict with keys: variance, mean, std_dev, count, valid_count, invalid_count, time_series
    """
    db, client = get_db_handle()
    collection = db["iotdata"]
    
    try:
        packet_match = {'"time"': {"$gte": start_utc, "$lte": end_utc}}

        # Add tag filtering if specified
        if tag_ids:
            if len(tag_ids) == 1:
                packet_match["tagID"] = tag_ids[0]
            else:
                packet_match["tagID"] = {"$in": tag_ids}

        # Count total samples (before temperature filtering)
        total_count_pipeline = [
            {"$match": packet_match},
            {"$unwind": "$sensorData"},
            {"$match": {"sensorData.obj": {"$exists": True, "$ne": None}}},
            {"$count": "count"},
        ]
        total_count_result = list(collection.aggregate(total_count_pipeline))
        total_count = total_count_result[0]["count"] if total_count_result else 0

        valid_match = {
            "sensorData.obj": {
                "$gte": 30,
                "$lte": 50,
                "$type": ["double", "int", "long", "decimal"],
            }
        }

        # MongoDB aggregation pipeline for statistics (per-sample)
        pipeline = [
            {"$match": packet_match},
            {"$unwind": "$sensorData"},
            {"$match": valid_match},
            {"$group": {
                "_id": None,
                "mean": {"$avg": "$sensorData.obj"},
                "stdDevPop": {"$stdDevPop": "$sensorData.obj"},
                "count": {"$sum": 1},
                "min": {"$min": "$sensorData.obj"},
                "max": {"$max": "$sensorData.obj"}
            }}
        ]
        
        result = list(collection.aggregate(pipeline))
        
        if not result or result[0]["count"] == 0:
            return {
                "variance": 0,
                "mean": 0,
                "std_dev": 0,
                "count": 0,
                "valid_count": 0,
                "invalid_count": total_count,
                "min": 0,
                "max": 0,
                "time_series": []
            }
        
        stats = result[0]
        std_dev = stats["stdDevPop"] if stats["stdDevPop"] is not None else 0
        variance = std_dev ** 2
        valid_count = stats["count"]
        invalid_count = total_count - valid_count
        
        # Get time series data for visualization (hourly aggregates)
        # Use sample_time = packet_time + sensorData.millis (ms)
        time_series_pipeline = [
            {"$match": packet_match},
            {"$unwind": "$sensorData"},
            {"$match": valid_match},
            {"$addFields": {
                "sample_time": {
                    "$dateAdd": {
                        "startDate": "$\"time\"",
                        "unit": "millisecond",
                        "amount": {"$ifNull": ["$sensorData.millis", 0]},
                    }
                }
            }},
            {"$sort": {"sample_time": 1}},
            {"$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m-%d %H:00:00",
                        "date": "$sample_time",
                        "timezone": "Asia/Dhaka"
                    }
                },
                "avg_temp": {"$avg": "$sensorData.obj"},
                "min_temp": {"$min": "$sensorData.obj"},
                "max_temp": {"$max": "$sensorData.obj"},
                "count": {"$sum": 1}
            }},
            {"$sort": {"_id": 1}},
            {"$limit": 1000}  # Limit to 1000 data points for performance
        ]
        
        time_series_result = list(collection.aggregate(time_series_pipeline))
        time_series = [
            {
                "time": item["_id"],
                "avg": round(item["avg_temp"], 2),
                "min": round(item["min_temp"], 2),
                "max": round(item["max_temp"], 2),
                "count": item["count"]
            }
            for item in time_series_result
        ]
        
        return {
            "variance": round(variance, 4),
            "mean": round(stats["mean"], 2),
            "std_dev": round(std_dev, 2),
            "count": total_count,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "min": round(stats["min"], 2),
            "max": round(stats["max"], 2),
            "time_series": time_series
        }
    
    finally:
        client.close()
