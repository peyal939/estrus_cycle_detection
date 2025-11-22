import csv
import pytz
from datetime import datetime, timedelta
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import render
from downloader.utils import get_db_handle

class DownloadDataView(APIView):
    def get(self, request):
        date_str = request.GET.get('date')
        if not date_str:
            return Response({"error": "Date parameter is required (YYYY-MM-DD)"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Parse date string
            # User input date is in BST (Bangladesh Standard Time)
            bst_tz = pytz.timezone('Asia/Dhaka')
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            
            # Create start and end time in BST
            start_bst = bst_tz.localize(datetime.combine(date_obj, datetime.min.time()))
            end_bst = bst_tz.localize(datetime.combine(date_obj, datetime.max.time()))
            
            # Convert to UTC for MongoDB query
            start_utc = start_bst.astimezone(pytz.UTC)
            end_utc = end_bst.astimezone(pytz.UTC)

            db, client = get_db_handle()
            collection = db['iotdata']

            # Query MongoDB
            # The collection uses '"time"' as the time field
            cursor = collection.find({
                '"time"': {
                    '$gte': start_utc,
                    '$lte': end_utc
                }
            })

            # Prepare CSV response
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="harness_data_{date_str}.csv"'

            writer = csv.writer(response)
            # Columns as requested
            header = ["tagID", "C", "ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz", "amb", "obj", "soc", "time"]
            writer.writerow(header)

            for doc in cursor:
                # Convert time back to BST for CSV output? 
                # User said "time will be real date for mongo Bangladesh standard time"
                # It's better to show the time in BST in the CSV so it matches the requested date.
                
                time_utc = doc.get('"time"') # Access with quotes
                time_bst_str = ""
                if isinstance(time_utc, datetime):
                    # Ensure it is aware
                    if time_utc.tzinfo is None:
                        time_utc = pytz.UTC.localize(time_utc)
                    time_bst = time_utc.astimezone(bst_tz)
                    time_bst_str = time_bst.strftime('%Y-%m-%d %H:%M:%S')
                
                row = [
                    doc.get('tagID'),
                    doc.get('C'),
                    doc.get('ax'),
                    doc.get('ay'),
                    doc.get('az'),
                    doc.get('gx'),
                    doc.get('gy'),
                    doc.get('gz'),
                    doc.get('mx'),
                    doc.get('my'),
                    doc.get('mz'),
                    doc.get('amb'),
                    doc.get('obj'),
                    doc.get('soc'),
                    time_bst_str
                ]
                writer.writerow(row)

            return response

        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def index(request):
    return render(request, 'index.html')
