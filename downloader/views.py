import csv
import pytz
from datetime import datetime, timedelta, time
from django.http import HttpResponse, JsonResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import render
from downloader.utils import (
    get_db_handle,
    get_distinct_tag_ids,
    generate_export_filename,
    estimate_query_size,
    LARGE_DATASET_THRESHOLD,
)

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin


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
            cursor = collection.find({'"time"': {"$gte": start_utc, "$lte": end_utc}})

            # Prepare CSV response
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = (
                f'attachment; filename="harness_data_{start_date_str}_to_{end_date_str}.csv"'
            )

            writer = csv.writer(response)
            # Columns as requested
            header = [
                "tagID",
                "C",
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
                "time",
            ]
            writer.writerow(header)

            for doc in cursor:
                # Convert time back to BST for CSV output?
                # User said "time will be real date for mongo Bangladesh standard time"
                # It's better to show the time in BST in the CSV so it matches the requested date.

                time_utc = doc.get('"time"')  # Access with quotes
                time_bst_str = ""
                if isinstance(time_utc, datetime):
                    # Ensure it is aware
                    if time_utc.tzinfo is None:
                        time_utc = pytz.UTC.localize(time_utc)
                    time_bst = time_utc.astimezone(bst_tz)
                    time_bst_str = time_bst.strftime("%Y-%m-%d %H:%M:%S")

                row = [
                    doc.get("tagID"),
                    doc.get("C"),
                    doc.get("ax"),
                    doc.get("ay"),
                    doc.get("az"),
                    doc.get("gx"),
                    doc.get("gy"),
                    doc.get("gz"),
                    doc.get("mx"),
                    doc.get("my"),
                    doc.get("mz"),
                    doc.get("amb"),
                    doc.get("obj"),
                    doc.get("soc"),
                    time_bst_str,
                ]
                writer.writerow(row)

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
                doc_count = estimate_query_size(collection, query)
                if doc_count > LARGE_DATASET_THRESHOLD:
                    return JsonResponse(
                        {
                            "warning": True,
                            "message": f"This query will download approximately {doc_count:,} records. This may take a while.",
                            "count": doc_count,
                            "threshold": LARGE_DATASET_THRESHOLD,
                        }
                    )

            # Execute query
            cursor = collection.find(query)

            # Generate filename
            filename = generate_export_filename(tag_ids, start_bst, end_bst)

            # Prepare CSV response
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'

            writer = csv.writer(response)
            header = [
                "tagID",
                "C",
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
                "time",
            ]
            writer.writerow(header)

            for doc in cursor:
                # Convert time back to BST for CSV output
                time_utc = doc.get('"time"')
                time_bst_str = ""
                if isinstance(time_utc, datetime):
                    if time_utc.tzinfo is None:
                        time_utc = pytz.UTC.localize(time_utc)
                    time_bst = time_utc.astimezone(bst_tz)
                    # Full seconds accuracy in timestamp
                    time_bst_str = time_bst.strftime("%Y-%m-%d %H:%M:%S")

                row = [
                    doc.get("tagID"),
                    doc.get("C"),
                    doc.get("ax"),
                    doc.get("ay"),
                    doc.get("az"),
                    doc.get("gx"),
                    doc.get("gy"),
                    doc.get("gz"),
                    doc.get("mx"),
                    doc.get("my"),
                    doc.get("mz"),
                    doc.get("amb"),
                    doc.get("obj"),
                    doc.get("soc"),
                    time_bst_str,
                ]
                writer.writerow(row)

            client.close()
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
