import os
from datetime import datetime
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


def estimate_query_size(collection, query):
    """Estimate the number of documents matching the query."""
    return collection.count_documents(query)
