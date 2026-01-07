import csv
import pytz
from datetime import datetime, timedelta, time
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import render
import os
from downloader.utils import (
    get_db_handle,
    get_distinct_tag_ids,
    generate_export_filename,
    estimate_query_size,
    calculate_temperature_stats,
    LARGE_DATASET_THRESHOLD,
)

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin


class _Echo:
    def write(self, value):
        return value


def _iter_docs_in_time_chunks(collection, base_query, start_utc, end_utc, projection):
    """Iterate matching documents using short-lived cursors.

    Some MongoDB Atlas tiers disallow no-timeout cursors; chunking keeps each
    cursor alive for a shorter time while still streaming a single CSV.
    """
    chunk_seconds = int(os.getenv("EXPORT_CHUNK_SECONDS", "3600"))
    if chunk_seconds < 1:
        chunk_seconds = 3600

    base_query = dict(base_query)
    base_query.pop('"time"', None)

    current = start_utc
    while current < end_utc:
        next_end = min(current + timedelta(seconds=chunk_seconds), end_utc)
        chunk_query = dict(base_query)
        if next_end == end_utc:
            chunk_query['"time"'] = {"$gte": current, "$lte": end_utc}
        else:
            chunk_query['"time"'] = {"$gte": current, "$lt": next_end}

        cursor = (
            collection.find(chunk_query, projection=projection)
            .sort([('"time"', 1), ("_id", 1)])
            .batch_size(500)
        )
        try:
            for doc in cursor:
                yield doc
        finally:
            cursor.close()

        current = next_end


class DownloadDataView(LoginRequiredMixin, APIView):
    def get(self, request):
        start_date_str = request.GET.get("start_date")
        end_date_str = request.GET.get("end_date")

        if not start_date_str or not end_date_str:
            return Response(
                {
                    "error": "Both start_date and end_date parameters are required (YYYY-MM-DD)"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Parse date strings
            # User input date is in BST (Bangladesh Standard Time)
            bst_tz = pytz.timezone("Asia/Dhaka")
            start_date_obj = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date_obj = datetime.strptime(end_date_str, "%Y-%m-%d")

            # Create start and end time in BST
            # Start from 00:00:00 of start_date
            start_bst = bst_tz.localize(
                datetime.combine(start_date_obj, datetime.min.time())
            )
            # End at 23:59:59 of end_date
            end_bst = bst_tz.localize(
                datetime.combine(end_date_obj, datetime.max.time())
            )

            # Convert to UTC for MongoDB query
            start_utc = start_bst.astimezone(pytz.UTC)
            end_utc = end_bst.astimezone(pytz.UTC)

            db, client = get_db_handle()
            collection = db["iotdata"]

            # Query MongoDB
            # The collection uses '"time"' as the time field
            query = {'"time"': {"$gte": start_utc, "$lte": end_utc}}
            projection = {"_id": 1, "tagID": 1, '"time"': 1, "time": 1, "sensorData": 1}
            docs_iter = _iter_docs_in_time_chunks(
                collection, query, start_utc, end_utc, projection
            )

            sensor_fields = [
                "ax",
                "ay",
                "az",
                "gx",
                "gy",
                "gz",
                "mx",
                "my",
                "mz",
                "amb",
                "obj",
                "soc",
            ]
            header = ["packet_id", "tagID", "time", "time_epoch", "millis", *sensor_fields]

            def row_iter():
                pseudo_buffer = _Echo()
                writer = csv.writer(pseudo_buffer)
                try:
                    yield writer.writerow(header)

                    for doc in docs_iter:
                        # Convert time back to BST for CSV output
                        time_utc = doc.get('"time"')  # Access with quotes
                        time_epoch = doc.get("time")

                        time_bst_str = ""
                        if isinstance(time_utc, datetime):
                            if time_utc.tzinfo is None:
                                time_utc = pytz.UTC.localize(time_utc)
                            time_bst = time_utc.astimezone(bst_tz)
                            time_bst_str = time_bst.strftime("%Y-%m-%d %H:%M:%S")
                            if time_epoch is None:
                                try:
                                    offset_seconds = int(time_bst.utcoffset().total_seconds())
                                    time_epoch = int(round(time_utc.timestamp() + offset_seconds))
                                except Exception:
                                    time_epoch = None
                        elif time_epoch is not None:
                            try:
                                timestamp = float(time_epoch)
                                dt_naive = datetime.fromtimestamp(timestamp, pytz.UTC).replace(
                                    tzinfo=None
                                )
                                dt_bst = bst_tz.localize(dt_naive)
                                time_bst_str = dt_bst.strftime("%Y-%m-%d %H:%M:%S")
                            except Exception:
                                time_bst_str = ""

                        sensor_data = doc.get("sensorData")
                        if not isinstance(sensor_data, list) or not sensor_data:
                            continue

                        packet_id = str(doc.get("_id", ""))
                        tag_id = doc.get("tagID")

                        for sample in sensor_data:
                            if not isinstance(sample, dict):
                                continue
                            row = [
                                packet_id,
                                tag_id,
                                time_bst_str,
                                time_epoch,
                                sample.get("millis"),
                                *[sample.get(field) for field in sensor_fields],
                            ]
                            yield writer.writerow(row)
                finally:
                    client.close()

            response = StreamingHttpResponse(row_iter(), content_type="text/csv")
            response["Content-Disposition"] = (
                f'attachment; filename="harness_data_{start_date_str}_to_{end_date_str}.csv"'
            )
            return response

        except ValueError:
            return Response(
                {"error": "Invalid date format. Use YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DatasetExporterView(LoginRequiredMixin, APIView):
    """
    Dataset Exporter with tagID filtering, time range support, and large dataset warnings.

    Query Parameters:
        - start_date (required): Start date in YYYY-MM-DD format
        - end_date (optional): End date in YYYY-MM-DD format, defaults to start_date
        - start_time (optional): Start time in HH:MM:SS format, defaults to 00:00:00
        - end_time (optional): End time in HH:MM:SS format, defaults to 23:59:59
        - tag_ids (optional): Comma-separated list of tag IDs, empty means all tags
        - confirm (optional): Set to 'true' to bypass large dataset warning
    """

    def get(self, request):
        # Get parameters
        start_date_str = request.GET.get("start_date")
        end_date_str = request.GET.get("end_date")
        start_time_str = request.GET.get("start_time", "00:00:00")
        end_time_str = request.GET.get("end_time", "23:59:59")
        tag_ids_str = request.GET.get("tag_ids", "")
        confirm_large = request.GET.get("confirm", "false").lower() == "true"

        # Validate required fields
        if not start_date_str:
            return Response(
                {"error": "start_date is required (YYYY-MM-DD)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Parse dates
            bst_tz = pytz.timezone("Asia/Dhaka")
            start_date_obj = datetime.strptime(start_date_str, "%Y-%m-%d")

            # Default end_date to start_date if not provided
            if not end_date_str:
                end_date_str = start_date_str
            end_date_obj = datetime.strptime(end_date_str, "%Y-%m-%d")

            # Parse times (default to full day if not provided)
            try:
                start_time_obj = datetime.strptime(start_time_str, "%H:%M:%S").time()
            except ValueError:
                start_time_obj = time(0, 0, 0)

            try:
                end_time_obj = datetime.strptime(end_time_str, "%H:%M:%S").time()
            except ValueError:
                end_time_obj = time(23, 59, 59)

            # Combine date and time
            start_datetime = datetime.combine(start_date_obj, start_time_obj)
            end_datetime = datetime.combine(end_date_obj, end_time_obj)

            # Localize to BST and convert to UTC for MongoDB query
            start_bst = bst_tz.localize(start_datetime)
            end_bst = bst_tz.localize(end_datetime)
            start_utc = start_bst.astimezone(pytz.UTC)
            end_utc = end_bst.astimezone(pytz.UTC)

            # Parse tag IDs
            tag_ids = []
            if tag_ids_str:
                tag_ids = [t.strip() for t in tag_ids_str.split(",") if t.strip()]
                # Convert to integers if they are numeric
                parsed_tag_ids = []
                for t in tag_ids:
                    try:
                        parsed_tag_ids.append(int(t))
                    except ValueError:
                        parsed_tag_ids.append(t)
                tag_ids = parsed_tag_ids

            # Build MongoDB query
            query = {'"time"': {"$gte": start_utc, "$lte": end_utc}}

            # Add tag filter if tags are selected
            if tag_ids:
                if len(tag_ids) == 1:
                    query["tagID"] = tag_ids[0]
                else:
                    query["tagID"] = {"$in": tag_ids}

            db, client = get_db_handle()
            collection = db["iotdata"]

            # Check dataset size and warn if large
            if not confirm_large:
                doc_count = estimate_query_size(
                    collection, query, max_count=LARGE_DATASET_THRESHOLD + 1
                )
                if doc_count > LARGE_DATASET_THRESHOLD:
                    return JsonResponse(
                        {
                            "warning": True,
                            "message": f"This query will download more than {LARGE_DATASET_THRESHOLD:,} records. This may take a while.",
                            "count": doc_count,
                            "threshold": LARGE_DATASET_THRESHOLD,
                        }
                    )

            # Execute query
            projection = {"_id": 1, "tagID": 1, '"time"': 1, "time": 1, "sensorData": 1}
            docs_iter = _iter_docs_in_time_chunks(
                collection, query, start_utc, end_utc, projection
            )

            # Generate filename
            filename = generate_export_filename(tag_ids, start_bst, end_bst)

            sensor_fields = [
                "ax",
                "ay",
                "az",
                "gx",
                "gy",
                "gz",
                "mx",
                "my",
                "mz",
                "amb",
                "obj",
                "soc",
            ]
            header = ["packet_id", "tagID", "time", "time_epoch", "millis", *sensor_fields]

            def row_iter():
                pseudo_buffer = _Echo()
                writer = csv.writer(pseudo_buffer)
                try:
                    yield writer.writerow(header)

                    for doc in docs_iter:
                        time_utc = doc.get('"time"')
                        time_epoch = doc.get("time")

                        time_bst_str = ""
                        if isinstance(time_utc, datetime):
                            if time_utc.tzinfo is None:
                                time_utc = pytz.UTC.localize(time_utc)
                            time_bst = time_utc.astimezone(bst_tz)
                            time_bst_str = time_bst.strftime("%Y-%m-%d %H:%M:%S")
                            if time_epoch is None:
                                try:
                                    offset_seconds = int(time_bst.utcoffset().total_seconds())
                                    time_epoch = int(round(time_utc.timestamp() + offset_seconds))
                                except Exception:
                                    time_epoch = None
                        elif time_epoch is not None:
                            try:
                                timestamp = float(time_epoch)
                                dt_naive = datetime.fromtimestamp(timestamp, pytz.UTC).replace(
                                    tzinfo=None
                                )
                                dt_bst = bst_tz.localize(dt_naive)
                                time_bst_str = dt_bst.strftime("%Y-%m-%d %H:%M:%S")
                            except Exception:
                                time_bst_str = ""

                        sensor_data = doc.get("sensorData")
                        if not isinstance(sensor_data, list) or not sensor_data:
                            continue

                        packet_id = str(doc.get("_id", ""))
                        tag_id = doc.get("tagID")

                        for sample in sensor_data:
                            if not isinstance(sample, dict):
                                continue
                            row = [
                                packet_id,
                                tag_id,
                                time_bst_str,
                                time_epoch,
                                sample.get("millis"),
                                *[sample.get(field) for field in sensor_fields],
                            ]
                            yield writer.writerow(row)
                finally:
                    client.close()

            response = StreamingHttpResponse(row_iter(), content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response

        except ValueError as e:
            return Response(
                {"error": f"Invalid date/time format: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@login_required
def index(request):
    # Get distinct tag IDs for the dropdown
    tag_ids = get_distinct_tag_ids()
    context = {"tag_ids": tag_ids}
    return render(request, "index.html", context)


@login_required
def dashboard(request):
    """Dashboard view for temperature variance visualization."""
    tag_ids = get_distinct_tag_ids()
    context = {"tag_ids": tag_ids}
    return render(request, "dashboard.html", context)


class TemperatureVarianceView(LoginRequiredMixin, APIView):
    """
    API endpoint for temperature variance statistics.
    
    Query Parameters:
        - start_date (required): Start date in YYYY-MM-DD format
        - end_date (optional): End date in YYYY-MM-DD format, defaults to start_date
        - start_time (optional): Start time in HH:MM:SS format, defaults to 00:00:00
        - end_time (optional): End time in HH:MM:SS format, defaults to 23:59:59
        - tag_ids (optional): Comma-separated list of tag IDs, empty means all tags
    
    Returns:
        JSON with temperature statistics including variance, mean, std_dev, and time series data.
        Only includes temperatures in the valid range (30-50°C).
    """
    
    def get(self, request):
        # Get parameters
        start_date_str = request.GET.get("start_date")
        end_date_str = request.GET.get("end_date", start_date_str)
        start_time_str = request.GET.get("start_time", "00:00:00")
        end_time_str = request.GET.get("end_time", "23:59:59")
        tag_ids_str = request.GET.get("tag_ids", "")
        
        if not start_date_str:
            return Response(
                {"error": "start_date parameter is required (YYYY-MM-DD)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        try:
            # Parse dates and times
            bst_tz = pytz.timezone("Asia/Dhaka")
            start_date_obj = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date_obj = datetime.strptime(end_date_str, "%Y-%m-%d")
            start_time_obj = datetime.strptime(start_time_str, "%H:%M:%S").time()
            end_time_obj = datetime.strptime(end_time_str, "%H:%M:%S").time()
            
            # Create datetime objects in BST
            start_datetime = datetime.combine(start_date_obj, start_time_obj)
            end_datetime = datetime.combine(end_date_obj, end_time_obj)
            
            start_bst = bst_tz.localize(start_datetime)
            end_bst = bst_tz.localize(end_datetime)
            
            # Convert to UTC
            start_utc = start_bst.astimezone(pytz.UTC)
            end_utc = end_bst.astimezone(pytz.UTC)
            
            # Parse tag IDs
            tag_ids = None
            if tag_ids_str:
                try:
                    tag_ids = [int(tid.strip()) for tid in tag_ids_str.split(",") if tid.strip()]
                except ValueError:
                    return Response(
                        {"error": "Invalid tag_ids format. Use comma-separated integers."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            
            # Calculate statistics
            stats = calculate_temperature_stats(start_utc, end_utc, tag_ids)
            
            return Response(stats, status=status.HTTP_200_OK)
            
        except ValueError as e:
            return Response(
                {"error": f"Invalid date/time format: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
