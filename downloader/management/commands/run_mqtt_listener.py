import json
import os
import pytz
from datetime import datetime, timezone
from django.core.management.base import BaseCommand
import paho.mqtt.client as mqtt
from downloader.utils import get_db_handle

class Command(BaseCommand):
    help = 'Listen to MQTT topic and save data to MongoDB'

    def handle(self, *args, **options):
        mongo_uri = os.getenv('MONGO_URI')
        mqtt_broker = os.getenv('MQTT_BROKER')
        mqtt_port = int(os.getenv('MQTT_PORT'))
        mqtt_topic = os.getenv('MQTT_TOPIC')
        mqtt_user = os.getenv('MQTT_USER')
        mqtt_pass = os.getenv('MQTT_PASS')

        db, client = get_db_handle()
        collection = db['iotdata']

        # Ensure collection is time-series
        # Note: existing collections cannot be converted to time-series easily if they contain data.
        # We assume the user created it as time-series or we just insert.
        # If it doesn't exist, we can try to create it explicitly, but usually auto-creation works for normal collections.
        # For time-series, explicit creation is better, but user said "i have created a database called harnesstag collection is iotdata made it time sereis".
        # So we assume it exists.

        def on_connect(client, userdata, flags, rc):
            self.stdout.write(self.style.SUCCESS(f'Connected with result code {rc}'))
            client.subscribe(mqtt_topic)

        def on_message(client, userdata, msg):
            try:
                payload = msg.payload.decode('utf-8')
                # self.stdout.write(f"Received payload: {payload}") 
                data = json.loads(payload)
                
                # Convert timestamp to datetime
                timestamp = data.get('time')
                
                if timestamp is not None:
                    try:
                        timestamp = float(timestamp)
                        
                        # The device sends a timestamp that corresponds to local time (BST) but as a UTC timestamp.
                        # e.g. It sends a timestamp for 11:54 UTC when it means 11:54 BST.
                        # We need to capture this "face value" and treat it as BST.
                        
                        bst_tz = pytz.timezone('Asia/Dhaka')
                        
                        # 1. Get the face value time (naive) from the timestamp
                        dt_naive = datetime.fromtimestamp(timestamp, timezone.utc).replace(tzinfo=None)
                        
                        # 2. Localize it as BST
                        dt_bst = bst_tz.localize(dt_naive)
                        
                        # 3. Convert to real UTC for storage
                        dt_utc = dt_bst.astimezone(timezone.utc)
                        
                        # The MongoDB collection was created with timeField='"time"' (quoted).
                        # So we must use the key '"time"' instead of 'time'.
                        data['"time"'] = dt_utc
                        if 'time' in data:
                            del data['time'] # Remove the original key to avoid confusion/duplication
                        
                        # Insert into MongoDB
                        collection.insert_one(data)
                        self.stdout.write(self.style.SUCCESS(f"Inserted data for tag {data.get('tagID')} at {data.get('\"time\"')}"))
                    except ValueError:
                        self.stderr.write(self.style.ERROR(f"Invalid timestamp format: {timestamp}"))
                    except Exception as insert_error:
                         self.stderr.write(self.style.ERROR(f"Insert failed: {insert_error} | Data: {data}"))
                else:
                    self.stderr.write(self.style.ERROR(f"Missing 'time' field in payload: {payload}"))
                
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error processing message: {e}"))

        client = mqtt.Client()
        client.username_pw_set(mqtt_user, mqtt_pass)
        client.on_connect = on_connect
        client.on_message = on_message

        self.stdout.write(f"Connecting to broker {mqtt_broker}...")
        client.connect(mqtt_broker, mqtt_port, 60)

        try:
            client.loop_forever()
        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS("Stopped MQTT listener"))
